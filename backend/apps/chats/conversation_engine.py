"""Conversation/Bot Engine — supersedes `apps.chats.operator_chat`
(Step 12) and `apps.chats.inbox_lifecycle` (Step 13) as the single entry
point `apps.webhooks.services.ingest_webhook` calls for a LIVE inbound
message. Both superseded modules are left in place, unmodified, per
explicit instruction (no destructive change without separate approval) —
this module simply stops being routed to from the webhook path.

Design basis: the approved 17-point Conversation Engine design (this
project's own conversation history). Menu/trigger CONTENT is always data
(`apps.bot.models`), never hardcoded branching — this module only
contains the resolver algorithm, never a menu string or trigger keyword
itself.

Resolution order for one inbound message, each step documented at its
own call site below:
  1. Effective `BotConfig` for this Chat (Office-specific if one exists,
     else GLOBAL) — bot entirely disabled/unconfigured -> no-op, silent.
  2. Global trigger match -> ALWAYS resets the flow (approved correction
     #1), regardless of any existing active session.
  3. No active session -> fallback text + show the Main Menu (correction
     #6) — this is also what a brand-new WhatsApp number's very first,
     non-trigger message hits; no auto Office-selection ever happens here
     (correction #3).
  4. Active session, current menu is the Office-selector
     (`BotMenu.is_office_selector`) -> delegate entirely to
     `apps.chats.operator_chat`'s existing, already-tested
     `available_operator_chat_offices()`/`select_office_for_chat()` —
     reused verbatim, never re-implemented (correction #12).
  5. Active session, ordinary menu -> match the reply against that menu's
     `BotMenuItem` rows; a match runs its `action_type`; no match ->
     fallback text + re-show the SAME menu, session state untouched
     (correction #7).
"""

import logging

from django.db.models import Q
from django.utils import timezone

from apps.bot.models import BotConfig, BotMenuItem, BotTrigger
from apps.blast.bff_client import BffDispatchError, send_blast_message, send_list_message
from apps.chats.models import Chat, ConversationSession
from apps.chats.operator_chat import (
    INVALID_SELECTION_TEXT,
    NO_OFFICE_AVAILABLE_TEXT,
    available_operator_chat_offices,
    select_office_for_chat,
)
from apps.waha_sessions.models import WahaSession

logger = logging.getLogger(__name__)

OFFICE_SELECTED_TEXT_TEMPLATE = 'Baik, percakapan Anda telah diarahkan ke {office_name}.'
HANDOFF_ACK_TEXT = 'Permintaan Anda sedang diteruskan ke petugas.'
_MAX_SELECTION_DIGITS = 6  # same guard as apps.chats.operator_chat._MAX_SELECTION_DIGITS

# Discussed requirement — Conversation/Bot Engine interactive list menus
# (WAHA's `sendList`, live-verified by the project operator directly
# against this deployment — see apps.blast.bff_client.send_list_message's
# own docstring for the confirmed request shape).
_MAX_LIST_ROWS = 10  # WhatsApp's own hard cap on rows in one list message
_OFFICES_PER_PAGE = 7  # discussed pagination split (7 Office rows + up to 2 nav rows, always <= _MAX_LIST_ROWS)
_PAGE_ROW_PREFIX = '__page_'
_NEXT_PAGE_LABEL = '▶️ Samsat Lainnya'
_PREV_PAGE_LABEL = '◀️ Samsat Sebelumnya'
_DEFAULT_LIST_BUTTON_TEXT = 'Pilih'


def _normalize(text: str) -> str:
    return (text or '').strip()


