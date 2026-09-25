import logging

import redis
from django.conf import settings
from django.db import connection
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

# Bounded so an unreachable Redis can't make this endpoint hang — no
# persistent Redis connection is held anywhere in the Django process
# (no cache backend, no session store), so every call constructs a
# fresh client and a fresh TCP attempt. No existing timeout value in
# this codebase anchors this specific number (see
# docs/generated/PHASE9-1C-DESIGN-AUDIT-REPORT.md Section 6); a
# hardcoded module constant, not `.env`-configurable, matching the same
# "conservative fixed default" pattern already used for
# STALE_THRESHOLD_MULTIPLIER (apps/sync/views.py, Phase 9.1A).
REDIS_HEALTH_TIMEOUT_SECONDS = 2


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


class RedisHealthView(APIView):
    """Reports Redis (the Celery broker/result backend, `settings.CELERY_BROKER_URL`)
    reachability, independent of backend/database liveness. Never
    returns raw connection details (may contain host/credentials) — see
    docs/06-SECURITY.md log redaction requirement.

    Deliberately narrow: a raw `PING` against Redis only, nothing else.
    Does NOT call `celery.control.ping()` or any Celery worker-inspection
    API, and does NOT infer or imply that a reachable Redis means a
    Celery worker is alive — those remain separate, unresolved questions
    (docs/generated/PHASE9-1C-DESIGN-AUDIT-REPORT.md Section 10)."""

    authentication_classes = []
    permission_classes = []

    def get(self, request):
        try:
            client = redis.Redis.from_url(
                settings.CELERY_BROKER_URL,
                socket_connect_timeout=REDIS_HEALTH_TIMEOUT_SECONDS,
                socket_timeout=REDIS_HEALTH_TIMEOUT_SECONDS,
            )
            client.ping()
        except Exception:
            logger.exception('Redis health check failed')
            return Response(
                {'status': 'error', 'component': 'redis'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({'status': 'ok', 'component': 'redis'})
