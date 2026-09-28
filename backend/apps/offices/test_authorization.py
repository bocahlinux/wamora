"""Step 3 — Office/role authorization foundation."""

from django.contrib.auth.models import User
from django.test import TestCase

from apps.offices.authorization import (
    can_access_office,
    get_user_office,
    has_global_access,
    is_global_admin,
    is_superadmin,
)
from apps.offices.models import ROLE_GLOBAL_ADMIN, ROLE_OFFICE_ADMIN, ROLE_OPERATOR, Office, OfficeMembership


class OfficeAuthorizationTests(TestCase):
    def setUp(self):
        self.office_a = Office.objects.create(name='Samsat Palangka Raya')
        self.office_b = Office.objects.create(name='Samsat Kasongan')

    # A. SUPERADMIN
    def test_superadmin_can_access_any_office(self):
        superadmin = User.objects.create_superuser('root', password='pw')
        self.assertTrue(is_superadmin(superadmin))
        self.assertTrue(has_global_access(superadmin))
        self.assertTrue(can_access_office(superadmin, self.office_a))
        self.assertTrue(can_access_office(superadmin, self.office_b))

    # F. Superadmin behavior must not depend on OfficeMembership at all.
    def test_superadmin_access_does_not_require_a_membership_row(self):
        superadmin = User.objects.create_superuser('root2', password='pw')
        self.assertFalse(OfficeMembership.objects.filter(user=superadmin).exists())
        self.assertTrue(has_global_access(superadmin))
        self.assertIsNone(get_user_office(superadmin))  # no Office, and that's fine for a superadmin

    # B. GLOBAL_ADMIN
    def test_global_admin_has_global_access_to_any_office(self):
        user = User.objects.create_user('gadmin', password='pw')
        OfficeMembership.objects.create(user=user, office=None, role=ROLE_GLOBAL_ADMIN)

        self.assertFalse(is_superadmin(user))
        self.assertTrue(is_global_admin(user))
        self.assertTrue(has_global_access(user))
        self.assertTrue(can_access_office(user, self.office_a))
        self.assertTrue(can_access_office(user, self.office_b))
        self.assertIsNone(get_user_office(user))  # office membership stays NULL

    # C. OFFICE_ADMIN
    def test_office_admin_can_only_access_own_office(self):
        user = User.objects.create_user('oadmin', password='pw')
        OfficeMembership.objects.create(user=user, office=self.office_a, role=ROLE_OFFICE_ADMIN)

        self.assertFalse(has_global_access(user))
        self.assertEqual(get_user_office(user), self.office_a)
        self.assertTrue(can_access_office(user, self.office_a))
        self.assertFalse(can_access_office(user, self.office_b))

    # D. OPERATOR
    def test_operator_can_only_access_own_office(self):
        user = User.objects.create_user('operator', password='pw')
        OfficeMembership.objects.create(user=user, office=self.office_a, role=ROLE_OPERATOR)

        self.assertFalse(has_global_access(user))
        self.assertEqual(get_user_office(user), self.office_a)
        self.assertTrue(can_access_office(user, self.office_a))
        self.assertFalse(can_access_office(user, self.office_b))

    # E. User without any membership
    def test_user_without_membership_has_no_office_access(self):
        user = User.objects.create_user('nobody', password='pw')

        self.assertFalse(is_superadmin(user))
        self.assertFalse(is_global_admin(user))
        self.assertFalse(has_global_access(user))
        self.assertIsNone(get_user_office(user))
        self.assertFalse(can_access_office(user, self.office_a))
        self.assertFalse(can_access_office(user, self.office_b))

    def test_can_access_office_is_false_for_a_none_target(self):
        superadmin = User.objects.create_superuser('root3', password='pw')
        self.assertFalse(can_access_office(superadmin, None))
