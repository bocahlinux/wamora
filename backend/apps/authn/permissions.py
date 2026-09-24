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
