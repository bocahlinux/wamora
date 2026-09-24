from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.waha_sessions.models import WahaSession
from apps.webhooks.models import WebhookEvent


class WebhookEventTests(TestCase):
    """docs/04-DATA-MODEL.md WebhookEvent: processing must be idempotent."""

    def setUp(self):
        self.session_a = WahaSession.objects.create(name='session-a')
        self.session_b = WahaSession.objects.create(name='session-b')

    def test_default_status_is_pending(self):
        event = WebhookEvent.objects.create(
            session=self.session_a, provider_event_id='evt-1', event_type='message'
        )
        self.assertEqual(event.status, WebhookEvent.STATUS_PENDING)
        self.assertEqual(event.attempts, 0)

    def test_duplicate_delivery_rejected_within_same_session(self):
        WebhookEvent.objects.create(session=self.session_a, provider_event_id='evt-1', event_type='message')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WebhookEvent.objects.create(
                    session=self.session_a, provider_event_id='evt-1', event_type='message'
                )

    def test_same_event_id_allowed_across_different_sessions(self):
        WebhookEvent.objects.create(session=self.session_a, provider_event_id='evt-1', event_type='message')
        WebhookEvent.objects.create(session=self.session_b, provider_event_id='evt-1', event_type='message')
        self.assertEqual(WebhookEvent.objects.filter(provider_event_id='evt-1').count(), 2)
