import jwt as pyjwt
from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings

from apps.authn.jwt_utils import JwtNotConfigured, compute_scopes, issue_access_token

from .keys import generate_test_key_pair

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()


class ComputeScopesTests(TestCase):
    def test_superuser_gets_all_scopes(self):
        user = User.objects.create_superuser('admin', 'admin@example.com', 'pw')
        self.assertEqual(
            compute_scopes(user),
            ['reading', 'sending', 'session control', 'blast', 'user administration', 'system administration'],
        )

    def test_ordinary_user_with_no_groups_gets_no_scopes(self):
        user = User.objects.create_user('plain', password='pw')
        self.assertEqual(compute_scopes(user), [])

    def test_group_membership_maps_to_matching_scope_only(self):
        user = User.objects.create_user('operator', password='pw')
        Group.objects.create(name='reading')
        Group.objects.create(name='sending')
        Group.objects.create(name='not-a-real-scope')
        user.groups.add(Group.objects.get(name='reading'), Group.objects.get(name='not-a-real-scope'))
        self.assertEqual(compute_scopes(user), ['reading'])


@override_settings(JWT_PRIVATE_KEY=PRIVATE_PEM, JWT_ISSUER='test-issuer', JWT_AUDIENCE='test-audience', JWT_KID='k1')
class IssueAccessTokenTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('operator', password='pw')

    def test_returns_bearer_token_with_expires_in(self):
        result = issue_access_token(self.user)
        self.assertEqual(result['token_type'], 'Bearer')
        self.assertIn('access_token', result)
        self.assertEqual(result['expires_in'], 8 * 60 * 60)

    def test_token_claims_are_correct(self):
        result = issue_access_token(self.user)
        decoded = pyjwt.decode(
            result['access_token'],
            PUBLIC_PEM,
            algorithms=['RS256'],
            audience='test-audience',
            issuer='test-issuer',
        )
        self.assertEqual(decoded['sub'], str(self.user.pk))
        self.assertEqual(decoded['scopes'], [])
        self.assertIn('iat', decoded)
        self.assertIn('exp', decoded)

    def test_token_header_carries_configured_kid(self):
        result = issue_access_token(self.user)
        header = pyjwt.get_unverified_header(result['access_token'])
        self.assertEqual(header['kid'], 'k1')
        self.assertEqual(header['alg'], 'RS256')

    @override_settings(JWT_PRIVATE_KEY='')
    def test_raises_when_unconfigured(self):
        with self.assertRaises(JwtNotConfigured):
            issue_access_token(self.user)
