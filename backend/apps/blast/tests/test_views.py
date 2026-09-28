from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.blast.models import BlastCampaign, BlastRecipient, OPERATION_TYPE_BLAST_SEND
from apps.offices.models import ROLE_GLOBAL_ADMIN, ROLE_OFFICE_ADMIN, ROLE_OPERATOR, Office, OfficeMembership, Role
from apps.operations.models import OutboundOperation
from apps.waha_sessions.models import WahaSession

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()

# Step 4 (Office integration) — distinguishes "not given, use the
# default test Office" from "explicitly no Office at all" for _user()/
# _create_campaign() below, without a magic string/None ambiguity.
_DEFAULT_OFFICE = object()

# The Role merge — resolves the old CharField's three fixed string
# values to the migration-0009-seeded Role rows with the matching
# organizational flags (`grants_global_access`/`is_office_admin`/
# `is_operator`), so `_user()` below keeps accepting the same
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


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
    BLAST_MAX_RECIPIENTS_PER_CAMPAIGN=100,
    BLAST_MAX_RECIPIENTS_PER_SESSION_PER_DAY=500,
)
class BlastCampaignAPITestCase(APITestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')
        # Step 4 (Office integration) — every test user/campaign below
        # defaults into this one Office unless a test explicitly asks
        # for something else (office=None or a different Office), so
        # every pre-existing test in this file keeps its original
        # meaning ("some ordinary campaign, some ordinary admin") without
        # having to touch each call site individually.
        self.office_a = Office.objects.create(name='Office A')
        self.office_b = Office.objects.create(name='Office B')

    def _user(self, username, scopes=(), office=_DEFAULT_OFFICE, role=ROLE_OPERATOR):
        user = User.objects.create_user(username, password='pw')
        for scope in scopes:
            group, _ = Group.objects.get_or_create(name=scope)
            user.groups.add(group)
        actual_office = self.office_a if office is _DEFAULT_OFFICE else office
        if actual_office is not None:
            role_obj = role if isinstance(role, Role) else _seeded_role(role)
            OfficeMembership.objects.create(
                user=user, office=actual_office, role=role_obj, requires_office=not role_obj.grants_global_access
            )
        return user

    def _auth_header(self, user):
        token = issue_access_token(user)['access_token']
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def _create_campaign(self, creator, recipient_count=3, session_name=None, office=_DEFAULT_OFFICE):
        recipients = [f'+62800000{i:05d}' for i in range(recipient_count)]
        payload = {
            'session': session_name or self.session.name,
            'name': 'Promo blast',
            'message_template': 'Hello there',
            'recipients': recipients,
        }
        actual_office = self.office_a if office is _DEFAULT_OFFICE else office
        if actual_office is not None:
            payload['office'] = actual_office.pk
        response = self.client.post(
            '/api/blast/campaigns/', payload, format='json', **self._auth_header(creator)
        )
        return response


class BlastCampaignCreateTests(BlastCampaignAPITestCase):
    def test_unauthenticated_request_is_rejected(self):
        response = self.client.post('/api/blast/campaigns/', {}, format='json')
        self.assertEqual(response.status_code, 401)

    def test_user_without_blast_scope_is_forbidden(self):
        user = self._user('nobody')
        response = self._create_campaign(user)
        self.assertEqual(response.status_code, 403)

    def test_blast_scoped_user_can_create_a_draft_campaign(self):
        creator = self._user('creator', scopes=['blast'])
        response = self._create_campaign(creator, recipient_count=3)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], BlastCampaign.STATUS_DRAFT)
        campaign = BlastCampaign.objects.get(pk=response.data['id'])
        self.assertEqual(campaign.created_by, creator)
        self.assertEqual(campaign.recipients.count(), 3)

    def test_create_writes_an_audit_log_entry(self):
        creator = self._user('creator', scopes=['blast'])
        response = self._create_campaign(creator, recipient_count=2)
        self.assertEqual(response.status_code, 201)
        entry = AuditLog.objects.get(action='blast.campaign.create')
        self.assertEqual(entry.actor, creator)
        self.assertEqual(entry.result, AuditLog.RESULT_SUCCESS)

    def test_more_than_max_recipients_is_rejected(self):
        creator = self._user('creator', scopes=['blast'])
        response = self._create_campaign(creator, recipient_count=101)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(BlastCampaign.objects.exists())

    def test_exactly_max_recipients_is_allowed(self):
        creator = self._user('creator', scopes=['blast'])
        response = self._create_campaign(creator, recipient_count=100)
        self.assertEqual(response.status_code, 201)

    def test_empty_recipients_is_rejected(self):
        creator = self._user('creator', scopes=['blast'])
        response = self.client.post(
            '/api/blast/campaigns/',
            {'session': self.session.name, 'name': 'x', 'message_template': 'hi', 'recipients': []},
            format='json',
            **self._auth_header(creator),
        )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_recipients_are_deduplicated_not_rejected(self):
        creator = self._user('creator', scopes=['blast'])
        response = self.client.post(
            '/api/blast/campaigns/',
            {
                'session': self.session.name, 'name': 'x', 'message_template': 'hi',
                'recipients': ['+628001', '+628001', '+628002'],
            },
            format='json',
            **self._auth_header(creator),
        )
        self.assertEqual(response.status_code, 201)
        campaign = BlastCampaign.objects.get(pk=response.data['id'])
        self.assertEqual(campaign.recipients.count(), 2)

    def test_unknown_session_is_rejected(self):
        creator = self._user('creator', scopes=['blast'])
        response = self._create_campaign(creator, session_name='does-not-exist')
        self.assertEqual(response.status_code, 400)


