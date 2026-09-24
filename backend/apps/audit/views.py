"""Internal (BFF-only) endpoint for audit-event writes —
docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 10. Used
for lifecycle actions (start/stop/restart/logout/qr/pairing-code) that have
no OutboundOperation to attach the audit write to (the send-message flow
writes its audit row via apps.operations.views.OutboundOperationResolveView
instead, in the same transaction as the operation resolve)."""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.internal_auth import HasInternalServiceKey

from .models import AuditLog
from .serializers import AuditEventSerializer


class AuditEventCreateView(APIView):
    authentication_classes = []
    permission_classes = [HasInternalServiceKey]

    def post(self, request):
        serializer = AuditEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        entry = AuditLog.objects.create(
            actor_id=data['actor_id'],
            action=data['action'],
            target=data['target'],
            result=data['result'],
        )
        return Response({'id': entry.pk}, status=status.HTTP_201_CREATED)
