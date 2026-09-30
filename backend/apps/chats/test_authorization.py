"""Blast Inbox-visibility fix — `chats_visible_to` now requires at least
one real inbound Message, in BOTH the globally-accessing branch and the
Office-scoped branch (Discussed requirement: a blast message must never
create a new, visible Inbox conversation for anyone)."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.chats.authorization import can_view_chat, chats_visible_to
from apps.chats.models import Chat, Message
from apps.offices.models import ROLE_GLOBAL_ADMIN, ROLE_OFFICE_ADMIN, Office, OfficeMembership, Role
from apps.waha_sessions.models import WahaSession


def _seeded_role(name):
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={'grants_global_access': name == ROLE_GLOBAL_ADMIN, 'is_office_admin': name == ROLE_OFFICE_ADMIN},
    )
    return role


class ChatsVisibleToInboundMessageRuleTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')
        self.office = Office.objects.create(name='Office A')
        self.office_admin = User.objects.create_user('admin_a', password='pw')
        OfficeMembership.objects.create(
            user=self.office_admin, office=self.office, role=_seeded_role(ROLE_OFFICE_ADMIN), requires_office=True,
        )
        self.superuser = User.objects.create_superuser('super', 'super@example.com', 'pw')

    def _outbound(self, chat, msg_id='out-1'):
        return Message.objects.create(
            session=self.session, chat=chat, provider_message_id=msg_id,
            direction=Message.DIRECTION_OUTBOUND, timestamp=timezone.now(),
        )

    def _inbound(self, chat, msg_id='in-1'):
        return Message.objects.create(
            session=self.session, chat=chat, provider_message_id=msg_id,
            direction=Message.DIRECTION_INBOUND, timestamp=timezone.now(),
        )

    def test_chat_with_zero_messages_is_invisible_to_office_admin(self):
        chat = Chat.objects.create(session=self.session, provider_chat_id='blast-only@lid', office=self.office)
        self.assertFalse(can_view_chat(self.office_admin, chat))
        self.assertNotIn(chat.pk, chats_visible_to(self.office_admin).values_list('pk', flat=True))

    def test_chat_with_zero_messages_is_invisible_to_a_globally_accessing_user(self):
        # The has_global_access branch previously returned every Chat
        # unfiltered — this is the regression the fix specifically closes.
        chat = Chat.objects.create(session=self.session, provider_chat_id='blast-only@lid', office=self.office)
        self.assertNotIn(chat.pk, chats_visible_to(self.superuser).values_list('pk', flat=True))

    def test_chat_with_only_an_outbound_message_is_still_invisible(self):
        # A blast send alone (a pure outbound message, no reply) must
        # never surface a new Inbox conversation.
        chat = Chat.objects.create(session=self.session, provider_chat_id='blast-sent@lid', office=self.office)
        self._outbound(chat)
        self.assertFalse(can_view_chat(self.office_admin, chat))
        self.assertNotIn(chat.pk, chats_visible_to(self.superuser).values_list('pk', flat=True))

    def test_chat_becomes_visible_the_moment_a_real_inbound_message_exists(self):
        chat = Chat.objects.create(session=self.session, provider_chat_id='replied@lid', office=self.office)
        self._outbound(chat, 'out-1')
        self.assertFalse(can_view_chat(self.office_admin, chat))

        self._inbound(chat, 'in-1')
        self.assertTrue(can_view_chat(self.office_admin, chat))
        self.assertIn(chat.pk, chats_visible_to(self.superuser).values_list('pk', flat=True))

    def test_office_scoped_user_still_never_sees_another_offices_chat(self):
        other_office = Office.objects.create(name='Office B')
        chat_b = Chat.objects.create(session=self.session, provider_chat_id='b@lid', office=other_office)
        self._inbound(chat_b)
        self.assertNotIn(chat_b.pk, chats_visible_to(self.office_admin).values_list('pk', flat=True))

    def test_history_office_match_via_message_office_does_not_require_that_same_message_to_be_inbound(self):
        # Regression guard for the Django "spanning multi-valued
        # relationships" pitfall: the office-match Message and the
        # inbound Message may be two DIFFERENT rows — chats_visible_to
        # must not silently require them to be the same one.
        other_office = Office.objects.create(name='Office B')
        chat = Chat.objects.create(session=self.session, provider_chat_id='moved@lid', office=other_office)
        # An outbound message tagged with THIS office's history (the Chat
        # has since moved to Office B, per Message.office's own docstring)…
        Message.objects.create(
            session=self.session, chat=chat, provider_message_id='office-tagged',
            direction=Message.DIRECTION_OUTBOUND, timestamp=timezone.now(), office=self.office,
        )
        # …and a SEPARATE, later, inbound message (from the new Office B
        # conversation) is what actually qualifies the chat for Inbox
        # visibility.
        self._inbound(chat, 'in-after-move')
        self.assertIn(chat.pk, chats_visible_to(self.office_admin).values_list('pk', flat=True))
