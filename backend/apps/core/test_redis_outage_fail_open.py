"""Phase 13 Track B Finding 1 (HIGH) — regression coverage.

The live failure drill (docs/generated/PHASE-13-TRACK-B-FAILURE-DRILL-REPORT.md)
found that stopping the dev Redis container turned every DRF-throttled
endpoint into an HTTP 500: `SimpleRateThrottle.allow_request()` calls
`self.cache.get(...)` with no exception handling, and this project's
cache backend is Redis with no fallback (`settings.py` CACHES). This
file proves the fix (`apps.core.throttling.FailOpenOnCacheErrorMixin`,
`SafeAnonRateThrottle`/`SafeUserRateThrottle`, and the `throttle_classes = []`
exemption on the three health views) at two levels:

1. Unit level — the mixin itself fails open on `RedisError` and behaves
   identically to the underlying DRF throttle otherwise.
2. Behavioral level — real HTTP requests through the actual DRF
   dispatch path (`APITestCase` client), with the real default cache
   backend's `.get()` patched to raise `redis.exceptions.ConnectionError`,
   proving no endpoint 500s because of it — including the login endpoint
   (which uses its own `LoginRateThrottle`, not the project defaults)
   and the three health endpoints (exempted from throttling entirely).

`config.settings_test` runs against `LocMemCache`, not Redis (see that
module's own docstring) — so every test below patches the cache
explicitly to *simulate* a `RedisError`, rather than relying on an
actually-unreachable Redis instance existing in this environment.
"""

from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache as django_cache
from django.test import override_settings
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.test import APITestCase

from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.authn.throttling import LoginRateThrottle
from apps.core.throttling import SafeAnonRateThrottle, SafeUserRateThrottle

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()


class _FakeRequest:
    def __init__(self, user=None, remote_addr='127.0.0.1'):
        self.user = user
        self.META = {'REMOTE_ADDR': remote_addr}


class FailOpenMixinUnitTests(APITestCase):
    """Direct, no-HTTP unit coverage of the mixin's own allow_request()."""

    def _throttle_raising(self, throttle_cls, exc):
        throttle = throttle_cls()
        with mock.patch.object(django_cache, 'get', side_effect=exc):
            return throttle.allow_request(_FakeRequest(), view=None)

    def test_safe_anon_throttle_allows_request_on_redis_error(self):
        allowed = self._throttle_raising(
            SafeAnonRateThrottle, RedisConnectionError('Connection refused')
        )
        self.assertTrue(allowed, 'SafeAnonRateThrottle must fail OPEN (allow the request) on a RedisError')

    def test_safe_user_throttle_allows_request_on_redis_error(self):
        user = User.objects.create_user('fail-open-user', password='pw')
        allowed = self._throttle_raising(
            SafeUserRateThrottle, RedisConnectionError('Connection refused')
        )
        self.assertTrue(allowed)
        user.delete()

    def test_login_throttle_allows_request_on_redis_error(self):
        allowed = self._throttle_raising(LoginRateThrottle, RedisConnectionError('Connection refused'))
        self.assertTrue(allowed, 'LoginRateThrottle must also fail open — it is the throttle in front of /api/auth/login/')

    def test_fail_open_event_is_logged_not_silent(self):
        throttle = SafeAnonRateThrottle()
        with mock.patch.object(django_cache, 'get', side_effect=RedisConnectionError('boom')):
            with self.assertLogs('apps.core.throttling', level='ERROR'):
                throttle.allow_request(_FakeRequest(), view=None)

    def test_safe_throttle_still_enforces_the_limit_when_cache_is_healthy(self):
        """The mixin must change nothing about normal (Redis-up) behavior —
        no security regression from Phase 12: this reproduces the request
        immediately over the throttle's own recorded history without any
        RedisError involved, and confirms it is still rejected."""
        # RFC 5737 TEST-NET-3 address, used only by this one test, so this
        # throttle-history cache key cannot collide with any other test in
        # the suite that exercises the real 'anon' throttle from the
        # Django test client's own default remote address.
        request = _FakeRequest(remote_addr='203.0.113.77')
        throttle = SafeAnonRateThrottle()
        throttle.rate = '1/min'
        throttle.num_requests, throttle.duration = throttle.parse_rate(throttle.rate)
        self.assertTrue(throttle.allow_request(request, view=None))
        second_throttle = SafeAnonRateThrottle()
        second_throttle.rate = '1/min'
        second_throttle.num_requests, second_throttle.duration = second_throttle.parse_rate(second_throttle.rate)
        self.assertFalse(
            second_throttle.allow_request(request, view=None),
            'A second request within the same window must still be throttled normally '
            'when the cache is healthy — the fail-open path must not weaken the '
            'normal-operation rate limit (Phase 12).',
        )


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
)
class RedisOutageBehavioralTests(APITestCase):
    """Real HTTP requests, with the real cache backend patched to raise —
    proves the fix through the actual DRF dispatch path, not just the
    throttle class in isolation."""

    def setUp(self):
        self.user = User.objects.create_user('redis-outage-user', password='pw')
        self.token = issue_access_token(self.user)['access_token']

    def _redis_down(self):
        return mock.patch.object(django_cache, 'get', side_effect=RedisConnectionError('Connection refused'))

    def test_liveness_endpoint_survives_redis_outage(self):
        with self._redis_down():
            response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, 200)

    def test_database_health_endpoint_survives_redis_outage(self):
        with self._redis_down():
            response = self.client.get('/api/health/database/')
        self.assertEqual(response.status_code, 200)

    def test_redis_health_endpoint_itself_is_not_throttled_via_the_cache(self):
        # This view's own logic pings settings.CELERY_BROKER_URL directly,
        # not the Django cache — mocked here the same way
        # apps.core.tests.RedisHealthViewTests does, so this test proves
        # only what it claims: the throttle-cache outage alone (cache.get()
        # patched below) does not block this endpoint, without depending
        # on any real network reachability.
        with self._redis_down(), mock.patch('apps.core.views.redis.Redis.from_url') as mocked_from_url:
            mocked_from_url.return_value.ping.return_value = True
            response = self.client.get('/api/health/redis/')
        self.assertEqual(response.status_code, 200)

    def test_authenticated_endpoint_does_not_500_during_redis_outage(self):
        with self._redis_down():
            response = self.client.get('/api/auth/me/', HTTP_AUTHORIZATION=f'Bearer {self.token}')
        self.assertNotEqual(response.status_code, 500)
        self.assertEqual(response.status_code, 200)

    def test_login_endpoint_does_not_500_during_redis_outage(self):
        with self._redis_down():
            response = self.client.post(
                '/api/auth/login/', {'username': 'redis-outage-user', 'password': 'pw'}, format='json'
            )
        self.assertNotEqual(response.status_code, 500)

    def test_unauthenticated_request_still_gets_a_clean_401_during_redis_outage(self):
        """Fail-open only bypasses the throttle check — it must not bypass
        authentication/permission checks (no Phase 12 regression)."""
        with self._redis_down():
            response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, 401)
