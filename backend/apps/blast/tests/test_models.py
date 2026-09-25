from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.blast.models import BlastCampaign, BlastRecipient
from apps.waha_sessions.models import WahaSession


class BlastCampaignTransitionTests(TestCase):
    def test_draft_can_only_go_to_pending_approval(self):
        self.assertTrue(BlastCampaign.is_valid_transition(BlastCampaign.STATUS_DRAFT, BlastCampaign.STATUS_PENDING_APPROVAL))
        self.assertFalse(BlastCampaign.is_valid_transition(BlastCampaign.STATUS_DRAFT, BlastCampaign.STATUS_APPROVED))
        self.assertFalse(BlastCampaign.is_valid_transition(BlastCampaign.STATUS_DRAFT, BlastCampaign.STATUS_SENDING))
        self.assertFalse(BlastCampaign.is_valid_transition(BlastCampaign.STATUS_DRAFT, BlastCampaign.STATUS_REJECTED))

    def test_pending_approval_can_go_to_approved_or_rejected_only(self):
        self.assertTrue(
            BlastCampaign.is_valid_transition(BlastCampaign.STATUS_PENDING_APPROVAL, BlastCampaign.STATUS_APPROVED)
        )
        self.assertTrue(
            BlastCampaign.is_valid_transition(BlastCampaign.STATUS_PENDING_APPROVAL, BlastCampaign.STATUS_REJECTED)
        )
        self.assertFalse(
            BlastCampaign.is_valid_transition(BlastCampaign.STATUS_PENDING_APPROVAL, BlastCampaign.STATUS_SENDING)
        )

    def test_approved_can_only_go_to_sending(self):
        self.assertTrue(BlastCampaign.is_valid_transition(BlastCampaign.STATUS_APPROVED, BlastCampaign.STATUS_SENDING))
        self.assertFalse(
            BlastCampaign.is_valid_transition(BlastCampaign.STATUS_APPROVED, BlastCampaign.STATUS_COMPLETED)
        )

    def test_sending_can_go_to_completed_or_failed_only(self):
        self.assertTrue(BlastCampaign.is_valid_transition(BlastCampaign.STATUS_SENDING, BlastCampaign.STATUS_COMPLETED))
        self.assertTrue(BlastCampaign.is_valid_transition(BlastCampaign.STATUS_SENDING, BlastCampaign.STATUS_FAILED))
        self.assertFalse(BlastCampaign.is_valid_transition(BlastCampaign.STATUS_SENDING, BlastCampaign.STATUS_APPROVED))

    def test_terminal_statuses_allow_no_further_transition(self):
        for terminal in (BlastCampaign.STATUS_COMPLETED, BlastCampaign.STATUS_REJECTED, BlastCampaign.STATUS_FAILED):
            for target in (BlastCampaign.STATUS_DRAFT, BlastCampaign.STATUS_PENDING_APPROVAL, BlastCampaign.STATUS_APPROVED):
                self.assertFalse(BlastCampaign.is_valid_transition(terminal, target))

    def test_unknown_status_has_no_allowed_transitions(self):
        self.assertFalse(BlastCampaign.is_valid_transition('not_a_real_status', BlastCampaign.STATUS_APPROVED))


class BlastRecipientModelTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')
        self.user = User.objects.create_user('creator', password='pw')
        self.campaign = BlastCampaign.objects.create(
            session=self.session, name='Test', message_template='hi', created_by=self.user,
        )

    def test_idempotency_key_is_deterministic_and_derived(self):
        recipient = BlastRecipient.objects.create(campaign=self.campaign, destination='+6280000000001')
        self.assertEqual(recipient.idempotency_key, f'blast:{self.campaign.pk}:{recipient.pk}')

    def test_duplicate_destination_within_same_campaign_is_rejected(self):
        BlastRecipient.objects.create(campaign=self.campaign, destination='+6280000000001')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BlastRecipient.objects.create(campaign=self.campaign, destination='+6280000000001')

    def test_same_destination_in_different_campaigns_is_allowed(self):
        other_campaign = BlastCampaign.objects.create(
            session=self.session, name='Other', message_template='hi', created_by=self.user,
        )
        BlastRecipient.objects.create(campaign=self.campaign, destination='+6280000000001')
        # Must not raise.
        BlastRecipient.objects.create(campaign=other_campaign, destination='+6280000000001')
