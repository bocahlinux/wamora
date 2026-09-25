"""Phase 11 — Blast campaign CRUD (draft/submit) + admin approval/reject
+ read access. Frontend-facing (JWTAuthentication), mounted at
`/api/blast/` — deliberately NOT under `/internal/` (that prefix is
reserved for HasInternalServiceKey-gated BFF -> Django traffic elsewhere
in this project; these endpoints are called by a logged-in human's
browser, same trust boundary as `apps.sync.views`/`apps.chats.views`).

Every status-changing write here follows the same compare-and-set
concurrency discipline as `apps.sync.views.SyncCheckpointRecoveryView`
(`.filter(pk=..., status=<value just read>).update(...)`, never a blind
`.save()`), and every transition is checked against
`BlastCampaign.ALLOWED_TRANSITIONS` first (finalized decision 2 — no
arbitrary status writes, client input is never trusted implicitly).
"""

import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.authn.authentication import JWTAuthentication
from apps.authn.permissions import HasBlastScope, HasSystemAdministrationScope

from .limits import remaining_daily_budget
from .models import BlastCampaign, BlastRecipient
from .serializers import (
    BlastCampaignCreateSerializer,
    BlastCampaignDetailSerializer,
    BlastCampaignListSerializer,
    BlastCampaignRejectSerializer,
    BlastRecipientResolveSerializer,
)
from .tasks import _maybe_finalize_campaign, schedule_blast_campaign_task

logger = logging.getLogger(__name__)


def _error(request, http_status, code, message):
    request_id = getattr(request, 'request_id', None)
    return Response({'error': {'code': code, 'message': message, 'request_id': request_id}}, status=http_status)


class BlastCampaignListCreateView(APIView):
    """GET /api/blast/campaigns/ — list, readable by either 'blast'
    (creators need to see their own campaigns) or 'system administration'
    (approvers need to see everything pending approval) — the first
    OR-composed DRF permission in this codebase, reasoned through rather
    than inventing a third scope name (design audit Section 7 explicitly
    recommends against a narrower 'blast approval' scope).

    POST /api/blast/campaigns/ — create a `draft` campaign (requires
    'blast'). Recipient cap (<=100) is enforced in the serializer
    (finalized decision 3)."""

    authentication_classes = [JWTAuthentication]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), HasBlastScope()]
        return [IsAuthenticated(), (HasBlastScope | HasSystemAdministrationScope)()]

    def get(self, request):
        campaigns = BlastCampaign.objects.select_related('session', 'created_by', 'approved_by').order_by(
            '-created_at'
        )
        return Response(BlastCampaignListSerializer(campaigns, many=True).data)

    def post(self, request):
        serializer = BlastCampaignCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        campaign = serializer.save()

        AuditLog.objects.create(
            actor=request.user,
            action='blast.campaign.create',
            target=f'{campaign.name} (session={campaign.session.name})',
            result=AuditLog.RESULT_SUCCESS,
        )

        return Response(BlastCampaignDetailSerializer(campaign).data, status=201)


class BlastCampaignDetailView(APIView):
    """GET /api/blast/campaigns/<pk>/ — same read-access reasoning as the
    list view above."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, (HasBlastScope | HasSystemAdministrationScope)]

    def get(self, request, pk):
        campaign = get_object_or_404(
            BlastCampaign.objects.select_related('session', 'created_by', 'approved_by').prefetch_related(
                'recipients'
            ),
            pk=pk,
        )
        return Response(BlastCampaignDetailSerializer(campaign).data)


class BlastCampaignSubmitView(APIView):
    """POST /api/blast/campaigns/<pk>/submit/ — draft -> pending_approval.

    Restricted to the campaign's own creator (an implementation-detail
    choice, not specified by the finalized decisions — documented in the
    implementation report): a 'blast'-scoped user submitting someone
    else's draft for approval has no clear legitimate use case in this
    v1 workflow, and this keeps "who can put a campaign in front of an
    approver" unambiguous."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasBlastScope]

    def post(self, request, pk):
        campaign = get_object_or_404(BlastCampaign, pk=pk)

        if campaign.created_by_id != request.user.id:
            return _error(request, 403, 'forbidden', 'Only the campaign creator may submit it for approval.')

        if not BlastCampaign.is_valid_transition(campaign.status, BlastCampaign.STATUS_PENDING_APPROVAL):
            return _error(
                request, 409, 'invalid_transition',
                f'Cannot submit a campaign in status {campaign.status!r} for approval.',
            )

        updated = BlastCampaign.objects.filter(pk=campaign.pk, status=campaign.status, updated_at=campaign.updated_at).update(
            status=BlastCampaign.STATUS_PENDING_APPROVAL, updated_at=timezone.now(),
        )
        if updated == 0:
            return _error(request, 409, 'concurrent_state_change', 'This campaign changed since it was last read.')

        campaign.refresh_from_db()
        return Response(BlastCampaignDetailSerializer(campaign).data)


