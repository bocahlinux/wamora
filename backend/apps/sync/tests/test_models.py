from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.sync.models import SyncCheckpoint
from apps.waha_sessions.models import WahaSession


class SyncCheckpointTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='default')

    def test_default_status_is_idle(self):
        checkpoint = SyncCheckpoint.objects.create(session=self.session)
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_IDLE)

    def test_only_one_checkpoint_per_session(self):
        SyncCheckpoint.objects.create(session=self.session)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SyncCheckpoint.objects.create(session=self.session)
