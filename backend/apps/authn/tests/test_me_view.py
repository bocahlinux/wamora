from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.authn.jwt_utils import issue_access_token

from .keys import generate_test_key_pair

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()
ME_URL = '/api/auth/me/'


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
)
class MeViewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'operator', password='pw', first_name='Op', last_name='Erator'
        )
        self.token = issue_access_token(self.user)['access_token']

    def _auth_header(self, token=None):
        return {'HTTP_AUTHORIZATION': f'Bearer {token or self.token}'}

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get(ME_URL)
        self.assertEqual(response.status_code, 401)

    def test_invalid_token_is_rejected(self):
        response = self.client.get(ME_URL, **self._auth_header('not-a-real-token'))
        self.assertEqual(response.status_code, 401)

    def test_valid_token_returns_the_caller(self):
        response = self.client.get(ME_URL, **self._auth_header())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.user.pk)
        self.assertEqual(response.data['username'], 'operator')
        self.assertEqual(response.data['display_name'], 'Op Erator')

    def test_falls_back_to_username_when_no_full_name_set(self):
        user = User.objects.create_user('noname', password='pw')
        token = issue_access_token(user)['access_token']
        response = self.client.get(ME_URL, **self._auth_header(token))
        self.assertEqual(response.data['display_name'], 'noname')

    def test_response_never_exposes_password_or_sensitive_fields(self):
        response = self.client.get(ME_URL, **self._auth_header())
        self.assertEqual(set(response.data.keys()), {'id', 'username', 'display_name'})
