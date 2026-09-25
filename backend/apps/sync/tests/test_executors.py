from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings

from apps.chats.models import Chat, Message
from apps.sync.executors import run_targeted_reconciliation_with_retry, trigger_reconciliation
from apps.sync.models import SyncCheckpoint
from apps.sync.tests.fixtures import REST_INBOUND_MESSAGE_1
from apps.waha_sessions.models import WahaSession


class SequentialStubWahaClient:
    """Returns one entry from `pages` per call (ignoring limit/offset),
    then empty lists forever after `pages` is exhausted — deliberately
    simpler than the shared StubWahaClient, only used here to test the
    retry loop's stop-as-soon-as-found behavior, not real pagination."""

    def __init__(self, pages):
        self._pages = list(pages)
        self.call_count = 0

    def fetch_chat_messages(self, session, chat_id, limit=100, offset=0):
        self.call_count += 1
        if self._pages:
            return self._pages.pop(0)
        return []

    def fetch_chats(self, session):
        return []


class RunTargetedReconciliationWithRetryTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='test_session')
        Chat.objects.create(session=self.session, provider_chat_id='000000000000000@lid')

    def test_finds_message_on_first_attempt_no_sleep_needed(self):
        client = SequentialStubWahaClient([[REST_INBOUND_MESSAGE_1]])
        with mock.patch('apps.sync.executors.time.sleep') as mocked_sleep:
            result = run_targeted_reconciliation_with_retry(
                'test_session', '000000000000000@lid', waha_client=client
            )
        self.assertEqual(result.messages_inserted, 1)
        self.assertEqual(client.call_count, 1)
        mocked_sleep.assert_not_called()

    def test_retries_until_message_appears_then_stops(self):
        client = SequentialStubWahaClient([[], [], [REST_INBOUND_MESSAGE_1]])
        with mock.patch('apps.sync.executors.time.sleep') as mocked_sleep:
            result = run_targeted_reconciliation_with_retry(
                'test_session', '000000000000000@lid', waha_client=client
            )
        self.assertEqual(result.messages_inserted, 1)
        self.assertEqual(client.call_count, 3)
        self.assertEqual(mocked_sleep.call_count, 2)

    def test_gives_up_cleanly_after_max_attempts_with_nothing_found(self):
        client = SequentialStubWahaClient([])
        with mock.patch('apps.sync.executors.time.sleep') as mocked_sleep:
            result = run_targeted_reconciliation_with_retry(
                'test_session', '000000000000000@lid', waha_client=client
            )
        self.assertEqual(result.messages_inserted, 0)
        self.assertEqual(client.call_count, 3)
        # Never sleeps after the LAST attempt — exactly attempts-1 sleeps.
        self.assertEqual(mocked_sleep.call_count, 2)

    def test_never_inserts_duplicate_message_across_retries(self):
        # Same message present on every attempt (simulates it having been
        # available all along) — repeated calls must stay duplicate-safe.
        client = SequentialStubWahaClient(
            [[REST_INBOUND_MESSAGE_1], [REST_INBOUND_MESSAGE_1], [REST_INBOUND_MESSAGE_1]]
        )
        with mock.patch('apps.sync.executors.time.sleep'):
            run_targeted_reconciliation_with_retry('test_session', '000000000000000@lid', waha_client=client)
        self.assertEqual(
            Message.objects.filter(provider_message_id=REST_INBOUND_MESSAGE_1['id']).count(), 1
        )

    def test_records_targeted_trigger_source_and_given_task_id(self):
        # docs/generated/NEXT-PHASE-RECONCILIATION-OBSERVABILITY-IMPLEMENTATION-REPORT.md.
        # This helper is shared by both executors (module docstring) — its
        # own trigger_source is always TRIGGER_TARGETED; task_id is
        # whatever its caller passes (default '' for the sync executor).
        client = SequentialStubWahaClient([[REST_INBOUND_MESSAGE_1]])
        with mock.patch('apps.sync.executors.time.sleep'):
            run_targeted_reconciliation_with_retry(
                'test_session', '000000000000000@lid', waha_client=client, task_id='celery-task-id',
            )
        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.last_run_trigger_source, SyncCheckpoint.TRIGGER_TARGETED)
        self.assertEqual(checkpoint.last_run_task_id, 'celery-task-id')

    def test_task_id_defaults_to_blank_for_the_sync_executor(self):
        client = SequentialStubWahaClient([[REST_INBOUND_MESSAGE_1]])
        with mock.patch('apps.sync.executors.time.sleep'):
            run_targeted_reconciliation_with_retry('test_session', '000000000000000@lid', waha_client=client)
        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.last_run_trigger_source, SyncCheckpoint.TRIGGER_TARGETED)
        self.assertEqual(checkpoint.last_run_task_id, '')


@override_settings(RECONCILIATION_EXECUTOR='sync')
class TriggerReconciliationSyncExecutorTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='test_session')
        Chat.objects.create(session=self.session, provider_chat_id='000000000000000@lid')

    def test_dispatches_to_run_targeted_reconciliation_with_retry(self):
        with mock.patch('apps.sync.executors.run_targeted_reconciliation_with_retry') as mocked:
            mocked.return_value = 'sentinel-result'
            result = trigger_reconciliation('test_session', '000000000000000@lid')
        mocked.assert_called_once_with('test_session', '000000000000000@lid')
        self.assertEqual(result, 'sentinel-result')

    def test_does_not_enqueue_a_celery_task(self):
        # No real WahaClient must be constructed here — reconcile_session
        # is mocked entirely, the same way the celery-executor tests below
        # avoid any real network call.
        with mock.patch('apps.sync.tasks.reconcile_chat_task.delay') as mocked_delay:
            with mock.patch('apps.sync.executors.reconcile_session') as mocked_reconcile:
                mocked_reconcile.return_value.messages_inserted = 1
                trigger_reconciliation('test_session', '000000000000000@lid')
        mocked_delay.assert_not_called()


@override_settings(RECONCILIATION_EXECUTOR='celery')
class TriggerReconciliationCeleryExecutorTests(TestCase):
    def test_enqueues_reconcile_chat_task_and_returns_none(self):
        with mock.patch('apps.sync.tasks.reconcile_chat_task.delay') as mocked_delay:
            result = trigger_reconciliation('test_session', '000000000000000@lid')
        mocked_delay.assert_called_once_with('test_session', '000000000000000@lid')
        self.assertIsNone(result)

    def test_does_not_run_reconciliation_synchronously(self):
        with mock.patch('apps.sync.tasks.reconcile_chat_task.delay'):
            with mock.patch('apps.sync.executors.reconcile_session') as mocked_reconcile:
                trigger_reconciliation('test_session', '000000000000000@lid')
        mocked_reconcile.assert_not_called()


@override_settings(RECONCILIATION_EXECUTOR='bogus-value')
class TriggerReconciliationInvalidExecutorTests(TestCase):
    def test_raises_improperly_configured_rather_than_silently_falling_back(self):
        with self.assertRaises(ImproperlyConfigured):
            trigger_reconciliation('test_session', '000000000000000@lid')
