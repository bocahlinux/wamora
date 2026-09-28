from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.offices.models import Office, OfficeInboxConfig, OfficeMembership, Role


def _role(name, **flags):
    return Role.objects.create(name=name, **flags)


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
        membership = OfficeMembership.objects.create(
            user=user, office=self.office_a, role=_role('Operator', is_operator=True), requires_office=True
        )
        self.assertEqual(membership.office, self.office_a)
        self.assertEqual(user.office_membership.office, self.office_a)

    def test_one_office_can_have_multiple_users(self):
        admin = User.objects.create_user('admin1', password='pw')
        operator = User.objects.create_user('operator2', password='pw')
        OfficeMembership.objects.create(
            user=admin, office=self.office_a, role=_role('Office Admin', is_office_admin=True), requires_office=True
        )
        OfficeMembership.objects.create(
            user=operator, office=self.office_a, role=_role('Operator2', is_operator=True), requires_office=True
        )
        self.assertEqual(self.office_a.memberships.count(), 2)

    def test_user_cannot_have_two_offices(self):
        user = User.objects.create_user('operator3', password='pw')
        role = _role('Operator3', is_operator=True)
        OfficeMembership.objects.create(user=user, office=self.office_a, role=role, requires_office=True)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OfficeMembership.objects.create(user=user, office=self.office_b, role=role, requires_office=True)

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
    """Step 2 — role/permission architecture, extended by the Role merge:
    `role` is now a `Role` FK carrying `grants_global_access`/
    `is_office_admin`/`is_operator`, and `requires_office` is the
    denormalized copy of `not role.grants_global_access` the
    `office_matches_role` CheckConstraint actually checks (see that
    field's own comment in models.py for why — a CHECK can't join to the
    separate Role table)."""

    def setUp(self):
        self.office_a = Office.objects.create(name='Samsat Palangka Raya')

    def test_office_admin_role_has_is_office_admin_flag(self):
        user = User.objects.create_user('padmin', password='pw')
        membership = OfficeMembership.objects.create(
            user=user, office=self.office_a, role=_role('Office Admin', is_office_admin=True), requires_office=True
        )
        membership.refresh_from_db()
        self.assertTrue(membership.role.is_office_admin)

    def test_operator_role_has_is_operator_flag(self):
        user = User.objects.create_user('poperator', password='pw')
        membership = OfficeMembership.objects.create(
            user=user, office=self.office_a, role=_role('Operator', is_operator=True), requires_office=True
        )
        membership.refresh_from_db()
        self.assertTrue(membership.role.is_operator)

    def test_global_access_role_can_be_represented_without_an_office(self):
        user = User.objects.create_user('globaladmin', password='pw')
        membership = OfficeMembership.objects.create(
            user=user, office=None, role=_role('Global Admin', grants_global_access=True), requires_office=False
        )
        membership.refresh_from_db()
        self.assertIsNone(membership.office)
        self.assertTrue(membership.role.grants_global_access)

    def test_global_access_role_rejects_an_office(self):
        # The office_matches_role CheckConstraint: a globally-accessing
        # Role must have no Office (requires_office=False) — such a user
        # is not tied to one, by design.
        user = User.objects.create_user('badglobaladmin', password='pw')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OfficeMembership.objects.create(
                    user=user, office=self.office_a, role=_role('Bad Global Admin', grants_global_access=True),
                    requires_office=False,
                )

    def test_non_global_role_requires_an_office(self):
        # The same constraint, the other direction: a non-globally-
        # accessing Role is only meaningful within a specific Office.
        user = User.objects.create_user('badofficeadmin', password='pw')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OfficeMembership.objects.create(
                    user=user, office=None, role=_role('Bad Office Admin', is_office_admin=True),
                    requires_office=True,
                )

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
