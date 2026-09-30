from unittest import mock

from django.test import TestCase, override_settings

from apps.blast.bff_client import BffDispatchError, send_list_message, start_typing, stop_typing

_SETTINGS = dict(
    BFF_INTERNAL_BASE_URL='http://bff.internal', OFFICE_DISPATCH_SERVICE_KEY='secret-key',
    BFF_INTERNAL_TIMEOUT_MS=5000,
)


@override_settings(**_SETTINGS)
class SendListMessageTests(TestCase):
    """Discussed requirement — Conversation/Bot Engine interactive list
    menus. Same contract as `send_blast_message`, just POSTs to
    `/internal/blast/send-list` (`bff/src/routes/internalBlast.ts`)."""

    def _response(self, status_code=200, json_data=None):
        response = mock.Mock()
        response.status_code = status_code
        response.json.return_value = json_data if json_data is not None else {'status': 'sent'}
        return response

    @mock.patch('apps.blast.bff_client.requests.post')
    def test_success_returns_sent_status(self, mocked_post):
        mocked_post.return_value = self._response(json_data={'status': 'sent', 'providerMessageId': 'abc123'})

        result = send_list_message('no_epahari', 'wp1@lid', {'title': 'Menu'}, 'key-1')

        self.assertEqual(result, {'status': 'sent', 'provider_message_id': 'abc123'})
        called_url = mocked_post.call_args[0][0]
        self.assertTrue(called_url.endswith('/internal/blast/send-list'))
        called_kwargs = mocked_post.call_args[1]
        self.assertEqual(called_kwargs['json']['list'], {'title': 'Menu'})
        self.assertEqual(called_kwargs['headers']['X-Office-Dispatch-Key'], 'secret-key')
        self.assertEqual(called_kwargs['headers']['Idempotency-Key'], 'key-1')

    @mock.patch('apps.blast.bff_client.requests.post')
    def test_waha_reported_failure_returns_failed_status(self, mocked_post):
        mocked_post.return_value = self._response(json_data={'status': 'failed'})
        result = send_list_message('no_epahari', 'wp1@lid', {'title': 'Menu'}, 'key-2')
        self.assertEqual(result['status'], 'failed')

    @mock.patch('apps.blast.bff_client.requests.post')
    def test_non_200_raises_dispatch_error(self, mocked_post):
        mocked_post.return_value = self._response(status_code=500)
        with self.assertRaises(BffDispatchError):
            send_list_message('no_epahari', 'wp1@lid', {'title': 'Menu'}, 'key-3')

    @mock.patch('apps.blast.bff_client.requests.post')
    def test_network_error_raises_dispatch_error(self, mocked_post):
        import requests
        mocked_post.side_effect = requests.ConnectionError('boom')
        with self.assertRaises(BffDispatchError):
            send_list_message('no_epahari', 'wp1@lid', {'title': 'Menu'}, 'key-4')

    @override_settings(BFF_INTERNAL_BASE_URL='')
    def test_missing_base_url_raises_dispatch_error(self):
        with self.assertRaises(BffDispatchError):
            send_list_message('no_epahari', 'wp1@lid', {'title': 'Menu'}, 'key-5')


@override_settings(**_SETTINGS)
class TypingIndicatorTests(TestCase):
    """Discussed requirement — human-like reply delay
    (`BotConfig.reply_delay_seconds`). Both functions share
    `_call_typing_endpoint`, so `start_typing` covers the shared success/
    failure paths; `stop_typing` only re-checks it hits the other path."""

    def _response(self, status_code=200):
        response = mock.Mock()
        response.status_code = status_code
        return response

    @mock.patch('apps.blast.bff_client.requests.post')
    def test_start_typing_posts_to_the_start_endpoint(self, mocked_post):
        mocked_post.return_value = self._response()

        start_typing('no_epahari', 'wp1@lid')

        called_url = mocked_post.call_args[0][0]
        self.assertTrue(called_url.endswith('/internal/typing/start'))
        called_kwargs = mocked_post.call_args[1]
        self.assertEqual(called_kwargs['json'], {'session': 'no_epahari', 'chatId': 'wp1@lid'})
        self.assertEqual(called_kwargs['headers']['X-Office-Dispatch-Key'], 'secret-key')

    @mock.patch('apps.blast.bff_client.requests.post')
    def test_stop_typing_posts_to_the_stop_endpoint(self, mocked_post):
        mocked_post.return_value = self._response()

        stop_typing('no_epahari', 'wp1@lid')

        called_url = mocked_post.call_args[0][0]
        self.assertTrue(called_url.endswith('/internal/typing/stop'))

    @mock.patch('apps.blast.bff_client.requests.post')
    def test_non_200_raises_dispatch_error(self, mocked_post):
        mocked_post.return_value = self._response(status_code=500)
        with self.assertRaises(BffDispatchError):
            start_typing('no_epahari', 'wp1@lid')

    @mock.patch('apps.blast.bff_client.requests.post')
    def test_network_error_raises_dispatch_error(self, mocked_post):
        import requests
        mocked_post.side_effect = requests.ConnectionError('boom')
        with self.assertRaises(BffDispatchError):
            start_typing('no_epahari', 'wp1@lid')

    @override_settings(BFF_INTERNAL_BASE_URL='')
    def test_missing_base_url_raises_dispatch_error(self):
        with self.assertRaises(BffDispatchError):
            start_typing('no_epahari', 'wp1@lid')
