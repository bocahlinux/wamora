# Data migration for the new dynamic Role model (0006_role.py) — seeds the
# two Roles that replace the just-superseded hardcoded `ROLE_GROUPS`
# mapping (apps/offices/serializers.py), then backfills every existing
# `global_admin`/`office_admin` OfficeMembership to point at the matching
# seeded Role. Behavior-preserving: each seeded Role's `scopes` is exactly
# today's `ROLE_GROUPS` bundle (`reading`, `blast`, `user
# administration`) — after this migration, an existing admin's effective
# JWT scopes are unchanged; only the DATA SOURCE for them moves from a
# code constant to an editable `Role` row a Superadmin can now manage
# through the UI.
#
# Deliberately does not touch Django Groups directly — `_sync_role_groups`
# (apps/offices/serializers.py) is the one place that syncs a user's
# Groups to their `custom_role.scopes`, and it already ran for these users
# under the old `_sync_admin_scope_group` when their membership was
# created/updated, so their Groups already match this migration's seeded
# Role's `scopes` (see 0005_backfill_admin_reading_group.py for the
# 'reading' half of that history). This migration only wires up the new
# `custom_role` pointer for consistency and future editability — a
# Superadmin who later edits the seeded Role's scopes will have that
# change take effect the next time a user's membership is saved (through
# `_sync_role_groups`), exactly like editing `ROLE_GROUPS` used to require
# a code change plus a rerun of `_sync_admin_scope_group`.
from django.db import migrations

ROLE_GLOBAL_ADMIN = 'global_admin'
ROLE_OFFICE_ADMIN = 'office_admin'

SEED_ROLE_SCOPES = ['reading', 'blast', 'user administration']

SEED_ROLES = {
    ROLE_GLOBAL_ADMIN: 'Global Admin',
    ROLE_OFFICE_ADMIN: 'Office Admin',
}


def seed_and_backfill(apps, schema_editor):
    Role = apps.get_model('offices', 'Role')
    OfficeMembership = apps.get_model('offices', 'OfficeMembership')

    role_by_org_role = {}
    for org_role, role_name in SEED_ROLES.items():
        role, _ = Role.objects.get_or_create(name=role_name, defaults={'scopes': SEED_ROLE_SCOPES})
        role_by_org_role[org_role] = role

    for org_role, role in role_by_org_role.items():
        # Only fills a NULL custom_role — never overwrites one a
        # Superadmin may have already assigned since 0006 was applied
        # (idempotent: safe to re-run, e.g. after a rollback/reapply).
        OfficeMembership.objects.filter(role=org_role, custom_role__isnull=True).update(custom_role=role)


def noop_reverse(apps, schema_editor):
    # Deliberately a no-op — clearing custom_role on reverse would strip
    # it from any membership a Superadmin has independently kept pointed
    # at one of these seeded Roles since this migration ran, which this
    # migration cannot distinguish from a row it set itself. Same
    # reasoning as 0005_backfill_admin_reading_group.py's noop_reverse.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('offices', '0006_role'),
    ]

    operations = [
        migrations.RunPython(seed_and_backfill, noop_reverse),
    ]
