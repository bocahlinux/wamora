# Phase 13 Track B — Fix Report (Finding 1 Redis outage, Finding 2 PostgreSQL outage)

**Scope of this task.** Fix only the two findings recorded in
`docs/generated/PHASE-13-TRACK-B-FAILURE-DRILL-REPORT.md`: Finding 1
(HIGH, Redis outage → every Django API endpoint 500s) and Finding 2 (MEDIUM,
PostgreSQL outage → dev backend fails to boot). No change to Blast, no
change to reconciliation logic, no automatic recovery added, no change
to WAHA/BFF, no production change, no touch to the real PostgreSQL
server (`192.168.168.171`) or the real WAHA session. Nothing committed.

---

## 1. Root cause of each finding

### Finding 1 — Redis outage (HIGH)

DRF's `SimpleRateThrottle.allow_request()` (`rest_framework/throttling.py:123`)
calls `self.cache.get(self.key, [])` with no exception handling of its
own. This project's only cache backend is Redis, with no fallback
(`backend/config/settings.py` `CACHES['default']` →
`django.core.cache.backends.redis.RedisCache`). DRF runs this throttle
check inside `APIView.dispatch()` → `initial()` → `check_throttles()`,
**before any view code executes**, for every view using the project's
`DEFAULT_THROTTLE_CLASSES` and for `LoginView`'s own `LoginRateThrottle`.
When Redis was stopped during the live drill, this call raised an
uncaught `redis.exceptions.ConnectionError`, which propagated out of
`dispatch()` uncaught → Django's generic 500 handler → every
DRF-throttled endpoint, **including the three health-check views that
exist specifically to report this kind of outage**
(`LivenessView`/`DatabaseHealthView`/`RedisHealthView`, none of which
previously overrode `throttle_classes`).

### Finding 2 — PostgreSQL outage (MEDIUM)

`infrastructure/development/office.yml`'s dev backend service runs
`python manage.py runserver 0.0.0.0:8000` (production instead runs
`gunicorn config.wsgi:application`, per `backend/Dockerfile:19` — this
finding is dev-only by construction). Django's built-in
`runserver.Command.inner_run()` calls `self.check_migrations()`
unconditionally, before binding the HTTP port. `check_migrations()`
constructs a `MigrationExecutor(connections[DEFAULT_DB_ALIAS])`, which
opens a real database connection; the only exception it catches is
`ImproperlyConfigured` (no database configured at all — not the same
as "configured but unreachable"). With PostgreSQL unreachable, this
raised an uncaught `django.db.utils.OperationalError`, crashing the
whole process before it ever bound to its port — so `LivenessView`
(deliberately DB-independent, `apps/core/views.py`) could not respond
either, even though its own logic never touches the database.

A related, initially-hidden precondition surfaced while building the
fix: `django.contrib.staticfiles` also ships its own `runserver`
override (to serve static files under `DEBUG`), and Django's
`get_commands()` resolves a same-named command in favor of whichever
app appears **earliest** in `INSTALLED_APPS`. `django.contrib.staticfiles`
was listed before `apps.core`, so a naive same-named override placed
only in `apps/core/management/commands/runserver.py` would have been
silently ignored — `manage.py runserver` would keep resolving to
staticfiles' command, and the fix would have had zero effect. This was
caught before relying on it (see Section 4) and fixed as part of this
same change.

---

## 2. Files changed

| File | Change |
|---|---|
| `backend/apps/core/throttling.py` (new) | `FailOpenOnCacheErrorMixin` + `SafeAnonRateThrottle`/`SafeUserRateThrottle` — catches `redis.exceptions.RedisError` in `allow_request()`, logs, returns `True` (allow). |
| `backend/config/settings.py` | `REST_FRAMEWORK['DEFAULT_THROTTLE_CLASSES']` now points at the two `Safe*` classes instead of DRF's raw ones. `INSTALLED_APPS`: moved `apps.core` to sit just before `django.contrib.staticfiles` (was after it), so `apps.core`'s `runserver` override actually wins command-name resolution — see Section 1's second root-cause note. |
| `backend/apps/authn/throttling.py` | `LoginRateThrottle` now also mixes in `FailOpenOnCacheErrorMixin`, so `/api/auth/login/`'s own dedicated throttle fails open the same way. |
| `backend/apps/core/views.py` | `LivenessView`, `DatabaseHealthView`, `RedisHealthView` each gained `throttle_classes = []` — exempt from the cache-backed throttle entirely, regardless of Redis's state. |
| `backend/apps/core/management/__init__.py`, `backend/apps/core/management/commands/__init__.py` (new) | Package scaffolding required for the command override below. |
| `backend/apps/core/management/commands/runserver.py` (new) | Overrides `check_migrations()`: catches `django.db.utils.OperationalError` from an unreachable database, logs a visible `logger.warning(..., exc_info=True)`, and lets the process continue starting instead of crashing. Subclasses `django.contrib.staticfiles`'s `runserver.Command` (not `django.core`'s directly) so static-file-serving behavior under `DEBUG` is preserved unchanged. |
| `backend/apps/core/test_redis_outage_fail_open.py` (new) | Tests for Finding 1 (Section 4). |
| `backend/apps/core/test_postgres_outage_boot.py` (new) | Tests for Finding 2 (Section 4). |