class BlastCampaignReadAccessTests(BlastCampaignAPITestCase):
    def test_blast_scoped_user_can_list(self):
        creator = self._user('creator', scopes=['blast'])
        self._create_campaign(creator, recipient_count=1)
        response = self.client.get('/api/blast/campaigns/', **self._auth_header(creator))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_system_administration_scoped_user_can_list(self):
        creator = self._user('creator', scopes=['blast'])
        self._create_campaign(creator, recipient_count=1)
        admin = self._user('admin', scopes=['system administration'])
        response = self.client.get('/api/blast/campaigns/', **self._auth_header(admin))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)

    def test_user_with_neither_scope_cannot_list(self):
        nobody = self._user('nobody')
        response = self.client.get('/api/blast/campaigns/', **self._auth_header(nobody))
        self.assertEqual(response.status_code, 403)

    def test_detail_view_includes_recipients(self):
        creator = self._user('creator', scopes=['blast'])
        created = self._create_campaign(creator, recipient_count=2)
        response = self.client.get(f'/api/blast/campaigns/{created.data["id"]}/', **self._auth_header(creator))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['recipients']), 2)


class BlastCampaignSubmitTests(BlastCampaignAPITestCase):
    def test_creator_can_submit_own_draft(self):
        creator = self._user('creator', scopes=['blast'])
        created = self._create_campaign(creator)
        response = self.client.post(
            f'/api/blast/campaigns/{created.data["id"]}/submit/', **self._auth_header(creator)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], BlastCampaign.STATUS_PENDING_APPROVAL)

    def test_another_blast_scoped_user_cannot_submit_someone_elses_draft(self):
        creator = self._user('creator', scopes=['blast'])
        other = self._user('other', scopes=['blast'])
        created = self._create_campaign(creator)
        response = self.client.post(f'/api/blast/campaigns/{created.data["id"]}/submit/', **self._auth_header(other))
        self.assertEqual(response.status_code, 403)

    def test_cannot_submit_a_campaign_twice(self):
        creator = self._user('creator', scopes=['blast'])
        created = self._create_campaign(creator)
        self.client.post(f'/api/blast/campaigns/{created.data["id"]}/submit/', **self._auth_header(creator))
        response = self.client.post(f'/api/blast/campaigns/{created.data["id"]}/submit/', **self._auth_header(creator))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error']['code'], 'invalid_transition')


class BlastCampaignApproveTests(BlastCampaignAPITestCase):
    def _submitted_campaign(self, creator, recipient_count=3):
        created = self._create_campaign(creator, recipient_count=recipient_count)
        self.client.post(f'/api/blast/campaigns/{created.data["id"]}/submit/', **self._auth_header(creator))
        return created.data['id']

    @mock.patch('apps.blast.views.schedule_blast_campaign_task.delay')
    def test_non_superuser_approver_can_approve_another_users_campaign(self, mocked_delay):
        creator = self._user('creator', scopes=['blast'])
        admin = self._user('admin', scopes=['system administration'])
        campaign_id = self._submitted_campaign(creator)

        response = self.client.post(f'/api/blast/campaigns/{campaign_id}/approve/', **self._auth_header(admin))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], BlastCampaign.STATUS_APPROVED)
        campaign = BlastCampaign.objects.get(pk=campaign_id)
        self.assertEqual(campaign.approved_by, admin)
        self.assertIsNotNone(campaign.approved_at)
        mocked_delay.assert_called_once_with(campaign_id)

    @mock.patch('apps.blast.views.schedule_blast_campaign_task.delay')
    def test_superuser_can_approve_own_pending_campaign(self, mocked_delay):
        superadmin = User.objects.create_superuser('superadmin', 'superadmin@example.com', 'pw')
        campaign_id = self._submitted_campaign(superadmin)

        response = self.client.post(f'/api/blast/campaigns/{campaign_id}/approve/', **self._auth_header(superadmin))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], BlastCampaign.STATUS_APPROVED)
        campaign = BlastCampaign.objects.get(pk=campaign_id)
        self.assertEqual(campaign.created_by, superadmin)
        self.assertEqual(campaign.approved_by, superadmin)
        self.assertIsNotNone(campaign.approved_at)
        mocked_delay.assert_called_once_with(campaign_id)

    @mock.patch('apps.blast.views.schedule_blast_campaign_task.delay')
    def test_approval_writes_an_audit_log_entry(self, mocked_delay):
        creator = self._user('creator', scopes=['blast'])
        admin = self._user('admin', scopes=['system administration'])
        campaign_id = self._submitted_campaign(creator)

        self.client.post(f'/api/blast/campaigns/{campaign_id}/approve/', **self._auth_header(admin))

        entry = AuditLog.objects.get(action='blast.campaign.approve')
        self.assertEqual(entry.actor, admin)

    def test_user_without_approval_scope_cannot_approve(self):
        creator = self._user('creator', scopes=['blast'])
        other = self._user('other', scopes=['blast'])
        campaign_id = self._submitted_campaign(creator)

        response = self.client.post(f'/api/blast/campaigns/{campaign_id}/approve/', **self._auth_header(other))
        self.assertEqual(response.status_code, 403)

    def test_non_superuser_creator_holding_admin_scope_cannot_approve_own_campaign(self):
        # The security regression: scope ownership alone never permits a
        # non-superuser to self-approve, even when they genuinely hold both.
        creator = self._user('creator', scopes=['blast', 'system administration'])
        campaign_id = self._submitted_campaign(creator)

        response = self.client.post(f'/api/blast/campaigns/{campaign_id}/approve/', **self._auth_header(creator))
        self.assertEqual(response.status_code, 403)
        campaign = BlastCampaign.objects.get(pk=campaign_id)
        self.assertEqual(campaign.status, BlastCampaign.STATUS_PENDING_APPROVAL)

    def test_cannot_approve_a_draft_campaign(self):
        creator = self._user('creator', scopes=['blast'])
        admin = self._user('admin', scopes=['system administration'])
        created = self._create_campaign(creator)

        response = self.client.post(f'/api/blast/campaigns/{created.data["id"]}/approve/', **self._auth_header(admin))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error']['code'], 'invalid_transition')

    @override_settings(BLAST_MAX_RECIPIENTS_PER_SESSION_PER_DAY=5)
    def test_approval_is_rejected_when_it_would_exceed_the_daily_budget(self):
        creator = self._user('creator', scopes=['blast'])
        admin = self._user('admin', scopes=['system administration'])

        # Consume 3 of the 5-per-day budget already.
        for i in range(3):
            OutboundOperation.objects.create(
                session=self.session, idempotency_key=f'blast:prior:{i}', destination='+6280000',
                operation_type=OPERATION_TYPE_BLAST_SEND, status=OutboundOperation.STATUS_SENT,
            )

        campaign_id = self._submitted_campaign(creator, recipient_count=3)  # would bring total to 6 > 5

        response = self.client.post(f'/api/blast/campaigns/{campaign_id}/approve/', **self._auth_header(admin))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error']['code'], 'daily_budget_exceeded')
        campaign = BlastCampaign.objects.get(pk=campaign_id)
        self.assertEqual(campaign.status, BlastCampaign.STATUS_PENDING_APPROVAL)

    @mock.patch('apps.blast.views.schedule_blast_campaign_task.delay')
    @override_settings(BLAST_MAX_RECIPIENTS_PER_SESSION_PER_DAY=5)
    def test_approval_succeeds_when_exactly_at_the_daily_budget(self, mocked_delay):
        creator = self._user('creator', scopes=['blast'])
        admin = self._user('admin', scopes=['system administration'])
        for i in range(2):
            OutboundOperation.objects.create(
                session=self.session, idempotency_key=f'blast:prior:{i}', destination='+6280000',
                operation_type=OPERATION_TYPE_BLAST_SEND, status=OutboundOperation.STATUS_SENT,
            )
        campaign_id = self._submitted_campaign(creator, recipient_count=3)  # totals exactly 5

        response = self.client.post(f'/api/blast/campaigns/{campaign_id}/approve/', **self._auth_header(admin))
        self.assertEqual(response.status_code, 200)


