# Phase 12 (Security Hardening) — Implementation Report

## 1. Objective

Close the 6 MUST-FIX findings from
`docs/generated/PHASE-12-SECURITY-HARDENING-DESIGN-AUDIT-REPORT.md`, per
the finalized user decisions (DRF built-in throttling + Redis cache
backend on Django, `express-rate-limit` on the BFF, a stricter scoped
login throttle, no account lockout, network-isolation doc note landed now
rather than deferred). The audit's OBSERVATION items (JWT rotation,
SSL/HSTS, BFF message-length bound) were explicitly out of scope and were
not touched. Blast (`apps/blast/`, `bff/src/routes/internalBlast.ts`,
`frontend/src/pages/Blast*.tsx`) and reconciliation/`possibly_stuck`/
`SyncCheckpoint` internals were explicitly out of scope and were not
touched, beyond the one permission-class line on `SyncStatusView` named by
MUST-FIX #1. No real WhatsApp message was sent and no live WAHA call was
made at any point in this task — all verification is Django/DRF
`APITestCase` and BFF `vitest`/`supertest` tests, run against SQLite
(backend test settings) or an in-process Express app (BFF), plus
`docker exec`-based `manage.py test`/`check`/`makemigrations` runs against
this project's real development containers (Postgres + Redis already
running, no live WAHA involved).

## 2. Fix-by-fix

### MUST-FIX #1 — Scope-gate `MessagesStatsView`/`ActivityFeedView`/`SyncStatusView`

**Found**: all three views used `permission_classes = [IsAuthenticated]`
only — any authenticated user, even one with zero assigned scopes, could
read message-volume stats, the merged `AuditLog`/`WebhookEvent` activity
feed, and per-session sync status. `apps.chats.*` already required
`HasReadingScope` for equivalent read-only data.

**Investigated before changing anything**: whether normal operators'
tokens actually carry the `'reading'` scope. Scopes are computed by
`apps.authn.jwt_utils.compute_scopes()` (`backend/apps/authn/jwt_utils.py:33-47`)
from Django Group membership named after each `settings.JWT_SCOPES` entry
(`backend/config/settings.py`), or unconditionally for a superuser. Since
`apps.chats.ChatListView`/`ChatMessagesView`/`ChatMarkReadView` already
require `HasReadingScope` (`backend/apps/chats/views.py:44,65` — pre-existing,
not touched this task) and the Inbox (`frontend/src/pages/InboxPage.tsx`)
already depends on it working for ordinary operators, any user who can use
the Inbox today already has `'reading'` scope. Gating Dashboard/SyncStatus
behind the same scope therefore does not newly require anything a working
Inbox user doesn't already have — confirmed, not assumed.

**Changed**:
- `backend/apps/dashboard/views.py:68` (`MessagesStatsView`) and `:122`
  (`ActivityFeedView`) — `permission_classes = [IsAuthenticated,
  HasReadingScope]`, `HasReadingScope` imported from `apps.authn.permissions`.
- `backend/apps/sync/views.py:169` (`SyncStatusView`) —
  `permission_classes = [IsAuthenticated, HasReadingScope]`.
  `SyncCheckpointRecoveryView`/`SyncCheckpointTaskStateView` (the same
  file) were **not** touched — they already require
  `HasSystemAdministrationScope`, out of this fix's scope.

**Tests added**:
- `backend/apps/dashboard/tests/test_views.py` —
  `test_authenticated_without_reading_scope_is_forbidden` on both
  `MessagesStatsViewTests` and `ActivityFeedViewTests` (403 for a
  no-scope user); the shared test-case `setUp` now grants the default
  `self.user` the `'reading'` Group so every pre-existing positive-path
  test keeps working unchanged.
