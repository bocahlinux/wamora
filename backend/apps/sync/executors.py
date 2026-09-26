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

from apps.sync.models import SyncCheckpoint
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


def run_targeted_reconciliation_with_retry(session_name, chat_id, waha_client=None, task_id='', is_final_attempt=True):
    """The one shared implementation of "reconcile this one chat, allowing
    for WAHA's REST history to lag slightly behind a just-accepted send".
    Called directly (in-process) by the `sync` executor below, and from
    inside `apps.sync.tasks.reconcile_chat_task` for the `celery`
    executor — so the retry policy itself never differs by executor.

    Every attempt is a plain call to the existing, already-tested
    `reconcile_session()` — safe to repeat because it is already
    duplicate-safe (the (session, provider_message_id) DB constraint) and
    idempotent by design. Stops as soon as a run actually inserts
    something new; never retries past MAX_ATTEMPTS.

    `task_id` — docs/generated/NEXT-PHASE-RECONCILIATION-OBSERVABILITY-DESIGN-AUDIT-REPORT.md
    Section 8/13. Both trigger_source values this helper's two callers
    ever pass are SyncCheckpoint.TRIGGER_TARGETED (this is always the
    targeted, single-chat path) — only task_id differs: the real Celery
    task ID from `reconcile_chat_task`'s own `self.request.id` for the
    `celery` executor, or '' (no Celery task exists) for the `sync`
    executor, the default here.

    `is_final_attempt` — PHASE-4-9-CELERY-WORKER-LIVENESS-IMPLEMENTATION-REPORT.md.
    Passed straight through to every `reconcile_session()` call below
    unchanged — see that function's own docstring. Defaults to `True`,
    correct for the `sync` executor (this module's own `EXECUTOR_SYNC`
    branch calls this function with no Celery retry wrapping it at all,
    so a raised exception here IS already the final attempt). Only
    `reconcile_chat_task` (apps.sync.tasks, the `celery` executor's
    Celery entry point) ever passes `False`, while its own
    `autoretry_for` retries remain."""
    result = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        result = reconcile_session(
            session_name, chat_ids=[chat_id], waha_client=waha_client,
            trigger_source=SyncCheckpoint.TRIGGER_TARGETED, task_id=task_id,
            is_final_attempt=is_final_attempt,
        )
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
        # No Celery task exists for this path — task_id stays '' (this
        # helper's own default), never fabricated.
        return run_targeted_reconciliation_with_retry(session_name, chat_id)
    if executor == EXECUTOR_CELERY:
        from apps.sync.tasks import reconcile_chat_task

        reconcile_chat_task.delay(session_name, chat_id)
        return None
    raise ImproperlyConfigured(f'Unknown RECONCILIATION_EXECUTOR: {executor!r}')
