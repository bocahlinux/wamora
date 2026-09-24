from django.test import TestCase

from apps.audit.models import AuditLog


class AuditLogTests(TestCase):
    def test_actor_is_nullable_for_system_initiated_actions(self):
        entry = AuditLog.objects.create(
            actor=None, action='session.start', target='default', result=AuditLog.RESULT_SUCCESS
        )
        self.assertIsNone(entry.actor)
        self.assertEqual(entry.result, AuditLog.RESULT_SUCCESS)

    def test_created_at_is_set_automatically(self):
        entry = AuditLog.objects.create(action='session.start', result=AuditLog.RESULT_FAILURE)
        self.assertIsNotNone(entry.created_at)
