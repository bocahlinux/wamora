"""Targeted-reconciliation trigger — executor dispatcher.

docs/generated/INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md.
This WAHA deployment sends no webhook for self-sent (outbound) messages
(docs/generated/INBOX-OUTBOUND-MESSAGE-MISSING-AUDIT-REPORT.md), so a
just-sent message would otherwise sit unseen until the next periodic
reconciliation. `trigger_reconciliation()` is called once, right after a
confirmed successful send, to reconcile that one chat immediately.

This module is the ONLY place that knows which executor
(settings.RECONCILIATION_EXECUTOR) is active. Both executors call the
exact same, already-tested `reconcile_session()`
(apps.sync.reconciliation) — nothing here adds a second Message/Chat/
Contact persistence path. Swapping `sync` for `celery` is a configuration
change only, never a source change (see apps.sync.tasks.reconcile_chat_task
for the Celery-side counterpart, which also just calls
`run_targeted_reconciliation_with_retry` below).
"""

import logging
import time

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.sync.reconciliation import reconcile_session

logger = logging.getLogger(__name__)

EXECUTOR_SYNC = 'sync'
EXECUTOR_CELERY = 'celery'

# Bounded retry for the race between WAHA accepting a send and that
# message becoming visible via WAHA's own REST history endpoint (the two
# are different WAHA subsystems — nothing in this project has ever
# measured the gap between them). Deliberately small and specific to this
# one targeted call, not a general polling mechanism — never touches the
# existing Inbox 5s poll, and never grows into an unbounded retry.
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1.5


def run_targeted_reconciliation_with_retry(session_name, chat_id, waha_client=None):
    """The one shared implementation of "reconcile this one chat, allowing
    for WAHA's REST history to lag slightly behind a just-accepted send".
    Called directly (in-process) by the `sync` executor below, and from
    inside `apps.sync.tasks.reconcile_chat_task` for the `celery`
    executor — so the retry policy itself never differs by executor.

    Every attempt is a plain call to the existing, already-tested
    `reconcile_session()` — safe to repeat because it is already
    duplicate-safe (the (session, provider_message_id) DB constraint) and
    idempotent by design. Stops as soon as a run actually inserts
    something new; never retries past MAX_ATTEMPTS."""
    result = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = reconcile_session(session_name, chat_ids=[chat_id], waha_client=waha_client)
        if result.messages_inserted > 0:
            return result
        if attempt < MAX_ATTEMPTS:
            time.sleep(RETRY_DELAY_SECONDS)
    return result


def trigger_reconciliation(session_name, chat_id):
    """Dispatches a targeted reconciliation for one chat using whichever
    executor `settings.RECONCILIATION_EXECUTOR` selects.

    Returns the `ReconciliationResult` when run synchronously (`sync`), or
    `None` when merely enqueued (`celery` — no result is available yet at
    this point). Never silently substitutes a different executor than the
    one configured: an unrecognized value raises `ImproperlyConfigured`
    rather than falling back to `sync`, since a silent fallback could hide
    a real deployment misconfiguration (settings.py already fails fast at
    Django startup for the same reason — this is defense in depth for
    tests/callers that override the setting after startup)."""
    executor = settings.RECONCILIATION_EXECUTOR
    if executor == EXECUTOR_SYNC:
        return run_targeted_reconciliation_with_retry(session_name, chat_id)
    if executor == EXECUTOR_CELERY:
        from apps.sync.tasks import reconcile_chat_task

        reconcile_chat_task.delay(session_name, chat_id)
        return None
    raise ImproperlyConfigured(f'Unknown RECONCILIATION_EXECUTOR: {executor!r}')
