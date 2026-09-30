"""External Blast-trigger API — Discussed requirement: an external caller
(e.g. the tax system) triggers a send by referencing a template's stable
`key` (or, for a freeform/single-message send, supplying `message_template`
directly), authenticated by a dedicated, DB-backed `BlastApiKey` (never a
JWT, never the BFF/internal-service shared secrets used elsewhere in this
project — a genuinely new credential type, see `BlastApiKey`'s own
docstring).

Mounted at `/api/external/blast/send/` — a clearly separate namespace
from both `/api/blast/` (JWT-authenticated, human dashboard) and
`/internal/` (HasInternalServiceKey/office-dispatch-key-authenticated,
BFF<->Django/Office<->BFF traffic). The actual security boundary is the
API key check (`BlastApiKeyAuthentication`), not path secrecy — same
framing this project already uses for its `/internal/` prefix.

Design call (documented per CLAUDE.md rule 8 — never silently decided,
revised from this endpoint's original Office-scoped-key version): a
`BlastApiKey` is now deliberately GLOBAL — one key is meant to cover
every kind of send an external caller needs (a single ad-hoc message, a
freeform blast, or a templated blast) across ANY session, not just one
Office's. The request body therefore now REQUIRES an explicit `session`
field; `office` for the resulting campaign is derived from that
session's own `WahaSession.office` (may be `None`, same as any
Office-less session elsewhere in this project — never guessed, never
taken from the key). A single ad-hoc message is not a separate code
path at all — it is simply a one-recipient request with no
`template_key`: the exact same campaign/budget/dispatch pipeline
handles it, so it is auto-approved and dispatched (near-immediately,
since a lone recipient has nothing to queue behind) exactly like any
other campaign this endpoint creates.
"""

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.waha_sessions.models import WahaSession

from .limits import remaining_daily_budget
from .models import BlastApiKey, BlastCampaign, BlastRecipient, BlastTemplate
from .tasks import schedule_blast_campaign_task
from .templating import extract_variable_names

logger = logging.getLogger(__name__)


def _error(request, http_status, code, message, details=None):
    request_id = getattr(request, 'request_id', None)
    body = {'error': {'code': code, 'message': message, 'request_id': request_id}}
    if details is not None:
        body['error']['details'] = details
    return Response(body, status=http_status)


class _ApiKeyPrincipal:
    """A minimal stand-in for `request.user` when a request authenticates
    via `BlastApiKeyAuthentication` — there is no real Django `User` for
    an external caller. `AnonymousUser` was deliberately NOT reused here:
    its `is_authenticated` is hardcoded `False` (by Django's own design,
    "no one is logged in"), which would make `IsAuthenticated` reject
    every successfully-authenticated request too, not just an
    unauthenticated one.

    `pk` mirrors the resolved `BlastApiKey`'s own pk — DRF's
    `UserRateThrottle` (applied globally, `apps.core.throttling`) reads
    `request.user.pk` for an authenticated request's cache key; without
    this, every request through this view would 500 inside DRF's own
    throttle check, before this view's code ever runs (found live,
    running this exact request through the real throttle middleware)."""

    is_authenticated = True
    is_anonymous = False

    def __init__(self, pk):
        self.pk = pk


