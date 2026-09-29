from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.chats.models import Chat, Message
from apps.chats.operator_chat import (
    CONFIRMATION_TEXT_TEMPLATE,
    INVALID_SELECTION_TEXT,
    NO_OFFICE_AVAILABLE_TEXT,
    OFFICE_NOT_FOUND,
    OFFICE_UNAVAILABLE,
    available_operator_chat_offices,
    handle_operator_chat_message,
    select_office_for_chat,
)
from apps.offices.models import Office, OfficeInboxConfig
from apps.waha_sessions.models import WahaSession

OFFICES_URL = '/internal/operator-chat/offices/'
SELECT_URL = '/internal/operator-chat/select-office/'
HEADERS = {'HTTP_X_INTERNAL_SERVICE_KEY': 'test-internal-service-key'}


class AvailableOperatorChatOfficesTests(TestCase):
    """Step 11 Section 4/13 — availability rule and ordering."""

    def test_active_and_enabled_office_appears(self):
        office = Office.objects.create(name='Samsat Palangka Raya')
        OfficeInboxConfig.objects.create(office=office, enabled=True)
        self.assertIn(office, available_operator_chat_offices())

    def test_active_but_disabled_office_does_not_appear(self):
        office = Office.objects.create(name='Samsat B')
        OfficeInboxConfig.objects.create(office=office, enabled=False)
        self.assertNotIn(office, available_operator_chat_offices())

    def test_inactive_but_enabled_office_does_not_appear(self):
        office = Office.objects.create(name='Samsat C', is_active=False)
        OfficeInboxConfig.objects.create(office=office, enabled=True)
        self.assertNotIn(office, available_operator_chat_offices())

    def test_inactive_and_disabled_office_does_not_appear(self):
        office = Office.objects.create(name='Samsat D', is_active=False)
        OfficeInboxConfig.objects.create(office=office, enabled=False)
        self.assertNotIn(office, available_operator_chat_offices())

    def test_active_office_with_no_config_at_all_does_not_appear(self):
        office = Office.objects.create(name='Samsat E')
        self.assertFalse(OfficeInboxConfig.objects.filter(office=office).exists())
        self.assertNotIn(office, available_operator_chat_offices())
        # Confirms the query never lazily creates one either.
        self.assertFalse(OfficeInboxConfig.objects.filter(office=office).exists())

    def test_results_are_ordered_by_name_ascending(self):
        palangka = Office.objects.create(name='Samsat Palangka Raya')
        sampit = Office.objects.create(name='Samsat Sampit')
        kasongan = Office.objects.create(name='Samsat Kasongan')
        for office in (palangka, sampit, kasongan):
            OfficeInboxConfig.objects.create(office=office, enabled=True)

        names = list(available_operator_chat_offices().values_list('name', flat=True))
        self.assertEqual(names, ['Samsat Kasongan', 'Samsat Palangka Raya', 'Samsat Sampit'])