class BlastCampaignRejectTests(BlastCampaignAPITestCase):
    def test_admin_can_reject_a_pending_campaign(self):
        creator = self._user('creator', scopes=['blast'])
        admin = self._user('admin', scopes=['system administration'])
        created = self._create_campaign(creator)
        self.client.post(f'/api/blast/campaigns/{created.data["id"]}/submit/', **self._auth_header(creator))

        response = self.client.post(
            f'/api/blast/campaigns/{created.data["id"]}/reject/', {'reason': 'Not approved this week'},
            format='json', **self._auth_header(admin),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], BlastCampaign.STATUS_REJECTED)
        campaign = BlastCampaign.objects.get(pk=created.data['id'])
        self.assertEqual(campaign.rejected_reason, 'Not approved this week')

    def test_rejection_writes_an_audit_log_entry(self):
        creator = self._user('creator', scopes=['blast'])
        admin = self._user('admin', scopes=['system administration'])
        created = self._create_campaign(creator)
        self.client.post(f'/api/blast/campaigns/{created.data["id"]}/submit/', **self._auth_header(creator))

        self.client.post(f'/api/blast/campaigns/{created.data["id"]}/reject/', format='json', **self._auth_header(admin))

        entry = AuditLog.objects.get(action='blast.campaign.reject')
        self.assertEqual(entry.actor, admin)

    def test_rejected_campaign_is_terminal_cannot_be_resubmitted(self):
        creator = self._user('creator', scopes=['blast'])
        admin = self._user('admin', scopes=['system administration'])
        created = self._create_campaign(creator)
        self.client.post(f'/api/blast/campaigns/{created.data["id"]}/submit/', **self._auth_header(creator))
        self.client.post(f'/api/blast/campaigns/{created.data["id"]}/reject/', format='json', **self._auth_header(admin))

        response = self.client.post(f'/api/blast/campaigns/{created.data["id"]}/submit/', **self._auth_header(creator))
        self.assertEqual(response.status_code, 409)

    def test_non_admin_cannot_reject(self):
        creator = self._user('creator', scopes=['blast'])
        created = self._create_campaign(creator)
        self.client.post(f'/api/blast/campaigns/{created.data["id"]}/submit/', **self._auth_header(creator))

        response = self.client.post(
            f'/api/blast/campaigns/{created.data["id"]}/reject/', format='json', **self._auth_header(creator)
        )
        self.assertEqual(response.status_code, 403)


