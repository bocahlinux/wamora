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

# Phase 12 (Security hardening) — settings.py's default CACHES points at a
# real Redis instance (shared with Celery), matching the deployed/Docker
# environment this test-settings module explicitly does NOT represent (see
# this module's own docstring above). A sandbox running `manage.py test`
# under config.settings_test has no such Redis reachable, and DRF's
# cache-backed throttling (settings.py REST_FRAMEWORK) would otherwise fail
# every request with a connection error rather than a clean 429. LocMemCache
# is process-local and per-test-run only — fine here since nothing in this
# test settings module needs cross-process cache sharing.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}
