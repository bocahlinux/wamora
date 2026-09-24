from django.test import override_settings
from rest_framework.test import APITestCase

from .keys import generate_test_key_pair

PRIVATE_PEM, _ = generate_test_key_pair()
ALLOWED_ORIGIN = 'http://localhost:5173'
LOGIN_URL = '/api/auth/login/'


@override_settings(
    CORS_ALLOWED_ORIGINS=[ALLOWED_ORIGIN],
    JWT_PRIVATE_KEY=PRIVATE_PEM,
)
class CorsPreflightTests(APITestCase):
    """docs/generated/PHASE-7-CORS-FIX-REPORT.md: the browser blocks the
    Phase 7 login POST at the CORS preflight stage because Django never
    emitted Access-Control-Allow-Origin. These tests exercise the actual
    preflight the browser sends, not just the POST itself."""

    def test_preflight_for_the_configured_origin_receives_cors_headers(self):
        response = self.client.options(
            LOGIN_URL,
            HTTP_ORIGIN=ALLOWED_ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS='content-type',
        )
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), ALLOWED_ORIGIN)
        self.assertIn('POST', response.headers.get('Access-Control-Allow-Methods', ''))

    def test_preflight_for_an_unconfigured_origin_receives_no_cors_headers(self):
        response = self.client.options(
            LOGIN_URL,
            HTTP_ORIGIN='http://evil.example.com',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS='content-type',
        )
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)

    def test_actual_login_response_carries_cors_headers_for_the_configured_origin(self):
        response = self.client.post(
            LOGIN_URL,
            {'username': 'nonexistent', 'password': 'wrong'},
            content_type='application/json',
            HTTP_ORIGIN=ALLOWED_ORIGIN,
        )
        # Credentials are deliberately wrong here — this test is only
        # about the CORS header being present regardless of auth outcome
        # (a 401 response still needs the header, or the browser hides
        # the response body from the frontend's error handling too).
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), ALLOWED_ORIGIN)

    def test_never_emits_a_wildcard_origin(self):
        response = self.client.options(
            LOGIN_URL,
            HTTP_ORIGIN=ALLOWED_ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
        )
        self.assertNotEqual(response.headers.get('Access-Control-Allow-Origin'), '*')

    def test_does_not_enable_credentialed_cors(self):
        response = self.client.options(
            LOGIN_URL,
            HTTP_ORIGIN=ALLOWED_ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
        )
        self.assertNotIn('Access-Control-Allow-Credentials', response.headers)


@override_settings(CORS_ALLOWED_ORIGINS=[])
class CorsUnconfiguredTests(APITestCase):
    def test_no_origin_is_allowed_when_unconfigured(self):
        """Fails closed — an empty CORS_ALLOWED_ORIGINS must never behave
        like a wildcard."""
        response = self.client.options(
            LOGIN_URL,
            HTTP_ORIGIN=ALLOWED_ORIGIN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
        )
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)
