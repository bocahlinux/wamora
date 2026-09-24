import hashlib
import hmac

from django.test import SimpleTestCase, override_settings

from apps.webhooks.authentication import verify_waha_webhook_signature


class VerifyWahaWebhookSignatureTests(SimpleTestCase):
    def _sign(self, secret, body):
        return hmac.new(secret.encode('utf-8'), body, hashlib.sha512).hexdigest()

    @override_settings(WAHA_WEBHOOK_HMAC_SECRET='test-secret')
    def test_valid_signature_accepted(self):
        body = b'{"event":"message"}'
        signature = self._sign('test-secret', body)
        self.assertTrue(verify_waha_webhook_signature(body, signature))

    @override_settings(WAHA_WEBHOOK_HMAC_SECRET='test-secret')
    def test_invalid_signature_rejected(self):
        body = b'{"event":"message"}'
        self.assertFalse(verify_waha_webhook_signature(body, 'not-the-right-signature'))

    @override_settings(WAHA_WEBHOOK_HMAC_SECRET='test-secret')
    def test_missing_signature_rejected(self):
        body = b'{"event":"message"}'
        self.assertFalse(verify_waha_webhook_signature(body, None))

    @override_settings(WAHA_WEBHOOK_HMAC_SECRET='')
    def test_unconfigured_secret_fails_closed(self):
        body = b'{"event":"message"}'
        signature = self._sign('anything', body)
        self.assertFalse(verify_waha_webhook_signature(body, signature))

    @override_settings(WAHA_WEBHOOK_HMAC_SECRET='test-secret')
    def test_signature_for_different_body_rejected(self):
        signature = self._sign('test-secret', b'{"event":"message"}')
        self.assertFalse(verify_waha_webhook_signature(b'{"event":"tampered"}', signature))
