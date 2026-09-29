import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.chats.conversation_engine import handle_conversation_message
from apps.chats.models import Chat, Contact, ConversationSession, Message
from apps.waha_sessions.models import WahaSession
from apps.webhooks.models import WebhookEvent
from apps.webhooks.parsing import (
    SUPPORTED_EVENT_TYPES,
    MessageParsingError,
    ParsedMessage,
    WebhookEnvelope,
    extract_phone_number,
    parse_message,
)

logger = logging.getLogger(__name__)


class DuplicateMessage(Exception):
    """Raised when a Message with this (session, provider_message_id)
    already exists — e.g. delivered via a different webhook event ID than
    originally expected. Not an error: the idempotency guarantee worked at
    the Message layer instead of the WebhookEvent layer."""


def ingest_webhook(envelope: WebhookEnvelope) -> WebhookEvent:
    """Records the raw event and, for supported event types, processes it.

    Idempotency: WebhookEvent.get_or_create on (session, provider_event_id)
    is the durable, first-committed step (Phase 2's unique constraint).
    - If a resolved (non-pending) WebhookEvent already exists, this is a
      true duplicate delivery — no reprocessing.
    - If a PENDING WebhookEvent already exists, a prior attempt started but
      never completed (e.g. an infra failure mid-processing) — this
      delivery is used to retry, rather than being treated as a no-op, so
      a stuck event can recover via WAHA's own webhook retries.
    """
    session, _ = WahaSession.objects.get_or_create(name=envelope.session_name)

    webhook_event, created = WebhookEvent.objects.get_or_create(
        session=session,
        provider_event_id=envelope.provider_event_id,
        defaults={'event_type': envelope.event_type, 'payload': envelope.payload},
    )

    if not created:
        webhook_event.attempts += 1
        webhook_event.save(update_fields=['attempts', 'updated_at'])
        if webhook_event.status != WebhookEvent.STATUS_PENDING:
            return webhook_event
        # else: still PENDING — fall through and (re)try processing.

    if envelope.event_type not in SUPPORTED_EVENT_TYPES:
        webhook_event.status = WebhookEvent.STATUS_UNSUPPORTED
        webhook_event.save(update_fields=['status', 'updated_at'])
        return webhook_event

    try:
        with transaction.atomic():
            parsed = parse_message(envelope.payload)
            message = persist_message(session, parsed)
    except MessageParsingError as exc:
        logger.warning('WebhookEvent %s could not be processed: %s', webhook_event.pk, exc)
        webhook_event.status = WebhookEvent.STATUS_FAILED
        webhook_event.error_message = str(exc)
        webhook_event.save(update_fields=['status', 'error_message', 'updated_at'])
        return webhook_event
    except DuplicateMessage:
        webhook_event.status = WebhookEvent.STATUS_PROCESSED
        webhook_event.processed_at = timezone.now()
        webhook_event.save(update_fields=['status', 'processed_at', 'updated_at'])
        return webhook_event

    # Conversation/Bot Engine (supersedes Step 12's operator_chat and Step
    # 13's inbox_lifecycle — both left in place, unmodified, just no
    # longer called from here). Deliberately AFTER the atomic block above
    # (never inside it): a failed outbound reply must never roll back the
    # inbound message that was already successfully received and
    # committed. Deliberately only reached from THIS live-webhook path,
    # never from `persist_message()` itself (also called by
    # `apps.sync.reconciliation` for history backfill, which must never
    # trigger a fresh bot reply for old messages).
    if message.direction == Message.DIRECTION_INBOUND:
        handle_conversation_message(session, message)

    webhook_event.status = WebhookEvent.STATUS_PROCESSED
    webhook_event.processed_at = timezone.now()
    webhook_event.save(update_fields=['status', 'processed_at', 'updated_at'])
    return webhook_event