def _send(session: WahaSession, chat_provider_id: str, idempotency_key: str, text: str, config=None) -> None:
    """Best-effort outbound, same reused Django -> BFF -> WAHA `sendText`
    path as every other bot-adjacent module in this app — never raises, a
    send failure is logged only, and never rolls back or blocks the
    already-committed inbound message this is a side effect of.

    Discussed requirement — human-like reply delay
    (`BotConfig.reply_delay_seconds`, `config` optional/`None`-safe since
    a couple of call sites build a payload before their own config lookup,
    same convention `_list_chrome` already established): a configured
    delay > 0 hands off to `apps.chats.tasks.send_bot_text_reply_task`
    (typing indicator + scheduled send, never a blocking sleep here)
    instead of calling `send_blast_message` inline. `delay_seconds <= 0`
    (the default) is byte-for-byte the original immediate-send behavior —
    no typing indicator, no Celery hop."""
    text = (text or '').strip()
    if not text:
        return
    delay_seconds = getattr(config, 'reply_delay_seconds', 0) or 0
    if delay_seconds > 0:
        # Local import: apps.chats.tasks imports FROM this module
        # (expire_waiting_operator_session) at module load time — a
        # top-level import here would be circular.
        from apps.chats.tasks import send_bot_text_reply_task

        send_bot_text_reply_task.delay(session.name, chat_provider_id, idempotency_key, text, delay_seconds)
        return
    try:
        send_blast_message(session.name, chat_provider_id, text, idempotency_key)
    except BffDispatchError as exc:
        logger.warning('conversation-engine send failed for %s/%s: %s', session.name, chat_provider_id, exc)


def _send_list(waha_session: WahaSession, chat_provider_id: str, idempotency_key: str, list_payload: dict, fallback_text: str, config=None) -> None:
    """Best-effort outbound via WAHA's interactive `sendList` operation
    (Discussed requirement — Conversation/Bot Engine list menus). Unlike
    `_send` (which simply logs and gives up on failure — acceptable for
    an ordinary text message), a MENU going missing entirely would leave
    a citizen stuck with no way to continue, so this falls back to a
    plain-text `_send` of `fallback_text` (the original numbered-text
    rendering) whenever the list itself fails to dispatch
    (`BffDispatchError`) or WAHA reports anything other than `"sent"`.

    Same human-like reply-delay hand-off as `_send` above (to
    `apps.chats.tasks.send_bot_list_reply_task`, which re-implements this
    same sendList-fails-so-fall-back-to-text behavior for the delayed
    path, since it runs in a separate task)."""
    delay_seconds = getattr(config, 'reply_delay_seconds', 0) or 0
    if delay_seconds > 0:
        from apps.chats.tasks import send_bot_list_reply_task

        send_bot_list_reply_task.delay(
            waha_session.name, chat_provider_id, idempotency_key, list_payload, fallback_text, delay_seconds,
        )
        return
    try:
        result = send_list_message(waha_session.name, chat_provider_id, list_payload, idempotency_key)
    except BffDispatchError as exc:
        logger.warning('conversation-engine sendList failed for %s/%s: %s', waha_session.name, chat_provider_id, exc)
        _send(waha_session, chat_provider_id, f'{idempotency_key}-list-fallback', fallback_text)
        return
    if result.get('status') != 'sent':
        logger.warning(
            'conversation-engine sendList returned status=%s for %s/%s',
            result.get('status'), waha_session.name, chat_provider_id,
        )
        _send(waha_session, chat_provider_id, f'{idempotency_key}-list-fallback', fallback_text)


def _list_chrome(config) -> tuple[str, str]:
    """(footer, button) — the two admin-configurable, GLOBAL-only pieces
    of every list message this engine sends (`BotConfig.list_footer_text`/
    `.list_button_text`, Settings > Bot Configuration > Config). `config`
    may be `None` at a couple of call sites that build a list payload
    before their own config lookup — same "safe default until an admin
    saves something real" convention `_effective_config` itself
    documents."""
    if config is None:
        return '', _DEFAULT_LIST_BUTTON_TEXT
    return config.list_footer_text, (config.list_button_text or _DEFAULT_LIST_BUTTON_TEXT)


def _send_menu(waha_session: WahaSession, chat_provider_id: str, idempotency_key: str, menu, config, prefix_text: str = '') -> None:
    """Sends `menu` as an interactive list (discussed requirement) when
    it has 1-10 enabled items; falls back to the original numbered-text
    rendering otherwise (zero items, or more than WhatsApp's own 10-row
    cap — `apps.bot.views`' own admin UI has no cap on item count, so
    this stays a safe universal escape hatch, not just a
    office-selector-specific concern) — via `_send_list`'s own
    `sendList`-failure fallback too. `prefix_text` (e.g. the
    `fallback_message` shown alongside a re-shown menu, correction #6/#7)
    is prepended to the list's own description, or to the plain-text
    fallback — never silently dropped."""
    items = list(menu.items.filter(enabled=True).order_by('order', 'id'))
    fallback_text = '\n\n'.join(part for part in [prefix_text, _render_menu_text(menu)] if part)
    if not (1 <= len(items) <= _MAX_LIST_ROWS):
        _send(waha_session, chat_provider_id, idempotency_key, fallback_text, config=config)
        return
    footer, button = _list_chrome(config)
    description = '\n\n'.join(part for part in [prefix_text, menu.intro_text.strip()] if part) or menu.name
    list_payload = {
        'title': menu.name,
        'description': description,
        'footer': footer,
        'button': button,
        'sections': [{
            'title': menu.name,
            'rows': [{'title': item.label, 'rowId': item.trigger_value, 'description': None} for item in items],
        }],
    }
    _send_list(waha_session, chat_provider_id, idempotency_key, list_payload, fallback_text, config=config)


