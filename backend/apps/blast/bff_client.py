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
