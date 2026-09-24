from django.db import models

from apps.waha_sessions.models import WahaSession


class WebhookEvent(models.Model):
    """docs/04-DATA-MODEL.md WebhookEvent: provider event ID, session, type,
    received time, status, attempts, safe payload representation, processed
    time and error information. Processing must be idempotent.

    Idempotency is enforced via the (session, provider_event_id) unique
    constraint below — the same "stable ID scoped by session" pattern used
    for Message identity, applied to the raw webhook delivery rather than
    the normalized message it eventually produces.

    `payload` must hold a SAFE representation only (docs/06-SECURITY.md log
    redaction requirement). Sanitizing the raw WAHA payload before it is
    stored is the responsibility of the webhook ingestion logic — a later
    phase (see docs/15-CODING-PHASES.md, "Webhook ingestion") — not this
    schema.
    """

    STATUS_PENDING = 'pending'
    STATUS_PROCESSED = 'processed'
    STATUS_FAILED = 'failed'
    STATUS_UNSUPPORTED = 'unsupported'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSED, 'Processed'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_UNSUPPORTED, 'Unsupported'),
    ]

    session = models.ForeignKey(WahaSession, on_delete=models.PROTECT, related_name='webhook_events')
    provider_event_id = models.CharField(max_length=128)
    event_type = models.CharField(max_length=64)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.PositiveIntegerField(default=0)
    payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'provider_event_id'], name='unique_webhook_event_per_session'
            ),
        ]
        indexes = [
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'{self.event_type}:{self.provider_event_id}'
