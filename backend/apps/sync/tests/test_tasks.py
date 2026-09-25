from unittest import mock

from django.test import TestCase, override_settings

from apps.chats.models import Chat, Message
from apps.sync.models import SyncCheckpoint
from apps.sync.reconciliation import ReconciliationResult
from apps.sync.tasks import reconcile_all_sessions_task, reconcile_chat_task, reconcile_session_task
from apps.sync.tests.test_reconciliation import StubWahaClient
from apps.sync.tests.fixtures import REST_INBOUND_MESSAGE_1
from apps.waha_sessions.models import WahaSession
from config.celery import app as celery_app


class CeleryAppInitializationTests(TestCase):
    """Celery app must initialize and correctly discover this project's
    tasks. Note: Celery's autodiscover_tasks() is lazy — it is normally
    triggered by a worker's own startup sequence. In-process, it must be
    forced via app.loader.import_default_modules() (confirmed the correct
    trigger — see docs/generated/PHASE-5-CELERY-REDIS.md)."""

    def test_app_initializes(self):
        self.assertIsNotNone(celery_app)
        self.assertEqual(celery_app.main, 'waha_monitoring')

    def test_tasks_are_discovered(self):
        celery_app.loader.import_default_modules()
        task_names = set(celery_app.tasks.keys())
        self.assertIn('apps.sync.tasks.reconcile_session_task', task_names)
        self.assertIn('apps.sync.tasks.reconcile_all_sessions_task', task_names)

    def test_task_registration_names_match_dotted_path(self):
        self.assertEqual(reconcile_session_task.name, 'apps.sync.tasks.reconcile_session_task')
        self.assertEqual(reconcile_all_sessions_task.name, 'apps.sync.tasks.reconcile_all_sessions_task')

    def test_broker_and_serialization_configuration(self):
        self.assertTrue(celery_app.conf.broker_url)
        self.assertEqual(celery_app.conf.task_serializer, 'json')
        self.assertEqual(celery_app.conf.result_serializer, 'json')
        self.assertEqual(celery_app.conf.accept_content, ['json'])
        self.assertEqual(celery_app.conf.timezone, 'UTC')

    def test_beat_schedule_includes_reconciliation(self):
        celery_app.loader.import_default_modules()
        celery_app.finalize()
        schedule = celery_app.conf.beat_schedule
        self.assertIn('reconcile-all-sessions', schedule)
        self.assertEqual(
            schedule['reconcile-all-sessions']['task'], 'apps.sync.tasks.reconcile_all_sessions_task'
        )


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class ReconcileSessionTaskTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='test_session')
        Chat.objects.create(session=self.session, provider_chat_id='000000000000000@lid')

    def test_task_executes_successfully_and_returns_summary(self):
        with mock.patch('apps.sync.tasks.reconcile_session') as mocked:
            mocked.return_value = ReconciliationResult()
            mocked.return_value.chats_processed = 1
            mocked.return_value.messages_inserted = 2

            async_result = reconcile_session_task.delay('test_session')

            self.assertTrue(async_result.successful())
            payload = async_result.result
            self.assertEqual(payload['session_name'], 'test_session')
            self.assertEqual(payload['chats_processed'], 1)
            self.assertEqual(payload['messages_inserted'], 2)
            self.assertFalse(payload['had_error'])

    def test_task_actually_persists_via_real_reconcile_session(self):
        # Integration-style: real reconcile_session, only the WAHA client
        # is stubbed — proves the task correctly delegates to, rather than
        # duplicates, the Phase 4 service layer.
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        with mock.patch('apps.sync.tasks.reconcile_session', wraps=None) as mocked:
            from apps.sync.reconciliation import reconcile_session as real_reconcile_session

            mocked.side_effect = lambda session_name, limit=100, max_pages=10, **kwargs: real_reconcile_session(
                session_name, limit=limit, max_pages=max_pages, waha_client=client
            )
            reconcile_session_task.delay('test_session')

        self.assertTrue(
            Message.objects.filter(
                session=self.session, provider_message_id=REST_INBOUND_MESSAGE_1['id']
            ).exists()
        )

    def test_rerunning_task_does_not_duplicate_durable_records(self):
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})

        def call_real(session_name, limit=100, max_pages=10, **kwargs):
            from apps.sync.reconciliation import reconcile_session as real_reconcile_session

            return real_reconcile_session(session_name, limit=limit, max_pages=max_pages, waha_client=client)

        with mock.patch('apps.sync.tasks.reconcile_session', side_effect=call_real):
            reconcile_session_task.delay('test_session')
            reconcile_session_task.delay('test_session')

        self.assertEqual(
            Message.objects.filter(provider_message_id=REST_INBOUND_MESSAGE_1['id']).count(), 1
        )

    def test_task_failure_is_observable_not_silently_swallowed(self):
        # Under CELERY_TASK_ALWAYS_EAGER with retry_backoff configured,
        # Celery raises celery.exceptions.Retry rather than looping
        # synchronously (backoff implies a real delay, which eager mode
        # does not simulate by sleeping) — this IS the correct, real
        # behavior, not a test workaround. It proves the failure is
        # observable: autoretry_for caught it and engaged the retry
        # policy rather than letting it disappear.
        from celery.exceptions import Retry

        with mock.patch('apps.sync.tasks.reconcile_session', side_effect=RuntimeError('boom')) as mocked:
            with self.assertRaises(Retry):
                reconcile_session_task.delay('test_session')
        mocked.assert_called_once()

    def test_records_periodic_trigger_source_and_real_task_id(self):
        # docs/generated/NEXT-PHASE-RECONCILIATION-OBSERVABILITY-IMPLEMENTATION-REPORT.md.
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        with mock.patch('apps.sync.tasks.reconcile_session', wraps=None) as mocked:
            from apps.sync.reconciliation import reconcile_session as real_reconcile_session

            mocked.side_effect = lambda session_name, limit=100, max_pages=10, **kwargs: real_reconcile_session(
                session_name, limit=limit, max_pages=max_pages, waha_client=client, **kwargs
            )
            reconcile_session_task.delay('test_session')

        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.last_run_trigger_source, SyncCheckpoint.TRIGGER_PERIODIC)
        self.assertTrue(checkpoint.last_run_task_id)  # a real, non-empty Celery task id

    def test_retry_policy_is_bounded(self):
        self.assertEqual(reconcile_session_task.max_retries, 3)
        self.assertEqual(reconcile_session_task.autoretry_for, (Exception,))

    def test_worker_style_redelivery_after_retry_eventually_succeeds(self):
        # Simulates what a real worker does on a retried task: re-invoke
        # the task body again later. Confirms that once the transient
        # condition clears, a subsequent delivery completes successfully —
        # without depending on eager mode simulating the backoff sleep
        # itself, which it deliberately does not do.
        from celery.exceptions import Retry

        with mock.patch('apps.sync.tasks.reconcile_session', side_effect=RuntimeError('transient')):
            with self.assertRaises(Retry):
                reconcile_session_task.delay('test_session')

        with mock.patch('apps.sync.tasks.reconcile_session') as mocked:
            mocked.return_value = ReconciliationResult()
            async_result = reconcile_session_task.delay('test_session')

        self.assertTrue(async_result.successful())


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class ReconcileChatTaskTests(TestCase):
    """The `RECONCILIATION_EXECUTOR=celery` counterpart to the `sync`
    executor's in-process call — docs/generated/
    INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md. Delegates
    entirely to apps.sync.executors.run_targeted_reconciliation_with_retry,
    the exact same function the `sync` executor calls directly — this
    task adds no reconciliation logic of its own."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='test_session')
        Chat.objects.create(session=self.session, provider_chat_id='000000000000000@lid')

    def test_delegates_to_run_targeted_reconciliation_with_retry(self):
        with mock.patch('apps.sync.tasks.run_targeted_reconciliation_with_retry') as mocked:
            mocked.return_value = ReconciliationResult()
            mocked.return_value.messages_inserted = 1

            async_result = reconcile_chat_task.delay('test_session', '000000000000000@lid')

        # task_id is the task's own real self.request.id (a fresh UUID per
        # run) — asserted as "some string", not a specific value.
        mocked.assert_called_once_with('test_session', '000000000000000@lid', task_id=mock.ANY)
        self.assertIsInstance(mocked.call_args.kwargs['task_id'], str)
        self.assertTrue(mocked.call_args.kwargs['task_id'])
        self.assertTrue(async_result.successful())
        payload = async_result.result
        self.assertEqual(payload['session_name'], 'test_session')
        self.assertEqual(payload['chat_id'], '000000000000000@lid')
        self.assertEqual(payload['messages_inserted'], 1)

    def test_actually_persists_via_the_real_shared_retry_helper(self):
        # Integration-style: real run_targeted_reconciliation_with_retry
        # (and therefore real reconcile_session), only the WAHA client is
        # stubbed — proves this task delegates to, rather than
        # duplicates, the shared executor logic.
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        with mock.patch('apps.sync.tasks.run_targeted_reconciliation_with_retry') as mocked:
            from apps.sync.executors import run_targeted_reconciliation_with_retry as real_helper

            mocked.side_effect = lambda session_name, chat_id, **kwargs: real_helper(
                session_name, chat_id, waha_client=client
            )
            reconcile_chat_task.delay('test_session', '000000000000000@lid')

        self.assertTrue(
            Message.objects.filter(
                session=self.session, provider_message_id=REST_INBOUND_MESSAGE_1['id']
            ).exists()
        )

    def test_records_targeted_trigger_source_and_real_task_id(self):
        client = StubWahaClient({'000000000000000@lid': [REST_INBOUND_MESSAGE_1]})
        with mock.patch('apps.sync.tasks.run_targeted_reconciliation_with_retry') as mocked:
            from apps.sync.executors import run_targeted_reconciliation_with_retry as real_helper

            mocked.side_effect = lambda session_name, chat_id, **kwargs: real_helper(
                session_name, chat_id, waha_client=client, **kwargs
            )
            reconcile_chat_task.delay('test_session', '000000000000000@lid')

        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.last_run_trigger_source, SyncCheckpoint.TRIGGER_TARGETED)
        self.assertTrue(checkpoint.last_run_task_id)  # a real, non-empty Celery task id


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class ReconcileAllSessionsTaskTests(TestCase):
    def test_dispatches_one_task_per_known_session(self):
        WahaSession.objects.create(name='session-a')
        WahaSession.objects.create(name='session-b')

        with mock.patch('apps.sync.tasks.reconcile_session_task.delay') as mocked_delay:
            result = reconcile_all_sessions_task.delay()

        self.assertEqual(result.result['sessions_dispatched'], 2)
        dispatched_names = {call.args[0] for call in mocked_delay.call_args_list}
        self.assertEqual(dispatched_names, {'session-a', 'session-b'})

    def test_no_sessions_dispatches_nothing(self):
        with mock.patch('apps.sync.tasks.reconcile_session_task.delay') as mocked_delay:
            result = reconcile_all_sessions_task.delay()

        self.assertEqual(result.result['sessions_dispatched'], 0)
        mocked_delay.assert_not_called()