def _office_selector_rows(offices, page: int) -> list:
    """One page's rows for the Office-selector list — up to
    `_OFFICES_PER_PAGE` real Offices (`rowId` = the Office's own stable
    pk, never a position) plus a "Samsat Sebelumnya" row (if `page > 1`)
    and/or a "Samsat Lainnya" row (if more Offices remain after this
    page) — at most `_OFFICES_PER_PAGE + 2` rows, always <=
    `_MAX_LIST_ROWS`. Both nav rows' `rowId` encodes the TARGET page
    directly (`_PAGE_ROW_PREFIX` + page number) — stateless (no "current
    page" is ever persisted anywhere); `_handle_office_selector_reply`
    decodes it back."""
    start = (page - 1) * _OFFICES_PER_PAGE
    end = start + _OFFICES_PER_PAGE
    page_offices = offices[start:end]
    rows = [{'title': office.name, 'rowId': str(office.pk), 'description': None} for office in page_offices]
    if page > 1:
        rows.append({'title': _PREV_PAGE_LABEL, 'rowId': f'{_PAGE_ROW_PREFIX}{page - 1}', 'description': None})
    if end < len(offices):
        rows.append({'title': _NEXT_PAGE_LABEL, 'rowId': f'{_PAGE_ROW_PREFIX}{page + 1}', 'description': None})
    return rows


