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
from apps.offices.models import ROLE_GLOBAL_ADMIN, ROLE_OFFICE_ADMIN, ROLE_OPERATOR, Office, OfficeMembership, Role

# The three seeded built-in Roles (migration 0009) — resolved by name on
# first use per test run and cached module-level Role instances would go
# stale across TestCase-per-test DB rollbacks, so this looks them up
# fresh via `get_or_create` every time instead (cheap; DB rows already
# exist from migrations, so this is always a plain `get`).
def _seeded_role(name, **flags):
    role, _ = Role.objects.get_or_create(name=name, defaults=flags)
    return role
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
        # The three seeded built-in Roles (migration 0009) — API payloads
        # send a Role id now, not the old CharField's string value, so
        # every `{'role': ROLE_X, ...}` payload literal below uses
        # `self.role_x.pk` instead of the bare `ROLE_X` string constant
        # (which stays valid as a plain Python value for `_user()`'s own
        # `role=` kwarg — see its own comment for why).
        self.role_global_admin = _seeded_role(
            ROLE_GLOBAL_ADMIN, grants_global_access=True, scopes=[ADMIN_SCOPE, BLAST_SCOPE, 'reading']
        )
        self.role_office_admin = _seeded_role(
            ROLE_OFFICE_ADMIN, is_office_admin=True, scopes=[ADMIN_SCOPE, BLAST_SCOPE, 'reading']
        )
        self.role_operator = _seeded_role(ROLE_OPERATOR, is_operator=True, scopes=[])

    def _user(self, username, scopes=(), office=None, role=None, superuser=False):
        if superuser:
            user = User.objects.create_superuser(username, f'{username}@example.com', 'pw')
        else:
            user = User.objects.create_user(username, password='pw')
        for scope in scopes:
            group, _ = Group.objects.get_or_create(name=scope)
            user.groups.add(group)
        if role is not None:
            # Accepts either a `Role` instance (a test building a custom
            # combination of flags) or one of the three seeded built-in
            # names (ROLE_GLOBAL_ADMIN/ROLE_OFFICE_ADMIN/ROLE_OPERATOR) —
            # the old CharField's exact values, now resolved to the
            # migration-0009-seeded Role with the matching flags, for
            # every test call site that predates this merge.
            role_obj = role if isinstance(role, Role) else _seeded_role(
                role,
                grants_global_access=(role == ROLE_GLOBAL_ADMIN),
                is_office_admin=(role == ROLE_OFFICE_ADMIN),
                is_operator=(role == ROLE_OPERATOR),
                scopes=[ADMIN_SCOPE, BLAST_SCOPE, 'reading'] if role in (ROLE_GLOBAL_ADMIN, ROLE_OFFICE_ADMIN) else [],
            )
            OfficeMembership.objects.create(
                user=user, office=office, role=role_obj, requires_office=not role_obj.grants_global_access
            )
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
            'initial': 'NU',
            'role': self.role_operator.pk,
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

    def test_created_user_has_the_given_initial(self):
        actor = self._superadmin()
        self.client.post('/api/users/', self._create_payload(initial='RD'), format='json', **self._auth_header(actor))
        response = self.client.get('/api/users/', **self._auth_header(actor))
        row = next(r for r in response.data if r['username'] == 'newuser')
        self.assertEqual(row['initial'], 'RD')

    def test_creating_a_user_without_an_initial_is_rejected(self):
        actor = self._superadmin()
        payload = self._create_payload()
        del payload['initial']
        response = self.client.post('/api/users/', payload, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 400)

    def test_username_with_a_space_is_rejected(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/users/', self._create_payload(username='new user'), format='json', **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(username='new user').exists())

    def test_username_with_an_at_sign_is_rejected(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/users/', self._create_payload(username='new@user'), format='json', **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 400)

    def test_username_with_dot_and_underscore_is_accepted(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/users/', self._create_payload(username='new.user_01'), format='json', **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(User.objects.filter(username='new.user_01').exists())

    def test_duplicate_username_is_rejected(self):
        actor = self._superadmin()
        self.client.post('/api/users/', self._create_payload(), format='json', **self._auth_header(actor))
        response = self.client.post('/api/users/', self._create_payload(), format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.filter(username='newuser').count(), 1)

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
            self._create_payload(username='sneaky', role=self.role_global_admin.pk, office=None),
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
            self._create_payload(role=self.role_office_admin.pk, office=None),
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 400)

    def test_global_admin_role_rejects_an_office(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/users/',
            self._create_payload(role=self.role_global_admin.pk, office=self.office_a.pk),
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
            {'role': self.role_global_admin.pk, 'office': None},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 403)
        target.refresh_from_db()
        self.assertEqual(target.office_membership.role_id, self.role_operator.pk)

    def test_office_admin_cannot_move_a_user_to_another_office(self):
        target = self._operator('operator_a', self.office_a)
        actor = self._office_admin('officeadmin_a', self.office_a)
        response = self.client.patch(
            f'/api/users/{target.pk}/',
            {'role': self.role_operator.pk, 'office': self.office_b.pk},
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
            {'role': self.role_operator.pk, 'office': self.office_b.pk},
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
            f'/api/users/{target.pk}/', {'role': self.role_operator.pk}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 400)

    def test_cannot_assign_role_to_a_superuser_account(self):
        target = self._superadmin('anothersuper')
        actor = self._superadmin()
        response = self.client.patch(
            f'/api/users/{target.pk}/',
            {'role': self.role_operator.pk, 'office': self.office_a.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 400)


class RoleScopeSyncTests(OfficesUsersApiTestCase):
    """Dynamic Role model — `_sync_role_groups` replaces the old hardcoded
    `ROLE_GROUPS` mapping this class used to exercise. `role` is now the
    ONE field carrying both organizational standing AND scopes (the Role
    merge) — creating/updating a user with a Role whose `scopes` is empty
    grants no Groups at all, and any globally-accessing actor may assign
    ANY existing Role (a Role's own `scopes`/flags are defined separately,
    Superuser-only, via `/api/roles/` — see `RoleApiTests` below)."""

    def _role(self, name, scopes=(), **flags):
        return Role.objects.create(name=name, scopes=list(scopes), **flags)

    def test_creating_a_user_with_a_scopeless_role_grants_no_groups(self):
        actor = self._superadmin()
        bare_role = self._role('Bare Office Admin', is_office_admin=True)
        response = self.client.post(
            '/api/users/',
            {'username': 'newadmin', 'password': 'a-strong-password', 'initial': 'NA', 'role': bare_role.pk, 'office': self.office_a.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username='newadmin')
        self.assertEqual(created.groups.count(), 0)

    def test_creating_a_user_with_a_scoped_role_grants_exactly_its_scopes(self):
        actor = self._superadmin()
        role = self._role('Office Admin+', is_office_admin=True, scopes=['reading', 'blast', ADMIN_SCOPE])
        response = self.client.post(
            '/api/users/',
            {'username': 'newadmin2', 'password': 'a-strong-password', 'initial': 'NA', 'role': role.pk, 'office': self.office_a.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username='newadmin2')
        self.assertEqual(set(created.groups.values_list('name', flat=True)), {'reading', 'blast', ADMIN_SCOPE})
        self.assertEqual(created.office_membership.role_id, role.pk)

    def test_creating_an_operator_role_user_with_no_scopes_grants_no_groups(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/users/',
            {'username': 'newoperator', 'password': 'a-strong-password', 'initial': 'NO', 'role': self.role_operator.pk, 'office': self.office_a.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username='newoperator')
        self.assertEqual(created.groups.count(), 0)

    def test_office_admin_actor_can_create_a_user_with_a_non_global_role(self):
        # Unaffected by the merge: an Office Admin could always create
        # another office_admin/operator-equivalent user in their own
        # Office — only a Role with grants_global_access is blocked for
        # a non-globally-accessing actor (see the next test).
        actor = self._office_admin('officeadminactor', self.office_a)
        role = self._role('Reader Op', is_operator=True, scopes=['reading'])
        response = self.client.post(
            '/api/users/',
            {'username': 'notsneaky', 'password': 'a-strong-password', 'initial': 'NS', 'role': role.pk, 'office': self.office_a.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 201)
        created = User.objects.get(username='notsneaky')
        self.assertEqual(set(created.groups.values_list('name', flat=True)), {'reading'})

    def test_office_admin_actor_cannot_create_a_user_with_a_globally_accessing_role(self):
        actor = self._office_admin('officeadminactor2', self.office_a)
        role = self._role('Sneaky Global', grants_global_access=True, scopes=['reading'])
        response = self.client.post(
            '/api/users/',
            {'username': 'sneaky', 'password': 'a-strong-password', 'initial': 'SN', 'role': role.pk, 'office': None},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username='sneaky').exists())

    def test_office_admin_actor_cannot_reassign_a_user_to_a_globally_accessing_role(self):
        actor = self._office_admin('officeadminactor3', self.office_a)
        target = self._operator('targetoperator', self.office_a)
        role = self._role('Sneaky Global 2', grants_global_access=True)
        response = self.client.patch(
            f'/api/users/{target.pk}/',
            {'role': role.pk, 'office': None},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 403)
        target.refresh_from_db()
        self.assertEqual(target.office_membership.role_id, self.role_operator.pk)

    def test_global_admin_can_reassign_a_user_to_a_different_role(self):
        actor = self._global_admin()
        target = self._operator('standalone_target', self.office_a)
        role = self._role('Reader', scopes=['reading'], is_operator=True)
        response = self.client.patch(
            f'/api/users/{target.pk}/',
            {'role': role.pk, 'office': self.office_a.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.office_membership.role_id, role.pk)
        self.assertEqual(set(target.groups.values_list('name', flat=True)), {'reading'})

    def test_reassigning_to_a_role_with_fewer_scopes_revokes_the_dropped_groups(self):
        actor = self._global_admin()
        rich_role = self._role('Rich', scopes=['reading', 'blast'], is_operator=True)
        target = self._operator('demote_target', self.office_a)
        target.office_membership.role = rich_role
        target.office_membership.save(update_fields=['role'])
        for name in ('reading', 'blast'):
            group, _ = Group.objects.get_or_create(name=name)
            target.groups.add(group)

        response = self.client.patch(
            f'/api/users/{target.pk}/',
            {'role': self.role_operator.pk, 'office': self.office_a.pk},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.office_membership.role_id, self.role_operator.pk)
        self.assertEqual(target.groups.count(), 0)


class RoleApiTests(OfficesUsersApiTestCase):
    """`/api/roles/` write access (POST/PATCH/DELETE) — Superuser-only,
    never reachable via a scope (not even 'user administration', which a
    non-superuser Global/Office Admin can hold via their own assigned
    Role) — see `RoleListCreateView`'s own docstring for why. GET is
    readable by any globally-accessing actor (see the next test)."""

    def test_superuser_can_list_and_create_roles(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/roles/', {'name': 'Support', 'scopes': ['reading', 'blast']}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Role.objects.filter(name='Support', scopes=['reading', 'blast']).exists())

        response = self.client.get('/api/roles/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)

    def test_superuser_can_set_organizational_flags_on_a_role(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/roles/',
            {'name': 'Custom Admin', 'scopes': ['reading'], 'grants_global_access': True, 'is_office_admin': True},
            format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['grants_global_access'], True)
        self.assertEqual(response.data['is_office_admin'], True)
        self.assertEqual(response.data['is_operator'], False)
        role = Role.objects.get(name='Custom Admin')
        self.assertTrue(role.grants_global_access)
        self.assertTrue(role.is_office_admin)
        self.assertEqual(len(response.data), 1)

    def test_global_admin_can_list_but_not_create_edit_or_delete_roles(self):
        actor = self._global_admin()
        role = Role.objects.create(name='Existing', scopes=['reading'])

        # Read: allowed, so a Global Admin can populate the "assign a
        # Role" picker in the Users form.
        response = self.client.get('/api/roles/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)
        response = self.client.get(f'/api/roles/{role.pk}/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)

        # Write: blocked — defining/changing what a Role grants stays
        # Superuser-only, even for a Global Admin who holds 'user
        # administration' themselves.
        response = self.client.post(
            '/api/roles/', {'name': 'Sneaky', 'scopes': ['system administration']}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.patch(
            f'/api/roles/{role.pk}/', {'scopes': ['reading', 'blast']}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.delete(f'/api/roles/{role.pk}/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_office_admin_can_list_roles_but_operator_cannot(self):
        # Office Admin needs the Role catalog to populate the Users
        # form's single `role` picker (the old fixed 3-value enum never
        # needed an API call for this) — but still cannot write to it
        # (covered by the Superuser-only write tests elsewhere).
        office_admin = self._office_admin('oa', self.office_a)
        response = self.client.get('/api/roles/', **self._auth_header(office_admin))
        self.assertEqual(response.status_code, 200)

        operator = self._operator('op', self.office_a)
        response = self.client.get('/api/roles/', **self._auth_header(operator))
        self.assertEqual(response.status_code, 403)

    def test_office_admin_cannot_write_to_roles_api(self):
        actor = self._office_admin('oawrite', self.office_a)
        role = Role.objects.create(name='Existing2', scopes=['reading'])
        response = self.client.post(
            '/api/roles/', {'name': 'Sneaky3', 'scopes': ['reading']}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.patch(
            f'/api/roles/{role.pk}/', {'scopes': ['blast']}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.delete(f'/api/roles/{role.pk}/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_creating_a_role_with_an_unknown_scope_is_rejected(self):
        actor = self._superadmin()
        response = self.client.post(
            '/api/roles/', {'name': 'Bogus', 'scopes': ['reading', 'not-a-real-scope']}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Role.objects.filter(name='Bogus').exists())

    def test_superuser_can_create_a_role_with_any_declared_scope_including_system_administration(self):
        # Deliberate: Role CRUD is Superuser-only, so a Role naming
        # 'system administration' is exactly as trusted as the Superuser
        # who defined it — no additional restriction on scope content.
        actor = self._superadmin()
        response = self.client.post(
            '/api/roles/', {'name': 'Full', 'scopes': ['system administration']}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 201)

    def test_deleting_an_unused_role_succeeds(self):
        actor = self._superadmin()
        role = Role.objects.create(name='Unused', scopes=['reading'])
        response = self.client.delete(f'/api/roles/{role.pk}/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Role.objects.filter(pk=role.pk).exists())

    def test_deleting_a_role_assigned_to_a_user_is_blocked(self):
        actor = self._superadmin()
        role = Role.objects.create(name='In Use', scopes=['reading'])
        target = self._operator('assignee', self.office_a)
        target.office_membership.role = role
        target.office_membership.save(update_fields=['role'])

        response = self.client.delete(f'/api/roles/{role.pk}/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Role.objects.filter(pk=role.pk).exists())

    def test_editing_a_roles_scopes_resyncs_assigned_members_immediately(self):
        actor = self._superadmin()
        role = Role.objects.create(name='Evolving', scopes=['reading'])
        target = self._operator('resync_target', self.office_a)
        target.office_membership.role = role
        target.office_membership.save(update_fields=['role'])
        group, _ = Group.objects.get_or_create(name='reading')
        target.groups.add(group)

        response = self.client.patch(
            f'/api/roles/{role.pk}/', {'scopes': ['reading', 'blast']}, format='json', **self._auth_header(actor)
        )
        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(set(target.groups.values_list('name', flat=True)), {'reading', 'blast'})


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
