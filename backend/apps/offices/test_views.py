"""Office & User management API tests — Step 6.

Same conventions as `apps.blast.tests.test_views`: `override_settings`
for ephemeral JWT test keys, a `_user()` helper that wires up both the
technical scope axis (Django `Group` -> JWT `scopes`, via
`apps.authn.jwt_utils.compute_scopes()`) and the organizational axis
(`OfficeMembership.role`/`office`) — the two Step 2 established as
independent.
"""

from django.contrib.auth.models import Group, User
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.blast.models import BlastCampaign
from apps.offices.models import ROLE_GLOBAL_ADMIN, ROLE_OFFICE_ADMIN, ROLE_OPERATOR, Office, OfficeMembership
from apps.waha_sessions.models import WahaSession

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()

ADMIN_SCOPE = 'user administration'
BLAST_SCOPE = 'blast'


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
)
class OfficesUsersApiTestCase(APITestCase):
    def setUp(self):
        self.office_a = Office.objects.create(name='Office A')
        self.office_b = Office.objects.create(name='Office B')

    def _user(self, username, scopes=(), office=None, role=None, superuser=False):
        if superuser:
            user = User.objects.create_superuser(username, f'{username}@example.com', 'pw')
        else:
            user = User.objects.create_user(username, password='pw')
        for scope in scopes:
            group, _ = Group.objects.get_or_create(name=scope)
            user.groups.add(group)
        if role is not None:
            OfficeMembership.objects.create(user=user, office=office, role=role)
        return user

    def _auth_header(self, user):
        token = issue_access_token(user)['access_token']
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def _superadmin(self, username='superadmin'):
        return self._user(username, superuser=True)

    def _global_admin(self, username='globaladmin'):
        return self._user(username, scopes=[ADMIN_SCOPE], role=ROLE_GLOBAL_ADMIN)

    def _office_admin(self, username, office):
        return self._user(username, scopes=[ADMIN_SCOPE], office=office, role=ROLE_OFFICE_ADMIN)

    def _operator(self, username, office):
        return self._user(username, office=office, role=ROLE_OPERATOR)


# --- OFFICE ------------------------------------------------------------

