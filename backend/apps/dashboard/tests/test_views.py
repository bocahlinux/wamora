from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.chats.models import Chat, ConversationSession, Message
from apps.offices.models import ROLE_GLOBAL_ADMIN, ROLE_OPERATOR, Office, OfficeMembership, Role
from apps.waha_sessions.models import WahaSession
from apps.webhooks.models import WebhookEvent

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()
MESSAGES_URL = '/api/dashboard/messages/'
ACTIVITY_URL = '/api/dashboard/activity/'
PENDING_CHATS_URL = '/api/dashboard/pending-chats/'


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
)
class DashboardEndpointsTestCase(APITestCase):
    def setUp(self):
        # Phase 12 (Security hardening) MUST-FIX #1 — both endpoints in
        # this module now require the 'reading' scope (HasReadingScope),
        # so the default test user here carries it via Group membership,
        # the same mechanism apps.chats.test_views/apps.sync.tests.test_views
        # already use for their own '_reading_user()' helpers. A dedicated
        # no-scope user is added below for the negative case.
        self.user = User.objects.create_user('operator', password='pw')
        group, _ = Group.objects.get_or_create(name='reading')
        self.user.groups.add(group)
        self.token = issue_access_token(self.user)['access_token']
        self.session = WahaSession.objects.create(name='primary')
        self.chat = Chat.objects.create(session=self.session, provider_chat_id='62811@c.us')

    def _auth_header(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}

    def _no_scope_auth_header(self):
        no_scope_user = User.objects.create_user('no-scope-operator', password='pw')
        token = issue_access_token(no_scope_user)['access_token']
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def _make_message(self, timestamp, provider_message_id):
        return Message.objects.create(
            session=self.session,
            chat=self.chat,
            provider_message_id=provider_message_id,
            direction=Message.DIRECTION_INBOUND,
            timestamp=timestamp,
        )

    def _make_webhook_event(self, received_at, provider_event_id, event_type='message', status_='processed'):
        event = WebhookEvent.objects.create(
            session=self.session,
            provider_event_id=provider_event_id,
            event_type=event_type,
            status=status_,
        )
        WebhookEvent.objects.filter(pk=event.pk).update(received_at=received_at)
        event.refresh_from_db()
        return event


class MessagesStatsViewTests(DashboardEndpointsTestCase):
    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get(MESSAGES_URL)
        self.assertEqual(response.status_code, 401)

    def test_authenticated_without_reading_scope_is_forbidden(self):
        # Phase 12 (Security hardening) MUST-FIX #1.
        response = self.client.get(MESSAGES_URL, **self._no_scope_auth_header())
        self.assertEqual(response.status_code, 403)

    def test_empty_dataset_returns_zeroed_trend(self):
        response = self.client.get(MESSAGES_URL, **self._auth_header())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['messages_today'], 0)
        self.assertEqual(len(response.data['trend']), 24)
        self.assertTrue(all(bucket['count'] == 0 for bucket in response.data['trend']))

    def test_counts_only_todays_messages(self):
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        self._make_message(today_start + timedelta(hours=2), 'wamid.today-1')
        self._make_message(today_start + timedelta(hours=2, minutes=30), 'wamid.today-2')
        self._make_message(today_start - timedelta(minutes=1), 'wamid.yesterday')
        self._make_message(today_start + timedelta(days=1), 'wamid.tomorrow')

        response = self.client.get(MESSAGES_URL, **self._auth_header())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['messages_today'], 2)

    def test_trend_buckets_messages_by_hour(self):
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        self._make_message(today_start + timedelta(hours=3, minutes=10), 'wamid.a')
        self._make_message(today_start + timedelta(hours=3, minutes=40), 'wamid.b')
        self._make_message(today_start + timedelta(hours=9, minutes=5), 'wamid.c')

        response = self.client.get(MESSAGES_URL, **self._auth_header())
        trend_by_hour = {item['hour']: item['count'] for item in response.data['trend']}
        self.assertEqual(trend_by_hour[(today_start + timedelta(hours=3)).isoformat()], 2)
        self.assertEqual(trend_by_hour[(today_start + timedelta(hours=9)).isoformat()], 1)
        self.assertEqual(trend_by_hour[(today_start + timedelta(hours=5)).isoformat()], 0)

    def test_trend_is_ordered_and_covers_the_full_day(self):
        response = self.client.get(MESSAGES_URL, **self._auth_header())
        hours = [item['hour'] for item in response.data['trend']]
        self.assertEqual(hours, sorted(hours))
        self.assertEqual(len(hours), 24)


