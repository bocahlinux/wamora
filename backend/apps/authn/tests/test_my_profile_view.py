from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.authn.jwt_utils import issue_access_token
from apps.offices.models import UserProfile

from .keys import generate_test_key_pair

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()
PROFILE_URL = '/api/auth/me/profile/'


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
)
class MyProfileViewTests(APITestCase):
    """GET/PATCH /api/auth/me/profile/ — discussed requirement: every
    role may self-edit their own name/initial/password, always their OWN
    row (never a target `pk` in the URL/body — there is none)."""

    def setUp(self):
        self.user = User.objects.create_user(
            'operator', password='old-strong-password', first_name='Op', last_name='Erator',
        )
        self.token = issue_access_token(self.user)['access_token']

    def _auth_header(self):
        return {'HTTP_AUTHORIZATION': f'Bearer {self.token}'}

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get(PROFILE_URL)
        self.assertEqual(response.status_code, 401)

    def test_get_returns_current_profile_with_blank_initial_if_none_set(self):
        response = self.client.get(PROFILE_URL, **self._auth_header())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'operator')
        self.assertEqual(response.data['initial'], '')

    def test_can_update_name_and_initial(self):
        response = self.client.patch(
            PROFILE_URL, {'first_name': 'Budi', 'last_name': 'Santoso', 'initial': 'BS'}, format='json',
            **self._auth_header(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['first_name'], 'Budi')
        self.assertEqual(response.data['initial'], 'BS')
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Budi')
        self.assertEqual(UserProfile.objects.get(user=self.user).initial, 'BS')

    def test_updating_initial_a_second_time_does_not_create_a_duplicate_profile_row(self):
        self.client.patch(PROFILE_URL, {'initial': 'AA'}, format='json', **self._auth_header())
        self.client.patch(PROFILE_URL, {'initial': 'BB'}, format='json', **self._auth_header())
        self.assertEqual(UserProfile.objects.filter(user=self.user).count(), 1)
        self.assertEqual(UserProfile.objects.get(user=self.user).initial, 'BB')

    def test_can_change_password_with_correct_current_password(self):
        response = self.client.patch(
            PROFILE_URL,
            {'current_password': 'old-strong-password', 'new_password': 'new-strong-password'},
            format='json', **self._auth_header(),
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('new-strong-password'))

    def test_changing_password_with_wrong_current_password_is_rejected(self):
        response = self.client.patch(
            PROFILE_URL,
            {'current_password': 'totally-wrong', 'new_password': 'new-strong-password'},
            format='json', **self._auth_header(),
        )
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('old-strong-password'))

    def test_changing_password_without_current_password_is_rejected(self):
        response = self.client.patch(
            PROFILE_URL, {'new_password': 'new-strong-password'}, format='json', **self._auth_header(),
        )
        self.assertEqual(response.status_code, 400)

    def test_username_is_never_editable_here(self):
        response = self.client.patch(
            PROFILE_URL, {'username': 'someoneelse'}, format='json', **self._auth_header(),
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'operator')
