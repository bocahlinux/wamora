"""Reconciliation / history synchronization (Phase 4).

docs/05-WEBHOOK-SYNC-DESIGN.md: "WAHA -> reconciliation job -> fetch
history -> compare stable IDs -> insert missing records -> advance
checkpoint." Must be repeatable, paginated, transaction-aware, and
duplicate-safe.

SCOPE: reconciles only Chat rows already known to this session (created
previously via webhook ingestion) — not a blind full-account sync.

PAGINATION: bounded multi-page fetch using `limit`+`offset`, confirmed
working against the real deployed WAHA instance (see
apps/sync/waha_client.py and docs/generated/PHASE-4-RECONCILIATION.md).
Bounded by three independent, safe stopping conditions — never an
unlimited history scan:
  1. A page returns fewer than `limit` items (end of available history).
  2. The oldest message in a page (ordering is confirmed newest-first) is
     at or before the PRE-RUN checkpoint watermark — we've caught up to
     already-synced data. This uses the checkpoint value that existed
     BEFORE this run started, never the value being built up during it.
  3. `max_pages` is reached (defensive hard cap, independent of the other
     two, in case a chat has never been synced before and has unbounded
     history).

CHECKPOINT SEMANTICS: `SyncCheckpoint.checkpoint_value` is a session-scoped
watermark — the latest message timestamp seen across a FULLY successful
run (confirmed with the project owner, since docs/04-DATA-MODEL.md does
not define it; re-confirmed unchanged when pagination was added). It is
purely an optimization marker; correctness (no duplicate durable records)
is guaranteed entirely by the existing (session, provider_message_id)
database constraint, independent of this value. The pagination `offset`
above is an EPHEMERAL, in-run fetch cursor only — never persisted, never
written to `checkpoint_value`. The checkpoint is only advanced when the
entire run completes without error.
"""

import datetime
import logging

from django.db import transaction
from django.utils import timezone

from apps.chats.models import Chat
from apps.sync.models import SyncCheckpoint
from apps.sync.waha_client import WahaClient, WahaClientError
from apps.waha_sessions.models import WahaSession
from apps.webhooks.parsing import MessageParsingError, parse_message, parse_timestamp
from apps.webhooks.services import DuplicateMessage, persist_message

logger = logging.getLogger(__name__)

DEFAULT_MESSAGE_LIMIT = 100
DEFAULT_MAX_PAGES = 10


class ReconciliationResult:
    def __init__(self):
        self.chats_processed = 0
        self.messages_inserted = 0
        self.messages_skipped_existing = 0
        self.messages_failed = 0
        self.chat_fetch_errors = []
        self.message_errors = []
        # Inbox/Chat (canonical Phase 8) chat-discovery step —
        # docs/generated/INBOX-CHAT-DECISION-REPORT.md Section 4.
        # Deliberately best-effort: a discovery failure is recorded here
        # for visibility but does NOT set had_error / block checkpoint
        # advancement — discovery is additive to this method's original
        # contract (catch up on already-known chats' message history),
        # not a precondition of it.
        self.chats_discovered = 0
        self.chat_discovery_error = None

    @property
    def had_error(self):
        return bool(self.chat_fetch_errors or self.message_errors)


def _iter_chat_history_pages(client, session_name, chat_id, limit, max_pages, stop_at_timestamp):
    """Yields successive pages (each a list of raw message dicts) newest-
    first via limit+offset (confirmed working — see waha_client.py),
    stopping at whichever of the three documented conditions (module
    docstring) is hit first. `offset` is a purely local loop variable —
    never persisted, never yielded.

    Yielding page-by-page (rather than collecting everything into one list
    before returning) matters for failure safety: if a LATER page's fetch
    raises WahaClientError, pages already yielded have already been
    persisted by the caller and are not lost — only the chat as a whole is
    then marked as having an error (see reconcile_session)."""
    offset = 0
    for _page_num in range(max_pages):
        page = client.fetch_chat_messages(session_name, chat_id, limit=limit, offset=offset)
        if not page:
            return
        yield page

        if len(page) < limit:
            return  # end of available history

        if stop_at_timestamp is not None:
            oldest_in_page = parse_timestamp(page[-1].get('timestamp'))
            if oldest_in_page <= stop_at_timestamp:
                return  # caught up to already-synced data

        offset += limit


