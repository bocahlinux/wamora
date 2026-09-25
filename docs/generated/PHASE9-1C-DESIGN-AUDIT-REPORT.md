# Phase 9.1C — Redis Health Endpoint — Design Audit (Read-Only)

**Scope.** Design/read-only audit only. No source, `.env`, configuration,
database, migration, Docker, or WAHA/Redis state was modified. No endpoint
was called live. No WhatsApp message was sent. No Celery task was
triggered. All claims below were verified directly against current source
this task, not carried over from any prior report without re-verification
— though one prior report (`docs/generated/PHASE9-1-DESIGN-AUDIT-REPORT.md`
Section 6.B) already proposed the same endpoint shape independently; this
audit re-derives it from source rather than assuming that report is still
accurate, and the two happen to agree.

---

## 1. Current Architecture (Existing Health-Check Infrastructure)

**`backend/apps/core/views.py`** — the sole home of infra-probe health
checks in this codebase:

```python
class LivenessView(APIView):
    authentication_classes = []
    permission_classes = []
    def get(self, request):
        return Response({'status': 'ok', 'component': 'backend'})

class DatabaseHealthView(APIView):
    authentication_classes = []
    permission_classes = []
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
        except Exception:
            logger.exception('Database health check failed')
            return Response({'status': 'error', 'component': 'database'},
                             status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({'status': 'ok', 'component': 'database'})
```

Registered in `backend/apps/core/urls.py`:

```python
urlpatterns = [
    path('health/', LivenessView.as_view(), name='health-liveness'),
    path('health/database/', DatabaseHealthView.as_view(), name='health-database'),
]
```

**No other health/status view exists anywhere in `backend/`.** `apps/sync/views.py`
(`SyncStatusView`, Phase 9.1A) is a *derived-state* endpoint (reads
`SyncCheckpoint`, a stored model), not a live infra probe — a materially
different category from `LivenessView`/`DatabaseHealthView`, which perform
a live check against the dependency itself at request time. `apps/dashboard/views.py`
has no infra-check views at all — its `HealthCard`-feeding queries
(`wahaQuery`/`backendQuery`/`databaseQuery` in `DashboardPage.tsx`) are
frontend-side wrappers around the exact same three backend calls
(`getBackendHealth()`, `getDatabaseHealth()`, and a BFF `/health` call),
not separate backend views.

**No reusable health-check helper/utility exists** — `LivenessView` and
`DatabaseHealthView` each inline their own check directly in `get()`. There
is no shared base class or decorator to reuse; **this audit does not
propose creating one for a single additional two-view pattern** (would be
a premature abstraction for a category that has exactly two, soon three,
members, each a few lines).

