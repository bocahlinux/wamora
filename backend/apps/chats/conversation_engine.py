"""Conversation/Bot Engine — supersedes `apps.chats.operator_chat`
(Step 12) and `apps.chats.inbox_lifecycle` (Step 13) as the single entry
point `apps.webhooks.services.ingest_webhook` calls for a LIVE inbound
message. Both superseded modules are left in place, unmodified, per
explicit instruction (no destructive change without separate approval) —
this module simply stops being routed to from the webhook path.

Design basis: the approved 17-point Conversation Engine design (this
project's own conversation history). Menu/trigger CONTENT is always data
(`apps.bot.models`), never hardcoded branching — this module only
contains the resolver algorithm, never a menu string or trigger keyword
itself.

Resolution order for one inbound message, each step documented at its
own call site below:
  1. Effective `BotConfig` for this Chat (Office-specific if one exists,
     else GLOBAL) — bot entirely disabled/unconfigured -> no-op, silent.
  2. Global trigger match -> ALWAYS resets the flow (approved correction
     #1), regardless of any existing active session.
  3. No active session -> fallback text + show the Main Menu (correction
     #6) — this is also what a brand-new WhatsApp number's very first,
     non-trigger message hits; no auto Office-selection ever happens here
     (correction #3).
  4. Active session, current menu is the Office-selector
     (`BotMenu.is_office_selector`) -> delegate entirely to
     `apps.chats.operator_chat`'s existing, already-tested
     `available_operator_chat_offices()`/`select_office_for_chat()` —
     reused verbatim, never re-implemented (correction #12).
  5. Active session, ordinary menu -> match the reply against that menu's
     `BotMenuItem` rows; a match runs its `action_type`; no match ->
     fallback text + re-show the SAME menu, session state untouched
     (correction #7).
"""

import logging

from django.utils import timezone

from apps.bot.models import BotConfig, BotMenuItem, BotTrigger
from apps.blast.bff_client import BffDispatchError, send_blast_message
from apps.chats.models import Chat, ConversationSession
from apps.chats.operator_chat import (
    INVALID_SELECTION_TEXT,
    NO_OFFICE_AVAILABLE_TEXT,
    available_operator_chat_offices,
    select_office_for_chat,
)
from apps.waha_sessions.models import WahaSession

logger = logging.getLogger(__name__)

OFFICE_SELECTED_TEXT_TEMPLATE = 'Baik, percakapan Anda telah diarahkan ke {office_name}.'
HANDOFF_ACK_TEXT = 'Permintaan Anda sedang diteruskan ke petugas.'
_MAX_SELECTION_DIGITS = 6  # same guard as apps.chats.operator_chat._MAX_SELECTION_DIGITS


def _normalize(text: str) -> str:
    return (text or '').strip()


def _send(session: WahaSession, chat_provider_id: str, idempotency_key: str, text: str) -> None:
    """Best-effort outbound, same reused Django -> BFF -> WAHA `sendText`
    path as every other bot-adjacent module in this app — never raises, a
    send failure is logged only, and never rolls back or blocks the
    already-committed inbound message this is a side effect of."""
    text = (text or '').strip()
    if not text:
        return
    try:
        send_blast_message(session.name, chat_provider_id, text, idempotency_key)
    except BffDispatchError as exc:
        logger.warning('conversation-engine send failed for %s/%s: %s', session.name, chat_provider_id, exc)


def _effective_config(office):
    """Office-specific `BotConfig` if one has ever been saved for this
    Office, else the GLOBAL row — never lazily created here (a WP's
    inbound message must never have the side effect of creating admin
    config rows; only `apps.bot.views` does that, on an admin's own
    GET/PATCH, same discipline as `apps.chats.operator_chat`'s own
    `available_operator_chat_offices()` docstring establishes for
    `OfficeInboxConfig`). `None` if nothing has been configured at all —
    callers treat that identically to `enabled=False`."""
    if office is not None:
        office_config = BotConfig.objects.filter(office=office).select_related('root_menu').first()
        if office_config is not None:
            return office_config
    return BotConfig.objects.filter(office=None).select_related('root_menu').first()


def _match_trigger(chat: Chat, body: str):
    """An enabled `BotTrigger` whose keyword matches `body`
    (case-insensitive) — an Office-specific trigger (for `chat.office`, if
    set) takes precedence over a same-keyword GLOBAL one, mirroring how a
    per-Office `BotConfig` already takes precedence over the GLOBAL one
    above. Returns `None` if nothing matches (including a blank body)."""
    keyword = _normalize(body)
    if not keyword:
        return None
    matches = BotTrigger.objects.filter(enabled=True, keyword__iexact=keyword).select_related('target_menu')
    if chat.office_id is not None:
        office_trigger = matches.filter(office_id=chat.office_id).first()
        if office_trigger is not None:
            return office_trigger
    return matches.filter(office__isnull=True).first()