class SelectOfficeForChatTests(TestCase):
    """Step 11 Section 3/7/8 — validated selection, never trusting the
    client, always re-checking the database at call time."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='no_epahari')

    def test_valid_office_is_assigned_to_the_chat(self):
        office = Office.objects.create(name='Office A')
        OfficeInboxConfig.objects.create(office=office, enabled=True)

        chat, error = select_office_for_chat(self.session, 'wp1@lid', office.pk)

        self.assertIsNone(error)
        self.assertEqual(chat.office, office)

    def test_selecting_an_office_clears_any_previous_assignment(self):
        # Regression: found live — a new handoff round left the PREVIOUS
        # round's assignee in place, hiding the Chat from
        # apps.dashboard.views.PendingChatsView's assigned_to__isnull=True
        # queue entirely, so nobody at the newly-selected Office was ever
        # notified.
        from django.contrib.auth.models import User

        from apps.chats.models import Chat

        office = Office.objects.create(name='Office C')
        OfficeInboxConfig.objects.create(office=office, enabled=True)
        previous_assignee = User.objects.create_user('previous_operator', password='pw')
        chat = Chat.objects.create(session=self.session, provider_chat_id='wp3@lid', assigned_to=previous_assignee)

        updated_chat, error = select_office_for_chat(self.session, 'wp3@lid', office.pk)

        self.assertIsNone(error)
        self.assertIsNone(updated_chat.assigned_to)
        chat.refresh_from_db()
        self.assertIsNone(chat.assigned_to)

    def test_disabled_office_is_rejected(self):
        office = Office.objects.create(name='Office B')
        OfficeInboxConfig.objects.create(office=office, enabled=False)

        chat, error = select_office_for_chat(self.session, 'wp2@lid', office.pk)

        self.assertIsNone(chat)
        self.assertEqual(error, OFFICE_UNAVAILABLE)

    def test_inactive_office_is_rejected(self):
        office = Office.objects.create(name='Office C', is_active=False)
        OfficeInboxConfig.objects.create(office=office, enabled=True)

        chat, error = select_office_for_chat(self.session, 'wp3@lid', office.pk)

        self.assertIsNone(chat)
        self.assertEqual(error, OFFICE_UNAVAILABLE)

    def test_nonexistent_office_id_is_rejected(self):
        chat, error = select_office_for_chat(self.session, 'wp4@lid', 999999)
        self.assertIsNone(chat)
        self.assertEqual(error, OFFICE_NOT_FOUND)

    def test_office_disabled_after_menu_was_built_is_rejected(self):
        # The race condition from Section 8: available when the menu was
        # sent, disabled before the WP actually chose it.
        office = Office.objects.create(name='Office Race')
        config = OfficeInboxConfig.objects.create(office=office, enabled=True)
        self.assertIn(office, available_operator_chat_offices())  # was available

        config.enabled = False
        config.save(update_fields=['enabled'])

        chat, error = select_office_for_chat(self.session, 'wp-race@lid', office.pk)
        self.assertIsNone(chat)
        self.assertEqual(error, OFFICE_UNAVAILABLE)

    def test_selection_never_touches_waha_session_office(self):
        office = Office.objects.create(name='Office D')
        OfficeInboxConfig.objects.create(office=office, enabled=True)
        self.assertIsNone(self.session.office)

        select_office_for_chat(self.session, 'wp5@lid', office.pk)

        self.session.refresh_from_db()
        self.assertIsNone(self.session.office)

    def test_selection_does_not_affect_other_offices_or_chats(self):
        office_a = Office.objects.create(name='Office A2')
        office_b = Office.objects.create(name='Office B2')
        OfficeInboxConfig.objects.create(office=office_a, enabled=True)
        OfficeInboxConfig.objects.create(office=office_b, enabled=True)
        other_chat = Chat.objects.create(session=self.session, provider_chat_id='other@lid', office=office_b)

        select_office_for_chat(self.session, 'wp6@lid', office_a.pk)

        other_chat.refresh_from_db()
        self.assertEqual(other_chat.office, office_b)  # untouched


@override_settings(INTERNAL_SERVICE_KEY='test-internal-service-key')
class OperatorChatOfficesViewTests(APITestCase):
    def test_requires_internal_service_key(self):
        response = self.client.get(OFFICES_URL)
        self.assertEqual(response.status_code, 403)

    def test_returns_only_available_offices_id_and_name(self):
        office = Office.objects.create(name='Samsat Palangka Raya')
        OfficeInboxConfig.objects.create(office=office, enabled=True)
        disabled = Office.objects.create(name='Samsat Disabled')
        OfficeInboxConfig.objects.create(office=disabled, enabled=False)

        response = self.client.get(OFFICES_URL, **HEADERS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [{'id': office.pk, 'name': office.name}])


@override_settings(INTERNAL_SERVICE_KEY='test-internal-service-key')
class OperatorChatSelectOfficeViewTests(APITestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='no_epahari')
        self.office = Office.objects.create(name='Samsat Palangka Raya')
        OfficeInboxConfig.objects.create(office=self.office, enabled=True)

    def test_requires_internal_service_key(self):
        response = self.client.post(
            SELECT_URL, {'session': 'no_epahari', 'chat_provider_id': 'wp1@lid', 'office_id': self.office.pk}
        )
        self.assertEqual(response.status_code, 403)

    def test_valid_selection_routes_the_chat(self):
        response = self.client.post(
            SELECT_URL,
            {'session': 'no_epahari', 'chat_provider_id': 'wp1@lid', 'office_id': self.office.pk},
            **HEADERS,
        )
        self.assertEqual(response.status_code, 200)
        chat = Chat.objects.get(session=self.session, provider_chat_id='wp1@lid')
        self.assertEqual(chat.office, self.office)

    def test_disabled_office_is_rejected_with_409(self):
        disabled = Office.objects.create(name='Disabled Office')
        OfficeInboxConfig.objects.create(office=disabled, enabled=False)
        response = self.client.post(
            SELECT_URL,
            {'session': 'no_epahari', 'chat_provider_id': 'wp2@lid', 'office_id': disabled.pk},
            **HEADERS,
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Chat.objects.filter(provider_chat_id='wp2@lid').exists())

    def test_nonexistent_office_is_rejected_with_404(self):
        response = self.client.post(
            SELECT_URL,
            {'session': 'no_epahari', 'chat_provider_id': 'wp3@lid', 'office_id': 999999},
            **HEADERS,
        )
        self.assertEqual(response.status_code, 404)

    def test_unknown_session_returns_404(self):
        response = self.client.post(
            SELECT_URL,
            {'session': 'does-not-exist', 'chat_provider_id': 'wp4@lid', 'office_id': self.office.pk},
            **HEADERS,
        )
        self.assertEqual(response.status_code, 404)

    def test_missing_fields_are_a_bad_request(self):
        response = self.client.post(SELECT_URL, {'session': 'no_epahari'}, **HEADERS)
        self.assertEqual(response.status_code, 400)


class HandleOperatorChatMessageTests(TestCase):
    """Step 12 — plain-text WhatsApp Office-selection flow. `send_blast_message`
    is always mocked (same discipline as `apps.blast`'s own dispatch
    tests) — never a real network call, matching Section "test wajib":
    no test may depend on WhatsApp production."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='no_epahari')
        self.office_a = Office.objects.create(name='Office A')
        self.office_b = Office.objects.create(name='Office B')
        OfficeInboxConfig.objects.create(office=self.office_a, enabled=True)
        OfficeInboxConfig.objects.create(office=self.office_b, enabled=True)

    def _inbound(self, chat, body, provider_message_id='m1'):
        return Message.objects.create(
            session=self.session, chat=chat, provider_message_id=provider_message_id,
            direction=Message.DIRECTION_INBOUND, message_type='text', body=body, timestamp=timezone.now(),
        )

    def _sent_text(self, mocked_send):
        return mocked_send.call_args[0][2]

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_new_chat_without_office_triggers_menu(self, mocked_send):
        chat = Chat.objects.create(session=self.session, provider_chat_id='wp1@lid')
        handle_operator_chat_message(self.session, self._inbound(chat, 'Halo'))
        mocked_send.assert_called_once()
        text = self._sent_text(mocked_send)
        self.assertIn('Office A', text)
        self.assertIn('Office B', text)

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_menu_only_lists_active_and_enabled_offices(self, mocked_send):
        disabled = Office.objects.create(name='Office C')
        OfficeInboxConfig.objects.create(office=disabled, enabled=False)
        chat = Chat.objects.create(session=self.session, provider_chat_id='wp2@lid')
        handle_operator_chat_message(self.session, self._inbound(chat, 'Halo'))
        self.assertNotIn('Office C', self._sent_text(mocked_send))

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_chat_with_office_does_not_trigger_menu(self, mocked_send):
        chat = Chat.objects.create(session=self.session, provider_chat_id='wp3@lid', office=self.office_a)
        handle_operator_chat_message(self.session, self._inbound(chat, 'Halo lagi'))
        mocked_send.assert_not_called()

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_valid_selection_sets_office(self, mocked_send):
        chat = Chat.objects.create(session=self.session, provider_chat_id='wp4@lid')
        handle_operator_chat_message(self.session, self._inbound(chat, str(self.office_a.pk)))
        chat.refresh_from_db()
        self.assertEqual(chat.office, self.office_a)

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_selection_of_nonexistent_office_is_rejected(self, mocked_send):
        chat = Chat.objects.create(session=self.session, provider_chat_id='wp5@lid')
        handle_operator_chat_message(self.session, self._inbound(chat, '999999'))
        chat.refresh_from_db()
        self.assertIsNone(chat.office)
        self.assertEqual(self._sent_text(mocked_send), INVALID_SELECTION_TEXT)

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_office_disabled_after_menu_built_rejects_selection(self, mocked_send):
        chat = Chat.objects.create(session=self.session, provider_chat_id='wp6@lid')
        config = self.office_a.inbox_config
        config.enabled = False
        config.save(update_fields=['enabled'])
        handle_operator_chat_message(self.session, self._inbound(chat, str(self.office_a.pk)))
        chat.refresh_from_db()
        self.assertIsNone(chat.office)
        self.assertEqual(self._sent_text(mocked_send), INVALID_SELECTION_TEXT)

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_invalid_text_reply_leaves_office_null(self, mocked_send):
        chat = Chat.objects.create(session=self.session, provider_chat_id='wp7@lid')
        handle_operator_chat_message(self.session, self._inbound(chat, 'entahlah'))
        chat.refresh_from_db()
        self.assertIsNone(chat.office)

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_confirmation_sent_after_successful_selection(self, mocked_send):
        chat = Chat.objects.create(session=self.session, provider_chat_id='wp8@lid')
        handle_operator_chat_message(self.session, self._inbound(chat, str(self.office_a.pk)))
        self.assertEqual(
            self._sent_text(mocked_send), CONFIRMATION_TEXT_TEMPLATE.format(office_name=self.office_a.name)
        )

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_next_message_after_selection_does_not_trigger_menu_again(self, mocked_send):
        chat = Chat.objects.create(session=self.session, provider_chat_id='wp9@lid')
        handle_operator_chat_message(self.session, self._inbound(chat, str(self.office_a.pk), 'm1'))
        mocked_send.reset_mock()
        chat.refresh_from_db()
        handle_operator_chat_message(self.session, self._inbound(chat, 'Terima kasih', 'm2'))
        mocked_send.assert_not_called()

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_waha_session_office_is_never_changed_by_a_selection(self, mocked_send):
        self.session.office = self.office_b
        self.session.save(update_fields=['office'])
        chat = Chat.objects.create(session=self.session, provider_chat_id='wp10@lid')
        handle_operator_chat_message(self.session, self._inbound(chat, str(self.office_a.pk)))
        self.session.refresh_from_db()
        self.assertEqual(self.session.office, self.office_b)

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_a_chat_that_already_has_an_office_is_never_moved_by_a_later_numeric_reply(self, mocked_send):
        chat = Chat.objects.create(session=self.session, provider_chat_id='wp11@lid', office=self.office_a)
        handle_operator_chat_message(self.session, self._inbound(chat, str(self.office_b.pk)))
        chat.refresh_from_db()
        self.assertEqual(chat.office, self.office_a)
        mocked_send.assert_not_called()

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_no_office_available_sends_safe_message_and_creates_no_office(self, mocked_send):
        OfficeInboxConfig.objects.filter(office__in=[self.office_a, self.office_b]).update(enabled=False)
        chat = Chat.objects.create(session=self.session, provider_chat_id='wp12@lid')
        handle_operator_chat_message(self.session, self._inbound(chat, 'Halo'))
        chat.refresh_from_db()
        self.assertIsNone(chat.office)
        self.assertEqual(self._sent_text(mocked_send), NO_OFFICE_AVAILABLE_TEXT)
        self.assertEqual(Office.objects.count(), 2)

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_office_a_and_office_b_chats_remain_isolated(self, mocked_send):
        chat_a = Chat.objects.create(session=self.session, provider_chat_id='wpA@lid', office=self.office_a)
        chat_b = Chat.objects.create(session=self.session, provider_chat_id='wpB@lid')
        handle_operator_chat_message(self.session, self._inbound(chat_b, str(self.office_b.pk), 'mB'))
        chat_a.refresh_from_db()
        chat_b.refresh_from_db()
        self.assertEqual(chat_a.office, self.office_a)
        self.assertEqual(chat_b.office, self.office_b)

    @mock.patch('apps.chats.operator_chat.send_blast_message')
    def test_group_chat_is_ignored_entirely(self, mocked_send):
        chat = Chat.objects.create(session=self.session, provider_chat_id='group1@g.us', is_group=True)
        handle_operator_chat_message(self.session, self._inbound(chat, 'Halo grup'))
        mocked_send.assert_not_called()
        chat.refresh_from_db()
        self.assertIsNone(chat.office)
