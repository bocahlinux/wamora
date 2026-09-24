import time

import jwt as pyjwt
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.exceptions import AuthenticationFailed

from apps.authn.authentication import JWTAuthentication

from .keys import generate_test_key_pair

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()
OTHER_PRIVATE_PEM, _ = generate_test_key_pair()


def _make_token(private_pem=PRIVATE_PEM, **overrides):
    now = int(time.time())
    payload = {
        'sub': overrides.pop('sub', '1'),
        'iss': overrides.pop('iss', 'test-issuer'),
        'aud': overrides.pop('aud', 'test-audience'),
        'iat': now,
        'exp': overrides.pop('exp', now + 3600),
    }
    payload.update(overrides)
    return pyjwt.encode(payload, private_pem, algorithm='RS256')


@override_settings(JWT_PUBLIC_KEY=PUBLIC_PEM, JWT_ISSUER='test-issuer', JWT_AUDIENCE='test-audience')
class JWTAuthenticationTests(TestCase):
    def setUp(self):
        self.auth = JWTAuthentication()
        self.factory = RequestFactory()
        self.user = User.objects.create_user('operator', password='pw')

    def _request(self, token=None):
        headers = {}
        if token is not None:
            headers['HTTP_AUTHORIZATION'] = f'Bearer {token}'
        return self.factory.get('/api/auth/me/', **headers)

    def test_no_authorization_header_returns_none(self):
        self.assertIsNone(self.auth.authenticate(self._request()))

    def test_non_bearer_scheme_returns_none(self):
        request = self.factory.get('/api/auth/me/', HTTP_AUTHORIZATION='Basic abc123')
        self.assertIsNone(self.auth.authenticate(request))

    def test_valid_token_resolves_the_signing_user(self):
        token = _make_token(sub=str(self.user.pk))
        user, payload = self.auth.authenticate(self._request(token))
        self.assertEqual(user.pk, self.user.pk)
        self.assertEqual(payload['sub'], str(self.user.pk))

    def test_expired_token_is_rejected(self):
        token = _make_token(sub=str(self.user.pk), exp=int(time.time()) - 10)
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self._request(token))

    def test_wrong_signing_key_is_rejected(self):
        token = _make_token(private_pem=OTHER_PRIVATE_PEM, sub=str(self.user.pk))
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self._request(token))

    def test_wrong_issuer_is_rejected(self):
        token = _make_token(sub=str(self.user.pk), iss='someone-else')
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self._request(token))

    def test_wrong_audience_is_rejected(self):
        token = _make_token(sub=str(self.user.pk), aud='someone-else')
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self._request(token))

    def test_malformed_token_is_rejected(self):
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self._request('not-a-jwt'))

    def test_unknown_subject_is_rejected(self):
        token = _make_token(sub='999999')
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self._request(token))

    def test_non_numeric_subject_is_rejected(self):
        token = _make_token(sub='not-a-number')
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self._request(token))

    def test_inactive_user_is_rejected(self):
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        token = _make_token(sub=str(self.user.pk))
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self._request(token))

    @override_settings(JWT_PUBLIC_KEY='')
    def test_unconfigured_public_key_fails_closed(self):
        token = _make_token(sub=str(self.user.pk))
        with self.assertRaises(AuthenticationFailed):
            self.auth.authenticate(self._request(token))