def _render_menu_text(menu) -> str:
    """Static rendering for an ordinary menu — the Office-selector menu
    (`is_office_selector=True`) is rendered separately, by
    `apps.chats.operator_chat`'s own menu-building convention, never via
    stored `BotMenuItem` rows (see that field's own model docstring)."""
    lines = []
    if menu.intro_text.strip():
        lines.append(menu.intro_text.strip())
        lines.append('')
    for item in menu.items.filter(enabled=True).order_by('order', 'id'):
        lines.append(f'{item.trigger_value}. {item.label}')
    return '\n'.join(lines).strip()


def _render_office_selector_text(offices) -> str:
    lines = ['Silakan pilih Samsat tujuan:', '']
    lines.extend(f'{office.pk}. {office.name}' for office in offices)
    lines.append('')
    lines.append('Balas dengan nomor pilihan Anda.')
    return '\n'.join(lines)


def _idempotency_key(message, suffix: str) -> str:
    return f'bot-{message.pk}-{suffix}'


def _start_new_session(chat: Chat, config) -> ConversationSession:
    """Creates a fresh `ConversationSession` positioned at `config.root_menu`
    — history is never deleted (correction #9), so any prior session for
    this Chat is simply left as-is; the partial-unique constraint on
    `ConversationSession.Meta` only allows this INSERT to succeed once any
    earlier active-state session for the same Chat has already been moved
    out of an active state (see `_reset_session_for_trigger` for the
    global-trigger case)."""
    return ConversationSession.objects.create(
        chat=chat,
        state=ConversationSession.STATE_ACTIVE,
        current_menu=config.root_menu,
    )


def _abandon_active_session(chat: Chat) -> None:
    """A global trigger always resets the flow (correction #1), even
    mid-submenu. The prior active-state session (if any) is moved to
    COMPLETED — not deleted (history is preserved, correction #9) — purely
    so the DB-level partial-unique constraint allows a new active session
    to be created; no "session completed" message is sent for this case,
    since the user themselves just explicitly asked to restart."""
    session = ConversationSession.objects.filter(chat=chat, state__in=ConversationSession.ACTIVE_STATES).first()
    if session is not None:
        session.state = ConversationSession.STATE_COMPLETED
        session.completed_at = timezone.now()
        session.current_menu = None
        session.save(update_fields=['state', 'completed_at', 'current_menu', 'updated_at'])


def _complete_session(session: ConversationSession, config) -> None:
    session.state = ConversationSession.STATE_COMPLETED
    session.completed_at = timezone.now()
    session.current_menu = None
    session.save(update_fields=['state', 'completed_at', 'current_menu', 'updated_at'])


def _handle_office_selector_reply(waha_session: WahaSession, message, chat: Chat, session: ConversationSession, body: str) -> None:
    idempotency_key = _idempotency_key(message, 'office-select')
    offices = list(available_operator_chat_offices())

    if not offices:
        _send(waha_session, chat.provider_chat_id, idempotency_key, NO_OFFICE_AVAILABLE_TEXT)
        return

    if not (body.isdigit() and len(body) <= _MAX_SELECTION_DIGITS):
        # Unrecognized reply while an active session is on this menu ->
        # fallback + re-show the SAME menu (correction #7), never silent,
        # never corrupting session state.
        _send(waha_session, chat.provider_chat_id, idempotency_key, _render_office_selector_text(offices))
        return

    selected_chat, error = select_office_for_chat(waha_session, chat.provider_chat_id, int(body))
    if error is not None:
        _send(waha_session, chat.provider_chat_id, idempotency_key, INVALID_SELECTION_TEXT)
        return

    # Office selection is recorded on ConversationSession.office (approved
    # correction #5) — select_office_for_chat() already synced
    # Chat.office for the existing RBAC/Inbox mechanism; this is the
    # reverse direction, session -> office, kept as a separate write since
    # ConversationSession is never that function's concern.
    session.office = selected_chat.office
    # Selecting a destination Office is this foundation's only handoff
    # trigger (correction #13 — no queue/assignment logic here, this is
    # purely the extension point). current_menu cleared: WAITING_OPERATOR
    # has no "current menu" position, same as COMPLETED.
    session.state = ConversationSession.STATE_WAITING_OPERATOR
    session.current_menu = None
    session.save(update_fields=['office', 'state', 'current_menu', 'updated_at'])

    _send(
        waha_session, chat.provider_chat_id, idempotency_key,
        OFFICE_SELECTED_TEXT_TEMPLATE.format(office_name=selected_chat.office.name),
    )


