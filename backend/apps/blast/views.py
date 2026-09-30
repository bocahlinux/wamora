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

from django.db import models
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.authn.authentication import JWTAuthentication
from apps.authn.permissions import HasBlastScope, HasOfficeAdminAccess, HasSystemAdministrationScope
from apps.offices.authorization import has_global_access
from apps.offices.models import Office

from .authorization import campaigns_visible_to, can_view_campaign, templates_visible_to
from .limits import remaining_daily_budget
from .models import BlastApiKey, BlastCampaign, BlastRecipient, BlastSettings, BlastTemplate, get_blast_settings
from .serializers import (
    BlastCampaignCreateSerializer,
    BlastCampaignDetailSerializer,
    BlastCampaignListSerializer,
    BlastCampaignRejectSerializer,
    BlastRecipientResolveSerializer,
    BlastTemplateSerializer,
    OfficeChoiceSerializer,
)
from .tasks import _maybe_finalize_campaign, schedule_blast_campaign_task

logger = logging.getLogger(__name__)


def _error(request, http_status, code, message, details=None):
    request_id = getattr(request, 'request_id', None)
    body = {'error': {'code': code, 'message': message, 'request_id': request_id}}
    if details is not None:
        body['error']['details'] = details
    return Response(body, status=http_status)


def _serializer_error_response(request, serializer):
    """`serializer.is_valid(raise_exception=True)` would hand the error
    dict to `apps.core.exceptions.api_exception_handler`, which only ever
    reads `detail.get('detail')` — for a dict-shaped ValidationError like
    `BlastCampaignCreateSerializer.validate()`'s own
    `{'recipients': ..., 'details': [...]}` (the all-or-nothing per-row
    variable-mismatch report), that key doesn't exist, so `message` comes
    back `None` and the entire `details` array is silently dropped —
    found by tracing the response shape end-to-end while wiring up the
    frontend, not by inspection alone. Rather than changing that GLOBAL
    handler (used by every endpoint in this project, well beyond Blast's
    own scope), this builds the error response by hand for this one
    endpoint, preserving `details` for the frontend's per-row error UI."""
    errors = serializer.errors
    raw_details = errors.get('details')
    # DRF wraps every leaf value of a raised dict-shaped ValidationError in
    # `ErrorDetail` (a str subclass) via `_get_error_details` — including
    # `index`, which `validate()` set as a plain int. Left alone, the
    # wire response would return `"index": "1"` (a JSON string) from
    # THIS endpoint but `"index": 1` (a JSON int) from the external API's
    # hand-built error response (external_views.py, which never raises
    # through DRF's ValidationError machinery) — found by comparing the
    # two endpoints' actual JSON output. Normalized back to int/str here
    # so both API surfaces hand the frontend the exact same shape.
    details = None
    if raw_details is not None:
        details = [
            {
                'index': int(row['index']),
                'destination': str(row['destination']),
                'missing': [str(v) for v in row['missing']],
                'extra': [str(v) for v in row['extra']],
            }
            for row in raw_details
        ]
    parts = [str(item) for key, value in errors.items() if key != 'details' for item in (value if isinstance(value, list) else [value])]
    message = ' '.join(parts) if parts else 'The request could not be processed.'
    return _error(request, 400, 'validation_error', message, details=details)


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
        # Step 4 (Office integration) — campaigns_visible_to() is the
        # single Office-boundary rule; see apps.blast.authorization.
        campaigns = campaigns_visible_to(request.user).select_related(
            'session', 'office', 'created_by', 'approved_by', 'template'
        ).order_by('-created_at')
        return Response(BlastCampaignListSerializer(campaigns, many=True).data)

    def post(self, request):
        serializer = BlastCampaignCreateSerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return _serializer_error_response(request, serializer)
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
            BlastCampaign.objects.select_related(
                'session', 'office', 'created_by', 'approved_by', 'template'
            ).prefetch_related('recipients'),
            pk=pk,
        )
        # Step 4 (Office integration) — same rule as the list view above.
        if not can_view_campaign(request.user, campaign):
            return _error(request, 403, 'forbidden', 'You do not have access to this campaign.')
        return Response(BlastCampaignDetailSerializer(campaign).data)


