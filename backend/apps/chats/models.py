from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.offices.models import Office
from apps.waha_sessions.models import WahaSession


class Contact(TimeStampedModel):
    session = models.ForeignKey(WahaSession, on_delete=models.PROTECT, related_name='contacts')
    provider_contact_id = models.CharField(max_length=128)
    display_name = models.CharField(max_length=255, blank=True)
    phone_number = models.CharField(max_length=32, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['session', 'provider_contact_id'], name='unique_contact_per_session'),
        ]

    def __str__(self):
        return self.display_name or self.provider_contact_id


class Chat(TimeStampedModel):
    session = models.ForeignKey(WahaSession, on_delete=models.PROTECT, related_name='chats')
    # Step 5 (Inbox <-> Office integration) — nullable, PROTECT, same
    # nullability/on_delete decision as BlastCampaign.office (Step 4):
    # existing Chat rows have no Office to backfill to, and no automatic
    # backfill is performed (apps/chats/authorization.py's own docstring
    # explains the resulting visibility consequence).
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, null=True, blank=True, related_name='chats'
    )
    provider_chat_id = models.CharField(max_length=128)
    contact = models.ForeignKey(
        Contact, on_delete=models.SET_NULL, null=True, blank=True, related_name='chats'
    )
    is_group = models.BooleanField(default=False)
    name = models.CharField(max_length=255, blank=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    # Inbox/Chat (canonical Phase 8) — docs/generated/INBOX-CHAT-DECISION-REPORT.md
    # Section 2/10: chat-level (not per-message, not per-user), durable,
    # UI-attention-only read state. Deliberately NOT synced to/from WAHA —
    # this project has no verified evidence WAHA even has a read-receipt
    # event or mark-read endpoint (docs/12-WAHA-REFERENCE.md's own
    # "Observed webhook event: message" — nothing else has ever been
    # observed). A nullable timestamp (not a boolean) so "unread" is simply
    # `last_read_at is None or last_message_at > last_read_at` and a future
    # WAHA read/seen integration can populate this same field without an
    # API/UI contract change.
    last_read_at = models.DateTimeField(null=True, blank=True)
    # DEPRECATED / LEGACY as of the Conversation Engine (ConversationSession,
    # below) — no longer read or written by the live webhook path
    # (`apps.chats.conversation_engine` replaces `apps.chats.inbox_lifecycle`
    # as of that change; see that module's own module-level docstring).
    # Left in place deliberately, per explicit instruction: no destructive
    # migration without separate approval. Its original purpose (Step 13,
    # one-time welcome send, compare-and-set idempotency guard) is now
    # superseded by ConversationSession's own lifecycle — a session's
    # intro/greeting text is shown every time its menu is (re)opened, not
    # gated by a per-Chat "ever welcomed" flag; duplicate-webhook safety
    # now comes from `Message`'s own `(session, provider_message_id)`
    # uniqueness ensuring the engine is invoked at most once per real
    # message, not from a claim on this field. Do not read or write this
    # field in any new code.
    welcome_sent_at = models.DateTimeField(null=True, blank=True)
    # Step 14 (Operator assignment & availability foundation) — current
    # assignment only, not a history table (deliberately out of this
    # step's scope). `on_delete=SET_NULL` matches this same model's own
    # `contact` field precedent above (never cascade-delete a Chat just
    # because the assigned User row is removed) — an unassigned Chat is
    # simply not lost from the Inbox, same reasoning as an unlinked
    # Contact. No backfill: every existing Chat stays `assigned_to=NULL`.
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_chats'
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['session', 'provider_chat_id'], name='unique_chat_per_session'),
        ]
        indexes = [
            models.Index(fields=['session', 'last_message_at']),
        ]

    def __str__(self):
        return self.name or self.provider_chat_id


