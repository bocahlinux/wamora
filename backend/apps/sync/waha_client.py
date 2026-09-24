"""Minimal WAHA REST client for reconciliation (Phase 4).

Uses only the endpoint pattern confirmed against the real deployment
(docs/12-WAHA-REFERENCE.md, docs/generated/PHASE-3-LIVE-VERIFICATION.md,
docs/generated/PHASE-4-RECONCILIATION.md):

    GET /api/{session}/chats/{chatId}/messages?limit=N&offset=M

PAGINATION — CONFIRMED against the real deployed WAHA instance (this
project's operator ran the live comparison directly):
- `limit` + `offset` work correctly: `?limit=2` returned the 2 newest
  messages; `?limit=2&offset=2` returned the next 2 older ones, with no
  overlap or gap between the two calls.
- Ordering is newest-first (descending by recency).
- `page` does NOT work as a pagination mechanism: `?limit=2&page=2`
  returned the identical result as `?limit=2` — `page` is silently
  ignored by this WAHA version. Never send `page`.
This client fetches exactly one page per call, given an explicit
`offset` — the multi-page loop and its stopping conditions live in
apps/sync/reconciliation.py, not here, since bounding the loop safely
depends on reconciliation-level state (the sync checkpoint), which this
client deliberately has no knowledge of.

RESPONSE SHAPE — also confirmed from the same real evidence: a bare JSON
array of message objects (no `{"messages": [...]}` wrapper). This client
still accepts a wrapped form defensively (harmless if never hit) and
raises a clear error for anything else, rather than silently guessing.
"""

import logging
import urllib.parse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10


class WahaClientError(Exception):
    """Raised for any WAHA request failure (network, non-200, or an
    unrecognized response shape). Never includes the API key — see
    docs/06-SECURITY.md log/response redaction requirement."""


class WahaClient:
    def __init__(self, base_url=None, api_key=None, timeout=DEFAULT_TIMEOUT_SECONDS):
        self.base_url = (base_url if base_url is not None else settings.WAHA_BASE_URL).rstrip('/')
        self.api_key = api_key if api_key is not None else settings.WAHA_API_KEY
        self.timeout = timeout

    def fetch_chat_messages(self, session: str, chat_id: str, limit: int = 100, offset: int = 0):
        """Returns a list of raw message dicts (the same shape as a
        webhook's `payload` object — see apps/webhooks/parsing.py) for one
        page, bounded by `limit`, starting at `offset`. Both are confirmed
        working against the real deployment (see module docstring). Never
        sends `page` — confirmed not to work as pagination. Raises
        WahaClientError on any failure."""
        if not self.base_url:
            raise WahaClientError('WAHA_BASE_URL is not configured')
        if not self.api_key:
            raise WahaClientError('WAHA_API_KEY is not configured')

        encoded_session = urllib.parse.quote(session, safe='')
        encoded_chat_id = urllib.parse.quote(chat_id, safe='')
        url = f'{self.base_url}/api/{encoded_session}/chats/{encoded_chat_id}/messages'

        try:
            response = requests.get(
                url,
                headers={'X-Api-Key': self.api_key},
                params={'limit': limit, 'offset': offset},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.warning('WAHA request failed for chat %s: %s', chat_id, type(exc).__name__)
            raise WahaClientError(f'WAHA request failed: {type(exc).__name__}') from exc

        if response.status_code != 200:
            logger.warning('WAHA returned HTTP %s for chat %s', response.status_code, chat_id)
            raise WahaClientError(f'WAHA returned HTTP {response.status_code}')

        try:
            data = response.json()
        except ValueError as exc:
            raise WahaClientError('WAHA response was not valid JSON') from exc

        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get('messages'), list):
            return data['messages']

        raise WahaClientError('Unrecognized WAHA response shape (expected a list or {"messages": [...]})')

    def fetch_chats(self, session: str):
        """Returns a list of raw chat dicts for the session — chat
        discovery (Inbox/Chat, canonical Phase 8;
        docs/generated/INBOX-CHAT-DECISION-REPORT.md Section 4).

        `GET /api/{session}/chats` is a documented "Observed endpoint"
        (docs/12-WAHA-REFERENCE.md) — confirmed reachable on this
        deployment, though its response shape was not independently
        re-verified field-by-field the way `fetch_chat_messages`'s was
        (that endpoint's pagination/shape/ordering were confirmed via a
        direct comparison run — see the reference doc). This method
        therefore applies the exact same defensive shape-handling as
        `fetch_chat_messages` (bare list, or {"chats"/"messages": [...]}
        wrapped) rather than assuming a specific shape, and raises a
        clear error for anything else instead of guessing."""
        if not self.base_url:
            raise WahaClientError('WAHA_BASE_URL is not configured')
        if not self.api_key:
            raise WahaClientError('WAHA_API_KEY is not configured')

        encoded_session = urllib.parse.quote(session, safe='')
        url = f'{self.base_url}/api/{encoded_session}/chats'

        try:
            response = requests.get(
                url,
                headers={'X-Api-Key': self.api_key},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.warning('WAHA chat-list request failed for session %s: %s', session, type(exc).__name__)
            raise WahaClientError(f'WAHA request failed: {type(exc).__name__}') from exc

        if response.status_code != 200:
            logger.warning('WAHA returned HTTP %s for chat list (session %s)', response.status_code, session)
            raise WahaClientError(f'WAHA returned HTTP {response.status_code}')

        try:
            data = response.json()
        except ValueError as exc:
            raise WahaClientError('WAHA response was not valid JSON') from exc

        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ('chats', 'messages'):
                if isinstance(data.get(key), list):
                    return data[key]

        raise WahaClientError('Unrecognized WAHA response shape for chat list (expected a bare list)')
