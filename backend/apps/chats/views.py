"""Inbox/Chat (canonical Phase 8) read + mark-as-read endpoints —
docs/generated/INBOX-CHAT-DECISION-REPORT.md.

Request path: Frontend -> Django direct (Section 1 of that report),
matching the Dashboard precedent — this data is durable, Django-owned,
and needs no live WAHA call to read. Sending a message stays
Frontend -> BFF -> WAHA, unchanged, reusing the existing sendText
endpoint (not touched by this module).

Auth: the same JWTAuthentication every Dashboard endpoint already uses,
plus a new `reading`-scope check (apps.authn.permissions.HasReadingScope)
per the decision report Section 5 — the first Django endpoints to check a
JWT scope, mirroring what the BFF already does for its own routes.
"""

from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.authn.authentication import JWTAuthentication
from apps.authn.permissions import HasOfficeAccess, HasOfficeAdminAccess, HasReadingScope

from .assignment import (
    NOT_AVAILABLE,
    NOT_OFFICE_MEMBER,
    NOT_OPERATOR_ROLE,
    USER_INACTIVE,
    USER_NOT_FOUND,
    assign_chat_to_operator,
    unassign_chat,
    valid_assignment_candidates,
)
from .authorization import can_view_chat, chats_visible_to
from .models import Chat
from .serializers import AssignChatSerializer, ChatListSerializer, MessageSerializer, OperatorCandidateSerializer


def _error(request, http_status, code, message):
    request_id = getattr(request, 'request_id', None)
    return Response({'error': {'code': code, 'message': message, 'request_id': request_id}}, status=http_status)


