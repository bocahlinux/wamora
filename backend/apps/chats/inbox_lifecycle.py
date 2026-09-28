"""Step 13 — Inbox welcome lifecycle (foundation only).

Complementary to `apps.chats.operator_chat` (Step 12): that module owns
the `Chat.office IS NULL` case (Office selection); THIS module owns the
`Chat.office IS NOT NULL` case (send the Office's one-time welcome
message). `apps.webhooks.services.ingest_webhook` branches between the
two — never both for the same message.

Deliberately welcome-only. `waiting_message`/`offline_message`
(`OfficeInboxConfig`, Step 10) are read nowhere in this module — their
semantics were explicitly deferred (no operator-reply-tracking or
operator-availability foundation exists anywhere in this codebase to
define them correctly; see the Step 13 audit). Storing/reading those two
fields, and any operator assignment/queue/availability concept, remains
entirely out of scope here.
"""

import logging

from django.utils import timezone

from apps.blast.bff_client import BffDispatchError, send_blast_message
from apps.chats.models import Chat
from apps.waha_sessions.models import WahaSession

logger = logging.getLogger(__name__)


def _send_welcome_text(session: WahaSession, chat_provider_id: str, idempotency_key: str, text: str) -> None:
    """Same reused Django -> BFF -> WAHA `sendText` path as
    `apps.chats.operator_chat._send_operator_chat_text` (Step 12) — best-
    effort, never raises. A send failure here does NOT un-claim
    `welcome_sent_at` (see `handle_inbox_lifecycle_message`'s own
    docstring for why: matches `apps.blast.bff_client`'s own established
    "never auto-retry a BFF dispatch failure" decision)."""
    try:
        send_blast_message(session.name, chat_provider_id, text, idempotency_key)
    except BffDispatchError as exc:
        logger.warning('inbox welcome send failed for %s/%s: %s', session.name, chat_provider_id, exc)


def handle_inbox_lifecycle_message(session: WahaSession, message) -> None:
    """Step 13 entry point — called once per successfully-persisted LIVE
    inbound webhook message whose Chat ALREADY has an Office (the
    `Chat.office IS NULL` case is `apps.chats.operator_chat`'s job, never
    this function's). Never called by reconciliation/history backfill
    (see `apps.webhooks.services.ingest_webhook`, the only caller).

    Sends `OfficeInboxConfig.welcome_message` exactly once per Chat, only
    when ALL of: `Office.is_active`, a saved `OfficeInboxConfig.enabled`,
    a non-blank `welcome_message`, and `Chat.welcome_sent_at IS NULL`.
    Re-reads Office/InboxConfig fresh from the database on every call —
    never trusts a stale/previously-fetched instance — so Case B/C
    (Office inactive / Inbox disabled) documented in the Step 13 plan is
    always evaluated against current state.

    Race safety: `Chat.objects.filter(pk=.., welcome_sent_at__isnull=True)
    .update(...)` is an atomic compare-and-set CLAIM, executed BEFORE any
    outbound send is attempted — this is what guarantees two near-
    simultaneous webhook deliveries for the same Chat can never both send
    a welcome (at most one UPDATE can affect a row; the loser's `claimed`
    count is 0 and it returns immediately). The accepted trade-off: if
    the outbound send itself then fails, the claim is not rolled back and
    no retry happens — identical to `apps.blast.bff_client`'s own
    documented "a BFF dispatch failure is never auto-retried" decision,
    not a new one invented here.
    """
    chat = Chat.objects.select_related('office', 'office__inbox_config').get(pk=message.chat_id)

    office = chat.office
    if office is None or not office.is_active:
        return

    inbox_config = getattr(office, 'inbox_config', None)
    if inbox_config is None or not inbox_config.enabled:
        return

    welcome_message = inbox_config.welcome_message.strip()
    if not welcome_message:
        return

    claimed = Chat.objects.filter(pk=chat.pk, welcome_sent_at__isnull=True).update(welcome_sent_at=timezone.now())
    if claimed == 0:
        return  # already sent (or lost a concurrent race to claim it) — no-op

    idempotency_key = f'inbox-welcome-{message.pk}'
    _send_welcome_text(session, chat.provider_chat_id, idempotency_key, welcome_message)