**`bff/src/routes/health.ts`** — a *separate*, Tencent-side health
endpoint, unauthenticated, reporting `{status: 'ok', service: 'bff', waha: {reachable: bool}}`.
It has **no Redis awareness and needs none** — Redis is Office-side
infrastructure (`docs/00-MASTER-SPEC.md`: "Office Docker: Celery
worker/beat + Redis"); the BFF process has no network path to it and no
`.env` variable referencing it (confirmed: no `REDIS`/`redis` string
anywhere under `bff/`). This is architectural, not an oversight — BFF
health already deliberately separates "BFF process alive" from "WAHA
reachable" (its own file-header comment says so); a third, Office-side
concern has no place in a Tencent-side process.

**Frontend consumption today** (`frontend/src/lib/djangoApi.ts`):
`getBackendHealth()` and `getDatabaseHealth()` both call Django
**directly** (Frontend → Django, no BFF hop), unauthenticated, and are
consumed by `DashboardPage.tsx`'s `HealthCard` via a
`useApiQuery(..., [])` fetch-once-on-mount wrapper — no polling on any of
the three existing Dashboard health cards.

---

## 2. Redis Connection Architecture (Current Use)

Verified directly, not assumed:

- **`redis==5.0.8`** is a direct entry in `backend/requirements.txt` — not
  a transitive-only dependency, confirmed present and pinned.
- **Only one Redis role exists in this codebase today: Celery broker +
  result backend.** `backend/config/settings.py:179-180`:
  ```python
  CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
  CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
  ```
- **No `CACHES` setting exists anywhere** (grepped full `settings.py` and
  the whole `backend/` tree) — Django's cache framework is not configured
  to use Redis (or anything else); there is no `django_redis` dependency,
  no `django.core.cache` usage found. Redis is **not** used as a session
  store, cache layer, or for any purpose beyond Celery's own
  broker/result-backend role.
- **No direct `redis`-package usage exists anywhere in `backend/` today**
  (grepped for `import redis`, `redis.Redis`, `from redis` — zero matches
  outside the dependency declaration itself). Celery's own internal
  transport code uses `redis` under the hood, but no application code in
  this repo constructs a `redis.Redis` client directly yet — **this slice
  would be the first.**
- **No separate `REDIS_URL` environment variable exists.** `.env.example`
  only defines `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`
  (`backend/.env.example:24-26`). `CELERY_BROKER_URL` is therefore the
  single source of truth for "where is Redis" in this codebase — reusing
  it (rather than inventing a new `REDIS_URL` variable) avoids a second
  variable that could silently drift from the one Celery actually connects
  to.
- **`backend/config/celery.py`** configures the Celery app via
  `app.config_from_object('django.conf:settings', namespace='CELERY')` —
  it does not expose a ready-made "ping the broker" call any more direct
  than what `redis-py` itself offers; **the project has no existing
  "official" Redis ping mechanism to reuse**, so this audit selects
  `redis-py`'s own `.ping()` (its canonical, library-documented
  health-check method) as the correct primitive — not a hand-rolled
  socket check, and not a Celery-level `control.ping()` (Section 15 — that
  checks worker liveness, a different and explicitly out-of-scope
  concern).

**Conclusion**: Redis health for this slice means "can a `redis-py` client
constructed from `settings.CELERY_BROKER_URL` complete a `PING`" — nothing
about Django's own runtime depends on Redis today (no cache, no sessions),
so this check is purely infrastructural/advance-warning in nature, exactly
mirroring what `DatabaseHealthView` already is for PostgreSQL.

---

## 3. Proposed Endpoint

**Owner: `apps/core`**, not `apps/sync` or `apps/dashboard`. Reasoning,
derived from precedent and ownership (per the task's explicit instruction
to decide by precedent, not preference):

- `apps/core` already owns exactly this category of view — live,
  stateless, dependency-reachability probes with no relationship to any
  Django model (`LivenessView`, `DatabaseHealthView`). A Redis probe is
  the same category: no model, no business logic, pure connectivity check.
