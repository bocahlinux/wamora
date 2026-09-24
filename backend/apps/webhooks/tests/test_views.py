import copy
import hashlib
import hmac
import json

from django.test import TestCase, override_settings

from apps.chats.models import Chat, Contact, Message
from apps.waha_sessions.models import WahaSession
from apps.webhooks.models import WebhookEvent
from apps.webhooks.tests.fixtures import (
    INBOUND_MESSAGE_ENVELOPE,
    OUTBOUND_MESSAGE_ENVELOPE,
    UNSUPPORTED_EVENT_ENVELOPE,
)

WEBHOOK_URL = '/api/webhooks/waha/'
TEST_SECRET = 'test-webhook-secret'


def sign(body_bytes: bytes, secret: str = TEST_SECRET) -> str:
    return hmac.new(secret.encode('utf-8'), body_bytes, hashlib.sha512).hexdigest()


@override_settings(WAHA_WEBHOOK_HMAC_SECRET=TEST_SECRET)
class WebhookSecurityTests(TestCase):
    """Security requirements: invalid/missing auth rejected; secrets never
    echoed back; errors never leak internals."""

    def _post_raw(self, body_bytes, **headers):
        return self.client.post(WEBHOOK_URL, data=body_bytes, content_type='application/json', **headers)

    def test_missing_signature_rejected(self):
        body = json.dumps(INBOUND_MESSAGE_ENVELOPE).encode()
        response = self._post_raw(body)
        self.assertEqual(response.status_code, 401)

    def test_invalid_signature_rejected(self):
        body = json.dumps(INBOUND_MESSAGE_ENVELOPE).encode()
        response = self._post_raw(body, HTTP_X_WEBHOOK_HMAC='not-the-right-signature')
        self.assertEqual(response.status_code, 401)

    def test_unauthenticated_request_does_not_touch_database(self):
        body = json.dumps(INBOUND_MESSAGE_ENVELOPE).encode()
        self._post_raw(body, HTTP_X_WEBHOOK_HMAC='wrong')
        self.assertFalse(WebhookEvent.objects.exists())

    def test_valid_signature_accepted(self):
        body = json.dumps(INBOUND_MESSAGE_ENVELOPE).encode()
        response = self._post_raw(body, HTTP_X_WEBHOOK_HMAC=sign(body))
        self.assertEqual(response.status_code, 200)

    def test_secret_never_present_in_response(self):
        body = json.dumps(INBOUND_MESSAGE_ENVELOPE).encode()
        response = self._post_raw(body, HTTP_X_WEBHOOK_HMAC=sign(body))
        self.assertNotIn(TEST_SECRET, response.content.decode())

    def test_error_response_does_not_leak_traceback_or_file_paths(self):
        response = self._post_raw(b'{not valid json', HTTP_X_WEBHOOK_HMAC=sign(b'{not valid json'))
        text = response.content.decode()
        self.assertNotIn('Traceback', text)
        self.assertNotIn('.py"', text)
        self.assertNotIn('django.db', text)


@override_settings(WAHA_WEBHOOK_HMAC_SECRET=TEST_SECRET)
class WebhookEnvelopeHttpTests(TestCase):
    def _post(self, envelope_or_bytes):
        body = envelope_or_bytes if isinstance(envelope_or_bytes, bytes) else json.dumps(envelope_or_bytes).encode()
        return self.client.post(
            WEBHOOK_URL, data=body, content_type='application/json', HTTP_X_WEBHOOK_HMAC=sign(body)
        )

    def test_malformed_json_returns_400(self):
        response = self._post(b'{not valid json')
        self.assertEqual(response.status_code, 400)

    def test_missing_required_fields_returns_400(self):
        response = self._post({'event': 'message'})
        self.assertEqual(response.status_code, 400)

    def test_unsupported_event_type_returns_200_and_is_recorded(self):
        response = self._post(UNSUPPORTED_EVENT_ENVELOPE)
        self.assertEqual(response.status_code, 200)
        event = WebhookEvent.objects.get(provider_event_id='FIXTURE-EVT-UNSUPPORTED-001')
        self.assertEqual(event.status, WebhookEvent.STATUS_UNSUPPORTED)
        self.assertEqual(event.event_type, 'session.status')


