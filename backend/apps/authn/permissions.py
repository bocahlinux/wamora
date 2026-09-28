"""Scope-checking DRF permission — Inbox/Chat (canonical Phase 8),
docs/generated/INBOX-CHAT-DECISION-REPORT.md Section 5: the chat/message
read and mark-as-read endpoints require the JWT's `reading` scope, not
just bare authentication. No Django endpoint has checked a JWT scope
before this — only the BFF has (`bff/src/middleware/auth.ts`'s
`requireScope`) — this mirrors that same check on the Django side,
reusing the same `scopes` claim `apps.authn.jwt_utils.compute_scopes()`
already puts in every issued token.
"""

from rest_framework.permissions import BasePermission

from apps.offices.authorization import get_user_office, has_global_access, is_office_admin_role


class HasReadingScope(BasePermission):
    def has_permission(self, request, view):
        claims = request.auth
        if not claims:
            return False
        return 'reading' in claims.get('scopes', [])


class HasSystemAdministrationScope(BasePermission):
    """Phase 13.A — docs/generated/PHASE-13A-MANUAL-RECONCILIATION-RECOVERY-IMPLEMENTATION-REPORT.md.
    Same shape as HasReadingScope, for the 'system administration' scope
    (already defined in settings.JWT_SCOPES/docs/06-SECURITY.md's own
    category names, but never checked by any endpoint before this) — the
    first administrative/state-changing, human-JWT-authenticated Django
    endpoint, so this is the first use of this scope name."""

    def has_permission(self, request, view):
        claims = request.auth
        if not claims:
            return False
        return 'system administration' in claims.get('scopes', [])


class HasBlastScope(BasePermission):
    """Phase 11 (Blast) — same shape as HasReadingScope/
    HasSystemAdministrationScope, for the 'blast' scope (already declared
    in settings.JWT_SCOPES/docs/06-SECURITY.md, but never checked by any
    endpoint before this — docs/generated/PHASE-11-BLAST-DESIGN-AUDIT-REPORT.md
    Section 7). No new scope name introduced."""

    def has_permission(self, request, view):
        claims = request.auth
        if not claims:
            return False
        return 'blast' in claims.get('scopes', [])


class HasUserAdministrationScope(BasePermission):
    """Step 6 (Office & User management) — same shape as the three scope
    checks above, for the 'user administration' scope. This scope name
    was already declared in settings.JWT_SCOPES/docs/06-SECURITY.md since
    early phases (frontend/src/pages/SettingsPage.tsx's own placeholder
    comment names it explicitly as the intended gate for exactly this
    feature) but never checked by any endpoint until now.

    A superuser gets this scope automatically (compute_scopes()'s
    superuser bypass). A non-superuser Global Admin/Office Admin gets it
    only via the 'user administration' Django Group — which this app's
    own views assign/remove as a side effect of assigning/clearing a
    user's `role` (see serializers.py's `_sync_role_groups`, and
    `models.Role` for the Superadmin-editable bundle that field points
    at), so assigning a Role through this app's own API is immediately
    sufficient on the affected user's next login — no separate manual
    Group-assignment command is needed."""

    def has_permission(self, request, view):
        claims = request.auth
        if not claims:
            return False
        return 'user administration' in claims.get('scopes', [])


class HasOfficeAccess(BasePermission):
    """Step 8 (Role x Scope alignment) — TRUE for anyone with a real
    organizational Office role: Superadmin/Global Admin (`has_global_access`)
    or an Office Admin/Operator with a real `OfficeMembership`
    (`get_user_office(user) is not None`). Deliberately independent of
    the `reading` JWT scope/Group.

    Exists because `reading` also gates two GLOBAL, non-Office-aware
    resources (`apps.dashboard`'s stats/activity, and the BFF's session-
    status route) that must NOT open up just because a role legitimately
    needs Office-scoped read access (Inbox). Only applied to views that
    already enforce their own Office boundary elsewhere
    (`apps.chats.authorization.chats_visible_to`/`can_view_chat`) — this
    class only answers "does this user have a role at all", never "which
    Office/rows can they see", exactly like every other permission class
    in this module leaves object-level filtering to the view."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return has_global_access(user) or get_user_office(user) is not None


class HasOfficeAdminAccess(BasePermission):
    """Step 8 (Role x Scope alignment) — TRUE for Superadmin/Global Admin
    (`has_global_access`) or a membership whose `Role` carries
    `is_office_admin` (`apps.offices.authorization.is_office_admin_role`)
    — an ADMINISTRATIVE Office role, excluding a plain Operator.
    Deliberately independent of the `system administration` JWT
    scope/Group.

    Exists because `system administration` also gates Sync Recovery
    (`apps.sync.views.SyncCheckpointRecoveryView`/`SyncCheckpointTaskStateView`),
    a GLOBAL, non-Office-aware admin action that must stay Superadmin/
    scope-only — granting an Office Admin real Blast-approval capability
    must never come bundled with that. Only applied to Blast approve/
    reject, which already enforce their own Office boundary
    (`apps.blast.authorization.can_view_campaign`) and self-approval rule
    unchanged in the view — this class only answers "is this user an
    administrative Office role at all"."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if has_global_access(user):
            return True
        return is_office_admin_role(user)
