from django.test import RequestFactory, TestCase, override_settings

from apps.core.internal_auth import HasInternalServiceKey


@override_settings(INTERNAL_SERVICE_KEY='test-internal-service-key')
class HasInternalServiceKeyTests(TestCase):
    def setUp(self):
        self.permission = HasInternalServiceKey()
        self.factory = RequestFactory()

    def test_correct_key_is_authorized(self):
        request = self.factory.post('/internal/whatever/', HTTP_X_INTERNAL_SERVICE_KEY='test-internal-service-key')
        self.assertTrue(self.permission.has_permission(request, None))

    def test_wrong_key_is_rejected(self):
        request = self.factory.post('/internal/whatever/', HTTP_X_INTERNAL_SERVICE_KEY='guessed-wrong')
        self.assertFalse(self.permission.has_permission(request, None))

    def test_missing_header_is_rejected(self):
        request = self.factory.post('/internal/whatever/')
        self.assertFalse(self.permission.has_permission(request, None))

    @override_settings(INTERNAL_SERVICE_KEY='')
    def test_unconfigured_secret_fails_closed_even_with_empty_header(self):
        request = self.factory.post('/internal/whatever/', HTTP_X_INTERNAL_SERVICE_KEY='')
        self.assertFalse(self.permission.has_permission(request, None))
