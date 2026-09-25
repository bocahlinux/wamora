from unittest import mock

from django.test import override_settings
from rest_framework.test import APITestCase

from apps.chats.models import Chat
from apps.sync.reconciliation import ReconciliationResult
from apps.waha_sessions.models import WahaSession

TRIGGER_URL = '/internal/reconciliation/trigger/'
HEADERS = {'HTTP_X_INTERNAL_SERVICE_KEY': 'test-internal-service-key'}


@override_settings(INTERNAL_SERVICE_KEY='test-internal-service-key', RECONCILIATION_EXECUTOR='sync')
class ReconciliationTriggerViewTests(APITestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='test_session')
        Chat.objects.create(session=self.session, provider_chat_id='c1@lid')

    def test_requires_internal_service_key(self):
        response = self.client.post(TRIGGER_URL, {'session': 'test_session', 'chat_id': 'c1@lid'})
        self.assertEqual(response.status_code, 403)

    def test_wrong_internal_service_key_is_rejected(self):
        response = self.client.post(
            TRIGGER_URL,
            {'session': 'test_session', 'chat_id': 'c1@lid'},
            HTTP_X_INTERNAL_SERVICE_KEY='wrong-key',
        )
        self.assertEqual(response.status_code, 403)

    def test_missing_session_is_a_bad_request(self):
        response = self.client.post(TRIGGER_URL, {'chat_id': 'c1@lid'}, **HEADERS)
        self.assertEqual(response.status_code, 400)

    def test_missing_chat_id_is_a_bad_request(self):
        response = self.client.post(TRIGGER_URL, {'session': 'test_session'}, **HEADERS)
        self.assertEqual(response.status_code, 400)

    def test_valid_request_dispatches_exactly_this_chat(self):
        with mock.patch('apps.sync.internal_views.trigger_reconciliation') as mocked:
            mocked.return_value = ReconciliationResult()
            response = self.client.post(
                TRIGGER_URL, {'session': 'test_session', 'chat_id': 'c1@lid'}, **HEADERS
            )
        mocked.assert_called_once_with('test_session', 'c1@lid')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['triggered'])
        self.assertEqual(response.data['executor'], 'sync')

    def test_celery_executor_response_reflects_enqueue_not_a_result(self):
        with mock.patch('apps.sync.internal_views.trigger_reconciliation') as mocked:
            mocked.return_value = None
            response = self.client.post(
                TRIGGER_URL, {'session': 'test_session', 'chat_id': 'c1@lid'}, **HEADERS
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data['executor'], 'celery')

    def test_end_to_end_with_a_stubbed_waha_client_actually_triggers_reconciliation(self):
        from apps.sync.tests.fixtures import REST_INBOUND_MESSAGE_1
        from apps.sync.tests.test_reconciliation import StubWahaClient

        client = StubWahaClient({'c1@lid': [REST_INBOUND_MESSAGE_1]})
        with mock.patch('apps.sync.executors.reconcile_session') as mocked_reconcile:
            from apps.sync.reconciliation import reconcile_session as real_reconcile_session

            mocked_reconcile.side_effect = lambda session_name, chat_ids, waha_client=None, **kwargs: (
                real_reconcile_session(session_name, chat_ids=chat_ids, waha_client=client)
            )
            response = self.client.post(
                TRIGGER_URL, {'session': 'test_session', 'chat_id': 'c1@lid'}, **HEADERS
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['messages_inserted'], 1)