class BlastRecipientResolveTests(BlastCampaignAPITestCase):
    """Phase 11 stuck-recovery fix —
    docs/generated/PHASE-11-BLAST-END-TO-END-AUDIT-REPORT.md Section 4/6.
    A `sending` recipient (worker died after the WAHA send but before the
    final status write) can be manually resolved by a 'system
    administration'-scoped admin, using the same compare-and-set
    discipline as every other status write in this app, and this also
    unblocks `_maybe_finalize_campaign` for the recipient's campaign."""

    def _sending_campaign(self, recipient_count=2, status=BlastCampaign.STATUS_SENDING):
        # A shared, unscoped creator reused across calls within one test
        # (this test class never authenticates as the creator, only as
        # `admin`) — avoids a duplicate-username collision from calling
        # this helper more than once in the same test.
        creator, _ = User.objects.get_or_create(username='campaign-creator')
        campaign = BlastCampaign.objects.create(
            session=self.session, name='Campaign', message_template='hello', created_by=creator, status=status,
        )
        recipients = [
            BlastRecipient.objects.create(campaign=campaign, destination=f'+6280000{i:04d}')
            for i in range(recipient_count)
        ]
        return campaign, recipients

    def _url(self, campaign_id, recipient_id):
        return f'/api/blast/campaigns/{campaign_id}/recipients/{recipient_id}/resolve/'

    def _stuck(self, recipient):
        BlastRecipient.objects.filter(pk=recipient.pk).update(status=BlastRecipient.STATUS_SENDING)
        recipient.refresh_from_db()
        return recipient

    # -- authentication / authorization --------------------------------------

    def test_unauthenticated_request_is_rejected(self):
        campaign, recipients = self._sending_campaign()
        recipient = self._stuck(recipients[0])
        response = self.client.post(self._url(campaign.pk, recipient.pk), {'status': 'sent'}, format='json')
        self.assertEqual(response.status_code, 401)
        recipient.refresh_from_db()
        self.assertEqual(recipient.status, BlastRecipient.STATUS_SENDING)

    def test_blast_scoped_user_without_admin_scope_is_forbidden(self):
        campaign, recipients = self._sending_campaign()
        recipient = self._stuck(recipients[0])
        blast_user = self._user('blast-only', scopes=['blast'])
        response = self.client.post(
            self._url(campaign.pk, recipient.pk), {'status': 'sent'}, format='json', **self._auth_header(blast_user)
        )
        self.assertEqual(response.status_code, 403)

    def test_unknown_campaign_returns_404(self):
        admin = self._user('admin', scopes=['system administration'])
        response = self.client.post(
            self._url(999999, 1), {'status': 'sent'}, format='json', **self._auth_header(admin)
        )
        self.assertEqual(response.status_code, 404)

    def test_unknown_recipient_returns_404(self):
        admin = self._user('admin', scopes=['system administration'])
        campaign, _recipients = self._sending_campaign()
        response = self.client.post(
            self._url(campaign.pk, 999999), {'status': 'sent'}, format='json', **self._auth_header(admin)
        )
        self.assertEqual(response.status_code, 404)

    def test_recipient_belonging_to_a_different_campaign_returns_404(self):
        admin = self._user('admin', scopes=['system administration'])
        campaign_a, recipients_a = self._sending_campaign()
        campaign_b, _recipients_b = self._sending_campaign()
        recipient = self._stuck(recipients_a[0])
        # recipient belongs to campaign_a, but the URL names campaign_b.
        response = self.client.post(
            self._url(campaign_b.pk, recipient.pk), {'status': 'sent'}, format='json', **self._auth_header(admin)
        )
        self.assertEqual(response.status_code, 404)

    def test_invalid_status_value_is_rejected(self):
        admin = self._user('admin', scopes=['system administration'])
        campaign, recipients = self._sending_campaign()
        recipient = self._stuck(recipients[0])
        response = self.client.post(
            self._url(campaign.pk, recipient.pk), {'status': 'skipped'}, format='json', **self._auth_header(admin)
        )
        self.assertEqual(response.status_code, 400)
        recipient.refresh_from_db()
        self.assertEqual(recipient.status, BlastRecipient.STATUS_SENDING)

    # -- successful recovery ---------------------------------------------------

    def test_admin_can_resolve_a_stuck_recipient_to_sent(self):
        admin = self._user('admin', scopes=['system administration'])
        campaign, recipients = self._sending_campaign(recipient_count=1)
        recipient = self._stuck(recipients[0])

        response = self.client.post(
            self._url(campaign.pk, recipient.pk), {'status': 'sent'}, format='json', **self._auth_header(admin)
        )
        self.assertEqual(response.status_code, 200)
        recipient.refresh_from_db()
        self.assertEqual(recipient.status, BlastRecipient.STATUS_SENT)
        self.assertIsNotNone(recipient.sent_at)
        self.assertEqual(recipient.failure_reason, '')

    def test_admin_can_resolve_a_stuck_recipient_to_failed(self):
        admin = self._user('admin', scopes=['system administration'])
        campaign, recipients = self._sending_campaign(recipient_count=1)
        recipient = self._stuck(recipients[0])

        response = self.client.post(
            self._url(campaign.pk, recipient.pk), {'status': 'failed'}, format='json', **self._auth_header(admin)
        )
        self.assertEqual(response.status_code, 200)
        recipient.refresh_from_db()
        self.assertEqual(recipient.status, BlastRecipient.STATUS_FAILED)
        self.assertIsNone(recipient.sent_at)
        self.assertTrue(recipient.failure_reason)

    def test_resolve_writes_an_audit_log_entry(self):
        admin = self._user('admin', scopes=['system administration'])
        campaign, recipients = self._sending_campaign(recipient_count=1)
        recipient = self._stuck(recipients[0])

        self.client.post(
            self._url(campaign.pk, recipient.pk), {'status': 'sent'}, format='json', **self._auth_header(admin)
        )
        entry = AuditLog.objects.get(action='blast.recipient.resolve')
        self.assertEqual(entry.actor, admin)
        self.assertIn(recipient.destination, entry.target)
        self.assertEqual(entry.result, AuditLog.RESULT_SUCCESS)

    def test_resolve_never_calls_the_bff_client(self):
        # The view module never imports send_blast_message at all, but
        # assert it explicitly against the function tasks.py actually
        # calls, so this stays a real regression guard, not just a
        # structural argument.
        admin = self._user('admin', scopes=['system administration'])
        campaign, recipients = self._sending_campaign(recipient_count=1)
        recipient = self._stuck(recipients[0])

        with mock.patch('apps.blast.tasks.send_blast_message') as mocked:
            response = self.client.post(
                self._url(campaign.pk, recipient.pk), {'status': 'sent'}, format='json', **self._auth_header(admin)
            )
        self.assertEqual(response.status_code, 200)
        mocked.assert_not_called()

    # -- rejection: not currently `sending` (no overwrite) ----------------------

    def test_pending_recipient_cannot_be_resolved(self):
        admin = self._user('admin', scopes=['system administration'])
        campaign, recipients = self._sending_campaign(recipient_count=1)
        recipient = recipients[0]  # still `pending`, never claimed
        self.assertEqual(recipient.status, BlastRecipient.STATUS_PENDING)

        response = self.client.post(
            self._url(campaign.pk, recipient.pk), {'status': 'sent'}, format='json', **self._auth_header(admin)
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error']['code'], 'not_sending')
        recipient.refresh_from_db()
        self.assertEqual(recipient.status, BlastRecipient.STATUS_PENDING)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_already_sent_recipient_cannot_be_overwritten_to_failed(self):
        admin = self._user('admin', scopes=['system administration'])
        campaign, recipients = self._sending_campaign(recipient_count=1)
        BlastRecipient.objects.filter(pk=recipients[0].pk).update(status=BlastRecipient.STATUS_SENT)
        recipient = recipients[0]
        recipient.refresh_from_db()

        response = self.client.post(
            self._url(campaign.pk, recipient.pk), {'status': 'failed'}, format='json', **self._auth_header(admin)
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error']['code'], 'not_sending')
        recipient.refresh_from_db()
        self.assertEqual(recipient.status, BlastRecipient.STATUS_SENT)  # untouched
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_already_failed_recipient_cannot_be_overwritten_to_sent(self):
        admin = self._user('admin', scopes=['system administration'])
        campaign, recipients = self._sending_campaign(recipient_count=1)
        BlastRecipient.objects.filter(pk=recipients[0].pk).update(
            status=BlastRecipient.STATUS_FAILED, failure_reason='This message could not be delivered.',
        )
        recipient = recipients[0]
        recipient.refresh_from_db()

        response = self.client.post(
            self._url(campaign.pk, recipient.pk), {'status': 'sent'}, format='json', **self._auth_header(admin)
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error']['code'], 'not_sending')
        recipient.refresh_from_db()
        self.assertEqual(recipient.status, BlastRecipient.STATUS_FAILED)  # untouched
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_skipped_recipient_cannot_be_overwritten(self):
        admin = self._user('admin', scopes=['system administration'])
        campaign, recipients = self._sending_campaign(recipient_count=1)
        BlastRecipient.objects.filter(pk=recipients[0].pk).update(status=BlastRecipient.STATUS_SKIPPED)
        recipient = recipients[0]
        recipient.refresh_from_db()

        response = self.client.post(
            self._url(campaign.pk, recipient.pk), {'status': 'sent'}, format='json', **self._auth_header(admin)
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error']['code'], 'not_sending')

    # -- concurrency / compare-and-set protection -------------------------------

    def test_concurrent_state_change_is_rejected_without_overwriting(self):
        # Mirrors apps.sync.tests.test_views.SyncCheckpointRecoveryViewTests.
        # test_concurrent_state_change_is_rejected_without_overwriting: force
        # the compare-and-set UPDATE itself to match zero rows (as if the
        # original dispatch task's own completion, or another recovery
        # call, had already changed this exact row between this view's
        # read and its write) and confirm the view reports the conflict
        # instead of writing anything.
        admin = self._user('admin', scopes=['system administration'])
        campaign, recipients = self._sending_campaign(recipient_count=1)
        real_recipient = self._stuck(recipients[0])
        real_updated_at = real_recipient.updated_at

        real_manager_filter = BlastRecipient.objects.filter

        def fake_filter(*args, **kwargs):
            if set(kwargs) == {'pk', 'status', 'updated_at'} and kwargs.get('status') == BlastRecipient.STATUS_SENDING:
                mocked_qs = mock.Mock()
                mocked_qs.update.return_value = 0
                return mocked_qs
            return real_manager_filter(*args, **kwargs)

        with mock.patch('apps.blast.views.BlastRecipient.objects.filter', side_effect=fake_filter):
            response = self.client.post(
                self._url(campaign.pk, real_recipient.pk), {'status': 'sent'}, format='json',
                **self._auth_header(admin),
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error']['code'], 'concurrent_state_change')

        real_recipient.refresh_from_db()
        self.assertEqual(real_recipient.status, BlastRecipient.STATUS_SENDING)  # untouched
        self.assertEqual(real_recipient.updated_at, real_updated_at)  # untouched
        self.assertEqual(AuditLog.objects.count(), 0)

    # -- campaign finalization side effect --------------------------------------

    def test_resolving_the_last_stuck_recipient_completes_the_campaign(self):
        admin = self._user('admin', scopes=['system administration'])
        campaign, recipients = self._sending_campaign(recipient_count=2)
        BlastRecipient.objects.filter(pk=recipients[0].pk).update(status=BlastRecipient.STATUS_SENT)
        stuck = self._stuck(recipients[1])

        response = self.client.post(
            self._url(campaign.pk, stuck.pk), {'status': 'sent'}, format='json', **self._auth_header(admin)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], BlastCampaign.STATUS_COMPLETED)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, BlastCampaign.STATUS_COMPLETED)

    def test_resolving_the_last_stuck_recipient_to_failed_when_all_others_failed_reaches_campaign_failed(self):
        admin = self._user('admin', scopes=['system administration'])
        campaign, recipients = self._sending_campaign(recipient_count=2)
        BlastRecipient.objects.filter(pk=recipients[0].pk).update(status=BlastRecipient.STATUS_FAILED)
        stuck = self._stuck(recipients[1])

        response = self.client.post(
            self._url(campaign.pk, stuck.pk), {'status': 'failed'}, format='json', **self._auth_header(admin)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], BlastCampaign.STATUS_FAILED)
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, BlastCampaign.STATUS_FAILED)

    def test_resolving_a_stuck_recipient_when_others_still_pending_does_not_finalize(self):
        admin = self._user('admin', scopes=['system administration'])
        campaign, recipients = self._sending_campaign(recipient_count=2)
        # recipients[0] left `pending` — still in-flight.
        stuck = self._stuck(recipients[1])

        response = self.client.post(
            self._url(campaign.pk, stuck.pk), {'status': 'sent'}, format='json', **self._auth_header(admin)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], BlastCampaign.STATUS_SENDING)  # still wedged on recipients[0]
        campaign.refresh_from_db()
        self.assertEqual(campaign.status, BlastCampaign.STATUS_SENDING)


