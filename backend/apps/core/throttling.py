"""Fail-open rate-limit throttling — Phase 13 Track B Finding 1 (HIGH).

DRF's SimpleRateThrottle.allow_request() reads the throttle cache
(settings.CACHES['default'], a RedisCache with no fallback backend —
config/settings.py) with no exception handling of its own. During the
Phase 13 Track B live drill, stopping the dev Redis container turned
every DRF-throttled endpoint into an uncaught redis.exceptions.ConnectionError
inside APIView.dispatch()'s initial() step — BEFORE any view code ran —
i.e. a Redis outage became an HTTP 500 on the entire Django API,
including the health-check endpoints that exist specifically to
diagnose this kind of outage (docs/generated/PHASE-13-TRACK-B-FAILURE-DRILL-REPORT.md).

This module makes that one failure mode fail OPEN instead: if the
throttle cache itself is unreachable, the request is allowed through —
an unavailable rate limiter should not itself become the outage. This
changes nothing when Redis is healthy; Phase 12's rate limits
(docs/generated/PHASE-12-SECURITY-HARDENING-DESIGN-AUDIT-REPORT.md)
apply exactly as before in that case. Every fail-open event is logged
via logger.exception (the same discipline apps.core.views.RedisHealthView
already uses), so it is visible in logs/monitoring, never silent.
"""

import logging

from redis.exceptions import RedisError
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

logger = logging.getLogger(__name__)


class FailOpenOnCacheErrorMixin:
    """Mix in before a DRF throttle base class to fail open (allow the
    request) instead of raising when the underlying cache backend
    (settings.CACHES) is unreachable, e.g. a Redis outage."""

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except RedisError:
            logger.exception(
                "Rate-limit cache unreachable; failing open for this "
                "request (throttle scope=%r)",
                getattr(self, "scope", None),
            )
            return True


class SafeAnonRateThrottle(FailOpenOnCacheErrorMixin, AnonRateThrottle):
    pass


class SafeUserRateThrottle(FailOpenOnCacheErrorMixin, UserRateThrottle):
    pass
