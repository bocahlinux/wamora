"""Dev-only `runserver` override — Phase 13 Track B Finding 2 (MEDIUM).

Django's own `runserver.Command.inner_run()` calls `self.check_migrations()`
unconditionally, before binding the HTTP port. `check_migrations()`
opens a real database connection (`MigrationExecutor(connections[...])`)
with no exception handling beyond `ImproperlyConfigured` (no databases
configured at all). During the Phase 13 Track B live drill, making
PostgreSQL unreachable while the dev backend container restarted meant
this raised an uncaught `django.db.utils.OperationalError`, crashing the
whole process before it ever bound to its port — so `LivenessView`
(deliberately DB-independent, see apps/core/views.py) could not respond
either, even though its own logic never touches the database
(docs/generated/PHASE-13-TRACK-B-FAILURE-DRILL-REPORT.md).

This override catches exactly that: if the database is unreachable when
checking migrations, log a clearly visible warning (never silent — the
underlying error is preserved via `exc_info=True`) and let the server
still start, rather than crash. `DatabaseHealthView` continues to
separately and correctly report the database outage on its own; this
change is only about restoring the ability to start (and to answer
liveness) when Postgres is down, which is a boot-time, process-level
concern, not a database-check concern. No migration is skipped and no
migration error is hidden: `check_migrations()`'s own normal (DB reachable)
behavior — including its usual "unapplied migrations" warning — is
completely unchanged; only the interrupted-by-outage case is now caught.

Dev-only impact: production never invokes `manage.py runserver` — it
runs `gunicorn config.wsgi:application` (backend/Dockerfile CMD). This
command is only ever invoked by `infrastructure/development/office.yml`'s
dev backend service, the sole `runserver` invocation anywhere in this
repository.

Subclasses `django.contrib.staticfiles`'s `runserver` override (not
`django.core`'s directly): `django.contrib.staticfiles` also ships its
own `runserver` command (to serve static files under `DEBUG`), and
Django's command loader resolves a same-named command in favor of
whichever app appears EARLIEST in `INSTALLED_APPS` — `config/settings.py`
lists `apps.core` just before `django.contrib.staticfiles` specifically
so this module (not either built-in one) is what `manage.py runserver`
actually runs. Subclassing staticfiles' own `Command` (itself a
subclass of `django.core`'s) means that static-file-serving behavior is
inherited unchanged; only `check_migrations()` is overridden here.
"""

import logging

from django.contrib.staticfiles.management.commands.runserver import (
    Command as RunserverCommand,
)
from django.db.utils import OperationalError

logger = logging.getLogger(__name__)


class Command(RunserverCommand):
    def check_migrations(self):
        try:
            super().check_migrations()
        except OperationalError:
            logger.warning(
                "Could not check migrations: the database is unreachable. "
                "Continuing to start anyway so this process's liveness "
                "endpoint can still respond; database-dependent endpoints "
                "will keep reporting this outage separately until the "
                "database is reachable again.",
                exc_info=True,
            )
