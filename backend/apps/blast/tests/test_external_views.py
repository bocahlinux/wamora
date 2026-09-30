from unittest import mock

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from apps.blast.models import BlastApiKey, BlastCampaign, BlastTemplate
from apps.offices.models import Office
from apps.waha_sessions.models import WahaSession

URL = '/api/external/blast/send/'


class ExternalBlastSendViewTests(APITestCase):
    """Discussed requirement — `BlastApiKey` is global (no Office of its
    own): one key must work for a single ad-hoc message, a freeform
    blast, or a templated blast, across ANY session/Office named in the
    request body — never restricted by anything on the key itself."""

    def setUp(self):
        self.office = Office.objects.create(name='Office A')
        self.session = WahaSession.objects.create(name='primary', office=self.office)
        self.creator = User.objects.create_user('creator', password='pw')
        self.template = BlastTemplate.objects.create(
            key='pajak-jatuh-tempo', name='Pajak Jatuh Tempo',
            content='Yth, {{nama_wp}} Nopol {{nopol}}', created_by=self.creator,
        )
        # Global key — no office at all, per the Discussed requirement.
        self.key, self.raw_key = BlastApiKey.create_with_raw_key(name='Tax system', created_by=self.creator)

    def _headers(self, api_key=None, idempotency_key='idem-1'):
        headers = {}
        if api_key is not None:
            headers['HTTP_X_API_KEY'] = api_key
        if idempotency_key is not None:
            headers['HTTP_IDEMPOTENCY_KEY'] = idempotency_key
        return headers

    def _body(self, **overrides):
        body = {
            'session': self.session.name,
            'template_key': self.template.key,
            'recipients': [{'destination': '+6280000000001', 'variables': {'nama_wp': 'Anto', 'nopol': 'KH1234AA'}}],
        }
        body.update(overrides)
        return body

    def test_missing_api_key_is_rejected(self):
        response = self.client.post(URL, self._body(), format='json', **self._headers(api_key=None))
        self.assertEqual(response.status_code, 401)

    def test_wrong_api_key_is_rejected(self):
        response = self.client.post(URL, self._body(), format='json', **self._headers(api_key='not-a-real-key'))
        self.assertEqual(response.status_code, 401)

    def test_revoked_api_key_is_rejected(self):
        BlastApiKey.objects.filter(pk=self.key.pk).update(is_active=False)
        response = self.client.post(URL, self._body(), format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 401)

    def test_missing_idempotency_key_header_is_rejected(self):
        response = self.client.post(
            URL, self._body(), format='json', **self._headers(api_key=self.raw_key, idempotency_key=None)
        )
        self.assertEqual(response.status_code, 400)

    def test_missing_session_is_rejected(self):
        body = self._body()
        del body['session']
        response = self.client.post(URL, body, format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 400)

    def test_unknown_session_is_rejected(self):
        response = self.client.post(URL, self._body(session='does-not-exist'), format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 404)

    def test_giving_both_template_key_and_message_template_is_rejected(self):
        body = self._body(message_template='freeform text')
        response = self.client.post(URL, body, format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 400)

    def test_giving_neither_template_key_nor_message_template_is_rejected(self):
        body = self._body()
        del body['template_key']
        response = self.client.post(URL, body, format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 400)

    @mock.patch('apps.blast.external_views.schedule_blast_campaign_task.delay')
    def test_valid_templated_request_creates_an_approved_campaign_and_schedules_it(self, mocked_schedule):
        response = self.client.post(URL, self._body(), format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['status'], BlastCampaign.STATUS_APPROVED)
        self.assertEqual(response.data['recipient_count'], 1)

        campaign = BlastCampaign.objects.get(pk=response.data['campaign_id'])
        self.assertEqual(campaign.status, BlastCampaign.STATUS_APPROVED)
        self.assertIsNone(campaign.approved_by)
        self.assertIsNotNone(campaign.approved_at)
        self.assertEqual(campaign.triggered_by_api_key_id, self.key.pk)
        self.assertEqual(campaign.template_id, self.template.pk)
        self.assertEqual(campaign.message_template, self.template.content)
        # office is derived from the SESSION, not from the (now global) key.
        self.assertEqual(campaign.office_id, self.office.pk)
        recipient = campaign.recipients.get(destination='+6280000000001')
        self.assertEqual(recipient.variables, {'nama_wp': 'Anto', 'nopol': 'KH1234AA'})
        mocked_schedule.assert_called_once_with(campaign.pk)

        self.key.refresh_from_db()
        self.assertIsNotNone(self.key.last_used_at)

    @mock.patch('apps.blast.external_views.schedule_blast_campaign_task.delay')
    def test_single_recipient_freeform_request_is_how_an_ad_hoc_message_is_sent(self, mocked_schedule):
        # Discussed requirement — "kirim pesan biasa" is not a separate
        # code path: a one-recipient freeform request IS the ad-hoc
        # single-message send.
        body = {'session': self.session.name, 'message_template': 'Halo, ini pesan biasa.', 'recipients': ['+6280000000009']}
        response = self.client.post(URL, body, format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 201, response.data)
        campaign = BlastCampaign.objects.get(pk=response.data['campaign_id'])
        self.assertIsNone(campaign.template_id)
        self.assertEqual(campaign.message_template, 'Halo, ini pesan biasa.')
        self.assertEqual(campaign.recipients.count(), 1)
        mocked_schedule.assert_called_once()

    @mock.patch('apps.blast.external_views.schedule_blast_campaign_task.delay')
    def test_freeform_multi_recipient_blast(self, mocked_schedule):
        body = {
            'session': self.session.name, 'message_template': 'Promo blast',
            'recipients': ['+62800001', '+62800002', '+62800003'],
        }
        response = self.client.post(URL, body, format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 201, response.data)
        campaign = BlastCampaign.objects.get(pk=response.data['campaign_id'])
        self.assertEqual(campaign.recipients.count(), 3)
        self.assertTrue(all(r.variables == {} for r in campaign.recipients.all()))

    def test_freeform_request_ignores_extraneous_variables_without_error(self):
        body = {
            'session': self.session.name, 'message_template': 'Halo',
            'recipients': [{'destination': '+62800001', 'variables': {'unexpected': 'value'}}],
        }
        response = self.client.post(URL, body, format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 201, response.data)

    @mock.patch('apps.blast.external_views.schedule_blast_campaign_task.delay')
    def test_the_same_global_key_works_across_different_offices_and_sessions(self, mocked_schedule):
        other_office = Office.objects.create(name='Office B')
        other_session = WahaSession.objects.create(name='secondary', office=other_office)

        r1 = self.client.post(
            URL, {'session': self.session.name, 'message_template': 'a', 'recipients': ['+62800001']},
            format='json', **self._headers(api_key=self.raw_key, idempotency_key='multi-1'),
        )
        r2 = self.client.post(
            URL, {'session': other_session.name, 'message_template': 'b', 'recipients': ['+62800002']},
            format='json', **self._headers(api_key=self.raw_key, idempotency_key='multi-2'),
        )
        self.assertEqual(r1.status_code, 201, r1.data)
        self.assertEqual(r2.status_code, 201, r2.data)
        c1 = BlastCampaign.objects.get(pk=r1.data['campaign_id'])
        c2 = BlastCampaign.objects.get(pk=r2.data['campaign_id'])
        self.assertEqual(c1.office_id, self.office.pk)
        self.assertEqual(c2.office_id, other_office.pk)

    @mock.patch('apps.blast.external_views.schedule_blast_campaign_task.delay')
    def test_repeated_idempotency_key_returns_the_same_campaign_not_a_second_one(self, mocked_schedule):
        first = self.client.post(URL, self._body(), format='json', **self._headers(api_key=self.raw_key, idempotency_key='dup-1'))
        second = self.client.post(URL, self._body(), format='json', **self._headers(api_key=self.raw_key, idempotency_key='dup-1'))

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data['campaign_id'], second.data['campaign_id'])
        self.assertEqual(BlastCampaign.objects.filter(triggered_by_api_key=self.key).count(), 1)
        mocked_schedule.assert_called_once()

    def test_missing_variable_on_a_recipient_rejects_the_whole_request(self):
        body = self._body(recipients=[{'destination': '+6280000000001', 'variables': {'nama_wp': 'Anto'}}])
        response = self.client.post(URL, body, format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(BlastCampaign.objects.count(), 0)

    def test_unknown_template_key_is_rejected(self):
        body = self._body(template_key='does-not-exist')
        response = self.client.post(URL, body, format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 404)

    def test_a_template_scoped_to_a_different_offices_session_is_not_usable(self):
        other_office = Office.objects.create(name='Office B')
        other_session = WahaSession.objects.create(name='secondary', office=other_office)
        private_template = BlastTemplate.objects.create(
            key='private-tpl', name='Private', content='Halo {{nama}}', office=other_office, created_by=self.creator,
        )
        # Requesting against `self.session` (Office A) with a template
        # scoped to Office B — template resolution is by the SESSION's
        # own office, so this must not resolve.
        body = self._body(template_key=private_template.key, recipients=[{'destination': '+62800001', 'variables': {'nama': 'X'}}])
        response = self.client.post(URL, body, format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 404)

        # The SAME template DOES resolve when the request targets Office
        # B's own session — with the SAME global key.
        body2 = self._body(
            session=other_session.name, template_key=private_template.key,
            recipients=[{'destination': '+62800001', 'variables': {'nama': 'X'}}],
        )
        with mock.patch('apps.blast.external_views.schedule_blast_campaign_task.delay'):
            response2 = self.client.post(URL, body2, format='json', **self._headers(api_key=self.raw_key, idempotency_key='idem-2'))
        self.assertEqual(response2.status_code, 201, response2.data)

    @mock.patch('apps.blast.external_views.schedule_blast_campaign_task.delay')
    def test_a_key_may_use_a_global_template(self, mocked_schedule):
        global_template = BlastTemplate.objects.create(
            key='global-tpl', name='Global', content='Halo {{nama}}', office=None, created_by=self.creator,
        )
        body = self._body(template_key=global_template.key, recipients=[{'destination': '+62800001', 'variables': {'nama': 'X'}}])
        response = self.client.post(URL, body, format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 201, response.data)

    @mock.patch('apps.blast.external_views.remaining_daily_budget', return_value=0)
    def test_exceeding_the_daily_budget_is_rejected(self, mocked_budget):
        response = self.client.post(URL, self._body(), format='json', **self._headers(api_key=self.raw_key))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(BlastCampaign.objects.count(), 0)
