"""Office/Celery -> Tencent/BFF internal dispatch call — finalized
decision 1. A NEW call direction (this codebase's only prior
cross-service traffic was BFF -> Django, `apps.operations`/`apps.audit`'s
internal endpoints); authenticated by a NEW, distinct shared secret
(`OFFICE_DISPATCH_SERVICE_KEY`, never `INTERNAL_SERVICE_KEY`, which
authenticates the opposite direction). Calls exactly one BFF endpoint
(`POST /internal/blast/send`), which itself only ever calls WAHA's
allowlisted `sendText` — never a generic proxy (CLAUDE.md rule 5).

Isolated in its own module, mirroring `apps.sync.waha_client.WahaClient`'s
own reasoning: a single narrow external call, easy to mock in tests
without a live BFF process (the task explicitly must remain unit-testable
without ever exercising a live BFF/WAHA call)."""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class BffDispatchError(Exception):
    """Raised for a request-level failure only (network error, timeout, or
    a non-2xx/invalid-JSON response) — never for a WAHA-reported send
    failure, which is a normal, successful HTTP response with
    `{"status": "failed"}` (see send_blast_message's return contract)."""


def send_blast_message(session_name: str, destination: str, text: str, idempotency_key: str) -> dict:
    """POST to the BFF's internal blast-send endpoint. Returns
    `{"status": "sent", "provider_message_id": str | None}` or
    `{"status": "failed"}` or `{"status": "unknown"}` on a clean response
    from the BFF (mirroring bff/src/routes/messages.ts's own
    sent/failed/unknown vocabulary for the single 1:1 send flow). Raises
    BffDispatchError for anything that isn't a clean, parseable response
    from the BFF itself (network error, timeout, non-200, bad JSON) — the
    caller (apps.blast.tasks) treats that the same way it treats a WAHA
    'failed' outcome, since from a dispatch-task's point of view neither
    can be told apart from "this recipient did not get a message" and
    both must NOT be auto-retried (decision 5).

    Never logs or includes `settings.OFFICE_DISPATCH_SERVICE_KEY` in any
    exception message.
    """
    if not settings.BFF_INTERNAL_BASE_URL:
        raise BffDispatchError('BFF_INTERNAL_BASE_URL is not configured')
    if not settings.OFFICE_DISPATCH_SERVICE_KEY:
        raise BffDispatchError('OFFICE_DISPATCH_SERVICE_KEY is not configured')

    url = f"{settings.BFF_INTERNAL_BASE_URL.rstrip('/')}/internal/blast/send"
    timeout_seconds = settings.BFF_INTERNAL_TIMEOUT_MS / 1000

    try:
        response = requests.post(
            url,
            json={'session': session_name, 'chatId': destination, 'text': text},
            headers={
                'X-Office-Dispatch-Key': settings.OFFICE_DISPATCH_SERVICE_KEY,
                'Idempotency-Key': idempotency_key,
            },
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        logger.warning('BFF blast-dispatch request failed: %s', type(exc).__name__)
        raise BffDispatchError(f'BFF request failed: {type(exc).__name__}') from exc

    if response.status_code != 200:
        logger.warning('BFF blast-dispatch returned HTTP %s', response.status_code)
        raise BffDispatchError(f'BFF returned HTTP {response.status_code}')

    try:
        data = response.json()
    except ValueError as exc:
        raise BffDispatchError('BFF response was not valid JSON') from exc

    if not isinstance(data, dict) or data.get('status') not in ('sent', 'failed', 'unknown'):
        raise BffDispatchError('Unrecognized BFF blast-dispatch response shape')

    return {
        'status': data['status'],
        'provider_message_id': data.get('providerMessageId') if isinstance(data.get('providerMessageId'), str) else None,
    }


def send_list_message(session_name: str, destination: str, list_payload: dict, idempotency_key: str) -> dict:
    """POST to the BFF's internal list-send endpoint
    (`POST /internal/blast/send-list`, `bff/src/routes/internalBlast.ts`)
    — Conversation/Bot Engine interactive list menus
    (`apps.chats.conversation_engine`). Same request/response contract as
    `send_blast_message` above, just a different WAHA operation
    underneath (`sendList`, CLAUDE.md rule 5 — a new, explicitly
    allowlisted endpoint, `sendText` untouched). `list_payload` is WAHA's
    own `message` object shape (`title`/`description`/`footer`/`button`/
    `sections`), live-verified by the project operator directly against
    this deployment's WAHA (GOWS engine) — passed through unchanged, this
    function never reshapes it.

    Never logs or includes `settings.OFFICE_DISPATCH_SERVICE_KEY` in any
    exception message."""
    if not settings.BFF_INTERNAL_BASE_URL:
        raise BffDispatchError('BFF_INTERNAL_BASE_URL is not configured')
    if not settings.OFFICE_DISPATCH_SERVICE_KEY:
        raise BffDispatchError('OFFICE_DISPATCH_SERVICE_KEY is not configured')

    url = f"{settings.BFF_INTERNAL_BASE_URL.rstrip('/')}/internal/blast/send-list"
    timeout_seconds = settings.BFF_INTERNAL_TIMEOUT_MS / 1000

    try:
        response = requests.post(
            url,
            json={'session': session_name, 'chatId': destination, 'list': list_payload},
            headers={
                'X-Office-Dispatch-Key': settings.OFFICE_DISPATCH_SERVICE_KEY,
                'Idempotency-Key': idempotency_key,
            },
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        logger.warning('BFF list-dispatch request failed: %s', type(exc).__name__)
        raise BffDispatchError(f'BFF request failed: {type(exc).__name__}') from exc

    if response.status_code != 200:
        logger.warning('BFF list-dispatch returned HTTP %s', response.status_code)
        raise BffDispatchError(f'BFF returned HTTP {response.status_code}')

    try:
        data = response.json()
    except ValueError as exc:
        raise BffDispatchError('BFF response was not valid JSON') from exc

    if not isinstance(data, dict) or data.get('status') not in ('sent', 'failed', 'unknown'):
        raise BffDispatchError('Unrecognized BFF list-dispatch response shape')

    return {
        'status': data['status'],
        'provider_message_id': data.get('providerMessageId') if isinstance(data.get('providerMessageId'), str) else None,
    }


def check_number_exists(session_name: str, destination: str) -> bool | None:
    """GET the BFF's internal number-validity check
    (`GET /internal/blast/check-number`, `bff/src/routes/internalBlast.ts`)
    — WAHA's `GET /api/contacts/check-exists`, live-verified directly
    against the real deployment (see that route's own comment for the
    evidence). Returns `True`/`False` for a definite answer, or `None`
    for a genuine request-level failure (raises `BffDispatchError` only
    for a network/HTTP/JSON-shape failure — an ambiguous `None` from a
    clean BFF response is a normal, valid return, not an exception,
    mirroring `send_blast_message`'s own status-vs-exception split).

    Never logs or includes `settings.OFFICE_DISPATCH_SERVICE_KEY` in any
    exception message."""
    if not settings.BFF_INTERNAL_BASE_URL:
        raise BffDispatchError('BFF_INTERNAL_BASE_URL is not configured')
    if not settings.OFFICE_DISPATCH_SERVICE_KEY:
        raise BffDispatchError('OFFICE_DISPATCH_SERVICE_KEY is not configured')

    url = f"{settings.BFF_INTERNAL_BASE_URL.rstrip('/')}/internal/blast/check-number"
    timeout_seconds = settings.BFF_INTERNAL_TIMEOUT_MS / 1000

    try:
        response = requests.get(
            url,
            params={'session': session_name, 'phone': destination},
            headers={'X-Office-Dispatch-Key': settings.OFFICE_DISPATCH_SERVICE_KEY},
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        logger.warning('BFF number-check request failed: %s', type(exc).__name__)
        raise BffDispatchError(f'BFF request failed: {type(exc).__name__}') from exc

    if response.status_code != 200:
        logger.warning('BFF number-check returned HTTP %s', response.status_code)
        raise BffDispatchError(f'BFF returned HTTP {response.status_code}')

    try:
        data = response.json()
    except ValueError as exc:
        raise BffDispatchError('BFF response was not valid JSON') from exc

    if not isinstance(data, dict) or 'numberExists' not in data:
        raise BffDispatchError('Unrecognized BFF number-check response shape')

    number_exists = data['numberExists']
    return number_exists if isinstance(number_exists, bool) else None


def _call_typing_endpoint(path: str, session_name: str, destination: str) -> None:
    """Shared body for `start_typing`/`stop_typing` below — a WAHA typing
    indicator is fire-and-forget (no `provider_message_id`, no
    sent/failed/unknown outcome to report back — WAHA's own `startTyping`/
    `stopTyping` endpoints return no meaningful body, confirmed by the
    project operator's own curl evidence). Raises `BffDispatchError` for a
    request-level failure only, exactly like `send_blast_message`/
    `send_list_message` above — the caller (`apps.chats.tasks`) treats a
    failed typing indicator as non-fatal and still sends the real message,
    since missing "typing…" is cosmetic, never worth losing the reply
    over.

    Never logs or includes `settings.OFFICE_DISPATCH_SERVICE_KEY` in any
    exception message."""
    if not settings.BFF_INTERNAL_BASE_URL:
        raise BffDispatchError('BFF_INTERNAL_BASE_URL is not configured')
    if not settings.OFFICE_DISPATCH_SERVICE_KEY:
        raise BffDispatchError('OFFICE_DISPATCH_SERVICE_KEY is not configured')

    url = f"{settings.BFF_INTERNAL_BASE_URL.rstrip('/')}{path}"
    timeout_seconds = settings.BFF_INTERNAL_TIMEOUT_MS / 1000

    try:
        response = requests.post(
            url,
            json={'session': session_name, 'chatId': destination},
            headers={'X-Office-Dispatch-Key': settings.OFFICE_DISPATCH_SERVICE_KEY},
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        logger.warning('BFF typing-dispatch request failed (%s): %s', path, type(exc).__name__)
        raise BffDispatchError(f'BFF request failed: {type(exc).__name__}') from exc

    if response.status_code != 200:
        logger.warning('BFF typing-dispatch returned HTTP %s (%s)', response.status_code, path)
        raise BffDispatchError(f'BFF returned HTTP {response.status_code}')


def start_typing(session_name: str, destination: str) -> None:
    """POST to the BFF's internal typing-start endpoint
    (`POST /internal/typing/start`, `bff/src/routes/internalTyping.ts`) —
    the human-like reply-delay feature
    (`apps.chats.conversation_engine`/`apps.chats.tasks`,
    `BotConfig.reply_delay_seconds`). Underlying WAHA operation:
    `POST /api/startTyping` (CLAUDE.md rule 5 — a new, explicitly
    allowlisted endpoint), request shape given directly by the project
    operator: `{chatId, session}`."""
    _call_typing_endpoint('/internal/typing/start', session_name, destination)


def stop_typing(session_name: str, destination: str) -> None:
    """Counterpart to `start_typing` — `POST /internal/typing/stop` ->
    WAHA's `POST /api/stopTyping`, same `{chatId, session}` request
    shape."""
    _call_typing_endpoint('/internal/typing/stop', session_name, destination)
