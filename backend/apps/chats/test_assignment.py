from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.chats.assignment import (
    NOT_AVAILABLE,
    NOT_OFFICE_MEMBER,
    NOT_OPERATOR_ROLE,
    USER_INACTIVE,
    USER_NOT_FOUND,
    assign_chat_to_operator,
    unassign_chat,
    valid_assignment_candidates,
)
from apps.chats.authorization import chats_visible_to
from apps.chats.models import Chat, Message
from apps.offices.models import ROLE_GLOBAL_ADMIN, ROLE_OFFICE_ADMIN, ROLE_OPERATOR, Office, OfficeMembership, Role
from apps.waha_sessions.models import WahaSession

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()

# The Role merge — resolves the old CharField's three fixed string
# values to the migration-0009-seeded Role rows with the matching
# organizational flags, so `_user()` below keeps accepting the same
# ROLE_GLOBAL_ADMIN/ROLE_OFFICE_ADMIN/ROLE_OPERATOR constants every
# existing test call site already passes it.
def _seeded_role(name):
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={
            'grants_global_access': name == ROLE_GLOBAL_ADMIN,
            'is_office_admin': name == ROLE_OFFICE_ADMIN,
            'is_operator': name == ROLE_OPERATOR,
        },
    )
    return role


class AssignmentTestBase:
    def setUp(self):
        self.session = WahaSession.objects.create(name='no_epahari')
        self.office_a = Office.objects.create(name='Office A')
        self.office_b = Office.objects.create(name='Office B')
        self.chat_a = Chat.objects.create(session=self.session, provider_chat_id='wp-a@lid', office=self.office_a)
        self.chat_b = Chat.objects.create(session=self.session, provider_chat_id='wp-b@lid', office=self.office_b)
        # Inbox-visibility rule (chats_visible_to): a Chat is only visible
        # once it has a real inbound Message — every assignment scenario
        # here models an already-ongoing conversation, so both fixtures
        # get one, exactly like a real citizen-initiated chat would.
        for chat in (self.chat_a, self.chat_b):
            Message.objects.create(
                session=self.session, chat=chat, provider_message_id=f'{chat.provider_chat_id}-msg-1',
                direction=Message.DIRECTION_INBOUND, timestamp=timezone.now(),
            )

    def _user(self, username, office=None, role=None, is_available=False, is_active=True, superuser=False):
        if superuser:
            user = User.objects.create_superuser(username, f'{username}@example.com', 'pw')
        else:
            user = User.objects.create_user(username, password='pw')
            if not is_active:
                user.is_active = False
                user.save(update_fields=['is_active'])
        if role is not None:
            role_obj = _seeded_role(role)
            OfficeMembership.objects.create(
                user=user, office=office, role=role_obj, is_available=is_available,
                requires_office=not role_obj.grants_global_access,
            )
        return user


# --- pure function-level tests ------------------------------------------