class ActivityFeedViewTests(DashboardEndpointsTestCase):
    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get(ACTIVITY_URL)
        self.assertEqual(response.status_code, 401)

    def test_authenticated_without_reading_scope_is_forbidden(self):
        # Phase 12 (Security hardening) MUST-FIX #1.
        response = self.client.get(ACTIVITY_URL, **self._no_scope_auth_header())
        self.assertEqual(response.status_code, 403)

    def test_empty_dataset_returns_empty_results(self):
        response = self.client.get(ACTIVITY_URL, **self._auth_header())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['results'], [])

    def test_merges_audit_and_webhook_events_sorted_by_recency(self):
        now = timezone.now()
        AuditLog.objects.create(
            actor=self.user, action='session.start', target='primary', result=AuditLog.RESULT_SUCCESS
        )
        AuditLog.objects.filter(action='session.start').update(created_at=now - timedelta(minutes=5))
        self._make_webhook_event(now - timedelta(minutes=1), 'evt-1')
        self._make_webhook_event(now - timedelta(minutes=10), 'evt-2')

        response = self.client.get(ACTIVITY_URL, **self._auth_header())
        results = response.data['results']
        self.assertEqual(len(results), 3)
        occurred_ats = [item['occurred_at'] for item in results]
        self.assertEqual(occurred_ats, sorted(occurred_ats, reverse=True))
        self.assertEqual(results[0]['id'], 'webhook-1')
        types = {item['type'] for item in results}
        self.assertEqual(types, {'audit', 'webhook'})

    def test_result_never_exposes_webhook_payload(self):
        self._make_webhook_event(timezone.now(), 'evt-1')
        response = self.client.get(ACTIVITY_URL, **self._auth_header())
        self.assertNotIn('payload', response.data['results'][0])

    def test_limit_bounds_the_result_set(self):
        now = timezone.now()
        for i in range(5):
            self._make_webhook_event(now - timedelta(minutes=i), f'evt-{i}')

        response = self.client.get(f'{ACTIVITY_URL}?limit=2', **self._auth_header())
        self.assertEqual(len(response.data['results']), 2)

    def test_invalid_limit_falls_back_to_default(self):
        response = self.client.get(f'{ACTIVITY_URL}?limit=not-a-number', **self._auth_header())
        self.assertEqual(response.status_code, 200)


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
)
class PendingChatsViewTests(APITestCase):
    """GET /api/dashboard/pending-chats/ — the handoff queue. Reuses
    `apps.chats.authorization.chats_visible_to` for Office boundary, so
    these tests only need to confirm THIS view applies the
    waiting_operator + unassigned filter correctly, plus the one
    discussed edge case (office=None visible to a globally-accessing
    actor only)."""

    def setUp(self):
        self.office_a = Office.objects.create(name='Office A')
        self.office_b = Office.objects.create(name='Office B')
        self.session = WahaSession.objects.create(name='primary')
        self.role_operator = Role.objects.get_or_create(name=ROLE_OPERATOR, defaults={'is_operator': True})[0]
        self.role_global_admin = Role.objects.get_or_create(
            name=ROLE_GLOBAL_ADMIN, defaults={'grants_global_access': True},
        )[0]

    def _auth_header(self, user):
        token = issue_access_token(user)['access_token']
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def _office_user(self, username, office, role):
        user = User.objects.create_user(username, password='pw')
        group, _ = Group.objects.get_or_create(name='reading')
        user.groups.add(group)
        OfficeMembership.objects.create(user=user, office=office, role=role, requires_office=not role.grants_global_access)
        return user

    def _waiting_chat(self, provider_chat_id, office):
        chat = Chat.objects.create(
            session=self.session, provider_chat_id=provider_chat_id, office=office, last_message_at=timezone.now(),
        )
        ConversationSession.objects.create(chat=chat, state=ConversationSession.STATE_WAITING_OPERATOR)
        return chat

    def test_unassigned_waiting_chat_appears_for_own_office(self):
        chat = self._waiting_chat('wp1@lid', self.office_a)
        user = self._office_user('op_a', self.office_a, self.role_operator)

        response = self.client.get(PENDING_CHATS_URL, **self._auth_header(user))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], chat.pk)

    def test_office_b_operator_does_not_see_office_a_pending_chat(self):
        self._waiting_chat('wp1@lid', self.office_a)
        user = self._office_user('op_b', self.office_b, self.role_operator)

        response = self.client.get(PENDING_CHATS_URL, **self._auth_header(user))

        self.assertEqual(response.data['count'], 0)

    def test_already_assigned_chat_does_not_appear(self):
        chat = self._waiting_chat('wp1@lid', self.office_a)
        assignee = self._office_user('op_taken', self.office_a, self.role_operator)
        chat.assigned_to = assignee
        chat.save(update_fields=['assigned_to'])
        viewer = self._office_user('op_viewer', self.office_a, self.role_operator)

        response = self.client.get(PENDING_CHATS_URL, **self._auth_header(viewer))

        self.assertEqual(response.data['count'], 0)

    def test_office_none_pending_chat_visible_only_to_global_admin(self):
        self._waiting_chat('wp1@lid', None)
        operator = self._office_user('op_c', self.office_a, self.role_operator)
        global_admin = self._office_user('gadmin', None, self.role_global_admin)

        operator_response = self.client.get(PENDING_CHATS_URL, **self._auth_header(operator))
        admin_response = self.client.get(PENDING_CHATS_URL, **self._auth_header(global_admin))

        self.assertEqual(operator_response.data['count'], 0)
        self.assertEqual(admin_response.data['count'], 1)
        self.assertIsNone(admin_response.data['results'][0]['office'])