class ChatListView(APIView):
    """GET /api/chats/ — paginated, most-recently-active chat first.

    `nulls_last=True` is explicit rather than relying on the database's
    default NULL-ordering behavior for DESC, which is backend-dependent
    (PostgreSQL defaults to NULLS FIRST for DESC — the opposite of what a
    "most recent activity first" list wants — SQLite's default differs
    again) — this keeps ordering correct and identical across this
    project's PostgreSQL production database and its SQLite test
    settings.
    """

    authentication_classes = [JWTAuthentication]
    # Step 8 — Office/Global Admin/Operator reach Inbox via their
    # organizational role (HasOfficeAccess), not just the `reading` Group/
    # scope (which also gates unrelated global resources). Object-level
    # Office filtering below (chats_visible_to/can_view_chat) is unchanged.
    permission_classes = [IsAuthenticated, (HasReadingScope | HasOfficeAccess)]

    def get(self, request):
        queryset = chats_visible_to(request.user).select_related('contact', 'assigned_to').order_by(
            F('last_message_at').desc(nulls_last=True)
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = ChatListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class ChatMessagesView(APIView):
    """GET /api/chats/:id/messages/ — paginated message history for one
    chat, newest-first (matches WAHA's own REST history ordering
    convention — docs/12-WAHA-REFERENCE.md). `-timestamp, -id` (not
    `-timestamp` alone) so ordering is deterministic even if two messages
    share an identical timestamp — page boundaries must never depend on
    an unstable sort."""

    authentication_classes = [JWTAuthentication]
    # Step 8 — Office/Global Admin/Operator reach Inbox via their
    # organizational role (HasOfficeAccess), not just the `reading` Group/
    # scope (which also gates unrelated global resources). Object-level
    # Office filtering below (chats_visible_to/can_view_chat) is unchanged.
    permission_classes = [IsAuthenticated, (HasReadingScope | HasOfficeAccess)]

    def get(self, request, pk):
        chat = get_object_or_404(Chat, pk=pk)
        if not can_view_chat(request.user, chat):
            return _error(request, 403, 'forbidden', 'You do not have access to this chat.')
        queryset = chat.messages.prefetch_related('media').order_by('-timestamp', '-id')
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = MessageSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class ChatMarkReadView(APIView):
    """POST /api/chats/:id/read/ — sets Chat.last_read_at to now. No
    body. Chat-level, durable, UI-attention-only state — never touches
    WAHA (see the model field's own docstring in apps/chats/models.py)."""

    authentication_classes = [JWTAuthentication]
    # Step 8 — Office/Global Admin/Operator reach Inbox via their
    # organizational role (HasOfficeAccess), not just the `reading` Group/
    # scope (which also gates unrelated global resources). Object-level
    # Office filtering below (chats_visible_to/can_view_chat) is unchanged.
    permission_classes = [IsAuthenticated, (HasReadingScope | HasOfficeAccess)]

    def post(self, request, pk):
        chat = get_object_or_404(Chat, pk=pk)
        if not can_view_chat(request.user, chat):
            return _error(request, 403, 'forbidden', 'You do not have access to this chat.')
        chat.last_read_at = timezone.now()
        chat.save(update_fields=['last_read_at', 'updated_at'])
        return Response({'id': chat.pk, 'last_read_at': chat.last_read_at})


_ASSIGNMENT_ERROR_MESSAGES = {
    USER_NOT_FOUND: 'No such user.',
    USER_INACTIVE: 'This user account is deactivated.',
    NOT_OFFICE_MEMBER: 'This user is not a member of this chat’s Office.',
    NOT_OPERATOR_ROLE: 'Only an Operator may be assigned a chat.',
    NOT_AVAILABLE: 'This operator is not currently available.',
}


class ChatOperatorsView(APIView):
    """GET /api/chats/:id/operators/ — Step 14 foundation. Operators who
    may currently be assigned THIS chat: real Office membership matching
    `chat.office`, role `operator`, `is_available=True`, account
    `is_active`. Gated by `HasOfficeAdminAccess` (Superadmin/Global
    Admin/Office Admin — an Operator never assigns chats administratively,
    per Step 14's own scope) PLUS the same `can_view_chat` Office
    boundary every other Chat endpoint already enforces — no new
    authorization logic, reused as-is."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasOfficeAdminAccess]

    def get(self, request, pk):
        chat = get_object_or_404(Chat, pk=pk)
        if not can_view_chat(request.user, chat):
            return _error(request, 403, 'forbidden', 'You do not have access to this chat.')
        candidates = valid_assignment_candidates(chat.office)
        return Response(OperatorCandidateSerializer(candidates, many=True).data)


class ChatAssignView(APIView):
    """POST /api/chats/:id/assign/ — body: {user_id}. Same
    `HasOfficeAdminAccess` + `can_view_chat` gate as
    `ChatOperatorsView` — an Office Admin can only ever reach a Chat (and
    therefore only ever assign within) their own Office; Superadmin/
    Global Admin reach any Chat, but `assign_chat_to_operator` still
    requires the target to be a real member of THAT chat's Office
    (Step 14 Section 4: "target operator memang anggota Office tujuan"),
    so cross-Office assignment is impossible regardless of actor."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasOfficeAdminAccess]

    def post(self, request, pk):
        chat = get_object_or_404(Chat, pk=pk)
        if not can_view_chat(request.user, chat):
            return _error(request, 403, 'forbidden', 'You do not have access to this chat.')

        serializer = AssignChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated_chat, error = assign_chat_to_operator(chat, serializer.validated_data['user_id'])
        if error is not None:
            return _error(request, 400, error, _ASSIGNMENT_ERROR_MESSAGES[error])

        AuditLog.objects.create(
            actor=request.user,
            action='chat.assign',
            target=f'chat={updated_chat.pk} -> {updated_chat.assigned_to.username}',
            result=AuditLog.RESULT_SUCCESS,
        )
        return Response(ChatListSerializer(updated_chat).data)


class ChatUnassignView(APIView):
    """POST /api/chats/:id/unassign/ — no body. Same gate as
    ChatAssignView. Unassigning never removes the Chat from the Inbox —
    Office visibility (`chats_visible_to`) is entirely unaffected."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasOfficeAdminAccess]

    def post(self, request, pk):
        chat = get_object_or_404(Chat, pk=pk)
        if not can_view_chat(request.user, chat):
            return _error(request, 403, 'forbidden', 'You do not have access to this chat.')

        updated_chat = unassign_chat(chat)

        AuditLog.objects.create(
            actor=request.user, action='chat.unassign', target=f'chat={updated_chat.pk}', result=AuditLog.RESULT_SUCCESS
        )
        return Response(ChatListSerializer(updated_chat).data)
