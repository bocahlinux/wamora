"""Internal (BFF-only) endpoint that triggers a targeted reconciliation
for one chat — docs/generated/INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md.

Same `HasInternalServiceKey` pattern already used by
`apps.operations`'s internal endpoints
(docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 8) — no
new auth mechanism. The BFF calls this fire-and-forget, immediately after
a confirmed successful outbound send (bff/src/routes/messages.ts); it
does not read or act on this endpoint's response body.
"""

import logging

from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.internal_auth import HasInternalServiceKey

from .executors import trigger_reconciliation

logger = logging.getLogger(__name__)


class ReconciliationTriggerSerializer(serializers.Serializer):
    session = serializers.CharField()
    chat_id = serializers.CharField()


class ReconciliationTriggerView(APIView):
    """POST /internal/reconciliation/trigger/ — body: {session, chat_id}."""

    authentication_classes = []
    permission_classes = [HasInternalServiceKey]

    def post(self, request):
        serializer = ReconciliationTriggerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = serializer.validated_data['session']
        chat_id = serializer.validated_data['chat_id']

        result = trigger_reconciliation(session, chat_id)

        if result is None:
            # EXECUTOR_CELERY — already enqueued; no synchronous result yet.
            return Response({'triggered': True, 'executor': 'celery'}, status=status.HTTP_202_ACCEPTED)
        return Response(
            {
                'triggered': True,
                'executor': 'sync',
                'messages_inserted': result.messages_inserted,
                'had_error': result.had_error,
            },
            status=status.HTTP_200_OK,
        )
