import copy
from unittest import mock

from django.db import DatabaseError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.chats.models import Chat, Contact, Message
from apps.waha_sessions.models import WahaSession
from apps.webhooks.models import WebhookEvent
from apps.webhooks.parsing import ParsedMessage, parse_envelope
from apps.webhooks.services import DuplicateMessage, persist_message, ingest_webhook
from apps.webhooks.tests.fixtures import INBOUND_MESSAGE_ENVELOPE


class IngestWebhookTransactionTests(TestCase):
    """docs' "Transaction requirements": partial failures must not leave a
    WebhookEvent falsely marked as successfully processed."""

    def test_unexpected_failure_leaves_webhook_event_pending_and_rolls_back_chat_contact(self):
        envelope = parse_envelope(INBOUND_MESSAGE_ENVELOPE)
        with mock.patch('apps.webhooks.services.Message.objects.create', side_effect=DatabaseError('boom')):
            with self.assertRaises(DatabaseError):
                ingest_webhook(envelope)

        event = WebhookEvent.objects.get(provider_event_id='FIXTURE-MSG-INBOUND-001')
        self.assertEqual(event.status, WebhookEvent.STATUS_PENDING)
        self.assertFalse(Message.objects.exists())
        # Chat/Contact created earlier in the SAME atomic block must be
        # rolled back too — not left as an orphaned partial write.
        self.assertFalse(Chat.objects.exists())
        self.assertFalse(Contact.objects.exists())

    def test_retry_after_transient_failure_completes_processing(self):
        envelope = parse_envelope(INBOUND_MESSAGE_ENVELOPE)
        with mock.patch('apps.webhooks.services.Message.objects.create', side_effect=DatabaseError('boom')):
            with self.assertRaises(DatabaseError):
                ingest_webhook(envelope)

        # A second delivery of the SAME event (WAHA's natural webhook retry
        # behavior) must retry processing rather than being treated as an
        # already-resolved duplicate.
        result = ingest_webhook(envelope)
        self.assertEqual(result.status, WebhookEvent.STATUS_PROCESSED)
        self.assertTrue(Message.objects.filter(provider_message_id='FIXTURE-MSG-INBOUND-001').exists())
        self.assertEqual(result.attempts, 1)

    def test_foreign_key_integrity(self):
        envelope = parse_envelope(INBOUND_MESSAGE_ENVELOPE)
        ingest_webhook(envelope)
        message = Message.objects.get(provider_message_id='FIXTURE-MSG-INBOUND-001')
        self.assertEqual(message.session.name, 'test_session')
        self.assertEqual(message.chat.provider_chat_id, '000000000000000@lid')


class PersistMessageDuplicateTests(TestCase):
    """Defensive coverage for a scenario not reachable through the current
    parsing rules (provider_event_id and provider_message_id are always the
    same field today — see parsing.py docstring), but kept in case that
    1:1 mapping assumption turns out to be wrong once verified live."""

    def test_duplicate_message_raises_duplicate_message(self):
        session = WahaSession.objects.create(name='s1')
        parsed = ParsedMessage(
            provider_message_id='dup-1',
            chat_provider_id='c1@lid',
            sender_provider_id='c1@lid',
            sender_alt=None,
            from_me=False,
            body='hi',
            message_type='text',
            is_group=False,
            timestamp=timezone.now(),
            push_name=None,
        )
        persist_message(session, parsed)
        with self.assertRaises(DuplicateMessage):
            with transaction.atomic():
                persist_message(session, parsed)

        self.assertEqual(Message.objects.filter(provider_message_id='dup-1').count(), 1)


class PersistMessagePushNameTests(TestCase):
    """docs/generated/INBOX-IDENTITY-DISPLAY-AUDIT-REPORT.md Option 3 —
    display-identity only, no merge, no new Contact ever created to force
    a mapping."""

    def test_inbound_push_name_updates_display_name_of_already_resolved_contact(self):
        session = WahaSession.objects.create(name='s1')
        parsed = ParsedMessage(
            provider_message_id='m1',
            chat_provider_id='c1@lid',
            sender_provider_id='c1@lid',
            sender_alt='62811520892@s.whatsapp.net',
            from_me=False,
            body='hi',
            message_type='text',
            is_group=False,
            timestamp=timezone.now(),
            push_name='Yuk Code Creative',
        )
        persist_message(session, parsed)

        contact = Contact.objects.get(session=session, provider_contact_id='c1@lid')
        self.assertEqual(contact.display_name, 'Yuk Code Creative')
        self.assertEqual(contact.phone_number, '62811520892')
        # No duplicate identity: still exactly one Contact and one Chat.
        self.assertEqual(Contact.objects.count(), 1)
        self.assertEqual(Chat.objects.count(), 1)

    def test_missing_push_name_leaves_display_name_untouched(self):
        session = WahaSession.objects.create(name='s1')
        Contact.objects.create(session=session, provider_contact_id='c1@lid', display_name='Existing Name')
        parsed = ParsedMessage(
            provider_message_id='m1',
            chat_provider_id='c1@lid',
            sender_provider_id='c1@lid',
            sender_alt=None,
            from_me=False,
            body='hi',
            message_type='text',
            is_group=False,
            timestamp=timezone.now(),
            push_name=None,
        )
        persist_message(session, parsed)

        contact = Contact.objects.get(session=session, provider_contact_id='c1@lid')
        self.assertEqual(contact.display_name, 'Existing Name')

    def test_outbound_push_name_is_ignored_no_contact_created(self):
        session = WahaSession.objects.create(name='s1')
        parsed = ParsedMessage(
            provider_message_id='m1',
            chat_provider_id='c1@lid',
            sender_provider_id='c1@lid',
            sender_alt=None,
            from_me=True,
            body='hi',
            message_type='text',
            is_group=False,
            timestamp=timezone.now(),
            push_name='Should Not Apply',
        )
        persist_message(session, parsed)
        self.assertFalse(Contact.objects.exists())

    def test_group_message_push_name_is_ignored_no_contact_created(self):
        session = WahaSession.objects.create(name='s1')
        parsed = ParsedMessage(
            provider_message_id='m1',
            chat_provider_id='g1@g.us',
            sender_provider_id='c1@lid',
            sender_alt=None,
            from_me=False,
            body='hi',
            message_type='text',
            is_group=True,
            timestamp=timezone.now(),
            push_name='Should Not Apply',
        )
        persist_message(session, parsed)
        self.assertFalse(Contact.objects.exists())


class IdempotencyAcrossSessionsTests(TestCase):
    def test_same_message_id_in_different_sessions_both_persist(self):
        envelope_a = parse_envelope(INBOUND_MESSAGE_ENVELOPE)
        other = copy.deepcopy(INBOUND_MESSAGE_ENVELOPE)
        other['session'] = 'session-b'
        envelope_b = parse_envelope(other)

        ingest_webhook(envelope_a)
        ingest_webhook(envelope_b)

        self.assertEqual(Message.objects.filter(provider_message_id='FIXTURE-MSG-INBOUND-001').count(), 2)
