from django.db import models

from apps.core.models import TimeStampedModel
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
