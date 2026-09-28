# Schema-only step 1/3 of merging OfficeMembership's old fixed `role`
# enum into the dynamic `Role` model (see 0009's docstring for the full
# picture). Purely additive — safe to apply without any data loss risk:
# three new booleans on Role (all default False, so every existing Role
# row keeps meaning "grants nothing extra" until 0009 explicitly sets the
# two seeded Roles' flags), and a temporarily-nullable
# `requires_office` on OfficeMembership (0009 backfills it from the old
# `role` column; 0010 makes it non-nullable once every row has a value).
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('offices', '0007_seed_and_backfill_roles'),
    ]

    operations = [
        migrations.AddField(
            model_name='role',
            name='grants_global_access',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='role',
            name='is_office_admin',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='role',
            name='is_operator',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='officemembership',
            name='requires_office',
            field=models.BooleanField(null=True),
        ),
    ]
