"""Phase 13 (Failure/security testing) Track A, scope item 3 — true
DB-level concurrency for webhook idempotency.

`test_ingestion.py`/`test_views.py` (Phase 3) already prove duplicate
webhook deliveries are idempotent, but every one of those tests sends the
same payload *sequentially* through Django's single-threaded test client —
that exercises the `get_or_create`/`UniqueConstraint` code path logically,
but never actually races two DB writers against each other. This module
does.

Why this can't just be a `TransactionTestCase` against the project's usual
`config.settings_test` (`:memory:` SQLite, see `config/settings_test.py`):
Django opens one real DB connection **per thread**, and a `:memory:`
SQLite database is private to the connection that created it. A second
thread's connection would see a completely separate, empty database — the
race this test needs to observe (two threads' unlocked pre-check SELECT in
`QuerySet.get_or_create()` both seeing "no row yet", then racing on the
transactional INSERT, with the loser required to catch `IntegrityError`
and recover) would never actually happen; it would silently look like a
pass without testing anything.

The fix used here: for this one `TransactionTestCase` only, `DATABASES` is
overridden (via `override_settings`, scoped to this class, restored for
every other test) to point at a real **on-disk** SQLite file instead of
`:memory:`. Separate threads' connections to the same file exhibit SQLite's
real file-locking/busy-retry behavior, which reproduces the same race
window Postgres has. This was verified empirically before writing this
test (see this task's implementation report for the raw multi-threaded
probe and its output) — plain `BEGIN IMMEDIATE`-style locking produces a
misleading `OperationalError` ("database is locked") that Django's
`get_or_create` does not encounter in practice; the actual
`get_or_create()` shape (unlocked read, then a transactional write that
can lose and must catch `IntegrityError`) reproduces a genuine, repeatable
`IntegrityError`-then-recover race on an on-disk file, which is what is
asserted below.

No live container is touched: this spins up its own throwaway SQLite file
in the OS temp directory, migrates the project's real schema into it, runs
the race, and deletes the file afterwards. Postgres/Redis/BFF/WAHA
containers are never contacted.
"""

import copy
import hashlib
import hmac
import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.test import Client, TransactionTestCase, override_settings

from apps.chats.models import Message
from apps.waha_sessions.models import WahaSession
from apps.webhooks.models import WebhookEvent
from apps.webhooks.tests.fixtures import INBOUND_MESSAGE_ENVELOPE

WEBHOOK_URL = '/api/webhooks/waha/'
TEST_SECRET = 'concurrency-test-webhook-secret'
CONCURRENT_REQUESTS = 8


def _sign(body_bytes: bytes) -> str:
    return hmac.new(TEST_SECRET.encode('utf-8'), body_bytes, hashlib.sha512).hexdigest()


def _on_disk_sqlite_databases(path: str) -> dict:
    cfg = copy.deepcopy(settings.DATABASES)
    cfg['default']['NAME'] = path
    cfg['default']['TEST'] = {'NAME': path}
    options = cfg['default'].setdefault('OPTIONS', {})
    # Generous busy-timeout (sqlite3.connect(..., timeout=...)) so a thread
    # that loses the initial write race waits for the winner to commit
    # instead of failing with a spurious "database is locked".
    options['timeout'] = 15
    return cfg