- `backend/apps/sync/tests/test_views.py` — replaced
  `test_authenticated_request_succeeds_with_no_scope_required` (asserted
  the OLD, now-incorrect behavior) with
  `test_authenticated_without_reading_scope_is_forbidden` (403) and
  `test_authenticated_with_reading_scope_succeeds` (200); `_user()` now
  grants the `'reading'` Group (mirroring `apps.chats.test_views`'s
  `_reading_user()`), and every other test in `SyncStatusViewTests` (23
  tests) continues to use it unchanged, now implicitly proving the
  scope-gated path still returns correct data.

**Result: CLOSED.**

### MUST-FIX #2 — Fail-closed `DJANGO_SECRET_KEY`

**Found**: `SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY',
'django-insecure-dev-only-placeholder')` — silently ran with a
well-known, guessable key if the env var was unset, in any environment,
including a real deployment.

**Changed** (`backend/config/settings.py:29-67`, `DEBUG` moved above this
block so the check can read it):
```python
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
```
Checks truthiness, not mere presence — Compose's `env_file:` mechanism
sets an unset value to a literal empty string (a pre-existing, documented
gotcha, `infrastructure/development/.env.example:12-24`), so `.get(key,
default)` alone would never see the default in that case.

**Why this doesn't break dev/test/production**:
- Real dev (`infrastructure/development/.env`, gitignored, confirmed by
  reading it): `DJANGO_SECRET_KEY` is already set to a real value and
  `DJANGO_DEBUG=True` — both exempt it from the raise anyway.
  `infrastructure/development/.env.example` documents the same
  pre-filled placeholder for the same reason (comment at lines 12-24 of
  that file, pre-existing, not written by this task).
- Test settings (`config.settings_test`, SQLite): exempted explicitly via
  `_USING_TEST_SETTINGS` — `manage.py test`'s *default* settings module
  (`config.settings`, used by the real `docker exec ... manage.py test`
  run in this task's verification) is unaffected by this exemption and
  continues to require a real value, which
  `infrastructure/development/.env` already provides.
- Real production (`infrastructure/office/.env.example`): `DJANGO_DEBUG=False`,
  `DJANGO_SECRET_KEY=` (empty template, ops fills it in) — this is exactly
  the case the fix now refuses to start on, which is the point.

**Tests**: no new dedicated unit test was added for the `ImproperlyConfigured`
raise itself — it fires at Django settings-module import time, before any
test runner can construct an `APITestCase` against it, and this project's
existing test-settings module structurally can't exercise it (it's exempted
by design). Verified instead by direct inspection/reasoning above, and
indirectly by the fact the full test suite (`config.settings_test`) and
`manage.py check`/`makemigrations --check` (`config.settings`, real
`DJANGO_SECRET_KEY` set) both still pass — proving neither exempted path
regressed.

**Result: CLOSED.**

### MUST-FIX #3 — Audit-log `LoginView`

**Found**: `LoginView.post` never wrote an `AuditLog` row on either the
success or the failure path.

