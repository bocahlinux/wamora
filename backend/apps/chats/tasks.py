"""Conversation/Bot Engine — periodic auto-expiry for a WAITING_OPERATOR
`ConversationSession` nobody manually closed
(`apps.chats.views.ChatCloseSessionView` is the operator's own manual
counterpart). Scheduled from `config/celery.py`, onto the same
provisioned Celery beat this project already runs `apps.sync`'s periodic
reconciliation task on — no new infrastructure.

Also owns the human-like reply-delay tasks (discussed requirement,
`BotConfig.reply_delay_seconds`) — `apps.chats.conversation_engine`'s
`_send`/`_send_list` enqueue these instead of calling
`send_blast_message`/`send_list_message` directly whenever a delay is
configured. Mirrors `apps.blast.tasks`'s own explicit, stated rule:
NEVER a blocking `time.sleep` inside a task — `send_bot_*_reply_task`
starts the WAHA typing indicator immediately, then schedules its own
`finish_bot_*_reply_task` counterpart via `apply_async(countdown=...)`,
exactly like `schedule_blast_campaign_task`/`dispatch_blast_recipient_task`
already split scheduling from dispatch for the same reason."""

import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.blast.bff_client import BffDispatchError, send_blast_message, send_list_message, start_typing, stop_typing

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


def _typing_best_effort(fn, verb: str, session_name: str, chat_provider_id: str) -> None:
    """Never raises — a failed typing indicator is cosmetic only (see
    `apps.blast.bff_client._call_typing_endpoint`'s own docstring); the
    real reply must still be attempted regardless."""
    try:
        fn(session_name, chat_provider_id)
    except BffDispatchError as exc:
        logger.warning('conversation-engine %s failed for %s/%s: %s', verb, session_name, chat_provider_id, exc)


def _send_text_best_effort(session_name: str, chat_provider_id: str, idempotency_key: str, text: str) -> None:
    try:
        send_blast_message(session_name, chat_provider_id, text, idempotency_key)
    except BffDispatchError as exc:
        logger.warning('conversation-engine delayed send failed for %s/%s: %s', session_name, chat_provider_id, exc)


@shared_task
def send_bot_text_reply_task(session_name: str, chat_provider_id: str, idempotency_key: str, text: str, delay_seconds: int) -> None:
    """First half of a delayed plain-text reply (`BotConfig.reply_delay_seconds`
    > 0) — starts the WAHA typing indicator now, then schedules
    `finish_bot_text_reply_task` at `delay_seconds` from now. See this
    module's own docstring for why this is two tasks, never one task with
    a blocking sleep."""
    _typing_best_effort(start_typing, 'startTyping', session_name, chat_provider_id)
    finish_bot_text_reply_task.apply_async(
        args=[session_name, chat_provider_id, idempotency_key, text], countdown=delay_seconds,
    )


@shared_task
def finish_bot_text_reply_task(session_name: str, chat_provider_id: str, idempotency_key: str, text: str) -> None:
    """Fires once `delay_seconds` (from `send_bot_text_reply_task`) has
    elapsed — stops the typing indicator, then sends the real message."""
    _typing_best_effort(stop_typing, 'stopTyping', session_name, chat_provider_id)
    _send_text_best_effort(session_name, chat_provider_id, idempotency_key, text)


@shared_task
def send_bot_list_reply_task(
    session_name: str, chat_provider_id: str, idempotency_key: str, list_payload: dict, fallback_text: str, delay_seconds: int,
) -> None:
    """List-message counterpart to `send_bot_text_reply_task` — same
    typing-now/schedule-finish split."""
    _typing_best_effort(start_typing, 'startTyping', session_name, chat_provider_id)
    finish_bot_list_reply_task.apply_async(
        args=[session_name, chat_provider_id, idempotency_key, list_payload, fallback_text], countdown=delay_seconds,
    )


@shared_task
def finish_bot_list_reply_task(
    session_name: str, chat_provider_id: str, idempotency_key: str, list_payload: dict, fallback_text: str,
) -> None:
    """Counterpart to `finish_bot_text_reply_task` for a list-message
    reply — same `sendList`-fails-so-fall-back-to-plain-text behavior
    `apps.chats.conversation_engine._send_list` already has for the
    immediate (no-delay) path, reimplemented here since this runs in a
    separate task, not inline in the engine."""
    _typing_best_effort(stop_typing, 'stopTyping', session_name, chat_provider_id)
    try:
        result = send_list_message(session_name, chat_provider_id, list_payload, idempotency_key)
    except BffDispatchError as exc:
        logger.warning('conversation-engine delayed sendList failed for %s/%s: %s', session_name, chat_provider_id, exc)
        _send_text_best_effort(session_name, chat_provider_id, f'{idempotency_key}-list-fallback', fallback_text)
        return
    if result.get('status') != 'sent':
        logger.warning(
            'conversation-engine delayed sendList returned status=%s for %s/%s',
            result.get('status'), session_name, chat_provider_id,
        )
        _send_text_best_effort(session_name, chat_provider_id, f'{idempotency_key}-list-fallback', fallback_text)
