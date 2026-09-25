"""Blast-specific daily send-budget accounting — finalized decision 3:
the 500/day/session counter is BLAST-SPECIFIC (only
`operation_type='blastSend'` OutboundOperation rows), not shared with
normal 1:1 outbound sends, and resets on the CALENDAR DAY in Asia/Jakarta
(not UTC). Both override the design audit's Section 5 defaults, per the
finalized decisions.

`zoneinfo` is Python 3.9+ stdlib (backend/Dockerfile: python:3.12-slim) —
no new dependency needed for the Asia/Jakarta boundary math.
"""

from datetime import datetime, time, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from apps.blast.models import OPERATION_TYPE_BLAST_SEND
from apps.operations.models import OutboundOperation

JAKARTA_TZ = ZoneInfo('Asia/Jakarta')


def jakarta_day_bounds_utc(moment=None):
    """Returns (start_utc, end_utc) — the [start, end) UTC instants
    spanning the Asia/Jakarta calendar day containing `moment` (default:
    now). Used as a half-open range so a row landing exactly at midnight
    the next day is correctly excluded from "today"."""
    moment = moment or timezone.now()
    local = moment.astimezone(JAKARTA_TZ)
    start_local = datetime.combine(local.date(), time.min, tzinfo=JAKARTA_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(dt_timezone.utc), end_local.astimezone(dt_timezone.utc)


def blast_sends_today(session, moment=None) -> int:
    """Count of `OutboundOperation` rows of `operation_type='blastSend'`
    for this session, created within the current Asia/Jakarta calendar
    day — every such row represents one attempted WAHA dispatch
    (regardless of its eventual sent/failed outcome), which is what the
    spam/ban-risk budget is actually about (an attempt still reaches
    WhatsApp's servers even if WAHA later reports a failure)."""
    start_utc, end_utc = jakarta_day_bounds_utc(moment)
    return OutboundOperation.objects.filter(
        session=session,
        operation_type=OPERATION_TYPE_BLAST_SEND,
        created_at__gte=start_utc,
        created_at__lt=end_utc,
    ).count()


def remaining_daily_budget(session, moment=None) -> int:
    """How many more blast recipient-sends this session may make today,
    never negative."""
    used = blast_sends_today(session, moment)
    return max(0, settings.BLAST_MAX_RECIPIENTS_PER_SESSION_PER_DAY - used)
