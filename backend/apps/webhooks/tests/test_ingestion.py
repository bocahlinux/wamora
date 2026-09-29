import copy
from unittest import mock

from django.db import DatabaseError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.chats.models import Chat, Contact, ConversationSession, Message
from apps.offices.models import Office
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
        list_reply_row_id=None,
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
            list_reply_row_id=None,
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
            list_reply_row_id=None,
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
            list_reply_row_id=None,
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
            list_reply_row_id=None,
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
            list_reply_row_id=None,
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


class PersistMessageOfficeSnapshotTests(TestCase):
    """Discussed requirement — per-Office Inbox history partitioning:
    Message.office is a SNAPSHOT of chat.office at persist time,
    deliberately never retroactively updated (Message.office's own field
    comment)."""

    def test_message_office_matches_chat_office_at_persist_time(self):
        office = Office.objects.create(name='Samsat Palangka Raya')
        session = WahaSession.objects.create(name='no_epahari', office=office)
        message = persist_message(session, _parsed_message())
        self.assertEqual(message.office, office)

    def test_message_office_is_null_for_unmapped_chat(self):
        session = WahaSession.objects.create(name='no_epahari')  # office=None
        message = persist_message(session, _parsed_message())
        self.assertIsNone(message.office)

    def test_earlier_messages_keep_their_own_office_after_chat_office_changes(self):
        office_a = Office.objects.create(name='Samsat Kasongan')
        office_b = Office.objects.create(name='Samsat Palangka Raya')
        session = WahaSession.objects.create(name='no_epahari')  # office=None
        chat = Chat.objects.create(session=session, provider_chat_id='c1@lid')

        message_1 = persist_message(session, _parsed_message(provider_message_id='m1'))
        self.assertIsNone(message_1.office)

        chat.office = office_a
        chat.save(update_fields=['office'])
        message_2 = persist_message(session, _parsed_message(provider_message_id='m2'))
        self.assertEqual(message_2.office, office_a)

        chat.office = office_b
        chat.save(update_fields=['office'])
        message_3 = persist_message(session, _parsed_message(provider_message_id='m3'))
        self.assertEqual(message_3.office, office_b)

        message_1.refresh_from_db()
        message_2.refresh_from_db()
        self.assertIsNone(message_1.office)
        self.assertEqual(message_2.office, office_a)


class PersistMessageOutboundCompletionFallbackTests(TestCase):
    """Regression — found live: apps.chats.conversation_engine's own
    session-completion paths (close_waiting_session/
    expire_waiting_operator_session/_handle_menu_item's completion
    branches) always complete the ConversationSession FIRST, then send
    the "sesi selesai" confirmation — so by the time that OUTBOUND,
    self-sent message is reconciled, its own session is already
    COMPLETED (not "active"), and was incorrectly falling through to
    `None` (persist_message's own comment: "between rounds"), banishing
    the citizen's own closing confirmation out of the Office they were
    just routed to. Fixed: an OUTBOUND message with no active session
    falls back to the most recently created session's Office instead —
    safe because the bot never speaks first into a not-yet-started round
    (only a citizen's INBOUND message can be pre-handoff chatter)."""

    def _parsed_outbound(self, **overrides):
        defaults = dict(
            provider_message_id='out-1', chat_provider_id='c1@lid', sender_provider_id='c1@lid',
            sender_alt=None, from_me=True, body='closing text', message_type='text', is_group=False,
            timestamp=timezone.now(), push_name=None, list_reply_row_id=None,
        )
        defaults.update(overrides)
        return ParsedMessage(**defaults)

    def test_closing_confirmation_is_tagged_to_the_just_completed_sessions_office(self):
        office = Office.objects.create(name='Samsat Kasongan')
        session = WahaSession.objects.create(name='no_epahari')
        chat = Chat.objects.create(session=session, provider_chat_id='c1@lid', office=office)
        cs = ConversationSession.objects.create(
            chat=chat, state=ConversationSession.STATE_WAITING_OPERATOR, office=office,
        )
        # Exact order apps.chats.conversation_engine.close_waiting_session
        # uses: complete the session, THEN (later, asynchronously
        # reconciled) the closing text gets persisted.
        cs.state = ConversationSession.STATE_COMPLETED
        cs.completed_at = timezone.now()
        cs.current_menu = None
        cs.save(update_fields=['state', 'completed_at', 'current_menu', 'updated_at'])

        message = persist_message(session, self._parsed_outbound())

        self.assertEqual(message.office, office)

    def test_inbound_pre_handoff_message_after_close_is_still_none(self):
        # The fix above is deliberately OUTBOUND-only — an INBOUND
        # message (the citizen re-engaging) in the same "no active
        # session" state must still resolve to None, never the old
        # session's Office (that's the original "Menu/2/2" bug this
        # would otherwise resurrect).
        office = Office.objects.create(name='Samsat Kasongan')
        session = WahaSession.objects.create(name='no_epahari')
        chat = Chat.objects.create(session=session, provider_chat_id='c1@lid', office=office)
        ConversationSession.objects.create(chat=chat, state=ConversationSession.STATE_COMPLETED, office=office)

        message = persist_message(session, _parsed_message(from_me=False))

        self.assertIsNone(message.office)


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


