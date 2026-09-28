from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.chats.inbox_lifecycle import handle_inbox_lifecycle_message
from apps.chats.models import Chat, Message
from apps.offices.models import Office, OfficeInboxConfig
from apps.waha_sessions.models import WahaSession

WELCOME = 'Halo, Anda terhubung dengan Petugas Samsat Palangka Raya.'


class HandleInboxLifecycleMessageTests(TestCase):
    """Step 13 — welcome-only Inbox lifecycle. `send_blast_message` is
    always mocked (same discipline as Step 12) — never a real network
    call."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='no_epahari')
        self.office = Office.objects.create(name='Samsat Palangka Raya')
        self.config = OfficeInboxConfig.objects.create(office=self.office, enabled=True, welcome_message=WELCOME)

    def _inbound(self, chat, body='pesan', provider_message_id='m1'):
        return Message.objects.create(
            session=self.session, chat=chat, provider_message_id=provider_message_id,
            direction=Message.DIRECTION_INBOUND, message_type='text', body=body, timestamp=timezone.now(),
        )

    def _chat(self, office=None, provider_chat_id='wp1@lid', **extra):
        return Chat.objects.create(session=self.session, provider_chat_id=provider_chat_id, office=office, **extra)

    # -- A/B: sends once when everything is satisfied -----------------------

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_welcome_sent_when_office_active_config_enabled_and_never_sent(self, mocked_send):
        chat = self._chat(office=self.office)
        handle_inbox_lifecycle_message(self.session, self._inbound(chat))
        mocked_send.assert_called_once()
        self.assertEqual(mocked_send.call_args[0][2], WELCOME)
        chat.refresh_from_db()
        self.assertIsNotNone(chat.welcome_sent_at)

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_welcome_sent_only_once(self, mocked_send):
        chat = self._chat(office=self.office)
        handle_inbox_lifecycle_message(self.session, self._inbound(chat, provider_message_id='m1'))
        handle_inbox_lifecycle_message(self.session, self._inbound(chat, provider_message_id='m2'))
        self.assertEqual(mocked_send.call_count, 1)

    # -- C: duplicate/replayed webhook (same claim guard) --------------------

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_calling_twice_for_the_same_message_does_not_double_send(self, mocked_send):
        chat = self._chat(office=self.office)
        message = self._inbound(chat)
        handle_inbox_lifecycle_message(self.session, message)
        handle_inbox_lifecycle_message(self.session, message)  # simulated replay
        self.assertEqual(mocked_send.call_count, 1)

    # -- D: empty welcome_message ---------------------------------------------

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_empty_welcome_message_sends_nothing_and_leaves_timestamp_null(self, mocked_send):
        self.config.welcome_message = ''
        self.config.save(update_fields=['welcome_message'])
        chat = self._chat(office=self.office)
        handle_inbox_lifecycle_message(self.session, self._inbound(chat))
        mocked_send.assert_not_called()
        chat.refresh_from_db()
        self.assertIsNone(chat.welcome_sent_at)

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_whitespace_only_welcome_message_sends_nothing(self, mocked_send):
        self.config.welcome_message = '   '
        self.config.save(update_fields=['welcome_message'])
        chat = self._chat(office=self.office)
        handle_inbox_lifecycle_message(self.session, self._inbound(chat))
        mocked_send.assert_not_called()
        chat.refresh_from_db()
        self.assertIsNone(chat.welcome_sent_at)

    # -- E: InboxConfig.enabled=False -----------------------------------------

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_disabled_inbox_config_sends_nothing(self, mocked_send):
        self.config.enabled = False
        self.config.save(update_fields=['enabled'])
        chat = self._chat(office=self.office)
        handle_inbox_lifecycle_message(self.session, self._inbound(chat))
        mocked_send.assert_not_called()
        chat.refresh_from_db()
        self.assertIsNone(chat.welcome_sent_at)

    # -- F: Office inactive ----------------------------------------------------

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_inactive_office_sends_nothing(self, mocked_send):
        self.office.is_active = False
        self.office.save(update_fields=['is_active'])
        chat = self._chat(office=self.office)
        handle_inbox_lifecycle_message(self.session, self._inbound(chat))
        mocked_send.assert_not_called()
        chat.refresh_from_db()
        self.assertIsNone(chat.welcome_sent_at)

    # -- G: no InboxConfig at all -----------------------------------------------

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_office_with_no_inbox_config_does_not_crash_and_sends_nothing(self, mocked_send):
        bare_office = Office.objects.create(name='Office No Config')
        self.assertFalse(OfficeInboxConfig.objects.filter(office=bare_office).exists())
        chat = self._chat(office=bare_office, provider_chat_id='wp-noconfig@lid')
        handle_inbox_lifecycle_message(self.session, self._inbound(chat))  # must not raise
        mocked_send.assert_not_called()
        chat.refresh_from_db()
        self.assertIsNone(chat.welcome_sent_at)
        self.assertFalse(OfficeInboxConfig.objects.filter(office=bare_office).exists())  # never auto-created

    # -- L: existing Chat.office is never overwritten by lifecycle ------------

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_lifecycle_never_changes_which_office_a_chat_belongs_to(self, mocked_send):
        other_office = Office.objects.create(name='Other Office')
        chat = self._chat(office=self.office)
        handle_inbox_lifecycle_message(self.session, self._inbound(chat))
        chat.refresh_from_db()
        self.assertEqual(chat.office, self.office)
        self.assertNotEqual(chat.office, other_office)

    # -- K: WahaSession.office untouched ----------------------------------------

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_waha_session_office_is_never_changed(self, mocked_send):
        self.session.office = self.office
        self.session.save(update_fields=['office'])
        chat = self._chat(office=self.office)
        handle_inbox_lifecycle_message(self.session, self._inbound(chat))
        self.session.refresh_from_db()
        self.assertEqual(self.session.office, self.office)


class WelcomeRaceConditionTests(TestCase):
    """Step 13 Section 6 — two near-simultaneous deliveries for the same
    Chat must never both pass the claim and both send."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='no_epahari')
        self.office = Office.objects.create(name='Office A')
        OfficeInboxConfig.objects.create(office=self.office, enabled=True, welcome_message=WELCOME)
        self.chat = Chat.objects.create(session=self.session, provider_chat_id='wp-race@lid', office=self.office)

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_concurrent_claim_only_lets_one_caller_through(self, mocked_send):
        m1 = Message.objects.create(
            session=self.session, chat=self.chat, provider_message_id='race-1',
            direction=Message.DIRECTION_INBOUND, message_type='text', body='a', timestamp=timezone.now(),
        )
        m2 = Message.objects.create(
            session=self.session, chat=self.chat, provider_message_id='race-2',
            direction=Message.DIRECTION_INBOUND, message_type='text', body='b', timestamp=timezone.now(),
        )
        # Simulates two webhook deliveries racing to process the same
        # Chat — the second call's compare-and-set UPDATE must affect 0
        # rows since the first already claimed it.
        handle_inbox_lifecycle_message(self.session, m1)
        handle_inbox_lifecycle_message(self.session, m2)
        self.assertEqual(mocked_send.call_count, 1)


