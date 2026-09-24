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

    session = models.OneToOneField(WahaSession, on_delete=models.PROTECT, related_name='sync_checkpoint')
    checkpoint_value = models.CharField(max_length=255, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_IDLE)
    lag_seconds = models.PositiveIntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    def __str__(self):
        return f'checkpoint:{self.session_id}'
