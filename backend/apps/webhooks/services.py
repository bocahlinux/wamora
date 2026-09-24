import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.chats.models import Chat, Contact, Message
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
            persist_message(session, parsed)
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

    webhook_event.status = WebhookEvent.STATUS_PROCESSED
    webhook_event.processed_at = timezone.now()
    webhook_event.save(update_fields=['status', 'processed_at', 'updated_at'])
    return webhook_event


def persist_message(session: WahaSession, parsed: ParsedMessage) -> Message:
    """Shared by webhook ingestion (Phase 3) and reconciliation (Phase 4,
    apps/sync/reconciliation.py) — both must apply identical Chat/Contact/
    Message persistence rules, so this is not duplicated."""
    chat, _ = Chat.objects.get_or_create(
        session=session,
        provider_chat_id=parsed.chat_provider_id,
        defaults={'is_group': parsed.is_group},
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

    try:
        message = Message.objects.create(
            session=session,
            chat=chat,
            provider_message_id=parsed.provider_message_id,
            direction=direction,
            message_type=parsed.message_type,
            body=parsed.body,
            timestamp=parsed.timestamp,
        )
    except IntegrityError:
        raise DuplicateMessage(parsed.provider_message_id)

    if chat.last_message_at is None or parsed.timestamp > chat.last_message_at:
        chat.last_message_at = parsed.timestamp
        chat.save(update_fields=['last_message_at', 'updated_at'])

    return message
