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

from apps.authn.authentication import JWTAuthentication
from apps.authn.permissions import HasReadingScope

from .models import Chat
from .serializers import ChatListSerializer, MessageSerializer


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
    permission_classes = [IsAuthenticated, HasReadingScope]

    def get(self, request):
        queryset = Chat.objects.select_related('contact').order_by(
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
    permission_classes = [IsAuthenticated, HasReadingScope]

    def get(self, request, pk):
        chat = get_object_or_404(Chat, pk=pk)
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
    permission_classes = [IsAuthenticated, HasReadingScope]

    def post(self, request, pk):
        chat = get_object_or_404(Chat, pk=pk)
        chat.last_read_at = timezone.now()
        chat.save(update_fields=['last_read_at', 'updated_at'])
        return Response({'id': chat.pk, 'last_read_at': chat.last_read_at})