class WebhookConversationEngineIntegrationTests(TestCase):
    """Conversation/Bot Engine — proves the real `ingest_webhook()` ->
    `persist_message()` -> `handle_conversation_message()` wiring, through
    the actual live webhook entrypoint (not calling
    `handle_conversation_message` directly, unlike
    `apps.chats.test_conversation_engine`'s unit tests). Supersedes the
    old Step 12 `WebhookOperatorChatIntegrationTests` — `ingest_webhook`
    no longer calls `apps.chats.operator_chat` at all (see
    `apps.webhooks.services`'s own comment)."""

    def setUp(self):
        from apps.bot.models import BotConfig, BotMenu

        menu = BotMenu.objects.create(name='Main Menu', intro_text='Selamat datang.')
        BotConfig.objects.create(office=None, enabled=True, root_menu=menu)

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_new_inbound_webhook_message_triggers_the_bot(self, mocked_send):
        envelope = parse_envelope(INBOUND_MESSAGE_ENVELOPE)
        ingest_webhook(envelope)
        mocked_send.assert_called_once()
        self.assertIn('Selamat datang.', mocked_send.call_args[0][2])

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_duplicate_webhook_delivery_sends_the_auto_reply_only_once(self, mocked_send):
        envelope = parse_envelope(INBOUND_MESSAGE_ENVELOPE)
        ingest_webhook(envelope)  # first delivery
        ingest_webhook(envelope)  # WAHA retry of the SAME event
        mocked_send.assert_called_once()

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_reconciliation_history_backfill_never_triggers_the_bot(self, mocked_send):
        # persist_message() is shared with apps.sync.reconciliation, which
        # calls it directly (bypassing ingest_webhook) for old history —
        # that path must never send a fresh bot reply.
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


class WebhookConversationEngineOfficeScopedIntegrationTests(TestCase):
    """Conversation/Bot Engine — proves the real `ingest_webhook()` wiring
    still applies an Office-specific `BotConfig`/`BotMenu` once a Chat has
    a selected Office, through the actual live webhook entrypoint.
    Supersedes the old Step 13 welcome-lifecycle integration tests
    (`welcome_sent_at`/`OfficeInboxConfig.welcome_message` are no longer
    read by the live webhook path at all — see `Chat.welcome_sent_at`'s
    own deprecation comment)."""

    def setUp(self):
        from apps.bot.models import BotConfig, BotMenu

        self.office = Office.objects.create(name='Samsat Palangka Raya')
        office_menu = BotMenu.objects.create(office=self.office, name='Menu Office', intro_text='Menu khusus Office.')
        BotConfig.objects.create(office=self.office, enabled=True, root_menu=office_menu)
        self.session_name = 'no_epahari'

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_chat_with_an_office_uses_that_offices_bot_config(self, mocked_send):
        chat_id = 'wp-i@lid'
        session = WahaSession.objects.create(name=self.session_name)
        Chat.objects.create(session=session, provider_chat_id=chat_id, office=self.office)

        ingest_webhook(_envelope(self.session_name, chat_id, 'Halo', 'evt-i1'))

        mocked_send.assert_called_once()
        self.assertIn('Menu khusus Office.', mocked_send.call_args[0][2])

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_reconciliation_never_sends_a_bot_reply_even_with_a_mapped_office(self, mocked_send):
        session = WahaSession.objects.create(name='reconcile-welcome-session')
        chat = Chat.objects.create(session=session, provider_chat_id='old-mapped@lid', office=self.office)
        persist_message(session, _parsed_message(chat_provider_id='old-mapped@lid', provider_message_id='hist-1'))
        mocked_send.assert_not_called()
        chat.refresh_from_db()
        self.assertIsNone(chat.welcome_sent_at)


