import copy
from unittest import mock

from django.db import DatabaseError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.chats.models import Chat, Contact, Message
from apps.offices.models import Office, OfficeInboxConfig
from apps.waha_sessions.models import WahaSession
from apps.webhooks.models import WebhookEvent
from apps.webhooks.parsing import ParsedMessage, parse_envelope
from apps.webhooks.services import DuplicateMessage, persist_message, ingest_webhook
from apps.webhooks.tests.fixtures import INBOUND_MESSAGE_ENVELOPE


def _parsed_message(**overrides):
    defaults = dict(
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
    defaults.update(overrides)
    return ParsedMessage(**defaults)


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


class PersistMessageOfficeRoutingTests(TestCase):
    """Step 9 (Inbox Office routing foundation) — a NEW Chat's `office` is
    copied from `WahaSession.office` at creation time only."""

    def test_new_chat_gets_office_from_mapped_session(self):
        office = Office.objects.create(name='Samsat Palangka Raya')
        session = WahaSession.objects.create(name='no_epahari', office=office)
        persist_message(session, _parsed_message())
        chat = Chat.objects.get(session=session, provider_chat_id='c1@lid')
        self.assertEqual(chat.office, office)

    def test_new_chat_office_stays_null_for_an_unmapped_session(self):
        session = WahaSession.objects.create(name='no_epahari')  # office=None
        persist_message(session, _parsed_message())
        chat = Chat.objects.get(session=session, provider_chat_id='c1@lid')
        self.assertIsNone(chat.office)
        # Unmapped must never silently create/guess an Office either.
        self.assertFalse(Office.objects.exists())

    def test_two_sessions_route_to_their_own_office(self):
        office_a = Office.objects.create(name='Samsat Palangka Raya')
        office_b = Office.objects.create(name='Samsat Kasongan')
        session_a = WahaSession.objects.create(name='session-a', office=office_a)
        session_b = WahaSession.objects.create(name='session-b', office=office_b)

        persist_message(session_a, _parsed_message(chat_provider_id='ca@lid', sender_provider_id='ca@lid'))
        persist_message(session_b, _parsed_message(chat_provider_id='cb@lid', sender_provider_id='cb@lid'))

        chat_a = Chat.objects.get(session=session_a, provider_chat_id='ca@lid')
        chat_b = Chat.objects.get(session=session_b, provider_chat_id='cb@lid')
        self.assertEqual(chat_a.office, office_a)
        self.assertEqual(chat_b.office, office_b)

    def test_existing_chat_office_is_never_overwritten_by_a_later_message(self):
        office_a = Office.objects.create(name='Office A')
        office_b = Office.objects.create(name='Office B')
        session = WahaSession.objects.create(name='no_epahari', office=office_a)
        persist_message(session, _parsed_message(provider_message_id='m1'))
        chat = Chat.objects.get(session=session, provider_chat_id='c1@lid')
        self.assertEqual(chat.office, office_a)

        # The session's mapping changes later — must NOT retroactively
        # move this already-existing Chat.
        session.office = office_b
        session.save(update_fields=['office'])
        persist_message(session, _parsed_message(provider_message_id='m2'))

        chat.refresh_from_db()
        self.assertEqual(chat.office, office_a)


class OfficeRoutedInboxVisibilityTests(TestCase):
    """Step 9 end-to-end: WahaSession.office -> persist_message ->
    Chat.office -> apps.chats.authorization.chats_visible_to (unchanged
    since Step 5) actually isolates by Office through the real ingestion
    path, not just manually-constructed Chat rows."""

    def setUp(self):
        from django.contrib.auth.models import User

        from apps.offices.models import OfficeMembership, Role

        self.office_a = Office.objects.create(name='Samsat Palangka Raya')
        self.office_b = Office.objects.create(name='Samsat Kasongan')
        self.session_a = WahaSession.objects.create(name='session-a', office=self.office_a)
        self.session_b = WahaSession.objects.create(name='session-b', office=self.office_b)

        persist_message(self.session_a, _parsed_message(chat_provider_id='ca@lid', sender_provider_id='ca@lid'))
        persist_message(self.session_b, _parsed_message(chat_provider_id='cb@lid', sender_provider_id='cb@lid'))
        self.chat_a = Chat.objects.get(session=self.session_a, provider_chat_id='ca@lid')
        self.chat_b = Chat.objects.get(session=self.session_b, provider_chat_id='cb@lid')

        self.admin_a = User.objects.create_user('admin_a_e2e', password='pw')
        role = Role.objects.create(name='Office Admin', is_office_admin=True)
        OfficeMembership.objects.create(user=self.admin_a, office=self.office_a, role=role, requires_office=True)
        self.superuser = User.objects.create_superuser('super_e2e', 'super_e2e@example.com', 'pw')

    def test_office_admin_sees_own_office_chat_from_real_ingestion(self):
        from apps.chats.authorization import chats_visible_to

        visible = set(chats_visible_to(self.admin_a).values_list('pk', flat=True))
        self.assertIn(self.chat_a.pk, visible)

    def test_office_admin_does_not_see_other_office_chat_from_real_ingestion(self):
        from apps.chats.authorization import chats_visible_to

        visible = set(chats_visible_to(self.admin_a).values_list('pk', flat=True))
        self.assertNotIn(self.chat_b.pk, visible)

    def test_superadmin_sees_both_offices_chats_from_real_ingestion(self):
        from apps.chats.authorization import chats_visible_to

        visible = set(chats_visible_to(self.superuser).values_list('pk', flat=True))
        self.assertEqual(visible, {self.chat_a.pk, self.chat_b.pk})


class WebhookOperatorChatIntegrationTests(TestCase):
    """Step 12 — proves the real `ingest_webhook()` -> `persist_message()`
    -> `handle_operator_chat_message()` wiring, through the actual live
    webhook entrypoint (not calling `handle_operator_chat_message`
    directly, unlike `apps.chats.test_operator_chat`'s unit tests)."""

    def setUp(self):
        office = Office.objects.create(name='Samsat Palangka Raya')
        OfficeInboxConfig.objects.create(office=office, enabled=True)

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_new_inbound_webhook_message_triggers_operator_chat_menu(self, mocked_send):
        envelope = parse_envelope(INBOUND_MESSAGE_ENVELOPE)
        ingest_webhook(envelope)
        mocked_send.assert_called_once()
        self.assertIn('Samsat Palangka Raya', mocked_send.call_args[0][2])

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_duplicate_webhook_delivery_sends_the_auto_reply_only_once(self, mocked_send):
        envelope = parse_envelope(INBOUND_MESSAGE_ENVELOPE)
        ingest_webhook(envelope)  # first delivery
        ingest_webhook(envelope)  # WAHA retry of the SAME event
        mocked_send.assert_called_once()

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_reconciliation_history_backfill_never_triggers_the_auto_reply(self, mocked_send):
        # persist_message() is shared with apps.sync.reconciliation, which
        # calls it directly (bypassing ingest_webhook) for old history —
        # that path must never send a fresh "select an Office" reply.
        session = WahaSession.objects.create(name='reconcile-session')
        persist_message(session, _parsed_message(chat_provider_id='old-chat@lid'))
        mocked_send.assert_not_called()


def _envelope(session_name, chat_id, body, event_id):
    raw = copy.deepcopy(INBOUND_MESSAGE_ENVELOPE)
    raw['session'] = session_name
    raw['payload']['id'] = event_id
    raw['payload']['from'] = chat_id
    raw['payload']['body'] = body
    raw['payload']['_data']['Info']['Chat'] = chat_id
    raw['payload']['_data']['Info']['Sender'] = chat_id
    return parse_envelope(raw)


class WebhookInboxWelcomeLifecycleIntegrationTests(TestCase):
    """Step 13 — proves the real `ingest_webhook()` -> branch-by-`Chat.office`
    -> `handle_inbox_lifecycle_message()` wiring through the actual live
    webhook entrypoint, and the Step 12/13 handoff timing."""

    def setUp(self):
        self.office = Office.objects.create(name='Samsat Palangka Raya')
        self.config = OfficeInboxConfig.objects.create(
            office=self.office, enabled=True, welcome_message='Selamat datang.'
        )
        self.session_name = 'no_epahari'

    # -- H: Chat.office NULL stays Step 12's job, welcome never fires --------

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_unmapped_chat_uses_office_selection_not_welcome(self, mocked_operator_send, mocked_welcome_send):
        ingest_webhook(_envelope(self.session_name, 'wp-h@lid', 'Halo', 'evt-h1'))
        mocked_operator_send.assert_called_once()  # Step 12 menu
        mocked_welcome_send.assert_not_called()

    # -- I: selection turn -> no welcome; NEXT inbound -> welcome once -------

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_welcome_starts_only_from_the_message_after_office_selection(self, mocked_operator_send, mocked_welcome_send):
        chat_id = 'wp-i@lid'
        # Turn 1: first contact, still unmapped -> Step 12 menu.
        ingest_webhook(_envelope(self.session_name, chat_id, 'Halo', 'evt-i1'))
        mocked_welcome_send.assert_not_called()

        # Turn 2: WP replies with the Office's own ID -> Step 12 sets
        # Chat.office and sends its OWN confirmation text — welcome must
        # NOT also fire on this same turn (Step 13's documented timing).
        ingest_webhook(_envelope(self.session_name, chat_id, str(self.office.pk), 'evt-i2'))
        chat = Chat.objects.get(session__name=self.session_name, provider_chat_id=chat_id)
        self.assertEqual(chat.office, self.office)
        mocked_welcome_send.assert_not_called()

        # Turn 3: next inbound message, Chat.office already set -> welcome
        # fires exactly once.
        ingest_webhook(_envelope(self.session_name, chat_id, 'ok', 'evt-i3'))
        mocked_welcome_send.assert_called_once()
        self.assertEqual(mocked_welcome_send.call_args[0][2], 'Selamat datang.')

        # Turn 4: yet another message -> no second welcome.
        ingest_webhook(_envelope(self.session_name, chat_id, 'ok lagi', 'evt-i4'))
        mocked_welcome_send.assert_called_once()

    # -- J: reconciliation never sends welcome ---------------------------------

    @mock.patch('apps.chats.inbox_lifecycle.send_blast_message')
    def test_reconciliation_never_sends_welcome_even_with_a_mapped_office(self, mocked_welcome_send):
        session = WahaSession.objects.create(name='reconcile-welcome-session')
        chat = Chat.objects.create(session=session, provider_chat_id='old-mapped@lid', office=self.office)
        persist_message(session, _parsed_message(chat_provider_id='old-mapped@lid', provider_message_id='hist-1'))
        mocked_welcome_send.assert_not_called()
        chat.refresh_from_db()
        self.assertIsNone(chat.welcome_sent_at)