def _handle_menu_item(waha_session: WahaSession, message, chat: Chat, session: ConversationSession, config, item: BotMenuItem) -> None:
    idempotency_key = _idempotency_key(message, f'item-{item.pk}')

    if item.action_type == BotMenuItem.ACTION_SHOW_MENU:
        session.current_menu = item.target_menu
        session.save(update_fields=['current_menu', 'updated_at'])
        # An Office-selector target renders its dynamic Office list
        # (correction #12 — reusing available_operator_chat_offices()
        # verbatim), never the static BotMenuItem rendering, which would
        # always be empty for such a menu (see BotMenu.is_office_selector's
        # own docstring: zero stored items are expected).
        if item.target_menu.is_office_selector:
            text = _render_office_selector_text(list(available_operator_chat_offices()))
        else:
            text = _render_menu_text(item.target_menu)
        _send(waha_session, chat.provider_chat_id, idempotency_key, text)
        return

    if item.action_type == BotMenuItem.ACTION_SEND_TEXT:
        _send(waha_session, chat.provider_chat_id, idempotency_key, item.text)
        _complete_session(session, config)
        _send(
            waha_session, chat.provider_chat_id, _idempotency_key(message, f'item-{item.pk}-completed'),
            config.session_completed_message if config else '',
        )
        return

    if item.action_type == BotMenuItem.ACTION_COMPLETE_SESSION:
        _complete_session(session, config)
        _send(
            waha_session, chat.provider_chat_id, idempotency_key,
            config.session_completed_message if config else '',
        )
        return

    if item.action_type == BotMenuItem.ACTION_HANDOFF_TO_OPERATOR:
        # Extension point only (correction #13) — no assignment/queue
        # logic exists here or anywhere else in this codebase yet. This
        # only records the state transition and acknowledges the request;
        # the actual Operator Workflow phase (canonical Phase 15, distinct
        # from this Conversation Engine work) is what will later act on
        # WAITING_OPERATOR sessions.
        session.state = ConversationSession.STATE_WAITING_OPERATOR
        session.save(update_fields=['state', 'updated_at'])
        _send(waha_session, chat.provider_chat_id, idempotency_key, HANDOFF_ACK_TEXT)
        return

    logger.warning('BotMenuItem %s has an unrecognized action_type %r', item.pk, item.action_type)


def handle_conversation_message(waha_session: WahaSession, message) -> None:
    """Entry point — called once per successfully-persisted LIVE inbound
    webhook message (never for reconciliation/history backfill, exactly
    like the two modules this supersedes; see this module's own docstring
    and `apps.webhooks.services.ingest_webhook`, the only caller). No-ops
    for a group chat or a message with no usable text body."""
    chat = message.chat
    if chat.is_group:
        return
    body = _normalize(message.body)
    if not body:
        return

    config = _effective_config(chat.office)
    if config is None or not config.enabled or config.root_menu is None:
        return

    trigger = _match_trigger(chat, body)
    if trigger is not None and trigger.target_menu is not None:
        _abandon_active_session(chat)
        ConversationSession.objects.create(
            chat=chat, state=ConversationSession.STATE_ACTIVE, current_menu=trigger.target_menu,
        )
        text = _render_menu_text(trigger.target_menu)
        _send(waha_session, chat.provider_chat_id, _idempotency_key(message, 'trigger'), text)
        return

    session = ConversationSession.objects.filter(
        chat=chat, state__in=ConversationSession.ACTIVE_STATES,
    ).select_related('current_menu').first()

    if session is None:
        # No active session and the message wasn't a recognized trigger ->
        # fallback + Main Menu, never silent (correction #6). This is also
        # what a brand-new WhatsApp number's very first message hits — no
        # auto Office-selection happens here (correction #3).
        _start_new_session(chat, config)
        text = config.fallback_message.strip()
        menu_text = _render_menu_text(config.root_menu)
        combined = '\n\n'.join(part for part in [text, menu_text] if part)
        _send(waha_session, chat.provider_chat_id, _idempotency_key(message, 'new'), combined)
        return

    if session.state == ConversationSession.STATE_WAITING_OPERATOR:
        # No queue/reply-routing logic exists yet (correction #13) — a
        # message arriving while WAITING_OPERATOR is simply not
        # re-injected into the menu tree; it is left for the (separate,
        # canonical) Operator Workflow phase to eventually consume.
        return

    current_menu = session.current_menu
    if current_menu is None:
        # Defensive only — an ACTIVE/NEW session should always carry a
        # current_menu; treat as unrecoverable and restart at the root,
        # same fallback+Main Menu behavior as "no active session".
        _complete_session(session, config)
        _start_new_session(chat, config)
        text = config.fallback_message.strip()
        menu_text = _render_menu_text(config.root_menu)
        combined = '\n\n'.join(part for part in [text, menu_text] if part)
        _send(waha_session, chat.provider_chat_id, _idempotency_key(message, 'recovered'), combined)
        return

    if current_menu.is_office_selector:
        _handle_office_selector_reply(waha_session, message, chat, session, body)
        return

    item = BotMenuItem.objects.filter(menu=current_menu, enabled=True, trigger_value__iexact=body).first()
    if item is None:
        # Unrecognized message WITH an active session -> fallback +
        # re-show the current menu, session state untouched (correction #7).
        text = config.fallback_message.strip()
        menu_text = _render_menu_text(current_menu)
        combined = '\n\n'.join(part for part in [text, menu_text] if part)
        _send(waha_session, chat.provider_chat_id, _idempotency_key(message, 'fallback'), combined)
        return

    _handle_menu_item(waha_session, message, chat, session, config, item)
