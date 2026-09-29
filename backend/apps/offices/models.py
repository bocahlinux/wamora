"""Office/unit-kerja foundation — Step 1 of the multi-office roadmap
(docs/generated/GROUP-USER-ARCHITECTURE-DESIGN-AUDIT-REPORT.md).

Deliberately a separate app/model from `django.contrib.auth.models.Group`
(already the JWT-scope mechanism, `apps.authn.jwt_utils.compute_scopes`)
and unrelated to `apps.chats.models.Chat.is_group` (a WhatsApp group
chat) — reusing either name/model here would conflate three unrelated
meanings of "group" in one codebase.

Originally no Role/permission model was planned — that decision was
deliberately revisited (see `Role` below): organizational standing
(global vs Office-scoped, administrative authority, operator/assignment
eligibility) and feature/menu access used to be two separate concepts
(a fixed `role` enum here, plus a separate superadmin-managed `Role`) and
are now merged into the one `Role` model every `OfficeMembership` points
at.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel

# The three seeded, built-in Roles' `name` values (created by
# migration 0009) — kept as module-level constants purely so existing
# code/tests that need "the built-in Global Admin/Office Admin/Operator
# Role" can look one up by a stable name
# (`Role.objects.get(name=ROLE_OFFICE_ADMIN)`) rather than a magic
# string repeated everywhere. These are NOT enum values on
# `OfficeMembership` any more — a membership's actual organizational
# standing comes entirely from whichever `Role` row its `role` FK points
# at (see `Role.grants_global_access`/`.is_office_admin`/`.is_operator`
# below), which a Superadmin can freely edit, rename, or combine — these
# three seeded rows are just the ones migrated data started out pointing
# at, not a fixed vocabulary the system enforces.
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


class Role(TimeStampedModel):
    """Superadmin-managed bundle covering BOTH axes every
    `OfficeMembership` used to answer with two separate fields:

      - Feature/menu access — `scopes`, a JSON list of strings validated
        by `RoleSerializer` to be a subset of `settings.JWT_SCOPES` —
        never freeform, so a Role can only ever grant a capability the
        backend genuinely enforces somewhere (`apps.authn.permissions`/
        the BFF's `requireScope`), not an invented one.
      - Organizational standing — `grants_global_access`/
        `is_office_admin`/`is_operator`, three independent booleans (not
        a re-creation of the old fixed 3-value enum) that replace what
        `OfficeMembership.role == 'global_admin'/'office_admin'/
        'operator'` used to mean. `apps.offices.authorization` is the
        ONE place that reads these — every other check
        (`HasOfficeAdminAccess`, `apps.chats.assignment`, Blast
        authorization, self-escalation guards in `views.py`) calls into
        that module, never compares these flags itself.

    Independent booleans, not an enum, because a Superadmin-defined Role
    is no longer required to be exactly one of three fixed shapes — e.g.
    a Role can combine `is_operator=True` with `scopes=['sending']`,
    something the old fixed enum could never express.

    `on_delete=PROTECT` on `OfficeMembership.role` (not `SET_NULL`) —
    deleting a Role that's still assigned to a user must be an explicit,
    deliberate action (reassign or clear it first), matching this
    project's existing convention for every other required-looking FK
    (see `OfficeMembership.office`/`.user` below)."""

    name = models.CharField(max_length=100, unique=True)
    scopes = models.JSONField(default=list, blank=True)
    grants_global_access = models.BooleanField(default=False)
    is_office_admin = models.BooleanField(default=False)
    is_operator = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class UserProfile(TimeStampedModel):
    """Every User's small, role-independent profile — deliberately
    separate from `OfficeMembership` (which a Superadmin never has at
    all, per that model's own "Superadmin, who needs none" precedent)
    since `initial` must be readable for EVERY role, Superadmin
    included. Colocated in this app (not `apps.authn`, which has no
    models of its own) because user creation already lives here
    (`UserCreateSerializer`/`UserListCreateView`).

    Discussed requirement: `initial` is set by whoever creates the user
    (Superadmin/Global Admin/Office Admin, via `UserCreateSerializer`)
    and shown to a citizen when that user claims a chat
    (`apps.chats.assignment.claim_chat`'s own notification) — a short
    signature, e.g. "RD", never the full name. Every role may also edit
    their OWN `initial` (`apps.offices.views.MyProfileView`, self-service).

    `on_delete=CASCADE` on `user` (not `PROTECT`) — unlike every
    Office/Role FK in this project, a User's own profile has no
    independent meaning once the User itself is deleted; there is
    nothing to "reassign first"."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    initial = models.CharField(max_length=10, blank=True, default='')

    def __str__(self):
        return f'{self.user.username} ({self.initial or "—"})'


class OfficeMembership(TimeStampedModel):
    """User -> (optionally) Office, plus that user's `Role` (feature
    access AND organizational standing — see `Role`'s own docstring).
    `OneToOneField` on `user` enforces "at most one Office per user" at
    the database level (per the agreed Step 1 design) rather than an
    app-level convention.

    Office and Role are deliberately two different questions ("where
    does this user work" vs. "what is their function") — this table
    answers both, because a `Role` with `grants_global_access=True`
    answers the second without an answer to the first: such a user is
    not tied to any one Office, so `office` is nullable and that row
    simply has no Office set. Every other Role is only meaningful
    *within* a specific Office, so those rows always have one — enforced
    by the `office_matches_role` constraint below via the denormalized
    `requires_office` flag (see its own field comment for why a plain
    `CheckConstraint` can no longer reference `role.grants_global_access`
    directly now that `role` is a FK to a separate table).

    SUPERADMIN is deliberately NOT representable by any `Role` here —
    `User.is_superuser` already answers that unambiguously (per Step 2's
    own brief: "tidak perlu dibuat sebagai role database terpisah jika
    is_superuser ... sudah cukup"); a superuser is exempt from this table
    entirely, by simply never having a row.

    `on_delete=PROTECT` on every FK, matching this project's existing
    convention for required FKs to User/other core rows (e.g.
    `apps.blast.models.BlastCampaign.created_by`,
    `apps.chats.models.Chat.session`) — deleting a User, an Office, or a
    Role that still has a membership must be an explicit, deliberate
    action (remove/reassign the membership first), never an accidental
    cascade."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='office_membership'
    )
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, related_name='memberships', null=True, blank=True
    )
    # Required (no `null=True`) — organizational standing and feature
    # access are now the same object, so a membership with no Role has
    # neither. `apps.offices.serializers._sync_role_groups` keeps the
    # underlying Django Groups (and so the JWT `scopes` claim) in sync
    # with whatever this points at every time it's assigned.
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name='memberships')
    # Denormalized copy of `not role.grants_global_access`, kept in sync
    # by `apps.offices.serializers._sync_role_groups` every time `role`
    # is assigned — exists ONLY so `Meta.constraints` below can still
    # enforce "Office required unless globally-accessing" at the
    # database level. A plain SQL `CheckConstraint` can check two columns
    # on THIS table but can't join to `role.grants_global_access` on the
    # separate `Role` table — this column is the trade-off that keeps
    # that DB-level guarantee instead of relying on application-level
    # validation (`_validate_role_office`) alone.
    requires_office = models.BooleanField()
    # Step 14 (Operator assignment & availability foundation) — a
    # deliberately separate concept from `User.is_active` (the Django
    # account itself) and from a membership row simply existing/matching
    # an Office (used throughout this codebase as "is this a current,
    # real membership"): `is_available` is the operator's own opt-in
    # signal that they are currently willing to receive a NEW Chat
    # assignment. Meaningful only when `role.is_operator` in practice
    # (see `apps.chats.assignment.valid_assignment_candidates`, which
    # filters on that flag too) but kept on this shared table rather than
    # a role-conditional model, matching every other field here.
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
                    Q(requires_office=False, office__isnull=True)
                    | Q(requires_office=True, office__isnull=False)
                ),
                name='office_matches_role',
            ),
        ]

    def __str__(self):
        return f'{self.user_id} -> {self.office_id} ({self.role_id})'


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
