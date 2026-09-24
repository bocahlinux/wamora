from datetime import timedelta

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.waha_sessions.models import WahaSession

from .models import OutboundOperation

REGISTER_URL = '/internal/outbound-operations/'
HEADERS = {'HTTP_X_INTERNAL_SERVICE_KEY': 'test-internal-service-key'}


@override_settings(INTERNAL_SERVICE_KEY='test-internal-service-key')
class OutboundOperationRegisterViewTests(APITestCase):
    def _register(self, **overrides):
        body = {
            'session': 'test_session',
            'idempotency_key': 'key-1',
            'destination': '62800000000@s.whatsapp.net',
            'operation_type': 'sendText',
        }
        body.update(overrides)
        return self.client.post(REGISTER_URL, body, **HEADERS)

    def test_requires_internal_service_key(self):
        response = self.client.post(REGISTER_URL, {'session': 'test_session', 'idempotency_key': 'k'})
        self.assertEqual(response.status_code, 403)

    def test_first_request_creates_a_new_pending_row(self):
        response = self._register()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['created'])
        self.assertEqual(response.data['status'], OutboundOperation.STATUS_PENDING)
        self.assertFalse(response.data['retryable'])
        self.assertEqual(OutboundOperation.objects.count(), 1)

    def test_first_request_creates_the_waha_session_if_unknown(self):
        self.assertFalse(WahaSession.objects.filter(name='test_session').exists())
        self._register()
        self.assertTrue(WahaSession.objects.filter(name='test_session').exists())

    def test_duplicate_key_returns_existing_row_without_creating_a_second_one(self):
        first = self._register()
        second = self._register()
        self.assertFalse(second.data['created'])
        self.assertEqual(first.data['id'], second.data['id'])
        self.assertEqual(OutboundOperation.objects.count(), 1)

    def test_duplicate_key_different_session_creates_a_separate_row(self):
        self._register(session='session-a')
        response = self._register(session='session-b')
        self.assertTrue(response.data['created'])
        self.assertEqual(OutboundOperation.objects.count(), 2)

    def test_sent_row_is_returned_as_is_never_retryable(self):
        first = self._register()
        operation = OutboundOperation.objects.get(pk=first.data['id'])
        operation.status = OutboundOperation.STATUS_SENT
        operation.provider_message_id = 'wa-msg-1'
        operation.save(update_fields=['status', 'provider_message_id', 'updated_at'])

        response = self._register()
        self.assertFalse(response.data['created'])
        self.assertEqual(response.data['status'], OutboundOperation.STATUS_SENT)
        self.assertEqual(response.data['provider_message_id'], 'wa-msg-1')
        self.assertFalse(response.data['retryable'])

    def test_fresh_failed_row_is_not_retryable(self):
        first = self._register()
        operation = OutboundOperation.objects.get(pk=first.data['id'])
        operation.status = OutboundOperation.STATUS_FAILED
        operation.save(update_fields=['status', 'updated_at'])

        response = self._register()
        self.assertEqual(response.data['status'], OutboundOperation.STATUS_FAILED)
        self.assertFalse(response.data['retryable'])

    def test_stale_failed_row_is_still_not_retryable(self):
        """Contract Section 9: FAILED is never stale-retry-eligible, only
        PENDING/UNKNOWN are — a confirmed failure always requires a new
        idempotency key, regardless of age."""
        first = self._register()
        operation = OutboundOperation.objects.get(pk=first.data['id'])
        operation.status = OutboundOperation.STATUS_FAILED
        operation.save(update_fields=['status', 'updated_at'])
        OutboundOperation.objects.filter(pk=operation.pk).update(
            updated_at=timezone.now() - timedelta(seconds=999)
        )

        response = self._register()
        self.assertFalse(response.data['retryable'])

    def test_fresh_pending_row_is_not_retryable(self):
        self._register()
        response = self._register()
        self.assertEqual(response.data['status'], OutboundOperation.STATUS_PENDING)
        self.assertFalse(response.data['retryable'])

    def test_stale_pending_row_is_retryable(self):
        first = self._register()
        OutboundOperation.objects.filter(pk=first.data['id']).update(
            updated_at=timezone.now() - timedelta(seconds=999)
        )
        response = self._register()
        self.assertEqual(response.data['status'], OutboundOperation.STATUS_PENDING)
        self.assertTrue(response.data['retryable'])

    def test_stale_unknown_row_is_retryable(self):
        first = self._register()
        operation = OutboundOperation.objects.get(pk=first.data['id'])
        operation.status = OutboundOperation.STATUS_UNKNOWN
        operation.save(update_fields=['status', 'updated_at'])
        OutboundOperation.objects.filter(pk=operation.pk).update(
            updated_at=timezone.now() - timedelta(seconds=999)
        )

        response = self._register()
        self.assertEqual(response.data['status'], OutboundOperation.STATUS_UNKNOWN)
        self.assertTrue(response.data['retryable'])


RESOLVE_URL = '/internal/outbound-operations/{}/'


@override_settings(INTERNAL_SERVICE_KEY='test-internal-service-key')
class OutboundOperationResolveViewTests(APITestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='test_session')
        self.operation = OutboundOperation.objects.create(
            session=self.session,
            idempotency_key='key-1',
            destination='62800000000@s.whatsapp.net',
            operation_type='sendText',
        )

    def test_requires_internal_service_key(self):
        response = self.client.patch(RESOLVE_URL.format(self.operation.pk), {'status': 'sent'})
        self.assertEqual(response.status_code, 403)

    def test_resolves_to_sent_with_provider_message_id(self):
        response = self.client.patch(
            RESOLVE_URL.format(self.operation.pk),
            {'status': 'sent', 'provider_message_id': 'wa-msg-1'},
            **HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        self.operation.refresh_from_db()
        self.assertEqual(self.operation.status, OutboundOperation.STATUS_SENT)
        self.assertEqual(self.operation.provider_message_id, 'wa-msg-1')

    def test_resolves_to_failed(self):
        response = self.client.patch(RESOLVE_URL.format(self.operation.pk), {'status': 'failed'}, **HEADERS)
        self.assertEqual(response.status_code, 200)
        self.operation.refresh_from_db()
        self.assertEqual(self.operation.status, OutboundOperation.STATUS_FAILED)

    def test_resolves_to_unknown_on_timeout(self):
        response = self.client.patch(RESOLVE_URL.format(self.operation.pk), {'status': 'unknown'}, **HEADERS)
        self.assertEqual(response.status_code, 200)
        self.operation.refresh_from_db()
        self.assertEqual(self.operation.status, OutboundOperation.STATUS_UNKNOWN)

    def test_writes_audit_log_when_actor_action_result_supplied(self):
        self.assertEqual(AuditLog.objects.count(), 0)
        self.client.patch(
            RESOLVE_URL.format(self.operation.pk),
            {'status': 'sent', 'action': 'message.send', 'target': 'test_session', 'result': 'success'},
            **HEADERS,
        )
        self.assertEqual(AuditLog.objects.count(), 1)
        entry = AuditLog.objects.get()
        self.assertEqual(entry.action, 'message.send')
        self.assertEqual(entry.result, 'success')
        self.operation.refresh_from_db()
        self.assertEqual(self.operation.audit_log_id, entry.pk)

    def test_no_audit_log_written_when_action_or_result_omitted(self):
        self.client.patch(RESOLVE_URL.format(self.operation.pk), {'status': 'sent'}, **HEADERS)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_unknown_operation_id_returns_404(self):
        response = self.client.patch(RESOLVE_URL.format(999999), {'status': 'sent'}, **HEADERS)
        self.assertEqual(response.status_code, 404)
