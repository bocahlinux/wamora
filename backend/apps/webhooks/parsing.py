"""Parses raw WAHA webhook payloads into structured data for ingestion.

FIELD-NAME ASSUMPTIONS — flagged here because they are NOT independently
verified against a live WAHA instance (no live access was available while
this was written; see docs/generated/PHASE-3-WEBHOOK-INGESTION.md, "Known
limitations", for the full list and reasoning):

- Envelope: top-level `event` (str), `session` (str), `payload` (dict).
  Inferred from the field paths given in the reported example
  (`payload.from`, `payload._data.Info.Chat`, ...), which imply a `payload`
  wrapper, plus WAHA's general public webhook envelope documentation.
- Stable event/message ID: `payload['id']`. NOT present in the reported
  example (which only showed from/fromMe/body/_data.Info.*) — assumed from
  WAHA's general public API documentation. This is the single most
  important assumption to verify live before trusting this in production;
  see docs/12-WAHA-REFERENCE.md.
- Chat/Sender identity: prefers `payload['_data']['Info']['Chat']` /
  `['Sender']` (confirmed field names from the Phase 2.5 reported example),
  falling back to the top-level `payload['from']` (also confirmed present)
  if the nested form is absent.
- Alt identity: `payload['_data']['Info']['SenderAlt']` (confirmed field
  name from the reported example).
- Direction: `payload['fromMe']` (confirmed field, boolean), falling back
  to `payload['_data']['Info']['IsFromMe']`.
- Body: `payload['body']` (confirmed field).
- Group flag: `payload['_data']['Info']['IsGroup']` — field name given in
  the Phase 3 objectives list, but no concrete value was observed; defaults
  to False if absent.
- Outbound (fromMe=True) structure is UNVERIFIED — this parser applies the
  SAME field extraction to both directions, since no evidence of a
  different outbound shape exists, but Phase 3 instructions explicitly
  warn not to assume symmetry, so this remains flagged.
"""

import datetime
from dataclasses import dataclass
from typing import Optional

from django.utils import timezone

SUPPORTED_EVENT_TYPES = {'message'}


class EnvelopeValidationError(Exception):
    """The webhook body fails basic envelope validation (missing/invalid
    `event`, `session`, `payload`, or no discoverable stable ID — the
    schema's WebhookEvent.provider_event_id is NOT NULL, so an event with
    no discoverable ID cannot be durably recorded at all)."""


class MessageParsingError(Exception):
    """A `message` event is missing data needed to safely persist a
    Message. Callers must record this as a failed WebhookEvent and must
    never fabricate the missing data."""


@dataclass
class WebhookEnvelope:
    event_type: str
    session_name: str
    provider_event_id: str
    payload: dict


@dataclass
class ParsedMessage:
    provider_message_id: str
    chat_provider_id: str
    sender_provider_id: str
    sender_alt: Optional[str]
    from_me: bool
    body: str
    message_type: str
    is_group: bool
    timestamp: datetime.datetime
    # Inbox display-identity fix — docs/generated/INBOX-IDENTITY-DISPLAY-AUDIT-REPORT.md.
    # WhatsApp's own self-reported sender display name. First observed in
    # this project's evidence via a real live webhook
    # (`_data.Info.PushName`); also already noted as an available REST
    # field in docs/12-WAHA-REFERENCE.md's "additional _data.Info.*
    # fields" list. Optional and defensively extracted like every other
    # field here — never required, never guessed when absent.
    push_name: Optional[str]


def parse_envelope(data) -> WebhookEnvelope:
    if not isinstance(data, dict):
        raise EnvelopeValidationError('Webhook body must be a JSON object')

    event_type = data.get('event')
    session_name = data.get('session')
    payload = data.get('payload')

    if not isinstance(event_type, str) or not event_type:
        raise EnvelopeValidationError('Missing or invalid "event"')
    if not isinstance(session_name, str) or not session_name:
        raise EnvelopeValidationError('Missing or invalid "session"')
    if not isinstance(payload, dict):
        raise EnvelopeValidationError('Missing or invalid "payload"')

    provider_event_id = payload.get('id')
    if not isinstance(provider_event_id, str) or not provider_event_id:
        raise EnvelopeValidationError('Missing or invalid "payload.id"')

    return WebhookEnvelope(
        event_type=event_type,
        session_name=session_name,
        provider_event_id=provider_event_id,
        payload=payload,
    )


def parse_message(payload: dict) -> ParsedMessage:
    info = {}
    data_field = payload.get('_data')
    if isinstance(data_field, dict):
        candidate = data_field.get('Info')
        if isinstance(candidate, dict):
            info = candidate

    provider_message_id = payload.get('id')
    if not isinstance(provider_message_id, str) or not provider_message_id:
        raise MessageParsingError('Missing stable message id (payload.id)')

    chat_provider_id = info.get('Chat') or payload.get('from')
    if not isinstance(chat_provider_id, str) or not chat_provider_id:
        raise MessageParsingError('Missing chat identifier (Info.Chat / payload.from)')

    sender_provider_id = info.get('Sender') or payload.get('from')
    if not isinstance(sender_provider_id, str) or not sender_provider_id:
        raise MessageParsingError('Missing sender identifier (Info.Sender / payload.from)')

    sender_alt = info.get('SenderAlt')
    if not isinstance(sender_alt, str) or not sender_alt:
        sender_alt = None

    from_me = payload.get('fromMe')
    if from_me is None:
        from_me = info.get('IsFromMe')
    if not isinstance(from_me, bool):
        raise MessageParsingError('Missing or invalid "fromMe" / "Info.IsFromMe"')

    body = payload.get('body')
    if not isinstance(body, str):
        body = ''

    message_type = payload.get('type') or info.get('Type')
    if not isinstance(message_type, str):
        message_type = ''

    is_group = info.get('IsGroup')
    if not isinstance(is_group, bool):
        is_group = False

    timestamp = parse_timestamp(payload.get('timestamp'))

    push_name = info.get('PushName')
    if not isinstance(push_name, str) or not push_name:
        push_name = None

    return ParsedMessage(
        provider_message_id=provider_message_id,
        chat_provider_id=chat_provider_id,
        sender_provider_id=sender_provider_id,
        sender_alt=sender_alt,
        from_me=from_me,
        body=body,
        message_type=message_type,
        is_group=is_group,
        timestamp=timestamp,
        push_name=push_name,
    )


def extract_phone_number(alt_identifier: Optional[str]) -> str:
    """Phase 2.5 rule: populate phone_number from an Alt identifier only
    when present AND safely interpretable as the phone/JID form — never
    guessed, never derived from the LID form."""
    if not alt_identifier or not alt_identifier.endswith('@s.whatsapp.net'):
        return ''
    number = alt_identifier.split('@', 1)[0]
    return number if number.isdigit() else ''


def parse_timestamp(raw) -> datetime.datetime:
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        try:
            return datetime.datetime.fromtimestamp(raw, tz=datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    # Fallback: server receipt time. Not the true WhatsApp message time —
    # flagged as a last-resort default; see module docstring.
    return timezone.now()
