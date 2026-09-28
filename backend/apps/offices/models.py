"""Office/unit-kerja foundation — Step 1 of the multi-office roadmap
(docs/generated/GROUP-USER-ARCHITECTURE-DESIGN-AUDIT-REPORT.md).

Deliberately a separate app/model from `django.contrib.auth.models.Group`
(already the JWT-scope mechanism, `apps.authn.jwt_utils.compute_scopes`)
and unrelated to `apps.chats.models.Chat.is_group` (a WhatsApp group
chat) — reusing either name/model here would conflate three unrelated
meanings of "group" in one codebase.

No Role/permission model, no Blast/Inbox wiring, no API/UI — those are
later steps. This is data-model foundation only.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel

# Step 2 (role/permission architecture) — module-level, not class
# attributes, so both `OfficeMembership.ROLE_CHOICES` and the
# `Meta.constraints` Q objects below can share exactly one spelling
# (same convention as `apps.blast.models.OPERATION_TYPE_BLAST_SEND`:
# a nested `Meta` class can't see its outer class's own attributes at
# class-body-evaluation time, so these can't live on OfficeMembership
# itself).
ROLE_GLOBAL_ADMIN = 'global_admin'
ROLE_OFFICE_ADMIN = 'office_admin'
ROLE_OPERATOR = 'operator'


class Office(TimeStampedModel):
    """A business unit (e.g. one Samsat office). `is_active` lets an
    office be retired without deleting it or the historical data that
    references it (memberships, and later Blast campaigns/Inbox chats)."""

    name = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class OfficeMembership(TimeStampedModel):
    """User -> (optionally) Office, plus that user's organizational role
    (Step 2 — role/permission architecture). `OneToOneField` on `user`
    enforces "at most one Office per user" at the database level (per
    the agreed Step 1 design) rather than an app-level convention.

    Office and role are deliberately two different questions ("where
    does this user work" vs. "what is their function") — this table
    answers both, because `GLOBAL_ADMIN` answers the second without an
    answer to the first: a Global Admin is not tied to any one Office,
    so `office` is nullable and a `GLOBAL_ADMIN` row simply has no
    Office set. `OFFICE_ADMIN`/`OPERATOR` are only meaningful *within*
    a specific Office, so their rows always have one — enforced by the
    `office_matches_role` constraint below, not just convention.

    SUPERADMIN is deliberately NOT a role value here — `User.is_superuser`
    already answers that unambiguously (per this step's own brief: "tidak
    perlu dibuat sebagai role database terpisah jika is_superuser ... sudah
    cukup"); a superuser is exempt from this table entirely, exactly like
    Step 1 already established, by simply never having a row.

    This intentionally does NOT touch `django.contrib.auth.models.Group`
    or `apps.authn.jwt_utils.compute_scopes()` — Group remains solely the
    existing JWT-scope mechanism; role here is a separate, organizational
    axis, read directly from this model wherever a later step needs it
    (Blast/Inbox authorization), not folded into the scope claim.

    `on_delete=PROTECT` on both FKs, matching this project's existing
    convention for required FKs to User/other core rows (e.g.
    `apps.blast.models.BlastCampaign.created_by`,
    `apps.chats.models.Chat.session`) — deleting a User or an Office
    that still has a membership must be an explicit, deliberate action
    (remove the membership first), never an accidental cascade."""

    ROLE_CHOICES = [
        (ROLE_GLOBAL_ADMIN, 'Global Admin'),
        (ROLE_OFFICE_ADMIN, 'Office Admin'),
        (ROLE_OPERATOR, 'Operator'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='office_membership'
    )
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name='memberships', null=True, blank=True
    )
    role = models.CharField(max_length=32, choices=ROLE_CHOICES)
    # Step 14 (Operator assignment & availability foundation) — a
    # deliberately separate concept from `User.is_active` (the Django
    # account itself) and from a membership row simply existing/matching
    # an Office (used throughout this codebase as "is this a current,
    # real membership"): `is_available` is the operator's own opt-in
    # signal that they are currently willing to receive a NEW Chat
    # assignment. Meaningful only for `ROLE_OPERATOR` rows in practice
    # (see `apps.chats.assignment.valid_assignment_candidates`, which
    # filters on role too) but kept on this shared table rather than a
    # role-conditional model, matching every other field here.
    #
    # Default `False`, deliberately conservative: existing real
    # OfficeMembership rows (created before this field existed) must NOT
    # suddenly become eligible assignment targets the moment this
    # migration runs — an operator must explicitly opt in via
    # `PATCH /api/auth/me/availability/` first.
    is_available = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(role=ROLE_GLOBAL_ADMIN, office__isnull=True)
                    | Q(role__in=[ROLE_OFFICE_ADMIN, ROLE_OPERATOR], office__isnull=False)
                ),
                name='office_matches_role',
            ),
        ]

    def __str__(self):
        return f'{self.user_id} -> {self.office_id} ({self.role})'


class OfficeInboxConfig(TimeStampedModel):
    """Step 10 — per-Office Inbox configuration FOUNDATION only. Stores
    what an Office's welcome/waiting/offline messages and enabled state
    *are*; nothing here sends a message or drives any WhatsApp flow yet
    (no webhook/persist_message change — deliberately out of this step's
    scope). `OneToOneField` (matching `apps.sync.models.SyncCheckpoint`'s
    own `session = OneToOneField(WahaSession, on_delete=PROTECT, ...)`
    precedent) enforces "at most one config per Office" at the database
    level. `on_delete=PROTECT`, same as every other FK to `Office` in
    this codebase — deleting an Office with a saved config must be an
    explicit, deliberate action.

    Deliberately created LAZILY (`get_or_create` in the view, not a
    signal/override `save()`/data migration) — no row exists for an
    Office until an admin actually saves one, so no existing Office's
    data needs to be touched by this step's migration at all."""

    office = models.OneToOneField(Office, on_delete=models.PROTECT, related_name='inbox_config')
    enabled = models.BooleanField(default=False)
    welcome_message = models.TextField(blank=True, default='')
    waiting_message = models.TextField(blank=True, default='')
    offline_message = models.TextField(blank=True, default='')

    def __str__(self):
        return f'{self.office_id} (enabled={self.enabled})'
