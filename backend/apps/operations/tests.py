from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.operations.models import OutboundOperation
from apps.waha_sessions.models import WahaSession


class OutboundOperationTests(TestCase):
    """docs/05-WEBHOOK-SYNC-DESIGN.md "Outbound during outage": use an
    idempotency key; never blindly resend an operation whose success is
    uncertain."""

    def setUp(self):
        self.session_a = WahaSession.objects.create(name='session-a')
        self.session_b = WahaSession.objects.create(name='session-b')

    def test_duplicate_idempotency_key_rejected_within_same_session(self):
        OutboundOperation.objects.create(
            session=self.session_a,
            idempotency_key='op-1',
            destination='62811@c.us',
            operation_type='send_text',
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OutboundOperation.objects.create(
                    session=self.session_a,
                    idempotency_key='op-1',
                    destination='62811@c.us',
                    operation_type='send_text',
                )

    def test_same_idempotency_key_allowed_across_different_sessions(self):
        OutboundOperation.objects.create(
            session=self.session_a, idempotency_key='op-1', destination='x', operation_type='send_text'
        )
        OutboundOperation.objects.create(
            session=self.session_b, idempotency_key='op-1', destination='x', operation_type='send_text'
        )
        self.assertEqual(OutboundOperation.objects.filter(idempotency_key='op-1').count(), 2)

    def test_unknown_status_models_ambiguous_outcome(self):
        operation = OutboundOperation.objects.create(
            session=self.session_a,
            idempotency_key='op-2',
            destination='62811@c.us',
            operation_type='send_text',
            status=OutboundOperation.STATUS_UNKNOWN,
        )
        self.assertEqual(operation.status, OutboundOperation.STATUS_UNKNOWN)
