from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.blast.bff_client import BffDispatchError
from apps.blast.models import BlastCampaign, BlastRecipient, OPERATION_TYPE_BLAST_SEND
from apps.blast.tasks import dispatch_blast_recipient_task, schedule_blast_campaign_task
from apps.operations.models import OutboundOperation
from apps.waha_sessions.models import WahaSession


def make_campaign(session, user, status=BlastCampaign.STATUS_APPROVED, recipient_count=3, name='Campaign'):
    campaign = BlastCampaign.objects.create(
        session=session, name=name, message_template='hello', created_by=user, status=status,
    )
    for i in range(recipient_count):
        BlastRecipient.objects.create(campaign=campaign, destination=f'+6280000{i:04d}')
    return campaign


class ScheduleBlastCampaignTaskTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')
        self.user = User.objects.create_user('creator', password='pw')

    def test_not_approved_campaign_is_a_no_op(self):
        campaign = make_campaign(self.session, self.user, status=BlastCampaign.STATUS_DRAFT)
        with mock.patch('apps.blast.tasks.dispatch_blast_recipient_task.apply_async') as mocked:
            result = schedule_blast_campaign_task.apply(args=[campaign.pk]).result
        self.assertEqual(result['skipped'], 'not_approved')
        mocked.assert_not_called()

    def test_missing_campaign_is_a_no_op(self):
        with mock.patch('apps.blast.tasks.dispatch_blast_recipient_task.apply_async') as mocked:
            result = schedule_blast_campaign_task.apply(args=[999999]).result
        self.assertEqual(result['skipped'], 'not_found')
        mocked.assert_not_called()

    def test_transitions_campaign_to_sending(self):
        campaign = make_campaign(self.session, self.user)
        with mock.patch('apps.blast.tasks.dispatch_blast_recipient_task.apply_async'):
            schedule_blast_campaign_task.apply(args=[campaign.pk])
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, BlastCampaign.STATUS_SENDING)

    def test_schedules_recipients_exactly_60_seconds_apart_in_id_order(self):
        campaign = make_campaign(self.session, self.user, recipient_count=4)
        with mock.patch('apps.blast.tasks.dispatch_blast_recipient_task.apply_async'):
            schedule_blast_campaign_task.apply(args=[campaign.pk])

        recipients = list(campaign.recipients.order_by('id'))
        for r in recipients:
            self.assertIsNotNone(r.scheduled_for)
        for earlier, later in zip(recipients, recipients[1:]):
            self.assertEqual((later.scheduled_for - earlier.scheduled_for).total_seconds(), 60)

    def test_enqueues_one_dispatch_task_per_recipient_with_matching_countdown(self):
        campaign = make_campaign(self.session, self.user, recipient_count=3)
        with mock.patch('apps.blast.tasks.dispatch_blast_recipient_task.apply_async') as mocked:
            schedule_blast_campaign_task.apply(args=[campaign.pk])

        self.assertEqual(mocked.call_count, 3)
        recipients = list(campaign.recipients.order_by('id'))
        countdowns = sorted(call.kwargs['countdown'] for call in mocked.call_args_list)
        self.assertAlmostEqual(countdowns[0], 0, delta=2)
        self.assertAlmostEqual(countdowns[1], 60, delta=2)
        self.assertAlmostEqual(countdowns[2], 120, delta=2)
        dispatched_ids = {call.kwargs['args'][0] for call in mocked.call_args_list}
        self.assertEqual(dispatched_ids, {r.pk for r in recipients})

    def test_throttles_against_another_campaigns_pending_recipients_on_the_same_session(self):
        earlier_campaign = make_campaign(self.session, self.user, status=BlastCampaign.STATUS_SENDING, recipient_count=1, name='Earlier')
        earlier_recipient = earlier_campaign.recipients.first()
        far_future = timezone.now() + timedelta(minutes=10)
        BlastRecipient.objects.filter(pk=earlier_recipient.pk).update(scheduled_for=far_future)

        later_campaign = make_campaign(self.session, self.user, recipient_count=2, name='Later')
        with mock.patch('apps.blast.tasks.dispatch_blast_recipient_task.apply_async'):
            schedule_blast_campaign_task.apply(args=[later_campaign.pk])

        later_recipients = list(later_campaign.recipients.order_by('id'))
        self.assertGreaterEqual(
            (later_recipients[0].scheduled_for - far_future).total_seconds(), 60 - 1,
        )

    def test_different_session_recipients_do_not_throttle_each_other(self):
        other_session = WahaSession.objects.create(name='secondary')
        campaign_a = make_campaign(self.session, self.user, status=BlastCampaign.STATUS_SENDING, recipient_count=1, name='A')
        far_future = timezone.now() + timedelta(minutes=10)
        BlastRecipient.objects.filter(pk=campaign_a.recipients.first().pk).update(scheduled_for=far_future)

        campaign_b = make_campaign(other_session, self.user, recipient_count=1, name='B')
        with mock.patch('apps.blast.tasks.dispatch_blast_recipient_task.apply_async'):
            schedule_blast_campaign_task.apply(args=[campaign_b.pk])

        recipient_b = campaign_b.recipients.first()
        recipient_b.refresh_from_db()
        # Must schedule near "now", NOT after campaign_a's far-future
        # recipient — different sessions never share the throttle.
        self.assertLess(recipient_b.scheduled_for, far_future)

    def test_calling_twice_only_schedules_once(self):
        campaign = make_campaign(self.session, self.user, recipient_count=2)
        with mock.patch('apps.blast.tasks.dispatch_blast_recipient_task.apply_async') as mocked:
            schedule_blast_campaign_task.apply(args=[campaign.pk])
            schedule_blast_campaign_task.apply(args=[campaign.pk])
        self.assertEqual(mocked.call_count, 2)  # only the first call's 2 recipients, not 4


class DispatchBlastRecipientTaskTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')
        self.user = User.objects.create_user('creator', password='pw')
        self.campaign = make_campaign(self.session, self.user, status=BlastCampaign.STATUS_SENDING, recipient_count=1)
        self.recipient = self.campaign.recipients.first()

    def test_missing_recipient_is_a_no_op(self):
        result = dispatch_blast_recipient_task.apply(args=[999999]).result
        self.assertEqual(result['skipped'], 'not_found')

    def test_campaign_not_sending_is_a_no_op(self):
        BlastCampaign.objects.filter(pk=self.campaign.pk).update(status=BlastCampaign.STATUS_APPROVED)
        with mock.patch('apps.blast.tasks.send_blast_message') as mocked:
            result = dispatch_blast_recipient_task.apply(args=[self.recipient.pk]).result
        self.assertEqual(result['skipped'], 'campaign_not_sending')
        mocked.assert_not_called()

    def test_already_claimed_recipient_is_a_no_op(self):
        BlastRecipient.objects.filter(pk=self.recipient.pk).update(status=BlastRecipient.STATUS_SENDING)
        with mock.patch('apps.blast.tasks.send_blast_message') as mocked:
            result = dispatch_blast_recipient_task.apply(args=[self.recipient.pk]).result
        self.assertEqual(result['skipped'], 'already_claimed')
        mocked.assert_not_called()

    def test_successful_send_marks_recipient_sent_and_resolves_outbound_operation(self):
        with mock.patch(
            'apps.blast.tasks.send_blast_message',
            return_value={'status': 'sent', 'provider_message_id': 'wa-msg-1'},
        ):
            dispatch_blast_recipient_task.apply(args=[self.recipient.pk])

        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.status, BlastRecipient.STATUS_SENT)
        self.assertIsNotNone(self.recipient.sent_at)
        self.assertIsNotNone(self.recipient.outbound_operation)
        self.assertEqual(self.recipient.outbound_operation.status, OutboundOperation.STATUS_SENT)
        self.assertEqual(self.recipient.outbound_operation.provider_message_id, 'wa-msg-1')
        self.assertEqual(self.recipient.outbound_operation.operation_type, OPERATION_TYPE_BLAST_SEND)

    def test_failed_send_marks_recipient_failed_with_sanitized_reason(self):
        with mock.patch('apps.blast.tasks.send_blast_message', side_effect=BffDispatchError('raw internal detail: 500 from BFF')):
            dispatch_blast_recipient_task.apply(args=[self.recipient.pk])

        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.status, BlastRecipient.STATUS_FAILED)
        self.assertNotIn('raw internal detail', self.recipient.failure_reason)
        self.assertNotIn('BFF', self.recipient.failure_reason)
        self.assertTrue(self.recipient.failure_reason)
        self.assertEqual(self.recipient.outbound_operation.status, OutboundOperation.STATUS_FAILED)

    def test_bff_reported_failed_status_also_marks_recipient_failed(self):
        with mock.patch('apps.blast.tasks.send_blast_message', return_value={'status': 'failed', 'provider_message_id': None}):
            dispatch_blast_recipient_task.apply(args=[self.recipient.pk])
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.status, BlastRecipient.STATUS_FAILED)

    def test_unknown_outcome_marks_recipient_failed_but_operation_unknown(self):
        with mock.patch('apps.blast.tasks.send_blast_message', return_value={'status': 'unknown', 'provider_message_id': None}):
            dispatch_blast_recipient_task.apply(args=[self.recipient.pk])
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.status, BlastRecipient.STATUS_FAILED)
        self.assertEqual(self.recipient.outbound_operation.status, OutboundOperation.STATUS_UNKNOWN)

    def test_task_never_raises_on_dispatch_failure_no_auto_retry(self):
        # Decision 5: no auto-retry. If this task re-raised, Celery's
        # default (non-autoretry) behavior would still not retry it
        # automatically, but re-raising would also mark the task FAILURE
        # in any result backend and could be misread as needing a retry
        # policy — this task must complete normally (return, not raise)
        # even when the send itself failed.
        with mock.patch('apps.blast.tasks.send_blast_message', side_effect=BffDispatchError('boom')):
            async_result = dispatch_blast_recipient_task.apply(args=[self.recipient.pk])
        self.assertTrue(async_result.successful())

    def test_the_same_recipient_task_firing_twice_results_in_exactly_one_sent_outbound_operation(self):
        # Simulates Celery's at-least-once redelivery of the SAME task
        # invocation (e.g. the worker acked late, or crashed after
        # completing but before acking). The first call must claim +
        # dispatch + resolve; a second call must recognize the recipient
        # is no longer `pending` (already `sent`) and must not call
        # send_blast_message again.
        with mock.patch(
            'apps.blast.tasks.send_blast_message',
            return_value={'status': 'sent', 'provider_message_id': 'wa-msg-1'},
        ) as mocked:
            dispatch_blast_recipient_task.apply(args=[self.recipient.pk])
            dispatch_blast_recipient_task.apply(args=[self.recipient.pk])

        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(
            OutboundOperation.objects.filter(operation_type=OPERATION_TYPE_BLAST_SEND, status=OutboundOperation.STATUS_SENT).count(),
            1,
        )
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.status, BlastRecipient.STATUS_SENT)

    def test_redelivery_after_operation_already_sent_reflects_without_resending(self):
        # A narrower variant: the OutboundOperation row is already `sent`
        # (e.g. from a first invocation whose recipient-row update lost a
        # race) but this recipient row is still `pending` — get_or_create
        # finds the existing SENT operation and must not re-dispatch.
        from apps.blast.models import BlastRecipient as BR

        OutboundOperation.objects.create(
            session=self.session, idempotency_key=self.recipient.idempotency_key, destination=self.recipient.destination,
            operation_type=OPERATION_TYPE_BLAST_SEND, status=OutboundOperation.STATUS_SENT,
            provider_message_id='wa-already-sent',
        )
        with mock.patch('apps.blast.tasks.send_blast_message') as mocked:
            result = dispatch_blast_recipient_task.apply(args=[self.recipient.pk]).result

        mocked.assert_not_called()
        self.assertEqual(result['result'], 'already_sent')
        self.recipient.refresh_from_db()
        self.assertEqual(self.recipient.status, BR.STATUS_SENT)


class CampaignFinalizationTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')
        self.user = User.objects.create_user('creator', password='pw')

    def test_campaign_completes_when_all_recipients_reach_a_terminal_status_with_at_least_one_sent(self):
        campaign = make_campaign(self.session, self.user, status=BlastCampaign.STATUS_SENDING, recipient_count=2)
        recipients = list(campaign.recipients.all())

        with mock.patch('apps.blast.tasks.send_blast_message', return_value={'status': 'sent', 'provider_message_id': 'm1'}):
            dispatch_blast_recipient_task.apply(args=[recipients[0].pk])
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, BlastCampaign.STATUS_SENDING)  # still in-flight

        with mock.patch('apps.blast.tasks.send_blast_message', side_effect=BffDispatchError('boom')):
            dispatch_blast_recipient_task.apply(args=[recipients[1].pk])
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, BlastCampaign.STATUS_COMPLETED)

    def test_campaign_reaches_failed_status_only_when_every_recipient_failed(self):
        campaign = make_campaign(self.session, self.user, status=BlastCampaign.STATUS_SENDING, recipient_count=2)
        recipients = list(campaign.recipients.all())

        with mock.patch('apps.blast.tasks.send_blast_message', side_effect=BffDispatchError('boom')):
            dispatch_blast_recipient_task.apply(args=[recipients[0].pk])
            dispatch_blast_recipient_task.apply(args=[recipients[1].pk])

        campaign.refresh_from_db()
        self.assertEqual(campaign.status, BlastCampaign.STATUS_FAILED)
