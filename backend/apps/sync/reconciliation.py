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

# PHASE-4-9-CELERY-WORKER-LIVENESS-IMPLEMENTATION-REPORT.md. Never the raw
# exception text (matches apps.blast.tasks.SAFE_FAILURE_MESSAGE's own
# precedent) — a single, generic, operator-safe string for the one class of
# failure this function's own code does not already know how to describe
# more specifically: an exception that is not WahaClientError (which keeps
# its own already-safe, already-specific str(exc) message below, unchanged)
# and not MessageParsingError (same). Distinguishing these for an operator
# is a documented future improvement, not this fix's scope.
SAFE_UNEXPECTED_ERROR_MESSAGE = 'Reconciliation failed due to an unexpected error.'


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
    trigger_source=None,
    task_id=None,
    is_final_attempt=True,
):
    """Reconciles the given session's already-known chats (all of them, or
    only `chat_ids` if provided) against WAHA REST history. Never marks the
    checkpoint as advanced unless the entire run completed without error.

    When `chat_ids` is not given (a full-session run, not a targeted
    re-sync of specific chats), first runs chat discovery (see
    `_discover_chats`) so a chat WAHA has but Django has never received a
    webhook for gets a row created before the per-chat loop below runs —
    in the same pass, not a separate one.

    `trigger_source`/`task_id` — docs/generated/NEXT-PHASE-RECONCILIATION-OBSERVABILITY-DESIGN-AUDIT-REPORT.md
    Section 8/13. Explicit, caller-supplied context only (never inferred
    from the call stack, never a fabricated ID) — each caller already
    knows, at its own call site, which SyncCheckpoint.TRIGGER_* it is and
    (for a Celery-executed caller) its own real `self.request.id`. Both
    default to `None`/absent so every existing caller (and every existing
    test) that doesn't pass them keeps working unchanged. Recorded once,
    at the START of the run (see write (A) below), not only on
    completion, so the metadata is already durably visible even if this
    run never reaches its own end — this is purely descriptive metadata:
    it never changes checkpoint_value, retry behavior, or the
    reconciliation loop itself.

    `is_final_attempt` — PHASE-4-9-CELERY-WORKER-LIVENESS-IMPLEMENTATION-REPORT.md.
    Closes the one gap the design audit found: an exception that is
    neither WahaClientError (handled per-chat below, unchanged) nor
    MessageParsingError (also handled per-chat, unchanged) used to
    propagate straight out of this function, skipping the terminal write
    at the bottom entirely and leaving the checkpoint RUNNING forever.
    Such an exception is now caught (see the `except Exception` below)
    and, if `is_final_attempt` is true, the checkpoint is written to its
    terminal STATUS_ERROR *before* the exception is re-raised — the
    caller (Celery, or whatever else called this function) still sees
    the original exception exactly as before; only the checkpoint's own
    fate changes.

    Defaults to `True` because that is the correct behavior for every
    caller that is NOT wrapped in Celery's own `autoretry_for` retry
    loop — the `sync` executor (apps.sync.executors), the
    `manage.py reconcile` management command, and every existing test in
    this module: for those callers, a raised exception here IS already
    the final attempt (nothing will call this function again on their
    behalf), so the checkpoint must reach STATUS_ERROR immediately, not
    stay RUNNING waiting for a retry that will never come.

    The two Celery entry points that DO retry
    (`reconcile_session_task`/`reconcile_chat_task` in apps.sync.tasks,
    both `autoretry_for=(Exception,), max_retries=3`) instead pass
    `is_final_attempt=self.request.retries >= self.max_retries` — false
    while a retry is still pending, true only on the actually-final
    attempt. This matters because Celery's autoretry wrapper re-invokes
    the ENTIRE task function from scratch on each retry, which re-enters
    this function from the top and immediately re-writes the checkpoint
    to RUNNING via write (A) above — so an intermediate failed attempt's
    checkpoint state is about to be overwritten within moments anyway;
    writing STATUS_ERROR for it here would be both premature (the retry
    may well succeed) and misleading (surfacing a transient "error" for
    what is, from the operator's point of view, still a healthy,
    in-progress retry-backoff sequence — the same legitimate-retry false-
    positive risk the design audit already documented for
    `possibly_stuck`, row H). Only once retries are truly exhausted does
    this function's own STATUS_ERROR write become the correct, final,
    durable answer."""
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
    update_fields = ['status', 'updated_at']
    if trigger_source is not None:
        checkpoint.last_run_trigger_source = trigger_source
        update_fields.append('last_run_trigger_source')
    if task_id is not None:
        checkpoint.last_run_task_id = task_id
        update_fields.append('last_run_task_id')
    checkpoint.save(update_fields=update_fields)

    client = waha_client or WahaClient()
    result = ReconciliationResult()
    latest_timestamp = None

    if chat_ids is None:
        result.chats_discovered, result.chat_discovery_error = _discover_chats(client, session)

    chats = Chat.objects.filter(session=session)
    if chat_ids is not None:
        chats = chats.filter(provider_chat_id__in=chat_ids)

    try:
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
    except Exception:
        # Anything reaching here is, by construction, NOT a WahaClientError
        # (caught per-chat immediately above) and NOT a MessageParsingError
        # (caught per-message immediately above) — an exception this
        # function's own code does not already know how to handle: a bug,
        # an unexpected DB error, an IntegrityError not converted to
        # DuplicateMessage, etc. (design audit row D). See `is_final_attempt`
        # in this function's own docstring for the retry-exhaustion
        # reasoning below.
        if is_final_attempt:
            checkpoint.last_run_at = timezone.now()
            checkpoint.status = SyncCheckpoint.STATUS_ERROR
            checkpoint.last_error = SAFE_UNEXPECTED_ERROR_MESSAGE
            # checkpoint_value is deliberately left untouched — same
            # "only advances on a fully successful run" guarantee the
            # existing had_error branch below already honors.
            checkpoint.save(update_fields=['status', 'last_run_at', 'last_error', 'updated_at'])
        # Re-raised unchanged either way: Celery's own autoretry_for still
        # needs to see the original exception to decide whether to retry
        # (when is_final_attempt is False) or mark the task FAILURE (when
        # True) — this function only ever adds a checkpoint write, never
        # swallows or replaces the exception itself.
        raise

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
