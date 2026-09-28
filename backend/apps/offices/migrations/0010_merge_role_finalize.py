# Schema-only step 3/3 of merging OfficeMembership's old fixed `role`
# enum into the dynamic `Role` model — safe to run only after 0009 has
# backfilled every row's `requires_office` and every 'operator' row's
# `custom_role` (both required NOT NULL below to be defined everywhere).
#
# Order matters here: the OLD `office_matches_role` constraint (on the
# old `role` CharField + `office`) must be dropped before that column can
# be dropped; the old `role` column must be dropped BEFORE
# `custom_role` can be renamed to `role` (avoids a name collision in the
# migration's intermediate state); `role`/`requires_office` are only
# widened to NOT NULL once every row is guaranteed to have a value
# (0009); the NEW `office_matches_role` constraint (on `requires_office`
# + `office`) is added last.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('offices', '0009_seed_operator_role_and_backfill'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='officemembership',
            name='office_matches_role',
        ),
        migrations.RemoveField(
            model_name='officemembership',
            name='role',
        ),
        migrations.RenameField(
            model_name='officemembership',
            old_name='custom_role',
            new_name='role',
        ),
        migrations.AlterField(
            model_name='officemembership',
            name='role',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name='memberships', to='offices.role'
            ),
        ),
        migrations.AlterField(
            model_name='officemembership',
            name='requires_office',
            field=models.BooleanField(),
        ),
        migrations.AddConstraint(
            model_name='officemembership',
            constraint=models.CheckConstraint(
                check=(
                    models.Q(requires_office=False, office__isnull=True)
                    | models.Q(requires_office=True, office__isnull=False)
                ),
                name='office_matches_role',
            ),
        ),
    ]