class OfficeIsolationTests(TestCase):
    """Step 13 — one Office's configuration/state never affects another's.
    No new admin-facing mutation endpoint was added in this step (see the
    final report), so this exercises the isolation that DOES apply here:
    the lifecycle side-effect itself never crosses Office boundaries."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='no_epahari')
        self.office_a = Office.objects.create(name='Office A')
        self.office_b = Office.objects.create(name='Office B')
        OfficeInboxConfig.objects.create(office=self.office_a, enabled=True, welcome_message='Welcome A')
        OfficeInboxConfig.objects.create(office=self.office_b, enabled=False, welcome_message='Welcome B')

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_office_b_being_disabled_does_not_block_office_as_welcome(self, mocked_send):
        chat_a = Chat.objects.create(session=self.session, provider_chat_id='a@lid', office=self.office_a)
        handle_inbox_lifecycle_message(
            self.session,
            Message.objects.create(
                session=self.session, chat=chat_a, provider_message_id='iso-1',
                direction=Message.DIRECTION_INBOUND, message_type='text', body='hi', timestamp=timezone.now(),
            ),
        )
        mocked_send.assert_called_once()
        self.assertEqual(mocked_send.call_args[0][2], 'Welcome A')

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_office_a_being_enabled_does_not_make_office_b_send(self, mocked_send):
        chat_b = Chat.objects.create(session=self.session, provider_chat_id='b@lid', office=self.office_b)
        handle_inbox_lifecycle_message(
            self.session,
            Message.objects.create(
                session=self.session, chat=chat_b, provider_message_id='iso-2',
                direction=Message.DIRECTION_INBOUND, message_type='text', body='hi', timestamp=timezone.now(),
            ),
        )
        mocked_send.assert_not_called()
