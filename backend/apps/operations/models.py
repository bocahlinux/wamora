from django.db import models

from apps.audit.models import AuditLog
from apps.core.models import TimeStampedModel
from apps.waha_sessions.models import WahaSession


class OutboundOperation(TimeStampedModel):
    """docs/04-DATA-MODEL.md OutboundOperation: idempotency key, session,
    destination, operation, status, provider message ID if available,
    timestamps and audit relation.

    docs/05-WEBHOOK-SYNC-DESIGN.md "Outbound during outage": use an
    idempotency key; never blindly resend an operation whose success is
    uncertain — STATUS_UNKNOWN below models that ambiguous-outcome case
    explicitly, not just success/failure.

    A generic payload/content field is intentionally NOT included here: the
    source document lists exactly the fields above, and the actual message
    content is owned by the Message model once an operation is resolved.
    """

    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_UNKNOWN = 'unknown'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_UNKNOWN, 'Unknown'),
    ]

    session = models.ForeignKey(WahaSession, on_delete=models.PROTECT, related_name='outbound_operations')
    idempotency_key = models.CharField(max_length=128)
    destination = models.CharField(max_length=128)
    operation_type = models.CharField(max_length=32)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    provider_message_id = models.CharField(max_length=128, blank=True)
    audit_log = models.ForeignKey(
        AuditLog, on_delete=models.SET_NULL, null=True, blank=True, related_name='outbound_operations'
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'idempotency_key'], name='unique_outbound_idempotency_key'
            ),
        ]
        indexes = [
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'{self.operation_type}:{self.idempotency_key}'
