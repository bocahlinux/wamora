"""Phase 8 dashboard backend foundation — docs/generated/PHASE-8-DASHBOARD-DATA-UI-AUDIT-REPORT.md
identified that the Dashboard's Row 2 (messages-today/trend, activity feed)
has no backing API yet. This module adds exactly two read-only aggregation
endpoints over existing models (`apps.chats.Message`, `apps.audit.AuditLog`,
`apps.webhooks.WebhookEvent`) — no new model, no migration.

Deliberately its own small app (`apps.dashboard`) rather than folded into
`apps.chats`/`apps.audit`: the activity feed reads from two unrelated
apps' models, so it doesn't belong to either one specifically, and the
project already gives each URL namespace (`/api/webhooks/`, `/api/auth/`,
...) its own app. This is that same pattern applied to `/api/dashboard/`,
not a new "dashboard service" abstraction — there is no shared service
layer here, just two independent views.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Count
from django.db.models.functions import TruncHour

from apps.audit.models import AuditLog
from apps.authn.authentication import JWTAuthentication
from apps.authn.permissions import HasReadingScope
from apps.chats.models import Message
from apps.webhooks.models import WebhookEvent

DEFAULT_ACTIVITY_LIMIT = 20
MAX_ACTIVITY_LIMIT = 100


class MessagesStatsView(APIView):
    """GET /api/dashboard/messages/ — today's message count plus an
    hourly trend, both computed with a single DB-side aggregate query
    each (no row iteration in Python).

    "Today" uses the UTC calendar day, matching this project's configured
    `TIME_ZONE = 'UTC'` / `USE_TZ = True` (settings.py) — not an
    unexamined assumption.

    Query/performance note (see the Phase 8 backend foundation report):
    `Message` is indexed on `(chat, timestamp)` only — there is no index
    supporting this chat-agnostic "all messages in a time range" filter,
    so this query is a sequential scan restricted by the WHERE clause.
    Acceptable at this project's current expected scale (a handful of
    WAHA sessions); flagged as a candidate `Index(fields=['timestamp'])`
    if message volume grows, not added speculatively here.

    Auth: Phase 12 (Security hardening) MUST-FIX #1 —
    docs/generated/PHASE-12-SECURITY-HARDENING-DESIGN-AUDIT-REPORT.md
    Section 3.2: this previously required only IsAuthenticated, with no
    scope check — any authenticated user, even one with zero assigned
    scopes, could read message-volume data. Now gated behind
    `HasReadingScope`, exactly mirroring `apps.chats.ChatListView`/
    `ChatMessagesView` (the existing precedent for read-only,
    conversation-adjacent data). Every normal operator's token already
    carries the 'reading' scope (Django Group membership named 'reading',
    apps.authn.jwt_utils.compute_scopes()) because the Inbox
    (frontend/src/pages/InboxPage.tsx) already depends on the exact same
    scope for apps.chats — this does not newly require anything a working
    Inbox user doesn't already have.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasReadingScope]

    def get(self, request):
        now = timezone.now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        today_qs = Message.objects.filter(timestamp__gte=day_start, timestamp__lt=day_end)
        messages_today = today_qs.count()

        buckets = {
            row['hour']: row['count']
            for row in (
                today_qs.annotate(hour=TruncHour('timestamp'))
                .values('hour')
                .annotate(count=Count('id'))
                .order_by('hour')
            )
        }
        trend = []
        for offset in range(24):
            hour = day_start + timedelta(hours=offset)
            trend.append({'hour': hour.isoformat(), 'count': buckets.get(hour, 0)})

        return Response({'messages_today': messages_today, 'trend': trend})


class ActivityFeedView(APIView):
    """GET /api/dashboard/activity/?limit=N — a bounded, merged, most-recent
    feed drawn from `AuditLog` (sensitive-operation audit trail) and
    `WebhookEvent` (inbound WAHA webhook events), the two existing
    "something happened" record types in the system. No new activity
    model is introduced.

    Bounded by construction: at most `limit` rows are fetched from each
    source (never the full table), merged in Python (at most 2*limit
    small dicts), then truncated to `limit` — no unbounded query.

    Query/performance note: `AuditLog` is indexed on `created_at`, so its
    query is index-backed. `WebhookEvent` is indexed on `status` only,
    not `received_at` — its query is a bounded but unindexed sort.
    Acceptable at current expected volume; flagged as a candidate
    `Index(fields=['received_at'])` if this becomes a hot path, not added
    speculatively here.

    Auth: Phase 12 (Security hardening) MUST-FIX #1 — same fix and
    reasoning as MessagesStatsView above, arguably sharper here since this
    view's results include every AuditLog row (actor/action/target/result
    of every session-control/blast-approval/recovery action in the
    system) — now gated behind HasReadingScope rather than bare
    IsAuthenticated.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, HasReadingScope]

    def get(self, request):
        limit = self._parse_limit(request.query_params.get('limit'))

        audit_entries = AuditLog.objects.order_by('-created_at', '-id')[:limit]
        webhook_events = WebhookEvent.objects.select_related('session').order_by('-received_at', '-id')[:limit]

        items = [
            {
                'id': f'audit-{entry.pk}',
                'type': 'audit',
                'action': entry.action,
                'target': entry.target,
                'result': entry.result,
                'occurred_at': entry.created_at,
            }
            for entry in audit_entries
        ] + [
            {
                'id': f'webhook-{event.pk}',
                'type': 'webhook',
                'action': event.event_type,
                'target': event.session.name,
                'result': event.status,
                'occurred_at': event.received_at,
            }
            for event in webhook_events
        ]

        items.sort(key=lambda item: (item['occurred_at'], item['id']), reverse=True)
        results = items[:limit]
        for item in results:
            item['occurred_at'] = item['occurred_at'].isoformat()

        return Response({'results': results})

    @staticmethod
    def _parse_limit(raw_value):
        if raw_value is None:
            return DEFAULT_ACTIVITY_LIMIT
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return DEFAULT_ACTIVITY_LIMIT
        if value < 1:
            return DEFAULT_ACTIVITY_LIMIT
        return min(value, MAX_ACTIVITY_LIMIT)
