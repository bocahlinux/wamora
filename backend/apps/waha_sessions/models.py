from django.db import models

from apps.core.models import TimeStampedModel


class WahaSession(TimeStampedModel):
    """A WAHA session (one WhatsApp connection). Acts as the scoping unit for
    chats/messages/webhooks/sync/outbound operations — docs/04-DATA-MODEL.md
    "Message identity": identifiers are stable provider IDs scoped by
    session, never global.

    `status` intentionally has no fixed `choices`: WAHA's exact status
    vocabulary is not enumerated in docs/12-WAHA-REFERENCE.md ("Production
    implementation must verify endpoint details against the installed WAHA
    version"), so this stores the raw reported value instead of guessing
    an enum that later turns out to be wrong.
    """

    name = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=32, blank=True)
    last_status_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name
