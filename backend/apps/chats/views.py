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

from django.db.models import Exists, F, OuterRef
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.models import AuditLog
from apps.authn.authentication import JWTAuthentication
from apps.authn.permissions import HasOfficeAccess, HasOfficeAdminAccess, HasReadingScope
from apps.offices.authorization import get_user_office, has_global_access
from apps.offices.models import Office

from .assignment import (
    ALREADY_CLAIMED,
    NOT_AVAILABLE,
    NOT_ELIGIBLE,
    NOT_OFFICE_MEMBER,
    NOT_OPERATOR_ROLE,
    USER_INACTIVE,
    USER_NOT_FOUND,
    assign_chat_to_operator,
    claim_chat,
    transfer_chat,
    unassign_chat,
    valid_assignment_candidates,
)
from .authorization import can_manage_chat, can_view_chat, chats_visible_to
from .conversation_engine import close_waiting_session
from .models import Chat, ConversationSession
from .serializers import (
    AssignChatSerializer,
    ChatListSerializer,
    MessageSerializer,
    OperatorCandidateSerializer,
    TransferChatSerializer,
)


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
        queryset = chats_visible_to(request.user).select_related('contact', 'assigned_to').annotate(
            _waiting_for_operator=Exists(
                ConversationSession.objects.filter(
                    chat=OuterRef('pk'), state=ConversationSession.STATE_WAITING_OPERATOR,
                )
            )
        ).order_by(
            F('last_message_at').desc(nulls_last=True)
        )
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = ChatListSerializer(page, many=True, context={'request': request})
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
        if not has_global_access(request.user):
            # Per-Office Inbox history partitioning (discussed
            # requirement) — an Office Admin/Operator sees only messages
            # snapshotted to their OWN Office (Message.office's own field
            # comment) — this also hides the bot's own pre-handoff menu
            # navigation, which is always office=None, and any OTHER
            # Office's period of history for this same Chat.
            # Superadmin/Global Admin are exempt (discussed requirement —
            # both see full, unfiltered history).
            queryset = queryset.filter(office=get_user_office(request.user))
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

_CLAIM_ERROR_MESSAGES = {
    NOT_ELIGIBLE: 'You are not eligible to claim this chat.',
    ALREADY_CLAIMED: 'This chat has already been claimed by someone else.',
}


def _has_open_waiting_operator_session(chat) -> bool:
    # Discussed requirement — hard block: once claimed, a chat handed off
    # to a human operator must be explicitly closed
    # (apps.chats.conversation_engine.close_waiting_session, via
    # ChatCloseSessionView) before it can be unassigned or handed to a
    # DIFFERENT user through the ordinary assign/unassign endpoints below.
    # Deliberately NOT applied to a future Superadmin/Global Admin
    # "transfer to another Office" action (not built yet) — that action
    # is specifically meant to move an open conversation, exempt by
    # design, never through these two endpoints.
    return ConversationSession.objects.filter(
        chat=chat, state=ConversationSession.STATE_WAITING_OPERATOR,
    ).exists()


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
        if not can_manage_chat(request.user, chat):
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
        if not can_manage_chat(request.user, chat):
            return _error(request, 403, 'forbidden', 'You do not have access to this chat.')

        serializer = AssignChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_user_id = serializer.validated_data['user_id']

        if (
            chat.assigned_to_id is not None and chat.assigned_to_id != target_user_id
            and _has_open_waiting_operator_session(chat)
        ):
            return _error(
                request, 400, 'session_not_closed',
                'Close this chat’s session before handing it to someone else.',
            )

        updated_chat, error = assign_chat_to_operator(chat, target_user_id)
        if error is not None:
            return _error(request, 400, error, _ASSIGNMENT_ERROR_MESSAGES[error])

        AuditLog.objects.create(
            actor=request.user,
            action='chat.assign',
            target=f'chat={updated_chat.pk} -> {updated_chat.assigned_to.username}',
            result=AuditLog.RESULT_SUCCESS,
        )
        return Response(ChatListSerializer(updated_chat, context={'request': request}).data)