class BlastApiKeyAuthentication(BaseAuthentication):
    """Reads `X-Api-Key`, hashes it, looks up an active `BlastApiKey` by
    that hash (`BlastApiKey.authenticate` — a unique-indexed equality
    lookup, not a linear per-row `hmac.compare_digest` scan; see that
    method's own docstring for why that still gives the same timing-
    safety guarantee). Implemented as a DRF AUTHENTICATION class (not a
    permission) specifically so DRF returns 401 — not 403 — for a
    missing/wrong key: DRF only emits 401 when at least one configured
    authenticator defines `authenticate_header`; a plain permission-only
    check would always 403, regardless of the actual failure reason.

    No real Django `User` exists for an external caller — `request.user`
    is left as `AnonymousUser` (deliberately unauthenticated by Django's
    own definition; `IsAuthenticated` below is only satisfied once a
    valid key attaches a REAL `BlastApiKey` via `authenticate()`
    returning non-None). The view itself never reads `request.user` —
    only `request.blast_api_key`. The key is global (no Office of its
    own to fall back on — see `BlastApiKey`'s own docstring), so the
    view resolves `session`/`office` from the client-supplied `session`
    name in the body — never blindly trusted, always re-looked-up
    against the real `WahaSession` row server-side."""

    def authenticate(self, request):
        raw_key = request.META.get('HTTP_X_API_KEY', '')
        if not raw_key:
            return None
        key = BlastApiKey.authenticate(raw_key)
        if key is None:
            raise AuthenticationFailed('Invalid API key.')
        request.blast_api_key = key
        return (_ApiKeyPrincipal(key.pk), key)

    def authenticate_header(self, request):
        return 'X-Api-Key'


def _template_office_q(office):
    """A template is usable by an API key if it belongs to that key's own
    Office, or is global (`office=None`, shared/reusable — see
    `BlastTemplate.office`'s own docstring)."""
    from django.db.models import Q

    return Q(office=office) | Q(office__isnull=True)


