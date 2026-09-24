import logging

from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .authentication import JWTAuthentication
from .jwt_utils import JwtNotConfigured, issue_access_token
from .serializers import LoginSerializer

logger = logging.getLogger(__name__)


class LoginView(APIView):
    """Issues a JWT access token for an authenticated Django user
    (docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 4).
    Public endpoint — this is the credential check itself, so no
    authentication is required to reach it.

    Rate limiting (docs/06-SECURITY.md "Rate limits: login, ...") is
    explicitly Phase 12 (Security hardening) scope, not implemented here —
    restated in docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md's
    own phase boundary (Section 15). Not silently added, not silently
    omitted from the record.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = authenticate(
            request,
            username=serializer.validated_data['username'],
            password=serializer.validated_data['password'],
        )
        if user is None:
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
            return Response(
                {'error': {'code': 'auth_not_configured', 'message': 'Authentication is not available'}},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(token, status=status.HTTP_200_OK)


class MeView(APIView):
    """Phase 8 dashboard backend foundation — identifies the caller of a
    Django-issued JWT for the frontend's own use (e.g. showing who is
    logged in), without exposing anything beyond the minimal safe fields
    below. No password, hash, email, or scope/claim data is returned."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            'id': user.pk,
            'username': user.username,
            'display_name': user.get_full_name() or user.username,
        })
