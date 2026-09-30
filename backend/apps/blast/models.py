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

import hashlib
import secrets

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.offices.models import Office
from apps.operations.models import OutboundOperation
from apps.waha_sessions.models import WahaSession

# apps.operations.OutboundOperation.operation_type has no `choices` (free
# CharField) — this is the one value this app ever writes there. Kept as a
# module-level constant so apps.blast.limits/tasks/tests share exactly one
# spelling, never a second hardcoded string.
OPERATION_TYPE_BLAST_SEND = 'blastSend'


class BlastTemplate(TimeStampedModel):
    """A reusable message shape with `{{variable}}` placeholders (Discussed
    requirement — vehicle-tax due-date reminders: same wording, different
    citizen/plate/amount per recipient). `content`'s placeholders are never
    declared separately — `apps.blast.templating.extract_variable_names()`
    is the single source of truth for what a template needs, derived from
    `content` itself every time it's read, never a second, driftable copy.

    `key` is deliberately separate from `name`: `key` is what the external
    API (and, internally, `BlastCampaign.template`) references and is
    never expected to change once created; `name` is a freely-renamable
    display label. A `BlastCampaign` created from a template SNAPSHOTS
    `content` into its own `message_template` at creation time (see that
    field's own comment) — editing or deleting a `BlastTemplate` afterward
    never changes what an already-created campaign actually sends.

    `office=None` = a shared/global template (e.g. a province-wide tax
    reminder wording every Samsat Office reuses) — same nullable-FK
    "null means global" convention `BlastCampaign.office`/
    `apps.bot.models.BotMenu.office` already established, not a new one
    invented here."""

    key = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    content = models.TextField()
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, null=True, blank=True, related_name='blast_templates'
    )
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='blast_templates_created'
    )

    def __str__(self):
        return f'{self.name} ({self.key})'


def _generate_api_key() -> str:
    # 32 bytes of CSPRNG entropy, url-safe text — same "generate, hash,
    # show once" shape as GitHub PATs/Stripe secret keys. `secrets` (stdlib)
    # is used rather than `random`, matching this project's existing
    # discipline of using cryptographically appropriate randomness for any
    # security-relevant value.
    return secrets.token_urlsafe(32)


def _hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()


class BlastApiKey(TimeStampedModel):
    """A credential for the external Blast-trigger API
    (`apps.blast.external_views.ExternalBlastSendView`) — genuinely new
    pattern in this codebase (no existing model stores a hashed-at-rest
    per-row secret; every other machine-to-machine credential here,
    `settings.INTERNAL_SERVICE_KEY`/`OFFICE_DISPATCH_SERVICE_KEY`/the WAHA
    webhook HMAC secret, is one static shared value from the environment).
    Built to the same "fails closed, constant-time compare" discipline
    those already follow, just backed by a real, admin-manageable table.

    The raw key is NEVER stored — only `key_hash` (sha256 hex digest,
    compared via `hmac.compare_digest` in the auth check, never `==`).
    `key_prefix` (first 8 characters of the raw key, plaintext) lets an
    admin tell keys apart in a list without ever being able to reconstruct
    or re-display the full secret — the same "shown once at creation,
    unrecoverable after" UX GitHub/Stripe use for their own API keys.

    Discussed requirement — a key is deliberately GLOBAL, not Office-
    scoped, and carries no Office field at all: one key is meant to be
    reused for every kind of send an external caller needs (a single
    ad-hoc message, a freeform blast, or a templated blast), across any
    session/Office. The scoping for any one request is entirely whatever
    `session` that request names
    (`apps.blast.external_views.ExternalBlastSendView`), resolved fully
    server-side from `WahaSession`, never trusted from anywhere else.
    `on_delete=PROTECT` on anything referencing this row (see
    `BlastCampaign.triggered_by_api_key`) means a key is deactivated
    (`is_active=False`), never deleted, so past campaigns stay fully
    attributable even after a key is revoked."""

    name = models.CharField(max_length=255)
    key_hash = models.CharField(max_length=64, unique=True)
    key_prefix = models.CharField(max_length=8)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='blast_api_keys_created'
    )
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.name} ({self.key_prefix}…)'

    @classmethod
    def create_with_raw_key(cls, *, name: str, created_by) -> tuple['BlastApiKey', str]:
        """The ONLY way a `BlastApiKey` is ever created — guarantees the
        raw key and its hash/prefix are always derived together, never
        independently constructed (e.g. never hand-built in a migration or
        a test with a mismatched hash). Returns `(instance, raw_key)` —
        `raw_key` is shown to the caller exactly once and is not
        recoverable from the returned instance afterward."""
        raw_key = _generate_api_key()
        instance = cls.objects.create(
            name=name,
            key_hash=_hash_api_key(raw_key),
            key_prefix=raw_key[:8],
            created_by=created_by,
        )
        return instance, raw_key

    @classmethod
    def authenticate(cls, raw_key: str):
        """Returns the matching active `BlastApiKey`, or `None`. Hashes
        `raw_key` and looks it up by the UNIQUE `key_hash` column (an
        indexed equality lookup, not a linear scan comparing every row) —
        `hmac.compare_digest` isn't needed here for the same reason
        `apps.authn`'s own JWT verification doesn't hand-roll a
        constant-time DB search either: a sha256 digest lookup via a
        unique index reveals nothing timing-wise beyond "some row matched
        or none did", the same guarantee this project's other
        shared-secret checks get from `hmac.compare_digest` on a single
        in-memory value instead."""
        try:
            key = cls.objects.select_related('office').get(key_hash=_hash_api_key(raw_key), is_active=True)
        except cls.DoesNotExist:
            return None
        return key


