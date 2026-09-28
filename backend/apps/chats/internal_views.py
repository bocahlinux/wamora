"""Step 11 — internal (server-to-server) endpoints for the "WP selects a
destination Office" foundation. Same `HasInternalServiceKey` pattern as
`apps.sync.internal_views.ReconciliationTriggerView` — not a Django/DRF
end-user JWT endpoint, no admin authentication (Step 11 Section 5:
"tidak membutuhkan authentication user admin jika memang dipanggil oleh
flow WhatsApp"). Whatever future process actually sends/receives the
WhatsApp menu would call these; nothing in this codebase calls them yet.
"""

from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.internal_auth import HasInternalServiceKey
from apps.waha_sessions.models import WahaSession

from .operator_chat import OFFICE_NOT_FOUND, available_operator_chat_offices, select_office_for_chat


class OperatorChatOfficeChoiceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class OperatorChatOfficesView(APIView):
    """GET /internal/operator-chat/offices/ — read-only. Returns only
    `id`/`name` for Offices currently available as a "Chat dengan
    Operator" destination — never OfficeMembership/admin/operator data,
    never an inactive or Inbox-disabled Office."""

    authentication_classes = []
    permission_classes = [HasInternalServiceKey]

    def get(self, request):
        offices = available_operator_chat_offices()
        return Response(OperatorChatOfficeChoiceSerializer(offices, many=True).data)


class SelectOperatorChatOfficeSerializer(serializers.Serializer):
    session = serializers.CharField()
    chat_provider_id = serializers.CharField()
    office_id = serializers.IntegerField()


class OperatorChatSelectOfficeView(APIView):
    """POST /internal/operator-chat/select-office/ — body: {session,
    chat_provider_id, office_id}. Re-validates `office_id` against the
    database on every call (Step 11 Section 7/8 — never trusts a
    previously-sent list, never trusts the client's own claim of which
    Office is available); sets that Chat's `office` only if still valid.
    Never creates or modifies `WahaSession.office`."""

    authentication_classes = []
    permission_classes = [HasInternalServiceKey]

    def post(self, request):
        serializer = SelectOperatorChatOfficeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        session = get_object_or_404(WahaSession, name=data['session'])
        chat, error = select_office_for_chat(session, data['chat_provider_id'], data['office_id'])

        if error is not None:
            status_code = 404 if error == OFFICE_NOT_FOUND else 409
            return Response(
                {'error': {'code': error, 'message': 'This Office is not a valid destination.'}},
                status=status_code,
            )

        return Response({'chat_id': chat.pk, 'office_id': chat.office_id, 'office_name': chat.office.name})
