"""Internal (BFF-only) endpoints for outbound-message idempotency —
docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 9's exact
state machine. Authenticated by apps.core.internal_auth.HasInternalServiceKey
(a shared static secret, not the end user's JWT — contract Section 8).
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.core.internal_auth import HasInternalServiceKey
from apps.waha_sessions.models import WahaSession

from .models import OutboundOperation
from .serializers import OutboundOperationRegisterSerializer, OutboundOperationResolveSerializer

logger = logging.getLogger(__name__)


def _serialize(operation: OutboundOperation, *, created: bool) -> dict:
    is_stale = (timezone.now() - operation.updated_at) > timedelta(seconds=settings.OUTBOUND_OPERATION_STALE_SECONDS)
    retryable = (
        not created
        and operation.status in (OutboundOperation.STATUS_PENDING, OutboundOperation.STATUS_UNKNOWN)
        and is_stale
    )
    return {
        'id': operation.pk,
        'created': created,
        'status': operation.status,
        'provider_message_id': operation.provider_message_id,
        'retryable': retryable,
    }


class OutboundOperationRegisterView(APIView):
    """POST — the pre-WAHA-call step of the send-message flow (contract
    Section 9, "First request" / "Duplicate request" rows). Registers a new
    OutboundOperation, or returns the existing one for a repeated
    idempotency key, never creating a second row for the same
    (session, idempotency_key) pair (enforced by the existing Phase 2
    unique constraint — a concurrent double-registration raises
    IntegrityError, handled below by re-fetching rather than erroring)."""

    authentication_classes = []
    permission_classes = [HasInternalServiceKey]

    def post(self, request):
        serializer = OutboundOperationRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        session, _ = WahaSession.objects.get_or_create(name=data['session'])

        with transaction.atomic():
            operation, created = OutboundOperation.objects.get_or_create(
                session=session,
                idempotency_key=data['idempotency_key'],
                defaults={
                    'destination': data['destination'],
                    'operation_type': data['operation_type'],
                    'status': OutboundOperation.STATUS_PENDING,
                },
            )

        return Response(_serialize(operation, created=created), status=status.HTTP_200_OK)


class OutboundOperationResolveView(APIView):
    """PATCH — the post-WAHA-call step (contract Section 9's "WAHA
    success"/"WAHA failure"/"Timeout" rows). Also writes the corresponding
    AuditLog row in the same transaction when actor/action/result are
    supplied, per contract Section 10 ("the same Django call that resolves
    the OutboundOperation also writes the AuditLog row") — avoiding a
    second BFF -> Django round trip for the send-message flow specifically.
    """

    authentication_classes = []
    permission_classes = [HasInternalServiceKey]

    def patch(self, request, pk):
        operation = get_object_or_404(OutboundOperation, pk=pk)

        serializer = OutboundOperationResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            operation.status = data['status']
            if data['provider_message_id']:
                operation.provider_message_id = data['provider_message_id']

            update_fields = ['status', 'provider_message_id', 'updated_at']

            if data['action'] and data['result']:
                audit_log = AuditLog.objects.create(
                    actor_id=data['actor_id'],
                    action=data['action'],
                    target=data['target'],
                    result=data['result'],
                )
                operation.audit_log = audit_log
                update_fields.append('audit_log')

            operation.save(update_fields=update_fields)

        return Response(_serialize(operation, created=False), status=status.HTTP_200_OK)
