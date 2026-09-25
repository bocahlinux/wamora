"""Read-only sync-status endpoint (Phase 9.1A) —
docs/generated/PHASE9-1A-DESIGN-AUDIT-REPORT.md /
docs/generated/PHASE9-1A-SYNC-STATUS-IMPLEMENTATION-REPORT.md.

Deliberately named `views.py`, distinct from `internal_views.py` (BFF-only,
`HasInternalServiceKey`-gated, write-triggering): this is a frontend-facing,
JWT-authenticated, read-only view — the same Frontend -> Django direct
pattern `apps.chats`/`apps.dashboard` already use, not a new BFF hop and
not the internal-service-key mechanism (that authenticates the BFF
*process*, not an end user's browser — see
`apps/core/internal_auth.py`'s own docstring).

`SyncStatusView` never touches WAHA, Redis, or Celery, and never triggers
reconciliation — purely reads the already-stored `SyncCheckpoint` row for
one session. `SyncCheckpointTaskStateView` (below) is the one exception
to "never touches Celery" in this module — see its own docstring for why
it is deliberately kept separate rather than folded into `SyncStatusView`.
"""

import logging

from celery.result import AsyncResult
from django.conf import settings
from django.db.models import Max
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.authn.authentication import JWTAuthentication
from apps.authn.permissions import HasReadingScope, HasSystemAdministrationScope
from apps.sync.models import SyncCheckpoint
from apps.waha_sessions.models import WahaSession
from apps.webhooks.models import WebhookEvent
from config.celery import app as celery_app

logger = logging.getLogger(__name__)

# A multiple of the already-configured RECONCILIATION_INTERVAL_SECONDS, not
# an independent constant, so this threshold always tracks whatever
# interval a given environment actually runs (dev and production share the
# same code path; only the underlying setting's value differs).
#
# Missing exactly one periodic reconciliation cycle can be ordinary
# scheduling jitter (Celery beat/worker timing, a momentarily busy
# worker); missing two consecutive cycles is a materially stronger signal
# that periodic reconciliation has actually stopped advancing. This
# mirrors the same "wait for repeated misses before declaring degraded"
# philosophy already used by the frontend's own connectivity indicator
# (frontend/src/pages/InboxPage.tsx's CONNECTIVITY_FAILURE_THRESHOLD = 2,
# Phase 9.1D) — not derived from that code, but a deliberately consistent
# choice for the same kind of judgment call.
STALE_THRESHOLD_MULTIPLIER = 2

# docs/generated/NEXT-PHASE-POSSIBLY-STUCK-DETECTION-DESIGN-AUDIT-REPORT.md
# Section 7 (Option 1, recommended). A fixed margin only — not itself
# derived from another setting. Added to settings.CELERY_TASK_TIME_LIMIT
# *inside* _is_possibly_stuck() (never baked into a module-level total),
# the same "read the live setting, don't cache it at import time"
# discipline STALE_THRESHOLD_MULTIPLIER/_derive_sync_status() already use
# for RECONCILIATION_INTERVAL_SECONDS just below — this also keeps the
# threshold correctly responsive to @override_settings in tests.
POSSIBLY_STUCK_SAFETY_MARGIN_SECONDS = 60


def _seconds_since(moment):
    if moment is None:
        return None
    return int((timezone.now() - moment).total_seconds())


def _isoformat(moment):
    """Matches the exact manual ISO-8601/UTC-'Z' formatting
    apps/dashboard/views.py's MessagesStatsView/ActivityFeedView already
    use for every timestamp they return — explicit here for the same
    reason, not relying on implicit JSON-encoder datetime handling."""
    if moment is None:
        return None
    value = moment.isoformat()
    if value.endswith('+00:00'):
        value = value[:-6] + 'Z'
    return value