class ValidAssignmentCandidatesTests(AssignmentTestBase, TestCase):
    def test_available_operator_in_office_is_a_candidate(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        self.assertIn(operator_a, valid_assignment_candidates(self.office_a))

    def test_operator_in_a_different_office_is_not_a_candidate(self):
        operator_b = self._user('operator_b', office=self.office_b, role=ROLE_OPERATOR, is_available=True)
        self.assertNotIn(operator_b, valid_assignment_candidates(self.office_a))

    def test_unavailable_operator_is_not_a_candidate(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=False)
        self.assertNotIn(operator_a, valid_assignment_candidates(self.office_a))

    def test_inactive_user_is_not_a_candidate(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True, is_active=False)
        self.assertNotIn(operator_a, valid_assignment_candidates(self.office_a))

    def test_office_admin_role_is_not_a_candidate(self):
        # Step 14's own deliberate scope: only role=operator rows are
        # assignment TARGETS, never office_admin/global_admin.
        admin_a = self._user('admin_a', office=self.office_a, role=ROLE_OFFICE_ADMIN, is_available=True)
        self.assertNotIn(admin_a, valid_assignment_candidates(self.office_a))

    def test_none_office_returns_no_candidates(self):
        self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        self.assertEqual(valid_assignment_candidates(None).count(), 0)


class AssignChatToOperatorTests(AssignmentTestBase, TestCase):
    def test_valid_assignment_succeeds(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        chat, error = assign_chat_to_operator(self.chat_a, operator_a.pk)
        self.assertIsNone(error)
        self.assertEqual(chat.assigned_to, operator_a)

    def test_nonexistent_user_is_rejected(self):
        chat, error = assign_chat_to_operator(self.chat_a, 999999)
        self.assertIsNone(chat)
        self.assertEqual(error, USER_NOT_FOUND)

    def test_inactive_user_is_rejected(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True, is_active=False)
        chat, error = assign_chat_to_operator(self.chat_a, operator_a.pk)
        self.assertIsNone(chat)
        self.assertEqual(error, USER_INACTIVE)

    def test_user_from_another_office_is_rejected(self):
        operator_b = self._user('operator_b', office=self.office_b, role=ROLE_OPERATOR, is_available=True)
        chat, error = assign_chat_to_operator(self.chat_a, operator_b.pk)
        self.assertIsNone(chat)
        self.assertEqual(error, NOT_OFFICE_MEMBER)

    def test_user_with_no_membership_is_rejected(self):
        plain_user = self._user('plain_user')
        chat, error = assign_chat_to_operator(self.chat_a, plain_user.pk)
        self.assertIsNone(chat)
        self.assertEqual(error, NOT_OFFICE_MEMBER)

    def test_global_admin_role_user_is_rejected_as_a_target(self):
        # role=global_admin always has office=None, which can never equal
        # a real chat.office_id.
        global_admin = self._user('gadmin', office=None, role=ROLE_GLOBAL_ADMIN, is_available=True)
        chat, error = assign_chat_to_operator(self.chat_a, global_admin.pk)
        self.assertIsNone(chat)
        self.assertEqual(error, NOT_OFFICE_MEMBER)

    def test_office_admin_role_is_rejected_as_a_target(self):
        admin_a = self._user('admin_a', office=self.office_a, role=ROLE_OFFICE_ADMIN, is_available=True)
        chat, error = assign_chat_to_operator(self.chat_a, admin_a.pk)
        self.assertIsNone(chat)
        self.assertEqual(error, NOT_OPERATOR_ROLE)

    def test_unavailable_operator_is_rejected(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=False)
        chat, error = assign_chat_to_operator(self.chat_a, operator_a.pk)
        self.assertIsNone(chat)
        self.assertEqual(error, NOT_AVAILABLE)

    def test_assignment_does_not_change_chat_office(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        chat, _ = assign_chat_to_operator(self.chat_a, operator_a.pk)
        self.assertEqual(chat.office, self.office_a)

    def test_reassignment_overwrites_previous_operator(self):
        operator_a1 = self._user('operator_a1', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        operator_a2 = self._user('operator_a2', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        assign_chat_to_operator(self.chat_a, operator_a1.pk)
        chat, error = assign_chat_to_operator(self.chat_a, operator_a2.pk)
        self.assertIsNone(error)
        self.assertEqual(chat.assigned_to, operator_a2)

    def test_two_sequential_assignments_leave_a_consistent_final_state(self):
        # Concurrency (Section 16): a plain single-row UPDATE is atomic;
        # simulates two near-simultaneous calls by running them
        # back-to-back and checking the final state is exactly one of the
        # two targets, never a corrupted/mixed value.
        operator_a1 = self._user('operator_a1', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        operator_a2 = self._user('operator_a2', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        assign_chat_to_operator(self.chat_a, operator_a1.pk)
        chat, _ = assign_chat_to_operator(self.chat_a, operator_a2.pk)
        self.chat_a.refresh_from_db()
        self.assertEqual(self.chat_a.assigned_to_id, operator_a2.pk)
        self.assertIn(self.chat_a.assigned_to_id, {operator_a1.pk, operator_a2.pk})


class UnassignChatTests(AssignmentTestBase, TestCase):
    def test_unassign_clears_assigned_to(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        assign_chat_to_operator(self.chat_a, operator_a.pk)
        chat = unassign_chat(self.chat_a)
        self.assertIsNone(chat.assigned_to)

    def test_unassign_does_not_change_chat_office(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        assign_chat_to_operator(self.chat_a, operator_a.pk)
        chat = unassign_chat(self.chat_a)
        self.assertEqual(chat.office, self.office_a)

    def test_unassignment_does_not_remove_chat_from_office_visibility(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        office_admin_a = self._user('admin_a', office=self.office_a, role=ROLE_OFFICE_ADMIN)
        assign_chat_to_operator(self.chat_a, operator_a.pk)
        unassign_chat(self.chat_a)
        self.assertIn(self.chat_a.pk, chats_visible_to(office_admin_a).values_list('pk', flat=True))


class AssignmentDoesNotGrantCrossOfficeAccessTests(AssignmentTestBase, TestCase):
    def test_assigned_operator_still_only_sees_own_office_chats(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        assign_chat_to_operator(self.chat_a, operator_a.pk)
        visible = set(chats_visible_to(operator_a).values_list('pk', flat=True))
        self.assertIn(self.chat_a.pk, visible)
        self.assertNotIn(self.chat_b.pk, visible)  # Office B's Chat, never assigned to operator_a


# --- API-level tests -------------------------------------------------------

@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM, JWT_PUBLIC_KEY=PUBLIC_PEM, JWT_ISSUER='test-issuer', JWT_AUDIENCE='test-audience',
)
class AssignmentApiTestCase(AssignmentTestBase, APITestCase):
    def _auth_header(self, user):
        token = issue_access_token(user)['access_token']
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}


class ChatOperatorsViewTests(AssignmentApiTestCase):
    def _url(self, chat):
        return f'/api/chats/{chat.pk}/operators/'

    def test_returns_only_valid_candidates(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        self._user('operator_a_unavailable', office=self.office_a, role=ROLE_OPERATOR, is_available=False)
        self._user('operator_b', office=self.office_b, role=ROLE_OPERATOR, is_available=True)
        actor = self._user('admin_a', office=self.office_a, role=ROLE_OFFICE_ADMIN)
        response = self.client.get(self._url(self.chat_a), **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)
        usernames = {row['username'] for row in response.data}
        self.assertEqual(usernames, {'operator_a'})
        self.assertIn('is_available', response.data[0])

    def test_operator_cannot_list_candidates(self):
        actor = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        response = self.client.get(self._url(self.chat_a), **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_office_admin_b_cannot_list_candidates_for_chat_a(self):
        actor = self._user('admin_b', office=self.office_b, role=ROLE_OFFICE_ADMIN)
        response = self.client.get(self._url(self.chat_a), **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)


class ChatAssignViewTests(AssignmentApiTestCase):
    def _url(self, chat):
        return f'/api/chats/{chat.pk}/assign/'

    def test_office_admin_a_can_assign_chat_a_to_operator_a(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        actor = self._user('admin_a', office=self.office_a, role=ROLE_OFFICE_ADMIN)
        response = self.client.post(self._url(self.chat_a), {'user_id': operator_a.pk}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)
        self.chat_a.refresh_from_db()
        self.assertEqual(self.chat_a.assigned_to, operator_a)

    def test_office_admin_a_cannot_assign_chat_a_to_operator_b(self):
        operator_b = self._user('operator_b', office=self.office_b, role=ROLE_OPERATOR, is_available=True)
        actor = self._user('admin_a', office=self.office_a, role=ROLE_OFFICE_ADMIN)
        response = self.client.post(self._url(self.chat_a), {'user_id': operator_b.pk}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 400)
        self.chat_a.refresh_from_db()
        self.assertIsNone(self.chat_a.assigned_to)

    def test_office_admin_b_cannot_assign_chat_a_at_all(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        actor = self._user('admin_b', office=self.office_b, role=ROLE_OFFICE_ADMIN)
        response = self.client.post(self._url(self.chat_a), {'user_id': operator_a.pk}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_global_admin_can_assign_within_scope(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        actor = self._user('gadmin', office=None, role=ROLE_GLOBAL_ADMIN)
        response = self.client.post(self._url(self.chat_a), {'user_id': operator_a.pk}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)

    def test_superadmin_can_assign(self):
        operator_b = self._user('operator_b', office=self.office_b, role=ROLE_OPERATOR, is_available=True)
        actor = self._user('super', superuser=True)
        response = self.client.post(self._url(self.chat_b), {'user_id': operator_b.pk}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)

    def test_operator_cannot_perform_assignment(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        actor = self._user('operator_a2', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        response = self.client.post(self._url(self.chat_a), {'user_id': operator_a.pk}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_assign_writes_an_audit_log_entry(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        actor = self._user('admin_a', office=self.office_a, role=ROLE_OFFICE_ADMIN)
        self.client.post(self._url(self.chat_a), {'user_id': operator_a.pk}, format='json', **self._auth_header(actor))
        self.assertTrue(AuditLog.objects.filter(action='chat.assign').exists())

    def test_assignment_does_not_change_chat_office(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        actor = self._user('admin_a', office=self.office_a, role=ROLE_OFFICE_ADMIN)
        self.client.post(self._url(self.chat_a), {'user_id': operator_a.pk}, format='json', **self._auth_header(actor))
        self.chat_a.refresh_from_db()
        self.assertEqual(self.chat_a.office, self.office_a)


class ChatUnassignViewTests(AssignmentApiTestCase):
    def _url(self, chat):
        return f'/api/chats/{chat.pk}/unassign/'

    def test_office_admin_a_can_unassign_chat_a(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        actor = self._user('admin_a', office=self.office_a, role=ROLE_OFFICE_ADMIN)
        assign_chat_to_operator(self.chat_a, operator_a.pk)
        response = self.client.post(self._url(self.chat_a), **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)
        self.chat_a.refresh_from_db()
        self.assertIsNone(self.chat_a.assigned_to)

    def test_office_admin_b_cannot_unassign_chat_a(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        actor = self._user('admin_b', office=self.office_b, role=ROLE_OFFICE_ADMIN)
        assign_chat_to_operator(self.chat_a, operator_a.pk)
        response = self.client.post(self._url(self.chat_a), **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)
        self.chat_a.refresh_from_db()
        self.assertEqual(self.chat_a.assigned_to, operator_a)

    def test_unassign_writes_an_audit_log_entry(self):
        operator_a = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=True)
        actor = self._user('admin_a', office=self.office_a, role=ROLE_OFFICE_ADMIN)
        assign_chat_to_operator(self.chat_a, operator_a.pk)
        self.client.post(self._url(self.chat_a), **self._auth_header(actor))
        self.assertTrue(AuditLog.objects.filter(action='chat.unassign').exists())


class OperatorAvailabilityApiTests(AssignmentApiTestCase):
    URL = '/api/auth/me/availability/'

    def test_operator_can_set_own_availability(self):
        actor = self._user('operator_a', office=self.office_a, role=ROLE_OPERATOR, is_available=False)
        response = self.client.patch(self.URL, {'is_available': True}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)
        actor.office_membership.refresh_from_db()
        self.assertTrue(actor.office_membership.is_available)

    def test_office_admin_cannot_use_this_endpoint(self):
        actor = self._user('admin_a', office=self.office_a, role=ROLE_OFFICE_ADMIN)
        response = self.client.patch(self.URL, {'is_available': True}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_user_without_membership_cannot_use_this_endpoint(self):
        actor = self._user('plain_user')
        response = self.client.patch(self.URL, {'is_available': True}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.patch(self.URL, {'is_available': True}, format='json')
        self.assertEqual(response.status_code, 401)
