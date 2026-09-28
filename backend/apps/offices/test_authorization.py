"""Step 3 — Office/role authorization foundation."""

from django.contrib.auth.models import User
from django.test import TestCase

from apps.offices.authorization import (
    can_access_office,
    get_user_office,
    has_global_access,
    is_global_admin,
    is_office_admin_role,
    is_operator_role,
    is_superadmin,
)
from apps.offices.models import Office, OfficeMembership, Role


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

    # B. Role with grants_global_access
    def test_global_access_role_has_global_access_to_any_office(self):
        user = User.objects.create_user('gadmin', password='pw')
        role = Role.objects.create(name='Global Admin', grants_global_access=True)
        OfficeMembership.objects.create(user=user, office=None, role=role, requires_office=False)

        self.assertFalse(is_superadmin(user))
        self.assertTrue(is_global_admin(user))
        self.assertTrue(has_global_access(user))
        self.assertTrue(can_access_office(user, self.office_a))
        self.assertTrue(can_access_office(user, self.office_b))
        self.assertIsNone(get_user_office(user))  # office membership stays NULL

    # C. Role with is_office_admin
    def test_office_admin_role_can_only_access_own_office(self):
        user = User.objects.create_user('oadmin', password='pw')
        role = Role.objects.create(name='Office Admin', is_office_admin=True)
        OfficeMembership.objects.create(user=user, office=self.office_a, role=role, requires_office=True)

        self.assertFalse(has_global_access(user))
        self.assertTrue(is_office_admin_role(user))
        self.assertFalse(is_operator_role(user))
        self.assertEqual(get_user_office(user), self.office_a)
        self.assertTrue(can_access_office(user, self.office_a))
        self.assertFalse(can_access_office(user, self.office_b))

    # D. Role with is_operator
    def test_operator_role_can_only_access_own_office(self):
        user = User.objects.create_user('operator', password='pw')
        role = Role.objects.create(name='Operator', is_operator=True)
        OfficeMembership.objects.create(user=user, office=self.office_a, role=role, requires_office=True)

        self.assertFalse(has_global_access(user))
        self.assertTrue(is_operator_role(user))
        self.assertFalse(is_office_admin_role(user))
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