class BlastCampaignOfficeIsolationTests(BlastCampaignAPITestCase):
    """Step 4 — BlastCampaign <-> Office integration."""

    def setUp(self):
        super().setUp()
        self.admin_a = self._user('admin_a', scopes=['blast', 'system administration'], office=self.office_a)
        self.operator_a = self._user('operator_a', scopes=['blast'], office=self.office_a)
        self.admin_b = self._user('admin_b', scopes=['blast', 'system administration'], office=self.office_b)
        self.operator_b = self._user('operator_b', scopes=['blast'], office=self.office_b)
        self.campaign_a_id = self._create_campaign(self.operator_a, office=self.office_a).data['id']
        self.campaign_b_id = self._create_campaign(self.operator_b, office=self.office_b).data['id']

    # -- create: Office ownership -------------------------------------------

    def test_new_campaign_belongs_to_creators_own_office(self):
        campaign = BlastCampaign.objects.get(pk=self.campaign_a_id)
        self.assertEqual(campaign.office, self.office_a)

    def test_client_supplied_office_is_ignored_for_a_non_global_user(self):
        # operator_a is a member of office_a only — sending office_b in
        # the request body must NOT move the campaign into office_b.
        response = self._create_campaign(self.operator_a, office=self.office_b)
        self.assertEqual(response.status_code, 201)
        campaign = BlastCampaign.objects.get(pk=response.data['id'])
        self.assertEqual(campaign.office, self.office_a)

    def test_user_without_any_office_cannot_create_a_campaign(self):
        no_office_user = self._user('no-office', scopes=['blast'], office=None)
        response = self._create_campaign(no_office_user)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(BlastCampaign.objects.filter(created_by=no_office_user).exists())

    def test_superadmin_must_specify_an_office_to_create_a_campaign(self):
        superadmin = User.objects.create_superuser('root', 'root@example.com', 'pw')
        response = self._create_campaign(superadmin, office=None)
        self.assertEqual(response.status_code, 400)

    def test_superadmin_can_create_a_campaign_for_any_office(self):
        superadmin = User.objects.create_superuser('root2', 'root2@example.com', 'pw')
        response = self._create_campaign(superadmin, office=self.office_b)
        self.assertEqual(response.status_code, 201)
        campaign = BlastCampaign.objects.get(pk=response.data['id'])
        self.assertEqual(campaign.office, self.office_b)

    # -- list: visibility -----------------------------------------------------

    def test_superadmin_sees_campaigns_from_every_office(self):
        superadmin = User.objects.create_superuser('root3', 'root3@example.com', 'pw')
        response = self.client.get('/api/blast/campaigns/', **self._auth_header(superadmin))
        ids = {c['id'] for c in response.data}
        self.assertIn(self.campaign_a_id, ids)
        self.assertIn(self.campaign_b_id, ids)

    def test_global_admin_sees_campaigns_from_every_office(self):
        global_admin = self._user('gadmin', scopes=['blast', 'system administration'], office=None)
        OfficeMembership.objects.create(
            user=global_admin, office=None, role=_seeded_role(ROLE_GLOBAL_ADMIN), requires_office=False
        )
        response = self.client.get('/api/blast/campaigns/', **self._auth_header(global_admin))
        ids = {c['id'] for c in response.data}
        self.assertIn(self.campaign_a_id, ids)
        self.assertIn(self.campaign_b_id, ids)

    def test_office_admin_a_sees_only_office_a_campaigns(self):
        response = self.client.get('/api/blast/campaigns/', **self._auth_header(self.admin_a))
        ids = {c['id'] for c in response.data}
        self.assertIn(self.campaign_a_id, ids)
        self.assertNotIn(self.campaign_b_id, ids)

    def test_operator_a_sees_only_office_a_campaigns(self):
        response = self.client.get('/api/blast/campaigns/', **self._auth_header(self.operator_a))
        ids = {c['id'] for c in response.data}
        self.assertIn(self.campaign_a_id, ids)
        self.assertNotIn(self.campaign_b_id, ids)

    def test_office_admin_b_and_operator_b_see_only_office_b_campaigns(self):
        for user in (self.admin_b, self.operator_b):
            response = self.client.get('/api/blast/campaigns/', **self._auth_header(user))
            ids = {c['id'] for c in response.data}
            self.assertIn(self.campaign_b_id, ids)
            self.assertNotIn(self.campaign_a_id, ids)

    def test_user_without_any_office_sees_no_office_bound_campaign(self):
        no_office_user = self._user('no-office2', scopes=['blast', 'system administration'], office=None)
        response = self.client.get('/api/blast/campaigns/', **self._auth_header(no_office_user))
        ids = {c['id'] for c in response.data}
        self.assertNotIn(self.campaign_a_id, ids)
        self.assertNotIn(self.campaign_b_id, ids)

    # -- detail: cross-office access denied ------------------------------------

    def test_office_admin_a_cannot_open_office_b_campaign_detail(self):
        response = self.client.get(
            f'/api/blast/campaigns/{self.campaign_b_id}/', **self._auth_header(self.admin_a)
        )
        self.assertEqual(response.status_code, 403)

    def test_operator_a_cannot_open_office_b_campaign_detail(self):
        response = self.client.get(
            f'/api/blast/campaigns/{self.campaign_b_id}/', **self._auth_header(self.operator_a)
        )
        self.assertEqual(response.status_code, 403)

    def test_superadmin_can_open_any_office_campaign_detail(self):
        superadmin = User.objects.create_superuser('root4', 'root4@example.com', 'pw')
        for campaign_id in (self.campaign_a_id, self.campaign_b_id):
            response = self.client.get(
                f'/api/blast/campaigns/{campaign_id}/', **self._auth_header(superadmin)
            )
            self.assertEqual(response.status_code, 200)

    # -- approve/reject: cross-office access denied ----------------------------

    def _submit(self, campaign_id, as_user):
        return self.client.post(f'/api/blast/campaigns/{campaign_id}/submit/', **self._auth_header(as_user))

    def test_admin_a_cannot_approve_office_b_campaign(self):
        self._submit(self.campaign_b_id, self.operator_b)
        response = self.client.post(
            f'/api/blast/campaigns/{self.campaign_b_id}/approve/', **self._auth_header(self.admin_a)
        )
        self.assertEqual(response.status_code, 403)
        campaign = BlastCampaign.objects.get(pk=self.campaign_b_id)
        self.assertEqual(campaign.status, BlastCampaign.STATUS_PENDING_APPROVAL)

    def test_admin_a_cannot_reject_office_b_campaign(self):
        self._submit(self.campaign_b_id, self.operator_b)
        response = self.client.post(
            f'/api/blast/campaigns/{self.campaign_b_id}/reject/', format='json', **self._auth_header(self.admin_a)
        )
        self.assertEqual(response.status_code, 403)

    @mock.patch('apps.blast.views.schedule_blast_campaign_task.delay')
    def test_admin_a_can_approve_office_a_campaign(self, mocked_delay):
        self._submit(self.campaign_a_id, self.operator_a)
        response = self.client.post(
            f'/api/blast/campaigns/{self.campaign_a_id}/approve/', **self._auth_header(self.admin_a)
        )
        self.assertEqual(response.status_code, 200)

    @mock.patch('apps.blast.views.schedule_blast_campaign_task.delay')
    def test_superadmin_self_approval_exception_still_holds_with_an_office(self, mocked_delay):
        superadmin = User.objects.create_superuser('root5', 'root5@example.com', 'pw')
        created = self._create_campaign(superadmin, office=self.office_a)
        self._submit(created.data['id'], superadmin)
        response = self.client.post(
            f'/api/blast/campaigns/{created.data["id"]}/approve/', **self._auth_header(superadmin)
        )
        self.assertEqual(response.status_code, 200)

    def test_non_superadmin_self_approval_still_blocked_with_an_office(self):
        # admin_a both creates and holds approval scope — the existing
        # (Step-4-unrelated) security rule must still hold.
        created = self._create_campaign(self.admin_a, office=self.office_a)
        self._submit(created.data['id'], self.admin_a)
        response = self.client.post(
            f'/api/blast/campaigns/{created.data["id"]}/approve/', **self._auth_header(self.admin_a)
        )
        self.assertEqual(response.status_code, 403)

    # -- Step 7 — explicit role coverage (role != scope) -----------------------
    # Everything above already proves the Office-boundary/self-approval rules
    # hold for an office-scoped scope-holder, but none of `admin_a`/
    # `operator_a`/etc. above ever set `role=` explicitly, so they are all
    # (via `_user()`'s own default) `ROLE_OPERATOR` rows. Blast's own
    # authorization code never branches on office_admin vs operator — both
    # only ever go through `has_global_access`/office-match — so this is
    # not a new code path, only literal proof for the ROLE_OFFICE_ADMIN/
    # ROLE_GLOBAL_ADMIN role values the Step 7 brief names explicitly.

    def test_office_admin_role_cannot_approve_across_office(self):
        office_admin_a = self._user(
            'realofficeadmin_a', scopes=['blast', 'system administration'], office=self.office_a, role=ROLE_OFFICE_ADMIN
        )
        self._submit(self.campaign_b_id, self.operator_b)
        response = self.client.post(
            f'/api/blast/campaigns/{self.campaign_b_id}/approve/', **self._auth_header(office_admin_a)
        )
        self.assertEqual(response.status_code, 403)

    def test_office_admin_role_cannot_self_approve(self):
        office_admin_a = self._user(
            'realofficeadmin_a2', scopes=['blast', 'system administration'], office=self.office_a, role=ROLE_OFFICE_ADMIN
        )
        created = self._create_campaign(office_admin_a, office=self.office_a)
        self._submit(created.data['id'], office_admin_a)
        response = self.client.post(
            f'/api/blast/campaigns/{created.data["id"]}/approve/', **self._auth_header(office_admin_a)
        )
        self.assertEqual(response.status_code, 403)

    def _global_admin(self, username, scopes=()):
        # `_user(office=None)` skips auto-membership entirely (it's the
        # "no membership at all" signal, not "membership with office=
        # None") — a real GLOBAL_ADMIN row is created explicitly here,
        # same pattern as the pre-existing
        # test_global_admin_sees_campaigns_from_every_office above.
        user = self._user(username, scopes=scopes, office=None)
        OfficeMembership.objects.create(
            user=user, office=None, role=_seeded_role(ROLE_GLOBAL_ADMIN), requires_office=False
        )
        return user

    def test_global_admin_can_create_a_campaign_for_any_office(self):
        global_admin = self._global_admin('gadmin2', scopes=['blast'])
        response = self._create_campaign(global_admin, office=self.office_b)
        self.assertEqual(response.status_code, 201)
        campaign = BlastCampaign.objects.get(pk=response.data['id'])
        self.assertEqual(campaign.office, self.office_b)

    def test_global_admin_cannot_self_approve(self):
        global_admin = self._global_admin('gadmin3', scopes=['blast', 'system administration'])
        created = self._create_campaign(global_admin, office=self.office_a)
        self._submit(created.data['id'], global_admin)
        response = self.client.post(
            f'/api/blast/campaigns/{created.data["id"]}/approve/', **self._auth_header(global_admin)
        )
        self.assertEqual(response.status_code, 403)

    @mock.patch('apps.blast.views.schedule_blast_campaign_task.delay')
    def test_global_admin_can_approve_another_users_campaign_with_scope(self, mocked_delay):
        global_admin = self._global_admin('gadmin4', scopes=['blast', 'system administration'])
        self._submit(self.campaign_a_id, self.operator_a)
        response = self.client.post(
            f'/api/blast/campaigns/{self.campaign_a_id}/approve/', **self._auth_header(global_admin)
        )
        self.assertEqual(response.status_code, 200)


