from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import AuditLog

AUDIT_URL = '/internal/audit-events/'
HEADERS = {'HTTP_X_INTERNAL_SERVICE_KEY': 'test-internal-service-key'}


@override_settings(INTERNAL_SERVICE_KEY='test-internal-service-key')
class AuditEventCreateViewTests(APITestCase):
    def test_requires_internal_service_key(self):
        response = self.client.post(AUDIT_URL, {'action': 'session.start', 'result': 'success'})
        self.assertEqual(response.status_code, 403)

    def test_creates_audit_log_with_actor(self):
        user = User.objects.create_user('operator', password='pw')
        response = self.client.post(
            AUDIT_URL,
            {'actor_id': user.pk, 'action': 'session.start', 'target': 'test_session', 'result': 'success'},
            **HEADERS,
        )
        self.assertEqual(response.status_code, 201)
        entry = AuditLog.objects.get(pk=response.data['id'])
        self.assertEqual(entry.actor_id, user.pk)
        self.assertEqual(entry.action, 'session.start')
        self.assertEqual(entry.target, 'test_session')
        self.assertEqual(entry.result, 'success')

    def test_actor_is_nullable_for_system_initiated_events(self):
        response = self.client.post(
            AUDIT_URL, {'action': 'session.restart', 'target': 'test_session', 'result': 'failure'}, **HEADERS
        )
        self.assertEqual(response.status_code, 201)
        entry = AuditLog.objects.get(pk=response.data['id'])
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.result, 'failure')

    def test_missing_required_fields_returns_400(self):
        response = self.client.post(AUDIT_URL, {'result': 'success'}, **HEADERS)
        self.assertEqual(response.status_code, 400)

    def test_invalid_result_value_returns_400(self):
        response = self.client.post(AUDIT_URL, {'action': 'x', 'result': 'maybe'}, **HEADERS)
        self.assertEqual(response.status_code, 400)
