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
