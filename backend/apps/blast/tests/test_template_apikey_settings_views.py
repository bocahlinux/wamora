from django.contrib.auth.models import Group, User
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.blast.models import BlastApiKey, BlastSettings, BlastTemplate
from apps.offices.models import ROLE_GLOBAL_ADMIN, ROLE_OPERATOR, Office, OfficeMembership, Role
from apps.waha_sessions.models import WahaSession

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()


def _seeded_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'grants_global_access': name == ROLE_GLOBAL_ADMIN},
    )
    return role


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM, JWT_PUBLIC_KEY=PUBLIC_PEM, JWT_ISSUER='test-issuer', JWT_AUDIENCE='test-audience',
)
class _BaseTestCase(APITestCase):
    def setUp(self):
        self.office = Office.objects.create(name='Office A')
        self.session = WahaSession.objects.create(name='primary', office=self.office)

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


class BlastTemplateViewTests(_BaseTestCase):
    """Discussed requirement — Templates are Superadmin/Global-Admin-only
    (`has_global_access`), full stop: an Office Admin/Operator can no
    longer read, create, or edit a template at all, regardless of the
    'blast'/'system administration' scope they hold for Campaigns."""

    URL = '/api/blast/templates/'

    def test_office_scoped_user_with_blast_scope_is_forbidden_from_listing(self):
        self._user('creator', scopes=['blast'], office=self.office)
        office_admin = self._user('office_admin', scopes=['blast', 'system administration'], office=self.office)
        response = self.client.get(self.URL, **self._auth(office_admin))
        self.assertEqual(response.status_code, 403)

    def test_office_scoped_user_is_forbidden_from_creating(self):
        user = self._user('creator', scopes=['blast'], office=self.office)
        response = self.client.post(
            self.URL, {'key': 'pajak', 'name': 'Pajak', 'content': 'Halo {{nama}}'}, format='json', **self._auth(user),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(BlastTemplate.objects.filter(key='pajak').exists())

    def test_global_admin_may_create_a_template_without_needing_the_blast_scope(self):
        # Gated purely on has_global_access now — no scope requirement at
        # all, unlike BlastCampaignListCreateView's POST (which still
        # requires 'blast' specifically).
        user = self._user('gadmin', scopes=[], office=None, role=ROLE_GLOBAL_ADMIN)
        response = self.client.post(
            self.URL, {'key': 'global-tpl', 'name': 'Global', 'content': 'Halo {{nama}}'}, format='json', **self._auth(user),
        )
        self.assertEqual(response.status_code, 201, response.data)
        template = BlastTemplate.objects.get(key='global-tpl')
        self.assertIsNone(template.office_id)

    def test_global_admin_sees_every_template_across_every_office(self):
        other_office = Office.objects.create(name='Office B')
        creator = self._user('creator2', office=None, role=ROLE_GLOBAL_ADMIN)
        mine = BlastTemplate.objects.create(key='mine', name='Mine', content='Hi {{a}}', office=self.office, created_by=creator)
        theirs = BlastTemplate.objects.create(key='theirs', name='Theirs', content='Hi {{a}}', office=other_office, created_by=creator)
        glob = BlastTemplate.objects.create(key='shared', name='Shared', content='Hi {{a}}', office=None, created_by=creator)

        response = self.client.get(self.URL, **self._auth(creator))
        keys = {row['key'] for row in response.data}
        self.assertEqual(keys, {mine.key, theirs.key, glob.key})

    def test_office_scoped_user_is_forbidden_from_reading_or_editing_a_single_template(self):
        gadmin = self._user('gadmin2', office=None, role=ROLE_GLOBAL_ADMIN)
        template = BlastTemplate.objects.create(key='fixed-key', name='X', content='Hi {{a}}', office=self.office, created_by=gadmin)
        office_admin = self._user('office_admin2', scopes=['blast'], office=self.office)

        get_response = self.client.get(f'{self.URL}{template.pk}/', **self._auth(office_admin))
        self.assertEqual(get_response.status_code, 403)
        patch_response = self.client.patch(
            f'{self.URL}{template.pk}/', {'name': 'Renamed'}, format='json', **self._auth(office_admin),
        )
        self.assertEqual(patch_response.status_code, 403)

    def test_key_is_never_editable_via_patch(self):
        gadmin = self._user('gadmin3', office=None, role=ROLE_GLOBAL_ADMIN)
        template = BlastTemplate.objects.create(key='fixed-key2', name='X', content='Hi {{a}}', office=self.office, created_by=gadmin)
        response = self.client.patch(
            f'{self.URL}{template.pk}/', {'key': 'attempted-rename', 'name': 'Renamed'}, format='json', **self._auth(gadmin),
        )
        self.assertEqual(response.status_code, 200, response.data)
        template.refresh_from_db()
        self.assertEqual(template.key, 'fixed-key2')
        self.assertEqual(template.name, 'Renamed')


class BlastApiKeyViewTests(_BaseTestCase):
    URL = '/api/blast/api-keys/'

    def test_office_scoped_user_is_forbidden(self):
        user = self._user('op', scopes=['blast'], office=self.office)
        response = self.client.get(self.URL, **self._auth(user))
        self.assertEqual(response.status_code, 403)

    def test_global_admin_creates_a_key_and_sees_the_raw_key_exactly_once(self):
        # Discussed requirement — a key is global, no Office at all.
        admin = self._user('gadmin2', office=None, role=ROLE_GLOBAL_ADMIN)
        response = self.client.post(self.URL, {'name': 'Tax system'}, format='json', **self._auth(admin))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('raw_key', response.data)
        self.assertNotIn('office', response.data)

        list_response = self.client.get(self.URL, **self._auth(admin))
        self.assertEqual(list_response.status_code, 200)
        self.assertNotIn('raw_key', list_response.data[0])
        self.assertNotIn('office', list_response.data[0])

    def test_revoke_sets_inactive_never_deletes(self):
        admin = self._user('gadmin3', office=None, role=ROLE_GLOBAL_ADMIN)
        key, _raw = BlastApiKey.create_with_raw_key(name='X', created_by=admin)
        response = self.client.post(f'{self.URL}{key.pk}/revoke/', **self._auth(admin))
        self.assertEqual(response.status_code, 204)
        key.refresh_from_db()
        self.assertFalse(key.is_active)


class BlastSettingsViewTests(_BaseTestCase):
    URL = '/api/blast/settings/'

    def test_office_scoped_user_is_forbidden(self):
        user = self._user('op2', scopes=['blast'], office=self.office)
        response = self.client.get(self.URL, **self._auth(user))
        self.assertEqual(response.status_code, 403)

    def test_default_delay_is_60_seconds(self):
        admin = self._user('gadmin4', office=None, role=ROLE_GLOBAL_ADMIN)
        response = self.client.get(self.URL, **self._auth(admin))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['inter_message_delay_seconds'], 60)

    def test_global_admin_can_update_the_delay(self):
        admin = self._user('gadmin5', office=None, role=ROLE_GLOBAL_ADMIN)
        response = self.client.patch(self.URL, {'inter_message_delay_seconds': 90}, format='json', **self._auth(admin))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(BlastSettings.objects.get(pk=1).inter_message_delay_seconds, 90)

    def test_negative_delay_is_rejected(self):
        admin = self._user('gadmin6', office=None, role=ROLE_GLOBAL_ADMIN)
        response = self.client.patch(self.URL, {'inter_message_delay_seconds': -1}, format='json', **self._auth(admin))
        self.assertEqual(response.status_code, 400)
