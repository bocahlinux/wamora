"""Conversation/Bot Engine — admin CRUD API authorization tests. Same
`_user()`/seeded-Role conventions as `apps.offices.test_views`
(`OfficesUsersApiTestCase`) — not imported from there directly (that
module's helper is test-file-local, same pattern every other app's test
suite already follows for its own actor fixtures)."""

from django.contrib.auth.models import Group, User
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.bot.models import BotConfig, BotMenu, BotMenuItem, BotTrigger
from apps.offices.models import ROLE_GLOBAL_ADMIN, ROLE_OFFICE_ADMIN, ROLE_OPERATOR, Office, OfficeMembership, Role

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()
ADMIN_SCOPE = 'user administration'


def _seeded_role(name, **flags):
    role, _ = Role.objects.get_or_create(name=name, defaults=flags)
    return role


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM, JWT_PUBLIC_KEY=PUBLIC_PEM, JWT_ISSUER='test-issuer', JWT_AUDIENCE='test-audience',
)
class BotApiTestCase(APITestCase):
    def setUp(self):
        self.office_a = Office.objects.create(name='Office A')
        self.office_b = Office.objects.create(name='Office B')
        self.role_global_admin = _seeded_role(ROLE_GLOBAL_ADMIN, grants_global_access=True, scopes=[ADMIN_SCOPE])
        self.role_office_admin = _seeded_role(ROLE_OFFICE_ADMIN, is_office_admin=True, scopes=[ADMIN_SCOPE])
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
            OfficeMembership.objects.create(user=user, office=office, role=role, requires_office=not role.grants_global_access)
        return user

    def _auth_header(self, user):
        token = issue_access_token(user)['access_token']
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def _superadmin(self, username='superadmin'):
        return self._user(username, superuser=True)

    def _global_admin(self, username='globaladmin'):
        return self._user(username, scopes=[ADMIN_SCOPE], role=self.role_global_admin)

    def _office_admin(self, username, office):
        return self._user(username, scopes=[ADMIN_SCOPE], office=office, role=self.role_office_admin)

    def _operator(self, username, office):
        return self._user(username, scopes=[ADMIN_SCOPE], office=office, role=self.role_operator)


