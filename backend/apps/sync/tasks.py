"""Celery tasks (Phase 5). Thin orchestration only — all business logic
stays in apps.sync.reconciliation, per the task-design instruction to
reuse the existing service layer rather than duplicate it.

docs/05-WEBHOOK-SYNC-DESIGN.md's "reconciliation job" is the only
recurring background job documented anywhere in this project — Celery
beat was provisioned specifically for this (docs/00-MASTER-SPEC.md,
docs/08-DEPLOYMENT.md). Webhook ingestion (Phase 3) deliberately remains
synchronous: nothing in the docs asks for it to move to Celery, it has no
external I/O to offload (pure DB writes), and WAHA expects a prompt HTTP
response — moving it to a background queue would add complexity with no
documented benefit. See docs/generated/PHASE-5-CELERY-REDIS.md for the
full reasoning.

IDEMPOTENCY: entirely inherited from apps.sync.reconciliation.reconcile_session
and the underlying (session, provider_message_id) database constraint
(Phase 2/4) — nothing new is added here. A task retry is safe purely
because re-running reconcile_session is already safe to re-run; this
module adds no idempotency logic of its own, by design.
"""

import logging

from celery import shared_task

from apps.sync.executors import run_targeted_reconciliation_with_retry
from apps.sync.models import SyncCheckpoint
from apps.sync.reconciliation import reconcile_session
from apps.waha_sessions.models import WahaSession

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def reconcile_session_task(self, session_name, limit=100, max_pages=10):
    """Thin wrapper around reconcile_session. Bounded, backed-off retry is
    a conservative safety net for transient failures (e.g. a momentary DB
    or network blip) — not documented anywhere as a requirement, chosen
    because retrying is provably safe (idempotent) rather than because a
    specific retry policy was specified. A permanent failure (e.g. the
    session no longer exists) simply exhausts its 3 retries and is
    recorded as failed — no retry policy can distinguish that case without
    inventing an undocumented taxonomy of error types."""
    result = reconcile_session(
        session_name, limit=limit, max_pages=max_pages,
        trigger_source=SyncCheckpoint.TRIGGER_PERIODIC, task_id=self.request.id,
        # PHASE-4-9-CELERY-WORKER-LIVENESS-IMPLEMENTATION-REPORT.md: only
        # the truly last attempt (no retries left) should write the
        # checkpoint to a terminal STATUS_ERROR on an unexpected exception
        # -- see reconcile_session()'s own `is_final_attempt` docstring.
        is_final_attempt=self.request.retries >= self.max_retries,
    )
    logger.info(
        'reconcile_session_task session=%s chats_processed=%d messages_inserted=%d '
        'chats_discovered=%d had_error=%s',
        session_name, result.chats_processed, result.messages_inserted,
        result.chats_discovered, result.had_error,
    )
    return {
        'session_name': session_name,
        'chats_processed': result.chats_processed,
        'messages_inserted': result.messages_inserted,
        'messages_skipped_existing': result.messages_skipped_existing,
        'messages_failed': result.messages_failed,
        'chats_discovered': result.chats_discovered,
        'chat_discovery_error': result.chat_discovery_error,
        'had_error': result.had_error,
    }


@shared_task(
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def reconcile_chat_task(self, session_name, chat_id):
    """Celery-executor counterpart to `RECONCILIATION_EXECUTOR=sync`'s
    in-process call — both ultimately run the exact same
    apps.sync.executors.run_targeted_reconciliation_with_retry, so the
    only difference between executors is WHERE this runs (a Celery
    worker vs. inline in the Django request thread), never WHAT it does.
    docs/generated/INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md.

    Deliberately separate from reconcile_session_task (the periodic,
    full-session job) rather than overloading it: this task's retry
    policy exists to wait out WAHA's REST-history lag for ONE just-sent
    message, a different concern from that task's transient-failure
    safety net, and keeping them apart means neither's tests or behavior
    can accidentally affect the other."""
    result = run_targeted_reconciliation_with_retry(
        session_name, chat_id, task_id=self.request.id,
        # Same reasoning as reconcile_session_task above.
        is_final_attempt=self.request.retries >= self.max_retries,
    )
    logger.info(
        'reconcile_chat_task session=%s chat_id=%s messages_inserted=%d had_error=%s',
        session_name, chat_id, result.messages_inserted, result.had_error,
    )
    return {
        'session_name': session_name,
        'chat_id': chat_id,
        'messages_inserted': result.messages_inserted,
        'had_error': result.had_error,
    }


@shared_task
def reconcile_all_sessions_task():
    """Periodic entry point (Celery beat — config/celery.py). Dispatches
    one reconcile_session_task per known WahaSession so that one session's
    failure/retry is isolated from the others, rather than one task
    looping over every session itself."""
    session_names = list(WahaSession.objects.values_list('name', flat=True))
    for session_name in session_names:
        reconcile_session_task.delay(session_name)
    return {'sessions_dispatched': len(session_names)}
