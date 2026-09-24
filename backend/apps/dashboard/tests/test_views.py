from datetime import timedelta

from django.contrib.auth.models import User
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.chats.models import Chat, Message
from apps.waha_sessions.models import WahaSession
from apps.webhooks.models import WebhookEvent

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()
MESSAGES_URL = '/api/dashboard/messages/'
ACTIVITY_URL = '/api/dashboard/activity/'


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
)
class DashboardEndpointsTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('operator', password='pw')
        self.token = issue_access_token(self.user)['access_token']
        self.session = WahaSession.objects.create(name='primary')
        self.chat = Chat.objects.create(session=self.session, provider_chat_id='62811@c.us')

    def _auth_header(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}

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
