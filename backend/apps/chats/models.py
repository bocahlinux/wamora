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
    # Step 13 (Inbox welcome lifecycle) — nullable, stamped exactly once,
    # the moment the welcome message is actually sent for this Chat (never
    # pre-emptively, never retroactively for a Chat that already existed
    # before this field did — no backfill). Doubles as the idempotency
    # guard: `Chat.objects.filter(pk=..., welcome_sent_at__isnull=True)
    # .update(...)` (apps/chats/inbox_lifecycle.py) is the sole compare-
    # and-set claim that lets at most one concurrent webhook delivery for
    # the same Chat actually send it — same discipline as every other
    # state-changing write in this project (apps.blast.views, apps.sync.views).
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