def _derive_sync_status(checkpoint):
    """Computed entirely from SyncCheckpoint.status + last_run_at — never
    lag_seconds (unwritten anywhere in this codebase; would always be
    null) and never an invented signal such as "possibly_stuck". Returns
    (sync_status, seconds_since_last_run).

    Total over every value SyncCheckpoint.STATUS_CHOICES allows, including
    the model's default STATUS_IDLE, even though no code path in this
    project leaves a checkpoint row observably in that state in practice
    (reconcile_session() advances a freshly get_or_create()'d checkpoint
    straight to STATUS_RUNNING within the same call, before it is visible
    to any other reader as 'idle') — grouped with 'running' rather than
    'never_synced' because a checkpoint ROW does exist in that case (this
    endpoint's own contract ties 'never_synced' specifically to no row
    existing), and "a reconciliation attempt has been initiated but not
    yet observed to progress" is the closer description.
    """
    if checkpoint is None:
        return 'never_synced', None

    seconds = _seconds_since(checkpoint.last_run_at)

    if checkpoint.status in (SyncCheckpoint.STATUS_RUNNING, SyncCheckpoint.STATUS_IDLE):
        return 'running', seconds
    if checkpoint.status == SyncCheckpoint.STATUS_ERROR:
        return 'failed', seconds

    # STATUS_OK
    threshold_seconds = settings.RECONCILIATION_INTERVAL_SECONDS * STALE_THRESHOLD_MULTIPLIER
    if seconds is not None and seconds <= threshold_seconds:
        return 'healthy', seconds
    return 'stale', seconds


def _is_possibly_stuck(checkpoint):
    """docs/generated/NEXT-PHASE-POSSIBLY-STUCK-DETECTION-DESIGN-AUDIT-REPORT.md
    Section 6/8. Detection only — never resets, retries, or otherwise
    mutates the checkpoint (see that report's Section 12, "Recovery
    Boundary"). Uses checkpoint.updated_at (set on every save, including
    the moment status becomes RUNNING), never last_run_at (only set on a
    *completed* run — stale/absent while genuinely stuck, per the design
    report Section 5). Depends on nothing beyond SyncCheckpoint's own
    already-loaded fields: no Celery/worker-liveness/Redis/WAHA call.

    Boundary is exclusive (age > threshold, not >=) — mirrors
    _derive_sync_status()'s own boundary-inclusive-for-the-healthy-side
    choice just above (<=), so the "not yet a problem" side is
    consistently the inclusive one in both functions.
    """
    if checkpoint is None or checkpoint.status != SyncCheckpoint.STATUS_RUNNING:
        return False
    threshold_seconds = settings.CELERY_TASK_TIME_LIMIT + POSSIBLY_STUCK_SAFETY_MARGIN_SECONDS
    return _seconds_since(checkpoint.updated_at) > threshold_seconds


