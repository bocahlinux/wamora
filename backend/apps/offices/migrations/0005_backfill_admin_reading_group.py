# Bug fix backfill — `_sync_admin_scope_group()` (apps/offices/serializers.py)
# now grants the 'reading' Django Group to Global Admin/Office Admin, same
# as 'user administration'/'blast', because 'reading' alone gates Dashboard
# stats/activity (apps.dashboard.views, HasReadingScope), the BFF
# WhatsApp-session-status route (bff/src/routes/session.ts), and Inbox's
# sync-status poll (apps.sync.views, HasReadingScope) — none of which
# HasOfficeAdminAccess/HasOfficeAccess reach. That fix only takes effect on
# a FUTURE create or role-update call; this migration is the one-time
# backfill for OfficeMembership rows that already had role=global_admin/
# office_admin before the fix landed, so no manual `manage.py shell` step
# is needed after deploying it.
#
# Deliberately does not replace or duplicate `_sync_admin_scope_group()`
# itself — ROLE_GROUPS/_MANAGED_GROUP_NAMES in serializers.py remain the
# single source of truth for which Groups a role gets going forward; this
# migration only reaches parity for rows that predate that mapping change.
# Only ADDS the 'reading' Group — never touches any other Group a user may
# already have (e.g. it never removes 'system administration', which no
# Admin role has ever been granted, before or after this fix).
from django.conf import settings
from django.db import migrations

# Mirrors apps.offices.models.ROLE_GLOBAL_ADMIN/ROLE_OFFICE_ADMIN as plain
# strings (never import app code from inside a migration — this uses the
# historical `apps` registry only) — these two role values have not
# changed since 0002_officemembership_role.py and are not expected to.
ROLE_GLOBAL_ADMIN = 'global_admin'
ROLE_OFFICE_ADMIN = 'office_admin'

READING_GROUP_NAME = 'reading'


def backfill_reading_group(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    OfficeMembership = apps.get_model('offices', 'OfficeMembership')

    reading_group, _ = Group.objects.get_or_create(name=READING_GROUP_NAME)

    admin_user_ids = OfficeMembership.objects.filter(
        role__in=[ROLE_GLOBAL_ADMIN, ROLE_OFFICE_ADMIN],
    ).values_list('user_id', flat=True)

    # `through.objects.bulk_create(..., ignore_conflicts=True)` on the
    # User<->Group m2m table — idempotent (a re-run, e.g. after a rollback
    # and reapply, adds nothing new) and never touches any Group a user
    # already belongs to, unlike `group.user_set.set(...)` which would.
    through = User.groups.through
    through.objects.bulk_create(
        [through(user_id=user_id, group_id=reading_group.pk) for user_id in admin_user_ids],
        ignore_conflicts=True,
    )


def noop_reverse(apps, schema_editor):
    # Deliberately a no-op, not a removal of the 'reading' Group membership
    # this migration added: reversing would also strip 'reading' from any
    # admin who was independently given it by a normal role-update call
    # (`_sync_admin_scope_group()`) after this migration ran — this
    # migration cannot distinguish the two, so it does not try.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('offices', '0004_officemembership_is_available'),
        ('auth', '0012_alter_user_first_name_max_length'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(backfill_reading_group, noop_reverse),
    ]