def persist_message(session: WahaSession, parsed: ParsedMessage) -> Message:
    """Shared by webhook ingestion (Phase 3) and reconciliation (Phase 4,
    apps/sync/reconciliation.py) — both must apply identical Chat/Contact/
    Message persistence rules, so this is not duplicated."""
    # Step 9 (Inbox Office routing foundation) — a NEW Chat's `office` is
    # copied from `session.office` at creation time only (`defaults=` is
    # never applied by get_or_create to an already-existing row, so an
    # existing Chat's `office` is never overwritten here). `session.office`
    # being NULL (unmapped session) is copied through as NULL — never
    # guessed, never auto-assigned.
    chat, _ = Chat.objects.get_or_create(
        session=session,
        provider_chat_id=parsed.chat_provider_id,
        defaults={'is_group': parsed.is_group, 'office': session.office},
    )

    if not parsed.from_me and not parsed.is_group:
        # Contact identity is only ever derived from INBOUND, non-group
        # messages — for an outbound message, "Sender" is presumed to be
        # our own account and is deliberately NOT used to create/update a
        # Contact (unverified outbound structure; see module-level notes in
        # parsing.py and docs/generated/PHASE-3-WEBHOOK-INGESTION.md).
        contact, _ = Contact.objects.get_or_create(
            session=session,
            provider_contact_id=parsed.sender_provider_id,
        )
        phone_number = extract_phone_number(parsed.sender_alt)
        if phone_number and contact.phone_number != phone_number:
            contact.phone_number = phone_number
            contact.save(update_fields=['phone_number', 'updated_at'])

        # Inbox display-identity fix —
        # docs/generated/INBOX-IDENTITY-DISPLAY-AUDIT-REPORT.md. Same
        # already-resolved Contact as the phone-number update above —
        # this never creates a Contact and never touches any other
        # Chat/Contact row, so it cannot produce a duplicate identity.
        if parsed.push_name and contact.display_name != parsed.push_name:
            contact.display_name = parsed.push_name
            contact.save(update_fields=['display_name', 'updated_at'])

        if chat.contact_id != contact.id:
            chat.contact = contact
            chat.save(update_fields=['contact', 'updated_at'])

    direction = Message.DIRECTION_OUTBOUND if parsed.from_me else Message.DIRECTION_INBOUND

    # Per-Office Inbox history partitioning (discussed requirement) — the
    # Office this message belongs to. NOT simply `chat.office`: that
    # field only changes when a citizen actually picks a NEW Office, so
    # between two handoff rounds it still holds the PREVIOUS round's
    # Office — found live: a citizen who re-typed "Menu" and navigated
    # the bot again (without yet picking any Office) had that entire
    # pre-handoff exchange mis-tagged to whichever Office they'd picked
    # LAST time, showing up in that Office's Inbox even though the new
    # round hadn't been routed anywhere (yet, or ever, if they picked a
    # DIFFERENT Office this time). Correct source of truth: the Chat's
    # currently ACTIVE `ConversationSession.office` (apps.chats.models —
    # starts `None` on every fresh session, only set once a real Office
    # selection happens WITHIN that same round):
    #   - an active session exists -> its own `.office` (None until this
    #     round's citizen actually picks one — exactly "pre-handoff, not
    #     yet routed anywhere", never a stale carry-over).
    #   - no active session, and this is an OUTBOUND (bot-generated)
    #     message -> the most recently created session's `.office`,
    #     WHATEVER its current state — found live: the bot's own closing
    #     confirmation ("✅ Permintaan Anda telah selesai...",
    #     apps.chats.conversation_engine.close_waiting_session/
    #     expire_waiting_operator_session/_handle_menu_item's completion
    #     paths) always completes the session FIRST, then sends — so by
    #     the time this self-sent message is reconciled, its own session
    #     is already COMPLETED and would otherwise fall through to the
    #     `None` branch below, incorrectly banishing the citizen's own
    #     "you're done" confirmation out of the Office they were just
    #     routed to. Safe specifically for OUTBOUND: the bot never speaks
    #     first into a not-yet-started round (only a citizen's INBOUND
    #     message can be that), so an outbound message with no active
    #     session is always the tail end of the round that JUST ended,
    #     never pre-handoff chatter of one that hasn't started yet.
    #   - no active session, and this is an INBOUND (citizen) message, but
    #     this Chat has had a session before -> `None` (between rounds —
    #     never fall back to the stale `chat.office`; this is the
    #     "re-typed Menu, hasn't picked an Office yet this round" case).
    #   - this Chat has NEVER had a ConversationSession at all -> fall
    #     back to `chat.office` (a Chat the bot has never engaged with —
    #     e.g. a WahaSession-level static Office mapping predating the
    #     Bot Engine — where `chat.office` is a legitimate, stable value,
    #     not a leftover from a previous bot round).
    active_session = ConversationSession.objects.filter(
        chat=chat, state__in=ConversationSession.ACTIVE_STATES,
    ).only('office_id').first()
    if active_session is not None:
        message_office_id = active_session.office_id
    elif direction == Message.DIRECTION_OUTBOUND:
        latest_session = ConversationSession.objects.filter(chat=chat).order_by('-id').only('office_id').first()
        message_office_id = latest_session.office_id if latest_session is not None else chat.office_id
    elif ConversationSession.objects.filter(chat=chat).exists():
        message_office_id = None
    else:
        message_office_id = chat.office_id

    try:
        message = Message.objects.create(
            session=session,
            chat=chat,
            provider_message_id=parsed.provider_message_id,
            direction=direction,
            message_type=parsed.message_type,
            body=parsed.body,
            timestamp=parsed.timestamp,
            office_id=message_office_id,
            list_reply_id=parsed.list_reply_row_id or '',
        )
    except IntegrityError:
        raise DuplicateMessage(parsed.provider_message_id)

    if chat.last_message_at is None or parsed.timestamp > chat.last_message_at:
        chat.last_message_at = parsed.timestamp
        chat.save(update_fields=['last_message_at', 'updated_at'])

    return message
