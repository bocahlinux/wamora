from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.chats.models import Chat
from apps.sync.models import SyncCheckpoint
from apps.sync.tests.fixtures import REST_INBOUND_MESSAGE_1
from apps.sync.tests.test_reconciliation import StubWahaClient
from apps.waha_sessions.models import WahaSession


class ReconcileManagementCommandTests(TestCase):
    """`python manage.py reconcile <session>` —
    docs/generated/NEXT-PHASE-RECONCILIATION-OBSERVABILITY-IMPLEMENTATION-REPORT.md.
    Confirmed a real, distinct trigger path this session (design audit,
    apps/sync/management/commands/reconcile.py) — never a Celery task, so
    last_run_task_id must always stay blank for this path."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='test_session')
        Chat.objects.create(session=self.session, provider_chat_id='000000000000000@lid')

    def test_records_management_command_trigger_source_and_blank_task_id(self):
        from unittest import mock

        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        with mock.patch('apps.sync.management.commands.reconcile.reconcile_session') as mocked:
            from apps.sync.reconciliation import reconcile_session as real_reconcile_session

            mocked.side_effect = lambda session_name, chat_ids=None, limit=100, max_pages=10, **kwargs: (
                real_reconcile_session(
                    session_name, chat_ids=chat_ids, limit=limit, max_pages=max_pages, waha_client=client,
                    **kwargs,
                )
            )
            call_command('reconcile', 'test_session', stdout=StringIO(), stderr=StringIO())

        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.last_run_trigger_source, SyncCheckpoint.TRIGGER_MANAGEMENT_COMMAND)
        self.assertEqual(checkpoint.last_run_task_id, '')

    def test_unknown_session_raises_command_error_without_creating_a_checkpoint(self):
        with self.assertRaises(CommandError):
            call_command('reconcile', 'does-not-exist', stdout=StringIO(), stderr=StringIO())
        self.assertEqual(SyncCheckpoint.objects.count(), 0)
