from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.offices.models import Office, OfficeMembership, Role

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM, JWT_PUBLIC_KEY=PUBLIC_PEM, JWT_ISSUER='test-issuer', JWT_AUDIENCE='test-audience',
)
class RoleVisibleMenuItemsTests(APITestCase):
    """Discussed requirement — Menu Access. `visible_menu_items` is a
    THIRD, independent axis from `scopes`: `null` (the default) means
    "not customized" (frontend falls back to its own scope-derived
    visibility); `[]` means "show nothing" (a deliberate, explicit
    choice); a non-empty list is a strict allowlist."""

    def setUp(self):
        self.office = Office.objects.create(name='Office A')
        self.role = Role.objects.create(name='Operator', is_operator=True, scopes=['reading', 'sending'])
        self.user = User.objects.create_user('operator', password='pw')
        OfficeMembership.objects.create(user=self.user, office=self.office, role=self.role, requires_office=True)
        self.superuser = User.objects.create_superuser('super', 'super@example.com', 'pw')

    def _auth(self, user):
        token = issue_access_token(user)['access_token']
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def test_me_exposes_null_visible_menu_items_by_default(self):
        response = self.client.get('/api/auth/me/', **self._auth(self.user))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['role']['visible_menu_items'])

    def test_role_can_be_explicitly_set_to_show_nothing(self):
        response = self.client.patch(
            f'/api/roles/{self.role.pk}/', {'visible_menu_items': []}, format='json', **self._auth(self.superuser),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.role.refresh_from_db()
        self.assertEqual(self.role.visible_menu_items, [])

    def test_role_can_be_reset_back_to_not_customized(self):
        Role.objects.filter(pk=self.role.pk).update(visible_menu_items=['dashboard'])
        response = self.client.patch(
            f'/api/roles/{self.role.pk}/', {'visible_menu_items': None}, format='json', **self._auth(self.superuser),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.role.refresh_from_db()
        self.assertIsNone(self.role.visible_menu_items)

    def test_superuser_can_customize_a_roles_visible_menu_items(self):
        response = self.client.patch(
            f'/api/roles/{self.role.pk}/', {'visible_menu_items': ['dashboard', 'blast.campaigns']}, format='json',
            **self._auth(self.superuser),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.role.refresh_from_db()
        self.assertEqual(self.role.visible_menu_items, ['dashboard', 'blast.campaigns'])

    def test_customized_value_is_reflected_on_me(self):
        Role.objects.filter(pk=self.role.pk).update(visible_menu_items=['dashboard'])
        response = self.client.get('/api/auth/me/', **self._auth(self.user))
        self.assertEqual(response.data['role']['visible_menu_items'], ['dashboard'])

    def test_unknown_menu_item_key_is_rejected(self):
        response = self.client.patch(
            f'/api/roles/{self.role.pk}/', {'visible_menu_items': ['totally_made_up_key']}, format='json',
            **self._auth(self.superuser),
        )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_keys_are_deduplicated_order_preserving(self):
        response = self.client.patch(
            f'{"/api/roles/"}{self.role.pk}/',
            {'visible_menu_items': ['dashboard', 'reports', 'dashboard']}, format='json', **self._auth(self.superuser),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['visible_menu_items'], ['dashboard', 'reports'])

    def test_non_superuser_cannot_edit_visible_menu_items(self):
        office_admin_role = Role.objects.create(name='OfficeAdmin', is_office_admin=True, scopes=['user administration'])
        office_admin = User.objects.create_user('office_admin', password='pw')
        OfficeMembership.objects.create(user=office_admin, office=self.office, role=office_admin_role, requires_office=True)

        response = self.client.patch(
            f'/api/roles/{self.role.pk}/', {'visible_menu_items': ['dashboard']}, format='json', **self._auth(office_admin),
        )
        self.assertEqual(response.status_code, 403)
