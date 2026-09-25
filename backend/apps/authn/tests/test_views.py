import jwt as pyjwt
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog

from .keys import generate_test_key_pair

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()

LOGIN_URL = '/api/auth/login/'


@override_settings(JWT_PRIVATE_KEY=PRIVATE_PEM, JWT_ISSUER='test-issuer', JWT_AUDIENCE='test-audience')
class LoginViewTests(APITestCase):
    def setUp(self):
        # Phase 12 (Security hardening) MUST-FIX #5 — LoginView now has its
        # own strict, IP-keyed 5/minute throttle (apps/authn/throttling.py).
        # The throttle's cache-backed history persists for the process
        # lifetime of the test run, shared by test IP (127.0.0.1) across
        # every test method/class that calls LOGIN_URL (this file and
        # apps/authn/tests/test_cors.py) — clearing the cache before each
        # test isolates them from one another and from this class's own
        # dedicated rate-limit tests below, which deliberately exhaust it.
        cache.clear()
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

    # -- Phase 12 (Security hardening) MUST-FIX #3: audit logging --------

    def test_successful_login_writes_a_success_audit_log(self):
        response = self.client.post(LOGIN_URL, {'username': 'operator', 'password': 'correct-horse'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AuditLog.objects.count(), 1)
        entry = AuditLog.objects.first()
        self.assertEqual(entry.action, 'auth.login')
        self.assertEqual(entry.target, 'operator')
        self.assertEqual(entry.result, AuditLog.RESULT_SUCCESS)
        self.assertEqual(entry.actor_id, self.user.pk)

    def test_failed_login_writes_a_failure_audit_log(self):
        response = self.client.post(LOGIN_URL, {'username': 'operator', 'password': 'wrong'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(AuditLog.objects.count(), 1)
        entry = AuditLog.objects.first()
        self.assertEqual(entry.action, 'auth.login')
        self.assertEqual(entry.target, 'operator')
        self.assertEqual(entry.result, AuditLog.RESULT_FAILURE)
        # No Django user to attribute a failed attempt to.
        self.assertIsNone(entry.actor_id)

    def test_unknown_username_failure_is_still_audited(self):
        response = self.client.post(LOGIN_URL, {'username': 'nobody', 'password': 'whatever'})
        self.assertEqual(response.status_code, 401)
        entry = AuditLog.objects.first()
        self.assertEqual(entry.target, 'nobody')
        self.assertEqual(entry.result, AuditLog.RESULT_FAILURE)

    def test_audit_log_never_contains_the_password(self):
        response = self.client.post(LOGIN_URL, {'username': 'operator', 'password': 'correct-horse'})
        self.assertEqual(response.status_code, 200)
        entry = AuditLog.objects.first()
        # Every field on the model, not just `target` — the model has no
        # metadata/free-text field the password could have leaked into.
        self.assertNotIn('correct-horse', entry.target)
        self.assertNotIn('correct-horse', entry.action)
        self.assertNotIn('correct-horse', str(entry))

    # -- Phase 12 (Security hardening) MUST-FIX #4: input length bounds --

    def test_oversized_username_is_rejected_with_400_not_500(self):
        response = self.client.post(LOGIN_URL, {'username': 'x' * 151, 'password': 'whatever'})
        self.assertEqual(response.status_code, 400)
        # Rejected before any credential check/audit write happens.
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_oversized_password_is_rejected_with_400_not_500(self):
        response = self.client.post(LOGIN_URL, {'username': 'operator', 'password': 'x' * 129})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_username_at_exactly_the_max_length_is_accepted_by_the_serializer(self):
        # 150 chars is valid input shape-wise; this username simply doesn't
        # match any real user, so it still 401s — proving the boundary
        # itself is not what rejects it (distinct from the 151-char case
        # above, which is a 400 from the length validator).
        response = self.client.post(LOGIN_URL, {'username': 'x' * 150, 'password': 'whatever'})
        self.assertEqual(response.status_code, 401)

    # -- Phase 12 (Security hardening) MUST-FIX #5: rate limiting --------

    def test_login_burst_beyond_the_configured_rate_returns_429(self):
        for _ in range(5):
            response = self.client.post(LOGIN_URL, {'username': 'operator', 'password': 'wrong'})
            self.assertEqual(response.status_code, 401)
        response = self.client.post(LOGIN_URL, {'username': 'operator', 'password': 'wrong'})
        self.assertEqual(response.status_code, 429)

    def test_rate_limit_applies_per_ip_regardless_of_credentials_tried(self):
        # Rotating the attempted username must not bypass the limit — the
        # throttle is IP-keyed, not username-keyed (apps/authn/throttling.py's
        # own documented reasoning).
        for i in range(5):
            response = self.client.post(LOGIN_URL, {'username': f'nobody-{i}', 'password': 'whatever'})
            self.assertEqual(response.status_code, 401)
        response = self.client.post(LOGIN_URL, {'username': 'yet-another-nobody', 'password': 'whatever'})
        self.assertEqual(response.status_code, 429)

    def test_throttled_response_does_not_write_an_audit_log(self):
        for _ in range(5):
            self.client.post(LOGIN_URL, {'username': 'operator', 'password': 'wrong'})
        AuditLog.objects.all().delete()
        response = self.client.post(LOGIN_URL, {'username': 'operator', 'password': 'wrong'})
        self.assertEqual(response.status_code, 429)
        # The view's own post() body (and therefore _audit_login) never
        # runs once DRF's throttle check rejects the request in initial().
        self.assertEqual(AuditLog.objects.count(), 0)
