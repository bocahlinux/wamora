from django.test import SimpleTestCase

from apps.webhooks.parsing import (
    EnvelopeValidationError,
    MessageParsingError,
    extract_phone_number,
    parse_envelope,
    parse_message,
)
from apps.webhooks.tests.fixtures import (
    INBOUND_MESSAGE_ENVELOPE,
    OUTBOUND_MESSAGE_ENVELOPE,
    UNSUPPORTED_EVENT_ENVELOPE,
)


class ParseEnvelopeTests(SimpleTestCase):
    def test_valid_envelope(self):
        envelope = parse_envelope(INBOUND_MESSAGE_ENVELOPE)
        self.assertEqual(envelope.event_type, 'message')
        self.assertEqual(envelope.session_name, 'test_session')
        self.assertEqual(envelope.provider_event_id, 'FIXTURE-MSG-INBOUND-001')

    def test_non_object_body_rejected(self):
        with self.assertRaises(EnvelopeValidationError):
            parse_envelope(['not', 'an', 'object'])

    def test_missing_event_rejected(self):
        data = {'session': 'test_session', 'payload': {'id': 'x'}}
        with self.assertRaises(EnvelopeValidationError):
            parse_envelope(data)

    def test_missing_session_rejected(self):
        data = {'event': 'message', 'payload': {'id': 'x'}}
        with self.assertRaises(EnvelopeValidationError):
            parse_envelope(data)

    def test_missing_payload_rejected(self):
        data = {'event': 'message', 'session': 'test_session'}
        with self.assertRaises(EnvelopeValidationError):
            parse_envelope(data)

    def test_missing_payload_id_rejected(self):
        data = {'event': 'message', 'session': 'test_session', 'payload': {}}
        with self.assertRaises(EnvelopeValidationError):
            parse_envelope(data)

    def test_unsupported_event_type_still_parses_as_valid_envelope(self):
        envelope = parse_envelope(UNSUPPORTED_EVENT_ENVELOPE)
        self.assertEqual(envelope.event_type, 'session.status')


class ParseMessageTests(SimpleTestCase):
    def test_inbound_lid_sender(self):
        parsed = parse_message(INBOUND_MESSAGE_ENVELOPE['payload'])
        self.assertEqual(parsed.provider_message_id, 'FIXTURE-MSG-INBOUND-001')
        self.assertEqual(parsed.chat_provider_id, '000000000000000@lid')
        self.assertEqual(parsed.sender_provider_id, '000000000000000@lid')
        self.assertEqual(parsed.sender_alt, '62800000000@s.whatsapp.net')
        self.assertFalse(parsed.from_me)
        self.assertFalse(parsed.is_group)
        self.assertEqual(parsed.body, 'Halo pak')

    def test_outbound_message(self):
        parsed = parse_message(OUTBOUND_MESSAGE_ENVELOPE['payload'])
        self.assertTrue(parsed.from_me)
        self.assertIsNone(parsed.sender_alt)
        self.assertEqual(parsed.chat_provider_id, '000000000000000@lid')

    def test_missing_alt_identifier_is_none_not_error(self):
        payload = {
            'id': 'x',
            'from': 'abc@lid',
            'fromMe': False,
            'body': 'hi',
            '_data': {'Info': {'Chat': 'abc@lid', 'Sender': 'abc@lid'}},
        }
        parsed = parse_message(payload)
        self.assertIsNone(parsed.sender_alt)

    def test_falls_back_to_top_level_from_when_info_missing(self):
        payload = {'id': 'x', 'from': 'abc@lid', 'fromMe': False, 'body': 'hi'}
        parsed = parse_message(payload)
        self.assertEqual(parsed.chat_provider_id, 'abc@lid')
        self.assertEqual(parsed.sender_provider_id, 'abc@lid')

    def test_missing_message_id_raises(self):
        payload = {'from': 'abc@lid', 'fromMe': False, 'body': 'hi'}
        with self.assertRaises(MessageParsingError):
            parse_message(payload)

    def test_missing_chat_identifier_raises(self):
        payload = {'id': 'x', 'fromMe': False, 'body': 'hi'}
        with self.assertRaises(MessageParsingError):
            parse_message(payload)

    def test_missing_from_me_raises(self):
        payload = {'id': 'x', 'from': 'abc@lid', 'body': 'hi'}
        with self.assertRaises(MessageParsingError):
            parse_message(payload)

    def test_extracts_push_name_from_info(self):
        payload = {
            'id': 'x',
            'from': 'abc@lid',
            'fromMe': False,
            'body': 'hi',
            '_data': {'Info': {'Chat': 'abc@lid', 'Sender': 'abc@lid', 'PushName': 'Yuk Code Creative'}},
        }
        parsed = parse_message(payload)
        self.assertEqual(parsed.push_name, 'Yuk Code Creative')

    def test_push_name_is_none_when_absent(self):
        payload = {
            'id': 'x',
            'from': 'abc@lid',
            'fromMe': False,
            'body': 'hi',
            '_data': {'Info': {'Chat': 'abc@lid', 'Sender': 'abc@lid'}},
        }
        parsed = parse_message(payload)
        self.assertIsNone(parsed.push_name)

    def test_push_name_is_none_when_not_a_string(self):
        payload = {
            'id': 'x',
            'from': 'abc@lid',
            'fromMe': False,
            'body': 'hi',
            '_data': {'Info': {'Chat': 'abc@lid', 'Sender': 'abc@lid', 'PushName': 123}},
        }
        parsed = parse_message(payload)
        self.assertIsNone(parsed.push_name)

    def test_push_name_is_none_when_empty_string(self):
        payload = {
            'id': 'x',
            'from': 'abc@lid',
            'fromMe': False,
            'body': 'hi',
            '_data': {'Info': {'Chat': 'abc@lid', 'Sender': 'abc@lid', 'PushName': ''}},
        }
        parsed = parse_message(payload)
        self.assertIsNone(parsed.push_name)


class ExtractPhoneNumberTests(SimpleTestCase):
    def test_extracts_digits_from_jid_alt(self):
        self.assertEqual(extract_phone_number('62800000000@s.whatsapp.net'), '62800000000')

    def test_returns_empty_when_absent(self):
        self.assertEqual(extract_phone_number(None), '')

    def test_does_not_treat_lid_as_phone_number(self):
        # Phase 2.5 rule: never derive phone number from the LID form.
        self.assertEqual(extract_phone_number('000000000000000@lid'), '')

    def test_rejects_non_numeric_local_part(self):
        self.assertEqual(extract_phone_number('not-a-number@s.whatsapp.net'), '')
