"""Conversation/Bot Engine — admin CRUD shapes. Authorization ("who may
read/write") lives entirely in `apps.bot.views`, built from
`apps.offices.authorization` — same split every other serializer module
in this project already follows (`apps.offices.serializers`'s own
docstring states this explicitly)."""

from rest_framework import serializers

from .models import BotConfig, BotMenu, BotMenuItem, BotTrigger


def _reject_non_ascii(value, field_label):
    # The shared Postgres database is SQL_ASCII (existing infra, not
    # something this app controls). Any non-ASCII character (emoji
    # included) stored here can get echoed back inside a WAHA webhook
    # payload later and crash JSON ingestion at the DB layer. Blocking it
    # at input time is cheaper than a DB encoding migration.
    offenders = sorted({c for c in value if ord(c) > 127})
    if offenders:
        raise serializers.ValidationError(
            f'{field_label} must not contain emoji or other non-ASCII characters '
            f'(found: {" ".join(offenders)}).'
        )
    return value


class BotMenuItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = BotMenuItem
        fields = ['id', 'menu', 'label', 'trigger_value', 'order', 'enabled', 'action_type', 'text', 'target_menu']
        read_only_fields = ['id']

    def validate_trigger_value(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('trigger_value must not be blank.')
        return value

    def validate(self, attrs):
        action_type = attrs.get('action_type', getattr(self.instance, 'action_type', None))
        target_menu = attrs.get('target_menu', getattr(self.instance, 'target_menu', None))
        if action_type == BotMenuItem.ACTION_SHOW_MENU and target_menu is None:
            raise serializers.ValidationError({'target_menu': 'Required when action_type is show_menu.'})
        return attrs


class BotMenuSerializer(serializers.ModelSerializer):
    items = BotMenuItemSerializer(many=True, read_only=True)

    class Meta:
        model = BotMenu
        fields = [
            'id', 'office', 'name', 'parent_menu', 'intro_text', 'is_office_selector', 'enabled', 'items',
        ]
        read_only_fields = ['id']

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('name must not be blank.')
        return value

    def validate_intro_text(self, value):
        return _reject_non_ascii(value, 'intro_text')


class BotTriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = BotTrigger
        fields = ['id', 'office', 'keyword', 'target_menu', 'enabled']
        read_only_fields = ['id']

    def validate_keyword(self, value):
        # Normalized once here (case-insensitive, stripped) so
        # apps.chats.conversation_engine's own matching only ever has to
        # apply the SAME normalization to the incoming message body — a
        # single, shared convention, not two independently-maintained ones.
        value = value.strip().lower()
        if not value:
            raise serializers.ValidationError('keyword must not be blank.')
        return value


class BotConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = BotConfig
        fields = [
            'id', 'office', 'enabled', 'fallback_message', 'session_completed_message', 'root_menu',
            'list_footer_text', 'list_button_text', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
