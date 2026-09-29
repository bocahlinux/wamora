"""Conversation/Bot Engine — periodic auto-expiry for a WAITING_OPERATOR
`ConversationSession` nobody manually closed
(`apps.chats.views.ChatCloseSessionView` is the operator's own manual
counterpart). Scheduled from `config/celery.py`, onto the same
provisioned Celery beat this project already runs `apps.sync`'s periodic
reconciliation task on — no new infrastructure.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .conversation_engine import expire_waiting_operator_session
from .models import ConversationSession

logger = logging.getLogger(__name__)


@shared_task
def expire_waiting_operator_sessions_task():
    """Closes every WAITING_OPERATOR session whose Chat has had no
    activity from EITHER side (`Chat.last_message_at` — bumped by an
    inbound message, docs/generated/INBOX-OUTBOUND-RECONCILIATION and by
    an operator's own outbound reply via the post-send reconciliation
    trigger) for longer than
    `settings.CONVERSATION_WAITING_OPERATOR_TIMEOUT_SECONDS`. Deliberately
    NOT the session's own `updated_at` — that only reflects when it
    ENTERED WAITING_OPERATOR, not whether anyone has since replied
    (discussed requirement: "1x24 jam tanpa balasan dari operator ATAUPUN
    WP", an inactivity timeout, not a fixed handoff-duration one). A
    Chat only ever reaches WAITING_OPERATOR after at least one inbound
    message, so `last_message_at` is never null here. Each session is
    closed independently — one failure (logged, never raised) does not
    block the rest, and the filter itself makes a re-run idempotent (an
    already-closed session no longer matches it)."""
    cutoff = timezone.now() - timezone.timedelta(seconds=settings.CONVERSATION_WAITING_OPERATOR_TIMEOUT_SECONDS)
    sessions = ConversationSession.objects.filter(
        state=ConversationSession.STATE_WAITING_OPERATOR, chat__last_message_at__lt=cutoff,
    ).select_related('chat', 'chat__session', 'chat__office')

    expired = 0
    for session in sessions:
        try:
            expire_waiting_operator_session(session)
            expired += 1
        except Exception:
            logger.exception('Failed to auto-expire ConversationSession %s', session.pk)

    if expired:
        logger.info('Auto-expired %d WAITING_OPERATOR conversation session(s)', expired)
    return expired
