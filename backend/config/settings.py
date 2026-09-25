"""
Django settings for config project.

WAHA Monitoring Dashboard — office backend.
All environment-specific and secret values are read from environment
variables. Never hardcode real secrets here (see docs/06-SECURITY.md).
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Local-development ergonomics only — loads backend/.env into os.environ
# if present, without overriding a variable already set in the real
# environment. No-op in Docker/production, where backend/.env never
# exists inside the image (backend/.dockerignore excludes it) and
# configuration arrives via docker-compose's own `env_file:` mechanism
# instead. See config/env.py's docstring and
# docs/generated/PHASE-7-ENV-LOADING-FIX-REPORT.md for why this exists.
from config.env import load_env_file  # noqa: E402

load_env_file(BASE_DIR / '.env')


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'False') == 'True'

# SECURITY WARNING: keep the secret key used in production secret!
# Phase 12 (Security hardening) MUST-FIX #2 — docs/generated/PHASE-12-SECURITY-HARDENING-DESIGN-AUDIT-REPORT.md
# Section 3.4: previously this fell back to a hardcoded, well-known
# placeholder whenever DJANGO_SECRET_KEY was unset, in *any* environment,
# including production — silently running with a guessable key used for
# session signing/password-reset tokens/other Django-internal crypto,
# rather than refusing to start. Every other secret in this codebase
# (INTERNAL_SERVICE_KEY, OFFICE_DISPATCH_SERVICE_KEY, WAHA_API_KEY, ...)
# already fails closed on a missing value; this brings SECRET_KEY in line.
#
# `.get(..., '')` (not a truthy default) deliberately: Compose's env_file:
# mechanism sets an unset .env value to a literal empty string, not an
# absent key, so `os.environ.get(key, default)` would never even see the
# default in that case — checking truthiness below is what actually
# matters (docs/generated/PHASE-F-DEVELOPMENT-FINALIZATION-IMPLEMENTATION-REPORT.md's
# own documented gotcha, restated in infrastructure/development/.env.example).
#
# The insecure placeholder remains available, but ONLY for local dev
# (DEBUG=True) or this project's own SQLite test-settings module
# (config.settings_test, config/settings_test.py's own docstring: "NOT
# used in any deployed environment") — never for a real, non-DEBUG
# deployment. `manage.py test`'s default settings module (config.settings,
# unchanged) is unaffected by this exemption and continues to require a
# real value from infrastructure/development/.env, which already sets one.
_DJANGO_SECRET_KEY_ENV = os.environ.get('DJANGO_SECRET_KEY', '')
_USING_TEST_SETTINGS = os.environ.get('DJANGO_SETTINGS_MODULE', '') == 'config.settings_test'

if _DJANGO_SECRET_KEY_ENV:
    SECRET_KEY = _DJANGO_SECRET_KEY_ENV
elif DEBUG or _USING_TEST_SETTINGS:
    SECRET_KEY = 'django-insecure-dev-only-placeholder'
else:
    raise ImproperlyConfigured(
        'DJANGO_SECRET_KEY must be set when DEBUG=False. Refusing to start '
        'with an insecure placeholder secret key in a non-DEBUG deployment '
        '(see docs/06-SECURITY.md).'
    )

ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if h.strip()]

# CORS (django-cors-headers) — docs/generated/PHASE-7-CORS-FIX-REPORT.md.
# Only the exact origin(s) listed here get Access-Control-Allow-Origin;
# an unconfigured/unlisted origin gets none. Never a wildcard — the
# frontend calls this endpoint with real credentials (a login POST), and
# this project's own hard rule set forbids permissive-by-default
# security config. Empty by default (fails closed): no origin is
# permitted until one is explicitly configured, same posture as
# INTERNAL_SERVICE_KEY/ALLOWED_HOSTS above.
CORS_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',') if o.strip()]

# Bearer-token auth (the JWT in an Authorization header) never needs the
# browser to send cookies cross-origin, so credentialed CORS is not
# enabled — this project's frontend fetch() calls never set
# `credentials: 'include'` (confirmed: frontend/src/lib/api.ts). Leaving
# this False is the least-privilege choice, not an oversight.
CORS_ALLOW_CREDENTIALS = False


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'apps.core',
    'apps.waha_sessions',
    'apps.audit',
    'apps.chats',
    'apps.webhooks',
    'apps.sync',
    'apps.operations',
    'apps.blast',
    'apps.authn',
    'apps.dashboard',
    'corsheaders',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Must run before CommonMiddleware and as early as possible (django-cors-headers'
    # own placement guidance) — this is the fix for the Phase 7 login CORS
    # gap (docs/generated/PHASE-7-CORS-FIX-REPORT.md). Adds response
    # headers only for the origin(s) in CORS_ALLOWED_ORIGINS below; never a
    # wildcard.
    'corsheaders.middleware.CorsMiddleware',
    'apps.core.middleware.RequestIDMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases
#
# PostgreSQL is EXISTING infrastructure (see docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md).
# This project must never create a PostgreSQL container or use SQLite as the
# application database (see docs/CLAUDE.md hard rules).

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', ''),
        'USER': os.environ.get('DB_USER', ''),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', ''),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}


# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Celery (see docs/00-MASTER-SPEC.md — Office Docker: Celery worker/beat + Redis)
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')

# Minimal required configuration (docs don't specify values beyond
# provisioning Celery worker/beat + Redis — see docs/generated/PHASE-5-CELERY-REDIS.md
# "Celery configuration" for the reasoning behind each conservative default
# chosen here, since none of this is documented and none should be
# silently invented as if it were).
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']  # never pickle — avoids deserializing untrusted data
CELERY_TIMEZONE = TIME_ZONE  # matches Django's own TIME_ZONE ('UTC')
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 600  # hard kill after 10 minutes — conservative, bounded
CELERY_TASK_SOFT_TIME_LIMIT = 540  # allow 9 minutes for graceful cleanup first
# Preserves today's retry-on-startup behavior explicitly rather than
# silently changing when Celery 6.0 flips this default — observed as a
# live CPendingDeprecationWarning during Phase 5 live verification
# (docs/generated/PHASE-5-LIVE-VERIFICATION.md).
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# How often the periodic reconciliation task runs (apps/sync/tasks.py).
# Not specified anywhere in the docs — a conservative default, deliberately
# configurable rather than hardcoded. See docs/generated/PHASE-5-CELERY-REDIS.md.
RECONCILIATION_INTERVAL_SECONDS = int(os.environ.get('RECONCILIATION_INTERVAL_SECONDS', '900'))

# Targeted-reconciliation trigger executor —
# docs/generated/INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md.
# Selects HOW apps.sync.executors.trigger_reconciliation() runs a
# single-chat reconciliation right after a confirmed outbound send (this
# WAHA deployment sends no webhook for self-sent messages — see that
# report's root cause). Both values call the exact same
# apps.sync.reconciliation.reconcile_session(); this setting changes
# nothing about WHAT runs, only WHERE:
#   'sync'   — runs in-process, inside the same request that receives the
#              trigger. No Celery/Redis required — the correct value for
#              this project's current manual, single-process development
#              setup. DEFAULT.
#   'celery' — enqueues apps.sync.tasks.reconcile_chat_task onto the
#              already-provisioned Celery/Redis infrastructure (see the
#              CELERY_* settings above, provisioned for the periodic
#              reconciliation job) — the correct value for the Office
#              deployment, which already runs a Celery worker + Redis.
# Fails fast at startup for anything else: an unrecognized value is never
# silently treated as 'sync', since that could hide a real deployment
# misconfiguration (e.g. a typo meant to select 'celery' in production).
RECONCILIATION_EXECUTOR = os.environ.get('RECONCILIATION_EXECUTOR', 'sync')
if RECONCILIATION_EXECUTOR not in ('sync', 'celery'):
    raise ImproperlyConfigured(
        f'RECONCILIATION_EXECUTOR must be "sync" or "celery", got {RECONCILIATION_EXECUTOR!r}'
    )


# WAHA webhook authentication (docs/07-API-CONTRACT.md: "Webhook endpoint
# must validate, authenticate..."). See apps/webhooks/authentication.py for
# the verification logic and its documented, unverified assumptions.
WAHA_WEBHOOK_HMAC_SECRET = os.environ.get('WAHA_WEBHOOK_HMAC_SECRET', '')

# WAHA REST client (Phase 4 reconciliation — apps/sync/waha_client.py).
# Reuses the exact variable names already established for the BFF's own
# WAHA client (bff/.env.example) for consistency, rather than inventing new
# ones. The backend calling WAHA directly is new as of Phase 4 (Phase 3 was
# webhook-inbound only).
WAHA_BASE_URL = os.environ.get('WAHA_BASE_URL', '')
WAHA_API_KEY = os.environ.get('WAHA_API_KEY', '')


# JWT issuance (Phase 6 — docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md
# Section 4). Django holds the private key and is the sole issuer; the BFF
# verifies independently using only the public key (no live call back to
# Django per request — the entire point of this design, see the contract's
# Section 9 Availability boundary). RS256 chosen over ES256/HS256 per the
# contract's Section 4 reasoning (asymmetric so a BFF-side compromise alone
# cannot forge tokens).
#
# Keys are supplied as PEM content directly (JWT_PRIVATE_KEY /
# JWT_PUBLIC_KEY) or, if unset, read from a file path (JWT_PRIVATE_KEY_PATH /
# JWT_PUBLIC_KEY_PATH) — never hardcoded, never committed, same handling
# class as WAHA_API_KEY / WAHA_WEBHOOK_HMAC_SECRET above.


def _read_key(env_value_var, env_path_var):
    value = os.environ.get(env_value_var, '')
    if value:
        # Environment files commonly can't hold real newlines inside a
        # value; allow a literal "\n" to represent one.
        return value.replace('\\n', '\n')
    path = os.environ.get(env_path_var, '')
    if path:
        return Path(path).read_text()
    return ''


JWT_PRIVATE_KEY = _read_key('JWT_PRIVATE_KEY', 'JWT_PRIVATE_KEY_PATH')
JWT_PUBLIC_KEY = _read_key('JWT_PUBLIC_KEY', 'JWT_PUBLIC_KEY_PATH')
JWT_ALGORITHM = 'RS256'
JWT_KID = os.environ.get('JWT_KID', 'default')
JWT_ISSUER = os.environ.get('JWT_ISSUER', 'waha-monitoring-django')
JWT_AUDIENCE = os.environ.get('JWT_AUDIENCE', 'waha-monitoring-bff')
# 8 hours — docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 4:
# a single access token, no v1 refresh mechanism (approved default).
JWT_ACCESS_TOKEN_LIFETIME_SECONDS = int(os.environ.get('JWT_ACCESS_TOKEN_LIFETIME_SECONDS', str(8 * 60 * 60)))

# The authorization-scope vocabulary — docs/06-SECURITY.md's own category
# names verbatim, reused rather than inventing a parallel one (contract
# Section 4/5). A user's scopes are computed as: every one of these six
# names that also matches a Django Group the user belongs to, plus all six
# unconditionally if the user is a superuser. This mapping is an
# implementation detail (contract Section 5) — Django's Group model remains
# the system of record for *what* a user's scopes are.
JWT_SCOPES = [
    'reading',
    'sending',
    'session control',
    'blast',
    'user administration',
    'system administration',
]

# BFF -> Django internal-endpoint authentication (contract Section 8) — a
# static shared secret, distinct from end-user JWTs, authenticating the BFF
# *process* to Django for the two narrow internal endpoints (outbound-
# operation registration/resolution, audit-event writes). Same handling
# class as every other secret on this page: environment-only, never
# committed, empty by default so an unconfigured deployment fails closed
# rather than silently accepting unauthenticated internal calls.
INTERNAL_SERVICE_KEY = os.environ.get('INTERNAL_SERVICE_KEY', '')

# docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 9: the
# OutboundOperation staleness/retry-eligibility threshold — approved default.
OUTBOUND_OPERATION_STALE_SECONDS = int(os.environ.get('OUTBOUND_OPERATION_STALE_SECONDS', '30'))


# Phase 11 (Blast) — docs/generated/PHASE-11-BLAST-DESIGN-AUDIT-REPORT.md,
# docs/11-DECISIONS-AND-OPEN-QUESTIONS.md item 12, and this phase's
# finalized-decisions implementation prompt (overrides some of the design
# audit's own defaults — see apps/blast/limits.py's module docstring).
BLAST_MAX_RECIPIENTS_PER_CAMPAIGN = int(os.environ.get('BLAST_MAX_RECIPIENTS_PER_CAMPAIGN', '100'))
BLAST_MAX_RECIPIENTS_PER_SESSION_PER_DAY = int(os.environ.get('BLAST_MAX_RECIPIENTS_PER_SESSION_PER_DAY', '500'))
BLAST_INTER_MESSAGE_DELAY_SECONDS = int(os.environ.get('BLAST_INTER_MESSAGE_DELAY_SECONDS', '60'))

# Office/Celery -> Tencent/BFF internal dispatch call (finalized decision
# 1) — a NEW call direction, authenticated by a NEW, distinct shared
# secret from INTERNAL_SERVICE_KEY above (that one authenticates the
# OPPOSITE direction, BFF -> Django). Same fail-closed handling class as
# every other secret on this page: environment-only, never committed,
# empty by default. Must match OFFICE_DISPATCH_SERVICE_KEY on the BFF
# side (bff/.env.example).
OFFICE_DISPATCH_SERVICE_KEY = os.environ.get('OFFICE_DISPATCH_SERVICE_KEY', '')
# Reaches the BFF over the same NetBird/LAN link DJANGO_INTERNAL_BASE_URL
# (bff/.env.example) already uses in the opposite direction — see
# docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md.
BFF_INTERNAL_BASE_URL = os.environ.get('BFF_INTERNAL_BASE_URL', '')
BFF_INTERNAL_TIMEOUT_MS = int(os.environ.get('BFF_INTERNAL_TIMEOUT_MS', '10000'))


# Cache — Phase 12 (Security hardening) MUST-FIX #5: DRF's cache-backed
# request throttling (below) needs a real, shared cache backend, which this
# project did not previously configure at all (Django would otherwise fall
# back to its own process-local, per-worker LocMemCache default, which
# cannot correctly rate-limit across multiple gunicorn worker processes).
# Reuses the SAME Redis instance already provisioned for Celery above
# (CELERY_BROKER_URL/CELERY_RESULT_BACKEND) rather than standing up new
# infrastructure — this project's own hard rule against unnecessary new
# services. A different logical DB index (1, not Celery's 0) keeps cache
# keys and the Celery broker/result data from colliding in the same Redis
# instance. Uses Django's own built-in `django.core.cache.backends.redis.RedisCache`
# (available since Django 4.0 — this project runs 4.2) — no extra
# dependency (e.g. django-redis) needed.
DJANGO_CACHE_REDIS_URL = os.environ.get('DJANGO_CACHE_REDIS_URL', 'redis://redis:6379/1')
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': DJANGO_CACHE_REDIS_URL,
    }
}


# Django REST Framework
# docs/07-API-CONTRACT.md API principles: "JSON, consistent errors, request IDs, ...".
# Browsable API is dev-only; production responses are JSON-only.
REST_FRAMEWORK = {
    'DEFAULT_RENDERER_CLASSES': (
        ['rest_framework.renderers.JSONRenderer', 'rest_framework.renderers.BrowsableAPIRenderer']
        if DEBUG
        else ['rest_framework.renderers.JSONRenderer']
    ),
    'EXCEPTION_HANDLER': 'apps.core.exceptions.api_exception_handler',
    # Inbox/Chat (canonical Phase 8) — docs/generated/INBOX-CHAT-DECISION-REPORT.md
    # Section 5: the project's first paginated endpoints (chat list,
    # message history). No prior pagination convention existed to match,
    # so this is DRF's own standard, unmodified PageNumberPagination — the
    # smallest addition that satisfies docs/07-API-CONTRACT.md's own
    # stated "pagination" principle. Existing endpoints are all plain
    # APIView responses (never call .paginate_queryset()), so this has no
    # effect on them.
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    # Phase 12 (Security hardening) MUST-FIX #5 — docs/06-SECURITY.md "Rate
    # limits: login, send, session control, blast, expensive sync"; this
    # project had zero generic rate limiting anywhere outside Blast's own
    # domain-specific dispatch throttle (apps/blast/tasks.py, an unrelated
    # concept). DRF's own built-in throttling — no new dependency needed.
    # Project-wide default: every DRF view gets a general per-IP (anon) or
    # per-user throttle unless it overrides `throttle_classes` itself (as
    # `authn.LoginView` does, below, with a much stricter login-specific
    # rate — see apps/authn/throttling.py).
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        # Deliberately generous circuit-breaker defaults, not a tight
        # per-endpoint budget — this project's actual scale is a handful of
        # operators/sessions (docs/00-MASTER-SPEC.md) and several
        # machine-authenticated internal routes (webhooks, BFF/Celery
        # internal calls) that also fall under these same DRF-wide
        # defaults unless a view sets its own `throttle_classes` (as
        # `authn.LoginView` does). These exist to catch a genuine flood
        # (hundreds of requests/minute from one source), not to constrain
        # ordinary interactive use (e.g. InboxPage.tsx's own polling) or
        # this project's own test suite (~430 tests, comfortably under
        # either number even in the pessimistic case of every test
        # consuming one unit from the same shared anonymous/IP bucket).
        # The login-specific 'login' rate below is the actual tight,
        # brute-force-specific control the audit called for.
        'anon': '1000/minute',
        'user': '2000/minute',
        # Deliberately much stricter — the highest-severity gap the audit
        # identified (unauthenticated credential-guessing surface,
        # compounded by the fact login was previously unaudited and
        # unbounded-length too — MUST-FIX #3/#4). 5/minute per client IP
        # is enough for a legitimate user who mistypes a password a couple
        # of times, while making automated brute-force guessing
        # impractical. Login lockout (account-level) was explicitly
        # decided AGAINST for v1 — this rate limit is the sole control.
        'login': '5/minute',
    },
}


# Security headers / cookie hardening (docs/06-SECURITY.md).
# SECURE_SSL_REDIRECT / HSTS are intentionally not set here: the TLS
# termination point is still an open decision (docs/11-DECISIONS-AND-OPEN-QUESTIONS.md,
# "TLS/domain") and forcing them now could break deployments before that is
# decided. Revisit in the security-hardening / production-deployment phases.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True


# Logging (docs/06-SECURITY.md: log redaction — never log secrets/credentials).
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
    },
}
