from django.contrib.auth.models import Group, User
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.blast.models import BlastCampaign, BlastRecipient
from apps.offices.models import ROLE_GLOBAL_ADMIN, ROLE_OPERATOR, Office, OfficeMembership, Role
from apps.waha_sessions.models import WahaSession

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()


def _seeded_role(name):
    role, _ = Role.objects.get_or_create(name=name, defaults={'grants_global_access': name == ROLE_GLOBAL_ADMIN})
    return role


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM, JWT_PUBLIC_KEY=PUBLIC_PEM, JWT_ISSUER='test-issuer', JWT_AUDIENCE='test-audience',
)
class BlastHistoryViewOfficeIsolationTests(APITestCase):
    """Discussed requirement — an Office Admin/Operator may only see
    Blast History rows for their OWN Office, never another Office's.
    `BlastHistoryView` reuses `campaigns_visible_to` (the same Office
    boundary Campaigns already enforces) rather than a second
    implementation, so this is really a regression test for that reuse,
    not a new access-control mechanism."""

    URL = '/api/blast/history/'

    def setUp(self):
        self.office_a = Office.objects.create(name='Office A')
        self.office_b = Office.objects.create(name='Office B')
        self.session_a = WahaSession.objects.create(name='session-a', office=self.office_a)
        self.session_b = WahaSession.objects.create(name='session-b', office=self.office_b)
        self.creator = User.objects.create_user('creator', password='pw')

        self.campaign_a = BlastCampaign.objects.create(
            session=self.session_a, office=self.office_a, name='Campaign A', message_template='hi',
            created_by=self.creator, status=BlastCampaign.STATUS_COMPLETED,
        )
        self.recipient_a = BlastRecipient.objects.create(
            campaign=self.campaign_a, destination='+62800000001', status=BlastRecipient.STATUS_SENT,
        )
        self.campaign_b = BlastCampaign.objects.create(
            session=self.session_b, office=self.office_b, name='Campaign B', message_template='hi',
            created_by=self.creator, status=BlastCampaign.STATUS_COMPLETED,
        )
        self.recipient_b = BlastRecipient.objects.create(
            campaign=self.campaign_b, destination='+62800000002', status=BlastRecipient.STATUS_SENT,
        )

    def _user(self, username, scopes=(), office=None, role=ROLE_OPERATOR):
        user = User.objects.create_user(username, password='pw')
        for scope in scopes:
            group, _ = Group.objects.get_or_create(name=scope)
            user.groups.add(group)
        if office is not None or role == ROLE_GLOBAL_ADMIN:
            role_obj = _seeded_role(role)
            OfficeMembership.objects.create(
                user=user, office=office, role=role_obj, requires_office=not role_obj.grants_global_access,
            )
        return user

    def _auth(self, user):
        token = issue_access_token(user)['access_token']
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def test_office_admin_sees_only_their_own_offices_history(self):
        admin_a = self._user('admin_a', scopes=['blast'], office=self.office_a)
        response = self.client.get(self.URL, **self._auth(admin_a))
        self.assertEqual(response.status_code, 200)
        destinations = {row['destination'] for row in response.data['results']}
        self.assertIn(self.recipient_a.destination, destinations)
        self.assertNotIn(self.recipient_b.destination, destinations)

    def test_operator_sees_only_their_own_offices_history(self):
        operator_b = self._user('operator_b', scopes=['blast'], office=self.office_b)
        response = self.client.get(self.URL, **self._auth(operator_b))
        destinations = {row['destination'] for row in response.data['results']}
        self.assertIn(self.recipient_b.destination, destinations)
        self.assertNotIn(self.recipient_a.destination, destinations)

    def test_office_query_param_cannot_bypass_an_office_scoped_users_own_boundary(self):
        admin_a = self._user('admin_a2', scopes=['blast'], office=self.office_a)
        response = self.client.get(f'{self.URL}?office={self.office_b.pk}', **self._auth(admin_a))
        destinations = {row['destination'] for row in response.data['results']}
        self.assertNotIn(self.recipient_b.destination, destinations)

    def test_globally_accessing_user_sees_every_offices_history(self):
        gadmin = self._user('gadmin', office=None, role=ROLE_GLOBAL_ADMIN)
        response = self.client.get(self.URL, **self._auth(gadmin))
        destinations = {row['destination'] for row in response.data['results']}
        self.assertIn(self.recipient_a.destination, destinations)
        self.assertIn(self.recipient_b.destination, destinations)

    def test_globally_accessing_user_can_filter_by_office(self):
        gadmin = self._user('gadmin2', office=None, role=ROLE_GLOBAL_ADMIN)
        response = self.client.get(f'{self.URL}?office={self.office_a.pk}', **self._auth(gadmin))
        destinations = {row['destination'] for row in response.data['results']}
        self.assertEqual(destinations, {self.recipient_a.destination})