# Module-level, not class attributes, so both `ConversationSession.STATE_CHOICES`
# and the `Meta.constraints` Q object below can share exactly one spelling
# — a nested `Meta` class can't see its outer class's own attributes at
# class-body-evaluation time (same convention already established by
# `apps.offices.models`'s own `ROLE_GLOBAL_ADMIN`/etc. and
# `apps.blast.models.OPERATION_TYPE_BLAST_SEND`).
CONVERSATION_STATE_NEW = 'new'
CONVERSATION_STATE_ACTIVE = 'active'
CONVERSATION_STATE_WAITING_OPERATOR = 'waiting_operator'
CONVERSATION_STATE_COMPLETED = 'completed'

# Only NEW/ACTIVE/WAITING_OPERATOR ever count as "the active session" for
# a Chat — enforced at the DB level (partial unique index on
# ConversationSession.Meta.constraints below), not just in application
# code, so a race between two near-simultaneous webhook deliveries for
# the same Chat can never create two concurrently-active sessions.
CONVERSATION_ACTIVE_STATES = [
    CONVERSATION_STATE_NEW, CONVERSATION_STATE_ACTIVE, CONVERSATION_STATE_WAITING_OPERATOR,
]


class ConversationSession(TimeStampedModel):
    """Conversation/Bot Engine — one pass of a Chat through the bot's
    menu tree. Deliberately colocated with `Chat`/`Message` (not in
    `apps.bot`, which owns only the *configuration* the bot reads, not
    per-Chat runtime state) — same "runtime data lives with its owning
    entity" split `apps.blast.models.BlastRecipient` vs.
    `apps.blast.serializers`-level config already establishes.

    A Chat may have MANY `ConversationSession` rows over time (approved
    design, explicit requirement — history is never deleted, a new
    global-trigger match or a fresh contact after COMPLETED always
    creates a new row rather than reusing/resetting an old one).
    `on_delete=PROTECT` on `chat`, matching this project's convention for
    every other FK to a durable entity — deleting a Chat with session
    history must be an explicit, deliberate action.

    Deliberately does NOT reuse `Chat.welcome_sent_at` or
    `Chat.office` as its own state — `welcome_sent_at` is left in place,
    unused by this engine, documented as deprecated/legacy (see its own
    field comment); `office` here is a SEPARATE, per-session value that
    gets synced onto `Chat.office` only when set (see `office`'s own
    comment) — the two fields answer different questions that usually,
    but not always, agree."""

    # Convenience aliases so callers can still write
    # `ConversationSession.STATE_NEW` etc. — plain re-exports of the
    # module-level constants above, safe because these are only ever
    # read after class-body evaluation completes, never from `Meta`.
    STATE_NEW = CONVERSATION_STATE_NEW
    STATE_ACTIVE = CONVERSATION_STATE_ACTIVE
    STATE_WAITING_OPERATOR = CONVERSATION_STATE_WAITING_OPERATOR
    STATE_COMPLETED = CONVERSATION_STATE_COMPLETED
    STATE_CHOICES = [
        (CONVERSATION_STATE_NEW, 'New'),
        (CONVERSATION_STATE_ACTIVE, 'Active'),
        (CONVERSATION_STATE_WAITING_OPERATOR, 'Waiting for operator (extension point only — no assignment logic here)'),
        (CONVERSATION_STATE_COMPLETED, 'Completed'),
    ]
    ACTIVE_STATES = CONVERSATION_ACTIVE_STATES

    chat = models.ForeignKey('Chat', on_delete=models.PROTECT, related_name='conversation_sessions')
    state = models.CharField(max_length=32, choices=STATE_CHOICES, default=CONVERSATION_STATE_NEW)
    # The menu tree position — a generic `state` value (above) plus this
    # FK is what "current_menu determines position, not one state per
    # menu level" (approved design) means concretely: NEW/ACTIVE says
    # roughly what phase the session is in; this FK says exactly where
    # in the tree. Null only when a WAITING_OPERATOR/COMPLETED session no
    # longer has a meaningful "current" menu.
    current_menu = models.ForeignKey(
        'bot.BotMenu', on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    # The Office THIS session routed its citizen to (set only if/when the
    # Office-selector menu, apps.bot.models.BotMenu.is_office_selector,
    # is reached and completed) — deliberately separate from `Chat.office`
    # (which exists for Inbox-visibility/RBAC purposes, Step 5, and is
    # kept in sync by apps.chats.conversation_engine whenever this field
    # is set, never the reverse). A later session for the same Chat can
    # pick a DIFFERENT Office than an earlier one; `Chat.office` always
    # reflects the most recent selection.
    office = models.ForeignKey(Office, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['chat'],
                condition=models.Q(state__in=CONVERSATION_ACTIVE_STATES),
                name='unique_active_conversation_session_per_chat',
            ),
        ]
        indexes = [
            models.Index(fields=['chat', 'state']),
        ]

    def __str__(self):
        return f'{self.chat_id} [{self.state}]'