@override_settings(WAHA_WEBHOOK_HMAC_SECRET=TEST_SECRET)
class TrueConcurrencyDuplicateWebhookTests(TransactionTestCase):
    """Fires the identical webhook payload from `CONCURRENT_REQUESTS`
    threads at (as close to) the same instant, each through the real
    `/api/webhooks/waha/` view (full signature check + parsing + ingestion
    — not the service function called directly), and asserts the
    `UniqueConstraint(session, provider_event_id)` still results in
    exactly one processed `WebhookEvent` and exactly one `Message`, with
    every losing thread reaching a clean handled outcome rather than an
    unhandled 500/exception."""

    @classmethod
    def _bust_connection_handler_cache(cls):
        # Django explicitly documents DATABASES as one of the settings
        # override_settings() does NOT safely propagate
        # (django.test.signals.COMPLEX_OVERRIDE_SETTINGS includes
        # "DATABASES" for exactly this reason): django.db.connections is a
        # process-wide singleton whose `.settings` is a `cached_property`
        # that, on first access, both caches itself AND stashes the
        # resolved dict onto `self._settings`. Once `_settings` is no
        # longer None, `ConnectionHandler.configure_settings()` skips
        # re-reading `django.conf.settings.DATABASES` entirely and just
        # re-returns that same stale dict — so popping the cached_property
        # alone is NOT enough, `_settings` must also be reset to None.
        # Confirmed empirically this task: without ALL of the resets below,
        # override_settings above silently has no effect — every new
        # per-thread connection keeps resolving 'default' to the ORIGINAL
        # config.settings_test shared-cache `:memory:` database, which
        # under real concurrent writers surfaces as a spurious
        # `OperationalError: database table is locked` (SQLite shared-cache
        # mode has no working busy-retry for table-level lock conflicts in
        # Python's sqlite3 module) rather than the genuine,
        # cleanly-recoverable IntegrityError race this test exists to
        # exercise.
        connections._settings = None
        connections.__dict__.pop('settings', None)
        connections.close_all()
        # close_all() only closes the underlying DB-API connection on each
        # already-created per-thread DatabaseWrapper — the wrapper OBJECT
        # itself (and its own captured settings_dict, read once at
        # creation) is left in place and would be reused as-is. The
        # CURRENT thread (main test thread, which just ran migrate()/will
        # create fixtures) must have its cached wrapper actually removed
        # so the next access constructs a brand new one from the
        # now-current settings. Other threads that have never touched
        # 'default' yet need no action here — they build their own fresh
        # wrapper lazily on first use.
        try:
            del connections['default']
        except AttributeError:
            pass

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp_dir = tempfile.mkdtemp(prefix='wamora-webhook-concurrency-')
        cls._db_path = os.path.join(cls._tmp_dir, 'concurrency.sqlite3')
        cls._databases_override = override_settings(DATABASES=_on_disk_sqlite_databases(cls._db_path))
        cls._databases_override.enable()
        cls._bust_connection_handler_cache()
        call_command('migrate', verbosity=0, interactive=False)

    @classmethod
    def tearDownClass(cls):
        connections.close_all()
        cls._databases_override.disable()
        cls._bust_connection_handler_cache()
        super().tearDownClass()
        try:
            os.remove(cls._db_path)
        except OSError:
            pass
        try:
            os.rmdir(cls._tmp_dir)
        except OSError:
            pass

    def setUp(self):
        # Pre-created single-threaded, deliberately: WahaSession.name is
        # itself unique, and get_or_create()-ing the session concurrently
        # too would confound the one race this test targets (the webhook
        # event's own UniqueConstraint) with an unrelated one.
        self.session = WahaSession.objects.create(name='concurrency-test-session')

    def test_concurrent_identical_webhook_deliveries_produce_exactly_one_processed_event(self):
        envelope = copy.deepcopy(INBOUND_MESSAGE_ENVELOPE)
        envelope['session'] = self.session.name
        body = json.dumps(envelope).encode()
        signature = _sign(body)

        barrier = threading.Barrier(CONCURRENT_REQUESTS)
        responses = []
        exceptions = []
        lock = threading.Lock()

        def worker():
            client = Client()
            try:
                barrier.wait(timeout=10)
                response = client.post(
                    WEBHOOK_URL, data=body, content_type='application/json', HTTP_X_WEBHOOK_HMAC=signature
                )
                with lock:
                    responses.append(response.status_code)
            except Exception as exc:  # noqa: BLE001 — the whole point: prove nothing escapes unhandled.
                with lock:
                    exceptions.append(repr(exc))
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as pool:
            futures = [pool.submit(worker) for _ in range(CONCURRENT_REQUESTS)]
            for future in as_completed(futures):
                future.result()

        self.assertEqual(exceptions, [], f'unhandled exception(s) from concurrent delivery: {exceptions}')
        self.assertEqual(
            responses,
            [200] * CONCURRENT_REQUESTS,
            'every concurrent delivery of the same webhook must get a clean handled response, not a crash',
        )

        webhook_events = list(WebhookEvent.objects.filter(session=self.session))
        self.assertEqual(
            len(webhook_events), 1, f'expected exactly one WebhookEvent row, found {len(webhook_events)}'
        )
        self.assertEqual(webhook_events[0].status, WebhookEvent.STATUS_PROCESSED)
        self.assertEqual(webhook_events[0].provider_event_id, envelope['payload']['id'])

        messages = list(Message.objects.filter(session=self.session))
        self.assertEqual(len(messages), 1, f'expected exactly one Message row (no duplicate send), found {len(messages)}')
        self.assertEqual(messages[0].provider_message_id, envelope['payload']['id'])
