from datetime import datetime
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.blast.limits import blast_sends_today, jakarta_day_bounds_utc, remaining_daily_budget
from apps.blast.models import OPERATION_TYPE_BLAST_SEND
from apps.operations.models import OutboundOperation
from apps.waha_sessions.models import WahaSession

JAKARTA = ZoneInfo('Asia/Jakarta')


class JakartaDayBoundsTests(TestCase):
    def test_bounds_span_exactly_24_hours_in_jakarta_local_time(self):
        moment = datetime(2026, 3, 15, 10, 0, tzinfo=JAKARTA)  # 10:00 WIB
        start_utc, end_utc = jakarta_day_bounds_utc(moment)
        self.assertEqual(start_utc.astimezone(JAKARTA).isoformat(), '2026-03-15T00:00:00+07:00')
        self.assertEqual(end_utc.astimezone(JAKARTA).isoformat(), '2026-03-16T00:00:00+07:00')
        self.assertEqual((end_utc - start_utc).total_seconds(), 24 * 3600)

    def test_jakarta_day_boundary_differs_from_utc_day_boundary(self):
        # 2026-03-15 23:30 WIB is still 2026-03-15 UTC+7, but already
        # 2026-03-15 16:30 UTC — the two calendars only coincide for part
        # of the day; this proves the function uses Jakarta's own
        # calendar date, not UTC's (finalized decision 3's explicit
        # override of the design audit's UTC default).
        late_local = datetime(2026, 3, 15, 23, 30, tzinfo=JAKARTA)
        start_utc, end_utc = jakarta_day_bounds_utc(late_local)
        # UTC equivalent of 2026-03-15 00:00 WIB is 2026-03-14 17:00 UTC.
        self.assertEqual(start_utc.isoformat(), '2026-03-14T17:00:00+00:00')
        self.assertEqual(end_utc.isoformat(), '2026-03-15T17:00:00+00:00')


@override_settings(BLAST_MAX_RECIPIENTS_PER_SESSION_PER_DAY=5)
class BlastSendsTodayTests(TestCase):
    def setUp(self):
        self.session = WahaSession.objects.create(name='primary')
        self.other_session = WahaSession.objects.create(name='secondary')

    def _create_operation(self, session, key, operation_type=OPERATION_TYPE_BLAST_SEND, created_at=None):
        op = OutboundOperation.objects.create(
            session=session, idempotency_key=key, destination='+62800000000', operation_type=operation_type,
            status=OutboundOperation.STATUS_SENT,
        )
        if created_at is not None:
            OutboundOperation.objects.filter(pk=op.pk).update(created_at=created_at)
            op.refresh_from_db()
        return op

    def test_counts_only_blast_send_operation_type(self):
        self._create_operation(self.session, 'blast:1:1', operation_type=OPERATION_TYPE_BLAST_SEND)
        self._create_operation(self.session, 'sendtext-key', operation_type='sendText')
        self.assertEqual(blast_sends_today(self.session), 1)

    def test_counts_only_current_session(self):
        self._create_operation(self.session, 'blast:1:1')
        self._create_operation(self.other_session, 'blast:1:2')
        self.assertEqual(blast_sends_today(self.session), 1)

    def test_excludes_operations_created_before_todays_jakarta_boundary(self):
        now = timezone.now()
        start_utc, _ = jakarta_day_bounds_utc(now)
        yesterday = start_utc - timezone.timedelta(minutes=1)
        self._create_operation(self.session, 'blast:old:1', created_at=yesterday)
        self.assertEqual(blast_sends_today(self.session, moment=now), 0)

    def test_remaining_daily_budget_subtracts_used(self):
        for i in range(3):
            self._create_operation(self.session, f'blast:1:{i}')
        self.assertEqual(remaining_daily_budget(self.session), 2)

    def test_remaining_daily_budget_never_negative(self):
        for i in range(10):
            self._create_operation(self.session, f'blast:1:{i}')
        self.assertEqual(remaining_daily_budget(self.session), 0)