class BlastCampaignApproveView(APIView):
    """POST /api/blast/campaigns/<pk>/approve/ — pending_approval ->
    approved, admin-only ('system administration'), and the approving
    user must differ from `created_by` (finalized decision 4 — checked
    explicitly here, not merely inferred from scope difference, since one
    user could hold both 'blast' and 'system administration').

    Also enforces the 500/day/session budget HERE, before writing
    `approved` (design audit Section 5/11: "rejected at approval time...
    rather than partially dispatched and then silently stalled
    mid-campaign") — a campaign that would push the session over budget
    never leaves `pending_approval`.

    On success, schedules `schedule_blast_campaign_task` (apps.blast.tasks)
    to compute per-recipient dispatch times and enqueue the per-recipient
    Celery tasks — this view itself never touches BFF/WAHA."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasSystemAdministrationScope]

    def post(self, request, pk):
        campaign = get_object_or_404(BlastCampaign.objects.select_related('session'), pk=pk)

        if campaign.created_by_id == request.user.id:
            return _error(request, 403, 'forbidden', 'A campaign cannot be approved by its own creator.')

        if not BlastCampaign.is_valid_transition(campaign.status, BlastCampaign.STATUS_APPROVED):
            return _error(
                request, 409, 'invalid_transition', f'Cannot approve a campaign in status {campaign.status!r}.'
            )

        recipient_count = campaign.recipients.count()
        remaining = remaining_daily_budget(campaign.session)
        if recipient_count > remaining:
            return _error(
                request, 409, 'daily_budget_exceeded',
                (
                    f'This campaign has {recipient_count} recipients, but session '
                    f'{campaign.session.name!r} only has {remaining} blast sends remaining today '
                    '(Asia/Jakarta calendar day).'
                ),
            )

        now = timezone.now()
        updated = BlastCampaign.objects.filter(
            pk=campaign.pk, status=campaign.status, updated_at=campaign.updated_at
        ).update(status=BlastCampaign.STATUS_APPROVED, approved_by=request.user, approved_at=now, updated_at=now)
        if updated == 0:
            return _error(request, 409, 'concurrent_state_change', 'This campaign changed since it was last read.')

        AuditLog.objects.create(
            actor=request.user,
            action='blast.campaign.approve',
            target=f'{campaign.name} (session={campaign.session.name}, recipients={recipient_count})',
            result=AuditLog.RESULT_SUCCESS,
        )

        schedule_blast_campaign_task.delay(campaign.pk)

        campaign.refresh_from_db()
        return Response(BlastCampaignDetailSerializer(campaign).data)


class BlastCampaignRejectView(APIView):
    """POST /api/blast/campaigns/<pk>/reject/ — pending_approval ->
    rejected, admin-only. Terminal (design audit Section 4): no
    resubmission of the same campaign row."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasSystemAdministrationScope]

    def post(self, request, pk):
        campaign = get_object_or_404(BlastCampaign, pk=pk)

        if not BlastCampaign.is_valid_transition(campaign.status, BlastCampaign.STATUS_REJECTED):
            return _error(
                request, 409, 'invalid_transition', f'Cannot reject a campaign in status {campaign.status!r}.'
            )

        serializer = BlastCampaignRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reason = serializer.validated_data['reason']

        updated = BlastCampaign.objects.filter(
            pk=campaign.pk, status=campaign.status, updated_at=campaign.updated_at
        ).update(status=BlastCampaign.STATUS_REJECTED, rejected_reason=reason, updated_at=timezone.now())
        if updated == 0:
            return _error(request, 409, 'concurrent_state_change', 'This campaign changed since it was last read.')

        AuditLog.objects.create(
            actor=request.user,
            action='blast.campaign.reject',
            target=f'{campaign.name} (session={campaign.session.name})',
            result=AuditLog.RESULT_SUCCESS,
        )

        campaign.refresh_from_db()
        return Response(BlastCampaignDetailSerializer(campaign).data)


