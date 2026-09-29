from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.bot.models import BotConfig, BotMenu
from apps.chats.models import Chat, ConversationSession
from apps.chats.tasks import expire_waiting_operator_sessions_task
from apps.waha_sessions.models import WahaSession


@override_settings(CONVERSATION_WAITING_OPERATOR_TIMEOUT_SECONDS=86400)
class ExpireWaitingOperatorSessionsTaskTests(TestCase):
    def setUp(self):
        self.waha_session = WahaSession.objects.create(name='no_epahari')
        root_menu = BotMenu.objects.create(name='Main Menu')
        BotConfig.objects.create(
            office=None, enabled=True, session_completed_message='Sesi berakhir.', root_menu=root_menu,
        )
        self.chat = Chat.objects.create(
            session=self.waha_session, provider_chat_id='wp1@lid', last_message_at=timezone.now(),
        )

    def _waiting_session(self, age, chat=None):
        chat = chat or self.chat
        session = ConversationSession.objects.create(
            chat=chat, state=ConversationSession.STATE_WAITING_OPERATOR, current_menu=None,
        )
        # The timeout is measured from the Chat's last activity (either
        # side), not the session's own updated_at — backdate
        # last_message_at directly to simulate a citizen/operator who
        # genuinely hasn't said anything in `age`.
        Chat.objects.filter(pk=chat.pk).update(last_message_at=timezone.now() - age)
        return session

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_session_older_than_timeout_is_expired(self, mocked_send):
        session = self._waiting_session(timedelta(hours=25))

        expired_count = expire_waiting_operator_sessions_task()

        self.assertEqual(expired_count, 1)
        session.refresh_from_db()
        self.assertEqual(session.state, ConversationSession.STATE_COMPLETED)
        mocked_send.assert_called_once()

    @mock.patch('apps.chats.conversation_engine.send_blast_message')
    def test_session_within_timeout_is_left_untouched(self, mocked_send):
        session = self._waiting_session(timedelta(hours=1))

        expired_count = expire_waiting_operator_sessions_task()

        self.assertEqual(expired_count, 0)
        session.refresh_from_db()
        self.assertEqual(session.state, ConversationSession.STATE_WAITING_OPERATOR)
        mocked_send.assert_not_called()

    @mock.patch('apps.chats.tasks.expire_waiting_operator_session')
    def test_one_failure_does_not_block_the_others(self, mocked_expire):
        other_chat = Chat.objects.create(session=self.waha_session, provider_chat_id='wp2@lid')
        self._waiting_session(timedelta(hours=25))
        self._waiting_session(timedelta(hours=25), chat=other_chat)
        mocked_expire.side_effect = [Exception('boom'), None]

        expired_count = expire_waiting_operator_sessions_task()

        self.assertEqual(expired_count, 1)
        self.assertEqual(mocked_expire.call_count, 2)
