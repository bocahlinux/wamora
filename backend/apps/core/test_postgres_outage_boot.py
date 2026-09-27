"""Phase 13 Track B Finding 2 (MEDIUM) — regression coverage.

The live failure drill (docs/generated/PHASE-13-TRACK-B-FAILURE-DRILL-REPORT.md)
found that restarting the dev backend container while PostgreSQL was
unreachable crashed the whole process before it ever bound to its HTTP
port: Django's built-in `runserver.Command.inner_run()` calls
`self.check_migrations()` unconditionally, and `check_migrations()`
opens a real database connection with no handling beyond
`ImproperlyConfigured` (no database configured at all) — so an
`OperationalError` from an unreachable database propagated uncaught.

`apps.core.management.commands.runserver.Command` overrides
`check_migrations()` to catch exactly that and log a visible warning
instead of crashing. This proves that override directly (bypassing the
real socket-binding/autoreloader machinery, which is not what changed
and is not safe to exercise in a unit test) and confirms the normal
(database reachable) behavior — including surfacing a *different*,
non-connection database error — is unchanged.

It also guards the override's own discoverability: Django resolves a
command name (here, `runserver`) to whichever installed app appears
EARLIEST in `INSTALLED_APPS` among all apps providing that command name
— `django.contrib.staticfiles` ships its own `runserver` too, and a
naive app ordering would let staticfiles' version silently win instead
of this one (confirmed to actually happen during development of this
fix, before `config/settings.py`'s `INSTALLED_APPS` was reordered).
`test_manage_py_actually_resolves_runserver_to_this_module` catches
exactly that regression, via the same `get_commands()` Django itself
uses.
"""

from unittest import mock

from django.core.management import get_commands
from django.core.management.commands.runserver import Command as DjangoRunserverCommand
from django.db import DataError
from django.db.utils import OperationalError
from django.test import SimpleTestCase

from apps.core.management.commands.runserver import Command as WamoraRunserverCommand


class RunserverCheckMigrationsOverrideTests(SimpleTestCase):
    def test_is_a_runserver_command_override(self):
        self.assertTrue(issubclass(WamoraRunserverCommand, DjangoRunserverCommand))

    def test_manage_py_actually_resolves_runserver_to_this_module(self):
        get_commands.cache_clear()
        self.assertEqual(
            get_commands()['runserver'],
            'apps.core',
            "Django resolved 'runserver' to a different app's command — "
            'this fix has no effect if this is not apps.core (see this '
            "module's docstring on INSTALLED_APPS ordering).",
        )

    def test_check_migrations_swallows_operational_error_and_logs_a_warning(self):
        command = WamoraRunserverCommand()
        with mock.patch.object(
            DjangoRunserverCommand, 'check_migrations', side_effect=OperationalError('could not connect to server')
        ):
            with self.assertLogs('apps.core.management.commands.runserver', level='WARNING') as logs:
                command.check_migrations()  # must not raise
        self.assertIn('unreachable', logs.output[0])

    def test_check_migrations_still_raises_non_operational_database_errors(self):
        """Only a connection-style OperationalError is swallowed — a
        genuinely different database error (not what this fix is about)
        must still surface normally, not be silently hidden."""
        command = WamoraRunserverCommand()
        with mock.patch.object(DjangoRunserverCommand, 'check_migrations', side_effect=DataError('bad data')):
            with self.assertRaises(DataError):
                command.check_migrations()

    def test_check_migrations_normal_path_is_unchanged_when_database_is_reachable(self):
        command = WamoraRunserverCommand()
        with mock.patch.object(DjangoRunserverCommand, 'check_migrations') as mocked:
            command.check_migrations()
        mocked.assert_called_once_with()
