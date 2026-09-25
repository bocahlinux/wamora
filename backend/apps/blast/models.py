"""Phase 11 — Blast (controlled bulk WhatsApp send).

docs/generated/PHASE-11-BLAST-DESIGN-AUDIT-REPORT.md Section 3, adjusted
for the finalized decisions in this phase's implementation prompt (state
machine names/branches, limits, approval self-check, no auto-retry/resume).

`BlastRecipient` reuses `apps.operations.OutboundOperation` for
idempotency/status tracking of the actual WAHA send (Section 3.3/6 of the
audit) rather than a parallel mechanism — `operation_type='blastSend'`,
linked via `outbound_operation`. The deterministic idempotency key
(`blast:{campaign_id}:{recipient_id}`) is derived, not stored, via the
`idempotency_key` property below — it is fully computable from the two
FKs already on the row, so persisting a third, potentially-stale copy of
the same value was deliberately not added (a documented deviation from
the design audit's Section 3.2 proposal, which listed it as a stored
field).
"""

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.operations.models import OutboundOperation
from apps.waha_sessions.models import WahaSession

# apps.operations.OutboundOperation.operation_type has no `choices` (free
# CharField) — this is the one value this app ever writes there. Kept as a
# module-level constant so apps.blast.limits/tasks/tests share exactly one
# spelling, never a second hardcoded string.
OPERATION_TYPE_BLAST_SEND = 'blastSend'


class BlastCampaign(TimeStampedModel):
    """One bulk-send campaign, scoped to a single WahaSession (the 500/day
    limit is per-session — decision 3.2 of the finalized decisions)."""

    STATUS_DRAFT = 'draft'
    STATUS_PENDING_APPROVAL = 'pending_approval'
    STATUS_APPROVED = 'approved'
    STATUS_SENDING = 'sending'
    STATUS_COMPLETED = 'completed'
    STATUS_REJECTED = 'rejected'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PENDING_APPROVAL, 'Pending approval'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_SENDING, 'Sending'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_FAILED, 'Failed'),
    ]

    # Explicit allowed-transitions table (finalized decision 2) — every
    # status-changing write in views.py/tasks.py must check this before
    # writing, never trust a client-supplied or implicitly-assumed status.
    # `failed` is reachable only from `sending` (all-recipients-failed,
    # decided by apps.blast.tasks._maybe_finalize_campaign — never a
    # direct API transition), and both `rejected` and `failed` are
    # terminal, same as `completed`.
    ALLOWED_TRANSITIONS = {
        STATUS_DRAFT: {STATUS_PENDING_APPROVAL},
        STATUS_PENDING_APPROVAL: {STATUS_APPROVED, STATUS_REJECTED},
        STATUS_APPROVED: {STATUS_SENDING},
        STATUS_SENDING: {STATUS_COMPLETED, STATUS_FAILED},
        STATUS_COMPLETED: set(),
        STATUS_REJECTED: set(),
        STATUS_FAILED: set(),
    }

    session = models.ForeignKey(WahaSession, on_delete=models.PROTECT, related_name='blast_campaigns')
    name = models.CharField(max_length=255)
    message_template = models.TextField()
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='blast_campaigns_created'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='blast_campaigns_approved',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['session', 'status']),
        ]

    def __str__(self):
        return f'{self.name} ({self.status})'

    @classmethod
    def is_valid_transition(cls, from_status: str, to_status: str) -> bool:
        return to_status in cls.ALLOWED_TRANSITIONS.get(from_status, set())


class BlastRecipient(TimeStampedModel):
    """One recipient within a BlastCampaign. `sending` guards against a
    double-pick under Celery's at-least-once task delivery (claimed via a
    compare-and-set update in apps.blast.tasks, never a blind .save()).
    `skipped` is reserved for a future cancel/resume feature (decision 6:
    no resume mechanism in v1) — no code path in this implementation sets
    it, but it is kept in the enum so a future phase can add cancellation
    without a further migration."""

    STATUS_PENDING = 'pending'
    STATUS_SENDING = 'sending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_SKIPPED = 'skipped'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENDING, 'Sending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SKIPPED, 'Skipped'),
    ]

    TERMINAL_STATUSES = {STATUS_SENT, STATUS_FAILED, STATUS_SKIPPED}

    campaign = models.ForeignKey(BlastCampaign, on_delete=models.CASCADE, related_name='recipients')
    destination = models.CharField(max_length=128)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    # A safe-to-display string only (decision 5) — never a raw WAHA/internal
    # exception message. See apps.blast.tasks.SAFE_FAILURE_MESSAGE.
    failure_reason = models.CharField(max_length=255, blank=True)
    outbound_operation = models.ForeignKey(
        OutboundOperation, on_delete=models.PROTECT, null=True, blank=True, related_name='blast_recipients'
    )

    class Meta:
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['scheduled_for']),
            models.Index(fields=['campaign', 'status']),
        ]
        constraints = [
            # A duplicate destination within one campaign is almost always
            # an input mistake (e.g. a pasted list with a repeated number);
            # rejecting it at the DB level also keeps the per-campaign
            # dispatch schedule and the daily-cap count from double-
            # counting the same phone number. Not specified by the
            # finalized decisions — an implementation-detail call, noted
            # in the implementation report.
            models.UniqueConstraint(fields=['campaign', 'destination'], name='unique_blast_campaign_destination'),
        ]

    def __str__(self):
        return f'{self.destination} ({self.status})'

    @property
    def idempotency_key(self) -> str:
        """Deterministic — `blast:{campaign_id}:{recipient_id}` — per
        design audit Section 6. Requires the recipient to already have a
        primary key (always true by the time apps.blast.tasks calls this,
        since recipients are persisted at campaign-creation time)."""
        return f'blast:{self.campaign_id}:{self.pk}'
