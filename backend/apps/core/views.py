import logging

from django.db import connection
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class LivenessView(APIView):
    """Backend process liveness only. Deliberately does not touch the
    database — office backend being up and PostgreSQL being reachable are
    distinct signals (docs/01-ARCHITECTURE.md "Failure isolation",
    docs/CLAUDE.md offline rule: office backend/database offline are
    reported separately)."""

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        return Response({'status': 'ok', 'component': 'backend'})


class DatabaseHealthView(APIView):
    """Reports PostgreSQL reachability, independent of backend liveness.
    Never returns raw driver error text (may contain host/user details) —
    see docs/06-SECURITY.md log redaction requirement."""

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
        except Exception:
            logger.exception('Database health check failed')
            return Response(
                {'status': 'error', 'component': 'database'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({'status': 'ok', 'component': 'database'})
