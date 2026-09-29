"""Step 11 — "WP selects a destination Office" foundation.

Deliberately NOT a WhatsApp menu/interactive-message engine: this
codebase has no interactive-list/button message support anywhere
(`apps.webhooks.parsing.SUPPORTED_EVENT_TYPES == {'message'}` — only
plain text messages have ever been parsed) and building one is out of
this step's scope ("Jangan membuat sistem interactive-message baru",
"Jangan mengganti engine WAHA/GOWS"). This module only answers the two
questions a future WhatsApp-menu integration would need:

  1. Which Offices may currently be offered to a WP as a destination?
  2. Given a WP's chosen Office ID, is it still valid, and if so, what
     Office should this Chat be routed to?

Both re-derive the answer from the database on every call — never from a
previously-sent list — so a race (Office/Inbox disabled between the menu
being sent and the WP's reply) is handled for free (docs Section 8).

Deliberately distinct from `WahaSession.office` (the session/channel ->
Office mapping, Step 9): that field is never read or written here. A
WP's destination choice is a separate, explicit, per-Chat routing
decision — this only ever writes `Chat.office`, never
`WahaSession.office`.
"""

import logging

from apps.blast.bff_client import BffDispatchError, send_blast_message
from apps.chats.models import Chat
from apps.offices.models import Office
from apps.waha_sessions.models import WahaSession

logger = logging.getLogger(__name__)

OFFICE_NOT_FOUND = 'office_not_found'
OFFICE_UNAVAILABLE = 'office_unavailable'

# Step 12 — plain-text WhatsApp Office-selection flow. Deliberate design
# decision (approved): the number a WP replies with is the Office's own
# database ID (shown next to its name in the menu), NOT a re-numbered
# 1..N position. This is what lets `select_office_for_chat()` (above)
# remain the ONLY validation authority with NO extra state: an Office ID
# is stable regardless of how the available-offices list has shifted
# between the menu being sent and the WP's reply, so the
# "disabled-after-menu-sent" race (Step 12 Section 8) is rejected
# correctly by that function's own fresh DB check alone — no snapshot of
# "which list was sent" needs to be stored anywhere, so this step adds NO
# model/migration.
#
# "Menu already sent, don't resend on every message" also needs no new
# state: a reply is only ever treated as a selection ATTEMPT when it is
# purely numeric (`str.isdigit()`); any other reply while
# `Chat.office IS NULL` (including the very first message) shows the
# full menu. A numeric-but-invalid attempt gets the short retry message,
# never the full list again — this is the "kontrol" the task asks for,
# derived entirely from the incoming message's own content, not stored
# conversation state.
_MAX_SELECTION_DIGITS = 6  # generous upper bound on any real Office PK; guards int() from a pathological input

NO_OFFICE_AVAILABLE_TEXT = 'Maaf, saat ini belum ada layanan Samsat yang tersedia.'
INVALID_SELECTION_TEXT = 'Pilihan tidak valid. Silakan balas dengan nomor sesuai daftar Office.'
CONFIRMATION_TEXT_TEMPLATE = 'Baik, percakapan Anda telah diarahkan ke {office_name}.'


def available_operator_chat_offices():
    """Offices a WP may currently choose as a "Chat dengan Operator"
    destination: `Office.is_active=True` AND a saved
    `OfficeInboxConfig.enabled=True`. An Office with no `OfficeInboxConfig`
    row at all is excluded by the `inbox_config__enabled=True` join
    itself (no matching row -> not returned) — never lazily created here,
    unlike the admin-facing `OfficeInboxConfigView` (Step 10), which
    creates one on first admin GET/PATCH; a WP opening the menu must
    never have that side effect.

    Ordered by name — deterministic, documented (Step 11 Section 4)."""
    return Office.objects.filter(is_active=True, inbox_config__enabled=True).order_by('name')


