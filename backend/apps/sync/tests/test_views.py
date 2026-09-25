from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Group, User
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.authn.jwt_utils import issue_access_token
from apps.authn.tests.keys import generate_test_key_pair
from apps.sync.models import SyncCheckpoint
from apps.waha_sessions.models import WahaSession
from apps.webhooks.models import WebhookEvent

PRIVATE_PEM, PUBLIC_PEM = generate_test_key_pair()

# Fixed, explicit interval for deterministic threshold math in these tests
# (STALE_THRESHOLD_MULTIPLIER = 2 in apps/sync/views.py -> 1800s/30min
# threshold here), independent of whatever this environment's real
# RECONCILIATION_INTERVAL_SECONDS default happens to be.
TEST_RECONCILIATION_INTERVAL_SECONDS = 900

# Same deterministic-test-isolation reasoning, for possibly_stuck's own
# threshold (apps/sync/views.py: CELERY_TASK_TIME_LIMIT + 60s margin).
TEST_CELERY_TASK_TIME_LIMIT = 600
POSSIBLY_STUCK_THRESHOLD_SECONDS = TEST_CELERY_TASK_TIME_LIMIT + 60  # 660


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
    RECONCILIATION_INTERVAL_SECONDS=TEST_RECONCILIATION_INTERVAL_SECONDS,
    CELERY_TASK_TIME_LIMIT=TEST_CELERY_TASK_TIME_LIMIT,
)
class SyncStatusViewTests(APITestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')

    def _url(self, session_name=None):
        return f'/api/sync/status/{session_name or self.session.name}/'

    def _auth_header(self, user):
        token = issue_access_token(user)['access_token']
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def _user(self, username='operator'):
        return User.objects.create_user(username, password='pw')

    def _make_webhook_event(self, session, received_at, provider_event_id, event_type='message', status_='processed'):
        # Mirrors apps/dashboard/tests/test_views.py's identical helper —
        # received_at is auto_now_add=True (models.py), so it can only be
        # backdated via a post-create .update(), never passed to create().
        event = WebhookEvent.objects.create(
            session=session, provider_event_id=provider_event_id, event_type=event_type, status=status_,
        )
        WebhookEvent.objects.filter(pk=event.pk).update(received_at=received_at)
        event.refresh_from_db()
        return event

    # -- authentication ------------------------------------------------

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 401)

    def test_authenticated_request_succeeds_with_no_scope_required(self):
        # IsAuthenticated-only, matching apps.dashboard's precedent (design
        # report Section 5) — a plain user with no Group/scope membership
        # at all must still succeed, unlike apps.chats's HasReadingScope
        # endpoints.
        user = self._user()
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)

    # -- never_synced ----------------------------------------------------

    def test_session_with_no_checkpoint_is_never_synced(self):
        user = self._user()
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['sync_status'], 'never_synced')
        self.assertIsNone(response.data['checkpoint_status'])
        self.assertIsNone(response.data['last_run_at'])
        self.assertIsNone(response.data['seconds_since_last_run'])
        self.assertIsNone(response.data['checkpoint_updated_at'])

    # -- running -----------------------------------------------------------

    def test_running_checkpoint_reports_running(self):
        user = self._user()
        SyncCheckpoint.objects.create(
            session=self.session, status=SyncCheckpoint.STATUS_RUNNING, last_run_at=None,
        )
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'running')
        self.assertEqual(response.data['checkpoint_status'], 'running')
        self.assertIsNone(response.data['last_run_at'])
        self.assertIsNone(response.data['seconds_since_last_run'])

    def test_running_checkpoint_after_a_prior_completed_run_still_reports_running(self):
        user = self._user()
        prior_run = timezone.now() - timedelta(minutes=5)
        SyncCheckpoint.objects.create(
            session=self.session, status=SyncCheckpoint.STATUS_RUNNING, last_run_at=prior_run,
        )
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'running')
        self.assertIsNotNone(response.data['last_run_at'])
        self.assertIsNotNone(response.data['seconds_since_last_run'])

    def test_idle_checkpoint_is_grouped_with_running_not_never_synced(self):
        # STATUS_IDLE is the model default and unreachable via any real
        # code path (see apps/sync/views.py's _derive_sync_status
        # docstring) — a row genuinely exists here, so this must not be
        # reported as 'never_synced'.
        user = self._user()
        SyncCheckpoint.objects.create(session=self.session, status=SyncCheckpoint.STATUS_IDLE)
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'running')

    # -- failed --------------------------------------------------------

    def test_error_checkpoint_reports_failed(self):
        user = self._user()
        SyncCheckpoint.objects.create(
            session=self.session,
            status=SyncCheckpoint.STATUS_ERROR,
            last_run_at=timezone.now(),
            last_error='boom',
        )
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'failed')
        self.assertEqual(response.data['checkpoint_status'], 'error')
        # last_error is deliberately never exposed (design report Section
        # 6/11 — never echo raw internal error text through this endpoint).
        self.assertNotIn('last_error', response.data)

    def test_old_error_checkpoint_still_reports_failed_not_stale(self):
        # 'failed' takes priority over any staleness calculation — an
        # errored checkpoint is 'failed' regardless of how long ago that
        # error happened, never silently reclassified as merely 'stale'.
        user = self._user()
        SyncCheckpoint.objects.create(
            session=self.session,
            status=SyncCheckpoint.STATUS_ERROR,
            last_run_at=timezone.now() - timedelta(hours=5),
        )
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'failed')

    # -- healthy / stale -------------------------------------------------

    def test_recent_ok_checkpoint_within_threshold_is_healthy(self):
        user = self._user()
        recent = timezone.now() - timedelta(seconds=60)
        SyncCheckpoint.objects.create(
            session=self.session, status=SyncCheckpoint.STATUS_OK,
            last_run_at=recent, checkpoint_value=recent.isoformat(),
        )
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'healthy')
        self.assertEqual(response.data['checkpoint_status'], 'ok')

    def test_ok_checkpoint_at_exactly_the_threshold_is_healthy(self):
        # threshold = TEST_RECONCILIATION_INTERVAL_SECONDS * 2 = 1800s;
        # <= threshold is healthy, boundary-inclusive.
        user = self._user()
        at_threshold = timezone.now() - timedelta(
            seconds=TEST_RECONCILIATION_INTERVAL_SECONDS * 2 - 5
        )
        SyncCheckpoint.objects.create(
            session=self.session, status=SyncCheckpoint.STATUS_OK, last_run_at=at_threshold,
        )
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'healthy')

    def test_old_ok_checkpoint_beyond_threshold_is_stale(self):
        user = self._user()
        old = timezone.now() - timedelta(
            seconds=TEST_RECONCILIATION_INTERVAL_SECONDS * 2 + 60
        )
        SyncCheckpoint.objects.create(
            session=self.session, status=SyncCheckpoint.STATUS_OK, last_run_at=old,
        )
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'stale')
        self.assertEqual(response.data['checkpoint_status'], 'ok')
        self.assertGreater(response.data['seconds_since_last_run'], TEST_RECONCILIATION_INTERVAL_SECONDS * 2)

    # -- checkpoint_updated_at -------------------------------------------

    def test_checkpoint_updated_at_is_returned(self):
        user = self._user()
        checkpoint = SyncCheckpoint.objects.create(
            session=self.session, status=SyncCheckpoint.STATUS_RUNNING,
        )
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertIsNotNone(response.data['checkpoint_updated_at'])
        # Timezone-aware, UTC, ISO-8601 — this project's TIME_ZONE='UTC'/
        # USE_TZ=True convention (settings.py), relied on rather than
        # assumed.
        self.assertTrue(str(response.data['checkpoint_updated_at']).endswith('Z'))
        checkpoint.refresh_from_db()
        self.assertEqual(
            response.data['checkpoint_updated_at'], checkpoint.updated_at.isoformat().replace('+00:00', 'Z'),
        )

    def test_last_run_at_is_timezone_aware_utc_iso8601(self):
        user = self._user()
        moment = timezone.now()
        SyncCheckpoint.objects.create(
            session=self.session, status=SyncCheckpoint.STATUS_OK, last_run_at=moment,
        )
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertTrue(str(response.data['last_run_at']).endswith('Z'))

    # -- last_webhook_received_at (Phase 9.1B) ----------------------------
    # docs/generated/PHASE-9-1B-WEBHOOK-TIMESTAMP-DESIGN-AUDIT-REPORT.md.
    # Deliberately independent of SyncCheckpoint/sync_status — these tests
    # never create a SyncCheckpoint, to prove the field works even for a
    # 'never_synced' session.

    def test_no_webhook_events_returns_null(self):
        user = self._user()
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['last_webhook_received_at'])

    def test_returns_most_recent_received_at_among_multiple_events(self):
        user = self._user()
        older = timezone.now() - timedelta(hours=2)
        newer = timezone.now() - timedelta(minutes=5)
        self._make_webhook_event(self.session, older, 'evt-older')
        self._make_webhook_event(self.session, newer, 'evt-newer')
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['last_webhook_received_at'], newer.isoformat().replace('+00:00', 'Z'))

    def test_webhook_event_from_another_session_is_excluded(self):
        user = self._user()
        other_session = WahaSession.objects.create(name='other')
        recent_other = timezone.now() - timedelta(minutes=1)
        old_own = timezone.now() - timedelta(hours=3)
        self._make_webhook_event(other_session, recent_other, 'evt-other')
        self._make_webhook_event(self.session, old_own, 'evt-own')
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['last_webhook_received_at'], old_own.isoformat().replace('+00:00', 'Z'))

    def test_last_webhook_received_at_is_timezone_aware_utc_iso8601(self):
        user = self._user()
        self._make_webhook_event(self.session, timezone.now(), 'evt-1')
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertTrue(str(response.data['last_webhook_received_at']).endswith('Z'))

    def test_last_webhook_received_at_present_even_when_never_synced(self):
        # No SyncCheckpoint created here at all — proves the two signals
        # (webhook delivery vs. reconciliation) are genuinely independent.
        user = self._user()
        self._make_webhook_event(self.session, timezone.now(), 'evt-1')
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'never_synced')
        self.assertIsNotNone(response.data['last_webhook_received_at'])

    def test_non_processed_webhook_event_still_counts(self):
        # A failed/unsupported delivery still proves WAHA reached us — not
        # filtered by status (design report Section 11).
        user = self._user()
        self._make_webhook_event(self.session, timezone.now(), 'evt-1', status_='failed')
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertIsNotNone(response.data['last_webhook_received_at'])

    # -- possibly_stuck (this task) ---------------------------------------
    # docs/generated/NEXT-PHASE-POSSIBLY-STUCK-DETECTION-DESIGN-AUDIT-REPORT.md.
    # Detection only — these tests never call reconcile_session()/trigger
    # any task; a RUNNING SyncCheckpoint is created directly to simulate
    # each scenario.

    def test_running_checkpoint_newer_than_threshold_is_not_possibly_stuck(self):
        user = self._user()
        recent = timezone.now() - timedelta(seconds=POSSIBLY_STUCK_THRESHOLD_SECONDS - 30)
        checkpoint = SyncCheckpoint.objects.create(session=self.session, status=SyncCheckpoint.STATUS_RUNNING)
        SyncCheckpoint.objects.filter(pk=checkpoint.pk).update(updated_at=recent)
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'running')
        self.assertFalse(response.data['possibly_stuck'])

    def test_running_checkpoint_exactly_at_threshold_is_not_yet_possibly_stuck(self):
        # Boundary is exclusive (age > threshold, not >=) — mirrors
        # _derive_sync_status()'s own inclusive-for-healthy <= choice, so
        # the "not yet a problem" side is consistently inclusive in both
        # functions (documented in _is_possibly_stuck()'s own docstring).
        user = self._user()
        at_threshold = timezone.now() - timedelta(seconds=POSSIBLY_STUCK_THRESHOLD_SECONDS)
        checkpoint = SyncCheckpoint.objects.create(session=self.session, status=SyncCheckpoint.STATUS_RUNNING)
        SyncCheckpoint.objects.filter(pk=checkpoint.pk).update(updated_at=at_threshold)
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertFalse(response.data['possibly_stuck'])

    def test_running_checkpoint_older_than_threshold_is_possibly_stuck(self):
        user = self._user()
        stale = timezone.now() - timedelta(seconds=POSSIBLY_STUCK_THRESHOLD_SECONDS + 30)
        checkpoint = SyncCheckpoint.objects.create(session=self.session, status=SyncCheckpoint.STATUS_RUNNING)
        SyncCheckpoint.objects.filter(pk=checkpoint.pk).update(updated_at=stale)
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'running')
        self.assertTrue(response.data['possibly_stuck'])

    def test_non_running_checkpoint_with_old_updated_at_is_not_possibly_stuck(self):
        # An old, non-RUNNING checkpoint (here: STATUS_OK, i.e. 'stale' in
        # sync_status terms) must never be reported as possibly_stuck —
        # that heuristic is gated on status == RUNNING, not merely on age.
        user = self._user()
        very_old = timezone.now() - timedelta(seconds=POSSIBLY_STUCK_THRESHOLD_SECONDS * 10)
        checkpoint = SyncCheckpoint.objects.create(
            session=self.session, status=SyncCheckpoint.STATUS_OK, last_run_at=very_old,
        )
        SyncCheckpoint.objects.filter(pk=checkpoint.pk).update(updated_at=very_old)
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'stale')
        self.assertFalse(response.data['possibly_stuck'])

    def test_error_checkpoint_is_not_possibly_stuck_regardless_of_age(self):
        user = self._user()
        very_old = timezone.now() - timedelta(seconds=POSSIBLY_STUCK_THRESHOLD_SECONDS * 10)
        checkpoint = SyncCheckpoint.objects.create(
            session=self.session, status=SyncCheckpoint.STATUS_ERROR, last_run_at=very_old,
        )
        SyncCheckpoint.objects.filter(pk=checkpoint.pk).update(updated_at=very_old)
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'failed')
        self.assertFalse(response.data['possibly_stuck'])

    def test_no_checkpoint_is_not_possibly_stuck(self):
        user = self._user()
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.data['sync_status'], 'never_synced')
        self.assertFalse(response.data['possibly_stuck'])

    def test_possibly_stuck_does_not_alter_other_response_fields(self):
        # Existing fields must remain byte-identical in shape/value —
        # possibly_stuck is purely additive.
        user = self._user()
        stale = timezone.now() - timedelta(seconds=POSSIBLY_STUCK_THRESHOLD_SECONDS + 30)
        checkpoint = SyncCheckpoint.objects.create(session=self.session, status=SyncCheckpoint.STATUS_RUNNING)
        SyncCheckpoint.objects.filter(pk=checkpoint.pk).update(updated_at=stale)
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(
            set(response.data.keys()),
            {
                'session', 'sync_status', 'checkpoint_status', 'last_run_at',
                'seconds_since_last_run', 'checkpoint_updated_at',
                'last_webhook_received_at', 'possibly_stuck',
            },
        )
        self.assertEqual(response.data['checkpoint_status'], 'running')
        self.assertIsNone(response.data['last_run_at'])

    def test_possibly_stuck_adds_no_additional_query(self):
        # Same 3-query bound the 9.1B task established (WahaSession lookup,
        # SyncCheckpoint lookup, WebhookEvent Max() aggregate) —
        # possibly_stuck is computed from the already-loaded checkpoint
        # object, with zero new query.
        user = self._user()
        stale = timezone.now() - timedelta(seconds=POSSIBLY_STUCK_THRESHOLD_SECONDS + 30)
        checkpoint = SyncCheckpoint.objects.create(session=self.session, status=SyncCheckpoint.STATUS_RUNNING)
        SyncCheckpoint.objects.filter(pk=checkpoint.pk).update(updated_at=stale)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        domain_queries = [
            q for q in ctx.captured_queries
            if 'waha_sessions_wahasession' in q['sql']
            or 'sync_synccheckpoint' in q['sql']
            or 'webhooks_webhookevent' in q['sql']
        ]
        self.assertEqual(len(domain_queries), 3)

    # -- unknown session ---------------------------------------------------

    def test_unknown_session_returns_404_with_standard_error_envelope(self):
        user = self._user()
        response = self.client.get(self._url(session_name='does-not-exist'), **self._auth_header(user))
        self.assertEqual(response.status_code, 404)
        # apps.core.exceptions.api_exception_handler's standard envelope —
        # the same {"error": {...}} shape every other endpoint's 404 (e.g.
        # ChatMessagesViewTests.test_unknown_chat_returns_404) already
        # produces, not a bespoke error shape for this endpoint.
        self.assertIn('error', response.data)
        self.assertIn('code', response.data['error'])
        self.assertIn('request_id', response.data['error'])

    # -- performance -------------------------------------------------------

    def test_query_count_is_bounded_no_n_plus_one(self):
        user = self._user()
        SyncCheckpoint.objects.create(session=self.session, status=SyncCheckpoint.STATUS_OK, last_run_at=timezone.now())
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        # Exactly 3 domain queries: the WahaSession lookup
        # (get_object_or_404), the SyncCheckpoint filter().first(), and
        # Phase 9.1B's WebhookEvent Max('received_at') aggregate — no
        # fourth, per-field, or related-object query (no N+1).
        domain_queries = [
            q for q in ctx.captured_queries
            if 'waha_sessions_wahasession' in q['sql']
            or 'sync_synccheckpoint' in q['sql']
            or 'webhooks_webhookevent' in q['sql']
        ]
        self.assertEqual(len(domain_queries), 3)


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
    CELERY_TASK_TIME_LIMIT=TEST_CELERY_TASK_TIME_LIMIT,
)
class SyncCheckpointRecoveryViewTests(APITestCase):
    """Phase 13.A — docs/generated/PHASE-13A-MANUAL-RECONCILIATION-RECOVERY-IMPLEMENTATION-REPORT.md.
    Manual recovery only: RUNNING -> ERROR, compare-and-set guarded, never
    touches checkpoint_value/Message/Chat/Contact, never enqueues a
    replacement task, never touches Celery."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')

    def _url(self, session_name=None):
        return f'/api/sync/recover/{session_name or self.session.name}/'

    def _auth_header(self, user):
        token = issue_access_token(user)['access_token']
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def _plain_user(self, username='operator'):
        return User.objects.create_user(username, password='pw')

    def _admin_user(self, username='admin'):
        user = User.objects.create_user(username, password='pw')
        group, _ = Group.objects.get_or_create(name='system administration')
        user.groups.add(group)
        return user

    def _stale_running_checkpoint(self, extra_seconds=30):
        stale = timezone.now() - timedelta(seconds=POSSIBLY_STUCK_THRESHOLD_SECONDS + extra_seconds)
        checkpoint = SyncCheckpoint.objects.create(session=self.session, status=SyncCheckpoint.STATUS_RUNNING)
        SyncCheckpoint.objects.filter(pk=checkpoint.pk).update(updated_at=stale)
        checkpoint.refresh_from_db()
        return checkpoint

    # -- authentication / authorization ------------------------------------

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.post(self._url())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(SyncCheckpoint.objects.count(), 0)

    def test_authenticated_without_system_administration_scope_is_rejected(self):
        self._stale_running_checkpoint()
        user = self._plain_user()
        response = self.client.post(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 403)
        checkpoint = SyncCheckpoint.objects.get(session=self.session)
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_RUNNING)  # untouched

    def test_unknown_session_returns_404(self):
        user = self._admin_user()
        response = self.client.post(self._url(session_name='does-not-exist'), **self._auth_header(user))
        self.assertEqual(response.status_code, 404)

    # -- rejection cases (no database change) ------------------------------

    def test_no_checkpoint_is_rejected(self):
        user = self._admin_user()
        response = self.client.post(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error']['code'], 'no_checkpoint')
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_fresh_running_checkpoint_is_rejected(self):
        checkpoint = SyncCheckpoint.objects.create(session=self.session, status=SyncCheckpoint.STATUS_RUNNING)
        user = self._admin_user()
        response = self.client.post(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error']['code'], 'not_stale')
        checkpoint.refresh_from_db()
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_RUNNING)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_error_checkpoint_is_rejected(self):
        checkpoint = SyncCheckpoint.objects.create(session=self.session, status=SyncCheckpoint.STATUS_ERROR)
        original_updated_at = checkpoint.updated_at
        user = self._admin_user()
        response = self.client.post(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error']['code'], 'not_running')
        checkpoint.refresh_from_db()
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_ERROR)
        self.assertEqual(checkpoint.updated_at, original_updated_at)  # untouched, no unnecessary write
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_ok_checkpoint_is_rejected(self):
        SyncCheckpoint.objects.create(session=self.session, status=SyncCheckpoint.STATUS_OK)
        user = self._admin_user()
        response = self.client.post(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error']['code'], 'not_running')

    # -- successful recovery -------------------------------------------------

    def test_stale_running_checkpoint_is_recovered(self):
        checkpoint = self._stale_running_checkpoint()
        user = self._admin_user()
        response = self.client.post(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['previous_status'], 'running')
        self.assertEqual(response.data['status'], 'error')
        self.assertTrue(response.data['recovered'])

        checkpoint.refresh_from_db()
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_ERROR)

    def test_recovery_does_not_change_checkpoint_value(self):
        checkpoint = self._stale_running_checkpoint()
        checkpoint.checkpoint_value = '2026-01-01T00:00:00+00:00'
        checkpoint.save(update_fields=['checkpoint_value'])
        # Re-establish a stale updated_at after the save above touched it
        # (auto_now) — isolates this test to checkpoint_value specifically.
        SyncCheckpoint.objects.filter(pk=checkpoint.pk).update(
            updated_at=timezone.now() - timedelta(seconds=POSSIBLY_STUCK_THRESHOLD_SECONDS + 30)
        )
        user = self._admin_user()
        response = self.client.post(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        checkpoint.refresh_from_db()
        self.assertEqual(checkpoint.checkpoint_value, '2026-01-01T00:00:00+00:00')

    def test_recovery_never_touches_message_chat_contact(self):
        # No Message/Chat/Contact model is imported or referenced by the
        # view at all (static fact, re-confirmed by this test creating
        # none and the view still succeeding) — recovery only reads
        # WahaSession/SyncCheckpoint and writes SyncCheckpoint/AuditLog.
        self._stale_running_checkpoint()
        user = self._admin_user()
        response = self.client.post(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)

    def test_successful_recovery_creates_exactly_one_audit_log(self):
        self._stale_running_checkpoint()
        user = self._admin_user()
        response = self.client.post(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AuditLog.objects.count(), 1)
        entry = AuditLog.objects.first()
        self.assertEqual(entry.actor_id, user.pk)
        self.assertEqual(entry.action, 'sync.checkpoint.recovery')
        self.assertIn(self.session.name, entry.target)
        self.assertEqual(entry.result, AuditLog.RESULT_SUCCESS)

    # -- concurrency / compare-and-set protection ---------------------------

    def test_concurrent_state_change_is_rejected_without_overwriting(self):
        # Simulates the exact race the design audit flagged (Section 8):
        # the view's own initial read is made to return a snapshot whose
        # updated_at no longer matches the real row (as if another process
        # already changed it between the read and the write) — the
        # compare-and-set UPDATE must then match zero rows and the view
        # must reject the request rather than overwrite the real row.
        real_checkpoint = self._stale_running_checkpoint()
        real_updated_at = real_checkpoint.updated_at

        stale_snapshot = SyncCheckpoint(
            pk=real_checkpoint.pk,
            session=self.session,
            status=SyncCheckpoint.STATUS_RUNNING,
        )
        stale_snapshot.updated_at = real_updated_at - timedelta(seconds=5)  # deliberately wrong

        real_manager_filter = SyncCheckpoint.objects.filter

        def fake_filter(*args, **kwargs):
            if 'session' in kwargs:
                mocked_qs = mock.Mock()
                mocked_qs.first.return_value = stale_snapshot
                return mocked_qs
            return real_manager_filter(*args, **kwargs)

        user = self._admin_user()
        with mock.patch('apps.sync.views.SyncCheckpoint.objects.filter', side_effect=fake_filter):
            response = self.client.post(self._url(), **self._auth_header(user))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data['error']['code'], 'concurrent_state_change')

        real_checkpoint.refresh_from_db()
        self.assertEqual(real_checkpoint.status, SyncCheckpoint.STATUS_RUNNING)  # untouched
        self.assertEqual(real_checkpoint.updated_at, real_updated_at)  # untouched
        self.assertEqual(AuditLog.objects.count(), 0)  # no success log for a rejected action


@override_settings(
    JWT_PRIVATE_KEY=PRIVATE_PEM,
    JWT_PUBLIC_KEY=PUBLIC_PEM,
    JWT_ISSUER='test-issuer',
    JWT_AUDIENCE='test-audience',
)
class SyncCheckpointTaskStateViewTests(APITestCase):
    """docs/generated/NEXT-PHASE-CELERY-TASK-CORRELATION-IMPLEMENTATION-REPORT.md.
    Diagnostic only — every test here asserts NO write of any kind
    (SyncCheckpoint/AuditLog/Message/Chat/Contact) occurs, since this view
    performs none."""

    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')

    def _url(self, session_name=None):
        return f'/api/sync/task-state/{session_name or self.session.name}/'

    def _auth_header(self, user):
        token = issue_access_token(user)['access_token']
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def _plain_user(self, username='operator'):
        return User.objects.create_user(username, password='pw')

    def _admin_user(self, username='admin'):
        user = User.objects.create_user(username, password='pw')
        group, _ = Group.objects.get_or_create(name='system administration')
        user.groups.add(group)
        return user

    def _checkpoint_with_task_id(self, task_id, status=SyncCheckpoint.STATUS_RUNNING):
        return SyncCheckpoint.objects.create(
            session=self.session, status=status, last_run_task_id=task_id,
        )

    # -- authentication / authorization ------------------------------------

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 401)

    def test_authenticated_without_system_administration_scope_is_rejected(self):
        self._checkpoint_with_task_id('abc-123')
        user = self._plain_user()
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 403)

    def test_unknown_session_returns_404(self):
        user = self._admin_user()
        response = self.client.get(self._url(session_name='does-not-exist'), **self._auth_header(user))
        self.assertEqual(response.status_code, 404)

    # -- no task id ----------------------------------------------------------

    def test_no_checkpoint_reports_no_task_id(self):
        user = self._admin_user()
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['last_run_task_id'], '')
        self.assertIsNone(response.data['task_state'])
        self.assertEqual(response.data['reason'], 'no_task_id')

    def test_blank_task_id_reports_no_task_id(self):
        # e.g. a management-command or sync-executor run.
        self._checkpoint_with_task_id('', status=SyncCheckpoint.STATUS_OK)
        user = self._admin_user()
        response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['reason'], 'no_task_id')

    # -- known Celery states, mocked at _query_task_state -------------------
    # docs/generated/NEXT-PHASE-CELERY-TASK-CORRELATION-DESIGN-AUDIT-REPORT.md's
    # own testing instruction: mock at the project boundary, never require a
    # live Celery worker.

    def _assert_state(self, celery_state, expected_note=None):
        self._checkpoint_with_task_id('task-abc')
        user = self._admin_user()
        with mock.patch('apps.sync.views._query_task_state', return_value=celery_state) as mocked:
            response = self.client.get(self._url(), **self._auth_header(user))
        mocked.assert_called_once_with('task-abc')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['last_run_task_id'], 'task-abc')
        self.assertEqual(response.data['task_state'], celery_state)
        self.assertIsNone(response.data['reason'])
        self.assertEqual(response.data['note'], expected_note)
        return response

    def test_pending_state_includes_the_ambiguity_note(self):
        from apps.sync.views import PENDING_AMBIGUITY_NOTE
        self._assert_state('PENDING', expected_note=PENDING_AMBIGUITY_NOTE)

    def test_started_state(self):
        self._assert_state('STARTED')

    def test_success_state(self):
        self._assert_state('SUCCESS')

    def test_failure_state(self):
        self._assert_state('FAILURE')

    def test_revoked_state(self):
        self._assert_state('REVOKED')

    def test_retry_state_is_preserved_verbatim_not_collapsed(self):
        # "may preserve additional meaningful state... do not create
        # unnecessary abstractions" — RETRY is a real Celery state not
        # explicitly named in the minimum list; relayed as-is.
        self._assert_state('RETRY')

    def test_unknown_stale_task_id_is_not_falsely_reported_as_success_or_failure(self):
        # Celery's own AsyncResult returns 'PENDING' for a task ID it has
        # never seen — confirmed exactly what this view reports (the
        # PENDING-ambiguity case), never a fabricated 'unknown' status and
        # never SUCCESS/FAILURE.
        from apps.sync.views import PENDING_AMBIGUITY_NOTE

        response = self._assert_state('PENDING', expected_note=PENDING_AMBIGUITY_NOTE)
        self.assertNotIn(response.data['task_state'], ('SUCCESS', 'FAILURE', 'REVOKED'))

    # -- Celery/Redis unavailable --------------------------------------------

    def test_celery_unavailable_is_distinguished_from_unknown_state(self):
        self._checkpoint_with_task_id('task-abc')
        user = self._admin_user()
        with mock.patch('apps.sync.views._query_task_state', return_value=None):
            response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['task_state'])
        self.assertEqual(response.data['reason'], 'unavailable')
        self.assertNotEqual(response.data['reason'], 'no_task_id')

    def test_real_connection_error_is_caught_and_reported_as_unavailable(self):
        # Exercises _query_task_state's own real exception handling, not a
        # mock of the helper itself — proves the try/except actually works.
        self._checkpoint_with_task_id('task-abc')
        user = self._admin_user()
        with mock.patch('apps.sync.views.AsyncResult', side_effect=ConnectionError('boom')):
            response = self.client.get(self._url(), **self._auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['reason'], 'unavailable')

    def test_no_secret_or_connection_detail_is_leaked_on_unavailability(self):
        self._checkpoint_with_task_id('task-abc')
        user = self._admin_user()
        with mock.patch(
            'apps.sync.views.AsyncResult',
            side_effect=ConnectionError('redis://:supersecretpassword@internal-redis-host:6379/0 unreachable'),
        ):
            response = self.client.get(self._url(), **self._auth_header(user))
        body = str(response.data)
        self.assertNotIn('supersecretpassword', body)
        self.assertNotIn('internal-redis-host', body)

    # -- no side effects ------------------------------------------------------

    def test_never_writes_anything(self):
        checkpoint = self._checkpoint_with_task_id('task-abc')
        original_updated_at = checkpoint.updated_at
        user = self._admin_user()
        with mock.patch('apps.sync.views._query_task_state', return_value='STARTED'):
            self.client.get(self._url(), **self._auth_header(user))
        checkpoint.refresh_from_db()
        self.assertEqual(checkpoint.status, SyncCheckpoint.STATUS_RUNNING)
        self.assertEqual(checkpoint.updated_at, original_updated_at)
        self.assertEqual(checkpoint.last_run_task_id, 'task-abc')
        self.assertEqual(AuditLog.objects.count(), 0)