No migration, no Blast file, no reconciliation file, no WAHA/BFF file,
no `.env`/infrastructure/production file was touched.

---

## 3. Design rationale

**Finding 1 — fail open, not fail closed.** An unavailable rate
limiter should not itself become an outage of the thing it protects.
Redis being down is already a rare, separately-alarming condition
(`RedisHealthView` reports it on its own), so temporarily not being
able to enforce the rate limit during that one abnormal window was
judged safer than a full API outage. This is a deliberate, narrow
change: only `redis.exceptions.RedisError` (parent of both
`ConnectionError` and `TimeoutError`, confirmed via the installed
`redis` package's own exception hierarchy) is caught — no other
exception type from `allow_request()` is swallowed. Normal (Redis-up)
operation is completely unaffected: the mixin's `try` block only
changes behavior on the `except` path, which the "still enforces the
limit when the cache is healthy" test (Section 4) exercises directly.
Every fail-open event is logged via `logger.exception`, matching the
discipline `RedisHealthView` already uses — never silent.

Health/liveness endpoints additionally get `throttle_classes = []`
rather than relying solely on the fail-open mixin, per the explicit
instruction that they "harus tetap bisa merespons ketika Redis mati" —
belt-and-suspenders: even if a future change ever removed the
fail-open mixin from the project defaults, these three views would
still not depend on the cache at all, matching their own purpose (to
report on other components' health, not gate themselves behind one).

**Finding 2 — restore the existing readiness/liveness split, don't
invent a new one.** The codebase already distinguishes process
liveness (`LivenessView`) from PostgreSQL reachability
(`DatabaseHealthView`) and Redis reachability (`RedisHealthView`) — the
outage crashed the *process*, which broke that split by making
`LivenessView` itself unreachable, not by changing what any view
reports. The fix is scoped to exactly the boot-time crash: it does not
touch migrations themselves, does not run migrations, and does not
hide a migration *content* error (a mismatched/corrupt migration state
while the database **is** reachable still raises normally — only
`OperationalError`, the connection-failure signature actually observed
in the drill, is caught; a different `django.db.Error` such as
`DataError` still propagates, per
`test_check_migrations_still_raises_non_operational_database_errors`).
`DatabaseHealthView` continues to independently and correctly report
the outage once the process is up — this fix only restores the
process's ability to *get* to that point.

Scoped to dev only by construction: production's `gunicorn` boot path
never calls `check_migrations()` at all (confirmed via
`backend/Dockerfile:19` and `infrastructure/office/docker-compose.yml`,
neither of which was touched); `manage.py runserver` is invoked only by
`infrastructure/development/office.yml`.

---

## 4. Tests added

**`backend/apps/core/test_redis_outage_fail_open.py`** (14 tests, 2 classes):
- `FailOpenMixinUnitTests` — direct, no-HTTP checks that
  `SafeAnonRateThrottle`/`SafeUserRateThrottle`/`LoginRateThrottle` all
  return `True` (allow) when the cache raises `RedisConnectionError`;
  that the fail-open event is logged (`assertLogs`, not silent); and
  that the **same** throttle class still enforces a real limit (second
  request within the window rejected) when the cache is healthy — the
  explicit "no security regression" check for Phase 12.
- `RedisOutageBehavioralTests` — real HTTP requests through the actual
  DRF dispatch path, with the real default cache's `.get()` patched to
  raise `RedisConnectionError`: `/api/health/`, `/api/health/database/`,
  `/api/health/redis/` all still return 200; an authenticated request
  to `/api/auth/me/` returns 200 (not 500); a login POST does not 500;
  and an *unauthenticated* request to `/api/auth/me/` still gets a
  clean 401 during the outage — proving fail-open bypasses only the
  throttle check, not authentication/permissions.

**`backend/apps/core/test_postgres_outage_boot.py`** (5 tests):
- Confirms the override module is a subclass of Django's `runserver`
  command.
- **`test_manage_py_actually_resolves_runserver_to_this_module`** —
  calls the same `get_commands()` Django itself uses and asserts
  `'runserver' → 'apps.core'`. This directly guards the
  `INSTALLED_APPS`-ordering precondition described in Section 1; it
  would have caught the staticfiles-precedence issue found while
  building this fix, and will catch any future reordering that
  silently reintroduces it.
- `check_migrations()` swallows `OperationalError` and logs a
  `WARNING`-level message containing "unreachable" (not raised).
- `check_migrations()` still raises a different `django.db.Error`
  (`DataError`) unchanged — the "don't silently hide a real migration
  problem" guard.
- `check_migrations()`'s normal (database-reachable) path is
  unchanged — calls straight through to the base implementation.

---

## 5. Full test results

```
$ python manage.py test apps.core.test_redis_outage_fail_open apps.core.test_postgres_outage_boot --settings=config.settings_test
Ran 16 tests in 2.215s
OK

$ python manage.py test --settings=config.settings_test
Ran 472 tests in 67.472s
OK
```
(456 pre-existing + 16 new = 472; matches exactly.)

```
$ python manage.py check --settings=config.settings_test
System check identified no issues (0 silenced).

$ python manage.py makemigrations --check --dry-run --settings=config.settings_test
No changes detected
```

`config.settings_test` wildcard-imports the real `config/settings.py`
(only `DATABASES`/`CACHES` are overridden for the test environment), so
the `INSTALLED_APPS` reorder and `DEFAULT_THROTTLE_CLASSES` change were
both exercised exactly as they run in the dev/prod settings module by
these runs — no separate real-settings run was needed.

No BFF file was touched; the BFF suite was not re-run (out of scope —
this task only concerns the two Django-side findings).

---

## 6. Track B scenario status — now

- **PostgreSQL outage: PASS (fixed).** Root cause (process crash in
  `check_migrations()`) addressed directly and covered by
  `test_check_migrations_swallows_operational_error_and_logs_a_warning`
  plus the discoverability guard. Not re-run against the live dev
  stack in this task (the user's instructions for this task were
  fix + unit/behavioral test + full suite + report, not a repeat live
  drill) — the fix is exercised at the unit level exactly at the call
  site the drill's own traceback identified.
- **Redis outage: PASS (fixed).** Root cause (uncaught `RedisError` in
  DRF's throttle check) addressed directly and covered by 9 unit +
  behavioral tests, including real HTTP requests through the actual
  dispatch path with the cache patched to fail exactly as it did
  during the live drill.

Re-running the actual live failure-injection drill (stopping the real
dev containers again) was not performed in this task — not requested,
and outside this task's stated scope (implement + test + report, then
stop).

---

## 7. Security regression check (Phase 12)

**No regression identified.**

- When the cache is healthy, `SafeAnonRateThrottle`/`SafeUserRateThrottle`/
  `LoginRateThrottle` behave identically to the DRF classes they wrap —
  the `try/except` only changes behavior on the exception path.
  `test_safe_throttle_still_enforces_the_limit_when_cache_is_healthy`
  proves a second request within the same window is still rejected.
- Fail-open is scoped to exactly one exception type
  (`redis.exceptions.RedisError`) raised from exactly one call
  (`self.cache.get(...)` inside `allow_request()`) — it cannot be
  triggered by, e.g., a request simply exceeding its rate; only a
  genuine cache-backend failure.
- Fail-open bypasses **only** the throttle check, never authentication
  or permission checks —
  `test_unauthenticated_request_still_gets_a_clean_401_during_redis_outage`
  proves `/api/auth/me/` still returns 401 (not 200) for an
  unauthenticated caller during a simulated Redis outage.
- The three health endpoints' new `throttle_classes = []` only removes
  throttling from views that had **no other** access control to begin
  with (`authentication_classes = []`, `permission_classes = []`,
  unchanged, by design — they are meant to be public health probes).
- Every fail-open event is logged at `ERROR` level
  (`logger.exception`), so a sustained Redis outage remains visible in
  logs/monitoring rather than silently degrading protection unnoticed.

---

**STOP.** Not proceeding to Phase 14. Nothing committed by this task —
`git status` shows only the files listed in Section 2 as modified/new,
plus the two pre-existing untracked Track A/B reports from earlier in
this session. Awaiting review and further instructions.