class SyncStatusView(APIView):
    """GET /api/sync/status/<session_name>/

    Auth: Phase 12 (Security hardening) MUST-FIX #1 —
    docs/generated/PHASE-12-SECURITY-HARDENING-DESIGN-AUDIT-REPORT.md
    Section 3.2. This previously used IsAuthenticated only, deliberately
    (see the Phase 9.1A design report Section 5's "operational/system
    state, not conversation content" reasoning, and the superseded
    docstring this replaces) — the Phase 12 audit re-examined that
    precedent and found it inconsistent with docs/06-SECURITY.md's
    "separate permissions for ... reading, ..." principle applied
    everywhere else, so it is now gated behind HasReadingScope, exactly
    mirroring apps.chats/apps.dashboard. Every normal operator's token
    already carries the 'reading' scope (Django Group membership named
    'reading') because the Inbox (frontend/src/pages/InboxPage.tsx)
    already depends on the exact same scope for apps.chats — this does
    not newly require anything a working Inbox/Dashboard user doesn't
    already have.

    404 (via get_object_or_404, the same pattern ChatMessagesView/
    ChatMarkReadView already use) when `session_name` names no known
    WahaSession at all — distinct from a *known* session that has simply
    never been reconciled, which is a normal 200 response with
    `sync_status: "never_synced"`.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasReadingScope]

    def get(self, request, session_name):
        session = get_object_or_404(WahaSession, name=session_name)

        # A plain filter().first() — never the reverse OneToOne accessor
        # (session.sync_checkpoint), which raises
        # SyncCheckpoint.DoesNotExist instead of returning None for a
        # session that has never been reconciled (see the design report
        # Section 3). One query, no exception-driven control flow, safe
        # for a never-synced session.
        checkpoint = SyncCheckpoint.objects.filter(session=session).first()
        sync_status, seconds_since_last_run = _derive_sync_status(checkpoint)

        # Phase 9.1B — docs/generated/PHASE-9-1B-WEBHOOK-TIMESTAMP-DESIGN-AUDIT-REPORT.md.
        # Server-received-time signal, deliberately independent of
        # SyncCheckpoint/reconciliation (Section 4 there): the most recent
        # WebhookEvent.received_at for this session, regardless of that
        # event's processing status (a failed/unsupported delivery still
        # proves WAHA is reaching us). Never Message.timestamp (that's the
        # WAHA-reported source event time, a different signal) and never a
        # value derived from the webhook payload itself.
        last_webhook_received_at = WebhookEvent.objects.filter(session=session).aggregate(
            Max('received_at')
        )['received_at__max']

        return Response({
            'session': session.name,
            'sync_status': sync_status,
            'checkpoint_status': checkpoint.status if checkpoint else None,
            'last_run_at': _isoformat(checkpoint.last_run_at) if checkpoint else None,
            'seconds_since_last_run': seconds_since_last_run,
            'checkpoint_updated_at': _isoformat(checkpoint.updated_at) if checkpoint else None,
            'last_webhook_received_at': _isoformat(last_webhook_received_at),
            'possibly_stuck': _is_possibly_stuck(checkpoint),
        })


class SyncCheckpointRecoveryView(APIView):
    """POST /api/sync/recover/<session_name>/ — Phase 13.A, manual
    recovery only. docs/generated/NEXT-PHASE-RECONCILIATION-RECOVERY-DESIGN-AUDIT-REPORT.md
    Section 17 / docs/generated/PHASE-13A-MANUAL-RECONCILIATION-RECOVERY-IMPLEMENTATION-REPORT.md.

    Marks a `possibly_stuck` checkpoint's status RUNNING -> ERROR, so an
    operator can manually clear a wedged reconciliation run. Deliberately
    NOT automatic (no periodic sweep calls this), NOT a replacement-task
    enqueue, NOT a Celery revoke/inspection (this project has no
    persisted task ID to revoke/inspect — see the design report Section
    10/14), and NEVER touches `checkpoint_value`, `Message`, `Chat`, or
    `Contact` rows.

    Auth: the same JWTAuthentication as SyncStatusView, plus the new
    HasSystemAdministrationScope gate (apps.authn.permissions) — an
    administrative, state-changing action, not a read, so `reading`
    alone (SyncStatusView's own gate) is deliberately not sufficient
    here; 'system administration' is an existing JWT scope
    (settings.JWT_SCOPES/docs/06-SECURITY.md) that had never been
    checked by any endpoint before this one.

    Reuses `_is_possibly_stuck()` verbatim (the exact function
    SyncStatusView's own `possibly_stuck` field calls) — no second
    threshold, no duplicated logic, per the design report's own
    instruction that detection and recovery must share one definition
    of "stuck."

    Concurrency safety: the RUNNING -> ERROR write is a conditional
    (compare-and-set) UPDATE — `.filter(pk=checkpoint.pk,
    status=STATUS_RUNNING, updated_at=<the exact value just read>)` —
    never a blind `checkpoint.save()`. If the row has changed since it
    was read (the original run finished, or an earlier recovery attempt
    already acted), the UPDATE matches zero rows and this view reports
    the conflict instead of silently overwriting whatever the row now
    holds (design report Sections 8/12/17 — the one safeguard that
    report identified as the minimum required before any recovery
    action, automatic or manual).
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasSystemAdministrationScope]

    def post(self, request, session_name):
        request_id = getattr(request, 'request_id', None)
        session = get_object_or_404(WahaSession, name=session_name)

        # Same plain filter().first() SyncStatusView uses — never the
        # reverse OneToOne accessor, which raises DoesNotExist instead of
        # returning None for a session that has no checkpoint at all.
        checkpoint = SyncCheckpoint.objects.filter(session=session).first()

        if checkpoint is None:
            # Mirrors SyncStatusView's own 'never_synced' framing — a
            # known session simply has nothing to recover, distinct from
            # an unknown session name (404, via get_object_or_404 above).
            return Response(
                {
                    'error': {
                        'code': 'no_checkpoint',
                        'message': 'This session has never been reconciled; there is no checkpoint to recover.',
                        'request_id': request_id,
                    }
                },
                status=409,
            )

        if checkpoint.status != SyncCheckpoint.STATUS_RUNNING:
            return Response(
                {
                    'error': {
                        'code': 'not_running',
                        'message': 'This checkpoint is not currently RUNNING; there is nothing to recover.',
                        'request_id': request_id,
                    }
                },
                status=409,
            )

        if not _is_possibly_stuck(checkpoint):
            return Response(
                {
                    'error': {
                        'code': 'not_stale',
                        'message': 'This checkpoint is RUNNING but not yet stale enough to be considered possibly stuck.',
                        'request_id': request_id,
                    }
                },
                status=409,
            )

        # The compare-and-set guard: only applies if the row is still
        # EXACTLY as just read (same status, same updated_at). Never
        # touches checkpoint_value, last_run_at, Message, Chat, or
        # Contact rows. updated_at is set explicitly — QuerySet.update()
        # does not trigger auto_now (that only fires on .save()).
        updated_count = SyncCheckpoint.objects.filter(
            pk=checkpoint.pk,
            status=SyncCheckpoint.STATUS_RUNNING,
            updated_at=checkpoint.updated_at,
        ).update(
            status=SyncCheckpoint.STATUS_ERROR,
            last_error='Marked as failed by manual recovery (possibly_stuck) — Phase 13.A.',
            updated_at=timezone.now(),
        )

        if updated_count == 0:
            # The checkpoint changed between our read and this write (the
            # original run finished, or another recovery attempt already
            # acted) — never overwrite whatever it now holds, and never
            # write a success AuditLog for an action that didn't apply.
            return Response(
                {
                    'error': {
                        'code': 'concurrent_state_change',
                        'message': (
                            'This checkpoint changed since it was last read; recovery was not applied, '
                            'to avoid overwriting a newer state.'
                        ),
                        'request_id': request_id,
                    }
                },
                status=409,
            )

        # AuditLog has no metadata/JSON field by design (apps/audit/models.py's
        # own docstring) — previous/resulting status is encoded in `target`
        # alongside the session name, the same string field
        # apps/dashboard/views.py's ActivityFeedView already uses for a
        # session identifier.
        AuditLog.objects.create(
            actor=request.user,
            action='sync.checkpoint.recovery',
            target=f'{session.name} (running->error)',
            result=AuditLog.RESULT_SUCCESS,
        )

        return Response({
            'session': session.name,
            'previous_status': SyncCheckpoint.STATUS_RUNNING,
            'status': SyncCheckpoint.STATUS_ERROR,
            'recovered': True,
        })


# docs/generated/NEXT-PHASE-CELERY-TASK-CORRELATION-DESIGN-AUDIT-REPORT.md
# Section 10 (recommended next task) / Section 9, option C. A known-ambiguous
# Celery API result — see PENDING_AMBIGUITY_NOTE below.
PENDING_AMBIGUITY_NOTE = (
    "Celery reports PENDING for both a genuinely queued-but-not-yet-started "
    "task and a task ID it has never seen at all — these cannot be "
    "distinguished via AsyncResult alone."
)
NO_TASK_ID_NOTE = (
    "No Celery task ID is recorded for this checkpoint's most recent run "
    "(a management-command or sync-executor run, or this session has never "
    "been reconciled)."
)
UNAVAILABLE_NOTE = "Celery/Redis could not be reached to correlate this task ID."


def _query_task_state(task_id):
    """Returns the raw Celery-reported state string, or None if Celery/Redis
    could not be reached. Isolated as its own function specifically so
    tests can mock this one call without needing a live Celery worker or
    broker — the correct project boundary per the design report's own
    testing instruction, mirroring RedisHealthView's identical
    'one narrow external call, wrapped, logged, never re-raised' shape."""
    try:
        return AsyncResult(task_id, app=celery_app).state
    except Exception:
        logger.exception('Celery task-state correlation failed')
        return None


class SyncCheckpointTaskStateView(APIView):
    """GET /api/sync/task-state/<session_name>/ — Phase "Celery task
    correlation" (docs/generated/NEXT-PHASE-CELERY-TASK-CORRELATION-DESIGN-AUDIT-REPORT.md,
    docs/generated/NEXT-PHASE-CELERY-TASK-CORRELATION-IMPLEMENTATION-REPORT.md).

    DIAGNOSTIC ONLY. Answers "what does Celery currently say about the
    task ID recorded in SyncCheckpoint.last_run_task_id" for a human
    operator investigating a `possibly_stuck` checkpoint — via the SAME
    field `_is_possibly_stuck()` and Phase 13.A already read, no second
    task-ID field. Performs NO write of any kind: never resets
    `SyncCheckpoint`, never revokes/retries/enqueues a Celery task, never
    calls the Phase 13.A recovery endpoint. A dedicated, separate endpoint
    rather than a new field on `SyncStatusView`'s response, deliberately:
    (1) `SyncStatusView`'s own docstring states it "never touches WAHA,
    Redis, or Celery" — preserving that guarantee unmodified matters more
    than saving one HTTP round trip, since every existing consumer of that
    endpoint (including this session's own polling in InboxPage.tsx,
    unaffected by this task) should keep working against an endpoint whose
    latency/failure profile never changed; (2) the design report's own
    explicit instruction not to fold this into `possibly_stuck` or change
    any existing field's semantics.

    THIS RESULT IS NOT OWNERSHIP PROOF. The design audit traced precisely
    why: `last_run_task_id` identifies whichever task most recently
    STARTED a run on this checkpoint, not necessarily the task that
    produced its current status, under the concurrent-execution race that
    audit's Section 6 proved possible today. This view reports Celery's
    own last-known state for that recorded ID, honestly and only that —
    it is supporting evidence for a human decision (e.g. via Phase 13.A),
    never an automated trigger for one.

    Auth: JWTAuthentication + IsAuthenticated + HasSystemAdministrationScope
    — the same administrative gate Phase 13.A's recovery endpoint uses
    (not `SyncStatusView`'s plain IsAuthenticated-only), because a Celery
    task ID is internal system/worker detail, one step more sensitive than
    the plain operational status `SyncStatusView` already exposes to any
    authenticated user. No new JWT scope was introduced.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasSystemAdministrationScope]

    def get(self, request, session_name):
        session = get_object_or_404(WahaSession, name=session_name)
        checkpoint = SyncCheckpoint.objects.filter(session=session).first()
        task_id = checkpoint.last_run_task_id if checkpoint else ''

        if not task_id:
            return Response({
                'session': session.name,
                'last_run_task_id': '',
                'task_state': None,
                'reason': 'no_task_id',
                'note': NO_TASK_ID_NOTE,
            })

        state = _query_task_state(task_id)

        if state is None:
            return Response({
                'session': session.name,
                'last_run_task_id': task_id,
                'task_state': None,
                'reason': 'unavailable',
                'note': UNAVAILABLE_NOTE,
            })

        return Response({
            'session': session.name,
            'last_run_task_id': task_id,
            'task_state': state,
            'reason': None,
            'note': PENDING_AMBIGUITY_NOTE if state == 'PENDING' else None,
        })
