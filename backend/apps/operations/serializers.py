from rest_framework import serializers

from .models import OutboundOperation


class OutboundOperationRegisterSerializer(serializers.Serializer):
    session = serializers.CharField(max_length=64)
    idempotency_key = serializers.CharField(max_length=128)
    destination = serializers.CharField(max_length=128)
    operation_type = serializers.CharField(max_length=32)


class OutboundOperationResolveSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[OutboundOperation.STATUS_SENT, OutboundOperation.STATUS_FAILED, OutboundOperation.STATUS_UNKNOWN]
    )
    provider_message_id = serializers.CharField(max_length=128, required=False, allow_blank=True, default='')
    actor_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    action = serializers.CharField(max_length=128, required=False, allow_blank=True, default='')
    target = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    result = serializers.ChoiceField(choices=['success', 'failure'], required=False, allow_null=True, default=None)
