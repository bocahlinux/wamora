# Data-only step 2/3 of merging OfficeMembership's old fixed `role` enum
# into the dynamic `Role` model.
#
# 1. Renames the two seeded Roles from 0007
#    (`0007_seed_and_backfill_roles.py`'s own `SEED_ROLES` = {'global_admin':
#    'Global Admin', 'office_admin': 'Office Admin'}) to the plain
#    `ROLE_GLOBAL_ADMIN`/`ROLE_OFFICE_ADMIN` constant strings themselves
#    (apps/offices/models.py) — so `Role.objects.get(name=ROLE_OFFICE_ADMIN)`
#    is a stable, mechanical lookup for the many test call sites that used
#    to pass that constant directly as the old CharField's value. A
#    Superadmin can rename either row to something friendlier afterward
#    (Settings -> Roles) — nothing about these three seeded rows is
#    special or protected once they exist.
# 2. Sets `grants_global_access`/`is_office_admin` on those two seeded
#    Roles (their `scopes` from 0007 — reading/blast/user administration —
#    are untouched), and creates a third seeded Role named
#    `ROLE_OPERATOR` (`is_operator=True`, no `scopes` — matches today's
#    Operator having no elevated scope by default).
# 3. Backfills every `OfficeMembership` whose OLD `role` CharField value
#    is 'operator' and whose `custom_role` is still NULL to point at the
#    new seeded Operator Role — mirrors 0007's own backfill for the other
#    two org roles (only fills a NULL `custom_role`, never overwrites one
#    a Superadmin may have since assigned — idempotent, safe to re-run).
# 3b. Separately (and this is NOT redundant with 3 above): for every
#    membership whose `custom_role` was ALREADY set — e.g. a Superadmin
#    used the Role feature (added before this merge) to assign a custom
#    Role to an existing Global/Office Admin/Operator — that Role never
#    had a chance to carry the new org-standing flags, since they didn't
#    exist yet when it was created. Sets the matching flag (True only,
#    additive) on every SUCH Role from the membership's old `role`
#    CharField value, so an already-custom-Role-assigned Operator doesn't
#    silently stop being treated as one (checked and fixed against the
#    dev/staging DB: a real pre-existing "Operator" custom Role had
#    exactly this gap before this step was added).
# 4. Backfills the new `requires_office` column (added nullable by 0008)
#    on EVERY membership from the old `role` CharField
#    (`role != 'global_admin'`) — 0010 will make this column non-nullable
#    once this has run, so 0010 depends on this migration.
from django.db import migrations

ROLE_GLOBAL_ADMIN = 'global_admin'
ROLE_OFFICE_ADMIN = 'office_admin'
ROLE_OPERATOR = 'operator'

# The exact display names 0007 seeded — renamed to the constants above.
OLD_SEED_DISPLAY_NAMES = {
    ROLE_GLOBAL_ADMIN: 'Global Admin',
    ROLE_OFFICE_ADMIN: 'Office Admin',
}


def seed_and_backfill(apps, schema_editor):
    Role = apps.get_model('offices', 'Role')
    OfficeMembership = apps.get_model('offices', 'OfficeMembership')

    for org_role, display_name in OLD_SEED_DISPLAY_NAMES.items():
        # get_or_create on the NEW name first (idempotent re-run after
        # the rename has already happened once), falling back to finding
        # the OLD display-named row created by 0007 and renaming it.
        role = Role.objects.filter(name=org_role).first()
        if role is None:
            role = Role.objects.filter(name=display_name).first()
            if role is not None:
                role.name = org_role
                role.save(update_fields=['name'])
        if role is None:
            # Defensive only — 0007 always creates these two rows, so
            # this path is not expected to run in practice.
            role = Role.objects.create(name=org_role, scopes=['reading', 'blast', 'user administration'])
        if org_role == ROLE_GLOBAL_ADMIN and not role.grants_global_access:
            role.grants_global_access = True
            role.save(update_fields=['grants_global_access'])
        if org_role == ROLE_OFFICE_ADMIN and not role.is_office_admin:
            role.is_office_admin = True
            role.save(update_fields=['is_office_admin'])

    operator_role, _ = Role.objects.get_or_create(name=ROLE_OPERATOR, defaults={'is_operator': True, 'scopes': []})
    if not operator_role.is_operator:
        operator_role.is_operator = True
        operator_role.save(update_fields=['is_operator'])

    OfficeMembership.objects.filter(role=ROLE_OPERATOR, custom_role__isnull=True).update(custom_role=operator_role)

    # 3b — see the module docstring above. Additive only: never clears a
    # flag, only ever sets one True on a Role a membership's old org role
    # says it should have.
    flag_by_org_role = {
        ROLE_GLOBAL_ADMIN: 'grants_global_access',
        ROLE_OFFICE_ADMIN: 'is_office_admin',
        ROLE_OPERATOR: 'is_operator',
    }
    for org_role, flag_name in flag_by_org_role.items():
        role_ids = (
            OfficeMembership.objects.filter(role=org_role, custom_role__isnull=False)
            .values_list('custom_role_id', flat=True)
            .distinct()
        )
        Role.objects.filter(pk__in=list(role_ids), **{flag_name: False}).update(**{flag_name: True})

    OfficeMembership.objects.exclude(role=ROLE_GLOBAL_ADMIN).update(requires_office=True)
    OfficeMembership.objects.filter(role=ROLE_GLOBAL_ADMIN).update(requires_office=False)


def noop_reverse(apps, schema_editor):
    # Deliberately a no-op — same reasoning as every other data migration
    # in this app (0005/0007): reversing could strip a Role assignment or
    # rename a row a Superadmin has since deliberately changed, which this
    # migration cannot distinguish from state it set itself.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('offices', '0008_role_org_flags'),
    ]

    operations = [
        migrations.RunPython(seed_and_backfill, noop_reverse),
    ]
