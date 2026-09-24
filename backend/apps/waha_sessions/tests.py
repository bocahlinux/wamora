from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.waha_sessions.models import WahaSession


class WahaSessionTests(TestCase):
    def test_name_is_unique(self):
        WahaSession.objects.create(name='default')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WahaSession.objects.create(name='default')