class BlastOfficeChoicesView(APIView):
    """GET /api/blast/offices/ — Step 4's minimal read-only office list,
    for a globally-accessing creator's campaign-create Office picker
    only (Office Admin/Operator have their Office auto-assigned server-
    side and never need this). Not Office management — no create/edit/
    deactivate endpoint exists anywhere; that is explicitly out of this
    step's scope."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, (HasBlastScope | HasSystemAdministrationScope)]

    def get(self, request):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a globally-accessing administrator may list Offices.')
        offices = Office.objects.filter(is_active=True).order_by('name')
        return Response(OfficeChoiceSerializer(offices, many=True).data)


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
    approved, admin-only ('system administration'). A non-superuser must
    differ from `created_by`; a Django superuser may approve their own
    campaign. This exception is checked explicitly here, not inferred from
    scope difference, since a non-superuser may hold both 'blast' and
    'system administration'.

    Also enforces the 500/day/session budget HERE, before writing
    `approved` (design audit Section 5/11: "rejected at approval time...
    rather than partially dispatched and then silently stalled
    mid-campaign") — a campaign that would push the session over budget
    never leaves `pending_approval`.

    On success, schedules `schedule_blast_campaign_task` (apps.blast.tasks)
    to compute per-recipient dispatch times and enqueue the per-recipient
    Celery tasks — this view itself never touches BFF/WAHA."""

    authentication_classes = [JWTAuthentication]
    # Step 8 (Role x Scope alignment) — Office/Global Admin reach approval
    # via their organizational role (HasOfficeAdminAccess), not just the
    # `system administration` Group/scope, which also gates unrelated
    # global Sync Recovery — granting that as a side effect of Blast
    # approval capability is exactly what this avoids. Office boundary
    # (can_view_campaign) and the self-approval rule below are unchanged.
    permission_classes = [IsAuthenticated, (HasSystemAdministrationScope | HasOfficeAdminAccess)]

    def post(self, request, pk):
        campaign = get_object_or_404(BlastCampaign.objects.select_related('session', 'office'), pk=pk)

        # Step 4 (Office integration) — checked before the existing
        # self-approval rule below; that rule is unchanged either way.
        if not can_view_campaign(request.user, campaign):
            return _error(request, 403, 'forbidden', 'You do not have access to this campaign.')

        if campaign.created_by_id == request.user.id and not request.user.is_superuser:
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
    # Step 8 — same reasoning as BlastCampaignApproveView above.
    permission_classes = [IsAuthenticated, (HasSystemAdministrationScope | HasOfficeAdminAccess)]

    def post(self, request, pk):
        campaign = get_object_or_404(BlastCampaign.objects.select_related('office'), pk=pk)

        # Step 4 (Office integration).
        if not can_view_campaign(request.user, campaign):
            return _error(request, 403, 'forbidden', 'You do not have access to this campaign.')

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