class BotConfigViewTests(BotApiTestCase):
    def test_superadmin_can_get_global_config_without_persisting_a_row(self):
        # GET must never have the side effect of creating a durable,
        # disabled BotConfig override just from being viewed — see
        # BotConfigView.get()'s own docstring for the live bug this
        # regression-guards (an office-specific row silently shadowing
        # the enabled GLOBAL config for every Chat routed to that Office).
        actor = self._superadmin()
        response = self.client.get('/api/bot/config/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['office'])
        self.assertIsNone(response.data['id'])
        self.assertFalse(BotConfig.objects.filter(office=None).exists())

    def test_get_returns_existing_row_unmodified_if_one_already_exists(self):
        existing = BotConfig.objects.create(office=None, enabled=True)
        actor = self._superadmin()
        response = self.client.get('/api/bot/config/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], existing.pk)
        self.assertTrue(response.data['enabled'])

    def test_office_admin_cannot_access_global_config(self):
        actor = self._office_admin('oa', self.office_a)
        response = self.client.get('/api/bot/config/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_office_admin_cannot_access_own_office_config(self):
        # Bot content is Superadmin/Global Admin only, per explicit
        # discussion — an Office Admin no longer administers even their
        # own Office's BotConfig (apps.bot.views._may_access's own
        # docstring: this is what caused a live bug, a half-configured
        # per-Office override silently shadowing GLOBAL). The one thing
        # an Office Admin may still toggle is
        # apps.offices.models.OfficeInboxConfig.enabled — a different
        # endpoint entirely, unaffected by this module.
        actor = self._office_admin('oa2', self.office_a)
        response = self.client.get(f'/api/bot/config/?office={self.office_a.pk}', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_office_admin_cannot_access_other_office_config(self):
        actor = self._office_admin('oa3', self.office_a)
        response = self.client.get(f'/api/bot/config/?office={self.office_b.pk}', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_operator_cannot_access_any_config(self):
        actor = self._operator('op1', self.office_a)
        response = self.client.get(f'/api/bot/config/?office={self.office_a.pk}', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_global_admin_can_patch_office_config(self):
        actor = self._global_admin()
        response = self.client.patch(
            f'/api/bot/config/?office={self.office_a.pk}', {'enabled': True}, format='json', **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['enabled'])
        self.assertTrue(BotConfig.objects.get(office=self.office_a).enabled)


class BotMenuViewTests(BotApiTestCase):
    def test_global_admin_can_create_global_menu(self):
        actor = self._global_admin()
        response = self.client.post('/api/bot/menus/', {'name': 'Main Menu'}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(BotMenu.objects.get(pk=response.data['id']).office)

    def test_office_admin_cannot_create_global_menu(self):
        actor = self._office_admin('oa4', self.office_a)
        response = self.client.post('/api/bot/menus/', {'name': 'Main Menu'}, format='json', **self._auth_header(actor))
        self.assertEqual(response.status_code, 403)

    def test_office_admin_cannot_create_menu_in_own_office(self):
        # Was previously allowed — bot content is now Superadmin/Global
        # Admin only, even for an Office Admin's own Office.
        actor = self._office_admin('oa5', self.office_a)
        response = self.client.post(
            '/api/bot/menus/', {'name': 'Menu Kasongan', 'office': self.office_a.pk}, format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(BotMenu.objects.filter(name='Menu Kasongan').exists())

    def test_office_admin_cannot_create_menu_in_other_office(self):
        actor = self._office_admin('oa6', self.office_a)
        response = self.client.post(
            '/api/bot/menus/', {'name': 'Menu B', 'office': self.office_b.pk}, format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(BotMenu.objects.filter(name='Menu B').exists())

    def test_delete_menu_referenced_by_item_is_rejected_cleanly(self):
        actor = self._global_admin()
        menu = BotMenu.objects.create(name='Main')
        target = BotMenu.objects.create(name='Target')
        BotMenuItem.objects.create(
            menu=menu, label='Go', trigger_value='1', action_type=BotMenuItem.ACTION_SHOW_MENU, target_menu=target,
        )
        response = self.client.delete(f'/api/bot/menus/{target.pk}/', **self._auth_header(actor))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(BotMenu.objects.filter(pk=target.pk).exists())

    def test_list_menus_filters_by_office_scope(self):
        actor = self._global_admin()
        BotMenu.objects.create(name='Global One')
        BotMenu.objects.create(name='Office A One', office=self.office_a)
        response = self.client.get(f'/api/bot/menus/?office={self.office_a.pk}', **self._auth_header(actor))
        self.assertEqual(response.status_code, 200)
        names = [m['name'] for m in response.data]
        self.assertEqual(names, ['Office A One'])


class BotMenuItemViewTests(BotApiTestCase):
    def setUp(self):
        super().setUp()
        self.menu = BotMenu.objects.create(name='Main Menu')

    def test_global_admin_can_create_item(self):
        actor = self._global_admin()
        response = self.client.post(
            f'/api/bot/menus/{self.menu.pk}/items/',
            {'label': 'Info', 'trigger_value': '1', 'action_type': BotMenuItem.ACTION_SEND_TEXT, 'text': 'Halo'},
            format='json', **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 201)

    def test_show_menu_action_requires_target_menu(self):
        actor = self._global_admin()
        response = self.client.post(
            f'/api/bot/menus/{self.menu.pk}/items/',
            {'label': 'Sub', 'trigger_value': '2', 'action_type': BotMenuItem.ACTION_SHOW_MENU},
            format='json', **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 400)

    def test_office_admin_cannot_create_item_in_global_menu(self):
        actor = self._office_admin('oa7', self.office_a)
        response = self.client.post(
            f'/api/bot/menus/{self.menu.pk}/items/',
            {'label': 'Info', 'trigger_value': '1', 'action_type': BotMenuItem.ACTION_SEND_TEXT, 'text': 'Halo'},
            format='json', **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 403)

    def test_patch_cannot_move_item_to_another_menu(self):
        actor = self._global_admin()
        other_menu = BotMenu.objects.create(name='Other')
        item = BotMenuItem.objects.create(
            menu=self.menu, label='Info', trigger_value='1', action_type=BotMenuItem.ACTION_SEND_TEXT, text='Halo',
        )
        response = self.client.patch(
            f'/api/bot/items/{item.pk}/', {'menu': other_menu.pk, 'label': 'Info Baru'}, format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.menu, self.menu)
        self.assertEqual(item.label, 'Info Baru')


class BotTriggerViewTests(BotApiTestCase):
    def test_keyword_is_normalized_lowercase(self):
        actor = self._global_admin()
        menu = BotMenu.objects.create(name='Main Menu')
        response = self.client.post(
            '/api/bot/triggers/', {'keyword': '  HALO  ', 'target_menu': menu.pk}, format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['keyword'], 'halo')

    def test_office_admin_cannot_create_global_trigger(self):
        actor = self._office_admin('oa8', self.office_a)
        menu = BotMenu.objects.create(name='Main Menu')
        response = self.client.post(
            '/api/bot/triggers/', {'keyword': 'halo', 'target_menu': menu.pk}, format='json',
            **self._auth_header(actor),
        )
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get('/api/bot/triggers/')
        self.assertEqual(response.status_code, 401)
