from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.bot.models import BotConfig, BotMenu, BotMenuItem, BotTrigger
from apps.chats.conversation_engine import HANDOFF_ACK_TEXT, handle_conversation_message
from apps.chats.models import Chat, ConversationSession, Message
from apps.offices.models import Office, OfficeInboxConfig
from apps.waha_sessions.models import WahaSession


class ConversationEngineTestCase(TestCase):
    """`send_blast_message` is always mocked at
    `apps.chats.conversation_engine.send_blast_message` — the engine's own
    import of it, never a real network/WAHA call, matching this project's
    existing discipline (`apps.chats.test_operator_chat`)."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='no_epahari')
        self.root_menu = BotMenu.objects.create(
            name='Main Menu', intro_text='Selamat datang di layanan Samsat.',
        )
        self.config = BotConfig.objects.create(
            office=None, enabled=True, fallback_message='Maaf, pilihan tidak dikenali.',
            session_completed_message='Terima kasih. Ketik "Menu" untuk memulai lagi.',
            root_menu=self.root_menu,
        )
        BotTrigger.objects.create(office=None, keyword='halo', target_menu=self.root_menu, enabled=True)
        BotTrigger.objects.create(office=None, keyword='menu', target_menu=self.root_menu, enabled=True)

    def _chat(self, provider_chat_id='wp1@lid', **kwargs):
        return Chat.objects.create(session=self.session, provider_chat_id=provider_chat_id, **kwargs)

    def _inbound(self, chat, body, provider_message_id='m1'):
        return Message.objects.create(
            session=self.session, chat=chat, provider_message_id=provider_message_id,
            direction=Message.DIRECTION_INBOUND, message_type='text', body=body, timestamp=timezone.now(),
        )

    def _sent_text(self, mocked_send, call_index=0):
        return mocked_send.call_args_list[call_index][0][2]

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_bot_disabled_globally_is_a_silent_noop(self, mocked_send):
        self.config.enabled = False
        self.config.save(update_fields=['enabled'])
        chat = self._chat()
        handle_conversation_message(self.session, self._inbound(chat, 'Halo'))
        mocked_send.assert_not_called()
        self.assertFalse(ConversationSession.objects.exists())

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_new_number_first_message_shows_main_menu_never_auto_selects_office(self, mocked_send):
        chat = self._chat()
        handle_conversation_message(self.session, self._inbound(chat, 'apa kabar'))

        chat.refresh_from_db()
        self.assertIsNone(chat.office)  # correction #3: no auto-selection
        mocked_send.assert_called_once()
        text = self._sent_text(mocked_send)
        self.assertIn('Maaf, pilihan tidak dikenali.', text)  # fallback, never silent
        self.assertIn('Selamat datang', text)

        session = ConversationSession.objects.get(chat=chat)
        self.assertEqual(session.state, ConversationSession.STATE_ACTIVE)
        self.assertEqual(session.current_menu, self.root_menu)

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_global_trigger_halo_shows_main_menu_without_fallback_prefix(self, mocked_send):
        chat = self._chat()
        handle_conversation_message(self.session, self._inbound(chat, 'Halo'))
        text = self._sent_text(mocked_send)
        self.assertNotIn('Maaf, pilihan tidak dikenali.', text)
        self.assertIn('Selamat datang', text)

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_global_trigger_resets_mid_submenu_to_main_menu(self, mocked_send):
        chat = self._chat()
        sub_menu = BotMenu.objects.create(name='Sub Menu', intro_text='Ini submenu.')
        BotMenuItem.objects.create(
            menu=self.root_menu, label='Buka submenu', trigger_value='1',
            action_type=BotMenuItem.ACTION_SHOW_MENU, target_menu=sub_menu,
        )
        handle_conversation_message(self.session, self._inbound(chat, 'Halo', 'm1'))
        handle_conversation_message(self.session, self._inbound(chat, '1', 'm2'))
        session = ConversationSession.objects.get(chat=chat, state__in=ConversationSession.ACTIVE_STATES)
        self.assertEqual(session.current_menu, sub_menu)

        mocked_send.reset_mock()
        handle_conversation_message(self.session, self._inbound(chat, 'Menu', 'm3'))

        self.assertEqual(ConversationSession.objects.filter(chat=chat).count(), 2)  # history preserved
        active = ConversationSession.objects.get(chat=chat, state__in=ConversationSession.ACTIVE_STATES)
        self.assertEqual(active.current_menu, self.root_menu)
        text = self._sent_text(mocked_send)
        self.assertIn('Selamat datang', text)

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_unrecognized_message_with_active_session_reshows_current_menu(self, mocked_send):
        chat = self._chat()
        handle_conversation_message(self.session, self._inbound(chat, 'Halo', 'm1'))
        session_before = ConversationSession.objects.get(chat=chat)
        mocked_send.reset_mock()

        handle_conversation_message(self.session, self._inbound(chat, 'zzz tidak dikenal', 'm2'))

        text = self._sent_text(mocked_send)
        self.assertIn('Maaf, pilihan tidak dikenali.', text)
        self.assertIn('Selamat datang', text)  # same menu re-shown
        session_after = ConversationSession.objects.get(chat=chat)
        self.assertEqual(session_before.pk, session_after.pk)
        self.assertEqual(session_after.state, ConversationSession.STATE_ACTIVE)
        self.assertEqual(session_after.current_menu, self.root_menu)

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_send_text_action_completes_session_and_sends_completion_message(self, mocked_send):
        chat = self._chat()
        BotMenuItem.objects.create(
            menu=self.root_menu, label='Info jam operasional', trigger_value='9',
            action_type=BotMenuItem.ACTION_SEND_TEXT, text='Kami buka Senin-Jumat 08.00-15.00.',
        )
        handle_conversation_message(self.session, self._inbound(chat, 'Halo', 'm1'))
        mocked_send.reset_mock()

        handle_conversation_message(self.session, self._inbound(chat, '9', 'm2'))

        self.assertEqual(self._sent_text(mocked_send, 0), 'Kami buka Senin-Jumat 08.00-15.00.')
        self.assertIn('Terima kasih', self._sent_text(mocked_send, 1))
        session = ConversationSession.objects.get(chat=chat)
        self.assertEqual(session.state, ConversationSession.STATE_COMPLETED)
        self.assertIsNotNone(session.completed_at)
        self.assertIsNone(session.current_menu)

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_after_completion_restart_creates_new_session_history_preserved(self, mocked_send):
        chat = self._chat()
        BotMenuItem.objects.create(
            menu=self.root_menu, label='Selesai', trigger_value='9',
            action_type=BotMenuItem.ACTION_COMPLETE_SESSION,
        )
        handle_conversation_message(self.session, self._inbound(chat, 'Halo', 'm1'))
        handle_conversation_message(self.session, self._inbound(chat, '9', 'm2'))
        self.assertEqual(
            ConversationSession.objects.get(chat=chat).state, ConversationSession.STATE_COMPLETED,
        )

        handle_conversation_message(self.session, self._inbound(chat, 'Halo', 'm3'))

        self.assertEqual(ConversationSession.objects.filter(chat=chat).count(), 2)
        active = ConversationSession.objects.get(chat=chat, state__in=ConversationSession.ACTIVE_STATES)
        self.assertEqual(active.current_menu, self.root_menu)

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_office_selector_menu_reuses_available_operator_chat_offices(self, mocked_send):
        office_a = Office.objects.create(name='Samsat A')
        office_b = Office.objects.create(name='Samsat B')
        OfficeInboxConfig.objects.create(office=office_a, enabled=True)
        OfficeInboxConfig.objects.create(office=office_b, enabled=True)
        disabled_office = Office.objects.create(name='Samsat Disabled')
        OfficeInboxConfig.objects.create(office=disabled_office, enabled=False)

        selector_menu = BotMenu.objects.create(name='Pilih Office', is_office_selector=True)
        BotMenuItem.objects.create(
            menu=self.root_menu, label='Hubungi Petugas', trigger_value='4',
            action_type=BotMenuItem.ACTION_SHOW_MENU, target_menu=selector_menu,
        )
        chat = self._chat()
        handle_conversation_message(self.session, self._inbound(chat, 'Halo', 'm1'))
        mocked_send.reset_mock()

        handle_conversation_message(self.session, self._inbound(chat, '4', 'm2'))

        text = self._sent_text(mocked_send)
        self.assertIn('Samsat A', text)
        self.assertIn('Samsat B', text)
        self.assertNotIn('Samsat Disabled', text)

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_office_selection_syncs_session_office_and_chat_office(self, mocked_send):
        office_a = Office.objects.create(name='Samsat A')
        OfficeInboxConfig.objects.create(office=office_a, enabled=True)
        selector_menu = BotMenu.objects.create(name='Pilih Office', is_office_selector=True)
        BotMenuItem.objects.create(
            menu=self.root_menu, label='Hubungi Petugas', trigger_value='4',
            action_type=BotMenuItem.ACTION_SHOW_MENU, target_menu=selector_menu,
        )
        chat = self._chat()
        handle_conversation_message(self.session, self._inbound(chat, 'Halo', 'm1'))
        handle_conversation_message(self.session, self._inbound(chat, '4', 'm2'))

        handle_conversation_message(self.session, self._inbound(chat, str(office_a.pk), 'm3'))

        chat.refresh_from_db()
        self.assertEqual(chat.office, office_a)
        session = ConversationSession.objects.get(chat=chat, state=ConversationSession.STATE_WAITING_OPERATOR)
        self.assertEqual(session.office, office_a)
        self.assertIsNone(session.current_menu)

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_handoff_to_operator_action_sets_waiting_operator_state(self, mocked_send):
        chat = self._chat()
        BotMenuItem.objects.create(
            menu=self.root_menu, label='Bicara dengan petugas', trigger_value='5',
            action_type=BotMenuItem.ACTION_HANDOFF_TO_OPERATOR,
        )
        handle_conversation_message(self.session, self._inbound(chat, 'Halo', 'm1'))
        mocked_send.reset_mock()

        handle_conversation_message(self.session, self._inbound(chat, '5', 'm2'))

        session = ConversationSession.objects.get(chat=chat)
        self.assertEqual(session.state, ConversationSession.STATE_WAITING_OPERATOR)
        self.assertEqual(self._sent_text(mocked_send), HANDOFF_ACK_TEXT)

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_message_while_waiting_operator_is_not_reinjected_into_menu(self, mocked_send):
        chat = self._chat()
        ConversationSession.objects.create(
            chat=chat, state=ConversationSession.STATE_WAITING_OPERATOR, current_menu=None,
        )
        handle_conversation_message(self.session, self._inbound(chat, 'halo petugas'))
        mocked_send.assert_not_called()

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_disabled_menu_item_is_treated_as_unrecognized(self, mocked_send):
        chat = self._chat()
        BotMenuItem.objects.create(
            menu=self.root_menu, label='Nonaktif', trigger_value='7',
            action_type=BotMenuItem.ACTION_COMPLETE_SESSION, enabled=False,
        )
        handle_conversation_message(self.session, self._inbound(chat, 'Halo', 'm1'))
        mocked_send.reset_mock()

        handle_conversation_message(self.session, self._inbound(chat, '7', 'm2'))

        self.assertIn('Maaf, pilihan tidak dikenali.', self._sent_text(mocked_send))
        session = ConversationSession.objects.get(chat=chat)
        self.assertEqual(session.state, ConversationSession.STATE_ACTIVE)

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_group_chat_is_ignored_entirely(self, mocked_send):
        chat = self._chat(provider_chat_id='group1@g.us', is_group=True)
        handle_conversation_message(self.session, self._inbound(chat, 'Halo grup'))
        mocked_send.assert_not_called()
        self.assertFalse(ConversationSession.objects.exists())

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_blank_body_is_ignored_entirely(self, mocked_send):
        chat = self._chat()
        handle_conversation_message(self.session, self._inbound(chat, '   '))
        mocked_send.assert_not_called()
        self.assertFalse(ConversationSession.objects.exists())

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_office_specific_bot_config_overrides_global(self, mocked_send):
        office = Office.objects.create(name='Samsat Kasongan')
        office_menu = BotMenu.objects.create(office=office, name='Menu Kasongan', intro_text='Menu khusus Kasongan.')
        BotConfig.objects.create(office=office, enabled=True, root_menu=office_menu)
        chat = self._chat(office=office)

        handle_conversation_message(self.session, self._inbound(chat, 'Halo'))

        text = self._sent_text(mocked_send)
        self.assertIn('Menu khusus Kasongan.', text)

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_office_specific_bot_disabled_overrides_global_enabled(self, mocked_send):
        office = Office.objects.create(name='Samsat Sampit')
        BotConfig.objects.create(office=office, enabled=False)
        chat = self._chat(office=office)

        handle_conversation_message(self.session, self._inbound(chat, 'Halo'))

        mocked_send.assert_not_called()

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_duplicate_webhook_delivery_is_handled_once_by_message_uniqueness(self, mocked_send):
        chat = self._chat()
        message = self._inbound(chat, 'Halo', 'dup-1')
        handle_conversation_message(self.session, message)
        mocked_send.reset_mock()
        # Simulate the webhook layer calling the engine again for the
        # same already-processed Message row (it never does in practice —
        # ingest_webhook only calls this once per persist_message() —
        # but the engine itself has no re-entrancy guard of its own; this
        # documents that duplicate protection lives at the Message /
        # WebhookEvent layer, per correction #14, not here).
        handle_conversation_message(self.session, message)
        self.assertEqual(mocked_send.call_count, 1)

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_reconciliation_style_direct_call_is_never_made_reconciliation_never_imports_this(self, mocked_send):
        # Structural guarantee, not a runtime one: apps.sync.reconciliation
        # calls persist_message() directly and never imports
        # handle_conversation_message at all.
        import apps.sync.reconciliation as reconciliation_module
        source = reconciliation_module.__file__
        with open(source, encoding='utf-8') as fh:
            contents = fh.read()
        self.assertNotIn('conversation_engine', contents)
