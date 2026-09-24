from rest_framework import serializers

from .models import AuditLog


class AuditEventSerializer(serializers.Serializer):
    actor_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    action = serializers.CharField(max_length=128)
    target = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    result = serializers.ChoiceField(choices=[AuditLog.RESULT_SUCCESS, AuditLog.RESULT_FAILURE])