@override_settings(WAHA_WEBHOOK_HMAC_SECRET=TEST_SECRET)
class WebhookMessageHttpTests(TestCase):
    def _post(self, envelope):
        body = json.dumps(envelope).encode()
        return self.client.post(
            WEBHOOK_URL, data=body, content_type='application/json', HTTP_X_WEBHOOK_HMAC=sign(body)
        )

    def test_inbound_message_creates_session_contact_chat_message(self):
        response = self._post(INBOUND_MESSAGE_ENVELOPE)
        self.assertEqual(response.status_code, 200)

        session = WahaSession.objects.get(name='test_session')

        contact = Contact.objects.get(session=session, provider_contact_id='000000000000000@lid')
        self.assertEqual(contact.phone_number, '62800000000')

        chat = Chat.objects.get(session=session, provider_chat_id='000000000000000@lid')
        self.assertEqual(chat.contact, contact)
        self.assertFalse(chat.is_group)

        message = Message.objects.get(session=session, provider_message_id='FIXTURE-MSG-INBOUND-001')
        self.assertEqual(message.direction, Message.DIRECTION_INBOUND)
        self.assertEqual(message.body, 'Halo pak')
        self.assertEqual(message.chat, chat)

        event = WebhookEvent.objects.get(provider_event_id='FIXTURE-MSG-INBOUND-001')
        self.assertEqual(event.status, WebhookEvent.STATUS_PROCESSED)
        self.assertIsNotNone(event.processed_at)

    def test_outbound_message_does_not_create_contact_from_sender(self):
        self._post(INBOUND_MESSAGE_ENVELOPE)
        response = self._post(OUTBOUND_MESSAGE_ENVELOPE)
        self.assertEqual(response.status_code, 200)

        session = WahaSession.objects.get(name='test_session')
        self.assertEqual(Contact.objects.filter(session=session).count(), 1)

        message = Message.objects.get(session=session, provider_message_id='FIXTURE-MSG-OUTBOUND-001')
        self.assertEqual(message.direction, Message.DIRECTION_OUTBOUND)

    def test_outbound_only_creates_chat_without_contact(self):
        response = self._post(OUTBOUND_MESSAGE_ENVELOPE)
        self.assertEqual(response.status_code, 200)
        session = WahaSession.objects.get(name='test_session')
        chat = Chat.objects.get(session=session, provider_chat_id='000000000000000@lid')
        self.assertIsNone(chat.contact)
        self.assertEqual(Contact.objects.filter(session=session).count(), 0)

    def test_missing_alt_identifier_leaves_phone_number_blank(self):
        envelope = copy.deepcopy(INBOUND_MESSAGE_ENVELOPE)
        del envelope['payload']['_data']['Info']['SenderAlt']
        envelope['payload']['id'] = 'FIXTURE-MSG-NO-ALT-001'
        self._post(envelope)
        session = WahaSession.objects.get(name='test_session')
        contact = Contact.objects.get(session=session, provider_contact_id='000000000000000@lid')
        self.assertEqual(contact.phone_number, '')

    def test_message_missing_required_field_records_failed_event_without_crashing(self):
        envelope = copy.deepcopy(INBOUND_MESSAGE_ENVELOPE)
        del envelope['payload']['fromMe']
        del envelope['payload']['_data']['Info']['IsFromMe']
        envelope['payload']['id'] = 'FIXTURE-MSG-BROKEN-001'
        response = self._post(envelope)
        self.assertEqual(response.status_code, 200)
        event = WebhookEvent.objects.get(provider_event_id='FIXTURE-MSG-BROKEN-001')
        self.assertEqual(event.status, WebhookEvent.STATUS_FAILED)
        self.assertFalse(Message.objects.filter(provider_message_id='FIXTURE-MSG-BROKEN-001').exists())

    def test_provider_message_id_preserved_verbatim(self):
        self._post(INBOUND_MESSAGE_ENVELOPE)
        message = Message.objects.get(provider_message_id='FIXTURE-MSG-INBOUND-001')
        self.assertEqual(message.provider_message_id, INBOUND_MESSAGE_ENVELOPE['payload']['id'])


@override_settings(WAHA_WEBHOOK_HMAC_SECRET=TEST_SECRET)
class WebhookIdempotencyHttpTests(TestCase):
    def _post(self, envelope):
        body = json.dumps(envelope).encode()
        return self.client.post(
            WEBHOOK_URL, data=body, content_type='application/json', HTTP_X_WEBHOOK_HMAC=sign(body)
        )

    def test_duplicate_webhook_event_does_not_duplicate_message(self):
        self._post(INBOUND_MESSAGE_ENVELOPE)
        response = self._post(INBOUND_MESSAGE_ENVELOPE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Message.objects.filter(provider_message_id='FIXTURE-MSG-INBOUND-001').count(), 1)
        self.assertEqual(WebhookEvent.objects.filter(provider_event_id='FIXTURE-MSG-INBOUND-001').count(), 1)

    def test_duplicate_delivery_increments_attempts(self):
        self._post(INBOUND_MESSAGE_ENVELOPE)
        self._post(INBOUND_MESSAGE_ENVELOPE)
        event = WebhookEvent.objects.get(provider_event_id='FIXTURE-MSG-INBOUND-001')
        self.assertEqual(event.attempts, 1)

    def test_same_message_id_across_different_sessions_both_persist(self):
        other = copy.deepcopy(INBOUND_MESSAGE_ENVELOPE)
        other['session'] = 'session-b'
        self._post(INBOUND_MESSAGE_ENVELOPE)
        response = self._post(other)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Message.objects.filter(provider_message_id='FIXTURE-MSG-INBOUND-001').count(), 2)
