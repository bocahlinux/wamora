"""DRF authentication using the existing Phase 6 JWT contract —
docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 4.

Until now, Django only ever *issued* tokens (`jwt_utils.issue_access_token`)
— verification was documented as BFF-side only ("the BFF verifies
independently using only the public key"). That description was about
who verifies *for the BFF's own routing decisions*; it never said Django
itself could never verify its own issued tokens for its own endpoints.
This class adds exactly that, reusing the exact same settings the BFF
already uses (`JWT_PUBLIC_KEY`, `JWT_ALGORITHM`, `JWT_ISSUER`,
`JWT_AUDIENCE`) — no new key, no new algorithm, no new claim, no change
to the token contract. Needed because `/api/auth/me/` and the two
`/api/dashboard/*` endpoints are called directly by the frontend
(`Frontend -> Django`, per `docs/07-API-CONTRACT.md`), not through the
BFF, so something on the Django side has to check the Bearer token.

Mirrors `bff/src/jwt.ts`'s verification logic closely (same algorithm
pinned explicitly, same issuer/audience check) for consistency between
the two independent verifiers.
"""

import re

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

BEARER_RE = re.compile(r'^Bearer\s+(.+)$')


class JWTAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.META.get('HTTP_AUTHORIZATION', '')
        match = BEARER_RE.match(header)
        if not match:
            # No credentials attempted — let permission_classes (e.g.
            # IsAuthenticated) produce the normal 401, not this class.
            return None

        if not settings.JWT_PUBLIC_KEY:
            raise AuthenticationFailed('Authentication is not available')

        token = match.group(1)
        try:
            payload = jwt.decode(
                token,
                settings.JWT_PUBLIC_KEY,
                algorithms=[settings.JWT_ALGORITHM],
                issuer=settings.JWT_ISSUER,
                audience=settings.JWT_AUDIENCE,
            )
        except jwt.InvalidTokenError:
            # Never echo the underlying library error text back to the
            # client (docs/06-SECURITY.md log redaction) — a single
            # generic message for every invalid-token reason (expired,
            # bad signature, wrong issuer/audience, malformed).
            raise AuthenticationFailed('Invalid or expired token')

        user_id = payload.get('sub')
        User = get_user_model()
        try:
            user = User.objects.get(pk=user_id, is_active=True)
        except (User.DoesNotExist, ValueError, TypeError):
            raise AuthenticationFailed('Invalid or expired token')

        return (user, payload)

    def authenticate_header(self, request):
        # Presence of this makes DRF respond 401 Unauthorized (not 403
        # Forbidden) when no/invalid credentials are supplied — the
        # correct status for a missing/bad Bearer token.
        return 'Bearer'
