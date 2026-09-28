from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.offices.models import (
    ROLE_GLOBAL_ADMIN,
    ROLE_OFFICE_ADMIN,
    ROLE_OPERATOR,
    Office,
    OfficeInboxConfig,
    OfficeMembership,
)


class OfficeTests(TestCase):
    def test_create_office(self):
        office = Office.objects.create(name='Samsat Palangka Raya')
        self.assertTrue(office.is_active)

    def test_name_is_unique(self):
        Office.objects.create(name='Samsat Palangka Raya')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Office.objects.create(name='Samsat Palangka Raya')

    def test_office_can_be_made_inactive(self):
        office = Office.objects.create(name='Samsat Sampit')
        office.is_active = False
        office.save()
        office.refresh_from_db()
        self.assertFalse(office.is_active)


class OfficeMembershipTests(TestCase):
    def setUp(self):
        self.office_a = Office.objects.create(name='Samsat Palangka Raya')
        self.office_b = Office.objects.create(name='Samsat Kasongan')

    def test_membership_links_user_to_office(self):
        user = User.objects.create_user('operator1', password='pw')
        membership = OfficeMembership.objects.create(user=user, office=self.office_a, role=ROLE_OPERATOR)
        self.assertEqual(membership.office, self.office_a)
        self.assertEqual(user.office_membership.office, self.office_a)

    def test_one_office_can_have_multiple_users(self):
        admin = User.objects.create_user('admin1', password='pw')
        operator = User.objects.create_user('operator2', password='pw')
        OfficeMembership.objects.create(user=admin, office=self.office_a, role=ROLE_OFFICE_ADMIN)
        OfficeMembership.objects.create(user=operator, office=self.office_a, role=ROLE_OPERATOR)
        self.assertEqual(self.office_a.memberships.count(), 2)

    def test_user_cannot_have_two_offices(self):
        user = User.objects.create_user('operator3', password='pw')
        OfficeMembership.objects.create(user=user, office=self.office_a, role=ROLE_OPERATOR)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OfficeMembership.objects.create(user=user, office=self.office_b, role=ROLE_OPERATOR)

    def test_superadmin_can_have_no_office_membership(self):
        superadmin = User.objects.create_superuser('root', password='pw')
        self.assertFalse(OfficeMembership.objects.filter(user=superadmin).exists())
        # No exception, no required row — a superuser is simply never
        # given an OfficeMembership; nothing in this model forces one.

    def test_regular_user_can_exist_without_office_during_transition(self):
        user = User.objects.create_user('unassigned', password='pw')
        # Reverse OneToOne accessor raises RelatedObjectDoesNotExist when
        # absent, which hasattr() turns into a plain False — this is the
        # "no Office yet, and that's fine" transition state.
        self.assertFalse(hasattr(user, 'office_membership'))
        self.assertFalse(OfficeMembership.objects.filter(user=user).exists())


class OfficeMembershipRoleTests(TestCase):
    """Step 2 — role/permission architecture."""

    def setUp(self):
        self.office_a = Office.objects.create(name='Samsat Palangka Raya')

    def test_office_admin_has_office_admin_role(self):
        user = User.objects.create_user('padmin', password='pw')
        membership = OfficeMembership.objects.create(user=user, office=self.office_a, role=ROLE_OFFICE_ADMIN)
        membership.refresh_from_db()
        self.assertEqual(membership.role, ROLE_OFFICE_ADMIN)

    def test_operator_has_operator_role(self):
        user = User.objects.create_user('poperator', password='pw')
        membership = OfficeMembership.objects.create(user=user, office=self.office_a, role=ROLE_OPERATOR)
        membership.refresh_from_db()
        self.assertEqual(membership.role, ROLE_OPERATOR)

    def test_global_admin_can_be_represented_without_an_office(self):
        user = User.objects.create_user('globaladmin', password='pw')
        membership = OfficeMembership.objects.create(user=user, office=None, role=ROLE_GLOBAL_ADMIN)
        membership.refresh_from_db()
        self.assertIsNone(membership.office)
        self.assertEqual(membership.role, ROLE_GLOBAL_ADMIN)

    def test_global_admin_role_rejects_an_office(self):
        # The office_matches_role CheckConstraint: GLOBAL_ADMIN must have
        # no Office — a Global Admin is not tied to one, by design.
        user = User.objects.create_user('badglobaladmin', password='pw')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OfficeMembership.objects.create(user=user, office=self.office_a, role=ROLE_GLOBAL_ADMIN)

    def test_office_admin_role_requires_an_office(self):
        # The same constraint, the other direction: OFFICE_ADMIN/OPERATOR
        # are only meaningful within a specific Office.
        user = User.objects.create_user('badofficeadmin', password='pw')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OfficeMembership.objects.create(user=user, office=None, role=ROLE_OFFICE_ADMIN)

    def test_superadmin_remains_representable_without_any_membership_row(self):
        # Unchanged from Step 1 — is_superuser alone is still sufficient;
        # this re-confirms adding `role` didn't force a row into existence.
        superadmin = User.objects.create_superuser('root2', password='pw')
        self.assertFalse(OfficeMembership.objects.filter(user=superadmin).exists())


class OfficeInboxConfigTests(TestCase):
    """Step 10 — Office Inbox configuration foundation."""

    def setUp(self):
        self.office = Office.objects.create(name='Samsat Palangka Raya')

    def test_office_can_have_one_inbox_config(self):
        config = OfficeInboxConfig.objects.create(office=self.office)
        self.assertEqual(config.office, self.office)

    def test_office_cannot_have_two_inbox_configs(self):
        OfficeInboxConfig.objects.create(office=self.office)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OfficeInboxConfig.objects.create(office=self.office)

    def test_default_enabled_is_false(self):
        config = OfficeInboxConfig.objects.create(office=self.office)
        self.assertFalse(config.enabled)

    def test_default_messages_are_empty(self):
        config = OfficeInboxConfig.objects.create(office=self.office)
        self.assertEqual(config.welcome_message, '')
        self.assertEqual(config.waiting_message, '')
        self.assertEqual(config.offline_message, '')

    def test_message_fields_are_saved(self):
        config = OfficeInboxConfig.objects.create(
            office=self.office,
            enabled=True,
            welcome_message='Halo, Anda terhubung dengan Petugas.',
            waiting_message='Pesan Anda sudah diterima.',
            offline_message='Petugas sedang tidak tersedia.',
        )
        config.refresh_from_db()
        self.assertTrue(config.enabled)
        self.assertEqual(config.welcome_message, 'Halo, Anda terhubung dengan Petugas.')
        self.assertEqual(config.waiting_message, 'Pesan Anda sudah diterima.')
        self.assertEqual(config.offline_message, 'Petugas sedang tidak tersedia.')

    def test_inactive_office_can_still_have_a_config(self):
        self.office.is_active = False
        self.office.save(update_fields=['is_active'])
        config = OfficeInboxConfig.objects.create(office=self.office, enabled=True)
        self.assertTrue(config.enabled)
        self.office.refresh_from_db()
        self.assertFalse(self.office.is_active)
        # Office.is_active and InboxConfig.enabled are independent — both
        # combinations are valid, this one included.
