"""Inbox/Chat (canonical Phase 8) read serializers —
docs/generated/INBOX-CHAT-DECISION-REPORT.md. Read-only (no create/update
fields exposed) — mutation (mark-as-read) is a dedicated, minimal view,
not a serializer-driven update.
"""

from rest_framework import serializers

from .models import Chat, MediaReference, Message


class ChatListSerializer(serializers.ModelSerializer):
    contact_name = serializers.SerializerMethodField()
    # Inbox display-identity fix —
    # docs/generated/INBOX-IDENTITY-DISPLAY-AUDIT-REPORT.md: exposes
    # Contact.phone_number (already correctly stored/linked, never
    # previously returned by this API) as a display fallback — no merge,
    # no new identity resolution, just surfacing existing, already-linked
    # data.
    phone_number = serializers.SerializerMethodField()
    unread = serializers.SerializerMethodField()

    class Meta:
        model = Chat
        fields = [
            'id',
            'provider_chat_id',
            'name',
            'is_group',
            'contact_name',
            'phone_number',
            'last_message_at',
            'last_read_at',
            'unread',
        ]

    def get_contact_name(self, obj):
        # Relies on the view's queryset using select_related('contact') —
        # accessing obj.contact here must never trigger a per-row query.
        return obj.contact.display_name if obj.contact_id and obj.contact.display_name else None

    def get_phone_number(self, obj):
        # Same select_related('contact') as get_contact_name — no extra query.
        return obj.contact.phone_number if obj.contact_id and obj.contact.phone_number else None

    def get_unread(self, obj):
        # No message yet -> nothing to read. Never read -> unread once a
        # message exists. Otherwise: has a message arrived since the last
        # read? (docs/generated/INBOX-CHAT-DECISION-REPORT.md Section 2 —
        # chat-level state, this is the whole derivation.)
        if obj.last_message_at is None:
            return False
        if obj.last_read_at is None:
            return True
        return obj.last_message_at > obj.last_read_at


class MediaReferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = MediaReference
        # storage_reference is deliberately excluded — it's an internal
        # pointer with no defined public-serving mechanism
        # (docs/generated/INBOX-CHAT-AUDIT-REPORT.md Section 5); exposing
        # it would let the frontend construct an assumption this project
        # has never confirmed, rather than an actually usable URL.
        fields = ['id', 'provider_media_id', 'mime_type', 'file_name']


class MessageSerializer(serializers.ModelSerializer):
    # Relies on the view's queryset using prefetch_related('media').
    media = MediaReferenceSerializer(many=True, read_only=True)

    class Meta:
        model = Message
        fields = [
            'id',
            'provider_message_id',
            'direction',
            'message_type',
            'body',
            'status',
            'timestamp',
            'media',
        ]
