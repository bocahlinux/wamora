"""Test-only settings override.

NOT used in any deployed environment, Dockerfile, docker-compose file, or
.env.example — the real application database remains PostgreSQL,
configured via environment variables, unconditionally (see
config/settings.py and docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md hard rule).

This module exists solely so `manage.py test` can run against an in-memory
SQLite engine when no PostgreSQL instance is reachable (e.g. local
sandboxes without Docker access to a Postgres container). Invoke
explicitly and only for this purpose:

    DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test
"""

from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}