def select_office_for_chat(session: WahaSession, chat_provider_id: str, office_id) -> tuple:
    """Validates `office_id` against the database (never trusting the
    WP-supplied value beyond using it as a lookup key) and, if it is
    still a valid destination, sets that Chat's `office` — creating the
    Chat if it does not already exist (same `get_or_create` idiom as
    `apps.webhooks.services.persist_message`), but WITHOUT touching
    `session.office`.

    Also clears `chat.assigned_to` — found live: picking a NEW handoff
    round (even back to the same Office) left the PREVIOUS round's
    assignee in place, which made this Chat silently invisible to
    `apps.dashboard.views.PendingChatsView`'s `assigned_to__isnull=True`
    filter — nobody at the newly-selected Office was ever notified a
    citizen was waiting, since the case still looked "already handled"
    by whoever closed the last round. A fresh round always needs to be
    claimed again, regardless of who handled the previous one.

    Returns `(chat, None)` on success, or `(None, error_code)` — one of
    `OFFICE_NOT_FOUND` (no such Office at all) or `OFFICE_UNAVAILABLE`
    (exists, but inactive or Inbox disabled — including the race where it
    was available when a menu was built and is not anymore)."""
    try:
        office = Office.objects.select_related('inbox_config').get(pk=office_id)
    except (Office.DoesNotExist, ValueError, TypeError):
        return None, OFFICE_NOT_FOUND

    inbox_config = getattr(office, 'inbox_config', None)
    if not office.is_active or inbox_config is None or not inbox_config.enabled:
        return None, OFFICE_UNAVAILABLE

    chat, _ = Chat.objects.get_or_create(session=session, provider_chat_id=chat_provider_id)
    chat.office = office
    chat.assigned_to = None
    chat.save(update_fields=['office', 'assigned_to', 'updated_at'])
    return chat, None


def _build_menu_text(offices) -> str:
    lines = ['Silakan pilih Samsat tujuan:', '']
    lines.extend(f'{office.pk}. {office.name}' for office in offices)
    lines.append('')
    lines.append('Balas dengan nomor pilihan Anda.')
    return '\n'.join(lines)


def _send_operator_chat_text(session: WahaSession, chat_provider_id: str, idempotency_key: str, text: str) -> None:
    """Reuses the existing Django -> BFF -> WAHA `sendText` path
    (`apps.blast.bff_client.send_blast_message`, Phase 11) — the same
    already-verified mechanism Blast dispatch uses, not a new WAHA/BFF
    call. Best-effort: a failed send is logged, never raised — this is a
    side effect of successfully receiving an inbound message, and must
    never roll back or fail the inbound message's own already-committed
    persistence (see `apps.webhooks.services.ingest_webhook`, which calls
    this AFTER its own transaction commits)."""
    try:
        send_blast_message(session.name, chat_provider_id, text, idempotency_key)
    except BffDispatchError as exc:
        logger.warning('operator-chat auto-reply failed for %s/%s: %s', session.name, chat_provider_id, exc)


def handle_operator_chat_message(session: WahaSession, message) -> None:
    """Step 12 entry point — called once per successfully-persisted LIVE
    inbound webhook message (never for reconciliation/history backfill,
    which calls `persist_message()` directly and never this function —
    replaying old history must never trigger a fresh "select an Office"
    reply). No-ops entirely once `Chat.office` is set, for a group chat,
    or for a message with no usable text body."""
    chat = message.chat
    if chat.is_group or chat.office_id is not None:
        return
    body = (message.body or '').strip()
    if not body:
        return

    offices = list(available_operator_chat_offices())
    idempotency_key = f'operator-chat-{message.pk}'

    if not offices:
        _send_operator_chat_text(session, chat.provider_chat_id, idempotency_key, NO_OFFICE_AVAILABLE_TEXT)
        return

    if body.isdigit() and len(body) <= _MAX_SELECTION_DIGITS:
        selected_chat, error = select_office_for_chat(session, chat.provider_chat_id, int(body))
        if error is None:
            text = CONFIRMATION_TEXT_TEMPLATE.format(office_name=selected_chat.office.name)
        else:
            text = INVALID_SELECTION_TEXT
        _send_operator_chat_text(session, chat.provider_chat_id, idempotency_key, text)
        return

    # Non-numeric reply (including the very first message) while still
    # unassigned — show the menu. Re-sent for every such message; a
    # numeric-but-wrong reply above gets the short retry text instead,
    # which is the "kontrol" against unconditional menu spam.
    _send_operator_chat_text(session, chat.provider_chat_id, idempotency_key, _build_menu_text(offices))
