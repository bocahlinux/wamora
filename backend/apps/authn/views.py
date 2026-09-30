import logging

from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.offices.authorization import get_user_office, has_global_access

from .authentication import JWTAuthentication
from .jwt_utils import JwtNotConfigured, issue_access_token
from .serializers import LoginSerializer
from .throttling import LoginRateThrottle

logger = logging.getLogger(__name__)

# Phase 12 (Security hardening) MUST-FIX #3 — audit-log action name for
# this endpoint, used for both the success and failure outcomes below (the
# single 'result' field on AuditLog already distinguishes them — no
# separate action name is needed for the two cases).
LOGIN_AUDIT_ACTION = 'auth.login'


class LoginView(APIView):
    """Issues a JWT access token for an authenticated Django user
    (docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 4).
    Public endpoint — this is the credential check itself, so no
    authentication is required to reach it.

    Phase 12 (Security hardening) — docs/generated/PHASE-12-SECURITY-HARDENING-DESIGN-AUDIT-REPORT.md
    Section 3.5/3.6: rate limiting and audit logging, both previously
    absent, are now applied here:
      - `throttle_classes = [LoginRateThrottle]` — a strict, IP-keyed
        5/minute limit (apps/authn/throttling.py), replacing the
        project-wide default throttle for this one view.
      - Every outcome (success AND failure) writes an `AuditLog` row
        (action='auth.login') — see `_audit_login` below. Login lockout
        (account-level) was explicitly decided AGAINST for v1; rate
        limiting plus this audit trail are the only controls.
    """

    authentication_classes = []
    permission_classes = []
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Only ever the raw string the client submitted, never included in
        # any log line beyond this one safe field — the password itself is
        # never logged/audited anywhere in this method or on any exception
        # path below (docs/06-SECURITY.md "log redaction").
        attempted_username = serializer.validated_data['username']

        user = authenticate(
            request,
            username=attempted_username,
            password=serializer.validated_data['password'],
        )
        if user is None:
            self._audit_login(attempted_username, AuditLog.RESULT_FAILURE)
            # Deliberately generic — never reveal whether the username
            # exists (standard practice, not documented by any project
            # spec but not contradicted by one either).
            return Response(
                {'error': {'code': 'invalid_credentials', 'message': 'Invalid username or password'}},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            token = issue_access_token(user)
        except JwtNotConfigured:
            logger.error('Login succeeded but JWT signing key is not configured')
            # The credential check itself succeeded; only token issuance
            # failed afterward — audited as a failure outcome for this
            # login attempt (the caller never received a usable session),
            # not a success.
            self._audit_login(attempted_username, AuditLog.RESULT_FAILURE)
            return Response(
                {'error': {'code': 'auth_not_configured', 'message': 'Authentication is not available'}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        self._audit_login(attempted_username, AuditLog.RESULT_SUCCESS, actor=user)
        return Response(token, status=status.HTTP_200_OK)

    @staticmethod
    def _audit_login(username, result, actor=None):
        """Mirrors the AuditLog.objects.create(...) pattern already used
        elsewhere (e.g. apps/sync/views.py's SyncCheckpointRecoveryView,
        called directly, not defensively wrapped — the same convention is
        kept here) — same fields, same call shape. `actor` is the
        authenticated user on success, or None on failure (there is no
        authenticated Django user to attribute a failed attempt to;
        `target` below carries the attempted username instead, the same
        "encode identifying context in target" convention already used
        elsewhere since AuditLog has no metadata/JSON field by design,
        apps/audit/models.py's own docstring).
        """
        AuditLog.objects.create(
            actor=actor,
            action=LOGIN_AUDIT_ACTION,
            target=username,
            result=result,
        )


class MeView(APIView):
    """Phase 8 dashboard backend foundation — identifies the caller of a
    Django-issued JWT for the frontend's own use (e.g. showing who is
    logged in), without exposing anything beyond the minimal safe fields
    below. `is_superuser` lets the UI mirror the Blast self-approval UX;
    backend authorization continues to read the authenticated Django user.
    No password, hash, email, or scope/claim data is returned.

    `has_global_access`/`office` — Step 4 (Blast<->Office integration):
    the minimal addition needed for the frontend to decide whether to
    show an Office picker (globally-accessing users) or a fixed, already-
    assigned Office (everyone else) when creating a Blast campaign. Reads
    `apps.offices.authorization` directly — the same single source of
    truth every backend Office/role check already uses — rather than
    re-deriving anything here."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        office = get_user_office(user)
        membership = getattr(user, 'office_membership', None)
        return Response({
            'id': user.pk,
            'username': user.username,
            'display_name': user.get_full_name() or user.username,
            'is_superuser': user.is_superuser,
            'has_global_access': has_global_access(user),
            'office': {'id': office.pk, 'name': office.name} if office else None,
            # Step 6 (Office & User management), extended by the Role
            # merge — the smallest addition needed for the frontend to
            # decide whether to show the Settings admin UI for an Office
            # Admin too, not just a globally-accessing user
            # (`has_global_access` alone doesn't cover that case), now via
            # `role.is_office_admin`. `None` for a Superadmin or anyone
            # without a membership row at all. `scopes` is included so the
            # frontend need not separately fetch the Role to know what
            # this account's own Role grants.
            'role': {
                'id': membership.role_id,
                'name': membership.role.name,
                'scopes': membership.role.scopes,
                'grants_global_access': membership.role.grants_global_access,
                'is_office_admin': membership.role.is_office_admin,
                'is_operator': membership.role.is_operator,
                # Discussed requirement — Menu Access. Raw, unresolved
                # value: `null` means "not customized" (frontend Sidebar
                # falls back to its own existing scope/has_global_access-
                # derived default visibility per item); `[]` means
                # "show nothing" (a deliberate, explicit choice — see
                # Role's own docstring for why this isn't collapsed into
                # the same meaning as `null`); a non-empty list is a
                # strict allowlist of `apps.offices.menu_items
                # .MENU_ITEM_KEYS` values. Left for the frontend to
                # interpret (same "backend hands over data, frontend owns
                # the fallback rule" split as `scopes` -> Sidebar's own
                # requiredScope checks) rather than resolved here, since
                # resolving it would require this endpoint to know the
                # frontend's own route/menu structure.
                'visible_menu_items': membership.role.visible_menu_items,
            } if membership else None,
            # Step 14 (Operator assignment & availability foundation) —
            # the smallest addition needed for the frontend to render the
            # operator's OWN current availability toggle correctly on
            # load, instead of guessing/defaulting it locally. `None` for
            # anyone without a membership row (including Superadmin) —
            # meaningful only alongside `role.is_operator`, same as
            # every other membership-only field here.
            'is_available': membership.is_available if membership else None,
            # Discussed requirement — the smallest addition needed for
            # the frontend to append "- {initial}" to every manually-typed
            # Inbox reply (InboxPage.tsx's handleSend), without a second
            # request to GET /api/auth/me/profile/. `''` for anyone who
            # hasn't set one yet (never backfilled — see
            # apps.offices.models.UserProfile's own docstring).
            'initial': getattr(getattr(user, 'profile', None), 'initial', '') or '',
        })
