from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from apps.sync.waha_client import WahaClient, WahaClientError


@override_settings(WAHA_BASE_URL='http://waha.internal:3000', WAHA_API_KEY='test-api-key')
class WahaClientTests(SimpleTestCase):
    def _client(self):
        return WahaClient()

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_encodes_chat_id_and_session_in_url(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: [])
        self._client().fetch_chat_messages('test_session', '000000000000000@lid', limit=10)

        called_url = mock_get.call_args.args[0]
        self.assertIn('000000000000000%40lid', called_url)
        self.assertNotIn('000000000000000@lid', called_url)

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_sends_api_key_header_not_query_param(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: [])
        self._client().fetch_chat_messages('test_session', 'c1@lid', limit=10)

        headers = mock_get.call_args.kwargs['headers']
        self.assertEqual(headers['X-Api-Key'], 'test-api-key')
        called_url = mock_get.call_args.args[0]
        self.assertNotIn('test-api-key', called_url)

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_sends_limit_and_offset_query_params(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: [])
        self._client().fetch_chat_messages('test_session', 'c1@lid', limit=42, offset=84)
        self.assertEqual(mock_get.call_args.kwargs['params'], {'limit': 42, 'offset': 84})

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_offset_defaults_to_zero(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: [])
        self._client().fetch_chat_messages('test_session', 'c1@lid', limit=10)
        self.assertEqual(mock_get.call_args.kwargs['params'], {'limit': 10, 'offset': 0})

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_never_sends_page_param(self, mock_get):
        # Confirmed against the real deployment: `page` is silently
        # ignored — offset is the only working pagination parameter.
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: [])
        self._client().fetch_chat_messages('test_session', 'c1@lid', limit=10, offset=20)
        self.assertNotIn('page', mock_get.call_args.kwargs['params'])

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_bare_list_response_returned_as_is(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: [{'id': 'm1'}])
        result = self._client().fetch_chat_messages('test_session', 'c1@lid')
        self.assertEqual(result, [{'id': 'm1'}])

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_wrapped_messages_envelope_unwrapped(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: {'messages': [{'id': 'm1'}]})
        result = self._client().fetch_chat_messages('test_session', 'c1@lid')
        self.assertEqual(result, [{'id': 'm1'}])

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_unrecognized_response_shape_raises(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: {'unexpected': 'shape'})
        with self.assertRaises(WahaClientError):
            self._client().fetch_chat_messages('test_session', 'c1@lid')

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_non_200_raises_waha_client_error(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=401, json=lambda: {'message': 'Unauthorized'})
        with self.assertRaises(WahaClientError):
            self._client().fetch_chat_messages('test_session', 'c1@lid')

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_network_error_raises_waha_client_error_without_leaking_key(self, mock_get):
        mock_get.side_effect = requests.ConnectionError('connection refused')
        with self.assertRaises(WahaClientError) as ctx:
            self._client().fetch_chat_messages('test_session', 'c1@lid')
        self.assertNotIn('test-api-key', str(ctx.exception))

    @override_settings(WAHA_API_KEY='')
    def test_missing_api_key_raises_without_making_request(self):
        with self.assertRaises(WahaClientError):
            self._client().fetch_chat_messages('test_session', 'c1@lid')

    @override_settings(WAHA_BASE_URL='')
    def test_missing_base_url_raises_without_making_request(self):
        with self.assertRaises(WahaClientError):
            self._client().fetch_chat_messages('test_session', 'c1@lid')


class WahaClientFetchChatsTests(SimpleTestCase):
    """Inbox/Chat chat discovery —
    docs/generated/INBOX-CHAT-DECISION-REPORT.md Section 4."""

    def _client(self):
        return WahaClient(base_url='http://waha.internal:3000', api_key='test-api-key')

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_encodes_session_and_calls_the_documented_chat_list_endpoint(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: [])
        self._client().fetch_chats('test session')  # deliberately includes a space
        called_url = mock_get.call_args.args[0]
        self.assertIn('test%20session', called_url)
        self.assertIn('/chats', called_url)
        self.assertNotIn('messages', called_url)

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_sends_api_key_header_not_query_param(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: [])
        self._client().fetch_chats('test_session')
        headers = mock_get.call_args.kwargs['headers']
        self.assertEqual(headers['X-Api-Key'], 'test-api-key')
        self.assertNotIn('test-api-key', mock_get.call_args.args[0])

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_bare_list_response_returned_as_is(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: [{'id': 'c1'}])
        result = self._client().fetch_chats('test_session')
        self.assertEqual(result, [{'id': 'c1'}])

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_wrapped_chats_envelope_unwrapped(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: {'chats': [{'id': 'c1'}]})
        result = self._client().fetch_chats('test_session')
        self.assertEqual(result, [{'id': 'c1'}])

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_unrecognized_response_shape_raises(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=200, json=lambda: {'unexpected': 'shape'})
        with self.assertRaises(WahaClientError):
            self._client().fetch_chats('test_session')

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_non_200_raises_waha_client_error(self, mock_get):
        mock_get.return_value = mock.Mock(status_code=500, json=lambda: {})
        with self.assertRaises(WahaClientError):
            self._client().fetch_chats('test_session')

    @mock.patch('apps.sync.waha_client.requests.get')
    def test_network_error_raises_waha_client_error_without_leaking_key(self, mock_get):
        mock_get.side_effect = requests.ConnectionError('connection refused')
        with self.assertRaises(WahaClientError) as ctx:
            self._client().fetch_chats('test_session')
        self.assertNotIn('test-api-key', str(ctx.exception))

    def test_missing_api_key_raises_without_making_request(self):
        with self.assertRaises(WahaClientError):
            WahaClient(base_url='http://waha.internal:3000', api_key='').fetch_chats('test_session')

    def test_missing_base_url_raises_without_making_request(self):
        with self.assertRaises(WahaClientError):
            WahaClient(base_url='', api_key='test-api-key').fetch_chats('test_session')
