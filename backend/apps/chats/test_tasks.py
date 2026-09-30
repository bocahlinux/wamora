from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.blast.bff_client import BffDispatchError
from apps.bot.models import BotConfig, BotMenu
from apps.chats.models import Chat, ConversationSession
from apps.chats.tasks import (
    expire_waiting_operator_sessions_task,
    finish_bot_list_reply_task,
    finish_bot_text_reply_task,
    send_bot_list_reply_task,
    send_bot_text_reply_task,
)
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


# Discussed requirement — human-like reply delay (`BotConfig.reply_delay_seconds`).
# `.apply(args=[...])` runs a `@shared_task`-decorated function
# synchronously, no broker required — same convention
# `apps.blast.tests.test_tasks` already established for this project's
# Celery tasks.

class SendBotTextReplyTaskTests(TestCase):
    @mock.patch('apps.chats.tasks.finish_bot_text_reply_task.apply_async')
    @mock.patch('apps.chats.tasks.start_typing')
    def test_starts_typing_and_schedules_finish_after_the_delay(self, mocked_start, mocked_apply_async):
        send_bot_text_reply_task.apply(args=['no_epahari', 'wp1@lid', 'key-1', 'Halo', 7])

        mocked_start.assert_called_once_with('no_epahari', 'wp1@lid')
        mocked_apply_async.assert_called_once_with(
            args=['no_epahari', 'wp1@lid', 'key-1', 'Halo'], countdown=7,
        )

    @mock.patch('apps.chats.tasks.finish_bot_text_reply_task.apply_async')
    @mock.patch('apps.chats.tasks.start_typing', side_effect=BffDispatchError('boom'))
    def test_a_failed_typing_indicator_never_blocks_scheduling_the_real_send(self, mocked_start, mocked_apply_async):
        send_bot_text_reply_task.apply(args=['no_epahari', 'wp1@lid', 'key-1', 'Halo', 7])
        mocked_apply_async.assert_called_once()


class FinishBotTextReplyTaskTests(TestCase):
    @mock.patch('apps.chats.tasks.send_blast_message')
    @mock.patch('apps.chats.tasks.stop_typing')
    def test_stops_typing_then_sends_the_real_message(self, mocked_stop, mocked_send):
        finish_bot_text_reply_task.apply(args=['no_epahari', 'wp1@lid', 'key-1', 'Halo'])

        mocked_stop.assert_called_once_with('no_epahari', 'wp1@lid')
        mocked_send.assert_called_once_with('no_epahari', 'wp1@lid', 'Halo', 'key-1')

    @mock.patch('apps.chats.tasks.send_blast_message', side_effect=BffDispatchError('boom'))
    @mock.patch('apps.chats.tasks.stop_typing')
    def test_a_failed_send_never_raises(self, mocked_stop, mocked_send):
        finish_bot_text_reply_task.apply(args=['no_epahari', 'wp1@lid', 'key-1', 'Halo'])  # must not raise

    @mock.patch('apps.chats.tasks.send_blast_message')
    @mock.patch('apps.chats.tasks.stop_typing', side_effect=BffDispatchError('boom'))
    def test_a_failed_stop_typing_never_blocks_the_real_send(self, mocked_stop, mocked_send):
        finish_bot_text_reply_task.apply(args=['no_epahari', 'wp1@lid', 'key-1', 'Halo'])
        mocked_send.assert_called_once()


class SendBotListReplyTaskTests(TestCase):
    @mock.patch('apps.chats.tasks.finish_bot_list_reply_task.apply_async')
    @mock.patch('apps.chats.tasks.start_typing')
    def test_starts_typing_and_schedules_finish_after_the_delay(self, mocked_start, mocked_apply_async):
        payload = {'title': 'Menu Utama'}
        send_bot_list_reply_task.apply(args=['no_epahari', 'wp1@lid', 'key-1', payload, 'fallback text', 10])

        mocked_start.assert_called_once_with('no_epahari', 'wp1@lid')
        mocked_apply_async.assert_called_once_with(
            args=['no_epahari', 'wp1@lid', 'key-1', payload, 'fallback text'], countdown=10,
        )


class FinishBotListReplyTaskTests(TestCase):
    @mock.patch('apps.chats.tasks.send_list_message', return_value={'status': 'sent', 'provider_message_id': None})
    @mock.patch('apps.chats.tasks.stop_typing')
    def test_stops_typing_then_sends_the_list(self, mocked_stop, mocked_send_list):
        payload = {'title': 'Menu Utama'}
        finish_bot_list_reply_task.apply(args=['no_epahari', 'wp1@lid', 'key-1', payload, 'fallback text'])

        mocked_stop.assert_called_once_with('no_epahari', 'wp1@lid')
        mocked_send_list.assert_called_once_with('no_epahari', 'wp1@lid', payload, 'key-1')

    @mock.patch('apps.chats.tasks.send_blast_message')
    @mock.patch('apps.chats.tasks.send_list_message', side_effect=BffDispatchError('boom'))
    @mock.patch('apps.chats.tasks.stop_typing')
    def test_sendlist_failure_falls_back_to_plain_text(self, mocked_stop, mocked_send_list, mocked_send_text):
        payload = {'title': 'Menu Utama'}
        finish_bot_list_reply_task.apply(args=['no_epahari', 'wp1@lid', 'key-1', payload, 'fallback text'])

        mocked_send_text.assert_called_once_with('no_epahari', 'wp1@lid', 'fallback text', 'key-1-list-fallback')

    @mock.patch('apps.chats.tasks.send_blast_message')
    @mock.patch('apps.chats.tasks.send_list_message', return_value={'status': 'failed', 'provider_message_id': None})
    @mock.patch('apps.chats.tasks.stop_typing')
    def test_sendlist_reporting_failed_falls_back_to_plain_text(self, mocked_stop, mocked_send_list, mocked_send_text):
        payload = {'title': 'Menu Utama'}
        finish_bot_list_reply_task.apply(args=['no_epahari', 'wp1@lid', 'key-1', payload, 'fallback text'])

        mocked_send_text.assert_called_once_with('no_epahari', 'wp1@lid', 'fallback text', 'key-1-list-fallback')