**Changed** (`backend/apps/authn/views.py`):
- `throttle_classes = [LoginRateThrottle]` (line 45, see MUST-FIX #5).
- `_audit_login(username, result, actor=None)` static method (lines
  90-106) calls `AuditLog.objects.create(actor=actor,
  action='auth.login', target=username, result=result)` — same shape as
  `apps.sync.views.SyncCheckpointRecoveryView`'s existing
  `AuditLog.objects.create(...)` call, called directly (not defensively
  wrapped), matching that precedent.
- Called on invalid credentials (line 63, `result=FAILURE`, `actor=None`
  — no Django user exists to attribute a failed attempt to), on
  `JwtNotConfigured` (line 80, `result=FAILURE` — the credential check
  succeeded but no usable token was ever issued), and on success (line
  86, `result=SUCCESS`, `actor=user`).
- **Never logs the password**: only `serializer.validated_data['username']`
  (the already-validated, length-bounded string) is ever passed to
  `_audit_login`; the raw request body/password is never touched again
  after the `authenticate()` call.

**Tests added** (`backend/apps/authn/tests/test_views.py`):
`test_successful_login_writes_a_success_audit_log`,
`test_failed_login_writes_a_failure_audit_log`,
`test_unknown_username_failure_is_still_audited`,
`test_audit_log_never_contains_the_password` (asserts the real password
string is absent from `target`, `action`, and `str(entry)` — i.e. every
field on the model, not just the obvious one).

**Result: CLOSED.**

### MUST-FIX #4 — Bound `LoginSerializer` field lengths

**Found**: `username`/`password` were unbounded `CharField()`s.

**Changed** (`backend/apps/authn/serializers.py:5-18`):
```python
USERNAME_MAX_LENGTH = 150  # matches django.contrib.auth.models.AbstractUser.username
PASSWORD_MAX_LENGTH = 128  # generous, common upper bound

class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=USERNAME_MAX_LENGTH)
    password = serializers.CharField(max_length=PASSWORD_MAX_LENGTH, trim_whitespace=False)
```
150 was confirmed against Django's actual `AbstractUser.username` field
definition (the real schema backing this project's `User` model), not
picked arbitrarily.

**Tests added**: `test_oversized_username_is_rejected_with_400_not_500`,
`test_oversized_password_is_rejected_with_400_not_500` (both assert a
clean 400 and zero `AuditLog` rows — rejected before any credential
check/audit write), `test_username_at_exactly_the_max_length_is_accepted_by_the_serializer`
(proves the boundary itself isn't what rejects a 150-char input — it
401s on the credential check instead, not the length validator).

**Result: CLOSED.**

### MUST-FIX #5 — Rate limiting (Django + BFF)

**Django/DRF** (`backend/config/settings.py`):
- **Cache backend wired up** (lines 369-388) — this project had **no**
  `CACHES` setting at all before this task (confirmed absent). Added
  Django's own built-in `django.core.cache.backends.redis.RedisCache`
  (no new dependency — available since Django 4.0, this project runs
  4.2), pointed at `DJANGO_CACHE_REDIS_URL` (env, default
  `redis://redis:6379/1` — the SAME Redis instance/service already
  provisioned for Celery, on logical DB index 1 instead of Celery's 0, to
  avoid key collisions). Documented in `backend/.env.example`,
  `infrastructure/development/.env.example`, `infrastructure/office/.env.example`,
  and set explicitly in the real (gitignored) `infrastructure/development/.env`.
- **General project-wide throttle** (lines 420-450):
  `DEFAULT_THROTTLE_CLASSES = [AnonRateThrottle, UserRateThrottle]`,
  `DEFAULT_THROTTLE_RATES = {'anon': '1000/minute', 'user': '2000/minute',
  'login': '5/minute'}`. The anon/user numbers are deliberately generous
  circuit-breakers rather than a tight per-endpoint budget — this
  project's real scale is a handful of operators (`docs/00-MASTER-SPEC.md`)
  plus several machine-authenticated internal routes (webhooks,
  BFF/Celery-internal calls) that also fall under these same DRF-wide
  defaults; a tight anon limit risked spurious 429s across this project's
  own ~430-test backend suite (many of which hit unauthenticated/internal
  endpoints sharing one IP-keyed bucket for the life of the test process)
  without adding meaningful real-world protection beyond what a
  much-higher ceiling already provides as a flood/DoS backstop.
- **Login-specific strict throttle** — new file
  `backend/apps/authn/throttling.py`: `LoginRateThrottle(AnonRateThrottle)`
  with `scope = 'login'` (IP-keyed, not username-keyed — an attacker
  rotating the claimed username must not bypass the limit). Set as
  `LoginView.throttle_classes = [LoginRateThrottle]` (`views.py:45`),
  which **replaces** (not adds to) the general anon/user default for this
  one view — 5/minute is already the binding constraint, so stacking the
  looser general throttle on top would add nothing. 5/minute chosen per
  the finalized decision's own suggested range (5-10/min), documented in
  `settings.py`'s inline comment.
- `backend/config/settings_test.py` — overrides `CACHES` to
  `LocMemCache` (lines 26-38): the real `CACHES` points at a live Redis
  instance matching the deployed/Docker environment, which a sandboxed
  `manage.py test` run under `config.settings_test` (this module's own
  documented purpose — SQLite, no Docker/Postgres/Redis access) cannot
  reach; `LocMemCache` keeps that test-settings module fully self-contained.

**BFF** (`bff/`):
- **New dependency**: `express-rate-limit@^7.5.1` (`bff/package.json`,
  `bff/package-lock.json`) — confirmed via `bff/package.json` that no
  equivalent existed already (only `cors`, `express`, `jsonwebtoken`).
  This is the one dependency-manifest change in this task, explicitly
  sanctioned by the task's own instructions.
- New `bff/src/middleware/rateLimit.ts` — `createApiRateLimiter()`, a
  per-IP limiter (`windowMs=60_000`, `limit=config.rateLimitMaxPerMinute`,
  default 300/minute, env `RATE_LIMIT_MAX_PER_MINUTE`), returning this
  project's own error envelope (`{error: {code: 'rate_limited',
  message}}`) on 429 rather than express-rate-limit's default plain-text
  body.
- `bff/src/app.ts` — mounted at `app.use('/api', createApiRateLimiter())`,
  before `sessionRouter`/`messagesRouter`, so it applies to every route
  under `/api` (`session.ts`, `messages.ts`) and runs before
  `requireAuth` (a flood is rejected regardless of whether it carries a
  valid token). **Deliberately not mounted on** `/health` (unauthenticated
  liveness probe, no WAHA-call surface, no abuse concern) or `/internal`
  (`internalBlastRouter` — already shared-secret-gated,
  Office/Celery-only, has its own separate, already-audited
  domain-specific dispatch throttling in `apps/blast`, explicitly out of
  this task's scope).
- `bff/src/config.ts` — added `rateLimitMaxPerMinute` (env
  `RATE_LIMIT_MAX_PER_MINUTE`, default 300).
- `bff/.env.example`, `infrastructure/tencent/.env.example` — documented
  the new variable.

**Tests added**:
- Django: `test_login_burst_beyond_the_configured_rate_returns_429` (5
  requests succeed/401, 6th is 429),
  `test_rate_limit_applies_per_ip_regardless_of_credentials_tried`
  (rotating the attempted username doesn't reset the counter),
  `test_throttled_response_does_not_write_an_audit_log` (a 429'd request
  never reaches `_audit_login` — DRF's throttle check runs in
  `initial()`, before the view's `post()` body). All three, plus every
  pre-existing `LoginViewTests`/`CorsPreflightTests`/`CorsUnconfiguredTests`
  test that hits `/api/auth/login/`, now start each test with
  `cache.clear()` in `setUp()` — the throttle's cache-backed history
  otherwise persists for the life of the test process, shared by test IP
  across every test method/class that calls the login endpoint.
- BFF: new `bff/test/rateLimit.test.ts` (5 tests) — allows requests up to
  the configured (test-mocked, small) limit; returns 429 with the correct
  error envelope once exceeded; the limiter is shared across different
  `/api` routes (not per-route); never blocks `/health`; never blocks
  `/internal`.

**Result: CLOSED** (both Django and BFF sides).

### MUST-FIX #6 — Document the BFF network-isolation reality project-wide

**Changed**: `docs/06-SECURITY.md`, new "Current BFF network-exposure
reality (Phase 12)" subsection under `## Network` — states plainly, for
every BFF route (not just Blast's internal dispatch endpoint): the
Tencent Compose file publishes `frontend`/`bff` ports with no interface
restriction; no NetBird/firewall configuration exists anywhere in-repo;
the BFF's only application-level defenses are JWT auth/scope checks
(frontend routes), the shared-secret check (Blast's internal route), and
(as of this task) the general per-IP rate limit; there is no in-repo
network-layer isolation backing any of it; NetBird/firewall rules remain
an explicit open item (`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`'s "Open"
list, cross-referenced by name) to be resolved at the infra/ops layer
before/during Phase 14. No firewall/NetBird configuration was actually
implemented — documentation only, per this task's own scope boundary.

**Result: CLOSED** (as a documentation fix — the underlying network
exposure itself remains open, by design, tracked in
`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`).

## 3. Test Results

### Targeted (new/modified tests for these 6 fixes)
All included in the full-suite runs below; individually re-confirmed
passing during development (see Section 2 per-fix breakdowns).

### Full backend suite
Run against the real development containers
(`infrastructure/development/office.yml`, Postgres + Redis already
running), using `config.settings_test` (SQLite) because the configured
`DB_USER` lacks `CREATEDB` on the real least-privilege Postgres role (a
pre-existing environment property, unrelated to this task — confirmed by
first attempting the real-Postgres path, which failed with "permission
denied to create database", then using the project's own documented
SQLite fallback):
```
docker exec -e DJANGO_SETTINGS_MODULE=config.settings_test development-backend-1 python manage.py test
```
**Before this task's changes**: not independently re-run on a clean
checkout (this task started from the working tree as-is); the audit
report and task prompt both cite 426 as the prior known-good baseline.
**After**: `Ran 439 tests in ~23s — OK` (0 failures, 0 errors). One
transient failure was found and fixed during development (a test bug in
`test_audit_log_never_contains_the_password` — it posted a password that
didn't match the test user's real one, so the login 401'd instead of
200'ing; fixed by using the correct password), not a product bug.

The 439 vs. 426 baseline includes both this task's new tests and any
tests added by other, already-committed work in this working tree prior
to this task starting (this task did not audit the delta down to the
single-test level against a hypothetical clean 426-test checkout — the
important fact is 439/439 pass with zero failures/errors after every
change in Section 2).

### `manage.py check`
```
docker exec development-backend-1 python manage.py check
System check identified no issues (0 silenced).
```
Run against the REAL settings module (`config.settings`, real Postgres +
Redis, real `DJANGO_SECRET_KEY` from `infrastructure/development/.env`,
`DEBUG=True`) — confirms the fail-closed `SECRET_KEY` logic and the new
`CACHES`/`RedisCache` config both load cleanly in the actual deployed-shape
environment, not just under the SQLite test settings.

### `manage.py makemigrations --check --dry-run`
```
docker exec development-backend-1 python manage.py makemigrations --check --dry-run
No changes detected
```
Confirms none of the 6 fixes required a migration (expected — no model
field was added/changed; `AuditLog`'s existing schema already covers the
login-audit fields used).

### BFF
```
npm run typecheck   -> clean (tsc --noEmit, no errors)
npm run build        -> clean (tsc -p tsconfig.json, no errors)
npm test              -> Test Files 13 passed (13); Tests 125 passed (125)
```
**Before**: 120 tests (task-stated baseline). **After**: 125 (120 + the 5
new `rateLimit.test.ts` tests). 0 failures.

## 4. `git diff --stat` (files touched by this task)

```
backend/.env.example                     |  +7
backend/apps/authn/serializers.py        | +16/-2
backend/apps/authn/tests/test_cors.py    | +15
backend/apps/authn/tests/test_views.py   | +102
backend/apps/authn/views.py              | +60/-6
backend/apps/authn/throttling.py         | new file
backend/apps/dashboard/tests/test_views.py | modified (setUp + 2 new tests)
backend/apps/dashboard/views.py          | +26/-2
backend/apps/sync/tests/test_views.py    | modified (helper + 2 tests replacing 1)
backend/apps/sync/views.py               | +24/-3   <- only SyncStatusView's permission line + docstring
backend/config/settings.py               | +105/-6
backend/config/settings_test.py          | +15
bff/.env.example                         |  +6
bff/package.json                         |  +1 dependency
bff/package-lock.json                    | lockfile update for the above
bff/src/app.ts                           |  +7
bff/src/config.ts                        | +10
bff/src/middleware/rateLimit.ts          | new file
bff/test/rateLimit.test.ts               | new file (5 tests)
docs/06-SECURITY.md                      | +28
infrastructure/development/.env.example  |  +6
infrastructure/office/.env.example       |  +6
infrastructure/tencent/.env.example      |  +6
infrastructure/development/.env          | +1 (gitignored, real dev env only)
```

**Confirmed NOT touched**: anything in `apps/blast/`,
`bff/src/routes/internalBlast.ts`, `frontend/src/pages/Blast*.tsx`;
`apps/sync/`'s reconciliation logic (only the one `SyncStatusView`
permission line + its docstring, as scoped); `apps/operations/`; any
Docker/Compose file; `frontend/` (no file under `frontend/` was touched —
the pre-existing `M` status on `frontend/src/pages/DashboardPage.tsx`/
`.css`/`SessionsPage.tsx`/`.css` and the various `docs/generated/*.md`
files visible in `git status` predate this task's session and were not
modified by it).

## 5. MUST-FIX closure summary

| # | Item | Status |
|---|---|---|
| 1 | Scope-gate Dashboard/SyncStatus views behind `HasReadingScope` | **CLOSED** |
| 2 | Fail-closed `DJANGO_SECRET_KEY` when `DEBUG=False` | **CLOSED** |
| 3 | Audit-log `LoginView` (success + failure) | **CLOSED** |
| 4 | Bound `LoginSerializer` field lengths | **CLOSED** |
| 5 | Rate limiting — Django (general + login-scoped) and BFF | **CLOSED** |
| 6 | Document BFF network-isolation reality project-wide | **CLOSED** (doc-only, per scope) |

## 6. OBSERVATION items — confirmed untouched

JWT key-rotation mechanism, `SECURE_SSL_REDIRECT`/HSTS activation, BFF
`messages.ts` text-length bound, `.gitignore`/committed-`.env`
re-verification, dependency-CVE audit — none of these were acted on. No
file under `frontend/src/lib/auth.ts`, no TLS/HSTS setting in
`backend/config/settings.py` (`SECURE_SSL_REDIRECT` was not touched —
confirmed by the diff in Section 4 showing only the `CACHES`/
`REST_FRAMEWORK`/`SECRET_KEY` regions of that file changed), and no
change to `bff/src/routes/messages.ts` were made.

## 7. Explicit confirmations

- **Blast/reconciliation untouched**: confirmed by `git status`/`git diff
  --stat` (Section 4) — zero files under `apps/blast/`,
  `bff/src/routes/internalBlast.ts`, `frontend/src/pages/Blast*.tsx`, or
  `apps/sync/`'s reconciliation/`possibly_stuck`/`SyncCheckpoint` logic
  were modified; `apps/sync/views.py`'s diff is exactly the one
  `SyncStatusView.permission_classes` line plus its docstring.
- **No real WhatsApp message or live WAHA call**: every test in this task
  runs against Django's `APITestCase` test client (SQLite in-memory DB,
  no network calls) or BFF's `vitest`/`supertest` in-process Express app
  with `global.fetch` stubbed/mocked (`vi.stubGlobal('fetch', fetchMock)`)
  — no test in this task's added/modified files makes a real HTTP call to
  a WAHA instance. The `docker exec` verification commands
  (`manage.py check`/`makemigrations`/`test`) run entirely against this
  project's own development Postgres/Redis containers; none invoke any
  WAHA-calling code path (login, dashboard, sync-status, and the new
  rate-limit/audit tests never call `apps.sync.waha_client`/`callWaha`).
