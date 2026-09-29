"""Conversation/Bot Engine — configuration data model.

Deliberately separate from `apps.chats` (which owns `Chat`/`Message`, and
now `ConversationSession` — a per-Chat runtime record, colocated with
`Chat` since it's Chat-scoped) — this app owns the *configuration* a
Superadmin/Office Admin edits (menus, triggers, per-Office bot settings),
matching the existing `apps.offices`/`apps.blast` split between
"organizational config" and "runtime data."

Design basis: approved Conversation Engine design (this conversation) —
menu/trigger content must be data, never hardcoded Python branching
(explicit requirement). `BotMenu.office` is nullable — `None` means a
GLOBAL menu/trigger, reachable before any Office has been selected for a
given conversation (the Main Menu shown on "Halo" is global by
construction; only once a citizen picks a destination Office via the
dedicated Office-selector menu does anything become Office-specific).
This mirrors `docs/03-UI-UX-SPEC.md`'s and the approved design's own
framing: the bot is one shared entry point, not N independent per-Office
bots, with Office-specific customization as an available *extension*,
not the default.
"""

from django.db import models

from apps.core.models import TimeStampedModel
from apps.offices.models import Office


class BotConfig(TimeStampedModel):
    """One row per Office, plus exactly one GLOBAL row (`office=None`) —
    same lazy-singleton pattern as `apps.offices.models.OfficeInboxConfig`
    (created on first admin GET/PATCH, `apps.bot.views` — never eagerly
    backfilled). The GLOBAL row is what a brand-new conversation (no
    Office selected yet) uses for `enabled`/`fallback_message`/
    `session_completed_message`/`root_menu` — see `root_menu`'s own
    comment for why it's nullable.

    `office` is nullable+unique (not a strict `OneToOneField` requiring a
    row per Office) so the GLOBAL row can exist without violating a
    NOT-NULL Office FK — Postgres allows multiple `NULL`s under a unique
    index by design, so this does NOT accidentally allow two GLOBAL rows;
    application code (`apps.bot.views`) is still responsible for treating
    "the GLOBAL row" as a singleton via `get_or_create(office=None)`,
    exactly like `OfficeInboxConfig` already does per-Office."""

    office = models.OneToOneField(
        Office, on_delete=models.PROTECT, null=True, blank=True, related_name='bot_config'
    )
    enabled = models.BooleanField(default=False)
    fallback_message = models.TextField(blank=True, default='')
    session_completed_message = models.TextField(blank=True, default='')
    # Nullable: a freshly created BotConfig (lazy `get_or_create`, like
    # OfficeInboxConfig) has no root menu yet — the engine treats "no
    # root_menu configured" the same as "bot not usable yet" (silently
    # does nothing), never a crash, matching this project's existing
    # "safe defaults until an admin saves something real" convention.
    root_menu = models.ForeignKey(
        'BotMenu', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    # Discussed requirement — Conversation/Bot Engine interactive list
    # menus (`apps.chats.conversation_engine`'s list-rendering, WAHA's
    # `sendList` — live-verified request shape:
    # `message.footer`/`message.button`). GLOBAL-only, same as everything
    # else this project's own per-office BotConfig capability was locked
    # down to (apps.bot.views._may_access) — one shared bot, one shared
    # list "chrome", not per-Office. Blank/default text is safe: WAHA
    # accepts an empty footer, and `list_button_text` defaults to a
    # sensible label rather than an empty button.
    list_footer_text = models.TextField(blank=True, default='')
    list_button_text = models.CharField(max_length=32, blank=True, default='Pilih')

    def __str__(self):
        return f'BotConfig({self.office or "GLOBAL"})'


class BotMenu(TimeStampedModel):
    """One node in a menu tree. `office=None` = GLOBAL (reachable before
    any Office is selected for this conversation — e.g. the Main Menu).
    `parent_menu` makes this a tree, self-referential, matching the
    approved design's "Main Menu -> submenu" shape.

    `is_office_selector=True` marks this menu as THE destination-Office
    picker — deliberately NOT populated via `BotMenuItem` rows (the
    Office list changes over time; storing it would mean re-syncing on
    every Office create/deactivate/Inbox-config change, an unnecessary
    second source of truth). Instead
    `apps.bot.conversation_engine` builds this menu's options and
    validates a reply against `apps.chats.operator_chat`'s existing,
    already-tested `available_operator_chat_offices()`/
    `select_office_for_chat()` directly — reused verbatim, per the
    approved design's explicit "jangan duplikasi logic filtering
    Office." A menu with `is_office_selector=True` is expected to have
    zero `BotMenuItem` rows; the engine never looks for any."""

    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, null=True, blank=True, related_name='bot_menus'
    )
    name = models.CharField(max_length=150)
    parent_menu = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True, related_name='child_menus'
    )
    # Shown above the item list every time this menu is displayed —
    # deliberately NOT a one-time "welcome" (approved design explicitly
    # separates greeting/intro text from any "sekali seumur hidup Chat"
    # mechanism; see ConversationSession — no per-Chat "already greeted"
    # flag exists anywhere in this design).
    intro_text = models.TextField(blank=True, default='')
    is_office_selector = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)

    class Meta:
        # NOTE (known Postgres limitation, not a bug): a plain multi-
        # column UNIQUE constraint treats NULL as distinct from every
        # other NULL, so this does NOT actually prevent two GLOBAL
        # (office=NULL) menus sharing the same `name` — only two
        # same-named menus under the SAME real Office are guaranteed
        # unique by the database. Acceptable for this foundation (a
        # duplicate global menu name is a data-quality annoyance, not a
        # correctness/security issue — nothing resolves menus by name,
        # only by FK); a partial/expression index would be needed to
        # close this fully, not added here to avoid unrequested scope
        # growth.
        constraints = [
            models.UniqueConstraint(fields=['office', 'name'], name='unique_botmenu_name_per_office'),
        ]

    def __str__(self):
        return f'{self.name} ({self.office or "GLOBAL"})'