class ChatUnassignView(APIView):
    """POST /api/chats/:id/unassign/ — no body. Same gate as
    ChatAssignView. Unassigning never removes the Chat from the Inbox —
    Office visibility (`chats_visible_to`) is entirely unaffected."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasOfficeAdminAccess]

    def post(self, request, pk):
        chat = get_object_or_404(Chat, pk=pk)
        if not can_manage_chat(request.user, chat):
            return _error(request, 403, 'forbidden', 'You do not have access to this chat.')

        if chat.assigned_to_id is not None and _has_open_waiting_operator_session(chat):
            return _error(
                request, 400, 'session_not_closed', 'Close this chat’s session before unassigning it.',
            )

        updated_chat = unassign_chat(chat)

        AuditLog.objects.create(
            actor=request.user, action='chat.unassign', target=f'chat={updated_chat.pk}', result=AuditLog.RESULT_SUCCESS
        )
        return Response(ChatListSerializer(updated_chat, context={'request': request}).data)


class ChatClaimView(APIView):
    """POST /api/chats/:id/claim/ — no body, always self-assigns the
    caller (`apps.chats.assignment.claim_chat`) — the "ambil" action for
    `apps.dashboard.views.PendingChatsView`'s queue. `HasOfficeAccess`
    (not `HasOfficeAdminAccess`) — a real Operator claims for themselves
    here; an Office Admin/Global Admin/Superadmin may also claim
    (relevant for a `chat.office=None` chat, which only a globally-
    accessing actor can even see — `claim_chat`'s own docstring)."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasOfficeAccess]

    def post(self, request, pk):
        chat = get_object_or_404(Chat, pk=pk)
        if not can_manage_chat(request.user, chat):
            return _error(request, 403, 'forbidden', 'You do not have access to this chat.')

        updated_chat, error = claim_chat(chat, request.user)
        if error is not None:
            return _error(request, 400, error, _CLAIM_ERROR_MESSAGES[error])

        AuditLog.objects.create(
            actor=request.user, action='chat.claim', target=f'chat={updated_chat.pk}', result=AuditLog.RESULT_SUCCESS,
        )
        return Response(ChatListSerializer(updated_chat, context={'request': request}).data)


class ChatCloseSessionView(APIView):
    """POST /api/chats/:id/close-session/ — no body. Manually ends this
    Chat's WAITING_OPERATOR `ConversationSession`
    (`apps.chats.conversation_engine.close_waiting_session`) — the
    operator's own counterpart to
    `apps.chats.tasks.expire_waiting_operator_sessions_task`'s 24h
    auto-expiry. The bot resumes answering this Chat's next message
    afterward.

    `HasOfficeAccess` (not `HasOfficeAdminAccess`) — the Operator actually
    handling this conversation, not only an Office Admin, is who normally
    ends it; `can_view_chat` below still enforces the same per-Office
    boundary every other Chat endpoint does."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasOfficeAccess]

    def post(self, request, pk):
        chat = get_object_or_404(Chat, pk=pk)
        if not can_manage_chat(request.user, chat):
            return _error(request, 403, 'forbidden', 'You do not have access to this chat.')

        session = close_waiting_session(chat)
        if session is None:
            return _error(
                request, 400, 'no_active_session', 'This chat has no session waiting for an operator.',
            )

        AuditLog.objects.create(
            actor=request.user, action='chat.close_session', target=f'chat={chat.pk} session={session.pk}',
            result=AuditLog.RESULT_SUCCESS,
        )
        return Response(ChatListSerializer(chat, context={'request': request}).data)


class ChatTransferView(APIView):
    """POST /api/chats/:id/transfer/ — body: {office_id, user_id}.
    Superadmin/Global Admin ONLY (discussed requirement) — moves this
    Chat, and its currently-open WAITING_OPERATOR session if any, to a
    DIFFERENT Office and a specific member of it
    (`apps.chats.assignment.transfer_chat`). Deliberately NOT gated by
    `_has_open_waiting_operator_session` — this is the one action whose
    entire purpose is redirecting an open handoff across Offices;
    `ChatAssignView`/`ChatUnassignView` remain blocked for everyone else.

    No existing permission class matches "globally-accessing actor only,
    explicitly excluding Office Admin" (`HasOfficeAdminAccess` includes
    Office Admin; `HasOfficeAccess` includes Operator too) — checked
    inline instead of introducing one for a single call site."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not has_global_access(request.user):
            return _error(
                request, 403, 'forbidden', 'Only a Superadmin/Global Admin may transfer a chat to another Office.',
            )
        chat = get_object_or_404(Chat, pk=pk)

        serializer = TransferChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            target_office = Office.objects.get(pk=serializer.validated_data['office_id'])
        except Office.DoesNotExist:
            return _error(request, 400, 'invalid', 'office_id does not reference a real Office.')

        updated_chat, error = transfer_chat(chat, target_office, serializer.validated_data['user_id'])
        if error is not None:
            return _error(request, 400, error, _ASSIGNMENT_ERROR_MESSAGES[error])

        AuditLog.objects.create(
            actor=request.user, action='chat.transfer',
            target=f'chat={updated_chat.pk} -> office={target_office.pk} user={updated_chat.assigned_to.username}',
            result=AuditLog.RESULT_SUCCESS,
        )
        return Response(ChatListSerializer(updated_chat, context={'request': request}).data)