class BlastSettings(TimeStampedModel):
    """True one-row singleton (no Office scoping — Discussed requirement:
    ONE dynamic delay for every Blast campaign, dashboard or API-triggered
    alike, not two divergent values) — replaces
    `settings.BLAST_INTER_MESSAGE_DELAY_SECONDS` (a static env var,
    confirmed read only by `apps.blast.tasks`) with an admin-editable
    value that takes effect immediately, no restart required. Accessed
    exclusively via `get_settings()` below — never `BlastSettings.objects
    .get(...)` directly, so the lazy-create-on-first-read singleton
    behavior (same idiom `apps.bot.models.BotConfig`'s own GLOBAL row
    already established) lives in exactly one place."""

    inter_message_delay_seconds = models.PositiveIntegerField(default=60)

    def __str__(self):
        return f'BlastSettings(delay={self.inter_message_delay_seconds}s)'


def get_blast_settings() -> BlastSettings:
    instance, _created = BlastSettings.objects.get_or_create(pk=1)
    return instance


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
    # Step 4 (Office integration) — nullable: 5 pre-existing campaigns
    # (audited, all created_by a superuser with no Office membership to
    # infer one from) have no safe Office to backfill onto. NULL means
    # "not Office-bound" and is treated as a distinct, deliberate case
    # by apps.blast.authorization — not an error state, not backfilled.
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, null=True, blank=True, related_name='blast_campaigns'
    )
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
    # Nullable, SET_NULL: the template a campaign was created from, kept
    # only as a "created from" pointer — `message_template` above is
    # always the actual snapshot sent, so editing/deleting this template
    # afterward never changes what this campaign already sends.
    template = models.ForeignKey(
        BlastTemplate, on_delete=models.SET_NULL, null=True, blank=True, related_name='blast_campaigns'
    )
    # Nullable: null = dashboard-created (a human clicked through
    # draft->pending_approval->approved). Set = created directly in
    # `approved` by `apps.blast.external_views.ExternalBlastSendView`.
    # PROTECT (not SET_NULL) — a revoked/deactivated key must still be
    # traceable on every campaign it ever triggered.
    triggered_by_api_key = models.ForeignKey(
        BlastApiKey, on_delete=models.PROTECT, null=True, blank=True, related_name='blast_campaigns'
    )
    # Only ever set (and required) by the external API path, for its
    # `Idempotency-Key` header replay-safety (see the UniqueConstraint
    # below). Always null for dashboard-created campaigns.
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['session', 'status']),
        ]
        constraints = [
            # Scoped to (triggered_by_api_key, idempotency_key) rather than
            # idempotency_key alone — two different external keys are
            # never expected to collide on the same literal string, but
            # scoping this way means one key's replay-safety can never be
            # affected by another's chosen idempotency keys.
            models.UniqueConstraint(
                fields=['triggered_by_api_key', 'idempotency_key'],
                name='unique_blast_campaign_api_key_idempotency_key',
                condition=models.Q(triggered_by_api_key__isnull=False, idempotency_key__isnull=False),
            ),
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
    # A definite (not ambiguous) "this number doesn't exist on WhatsApp"
    # result from WAHA's check-exists endpoint, checked before ever
    # attempting a send — distinct from STATUS_FAILED (a send was
    # attempted and failed) so History can report "how many recipients
    # were bad numbers" separately from "how many sends failed".
    STATUS_INVALID_NUMBER = 'invalid_number'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_SENDING, 'Sending'),
        (STATUS_SENT, 'Sent'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_SKIPPED, 'Skipped'),
        (STATUS_INVALID_NUMBER, 'Invalid number'),
    ]

    TERMINAL_STATUSES = {STATUS_SENT, STATUS_FAILED, STATUS_SKIPPED, STATUS_INVALID_NUMBER}

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
    # Per-recipient placeholder values for `campaign.template`'s
    # `{{var}}` names (empty dict for a freeform, non-templated campaign).
    # Rendered into the actual outbound text only at send time, via
    # apps.blast.templating.render_template — never stored rendered.
    variables = models.JSONField(default=dict, blank=True)

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