class BotMenuItem(TimeStampedModel):
    """One selectable option within a `BotMenu`. `trigger_value` is
    matched against the incoming message body (case-insensitive,
    stripped — same normalization `apps.bot.conversation_engine` applies
    to global triggers), scoped to this item's own `menu` — the same
    "'1' means something different in every menu" property the approved
    design requires, satisfied for free by `trigger_value` living on a
    per-menu row rather than a global lookup table.

    `action_type` drives what happens when selected — kept as a small,
    fixed vocabulary (not free text), matching this project's existing
    "never invent an unenforced capability" discipline (`Role.scopes`
    validated against a fixed list is the precedent). Only the 4 values
    below are foundation for this pass; `API_CALL`-shaped actions
    (esamsat, etc.) are explicitly not built — see `action_config`'s own
    comment."""

    ACTION_SEND_TEXT = 'send_text'
    ACTION_SHOW_MENU = 'show_menu'
    ACTION_COMPLETE_SESSION = 'complete_session'
    ACTION_HANDOFF_TO_OPERATOR = 'handoff_to_operator'
    ACTION_CHOICES = [
        (ACTION_SEND_TEXT, 'Send text (leaf — completes the session after sending)'),
        (ACTION_SHOW_MENU, 'Show another menu'),
        (ACTION_COMPLETE_SESSION, 'Complete the session'),
        (ACTION_HANDOFF_TO_OPERATOR, 'Hand off to a human operator (extension point only)'),
    ]

    menu = models.ForeignKey(BotMenu, on_delete=models.CASCADE, related_name='items')
    label = models.CharField(max_length=200)
    trigger_value = models.CharField(max_length=32)
    order = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)
    action_type = models.CharField(max_length=32, choices=ACTION_CHOICES)
    # Used only by ACTION_SEND_TEXT (the text to send) — for
    # ACTION_SHOW_MENU, `target_menu` below is used instead;
    # ACTION_COMPLETE_SESSION/ACTION_HANDOFF_TO_OPERATOR use the
    # relevant `BotConfig` message field, not this one. Deliberately a
    # single plain-text field, not a JSON `action_config` blob — no
    # action type in this foundation needs more than one text value, and
    # a JSON blob for unused structure would be exactly the kind of
    # "build it because it might be useful later" this project's own
    # coding guidance says not to do.
    text = models.TextField(blank=True, default='')
    target_menu = models.ForeignKey(
        BotMenu, on_delete=models.PROTECT, null=True, blank=True, related_name='+'
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['menu', 'trigger_value'], name='unique_trigger_value_per_menu'),
        ]
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.trigger_value} -> {self.label} ({self.menu_id})'


class BotTrigger(TimeStampedModel):
    """A keyword that ALWAYS reopens/resets to a menu, regardless of the
    Chat's current `ConversationSession` state — "Halo"/"Menu"/"Mulai"/
    "Bantuan" per the approved design, but the exact keyword list is
    configuration, never hardcoded (explicit requirement). `office=None`
    = applies globally; an Office-specific row with the same keyword
    would let one Office override the global behavior — not required for
    this foundation, but the field shape already allows it without
    redesign, same "accommodate without building" precedent as
    `OfficeInboxConfig`'s own fields before Step 13 consumed them."""

    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, null=True, blank=True, related_name='bot_triggers'
    )
    keyword = models.CharField(max_length=32)
    target_menu = models.ForeignKey(
        BotMenu, on_delete=models.PROTECT, null=True, blank=True, related_name='+'
    )
    enabled = models.BooleanField(default=True)

    class Meta:
        # Same NULL-uniqueness caveat as BotMenu.Meta above — two GLOBAL
        # triggers with the same keyword aren't DB-rejected; the engine
        # resolves ties deterministically (first match by `id`), so this
        # is a data-quality concern, not a correctness one.
        constraints = [
            models.UniqueConstraint(fields=['office', 'keyword'], name='unique_trigger_keyword_per_office'),
        ]

    def __str__(self):
        return f'{self.keyword} ({self.office or "GLOBAL"})'