def _send_office_selector(waha_session: WahaSession, chat: Chat, idempotency_key: str, config, offices, page: int = 1) -> None:
    """Sends (or re-sends, for pagination) the Office-selector as an
    interactive list — discussed requirement. Falls back to the original
    numbered-text rendering (`_render_office_selector_text`, unpaginated
    — WhatsApp's row cap only applies to the richer list format) if
    `sendList` itself fails to dispatch."""
    total_pages = max(1, -(-len(offices) // _OFFICES_PER_PAGE))  # ceil division, never 0 pages
    page = max(1, min(page, total_pages))
    footer, button = _list_chrome(config)
    fallback_text = _render_office_selector_text(offices)
    list_payload = {
        'title': 'Pilih Samsat',
        'description': 'Silakan pilih Samsat tujuan:',
        'footer': footer,
        'button': button,
        'sections': [{'title': 'Samsat', 'rows': _office_selector_rows(offices, page)}],
    }
    _send_list(waha_session, chat.provider_chat_id, idempotency_key, list_payload, fallback_text, config=config)


def _effective_config(office):
    """Office-specific `BotConfig` if one has ever been saved for this
    Office, else the GLOBAL row — never lazily created here (a WP's
    inbound message must never have the side effect of creating admin
    config rows; only `apps.bot.views` does that, on an admin's own
    GET/PATCH, same discipline as `apps.chats.operator_chat`'s own
    `available_operator_chat_offices()` docstring establishes for
    `OfficeInboxConfig`). `None` if nothing has been configured at all —
    callers treat that identically to `enabled=False`."""
    if office is not None:
        office_config = BotConfig.objects.filter(office=office).select_related('root_menu').first()
        if office_config is not None:
            return office_config
    return BotConfig.objects.filter(office=None).select_related('root_menu').first()


def _match_trigger(chat: Chat, body: str):
    """An enabled `BotTrigger` whose keyword matches `body`
    (case-insensitive) — an Office-specific trigger (for `chat.office`, if
    set) takes precedence over a same-keyword GLOBAL one, mirroring how a
    per-Office `BotConfig` already takes precedence over the GLOBAL one
    above. Returns `None` if nothing matches (including a blank body)."""
    keyword = _normalize(body)
    if not keyword:
        return None
    matches = BotTrigger.objects.filter(enabled=True, keyword__iexact=keyword).select_related('target_menu')
    if chat.office_id is not None:
        office_trigger = matches.filter(office_id=chat.office_id).first()
        if office_trigger is not None:
            return office_trigger
    return matches.filter(office__isnull=True).first()


def _match_menu_item(menu, body: str, list_reply_id: str):
    """Discussed requirement — Conversation/Bot Engine interactive list
    menus. Prefers the tapped list row's stable `rowId`
    (`Message.list_reply_id`, set only for a genuine interactive-list
    tap — confirmed via a real captured webhook delivery, see that
    field's own model comment) — unambiguous even if two items happen to
    share label text, and immune to `body` carrying the row's TITLE text
    rather than `trigger_value` once list rendering is in play. Falls
    back to matching `body` against EITHER `trigger_value` (a
    manually-typed reply — unaffected by switching rendering to a list,
    e.g. an old WhatsApp client that can't render one) OR `label`
    (defensive, in case `list_reply_id` is ever absent for a real tap on
    some other WhatsApp client) when no rowId is present. Returns `None`
    if nothing matches."""
    qs = BotMenuItem.objects.filter(menu=menu, enabled=True)
    if list_reply_id:
        item = qs.filter(trigger_value=list_reply_id).first()
        if item is not None:
            return item
    return qs.filter(Q(trigger_value__iexact=body) | Q(label__iexact=body)).first()


def _render_menu_text(menu) -> str:
    """Static rendering for an ordinary menu — the Office-selector menu
    (`is_office_selector=True`) is rendered separately, by
    `apps.chats.operator_chat`'s own menu-building convention, never via
    stored `BotMenuItem` rows (see that field's own model docstring)."""
    lines = []
    if menu.intro_text.strip():
        lines.append(menu.intro_text.strip())
        lines.append('')
    for item in menu.items.filter(enabled=True).order_by('order', 'id'):
        lines.append(f'{item.trigger_value}. {item.label}')
    return '\n'.join(lines).strip()


def _render_office_selector_text(offices) -> str:
    """Numbers by DISPLAY POSITION (1, 2, 3, ... in the order `offices`
    is already given — `available_operator_chat_offices()` orders by
    name), never by `office.pk` — found live: offices are created in an
    arbitrary order, so their raw pk (e.g. Kasongan=2, Palangka Raya=1,
    Sampit=3) does not match alphabetical display order at all, showing
    a citizen a confusingly out-of-sequence "2. Samsat Kasongan / 1.
    Samsat Palangka Raya / 3. Samsat Sampit" list. `_handle_office_selector_reply`
    decodes the WP's numeric reply against this SAME position, never a
    raw pk lookup."""
    lines = ['Silakan pilih Samsat tujuan:', '']
    lines.extend(f'{position}. {office.name}' for position, office in enumerate(offices, start=1))
    lines.append('')
    lines.append('Balas dengan nomor pilihan Anda.')
    return '\n'.join(lines)


def _idempotency_key(message, suffix: str) -> str:
    return f'bot-{message.pk}-{suffix}'


def _start_new_session(chat: Chat, config) -> ConversationSession:
    """Creates a fresh `ConversationSession` positioned at `config.root_menu`
    — history is never deleted (correction #9), so any prior session for
    this Chat is simply left as-is; the partial-unique constraint on
    `ConversationSession.Meta` only allows this INSERT to succeed once any
    earlier active-state session for the same Chat has already been moved
    out of an active state (see `_reset_session_for_trigger` for the
    global-trigger case)."""
    return ConversationSession.objects.create(
        chat=chat,
        state=ConversationSession.STATE_ACTIVE,
        current_menu=config.root_menu,
    )


def _abandon_active_session(chat: Chat) -> None:
    """A global trigger always resets the flow (correction #1), even
    mid-submenu. The prior active-state session (if any) is moved to
    COMPLETED — not deleted (history is preserved, correction #9) — purely
    so the DB-level partial-unique constraint allows a new active session
    to be created; no "session completed" message is sent for this case,
    since the user themselves just explicitly asked to restart."""
    session = ConversationSession.objects.filter(chat=chat, state__in=ConversationSession.ACTIVE_STATES).first()
    if session is not None:
        session.state = ConversationSession.STATE_COMPLETED
        session.completed_at = timezone.now()
        session.current_menu = None
        session.save(update_fields=['state', 'completed_at', 'current_menu', 'updated_at'])


def _complete_session(session: ConversationSession, config) -> None:
    session.state = ConversationSession.STATE_COMPLETED
    session.completed_at = timezone.now()
    session.current_menu = None
    session.save(update_fields=['state', 'completed_at', 'current_menu', 'updated_at'])


def _handle_office_selector_reply(waha_session: WahaSession, message, chat: Chat, session: ConversationSession, body: str, config) -> None:
    idempotency_key = _idempotency_key(message, 'office-select')
    offices = list(available_operator_chat_offices())

    if not offices:
        _send(waha_session, chat.provider_chat_id, idempotency_key, NO_OFFICE_AVAILABLE_TEXT, config=config)
        return

    list_reply_id = message.list_reply_id

    # Page navigation ("Samsat Lainnya"/"Samsat Sebelumnya") — only ever
    # reachable via a genuine list tap (their rowId is never a real
    # Office pk or a digit a WP could type), stateless: the target page
    # is encoded directly in the tapped row's own rowId
    # (`_office_selector_rows`'s own comment) — the session/current_menu
    # is left completely untouched, this is purely "show a different
    # page of the SAME menu".
    if list_reply_id and list_reply_id.startswith(_PAGE_ROW_PREFIX):
        try:
            target_page = int(list_reply_id[len(_PAGE_ROW_PREFIX):])
        except ValueError:
            target_page = 1
        _send_office_selector(waha_session, chat, idempotency_key, config, offices, page=target_page)
        return

    selected_office = None
    if list_reply_id:
        # A genuine Office row tap — rowId is that Office's own stable
        # pk (`_office_selector_rows`), never a display position, so no
        # "which page were they shown" ambiguity here at all.
        selected_office = next((office for office in offices if str(office.pk) == list_reply_id), None)

    if selected_office is None:
        # Manually-typed fallback (or a stale/invalid rowId) — the same
        # numeric-POSITION parsing this project used before switching to
        # lists (an old WhatsApp client that can't render one, or a
        # citizen who types out of habit). Position is always relative
        # to the FULL list's ordering (page 1 onward), matching
        # `_render_office_selector_text`'s own unpaginated numbering —
        # a typed reply was never shown page-specific numbers to begin
        # with.
        if not (body.isdigit() and len(body) <= _MAX_SELECTION_DIGITS):
            # Unrecognized reply while an active session is on this menu
            # -> fallback + re-show the SAME menu (correction #7), never
            # silent, never corrupting session state. Always re-shown
            # from page 1 — there is no "current page" to return to.
            _send_office_selector(waha_session, chat, idempotency_key, config, offices, page=1)
            return

        position = int(body)
        if not (1 <= position <= len(offices)):
            # Same fallback text a stale/unknown office id already produced
            # (INVALID_SELECTION_TEXT) — a reply outside the shown range is
            # exactly as invalid as one that no longer resolves to a real,
            # available Office.
            _send(waha_session, chat.provider_chat_id, idempotency_key, INVALID_SELECTION_TEXT, config=config)
            return
        selected_office = offices[position - 1]

    # Race note: `offices` here is re-fetched fresh (not the exact list
    # rendered earlier), same as before this fix — if the available-Office
    # set changed in between (one got disabled/enabled), the selection can
    # resolve to a different Office than what the citizen actually saw.
    # Accepted, documented trade-off (matches this project's existing
    # tolerance for this class of race, e.g. select_office_for_chat's own
    # docstring).
    selected_chat, error = select_office_for_chat(waha_session, chat.provider_chat_id, selected_office.pk)
    if error is not None:
        _send(waha_session, chat.provider_chat_id, idempotency_key, INVALID_SELECTION_TEXT, config=config)
        return

    # Office selection is recorded on ConversationSession.office (approved
    # correction #5) — select_office_for_chat() already synced
    # Chat.office for the existing RBAC/Inbox mechanism; this is the
    # reverse direction, session -> office, kept as a separate write since
    # ConversationSession is never that function's concern.
    session.office = selected_chat.office
    # Selecting a destination Office is this foundation's only handoff
    # trigger (correction #13 — no queue/assignment logic here, this is
    # purely the extension point). current_menu cleared: WAITING_OPERATOR
    # has no "current menu" position, same as COMPLETED.
    session.state = ConversationSession.STATE_WAITING_OPERATOR
    session.current_menu = None
    session.save(update_fields=['office', 'state', 'current_menu', 'updated_at'])

    _send(
        waha_session, chat.provider_chat_id, idempotency_key,
        OFFICE_SELECTED_TEXT_TEMPLATE.format(office_name=selected_chat.office.name),
        config=config,
    )


def _handle_menu_item(waha_session: WahaSession, message, chat: Chat, session: ConversationSession, config, item: BotMenuItem) -> None:
    idempotency_key = _idempotency_key(message, f'item-{item.pk}')

    if item.action_type == BotMenuItem.ACTION_SHOW_MENU:
        session.current_menu = item.target_menu
        session.save(update_fields=['current_menu', 'updated_at'])
        # An Office-selector target renders its dynamic, paginated Office
        # list (correction #12 — reusing available_operator_chat_offices()
        # verbatim), never the static BotMenuItem rendering, which would
        # always be empty for such a menu (see BotMenu.is_office_selector's
        # own docstring: zero stored items are expected).
        if item.target_menu.is_office_selector:
            _send_office_selector(waha_session, chat, idempotency_key, config, list(available_operator_chat_offices()))
        else:
            _send_menu(waha_session, chat.provider_chat_id, idempotency_key, item.target_menu, config)
        return

    if item.action_type == BotMenuItem.ACTION_SEND_TEXT:
        _send(waha_session, chat.provider_chat_id, idempotency_key, item.text, config=config)
        _complete_session(session, config)
        _send(
            waha_session, chat.provider_chat_id, _idempotency_key(message, f'item-{item.pk}-completed'),
            config.session_completed_message if config else '', config=config,
        )
        return

    if item.action_type == BotMenuItem.ACTION_COMPLETE_SESSION:
        _complete_session(session, config)
        _send(
            waha_session, chat.provider_chat_id, idempotency_key,
            config.session_completed_message if config else '', config=config,
        )
        return

    if item.action_type == BotMenuItem.ACTION_HANDOFF_TO_OPERATOR:
        # Extension point only (correction #13) — no assignment/queue
        # logic exists here or anywhere else in this codebase yet. This
        # only records the state transition and acknowledges the request;
        # the actual Operator Workflow phase (canonical Phase 15, distinct
        # from this Conversation Engine work) is what will later act on
        # WAITING_OPERATOR sessions.
        session.state = ConversationSession.STATE_WAITING_OPERATOR
        session.save(update_fields=['state', 'updated_at'])
        _send(waha_session, chat.provider_chat_id, idempotency_key, HANDOFF_ACK_TEXT, config=config)
        return

    logger.warning('BotMenuItem %s has an unrecognized action_type %r', item.pk, item.action_type)


def close_waiting_session(chat: Chat) -> ConversationSession | None:
    """Operator-initiated close — `apps.chats.views.ChatCloseSessionView`'s
    only caller. Ends this Chat's WAITING_OPERATOR `ConversationSession`
    (if one exists) the same way `_complete_session` ends any other
    session, then sends the SAME `session_completed_message` an ordinary
    `ACTION_COMPLETE_SESSION` menu item would — from the citizen's side,
    "operator finished" and "flow completed" read identically. Returns
    `None` (never raises) if this Chat has no WAITING_OPERATOR session to
    close — the view turns that into a 400, never a silent no-op."""
    session = ConversationSession.objects.filter(
        chat=chat, state=ConversationSession.STATE_WAITING_OPERATOR,
    ).select_related('chat__session').first()
    if session is None:
        return None
    config = _effective_config(chat.office)
    _complete_session(session, config)
    _send(
        chat.session, chat.provider_chat_id, _idempotency_key_for_session(session, 'close'),
        config.session_completed_message if config else '', config=config,
    )
    return session


def expire_waiting_operator_session(session: ConversationSession) -> None:
    """Auto-expiry counterpart to `close_waiting_session` —
    `apps.chats.tasks.expire_waiting_operator_sessions_task`'s only
    caller, for a WAITING_OPERATOR session nobody manually closed within
    `settings.CONVERSATION_WAITING_OPERATOR_TIMEOUT_SECONDS`. Same
    STATE_COMPLETED transition and citizen-facing text as a manual close
    — the two are indistinguishable from the citizen's side."""
    chat = session.chat
    config = _effective_config(chat.office)
    _complete_session(session, config)
    _send(
        chat.session, chat.provider_chat_id, _idempotency_key_for_session(session, 'expire'),
        config.session_completed_message if config else '', config=config,
    )


def _idempotency_key_for_session(session: ConversationSession, suffix: str) -> str:
    # Not `_idempotency_key(message, suffix)` — closing/expiring a session
    # is never triggered by an inbound `Message`, so that helper's
    # `message.pk`-keyed shape doesn't apply; keyed by the session's own
    # pk instead, still stable/unique per (session, action).
    return f'bot-session-{session.pk}-{suffix}'


def handle_conversation_message(waha_session: WahaSession, message) -> None:
    """Entry point — called once per successfully-persisted LIVE inbound
    webhook message (never for reconciliation/history backfill, exactly
    like the two modules this supersedes; see this module's own docstring
    and `apps.webhooks.services.ingest_webhook`, the only caller). No-ops
    for a group chat or a message with no usable text body."""
    chat = message.chat
    if chat.is_group:
        return
    body = _normalize(message.body)
    if not body:
        return

    config = _effective_config(chat.office)
    if config is None or not config.enabled or config.root_menu is None:
        return

    session = ConversationSession.objects.filter(
        chat=chat, state__in=ConversationSession.ACTIVE_STATES,
    ).select_related('current_menu').first()

    if session is not None and session.state == ConversationSession.STATE_WAITING_OPERATOR:
        # A live handoff to a human operator is immune to EVERY inbound
        # message, including a global trigger keyword like "halo" — this
        # check must run BEFORE trigger matching below, not after it (a
        # real bug found live: sending a trigger word while
        # WAITING_OPERATOR was resetting the flow and re-showing the
        # menu, silently pulling the citizen back out of an active
        # handoff). Only `close_waiting_session()` (an operator's own
        # manual close, apps.chats.views.ChatCloseSessionView) or
        # `expire_waiting_operator_session()` (the 24h auto-expiry,
        # apps.chats.tasks) may end this state — never a message from the
        # citizen themselves.
        return

    trigger = _match_trigger(chat, body)
    if trigger is not None and trigger.target_menu is not None:
        _abandon_active_session(chat)
        ConversationSession.objects.create(
            chat=chat, state=ConversationSession.STATE_ACTIVE, current_menu=trigger.target_menu,
        )
        _send_menu(waha_session, chat.provider_chat_id, _idempotency_key(message, 'trigger'), trigger.target_menu, config)
        return

    if session is None:
        # No active session and the message wasn't a recognized trigger ->
        # fallback + Main Menu, never silent (correction #6). This is also
        # what a brand-new WhatsApp number's very first message hits — no
        # auto Office-selection happens here (correction #3).
        _start_new_session(chat, config)
        _send_menu(
            waha_session, chat.provider_chat_id, _idempotency_key(message, 'new'), config.root_menu, config,
            prefix_text=config.fallback_message.strip(),
        )
        return

    current_menu = session.current_menu
    if current_menu is None:
        # Defensive only — an ACTIVE/NEW session should always carry a
        # current_menu; treat as unrecoverable and restart at the root,
        # same fallback+Main Menu behavior as "no active session".
        _complete_session(session, config)
        _start_new_session(chat, config)
        _send_menu(
            waha_session, chat.provider_chat_id, _idempotency_key(message, 'recovered'), config.root_menu, config,
            prefix_text=config.fallback_message.strip(),
        )
        return

    if current_menu.is_office_selector:
        _handle_office_selector_reply(waha_session, message, chat, session, body, config)
        return

    item = _match_menu_item(current_menu, body, message.list_reply_id)
    if item is None:
        # Unrecognized message WITH an active session -> fallback +
        # re-show the current menu, session state untouched (correction #7).
        _send_menu(
            waha_session, chat.provider_chat_id, _idempotency_key(message, 'fallback'), current_menu, config,
            prefix_text=config.fallback_message.strip(),
        )
        return

    _handle_menu_item(waha_session, message, chat, session, config, item)