class BlastTemplateListCreateView(APIView):
    """GET/POST /api/blast/templates/ — Discussed requirement:
    Superadmin/Global-Admin-only (`has_global_access`), same gating
    precedent as `BlastApiKeyListCreateView`/`BlastSettingsView` below.
    An Office Admin/Operator never sees or manages templates at all
    (previously readable via 'blast'/'system administration' — narrowed
    deliberately, a real access-control change, not an oversight fix).

    A globally-accessing creator may set `office` explicitly (including
    `null` for a shared/global template) — `templates_visible_to`'s own
    office-boundary logic is now moot in practice (every caller who
    reaches this view already has global access, so that helper's
    `has_global_access` branch — return everything — is the only branch
    that ever runs here), but is still reused rather than duplicated."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a Superadmin or Global Admin may manage templates.')
        templates = templates_visible_to(request.user).select_related('office', 'created_by').order_by('name')
        return Response(BlastTemplateSerializer(templates, many=True).data)

    def post(self, request):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a Superadmin or Global Admin may manage templates.')

        serializer = BlastTemplateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        template = serializer.save(created_by=request.user)

        AuditLog.objects.create(
            actor=request.user,
            action='blast.template.create',
            target=f'{template.name} ({template.key})',
            result=AuditLog.RESULT_SUCCESS,
        )
        return Response(BlastTemplateSerializer(template).data, status=201)


class BlastTemplateDetailView(APIView):
    """GET/PATCH /api/blast/templates/<pk>/ — same Superadmin/Global-
    Admin-only gate as the list/create view above. No DELETE — a
    template is retired via `is_active=False` (same "revoke, never
    hard-delete" convention as `BlastApiKey`), so a
    `BlastCampaign.template` pointer to it never dangles and stays fully
    auditable."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a Superadmin or Global Admin may manage templates.')
        template = get_object_or_404(BlastTemplate.objects.select_related('office', 'created_by'), pk=pk)
        return Response(BlastTemplateSerializer(template).data)

    def patch(self, request, pk):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a Superadmin or Global Admin may manage templates.')
        template = get_object_or_404(BlastTemplate, pk=pk)

        serializer = BlastTemplateSerializer(template, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        # `key` is stable-by-design (BlastTemplate's own docstring) —
        # never editable after creation, regardless of what the client
        # sends; every other field may change freely.
        serializer.validated_data.pop('key', None)
        template = serializer.save()

        AuditLog.objects.create(
            actor=request.user,
            action='blast.template.update',
            target=f'{template.name} ({template.key})',
            result=AuditLog.RESULT_SUCCESS,
        )
        return Response(BlastTemplateSerializer(template).data)


class BlastApiKeyListCreateView(APIView):
    """GET/POST /api/blast/api-keys/ — Superadmin/Global-Admin-only
    (mirrors the Roles tab's superuser/global-admin-only precedent,
    `apps.offices.views`'s Role views). The raw key is only ever present
    in the POST response, exactly once.

    Discussed requirement — a key is global: it carries no Office at all
    (see `BlastApiKey`'s own docstring) — it works for a single ad-hoc
    message, a freeform blast, or a templated blast, against any session
    named in each individual external request."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a Superadmin or Global Admin may manage API keys.')
        keys = BlastApiKey.objects.select_related('created_by').order_by('-created_at')
        return Response([
            {
                'id': key.pk,
                'name': key.name,
                'key_prefix': key.key_prefix,
                'is_active': key.is_active,
                'created_by': key.created_by.username,
                'last_used_at': key.last_used_at,
                'created_at': key.created_at,
            }
            for key in keys
        ])

    def post(self, request):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a Superadmin or Global Admin may manage API keys.')

        name = (request.data.get('name') or '').strip()
        if not name:
            return _error(request, 400, 'validation_error', 'name must not be blank.')

        key, raw_key = BlastApiKey.create_with_raw_key(name=name, created_by=request.user)

        AuditLog.objects.create(
            actor=request.user,
            action='blast.api_key.create',
            target=f'{key.name} ({key.key_prefix}…)',
            result=AuditLog.RESULT_SUCCESS,
        )
        return Response(
            {
                'id': key.pk,
                'name': key.name,
                'key_prefix': key.key_prefix,
                'is_active': key.is_active,
                'raw_key': raw_key,
            },
            status=201,
        )


class BlastApiKeyRevokeView(APIView):
    """POST /api/blast/api-keys/<pk>/revoke/ — is_active=False, never a
    hard delete (past campaigns stay attributable)."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a Superadmin or Global Admin may manage API keys.')

        key = get_object_or_404(BlastApiKey, pk=pk)
        BlastApiKey.objects.filter(pk=key.pk).update(is_active=False, updated_at=timezone.now())

        AuditLog.objects.create(
            actor=request.user,
            action='blast.api_key.revoke',
            target=f'{key.name} ({key.key_prefix}…)',
            result=AuditLog.RESULT_SUCCESS,
        )
        return Response(status=204)


class BlastSettingsView(APIView):
    """GET/PATCH /api/blast/settings/ — the one-row `BlastSettings`
    singleton (currently just `inter_message_delay_seconds`).
    Superadmin/Global-Admin-only, same reasoning as API Keys — this is a
    system-wide value, not an Office-scoped one."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a Superadmin or Global Admin may view Blast settings.')
        settings_row = get_blast_settings()
        return Response({'inter_message_delay_seconds': settings_row.inter_message_delay_seconds})

    def patch(self, request):
        if not has_global_access(request.user):
            return _error(request, 403, 'forbidden', 'Only a Superadmin or Global Admin may edit Blast settings.')

        delay = request.data.get('inter_message_delay_seconds')
        try:
            delay = int(delay)
        except (TypeError, ValueError):
            return _error(request, 400, 'validation_error', 'inter_message_delay_seconds must be an integer.')
        if delay < 0:
            return _error(request, 400, 'validation_error', 'inter_message_delay_seconds must not be negative.')

        settings_row = get_blast_settings()
        BlastSettings.objects.filter(pk=settings_row.pk).update(
            inter_message_delay_seconds=delay, updated_at=timezone.now()
        )

        AuditLog.objects.create(
            actor=request.user,
            action='blast.settings.update',
            target=f'inter_message_delay_seconds={delay}',
            result=AuditLog.RESULT_SUCCESS,
        )
        return Response({'inter_message_delay_seconds': delay})


class BlastHistoryView(APIView):
    """GET /api/blast/history/ — flattened `BlastRecipient` across every
    campaign the user may see (reuses `campaigns_visible_to` as the
    Office boundary, filtered onto recipients via `campaign__in`), the
    server-side-paginated, filterable audit table the Inbox never shows
    (Discussed requirement — blast never creates a visible Inbox
    conversation; this table is where it's actually visible instead).

    Query params: `search` (destination or campaign name, icontains),
    `status`, `office` (Superadmin/Global Admin only — ignored
    otherwise, since a scoped user is already limited to their own
    Office by `campaigns_visible_to`), `template` (template id),
    `source` (`dashboard` or `api`), `date_from`/`date_to` (ISO dates,
    inclusive, filtered on `created_at`), `page`/`page_size`."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, (HasBlastScope | HasSystemAdministrationScope)]

    def get(self, request):
        from django.core.paginator import Paginator

        recipients = BlastRecipient.objects.filter(campaign__in=campaigns_visible_to(request.user)).select_related(
            'campaign', 'campaign__office', 'campaign__template', 'campaign__triggered_by_api_key'
        ).order_by('-created_at')

        search = request.query_params.get('search', '').strip()
        if search:
            recipients = recipients.filter(
                models.Q(destination__icontains=search) | models.Q(campaign__name__icontains=search)
            )

        status_filter = request.query_params.get('status', '').strip()
        if status_filter:
            recipients = recipients.filter(status=status_filter)

        if has_global_access(request.user):
            office_id = request.query_params.get('office', '').strip()
            if office_id:
                recipients = recipients.filter(campaign__office_id=office_id)

        template_id = request.query_params.get('template', '').strip()
        if template_id:
            recipients = recipients.filter(campaign__template_id=template_id)

        source = request.query_params.get('source', '').strip()
        if source == 'api':
            recipients = recipients.filter(campaign__triggered_by_api_key__isnull=False)
        elif source == 'dashboard':
            recipients = recipients.filter(campaign__triggered_by_api_key__isnull=True)

        date_from = request.query_params.get('date_from', '').strip()
        if date_from:
            recipients = recipients.filter(created_at__date__gte=date_from)
        date_to = request.query_params.get('date_to', '').strip()
        if date_to:
            recipients = recipients.filter(created_at__date__lte=date_to)

        page_size = min(int(request.query_params.get('page_size', 25) or 25), 100)
        paginator = Paginator(recipients, page_size)
        page_number = request.query_params.get('page', 1)
        page = paginator.get_page(page_number)

        results = [
            {
                'id': r.pk,
                'destination': r.destination,
                'status': r.status,
                'failure_reason': r.failure_reason,
                'variables': r.variables,
                'sent_at': r.sent_at,
                'created_at': r.created_at,
                'campaign': {
                    'id': r.campaign_id,
                    'name': r.campaign.name,
                    'office': {'id': r.campaign.office_id, 'name': r.campaign.office.name}
                    if r.campaign.office_id else None,
                    'template': {'id': r.campaign.template_id, 'name': r.campaign.template.name}
                    if r.campaign.template_id else None,
                    'source': 'api' if r.campaign.triggered_by_api_key_id else 'dashboard',
                },
            }
            for r in page.object_list
        ]
        return Response({
            'count': paginator.count,
            'num_pages': paginator.num_pages,
            'page': page.number,
            'results': results,
        })
