"""Celery tasks (Phase 11 — Blast). Thin orchestration, mirroring
apps.sync.tasks's own idioms (fan-out-one-task-per-unit, "safe to re-run"
docstring discipline) but for a fundamentally different shape of problem:
apps.sync.tasks fans out one task per SESSION; this module fans out one
task per RECIPIENT, each scheduled via `apply_async(countdown=...)` at a
computed future time — NEVER a `time.sleep`-in-a-loop design (design audit
Section 5: a single task looping with `time.sleep(60)` between up to 100
recipients would be hard-killed by CELERY_TASK_TIME_LIMIT=600 long before
finishing a full campaign).

IDEMPOTENCY: `dispatch_blast_recipient_task` re-checks the campaign and
claims its recipient (`pending -> sending`, compare-and-set) before doing
anything else — defense-in-depth on top of `OutboundOperation`'s own
`unique(session, idempotency_key)` DB constraint (the real idempotency
boundary, reused verbatim from apps.operations — see models.py).

NO AUTO-RETRY (finalized decision 5): neither task declares
`autoretry_for`, and `dispatch_blast_recipient_task` never re-raises a
BFF/WAHA-side failure — a failed send is recorded as
`BlastRecipient.status='failed'` with a sanitized reason and the task
completes normally. This is a deliberate correctness requirement, not an
oversight: an auto-retried send could otherwise burst two sends close
together and violate the 60s-same-session throttle (decision 3's own
stated reasoning).

NO AUTO-RESUME (finalized decision 6): `schedule_blast_campaign_task`
transitions the campaign `approved -> sending` via a single compare-and-
set claim; if the worker dies partway through scheduling recipients (or
partway through a campaign's dispatch window), nothing here notices or
recovers automatically. The campaign's true state remains fully
diagnosable from `BlastRecipient.status`/`scheduled_for` alone, per
decision 6 — no distributed lock, no periodic sweep, no resume task.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.operations.models import OutboundOperation

from .bff_client import BffDispatchError, send_blast_message
from .models import OPERATION_TYPE_BLAST_SEND, BlastCampaign, BlastRecipient

logger = logging.getLogger(__name__)

# Never the raw WAHA/internal exception text (decision 5) — a single,
# generic, operator-safe string for every failure cause (BFF unreachable,
# WAHA rejected the send, malformed response, etc.). Distinguishing these
# for an operator is a documented future improvement, not this phase's
# scope.
SAFE_FAILURE_MESSAGE = 'This message could not be delivered.'


@shared_task(bind=True)
def schedule_blast_campaign_task(self, campaign_id):
    """Triggered once, synchronously, right after
    BlastCampaignApproveView transitions a campaign to `approved`.
    Computes each pending recipient's `scheduled_for` (finalized decision
    3: 60s apart, throttled against any OTHER campaign already dispatching
    on the SAME session — recipients on different sessions never need to
    coordinate with each other) and enqueues one `dispatch_blast_recipient_task`
    per recipient via `apply_async(countdown=...)`.

    Idempotent guard: only the invocation that wins the `approved ->
    sending` compare-and-set actually schedules anything — a redelivered
    duplicate call (Celery's at-least-once semantics) becomes a cheap
    no-op. This is NOT a resume mechanism (decision 6): if the worker
    dies after the claim but before every recipient is scheduled, the
    unscheduled remainder simply never dispatches — a known, documented
    v1 limitation, not silently hidden.
    """
    try:
        campaign = BlastCampaign.objects.select_related('session').get(pk=campaign_id)
    except BlastCampaign.DoesNotExist:
        logger.warning('schedule_blast_campaign_task campaign_id=%s not found', campaign_id)
        return {'campaign_id': campaign_id, 'skipped': 'not_found'}

    claimed = BlastCampaign.objects.filter(pk=campaign.pk, status=BlastCampaign.STATUS_APPROVED).update(
        status=BlastCampaign.STATUS_SENDING, updated_at=timezone.now()
    )
    if claimed == 0:
        logger.info('schedule_blast_campaign_task campaign_id=%s already scheduled/not approved', campaign_id)
        return {'campaign_id': campaign_id, 'skipped': 'not_approved'}

    delay_seconds = settings.BLAST_INTER_MESSAGE_DELAY_SECONDS
    now = timezone.now()

    # Same-session throttle across DIFFERENT campaigns (finalized decision
    # 3's parenthetical: "this is what actually needs enforcing at
    # schedule-time"). Only PENDING recipients matter here — a recipient
    # that already reached a terminal status is done occupying the
    # session's send timeline.
    last_scheduled = BlastRecipient.objects.filter(
        campaign__session_id=campaign.session_id, status=BlastRecipient.STATUS_PENDING,
    ).exclude(campaign_id=campaign.pk).aggregate(models.Max('scheduled_for'))['scheduled_for__max']

    start = now
    if last_scheduled is not None:
        earliest_allowed = last_scheduled + timedelta(seconds=delay_seconds)
        if earliest_allowed > start:
            start = earliest_allowed

    recipients = list(campaign.recipients.filter(status=BlastRecipient.STATUS_PENDING).order_by('id'))
    for index, recipient in enumerate(recipients):
        recipient.scheduled_for = start + timedelta(seconds=index * delay_seconds)
    BlastRecipient.objects.bulk_update(recipients, ['scheduled_for'])

    for recipient in recipients:
        countdown = max(0.0, (recipient.scheduled_for - timezone.now()).total_seconds())
        dispatch_blast_recipient_task.apply_async(args=[recipient.pk], countdown=countdown)

    logger.info(
        'schedule_blast_campaign_task campaign_id=%s recipients_scheduled=%d first=%s last=%s',
        campaign_id, len(recipients),
        recipients[0].scheduled_for.isoformat() if recipients else None,
        recipients[-1].scheduled_for.isoformat() if recipients else None,
    )
    return {'campaign_id': campaign_id, 'recipients_scheduled': len(recipients)}


@shared_task(bind=True)
def dispatch_blast_recipient_task(self, recipient_id):
    """Fires once per recipient at its computed `scheduled_for` time.
    Short-lived (one WAHA send via the BFF), so it can never approach
    CELERY_TASK_TIME_LIMIT regardless of campaign size.

    Step order, each a defense-in-depth idempotency/safety check on top
    of the last: (1) re-check the campaign is still `sending` — a no-op
    if not (design audit Section 5); (2) claim the recipient
    (`pending -> sending`, compare-and-set) — a no-op if already claimed
    by a redelivered/duplicate invocation; (3) register-or-fetch the
    linked OutboundOperation via its existing unique(session,
    idempotency_key) constraint (apps.operations.models) — the REAL
    idempotency boundary, never re-sent if already `sent`; (4) call BFF;
    (5) resolve both OutboundOperation and BlastRecipient from the
    outcome. Never re-raises on a BFF/WAHA-side failure — see module
    docstring, "NO AUTO-RETRY".
    """
    try:
        recipient = BlastRecipient.objects.select_related('campaign', 'campaign__session').get(pk=recipient_id)
    except BlastRecipient.DoesNotExist:
        logger.warning('dispatch_blast_recipient_task recipient_id=%s not found', recipient_id)
        return {'recipient_id': recipient_id, 'skipped': 'not_found'}

    campaign = recipient.campaign

    if campaign.status != BlastCampaign.STATUS_SENDING:
        logger.info(
            'dispatch_blast_recipient_task recipient_id=%s campaign status=%s, not dispatching',
            recipient_id, campaign.status,
        )
        return {'recipient_id': recipient_id, 'skipped': 'campaign_not_sending'}

    claimed = BlastRecipient.objects.filter(pk=recipient.pk, status=BlastRecipient.STATUS_PENDING).update(
        status=BlastRecipient.STATUS_SENDING, updated_at=timezone.now()
    )
    if claimed == 0:
        logger.info('dispatch_blast_recipient_task recipient_id=%s already claimed', recipient_id)
        return {'recipient_id': recipient_id, 'skipped': 'already_claimed'}

    idempotency_key = recipient.idempotency_key
    operation, created = OutboundOperation.objects.get_or_create(
        session=campaign.session,
        idempotency_key=idempotency_key,
        defaults={
            'destination': recipient.destination,
            'operation_type': OPERATION_TYPE_BLAST_SEND,
            'status': OutboundOperation.STATUS_PENDING,
        },
    )

    if not created and operation.status == OutboundOperation.STATUS_SENT:
        # A prior invocation of this exact task already completed this
        # send (e.g. redelivery after the claim above but before this
        # invocation's own result was recorded) — reflect it, never call
        # BFF/WAHA a second time for the same recipient.
        BlastRecipient.objects.filter(pk=recipient.pk).update(
            status=BlastRecipient.STATUS_SENT, sent_at=timezone.now(), outbound_operation=operation,
        )
        _maybe_finalize_campaign(campaign.pk)
        return {'recipient_id': recipient_id, 'result': 'already_sent'}

    try:
        result = send_blast_message(campaign.session.name, recipient.destination, campaign.message_template, idempotency_key)
    except BffDispatchError as exc:
        logger.warning('dispatch_blast_recipient_task recipient_id=%s BFF dispatch failed: %s', recipient_id, exc)
        result = {'status': 'failed', 'provider_message_id': None}

    if result['status'] == 'sent':
        operation.status = OutboundOperation.STATUS_SENT
        operation.provider_message_id = result.get('provider_message_id') or ''
        operation.save(update_fields=['status', 'provider_message_id', 'updated_at'])
        BlastRecipient.objects.filter(pk=recipient.pk).update(
            status=BlastRecipient.STATUS_SENT, sent_at=timezone.now(), outbound_operation=operation, failure_reason='',
        )
    else:
        # Both 'failed' (WAHA/BFF cleanly reported failure) and 'unknown'
        # (ambiguous — e.g. a timeout) are recorded as BlastRecipient
        # 'failed' with the same sanitized reason: from an operator's
        # point of view "message not confirmed delivered" is the
        # actionable fact, and decision 5's "no auto-retry" applies
        # equally to both. OutboundOperation itself keeps the finer-
        # grained 'unknown' distinction for any future diagnostic use.
        operation.status = (
            OutboundOperation.STATUS_UNKNOWN if result['status'] == 'unknown' else OutboundOperation.STATUS_FAILED
        )
        operation.save(update_fields=['status', 'updated_at'])
        BlastRecipient.objects.filter(pk=recipient.pk).update(
            status=BlastRecipient.STATUS_FAILED, outbound_operation=operation, failure_reason=SAFE_FAILURE_MESSAGE,
        )

    _maybe_finalize_campaign(campaign.pk)
    return {'recipient_id': recipient_id, 'result': result['status']}


def _maybe_finalize_campaign(campaign_id):
    """Called after every recipient dispatch resolves. Transitions
    `sending -> completed` (or `-> failed` iff EVERY recipient ended up
    `failed` — finalized decision 2: partial failure still reaches
    `completed`) once every recipient has reached a terminal status.
    Compare-and-set on `status=SENDING` makes concurrent finalization
    attempts (the last two recipients resolving at nearly the same time)
    safe: only one caller's UPDATE actually matches a row."""
    campaign = BlastCampaign.objects.filter(pk=campaign_id).only('pk', 'status').first()
    if campaign is None or campaign.status != BlastCampaign.STATUS_SENDING:
        return

    statuses = set(BlastRecipient.objects.filter(campaign_id=campaign_id).values_list('status', flat=True))
    if not statuses or not statuses.issubset(BlastRecipient.TERMINAL_STATUSES):
        return  # still in-flight

    final_status = (
        BlastCampaign.STATUS_FAILED if statuses == {BlastRecipient.STATUS_FAILED} else BlastCampaign.STATUS_COMPLETED
    )
    BlastCampaign.objects.filter(pk=campaign_id, status=BlastCampaign.STATUS_SENDING).update(
        status=final_status, updated_at=timezone.now()
    )