class BlastRoleWithoutSystemAdministrationScopeTests(BlastCampaignOfficeIsolationTests):
    """Step 8 (Role x Scope alignment) — proves Blast approve/reject now
    come from `HasOfficeAdminAccess` (organizational role), not the
    `system administration` Group/scope: every admin user here explicitly
    has NO `system administration` Group at all. Reuses
    `BlastCampaignOfficeIsolationTests`'s office_a/office_b/campaign_a_id/
    campaign_b_id/operator_a/operator_b fixtures."""

    @mock.patch('apps.blast.views.schedule_blast_campaign_task.delay')
    def test_office_admin_role_without_scope_can_approve_own_office_campaign(self, mocked_delay):
        office_admin_a = self._user(
            'roleonly_admin_a', scopes=['blast'], office=self.office_a, role=ROLE_OFFICE_ADMIN
        )
        self._submit(self.campaign_a_id, self.operator_a)
        response = self.client.post(
            f'/api/blast/campaigns/{self.campaign_a_id}/approve/', **self._auth_header(office_admin_a)
        )
        self.assertEqual(response.status_code, 200)

    def test_office_admin_role_without_scope_can_reject_own_office_campaign(self):
        office_admin_a = self._user(
            'roleonly_admin_a2', scopes=['blast'], office=self.office_a, role=ROLE_OFFICE_ADMIN
        )
        self._submit(self.campaign_a_id, self.operator_a)
        response = self.client.post(
            f'/api/blast/campaigns/{self.campaign_a_id}/reject/', format='json', **self._auth_header(office_admin_a)
        )
        self.assertEqual(response.status_code, 200)

    def test_office_admin_role_without_scope_cannot_approve_other_office_campaign(self):
        office_admin_a = self._user(
            'roleonly_admin_a3', scopes=['blast'], office=self.office_a, role=ROLE_OFFICE_ADMIN
        )
        self._submit(self.campaign_b_id, self.operator_b)
        response = self.client.post(
            f'/api/blast/campaigns/{self.campaign_b_id}/approve/', **self._auth_header(office_admin_a)
        )
        self.assertEqual(response.status_code, 403)

    def test_office_admin_role_without_scope_still_cannot_self_approve(self):
        office_admin_a = self._user(
            'roleonly_admin_a4', scopes=['blast'], office=self.office_a, role=ROLE_OFFICE_ADMIN
        )
        created = self._create_campaign(office_admin_a, office=self.office_a)
        self._submit(created.data['id'], office_admin_a)
        response = self.client.post(
            f'/api/blast/campaigns/{created.data["id"]}/approve/', **self._auth_header(office_admin_a)
        )
        self.assertEqual(response.status_code, 403)

    @mock.patch('apps.blast.views.schedule_blast_campaign_task.delay')
    def test_global_admin_role_without_scope_can_approve_any_office_campaign(self, mocked_delay):
        global_admin = self._global_admin('roleonly_gadmin', scopes=['blast'])
        self._submit(self.campaign_b_id, self.operator_b)
        response = self.client.post(
            f'/api/blast/campaigns/{self.campaign_b_id}/approve/', **self._auth_header(global_admin)
        )
        self.assertEqual(response.status_code, 200)

    def test_operator_role_cannot_approve_even_within_own_office(self):
        # Operator is an Office role, but not an ADMINISTRATIVE one —
        # HasOfficeAdminAccess must exclude it (unlike HasOfficeAccess for
        # Inbox, which deliberately includes Operator).
        self._submit(self.campaign_a_id, self.operator_a)
        response = self.client.post(
            f'/api/blast/campaigns/{self.campaign_a_id}/approve/', **self._auth_header(self.operator_a)
        )
        self.assertEqual(response.status_code, 403)

    def test_office_admin_role_without_scope_still_cannot_recover_stuck_recipient(self):
        # BlastRecipientResolveView deliberately was NOT touched in Step 8
        # (out of scope — only approve/reject were named) — still
        # `HasSystemAdministrationScope`-only, so a role-only Office Admin
        # must still be denied here.
        office_admin_a = self._user(
            'roleonly_admin_a5', scopes=['blast'], office=self.office_a, role=ROLE_OFFICE_ADMIN
        )
        response = self.client.post(
            f'/api/blast/campaigns/{self.campaign_a_id}/recipients/999999/resolve/',
            {'status': 'sent'}, format='json', **self._auth_header(office_admin_a),
        )
        self.assertEqual(response.status_code, 403)