class OfficeManagementApiTests(OfficesUsersApiTestCase):
    def test_superadmin_can_create_office(self):
        actor = self._superadmin()
        response = self.client.post('/api/offices/', {'name': 'Samsat Sampit'}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Office.objects.filter(name='Samsat Sampit').exists())

    def test_global_admin_can_create_office(self):
        actor = self._global_admin()
        response = self.client.post('/api/offices/', {'name': 'Samsat Kasongan'}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 201)

    def test_office_admin_cannot_create_office(self):
        actor = self._office_admin('officeadmin_a', self.office_a)
        response = self.client.post('/api/offices/', {'name': 'Samsat Baru'}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Office.objects.filter(name='Samsat Baru').exists())

    def test_office_admin_cannot_list_offices(self):
        actor = self._office_admin('officeadmin_a', self.office_a)
        response = self.client.get('/api/offices/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_operator_cannot_create_office(self):
        actor = self._operator('operator_a', self.office_a)
        response = self.client.post('/api/offices/', {'name': 'Samsat X'}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_office_name_must_be_unique(self):
        actor = self._superadmin()
        response = self.client.post('/api/offices/', {'name': 'Office A'}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 400)

    def test_superadmin_can_deactivate_an_office(self):
        actor = self._superadmin()
        response = self.client.patch(
            f'/api/offices/{self.office_a.pk}/', {'is_active': False}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 200)
        self.office_a.refresh_from_db()
        self.assertFalse(self.office_a.is_active)

    def test_inactive_office_cannot_be_selected_for_a_new_blast_campaign(self):
        actor = self._superadmin()
        self.office_a.is_active = False
        self.office_a.save()
        session = WahaSession.objects.create(name='primary')
        response = self.client.post(
            '/api/blast/campaigns/',
            {
                'session': session.name,
                'name': 'Promo',
                'message_template': 'Hello',
                'recipients': ['+628000000001'],
                'office': self.office_a.pk,
            },
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(BlastCampaign.objects.exists())

    def test_inactive_office_blocks_creation_even_for_its_own_office_admin(self):
        self.office_a.is_active = False
        self.office_a.save()
        actor = self._office_admin('officeadmin_a', self.office_a)
        group, _ = Group.objects.get_or_create(name=BLAST_SCOPE)
        actor.groups.add(group)
        session = WahaSession.objects.create(name='primary')
        response = self.client.post(
            '/api/blast/campaigns/',
            {'session': session.name, 'name': 'Promo', 'message_template': 'Hello', 'recipients': ['+628000000001']},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 400)


# --- USER ---------------------------------------------------------------

class UserManagementApiTests(OfficesUsersApiTestCase):
    def _create_payload(self, **overrides):
        payload = {
            'username': 'newuser',
            'password': 'a-strong-password',
            'role': ROLE_OPERATOR,
            'office': self.office_a.pk,
        }
        payload.update(overrides)
        return payload

    def test_superadmin_can_create_user(self):
        actor = self._superadmin()
        response = self.client.post('/api/users/', self._create_payload(), format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_global_admin_can_create_user(self):
        actor = self._global_admin()
        response = self.client.post('/api/users/', self._create_payload(), format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 201)

    def test_created_user_password_is_hashed_never_plaintext(self):
        actor = self._superadmin()
        self.client.post('/api/users/', self._create_payload(), format='json', **self._auth_header(actor))
        created = User.objects.get(username='newuser')
        self.assertNotEqual(created.password, 'a-strong-password')
        self.assertTrue(created.check_password('a-strong-password'))

    def test_cannot_create_a_superuser_via_this_api(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/users/', self._create_payload(is_superuser=True), format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username='newuser')
        self.assertFalse(created.is_superuser)

    def test_office_admin_can_create_user_in_own_office(self):
        actor = self._office_admin('officeadmin_a', self.office_a)
        response = self.client.post(
            '/api/users/', self._create_payload(username='operator_new'), format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 201)
        membership = OfficeMembership.objects.get(user__username='operator_new')
        self.assertEqual(membership.office, self.office_a)

    def test_office_admin_cannot_place_new_user_in_another_office(self):
        actor = self._office_admin('officeadmin_a', self.office_a)
        response = self.client.post(
            '/api/users/',
            self._create_payload(username='operator_new', office=self.office_b.pk),
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 201)
        # Client-supplied Office B is ignored/overwritten — same
        # "never trust client-supplied Office" discipline as Blast.
        membership = OfficeMembership.objects.get(user__username='operator_new')
        self.assertEqual(membership.office, self.office_a)

    def test_office_admin_cannot_create_a_global_admin(self):
        actor = self._office_admin('officeadmin_a', self.office_a)
        response = self.client.post(
            '/api/users/',
            self._create_payload(username='sneaky', role=ROLE_GLOBAL_ADMIN, office=None),
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username='sneaky').exists())

    def test_operator_cannot_create_user(self):
        actor = self._operator('operator_a', self.office_a)
        response = self.client.post('/api/users/', self._create_payload(), format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_operator_cannot_list_users(self):
        actor = self._operator('operator_a', self.office_a)
        response = self.client.get('/api/users/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_office_admin_role_requires_an_office(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/users/',
            self._create_payload(role=ROLE_OFFICE_ADMIN, office=None),
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 400)

    def test_global_admin_role_rejects_an_office(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/users/',
            self._create_payload(role=ROLE_GLOBAL_ADMIN, office=self.office_a.pk),
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 400)

    def test_office_admin_sees_only_own_office_users_on_list(self):
        self._office_admin('officeadmin_a', self.office_a)
        self._operator('operator_a', self.office_a)
        self._operator('operator_b', self.office_b)
        actor = self._office_admin('officeadmin_a2', self.office_a)
        response = self.client.get('/api/users/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)
        usernames = {row['username'] for row in response.data}
        self.assertIn('operator_a', usernames)
        self.assertNotIn('operator_b', usernames)

    def test_office_admin_cannot_view_another_offices_user_detail(self):
        target = self._operator('operator_b', self.office_b)
        actor = self._office_admin('officeadmin_a', self.office_a)
        response = self.client.get(f'/api/users/{target.pk}/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_office_admin_cannot_update_another_offices_user(self):
        target = self._operator('operator_b', self.office_b)
        actor = self._office_admin('officeadmin_a', self.office_a)
        response = self.client.patch(
            f'/api/users/{target.pk}/', {'is_active': False}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 403)
        target.refresh_from_db()
        self.assertTrue(target.is_active)

    def test_office_admin_cannot_promote_a_user_to_global_admin(self):
        target = self._operator('operator_a', self.office_a)
        actor = self._office_admin('officeadmin_a', self.office_a)
        response = self.client.patch(
            f'/api/users/{target.pk}/',
            {'role': ROLE_GLOBAL_ADMIN, 'office': None},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 403)
        target.refresh_from_db()
        self.assertEqual(target.office_membership.role, ROLE_OPERATOR)

    def test_office_admin_cannot_move_a_user_to_another_office(self):
        target = self._operator('operator_a', self.office_a)
        actor = self._office_admin('officeadmin_a', self.office_a)
        response = self.client.patch(
            f'/api/users/{target.pk}/',
            {'role': ROLE_OPERATOR, 'office': self.office_b.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 403)
        target.refresh_from_db()
        self.assertEqual(target.office_membership.office, self.office_a)

    def test_global_admin_can_move_a_user_between_offices(self):
        target = self._operator('operator_a', self.office_a)
        actor = self._global_admin()
        response = self.client.patch(
            f'/api/users/{target.pk}/',
            {'role': ROLE_OPERATOR, 'office': self.office_b.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.office_membership.office, self.office_b)
        # Still exactly one membership row (OneToOneField) — moved in
        # place, never duplicated.
        self.assertEqual(OfficeMembership.objects.filter(user=target).count(), 1)

    def test_office_admin_cannot_edit_their_own_account_via_this_endpoint(self):
        actor = self._office_admin('officeadmin_a', self.office_a)
        response = self.client.patch(
            f'/api/users/{actor.pk}/', {'is_active': False}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 403)

    def test_global_admin_cannot_edit_their_own_account_via_this_endpoint(self):
        actor = self._global_admin()
        response = self.client.patch(
            f'/api/users/{actor.pk}/', {'is_active': False}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 403)

    def test_superuser_targeting_self_is_not_blocked_by_the_self_edit_rule(self):
        # Rule 10 — Superadmin keeps ordinary Django self-management
        # behavior; the self-edit block above only applies to
        # non-superuser admins (rule 8's escalation concern).
        actor = self._superadmin()
        response = self.client.patch(
            f'/api/users/{actor.pk}/', {'first_name': 'Root'}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 200)

    def test_deactivated_user_cannot_log_in(self):
        target = self._operator('operator_a', self.office_a)
        target.is_active = False
        target.save()
        response = self.client.post(
            '/api/auth/login/', {'username': 'operator_a', 'password': 'pw'}, format='json'
        )
        self.assertEqual(response.status_code, 401)

    def test_deactivated_user_existing_token_stops_working(self):
        # JWTAuthentication re-fetches the user with is_active=True on
        # every request (apps/authn/authentication.py) — deactivating
        # after a token was already issued must still lock them out.
        target = self._operator('operator_a', self.office_a)
        header = self._auth_header(target)
        target.is_active = False
        target.save()
        response = self.client.get('/api/auth/me/', **header)
        self.assertEqual(response.status_code, 401)

    def test_role_and_office_must_be_provided_together(self):
        target = self._operator('operator_a', self.office_a)
        actor = self._superadmin()
        response = self.client.patch(
            f'/api/users/{target.pk}/', {'role': ROLE_OPERATOR}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 400)

    def test_cannot_assign_role_to_a_superuser_account(self):
        target = self._superadmin('anothersuper')
        actor = self._superadmin()
        response = self.client.patch(
            f'/api/users/{target.pk}/',
            {'role': ROLE_OPERATOR, 'office': self.office_a.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 400)


class RoleScopeSyncTests(OfficesUsersApiTestCase):
    """Step 8 (Role x Scope alignment) — `_sync_admin_scope_group` now
    also manages the 'blast' Group (not just 'user administration'), and
    must NEVER touch 'system administration'/'reading' — those two stay
    Group-only for genuinely global actions (Sync Recovery, Dashboard/
    Sessions), reached by Office/Global Admin instead through
    HasOfficeAdminAccess/HasOfficeAccess (role-checked live, no Group)."""

    def test_creating_an_office_admin_grants_user_administration_and_blast_groups(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/users/',
            {'username': 'newadmin', 'password': 'a-strong-password', 'role': ROLE_OFFICE_ADMIN, 'office': self.office_a.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username='newadmin')
        group_names = set(created.groups.values_list('name', flat=True))
        self.assertEqual(group_names, {ADMIN_SCOPE, 'blast'})

    def test_creating_a_global_admin_grants_user_administration_and_blast_groups(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/users/',
            {'username': 'newgadmin', 'password': 'a-strong-password', 'role': ROLE_GLOBAL_ADMIN},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username='newgadmin')
        group_names = set(created.groups.values_list('name', flat=True))
        self.assertEqual(group_names, {ADMIN_SCOPE, 'blast'})

    def test_creating_an_operator_grants_no_groups_at_all(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/users/',
            {'username': 'newoperator', 'password': 'a-strong-password', 'role': ROLE_OPERATOR, 'office': self.office_a.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username='newoperator')
        self.assertEqual(created.groups.count(), 0)

    def test_office_admin_and_global_admin_never_get_system_administration_or_reading_groups(self):
        actor = self._superadmin()
        for role, office in ((ROLE_OFFICE_ADMIN, self.office_a.pk), (ROLE_GLOBAL_ADMIN, None)):
            username = f'checkgroups_{role}'
            payload = {'username': username, 'password': 'a-strong-password', 'role': role}
            if office is not None:
                payload['office'] = office
            self.client.post('/api/users/', payload, format='json', **self._auth_header(actor))
            created = User.objects.get(username=username)
            group_names = set(created.groups.values_list('name', flat=True))
            self.assertNotIn('system administration', group_names)
            self.assertNotIn('reading', group_names)

    def test_demoting_office_admin_to_operator_revokes_blast_and_user_administration(self):
        actor = self._superadmin()
        self.client.post(
            '/api/users/',
            {'username': 'demoted_admin', 'password': 'a-strong-password', 'role': ROLE_OFFICE_ADMIN, 'office': self.office_a.pk},
            format='json',
            **self._auth_header(actor),
        )
        target = User.objects.get(username='demoted_admin')
        self.assertEqual(
            set(target.groups.values_list('name', flat=True)), {ADMIN_SCOPE, 'blast'}
        )
        response = self.client.patch(
            f'/api/users/{target.pk}/',
            {'role': ROLE_OPERATOR, 'office': self.office_a.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.groups.count(), 0)

    def test_promoting_operator_to_office_admin_grants_blast_and_user_administration(self):
        actor = self._superadmin()
        target = self._operator('promoted_operator', self.office_a)
        self.assertEqual(target.groups.count(), 0)
        response = self.client.patch(
            f'/api/users/{target.pk}/',
            {'role': ROLE_OFFICE_ADMIN, 'office': self.office_a.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(set(target.groups.values_list('name', flat=True)), {ADMIN_SCOPE, 'blast'})


# --- OFFICE INBOX CONFIG (Step 10) --------------------------------------

class OfficeInboxConfigApiTests(OfficesUsersApiTestCase):
    def _url(self, office):
        return f'/api/offices/{office.pk}/inbox-config/'

    # -- retrieve / lazy creation ------------------------------------------

    def test_superadmin_can_get_config_office_a(self):
        actor = self._superadmin()
        response = self.client.get(self._url(self.office_a), **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['enabled'])
        self.assertEqual(response.data['welcome_message'], '')

    def test_superadmin_can_get_config_office_b(self):
        actor = self._superadmin()
        response = self.client.get(self._url(self.office_b), **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)

    def test_get_lazily_creates_exactly_one_config_row(self):
        from apps.offices.models import OfficeInboxConfig

        actor = self._superadmin()
        self.assertEqual(OfficeInboxConfig.objects.filter(office=self.office_a).count(), 0)
        self.client.get(self._url(self.office_a), **self._auth_header(actor))
        self.client.get(self._url(self.office_a), **self._auth_header(actor))
        self.assertEqual(OfficeInboxConfig.objects.filter(office=self.office_a).count(), 1)

    # -- update --------------------------------------------------------------

    def test_superadmin_can_update_config_office_a(self):
        actor = self._superadmin()
        response = self.client.patch(
            self._url(self.office_a),
            {'enabled': True, 'welcome_message': 'Halo dari Palangka Raya'},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['enabled'])
        self.assertEqual(response.data['welcome_message'], 'Halo dari Palangka Raya')

    def test_superadmin_can_update_config_office_b(self):
        actor = self._superadmin()
        response = self.client.patch(
            self._url(self.office_b), {'enabled': True}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 200)

    def test_global_admin_can_get_and_update_office_a_and_b(self):
        actor = self._global_admin()
        for office in (self.office_a, self.office_b):
            get_response = self.client.get(self._url(office), **self._auth_header(actor))
            self.assertEqual(get_response.status_code, 200)
            patch_response = self.client.patch(
                self._url(office), {'enabled': True}, format='json', **self._auth_header(actor)
            )
            self.assertEqual(patch_response.status_code, 200)

    def test_office_admin_a_can_get_and_update_own_office(self):
        actor = self._office_admin('officeadmin_a', self.office_a)
        get_response = self.client.get(self._url(self.office_a), **self._auth_header(actor))
        self.assertEqual(get_response.status_code, 200)
        patch_response = self.client.patch(
            self._url(self.office_a),
            {'enabled': True, 'waiting_message': 'Mohon tunggu'},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.data['waiting_message'], 'Mohon tunggu')

    def test_office_admin_a_cannot_get_office_b(self):
        actor = self._office_admin('officeadmin_a', self.office_a)
        response = self.client.get(self._url(self.office_b), **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_office_admin_a_cannot_update_office_b(self):
        actor = self._office_admin('officeadmin_a', self.office_a)
        response = self.client.patch(
            self._url(self.office_b), {'enabled': True}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 403)
        from apps.offices.models import OfficeInboxConfig

        self.assertFalse(OfficeInboxConfig.objects.filter(office=self.office_b, enabled=True).exists())

    def test_operator_cannot_get_config(self):
        actor = self._operator('operator_a', self.office_a)
        response = self.client.get(self._url(self.office_a), **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_operator_cannot_update_config(self):
        actor = self._operator('operator_a', self.office_a)
        response = self.client.patch(
            self._url(self.office_a), {'enabled': True}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get(self._url(self.office_a))
        self.assertEqual(response.status_code, 401)

    def test_unknown_office_returns_404(self):
        actor = self._superadmin()
        response = self.client.get('/api/offices/999999/inbox-config/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 404)

    def test_config_persists_and_is_readable_for_an_inactive_office(self):
        actor = self._superadmin()
        self.office_a.is_active = False
        self.office_a.save(update_fields=['is_active'])
        patch_response = self.client.patch(
            self._url(self.office_a), {'enabled': True}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(patch_response.status_code, 200)
        get_response = self.client.get(self._url(self.office_a), **self._auth_header(actor))
        self.assertEqual(get_response.status_code, 200)
        self.assertTrue(get_response.data['enabled'])

    def test_update_writes_an_audit_log_entry(self):
        from apps.audit.models import AuditLog

        actor = self._superadmin()
        self.client.patch(self._url(self.office_a), {'enabled': True}, format='json', **self._auth_header(actor))
        self.assertTrue(
            AuditLog.objects.filter(action='office.inbox_config.update', target=self.office_a.name).exists()
        )

    def test_unknown_fields_are_ignored_not_corrupting(self):
        actor = self._superadmin()
        response = self.client.patch(
            self._url(self.office_a),
            {'enabled': True, 'is_superuser': True, 'office': self.office_b.pk, 'random_field': 'x'},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 200)
        from apps.offices.models import OfficeInboxConfig

        config = OfficeInboxConfig.objects.get(office=self.office_a)
        self.assertEqual(config.office, self.office_a)  # unchanged, never moved to office_b