class ExternalBlastSendView(APIView):
    """POST /api/external/blast/send/

    Body: `{"session": str, "template_key": str, "campaign_name": str
    (optional), "recipients": [{"destination": str, "variables": {...}},
    ...]}` — for a TEMPLATED send (`template_key` given: every recipient
    must carry exactly that template's declared variables, all-or-
    nothing, identical rule to the internal dashboard's own template
    path). OR `{"session": str, "message_template": str, "campaign_name":
    str (optional), "recipients": [{"destination": str}, ...]}` — for a
    FREEFORM send (`message_template` given instead: recipients need
    only `destination`, no variables). Exactly one of `template_key`/
    `message_template` must be given. A single-recipient freeform request
    is how an external caller sends one ad-hoc message — not a separate
    code path, just this same shape with one recipient.

    Header: `X-Api-Key` (required, checked by `BlastApiKeyAuthentication`),
    `Idempotency-Key` (required — a repeated key for the same
    `BlastApiKey` returns the already-created campaign instead of
    creating a second one).

    On success: creates the campaign directly in `approved`
    (`approved_by=None`, `triggered_by_api_key=<key>`,
    `approved_at=now()`) and calls `schedule_blast_campaign_task` — the
    SAME task the human-approval path already calls; auto-approval only
    skips the human click, never a second dispatch mechanism."""

    authentication_classes = [BlastApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        key: BlastApiKey = request.blast_api_key

        idempotency_key = request.headers.get('Idempotency-Key', '').strip()
        if not idempotency_key:
            return _error(request, 400, 'validation_error', 'Idempotency-Key header is required.')

        existing = BlastCampaign.objects.filter(
            triggered_by_api_key=key, idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            return Response({
                'campaign_id': existing.pk,
                'status': existing.status,
                'recipient_count': existing.recipients.count(),
                'triggered_by_api_key': key.name,
            })

        body = request.data if isinstance(request.data, dict) else {}
        session_name = str(body.get('session') or '').strip()
        template_key = str(body.get('template_key') or '').strip()
        message_template = body.get('message_template')
        raw_recipients = body.get('recipients')

        if not session_name:
            return _error(request, 400, 'validation_error', 'session is required.')
        if bool(template_key) == bool(message_template):
            return _error(
                request, 400, 'validation_error',
                'Exactly one of template_key or message_template must be given.',
            )
        if not isinstance(raw_recipients, list) or not raw_recipients:
            return _error(request, 400, 'validation_error', 'recipients must be a non-empty list.')

        try:
            session = WahaSession.objects.select_related('office').get(name=session_name)
        except WahaSession.DoesNotExist:
            return _error(request, 404, 'session_not_found', f'No WahaSession named {session_name!r} found.')

        template = None
        if template_key:
            template = BlastTemplate.objects.filter(
                key=template_key, is_active=True,
            ).filter(_template_office_q(session.office)).first()
            if template is None:
                return _error(request, 404, 'template_not_found', f'No active template with key {template_key!r} found.')
            resolved_message_template = template.content
            campaign_name = str(body.get('campaign_name') or '').strip() or f'External blast ({template_key})'
        else:
            resolved_message_template = str(message_template).strip()
            if not resolved_message_template:
                return _error(request, 400, 'validation_error', 'message_template must not be blank.')
            campaign_name = str(body.get('campaign_name') or '').strip() or 'External message'

        required_vars = extract_variable_names(resolved_message_template) if template is not None else set()
        normalized = []
        details = []
        seen_destinations = {}
        for index, item in enumerate(raw_recipients):
            if isinstance(item, str):
                item = {'destination': item}
            if not isinstance(item, dict):
                details.append({'index': index, 'error': 'Each recipient must be a string or an object.'})
                continue
            destination = str(item.get('destination') or '').strip()
            if not destination:
                details.append({'index': index, 'error': 'destination must not be blank.'})
                continue
            # Freeform (no template): variables are simply not applicable
            # — never validated, even if the caller sends some.
            if template is None:
                if destination in seen_destinations:
                    continue
                seen_destinations[destination] = True
                normalized.append({'destination': destination, 'variables': {}})
                continue

            variables = item.get('variables') or {}
            if not isinstance(variables, dict):
                details.append({'index': index, 'destination': destination, 'error': 'variables must be an object.'})
                continue
            row_keys = {k for k, v in variables.items() if str(v).strip() != ''}
            missing = required_vars - row_keys
            extra = row_keys - required_vars
            if missing or extra:
                details.append({
                    'index': index, 'destination': destination,
                    'missing': sorted(missing), 'extra': sorted(extra),
                })
                continue
            if destination in seen_destinations:
                continue
            seen_destinations[destination] = True
            normalized.append({'destination': destination, 'variables': variables})

        if details:
            return _error(
                request, 400, 'validation_error',
                'One or more recipients have missing or unexpected variables.', details=details,
            )
        if not normalized:
            return _error(request, 400, 'validation_error', 'At least one valid recipient is required.')

        remaining = remaining_daily_budget(session)
        if len(normalized) > remaining:
            return _error(
                request, 409, 'daily_budget_exceeded',
                (
                    f'This request has {len(normalized)} recipients, but session {session.name!r} only has '
                    f'{remaining} blast sends remaining today (Asia/Jakarta calendar day).'
                ),
            )

        now = timezone.now()
        try:
            with transaction.atomic():
                campaign = BlastCampaign.objects.create(
                    session=session,
                    office=session.office,
                    name=campaign_name,
                    template=template,
                    message_template=resolved_message_template,
                    status=BlastCampaign.STATUS_APPROVED,
                    created_by=key.created_by,
                    approved_by=None,
                    approved_at=now,
                    triggered_by_api_key=key,
                    idempotency_key=idempotency_key,
                )
                BlastRecipient.objects.bulk_create([
                    BlastRecipient(campaign=campaign, destination=r['destination'], variables=r['variables'])
                    for r in normalized
                ])
        except IntegrityError:
            # A concurrent request with the same Idempotency-Key won the
            # UniqueConstraint race — fetch and return what it created,
            # rather than erroring on a request that is, semantically, a
            # legitimate replay.
            existing = BlastCampaign.objects.filter(triggered_by_api_key=key, idempotency_key=idempotency_key).first()
            if existing is not None:
                return Response({
                    'campaign_id': existing.pk,
                    'status': existing.status,
                    'recipient_count': existing.recipients.count(),
                    'triggered_by_api_key': key.name,
                })
            raise

        BlastApiKey.objects.filter(pk=key.pk).update(last_used_at=now)
        schedule_blast_campaign_task.delay(campaign.pk)

        return Response({
            'campaign_id': campaign.pk,
            'status': campaign.status,
            'recipient_count': len(normalized),
            'triggered_by_api_key': key.name,
        }, status=201)