class Message(TimeStampedModel):
    """docs/04-DATA-MODEL.md "Message identity": use stable provider/WAHA
    identifiers scoped by session; never body/timestamp/sender alone. The
    (session, provider_message_id) unique constraint below is the concrete
    enforcement of that rule, and is also what makes webhook/reconciliation
    ingestion idempotent (docs/05-WEBHOOK-SYNC-DESIGN.md) — inserting the
    same provider message twice for the same session is rejected at the
    database level, not just in application logic.
    """

    DIRECTION_INBOUND = 'inbound'
    DIRECTION_OUTBOUND = 'outbound'
    DIRECTION_CHOICES = [
        (DIRECTION_INBOUND, 'Inbound'),
        (DIRECTION_OUTBOUND, 'Outbound'),
    ]

    session = models.ForeignKey(WahaSession, on_delete=models.PROTECT, related_name='messages')
    chat = models.ForeignKey(Chat, on_delete=models.PROTECT, related_name='messages')
    provider_message_id = models.CharField(max_length=128)
    direction = models.CharField(max_length=16, choices=DIRECTION_CHOICES)
    message_type = models.CharField(max_length=32, blank=True)
    body = models.TextField(blank=True)
    status = models.CharField(max_length=32, blank=True)
    timestamp = models.DateTimeField()
    # Discussed requirement — per-Office Inbox history partitioning: a
    # SNAPSHOT of `chat.office` at the moment this Message was persisted
    # (`apps.webhooks.services.persist_message`, the only writer),
    # deliberately never updated afterward even if `chat.office` later
    # changes (a citizen picking a DIFFERENT Office later must not
    # retroactively relabel earlier history — `Chat.office`'s own comment
    # already documents that it "always reflects the most recent
    # selection", which is exactly what this field intentionally does
    # NOT do). `null` for every message sent before a citizen has ever
    # selected an Office in the current handoff round (including the
    # bot's own pre-handoff menu navigation) — `ChatMessagesView` treats
    # `null` the same as "not this Office's history", never guessed into
    # one. `on_delete=PROTECT`, same as every other Office FK in this
    # project — deleting an Office with message history must be explicit.
    office = models.ForeignKey(Office, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    # Discussed requirement — Conversation/Bot Engine interactive list
    # menus. The stable `rowId` a citizen tapped (WAHA's
    # `listResponseMessage.singleSelectReply.selectedRowID`,
    # `apps.webhooks.parsing.ParsedMessage.list_reply_row_id`) — blank for
    # every ordinary message, including a manually-TYPED reply to a list
    # menu. `apps.chats.conversation_engine` prefers this over `body` for
    # matching a tap unambiguously (label text alone can't disambiguate
    # paginated "Selanjutnya"/"Sebelumnya" rows across more than one
    # page — see that module's own pagination comments).
    list_reply_id = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['session', 'provider_message_id'], name='unique_message_per_session'),
        ]
        indexes = [
            models.Index(fields=['chat', 'timestamp']),
        ]

    def __str__(self):
        return f'{self.provider_message_id} ({self.session_id})'


class MediaReference(TimeStampedModel):
    """A pointer to media held by WAHA (docs/08-DEPLOYMENT.md: WAHA persists
    media under /app/.media) — this table stores a reference only, never the
    media blob itself."""

    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='media')
    provider_media_id = models.CharField(max_length=128, blank=True)
    mime_type = models.CharField(max_length=128, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    storage_reference = models.CharField(max_length=512, blank=True)

    def __str__(self):
        return self.file_name or self.provider_media_id or str(self.pk)