- `apps/sync` owns `SyncCheckpoint`-derived state (Phase 9.1A) — a
  fundamentally different kind of endpoint (reads stored data about past
  reconciliation runs, doesn't perform a live check at request time).
  Putting a live Redis probe there would blur a distinction Section 14 of
  this audit (and the 9.1A/9.1E reports before it) is specifically careful
  to preserve.
- `apps/dashboard` has no infra-probe views at all today — its role is
  aggregation (`DashboardMessages`, `DashboardActivity`), not
  reachability checks. Adding one there would create a second home for
  the same category of thing `apps/core` already owns.

**Route**: `GET /api/health/redis/`, added to `backend/apps/core/urls.py`
directly beneath the existing two:

```python
urlpatterns = [
    path('health/', LivenessView.as_view(), name='health-liveness'),
    path('health/database/', DatabaseHealthView.as_view(), name='health-database'),
    path('health/redis/', RedisHealthView.as_view(), name='health-redis'),
]
```

This exact path (`/api/health/redis/`) was also independently proposed in
the prior `PHASE9-1-DESIGN-AUDIT-REPORT.md` (Section 6.B) — re-derived
here from source, not copied, and found to agree.

---

## 4. Proposed Auth

**Unauthenticated** — `authentication_classes = []`, `permission_classes = []`,
identical to `LivenessView`/`DatabaseHealthView`.

**Derived from precedent, not invented**: both existing health probes in
this codebase are deliberately unauthenticated infra checks. A third probe
in the same category, returning the same minimal `{status, component}`
shape with no PII and no secret material (Section 5), has no principled
reason to diverge from that established pattern — introducing auth here
alone would create an inconsistent trio for no stated reason, and there is
no precedent anywhere in this codebase for an authenticated *infra-liveness*
endpoint (JWT auth in this project is reserved for endpoints that return
or act on actual application/business data — chats, messages, sync
status, dashboard stats — a different category, per `apps/authn/permissions.py`'s
`HasReadingScope` being scoped specifically to chat content, not
infrastructure probes).

---

## 5. Proposed Response Contract

Mirrors `DatabaseHealthView` exactly — same shape, same status codes, same
"don't raise through the global exception handler" pattern:

**Healthy:**
```json
{"status": "ok", "component": "redis"}
```
`HTTP 200`.

**Unavailable (any failure — see Section 13 for why these are not split):**
```json
{"status": "error", "component": "redis"}
```
`HTTP 503 Service Unavailable`.

**Not using the global `{error: {code, message, request_id}}` envelope**
(`apps/core/exceptions.py`) — deliberately, matching `DatabaseHealthView`'s
own existing precedent: that envelope is produced by
`api_exception_handler` when a DRF exception *propagates*; both existing
health views instead **catch** their failure internally and hand back a
small, deliberately-shaped body, sidestepping the general envelope
entirely. This is an established, tested exception to the general
convention for this one narrow view category — not a new inconsistency
introduced by this slice.

**No secret, URL, host, port, credential, or raw exception text is ever
included** — the response body contains only the two fixed string fields
above, in both the success and failure case. (Section 12 covers this in
detail.)

---

## 6. Timeout / Failure Behavior

**Requirement**: the check must not hang when Redis is down.

**No existing Redis timeout configuration exists anywhere in this
codebase to reuse** (Section 2 — Redis has never been touched directly by
application code before this slice), unlike `DatabaseHealthView`, which
implicitly relies on Django's already-established DB connection (typically
already open by the time a request is handled, so `SELECT 1` returns
near-instantly even in the slow case, and Django's own `CONN_MAX_AGE`/driver
defaults govern the rest — nothing this project has ever needed to bound
explicitly).

Redis is different: **no persistent connection is held anywhere in the
Django process today** (no cache backend, no session store using it), so
every call to this endpoint would construct a fresh `redis-py` client and
attempt a **new** TCP connection each time. Without an explicit bound,
`redis-py`'s default `socket_connect_timeout`/`socket_timeout` are `None`
(no timeout — blocks on the OS-level TCP stack, which can take a long time
against an unreachable host). This audit therefore proposes a bounded,
hardcoded value — a genuinely new constant, documented and justified per
the task's own instruction (item 6), not silently invented:

```python
REDIS_HEALTH_TIMEOUT_SECONDS = 2
```

