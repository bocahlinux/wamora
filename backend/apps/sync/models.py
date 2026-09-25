from django.db import models

from apps.core.models import TimeStampedModel
from apps.waha_sessions.models import WahaSession


class SyncCheckpoint(TimeStampedModel):
    """docs/04-DATA-MODEL.md SyncCheckpoint: session, checkpoint, last run,
    status and lag/error. One checkpoint per session — reconciliation
    (docs/05-WEBHOOK-SYNC-DESIGN.md: "fetch history -> compare stable IDs ->
    insert missing records -> advance checkpoint") advances this pointer as
    it progresses."""

    STATUS_IDLE = 'idle'
    STATUS_RUNNING = 'running'
    STATUS_OK = 'ok'
    STATUS_ERROR = 'error'
    STATUS_CHOICES = [
        (STATUS_IDLE, 'Idle'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_OK, 'Ok'),
        (STATUS_ERROR, 'Error'),
    ]

    # docs/generated/NEXT-PHASE-RECONCILIATION-OBSERVABILITY-DESIGN-AUDIT-REPORT.md
    # Section 8/13 — minimal execution-provenance metadata, not a new
    # execution-history table (explicitly out of scope). Exactly the three
    # trigger call sites that actually exist in this codebase
    # (apps/sync/reconciliation.py's callers) — no invented category:
    # - TRIGGER_PERIODIC: Celery beat -> reconcile_all_sessions_task ->
    #   reconcile_session_task (apps/sync/tasks.py) — always Celery.
    # - TRIGGER_TARGETED: apps.sync.executors.trigger_reconciliation() —
    #   either EXECUTOR_SYNC (in-process, no Celery task) or
    #   EXECUTOR_CELERY (reconcile_chat_task) — distinguished from each
    #   other by whether last_run_task_id is populated, not by a second
    #   trigger_source value (a targeted run is a targeted run regardless
    #   of which executor ran it).
    # - TRIGGER_MANAGEMENT_COMMAND: `manage.py reconcile`
    #   (apps/sync/management/commands/reconcile.py) — never Celery.
    TRIGGER_PERIODIC = 'periodic'
    TRIGGER_TARGETED = 'targeted'
    TRIGGER_MANAGEMENT_COMMAND = 'management_command'
    TRIGGER_SOURCE_CHOICES = [
        (TRIGGER_PERIODIC, 'Periodic'),
        (TRIGGER_TARGETED, 'Targeted'),
        (TRIGGER_MANAGEMENT_COMMAND, 'Management command'),
    ]

    session = models.OneToOneField(WahaSession, on_delete=models.PROTECT, related_name='sync_checkpoint')
    checkpoint_value = models.CharField(max_length=255, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_IDLE)
    lag_seconds = models.PositiveIntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    # Set at the START of a run (not only on completion) so the metadata
    # is already visible even if the run gets stuck — see reconciliation.py.
    # Never cleared; always describes the most recent known run, matching
    # every other "last_*" field already on this model.
    last_run_trigger_source = models.CharField(max_length=32, choices=TRIGGER_SOURCE_CHOICES, blank=True)
    # Empty string (this model's existing CharField convention for "no
    # value", matching checkpoint_value/last_error above) for the two
    # trigger sources that have no Celery task at all (EXECUTOR_SYNC,
    # management command) — never fabricated, never the checkpoint's own
    # id/timestamp.
    last_run_task_id = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return f'checkpoint:{self.session_id}'
