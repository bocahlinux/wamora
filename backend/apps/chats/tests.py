from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.chats.models import Chat, Contact, MediaReference, Message
from apps.waha_sessions.models import WahaSession


class ContactTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='default')

    def test_unique_per_session(self):
        Contact.objects.create(session=self.session, provider_contact_id='62811@c.us')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Contact.objects.create(session=self.session, provider_contact_id='62811@c.us')


class ChatTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='default')

    def test_unique_per_session(self):
        Chat.objects.create(session=self.session, provider_chat_id='62811@c.us')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Chat.objects.create(session=self.session, provider_chat_id='62811@c.us')


class MessageIdentityTests(TestCase):
    """docs/04-DATA-MODEL.md "Message identity": stable provider ID scoped
    by session — never body/timestamp/sender alone."""

    def setUp(self):
        self.session_a = WahaSession.objects.create(name='session-a')
        self.session_b = WahaSession.objects.create(name='session-b')
        self.chat_a = Chat.objects.create(session=self.session_a, provider_chat_id='62811@c.us')
        self.chat_b = Chat.objects.create(session=self.session_b, provider_chat_id='62811@c.us')

    def _make_message(self, session, chat, provider_message_id, **overrides):
        fields = {
            'session': session,
            'chat': chat,
            'provider_message_id': provider_message_id,
            'direction': Message.DIRECTION_INBOUND,
            'timestamp': timezone.now(),
        }
        fields.update(overrides)
        return Message.objects.create(**fields)

    def test_duplicate_provider_message_id_rejected_within_same_session(self):
        self._make_message(self.session_a, self.chat_a, 'wamid.ABC123')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                # Different body/timestamp/sender must NOT bypass the identity rule.
                self._make_message(
                    self.session_a, self.chat_a, 'wamid.ABC123', body='a different body'
                )

    def test_same_provider_message_id_allowed_across_different_sessions(self):
        # Proves identity is scoped by session, not global.
        self._make_message(self.session_a, self.chat_a, 'wamid.ABC123')
        self._make_message(self.session_b, self.chat_b, 'wamid.ABC123')
        self.assertEqual(Message.objects.filter(provider_message_id='wamid.ABC123').count(), 2)


class MediaReferenceTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='default')
        self.chat = Chat.objects.create(session=self.session, provider_chat_id='62811@c.us')
        self.message = Message.objects.create(
            session=self.session,
            chat=self.chat,
            provider_message_id='wamid.ABC123',
            direction=Message.DIRECTION_INBOUND,
            timestamp=timezone.now(),
        )

    def test_cascades_on_message_delete(self):
        MediaReference.objects.create(message=self.message, provider_media_id='media-1')
        self.message.delete()
        self.assertEqual(MediaReference.objects.count(), 0)
