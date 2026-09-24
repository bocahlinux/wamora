from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """docs/06-SECURITY.md: record actor, time, action, target and result
    for sensitive operations. Append-only — no updated_at; entries are not
    expected to change after creation.

    A generic metadata/extra-context field was intentionally NOT added: the
    source document names exactly these five fields (actor, time, action,
    target, result). Add one later only if a concrete, documented need for
    it arises.
    """

    RESULT_SUCCESS = 'success'
    RESULT_FAILURE = 'failure'
    RESULT_CHOICES = [
        (RESULT_SUCCESS, 'Success'),
        (RESULT_FAILURE, 'Failure'),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs'
    )
    action = models.CharField(max_length=128)
    target = models.CharField(max_length=255, blank=True)
    result = models.CharField(max_length=16, choices=RESULT_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.action}:{self.result}'