class WebhookConversationEngineOfficeReselectionTests(TestCase):
    """Regression — found live: a citizen who closed a handoff to Office
    A, then re-triggered the bot menu (typing "Menu" and navigating
    again) BEFORE picking any Office for this new round, had that entire
    pre-handoff exchange mis-tagged as Office A's history (`chat.office`
    is only updated once a NEW Office is actually picked, so it still
    held Office A's value from the previous round) — showing up in
    Office A's Inbox even though the citizen hadn't been routed anywhere
    yet this round. `persist_message`'s own comment documents the fix:
    source `Message.office` from the Chat's currently ACTIVE
    `ConversationSession.office` instead."""

    def setUp(self):
        from apps.bot.models import BotConfig, BotMenu, BotMenuItem, BotTrigger
        from apps.offices.models import OfficeInboxConfig

        self.office_a = Office.objects.create(name='Samsat Kasongan')
        OfficeInboxConfig.objects.create(office=self.office_a, enabled=True)
        self.root_menu = BotMenu.objects.create(name='Main Menu', intro_text='Selamat datang.')
        selector_menu = BotMenu.objects.create(name='Pilih Office', is_office_selector=True)
        BotMenuItem.objects.create(
            menu=self.root_menu, label='Chat dengan Operator', trigger_value='4',
            action_type=BotMenuItem.ACTION_SHOW_MENU, target_menu=selector_menu,
        )
        BotTrigger.objects.create(office=None, keyword='menu', target_menu=self.root_menu, enabled=True)
        BotConfig.objects.create(office=None, enabled=True, root_menu=self.root_menu)
        self.session_name = 'no_epahari'
        self.chat_id = 'wp1@lid'

    def _send(self, body, event_id):
        ingest_webhook(_envelope(self.session_name, self.chat_id, body, event_id))

    def _last_message_office(self):
        return Message.objects.filter(chat__provider_chat_id=self.chat_id).order_by('-id').first().office

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_pre_handoff_navigation_after_a_closed_session_is_never_tagged_to_the_old_office(self, mocked_send):
        # Round 1: trigger, pick "Chat dengan Operator", select the only
        # available Office (position 1 — Kasongan).
        self._send('Menu', 'evt-1')
        self._send('4', 'evt-2')
        self._send('1', 'evt-3')  # the selection reply itself stays None — see below
        chat = Chat.objects.get(provider_chat_id=self.chat_id)
        self.assertEqual(chat.office, self.office_a)
        self._send('Terima kasih', 'evt-3b')  # first message AFTER the pick takes effect
        self.assertEqual(self._last_message_office(), self.office_a)

        # Operator closes the session — same STATE_COMPLETED transition
        # apps.chats.views.ChatCloseSessionView triggers.
        ConversationSession.objects.filter(chat=chat, state=ConversationSession.STATE_WAITING_OPERATOR).update(
            state=ConversationSession.STATE_COMPLETED,
        )

        # Round 2: the citizen chats again and navigates the bot menu —
        # but has NOT picked an Office yet this round. None of this may
        # be tagged to Office A (the previous round's pick).
        self._send('Selamat sore pak', 'evt-4')
        self.assertIsNone(self._last_message_office())
        self._send('Menu', 'evt-5')
        self.assertIsNone(self._last_message_office())
        self._send('4', 'evt-6')
        self.assertIsNone(self._last_message_office())

        # The selection reply ITSELF ("1") is still tagged None — an
        # accepted, documented edge case (the Office isn't applied until
        # AFTER this message is already persisted — see
        # conversation_engine._handle_office_selector_reply's own "Race
        # note"). What matters is the SESSION now reflects the pick...
        self._send('1', 'evt-7')
        chat.refresh_from_db()
        self.assertEqual(chat.office, self.office_a)
        self.assertEqual(
            ConversationSession.objects.get(chat=chat, state=ConversationSession.STATE_WAITING_OPERATOR).office,
            self.office_a,
        )
        # ...so the NEXT message (an operator's reply, or anything after)
        # correctly resumes tagging to the newly-picked Office.
        self._send('Terima kasih', 'evt-8')
        self.assertEqual(self._last_message_office(), self.office_a)