class BlastRecipientResolveView(APIView):
    """POST /api/blast/campaigns/<pk>/recipients/<recipient_id>/resolve/ —
    Phase 11 stuck-recovery fix, closing the end-to-end audit report's one
    FAIL (docs/generated/PHASE-11-BLAST-END-TO-END-AUDIT-REPORT.md Section
    4/6/Summary): a worker that dies after the WAHA send succeeds but
    before `dispatch_blast_recipient_task` (apps.blast.tasks) writes the
    final status leaves a `BlastRecipient` stuck in `sending` forever —
    no task, API, or admin-site path could previously move it forward,
    and `_maybe_finalize_campaign` only finalizes a campaign once every
    recipient reaches a TERMINAL status, so one stuck recipient
    permanently blocked its whole campaign from ever completing.

    This is a MANUAL recovery action only (finalized decision 6, "no
    automatic resume/recovery in v1", still stands — nothing here is a
    periodic sweep or auto-heal). The system cannot know whether the
    WhatsApp message actually went through in that ambiguous window
    (that is the nature of the gap, and querying WAHA/reconciliation to
    find out is explicitly out of scope for this fix) — so the honest
    design lets the admin record the real-world outcome they determined
    externally (e.g. they checked the actual WhatsApp chat), choosing
    `sent` or `failed` themselves rather than the system guessing one.
    Recording `sent` here never triggers a new send (it is a pure status
    write, same as every other write in this module) — see
    BlastRecipientResolveSerializer's docstring.

    Same compare-and-set discipline as every other write in this module
    (and as `apps.sync.views.SyncCheckpointRecoveryView`, this
    codebase's own closest precedent for "a human manually resolves a
    stuck automated process"): only succeeds if the recipient is still
    actually `sending` at write time, so a concurrent legitimate
    completion (the original dispatch task finally finishing) or a
    second concurrent recovery call cannot silently overwrite this one,
    or vice versa.

    Gated by HasSystemAdministrationScope (the same scope
    SyncCheckpointRecoveryView uses for "human resolves stuck automated
    thing") — deliberately not HasBlastScope, since this is an
    administrative correction, not a campaign-authoring action, and not
    restricted to a non-creator like BlastCampaignApproveView (recovering
    a stuck send is not "approving your own campaign" and has no
    analogous self-dealing concern, matching BlastCampaignRejectView's
    own no-creator-restriction precedent).

    Never calls the BFF/WAHA client — no `send_blast_message` import
    exists in this module at all, so a re-dispatch is structurally
    impossible here, not just avoided by convention.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasSystemAdministrationScope]

    def post(self, request, pk, recipient_id):
        campaign = get_object_or_404(BlastCampaign.objects.select_related('session'), pk=pk)
        recipient = get_object_or_404(BlastRecipient, pk=recipient_id, campaign_id=campaign.pk)

        serializer = BlastRecipientResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data['status']

        if recipient.status != BlastRecipient.STATUS_SENDING:
            return _error(
                request, 409, 'not_sending',
                f'This recipient is not currently `sending` (status={recipient.status!r}); there is nothing to recover.',
            )

        write_fields = {'status': new_status, 'updated_at': timezone.now()}
        if new_status == BlastRecipient.STATUS_SENT:
            write_fields['sent_at'] = timezone.now()
            write_fields['failure_reason'] = ''
        else:
            write_fields['failure_reason'] = 'Marked as failed by manual recovery (stuck in sending).'

        updated = BlastRecipient.objects.filter(
            pk=recipient.pk, status=BlastRecipient.STATUS_SENDING, updated_at=recipient.updated_at,
        ).update(**write_fields)
        if updated == 0:
            return _error(
                request, 409, 'concurrent_state_change',
                'This recipient changed since it was last read; recovery was not applied, '
                'to avoid overwriting a newer state.',
            )

        AuditLog.objects.create(
            actor=request.user,
            action='blast.recipient.resolve',
            target=f'{recipient.destination} (campaign={campaign.name}, sending->{new_status})',
            result=AuditLog.RESULT_SUCCESS,
        )

        # The compounding consequence the audit flagged: a campaign
        # wedged solely because of this one stuck recipient must be able
        # to reach a terminal status now — _maybe_finalize_campaign is
        # reused verbatim (not a second implementation) so this shares
        # exactly one definition of "can this campaign finalize."
        _maybe_finalize_campaign(campaign.pk)

        campaign.refresh_from_db()
        return Response(BlastCampaignDetailSerializer(campaign).data)
