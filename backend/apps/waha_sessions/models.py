from django.db import models

from apps.core.models import TimeStampedModel
from apps.offices.models import Office


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
    # Step 9 (Inbox Office routing foundation) — nullable, PROTECT, same
    # pattern as Chat.office/BlastCampaign.office: one Office can own many
    # WahaSession rows (a plain FK), one session has at most one Office.
    # Left NULL for every existing session (no auto-backfill, no
    # auto-created Office) until an admin maps it explicitly — see
    # apps/webhooks/services.py::persist_message and
    # apps/sync/reconciliation.py::_discover_chats for where a NEW Chat's
    # own `office` is copied from this field at creation time only, never
    # on an existing Chat.
    office = models.ForeignKey(
        Office, on_delete=models.PROTECT, null=True, blank=True, related_name='waha_sessions'
    )

    def __str__(self):
        return self.name
