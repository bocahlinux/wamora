"""JWT issuance — docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md
Section 4. Django is the sole issuer; verification happens independently on
the BFF side using only the public key (not implemented here — the BFF is a
separate Node/TypeScript process). This module never verifies tokens, only
issues them.

Since Phase 8's dashboard backend foundation, Django also verifies tokens
for endpoints the frontend calls directly (not through the BFF) — see
`apps/authn/authentication.py`. That is a second, independent consumer of
the same public key/issuer/audience/algorithm defined below; nothing about
issuance, the signing key, or the token contract changed.

v1 behavior, stated explicitly: every token's header carries `kid`
(settings.JWT_KID), but the BFF's verifier (bff/src/jwt.ts) does not read
it and checks against exactly one statically-configured public key — there
is no multi-key registry, no JWKS endpoint, no rotation mechanism actually
wired up. `kid` is included only for forward compatibility, in case a
future rotation mechanism is built; it does nothing today. Do not read
"kid is present" as "key rotation is supported."
"""

import time

import jwt
from django.conf import settings


class JwtNotConfigured(Exception):
    """Raised when JWT_PRIVATE_KEY (or JWT_PRIVATE_KEY_PATH) is not set —
    fails closed rather than issuing an unsigned or weakly-signed token."""


def compute_scopes(user) -> list:
    """docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 5:
    "how Django's existing auth.User/Group/Permission model maps to these
    specific scope strings is an implementation detail." Implemented as:
    every scope name in settings.JWT_SCOPES that also matches a Group the
    user belongs to, plus all of them unconditionally for a superuser.
    Deliberately does not touch django.contrib.auth.Permission — Group
    membership is the simplest mechanism that satisfies "separate
    permissions for session control, reading, sending, ..." without
    inventing a new permission model.
    """
    if user.is_superuser:
        return list(settings.JWT_SCOPES)
    group_names = set(user.groups.values_list('name', flat=True))
    return [scope for scope in settings.JWT_SCOPES if scope in group_names]


def issue_access_token(user) -> dict:
    """Returns {"access_token": ..., "token_type": "Bearer", "expires_in": ...}.
    Raises JwtNotConfigured if no private key is available."""
    if not settings.JWT_PRIVATE_KEY:
        raise JwtNotConfigured('JWT_PRIVATE_KEY (or JWT_PRIVATE_KEY_PATH) is not configured')

    now = int(time.time())
    lifetime = settings.JWT_ACCESS_TOKEN_LIFETIME_SECONDS
    payload = {
        'sub': str(user.pk),
        'iss': settings.JWT_ISSUER,
        'aud': settings.JWT_AUDIENCE,
        'iat': now,
        'exp': now + lifetime,
        'scopes': compute_scopes(user),
    }
    token = jwt.encode(
        payload,
        settings.JWT_PRIVATE_KEY,
        algorithm=settings.JWT_ALGORITHM,
        headers={'kid': settings.JWT_KID},
    )
    return {'access_token': token, 'token_type': 'Bearer', 'expires_in': lifetime}