def _discover_chats(client, session):
    """Chat discovery (Inbox/Chat, canonical Phase 8;
    docs/generated/INBOX-CHAT-DECISION-REPORT.md Section 4). Fetches
    WAHA's chat list and creates a bare Chat row (provider_chat_id only)
    for any chat WAHA reports that Django doesn't already have — closing
    the gap that this function's own message-reconciliation loop below
    can only ever process chats already present in the database.

    Field extraction is deliberately conservative
    (apps/sync/waha_client.py::fetch_chats's own docstring): only the
    chat identifier is trusted, tried in the same
    nested-then-top-level-fallback order already established for message
    parsing (apps/webhooks/parsing.py::parse_message). `is_group`/`name`
    are intentionally left unset here — the existing, already-tested
    persist_message() already fills them in correctly the moment a real
    message for that chat is ingested (via a live webhook or this same
    function's own subsequent per-chat loop), so nothing here needs to
    guess at chat-list-specific field names this project has never
    confirmed.

    Returns (discovered_count, error_message_or_None). Never raises —
    a WAHA failure here is reported, not fatal to the rest of the run."""
    try:
        raw_chats = client.fetch_chats(session.name)
    except WahaClientError as exc:
        logger.warning('Chat discovery failed for session %s: %s', session.name, exc)
        return 0, str(exc)

    discovered = 0
    for raw_chat in raw_chats:
        if not isinstance(raw_chat, dict):
            continue
        data_field = raw_chat.get('_data')
        info = data_field.get('Info', {}) if isinstance(data_field, dict) else {}
        provider_chat_id = info.get('Chat') if isinstance(info, dict) else None
        if not isinstance(provider_chat_id, str) or not provider_chat_id:
            provider_chat_id = raw_chat.get('id')
        if not isinstance(provider_chat_id, str) or not provider_chat_id:
            logger.warning('Skipping a discovered chat with no usable identifier for session %s', session.name)
            continue
        _, created = Chat.objects.get_or_create(session=session, provider_chat_id=provider_chat_id)
        if created:
            discovered += 1
    return discovered, None


def reconcile_session(
    session_name,
    chat_ids=None,
    limit=DEFAULT_MESSAGE_LIMIT,
    max_pages=DEFAULT_MAX_PAGES,
    waha_client=None,
):
    """Reconciles the given session's already-known chats (all of them, or
    only `chat_ids` if provided) against WAHA REST history. Never marks the
    checkpoint as advanced unless the entire run completed without error.

    When `chat_ids` is not given (a full-session run, not a targeted
    re-sync of specific chats), first runs chat discovery (see
    `_discover_chats`) so a chat WAHA has but Django has never received a
    webhook for gets a row created before the per-chat loop below runs —
    in the same pass, not a separate one."""
    session = WahaSession.objects.get(name=session_name)
    checkpoint, _ = SyncCheckpoint.objects.get_or_create(session=session)

    # Read the PRE-RUN watermark once — used only as a pagination stopping
    # boundary, never mutated during the run.
    stop_at_timestamp = None
    if checkpoint.checkpoint_value:
        try:
            stop_at_timestamp = datetime.datetime.fromisoformat(checkpoint.checkpoint_value)
        except ValueError:
            stop_at_timestamp = None

    checkpoint.status = SyncCheckpoint.STATUS_RUNNING
    checkpoint.save(update_fields=['status', 'updated_at'])

    client = waha_client or WahaClient()
    result = ReconciliationResult()
    latest_timestamp = None

    if chat_ids is None:
        result.chats_discovered, result.chat_discovery_error = _discover_chats(client, session)

    chats = Chat.objects.filter(session=session)
    if chat_ids is not None:
        chats = chats.filter(provider_chat_id__in=chat_ids)

    for chat in chats:
        chat_fetch_failed = False
        try:
            for page in _iter_chat_history_pages(
                client, session.name, chat.provider_chat_id, limit, max_pages, stop_at_timestamp
            ):
                for raw_message in page:
                    try:
                        parsed = parse_message(raw_message)
                    except MessageParsingError as exc:
                        result.messages_failed += 1
                        result.message_errors.append(str(exc))
                        logger.warning(
                            'Reconciliation could not parse a message in chat %s: %s',
                            chat.provider_chat_id, exc,
                        )
                        continue

                    try:
                        with transaction.atomic():
                            persist_message(session, parsed)
                    except DuplicateMessage:
                        result.messages_skipped_existing += 1
                        continue

                    result.messages_inserted += 1
                    if latest_timestamp is None or parsed.timestamp > latest_timestamp:
                        latest_timestamp = parsed.timestamp
        except WahaClientError as exc:
            chat_fetch_failed = True
            result.chat_fetch_errors.append(f'{chat.provider_chat_id}: {exc}')
            logger.warning('Reconciliation fetch failed for chat %s: %s', chat.provider_chat_id, exc)

        if not chat_fetch_failed:
            result.chats_processed += 1

    checkpoint.last_run_at = timezone.now()
    if result.had_error:
        checkpoint.status = SyncCheckpoint.STATUS_ERROR
        checkpoint.last_error = '; '.join(result.chat_fetch_errors + result.message_errors)[:2000]
        # checkpoint_value is intentionally NOT advanced — a run with any
        # error cannot be trusted as "fully caught up"; the next run will
        # safely reprocess (duplicates are rejected at the DB layer).
    else:
        checkpoint.status = SyncCheckpoint.STATUS_OK
        checkpoint.last_error = ''
        if latest_timestamp is not None:
            checkpoint.checkpoint_value = latest_timestamp.isoformat()

    checkpoint.save(update_fields=['status', 'last_run_at', 'last_error', 'checkpoint_value', 'updated_at'])
    return result
