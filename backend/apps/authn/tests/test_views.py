import jwt as pyjwt
from django.contrib.auth.models import User
from django.test import override_settings
from rest_framework.test import APITestCase

from .keys import generate_test_key_pair

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()

LOGIN_URL = '/api/auth/login/'


@override_settings(JWT_PRIVATE_KEY=PRIVATE_PEM, JWT_ISSUER='test-issuer', JWT_AUDIENCE='test-audience')
class LoginViewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('operator', password='correct-horse')

    def test_valid_credentials_return_access_token(self):
        response = self.client.post(LOGIN_URL, {'username': 'operator', 'password': 'correct-horse'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('access_token', response.data)
        self.assertEqual(response.data['token_type'], 'Bearer')

    def test_wrong_password_returns_401_generic_error(self):
        response = self.client.post(LOGIN_URL, {'username': 'operator', 'password': 'wrong'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data['error']['code'], 'invalid_credentials')

    def test_unknown_username_returns_same_generic_401(self):
        response = self.client.post(LOGIN_URL, {'username': 'nobody', 'password': 'whatever'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data['error']['code'], 'invalid_credentials')

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        response = self.client.post(LOGIN_URL, {'username': 'operator', 'password': 'correct-horse'})
        self.assertEqual(response.status_code, 401)

    def test_missing_fields_return_400(self):
        response = self.client.post(LOGIN_URL, {'username': 'operator'})
        self.assertEqual(response.status_code, 400)

    def test_issued_token_is_verifiable_with_the_public_key(self):
        response = self.client.post(LOGIN_URL, {'username': 'operator', 'password': 'correct-horse'})
        decoded = pyjwt.decode(
            response.data['access_token'],
            PUBLIC_PEM,
            algorithms=['RS256'],
            audience='test-audience',
            issuer='test-issuer',
        )
        self.assertEqual(decoded['sub'], str(self.user.pk))

    @override_settings(JWT_PRIVATE_KEY='')
    def test_returns_503_when_signing_key_not_configured(self):
        response = self.client.post(LOGIN_URL, {'username': 'operator', 'password': 'correct-horse'})
        self.assertEqual(response.status_code, 503)