**Reasoning for `2`**: short enough that a hung Redis doesn't make the
health endpoint itself a slow/hanging dependency for whatever calls it
(Dashboard's fetch-once-on-mount pattern, Section 1), long enough not to
false-positive on ordinary network jitter to a Docker-internal
`redis:6379` hostname. Applied to both `socket_connect_timeout` and
`socket_timeout` (covers both "can't open the TCP connection" and "opened
but didn't respond to `PING` in time"). This mirrors the same
"conservative, documented, environment-configurable-if-ever-needed"
posture the project already used for `RECONCILIATION_INTERVAL_SECONDS`
(`settings.py:203`) and `STALE_THRESHOLD_MULTIPLIER`
(`apps/sync/views.py`, Phase 9.1A) — precedent for *how* to introduce a
new constant, not for the specific value, which has no prior art in this
codebase to mirror.

**Not proposed as a new environment variable** — matching the Phase 9.1A
precedent of `STALE_THRESHOLD_MULTIPLIER` (a hardcoded module constant,
not `.env`-configurable), since this is an internal safety bound with no
stated operational requirement to be tunable per-deployment, not a
business-meaningful threshold like `RECONCILIATION_INTERVAL_SECONDS`.

---

## 7. Side Effects

Confirmed the proposed check has none of the following:

- **No Celery task created** — `redis-py`'s `.ping()` is a raw Redis
  `PING` command; it does not go through Celery's task-publishing code
  path at all (no `.delay()`, no `app.send_task()`, nothing that touches
  a queue).
- **No reconciliation triggered** — `reconcile_session()`/`reconcile_all_sessions_task`
  are not referenced, imported, or called anywhere in this proposal.
- **No database write** — no model is touched; this view does not import
  anything from `apps.sync.models` or any other model module.
- **No permanent Redis state change** — `PING` is a read-only Redis
  command by definition; no `SET`/`DEL`/queue manipulation of any kind.
- **No WAHA interaction** — no import of `wahaClient`-equivalent code (this
  is backend-only; WAHA calls happen in the BFF, a separate process this
  slice doesn't touch).

---

## 8. Testability

**No live Redis required for unit tests** — mirrors `DatabaseHealthViewTests`'s
own mocking pattern exactly (`apps/core/tests.py:24-48`, which mocks
`apps.core.views.connection` rather than requiring a real PostgreSQL
instance). The equivalent here: patch the `redis.Redis.from_url` call (or
a small module-level helper wrapping it) inside `apps.core.views`.

Proposed test cases (added to the existing `apps/core/tests.py`, same
file, same `SimpleTestCase` style — no new test infrastructure needed):

1. **Reachable**: mock the client's `.ping()` to return `True` → assert
   `200`, `{'status': 'ok', 'component': 'redis'}`.
2. **Unavailable (connection refused)**: mock `.ping()` to raise
   `redis.exceptions.ConnectionError` → assert `503`,
   `{'status': 'error', 'component': 'redis'}`.
3. **Timeout**: mock `.ping()` to raise `redis.exceptions.TimeoutError` →
   assert the same `503` body as case 2 (Section 13 — deliberately not
   distinguished in the response).
4. **No secret leakage**: construct the mocked exception with a message
   containing a fake credential/hostname string (mirroring
   `DatabaseHealthViewTests.test_database_health_error_does_not_leak_driver_details`
   exactly) → assert the fake string is absent from `response.data`.
5. **`REDIS_HEALTH_TIMEOUT_SECONDS` is actually passed** to the client
   constructor — assert the mock was called with the expected
   `socket_connect_timeout`/`socket_timeout` kwargs, so the timeout
   constant doesn't silently rot unused.

`settings_test.py` needs **no change** — it only overrides `DATABASES`;
Redis was never part of Django's settings-level test configuration and
doesn't need to be, since the view is fully mockable without touching
`CELERY_BROKER_URL`'s real value at all.

---

## 9. Frontend / BFF Boundary

**Per this task's explicit scope, no frontend change is proposed or made
in this slice.** Recorded here only as the contract a future slice would
consume:

- **Frontend reads Django directly** (Frontend → Django), matching
  `getBackendHealth()`/`getDatabaseHealth()` exactly — a future
  `getRedisHealth()` in `frontend/src/lib/djangoApi.ts` would call
  `GET /api/health/redis/` directly, no auth header, same `ComponentHealth`
  interface already defined and reused (`{status: string, component: string}`
  — **no new frontend type needed**, the existing `ComponentHealth`
  interface already matches this shape exactly).
- **No BFF involvement** — confirmed in Section 1: the BFF has no network
  path to Office-side Redis and no existing Redis awareness; routing this
  through the BFF would require adding a new cross-boundary proxy hop for
  a check Django can already answer directly, which the task's own
  instruction explicitly warns against ("Jangan menambahkan proxy layer
  hanya karena bisa").
- **Frontend integration (consuming this endpoint from `DashboardPage.tsx`,
  i.e. the previously-identified 9.1F) is correctly a separate,
  independent slice** — already named as such in
  `docs/generated/PHASE9-NEXT-SLICES-DESIGN-AUDIT-REPORT.md` Section 6,
  which additionally found `HealthCard`'s existing `{ok: boolean, detail: string}`
  prop shape already fits a `ComponentHealth`-style two-value response
  cleanly (this is the *simpler* of the two integration shapes that report
  discussed — the boolean-vs-enum friction identified there was specific
  to `SyncStatus`'s five-value enum, which does not apply to this
  endpoint's plain `ok`/`error` shape).

---

## 10. Celery Boundary (Explicit)

Restated per the task's explicit instruction, as a hard boundary for this
slice specifically:

- **This check performs exactly one operation**: `redis-py`'s `.ping()`
  against `settings.CELERY_BROKER_URL`. Nothing else.
- **It does not call `celery_app.control.ping()`, `.inspect().active()`,
  `.inspect().stats()`, or any other Celery-native worker-inspection API.**
- **It does not infer, imply, or document that a reachable Redis means a
  Celery worker is alive.** The response body's `component: 'redis'`
  label is deliberately literal — it makes no claim about Celery at all,
  worker or otherwise.
- **The distinction between "Redis down" and "Redis up, worker dead"
  remains exactly as unresolved as it was in every prior Phase 9 report**
  (`PHASE9-NEXT-SLICES-DESIGN-AUDIT-REPORT.md` Section 10) — this slice
  narrows the four-state boundary table there by exactly one row (Redis
  reachability itself), and no further.

---

## 11. Security Considerations

- **No credential, host, port, or raw connection string is ever included
  in the response body**, in either the success or failure case — the
  response is always exactly one of the two fixed two-field bodies in
  Section 5.
- **No raw exception text reaches the client** — every failure path is
  caught by a single `except Exception`, logged server-side via
  `logger.exception(...)` (same as `DatabaseHealthView`), and converted to
  the fixed `{'status': 'error', 'component': 'redis'}` body — mirroring
  `DatabaseHealthViewTests.test_database_health_error_does_not_leak_driver_details`'s
  already-proven pattern (Section 8, test case 4) for the exact same
  class of risk (a Redis connection string can carry a password, just as
  the Postgres one already does).
- **Unauthenticated is not an information-disclosure risk here** — the
  response reveals only "is the configured Redis reachable," a binary
  operational fact with no PII, no business data, and no more sensitive
  than `DatabaseHealthView`'s already-shipped, already-unauthenticated
  equivalent for PostgreSQL.
- **No new attack surface for triggering side effects** — Section 7
  already confirms the check is read-only and cannot be used to enqueue
  tasks, write data, or mutate Redis state; an unauthenticated caller can
  therefore only ever learn the single fact above, repeatedly, at whatever
  rate they choose (the same exposure profile the two existing
  unauthenticated health endpoints already have — not a new category of
  risk introduced by this slice).

---

## 12. Failure Semantics (Taxonomy Decision)

Per the task's explicit question: **do "unavailable," "misconfigured," and
"timeout" collapse into one `error` status, or get distinguished?**

**Decision: collapse all three into the single existing `{'status': 'error', 'component': 'redis'}` shape — no internal sub-code.**

Derived directly from precedent, not chosen for convenience alone:
`DatabaseHealthView` already establishes the only failure-taxonomy
precedent this codebase has for infra-probe endpoints, and it uses a
single broad `except Exception` with a single undifferentiated `'error'`
status — no distinction between "wrong credentials," "host unreachable,"
"query timeout," or any other PostgreSQL failure mode. Introducing a
richer taxonomy for Redis alone, when the sibling endpoint one file above
it doesn't have one, would create an inconsistency in this specific
2-then-3-member endpoint family without a concrete stated consumer need
for the distinction (no UI in this project currently branches on *why*
a health check failed — every existing consumer, `HealthCard`, only
branches on `ok`/`error`).

Distinguishing sub-cases (`ConnectionError` vs. `TimeoutError` vs. a
malformed `CELERY_BROKER_URL` raising synchronously at `from_url()`) is
still useful **server-side**, in logs — the proposed `logger.exception(...)`
call already captures the real exception type/message for an operator
reading logs, so no diagnostic information is lost, only excluded from the
public API response.

---

## 13. Relationship to Phase 9.1A / 9.1E

**No change to `apps/sync/views.py`, `SyncStatusView`, or its response
shape.** Confirmed by design, not merely by omission:

- `sync_status` (`healthy`/`stale`/`running`/`failed`/`never_synced`)
  remains derived exclusively from `SyncCheckpoint`, exactly as Phase 9.1A
  implemented it — this slice adds no new field to that response and
  reads no `SyncCheckpoint` data at all.
- The frontend's `mapSyncStatus()`/`SYNC_STATUS_LABEL` (Phase 9.1E,
  `InboxPage.tsx`) are untouched by this design — Redis health has no
  proposed presence in `InboxPage.tsx` at all, only (in a future,
  separate slice) `DashboardPage.tsx`.
- The connectivity indicator (`reportPollOutcome`, Phase 9.1D) is
  similarly untouched — it reacts to `ApiError.kind` from Inbox's own
  polling loop and has no relationship to a Redis health check on a
  different page.

**This preserves the "derived state, never invented signal" and
"independent, non-overlapping signals" discipline** established across
every prior Phase 9 slice: Redis health becomes a *third* independent
signal (alongside Signal A/connectivity and Signal B/sync health), not a
new input folded into either of the first two.

---

## 14. Files Expected to Change During Implementation

(Backend only — no frontend change proposed in this slice, per Section 9.)

- **`backend/apps/core/views.py`** — add `RedisHealthView` class (and the
  `REDIS_HEALTH_TIMEOUT_SECONDS` constant), following `DatabaseHealthView`'s
  exact structure; add `import redis` at the top.
- **`backend/apps/core/urls.py`** — one new `path(...)` line, one updated
  import line.
- **`backend/apps/core/tests.py`** — new `RedisHealthViewTests` class,
  same file, same `SimpleTestCase`/`mock.patch` style as the existing two
  test classes (Section 8).

**No other file requires a change**: no migration (no model involved), no
`settings.py` change (reuses `CELERY_BROKER_URL` as-is), no `.env.example`
change (no new variable), no `requirements.txt` change (`redis==5.0.8`
already present), no `apps/sync/*` change, no frontend file, no BFF file,
no Docker/infrastructure file.

---

## 15. Dependencies

- **No dependency on any other unimplemented Phase 9 slice** — this
  endpoint can be implemented and tested entirely standalone.
- **9.1F (Dashboard Redis card, per the prior audit's naming) depends on
  this slice** — the one hard dependency identified in
  `PHASE9-NEXT-SLICES-DESIGN-AUDIT-REPORT.md` Section 12, reconfirmed
  unchanged here.
- **No dependency on Celery worker liveness detection** — explicitly
  independent per Section 10.
- **No dependency on any pending user decision from prior reports** (the
  `RECONCILIATION_EXECUTOR` production-value question, the stuck-`running`
  design, etc.) — none of those affect this endpoint's design or
  implementation.

---

## 16. Risks

- **Very low regression risk** — purely additive: one new file-internal
  class, one new URL line, no existing endpoint's behavior, response
  shape, or status code changes.
- **Timeout-value risk (Section 6)**: `REDIS_HEALTH_TIMEOUT_SECONDS = 2`
  is a new, previously-nonexistent constant with no in-repo precedent for
  its specific value (unlike its *pattern* of introduction, which does
  have precedent) — too aggressive a value could report `error` under
  transient network jitter; too lax defeats the "must not hang" goal.
  Documented in Section 6 as the one implementation detail with the least
  direct precedent to anchor it.
- **First direct use of `redis-py` client API in this codebase** — low
  risk in isolation (the library is already a proven, pinned dependency
  via Celery), but this slice is the first code path to construct a
  `redis.Redis` object directly rather than through Celery's own
  configuration plumbing; worth a careful read of the actual `.ping()`
  exception types raised by the installed `redis==5.0.8` version during
  implementation, rather than assuming a fixed set in advance.
- **No risk to WAHA, webhook, Session Management, reconciliation, or
  Inbox message flow** — confirmed untouched throughout (Sections 7, 13).

---

## 17. USER DECISIONS REQUIRED

Given the strength of existing precedent, most design questions in the
original task's scope were resolvable directly from source and are
documented as decisions above (auth: unauthenticated per Sections 4/11;
endpoint owner: `apps/core` per Section 3; response shape: mirrors
`DatabaseHealthView` per Section 5; failure taxonomy: collapsed, single
`error` status per Section 12; BFF: not involved per Section 9; Celery:
explicitly out of scope per Section 10). Only one genuine open judgment
call remains:

1. **`REDIS_HEALTH_TIMEOUT_SECONDS` value** (Section 6/16).
   - **Options**: (a) `2` seconds, as proposed — a conservative default
     with no in-repo precedent to anchor the specific number; (b) a
     different fixed value, if you have an operational reason to prefer
     shorter/longer; (c) make it `.env`-configurable instead of a hardcoded
     constant, if you expect this to need per-deployment tuning the way
     `RECONCILIATION_INTERVAL_SECONDS` does.
   - **Consequences**: too short risks false `error` reports under
     ordinary network jitter to the `redis:6379` Docker hostname; too long
     weakens the "must not hang" guarantee this endpoint exists to satisfy
     for whatever calls it (Dashboard's fetch-once-on-mount pattern).
     Making it env-configurable adds one more variable to document and
     operate, for a value this audit found no stated requirement to tune
     per-environment.
   - **Recommendation, based on existing architecture (not imposed)**: `2`
     seconds as a hardcoded module constant, following the same
     "conservative fixed default, not environment-configurable" pattern
     `STALE_THRESHOLD_MULTIPLIER` already established in Phase 9.1A for a
     comparably low-stakes internal constant — but this is the one number
     in this report genuinely worth your confirmation before implementation,
     since no existing value in this codebase anchors it.

Everything else in this report was derived, not chosen — implementation
can proceed directly from Sections 3–14 above once you approve moving
forward.

---

## Summary of findings and decisions needed

Existing infrastructure gives a very strong, unambiguous precedent for
this slice: `apps/core/views.py`'s `DatabaseHealthView` is a
near-exact template — same unauthenticated pattern, same
`{status, component}` two-field response, same "catch internally, never
propagate a raw exception" discipline. Redis itself is used in this
codebase **only** as the Celery broker/result backend (`CELERY_BROKER_URL`,
already configured, no separate `REDIS_URL` needed) — no cache layer, no
session store, and no code anywhere constructs a `redis-py` client
directly yet, making this slice the first to do so. The proposed design:
a new `RedisHealthView` in `apps/core/views.py`, routed at
`GET /api/health/redis/`, unauthenticated, returning
`{status: 'ok'|'error', component: 'redis'}` (200/503), performing exactly
one `redis-py` `.ping()` call against `settings.CELERY_BROKER_URL` with a
bounded timeout, with all failure modes (unreachable, timeout,
misconfigured) collapsed into the single existing `error` status —
matching `DatabaseHealthView`'s own taxonomy exactly, not inventing a
richer one. No BFF involvement (Redis is Office-side; BFF has no path to
it). No Celery worker-liveness inference of any kind — explicitly a
Redis-only signal. No change to `SyncStatusView`, `sync_status`, or the
connectivity indicator — this is a third, independent signal. Fully
unit-testable without a live Redis instance, mirroring
`DatabaseHealthViewTests`'s existing mock-based pattern.

**Only one open question remains** (Section 17): the specific value of a
new, previously-unprecedented health-check timeout constant
(`REDIS_HEALTH_TIMEOUT_SECONDS`, proposed as `2` seconds). Every other
design decision in the original task's scope was resolvable directly from
existing source and is documented as a decision, not a question, above.

**No source code, `.env`/configuration, database, Docker configuration, or
Redis/WAHA state was modified in producing this report.** No endpoint was
called live and no WhatsApp message was sent. Awaiting your decision on
Section 17 (and your go-ahead to implement) — **nothing was implemented.**
