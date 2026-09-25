from unittest import mock

import redis
from django.conf import settings
from django.test import SimpleTestCase
from rest_framework.exceptions import NotFound
from rest_framework.test import APIRequestFactory

from apps.core.exceptions import api_exception_handler
from apps.core.middleware import RequestIDMiddleware
from apps.core.views import (
    REDIS_HEALTH_TIMEOUT_SECONDS,
    DatabaseHealthView,
    LivenessView,
    RedisHealthView,
)

factory = APIRequestFactory()


class LivenessViewTests(SimpleTestCase):
    def test_liveness_ok_without_touching_database(self):
        request = factory.get('/api/health/')
        with mock.patch('apps.core.views.connection') as mocked_connection:
            response = LivenessView.as_view()(request)
            mocked_connection.cursor.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'status': 'ok', 'component': 'backend'})


class DatabaseHealthViewTests(SimpleTestCase):
    def test_database_health_ok(self):
        request = factory.get('/api/health/database/')
        with mock.patch('apps.core.views.connection') as mocked_connection:
            cursor_cm = mocked_connection.cursor.return_value
            cursor = cursor_cm.__enter__.return_value
            cursor.fetchone.return_value = (1,)

            response = DatabaseHealthView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'status': 'ok', 'component': 'database'})

    def test_database_health_error_does_not_leak_driver_details(self):
        request = factory.get('/api/health/database/')
        with mock.patch('apps.core.views.connection') as mocked_connection:
            mocked_connection.cursor.side_effect = Exception(
                'connection to server at "office-db-host" user "secret_user" password authentication failed'
            )
            response = DatabaseHealthView.as_view()(request)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data, {'status': 'error', 'component': 'database'})
        self.assertNotIn('secret_user', str(response.data))
        self.assertNotIn('office-db-host', str(response.data))


class RedisHealthViewTests(SimpleTestCase):
    def test_redis_health_ok(self):
        request = factory.get('/api/health/redis/')
        with mock.patch('apps.core.views.redis.Redis.from_url') as mocked_from_url:
            mocked_client = mocked_from_url.return_value
            mocked_client.ping.return_value = True

            response = RedisHealthView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'status': 'ok', 'component': 'redis'})

    def test_redis_health_connection_error(self):
        request = factory.get('/api/health/redis/')
        with mock.patch('apps.core.views.redis.Redis.from_url') as mocked_from_url:
            mocked_client = mocked_from_url.return_value
            mocked_client.ping.side_effect = redis.exceptions.ConnectionError(
                'Error 111 connecting to redis:6379. Connection refused.'
            )

            response = RedisHealthView.as_view()(request)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data, {'status': 'error', 'component': 'redis'})

    def test_redis_health_timeout(self):
        request = factory.get('/api/health/redis/')
        with mock.patch('apps.core.views.redis.Redis.from_url') as mocked_from_url:
            mocked_client = mocked_from_url.return_value
            mocked_client.ping.side_effect = redis.exceptions.TimeoutError('Timeout reading from socket')

            response = RedisHealthView.as_view()(request)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data, {'status': 'error', 'component': 'redis'})

    def test_redis_health_error_does_not_leak_connection_details(self):
        request = factory.get('/api/health/redis/')
        with mock.patch('apps.core.views.redis.Redis.from_url') as mocked_from_url:
            mocked_client = mocked_from_url.return_value
            mocked_client.ping.side_effect = redis.exceptions.ConnectionError(
                'Error connecting to redis://:supersecretpassword@internal-redis-host:6379/0'
            )

            response = RedisHealthView.as_view()(request)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data, {'status': 'error', 'component': 'redis'})
        self.assertNotIn('supersecretpassword', str(response.data))
        self.assertNotIn('internal-redis-host', str(response.data))

    def test_redis_health_uses_bounded_timeout(self):
        request = factory.get('/api/health/redis/')
        with mock.patch('apps.core.views.redis.Redis.from_url') as mocked_from_url:
            mocked_client = mocked_from_url.return_value
            mocked_client.ping.return_value = True

            RedisHealthView.as_view()(request)

        mocked_from_url.assert_called_once_with(
            settings.CELERY_BROKER_URL,
            socket_connect_timeout=REDIS_HEALTH_TIMEOUT_SECONDS,
            socket_timeout=REDIS_HEALTH_TIMEOUT_SECONDS,
        )


class RequestIDMiddlewareTests(SimpleTestCase):
    def _run_middleware(self, request):
        response = mock.MagicMock()
        middleware = RequestIDMiddleware(get_response=lambda req: response)
        middleware(request)
        return request, response

    def test_generates_request_id_when_absent(self):
        request = factory.get('/api/health/')
        request, response = self._run_middleware(request)
        self.assertTrue(request.request_id)
        response.__setitem__.assert_called_with('X-Request-ID', request.request_id)

    def test_preserves_incoming_request_id(self):
        request = factory.get('/api/health/', HTTP_X_REQUEST_ID='client-supplied-id')
        request, response = self._run_middleware(request)
        self.assertEqual(request.request_id, 'client-supplied-id')
        response.__setitem__.assert_called_with('X-Request-ID', 'client-supplied-id')


class ApiExceptionHandlerTests(SimpleTestCase):
    def test_formats_drf_exception_as_error_envelope(self):
        request = factory.get('/api/does-not-exist/')
        request.request_id = 'req-123'

        response = api_exception_handler(NotFound('missing'), {'request': request})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.data,
            {'error': {'code': 'not_found', 'message': 'missing', 'request_id': 'req-123'}},
        )

    def test_unhandled_exception_returns_generic_500_envelope(self):
        request = factory.get('/api/health/')
        request.request_id = 'req-456'

        response = api_exception_handler(ValueError('should not leak'), {'request': request})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.data,
            {'error': {'code': 'internal_error', 'message': 'Internal server error', 'request_id': 'req-456'}},
        )
