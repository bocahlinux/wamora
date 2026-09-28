from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.offices.models import Office
from apps.waha_sessions.models import WahaSession


class WahaSessionTests(TestCase):
    def test_name_is_unique(self):
        WahaSession.objects.create(name='default')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                WahaSession.objects.create(name='default')


class WahaSessionOfficeMappingTests(TestCase):
    """Step 9 (Inbox Office routing foundation) — WahaSession.office."""

    def test_session_is_valid_with_no_office_mapping(self):
        session = WahaSession.objects.create(name='no_epahari')
        self.assertIsNone(session.office)

    def test_session_can_be_mapped_to_an_office(self):
        office = Office.objects.create(name='Samsat Palangka Raya')
        session = WahaSession.objects.create(name='no_epahari', office=office)
        self.assertEqual(session.office, office)

    def test_one_office_can_have_many_sessions(self):
        office = Office.objects.create(name='Samsat Palangka Raya')
        session_a = WahaSession.objects.create(name='session-a', office=office)
        session_b = WahaSession.objects.create(name='session-b', office=office)
        self.assertEqual(set(office.waha_sessions.all()), {session_a, session_b})

    def test_mapping_can_be_changed_without_affecting_the_session_identity(self):
        office_a = Office.objects.create(name='Office A')
        office_b = Office.objects.create(name='Office B')
        session = WahaSession.objects.create(name='no_epahari', office=office_a)
        session.office = office_b
        session.save(update_fields=['office'])
        session.refresh_from_db()
        self.assertEqual(session.office, office_b)
        self.assertEqual(session.name, 'no_epahari')
