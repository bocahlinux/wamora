"""Authentication for BFF -> Django internal endpoints
(docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 8) — a
static shared secret, deliberately distinct from end-user JWT
authentication (contract requirement #12: "Keep BFF -> Django
authentication separate from end-user JWT authentication"). This
authenticates the BFF *process*, not the frontend user who triggered the
call; the BFF is trusted to have already verified the user's JWT itself.
"""

import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission

HEADER_NAME = 'HTTP_X_INTERNAL_SERVICE_KEY'


class HasInternalServiceKey(BasePermission):
    """Fails closed: if INTERNAL_SERVICE_KEY is unconfigured, no request is
    ever authorized (an empty configured secret would otherwise make an
    empty header "valid")."""

    def has_permission(self, request, view):
        configured = settings.INTERNAL_SERVICE_KEY
        if not configured:
            return False
        provided = request.META.get(HEADER_NAME, '')
        if not provided:
            return False
        return hmac.compare_digest(provided, configured)
