# Phase 13 (Failure/Security Testing) — Track B Live Failure Drill Report

**This was a live drill against the LOCAL DEVELOPMENT stack only**
(`infrastructure/development/office.yml`/`tencent.yml`). **Production was
never touched.** The real PostgreSQL server (`192.168.168.171`) and the
real WAHA instance/WhatsApp session (`100.124.162.223:3000`,
session `no_epahari`) were never stopped, disconnected, or sent any
write/message traffic — both are genuine external infrastructure per
`docs/CLAUDE.md`'s hard rules, and drilling "outage" for them was
simulated by pointing the *dev* backend/BFF at deliberately unreachable
addresses (an unused local port for Postgres, an RFC 5737 TEST-NET-1
address for WAHA), never by touching the real servers. **No fix was
applied for any finding below** — every failure is documented as
PASS/FAIL with evidence, per the explicit instruction to stop before
fixing. **Nothing was committed.**

---

## 0. Pre-Drill Preparation

- **Docs re-read**: `docs/09-TEST-PLAN.md`, `docs/15-CODING-PHASES.md`,
  `docs/generated/PHASE-13-FAILURE-SECURITY-TESTING-SCOPING-AUDIT-REPORT.md`.
- **In-flight activity check (read-only query against the real dev
  database, before touching anything)**:
  ```
  BlastCampaign by status: {'rejected': 1, 'pending_approval': 3}
  BlastRecipient by status: {'pending': 4}
  OutboundOperation pending/unknown count: 0
  ```
  No campaign was `approved`/`sending`; no outbound operation was
  ambiguous. Confirmed safe to proceed — no real WhatsApp send was ever
  at risk of being triggered or duplicated by this drill.
- **Pre-drill state**: all dev containers were found already stopped
  (`docker ps -a` showed every `wamora-dev-*` container `Exited`). The
  full dev stack (`office.yml` + `tencent.yml`) was started fresh as
  the drill's baseline and confirmed fully healthy before any failure
  was injected (Section 1).
- **Rollback plan**: both `.env` files that needed temporary edits
  (`infrastructure/development/.env`, `infrastructure/development/tencent.env`)
  were read in full before any edit, each temporary change was reverted
  immediately after its scenario, and both files were re-read afterward
  to confirm byte-for-byte restoration (Section 8). Container
  stop/start and `docker network disconnect`/`connect` are both
  natively reversible Docker operations.
- **Scope actually drilled**: the 6 scenarios the task specified
  (Office/backend outage, PostgreSQL outage, Redis outage, BFF/WAHA
  outage, network partition, recovery) — a deliberate subset of
  `docs/09-TEST-PLAN.md`'s 8 Failure items; items 6 (duplicate webhook)
  and 8 (ambiguous outbound) are out of this task's scope, already
  covered by Phase 13 Track A's concurrency test and existing
  idempotency tests respectively.

---

## 1. Baseline (before any failure injection)

| Check | Result |
|---|---|
| `GET /api/health/` (Django liveness) | `200 {"status":"ok","component":"backend"}` |
| `GET /api/health/database/` | `200 {"status":"ok","component":"database"}` |
| `GET /api/health/redis/` | `200 {"status":"ok","component":"redis"}` |
| `GET /health` (BFF) | `200 {"status":"ok","service":"bff","waha":{"reachable":true}}` |
| `GET /` (frontend dev server) | `200` |

All five green. This is the reference state every scenario's "recovery"
step is compared against.

---

## 2. Scenario 1 — Office/Backend Outage

**Action**: `docker compose -f office.yml stop` — stopped `backend`,
`celery-worker`, `celery-beat`, `redis` (the entire Office side), leaving
`bff`/`frontend` (Tencent side) and the real WAHA untouched.

**Expected** (`docs/09-TEST-PLAN.md` #1): "WAHA remains working; live
operations remain possible; office shows offline."

**Actual**:
```
BFF /health         -> 200 {"status":"ok","service":"bff","waha":{"reachable":true}}
Frontend /          -> 200
Django /api/health/ -> curl exit 7 (connection refused), ~2.2s
BFF session-status route (bad token) -> 401 (fast, not a hang) — confirms
    BFF's own JWT verification is independent of Django (RS256 public-key
    check, no callback to Django needed)
```

**Verdict: PASS.** WAHA/BFF fully independent and reachable; Django
cleanly unreachable (fast refusal, not a hang); frontend's static shell
still serves. Matches the architecture's stated invariant
(`docs/01-ARCHITECTURE.md`: "Office outage tidak boleh otomatis
mematikan Tencent/WAHA") exactly.

**Recovery**: `docker compose -f office.yml start` → all three health
endpoints `ok` within ~10s, no manual intervention beyond the restart
itself, no error in logs.

---

## 3. Scenario 2 — PostgreSQL Outage

**Simulation method**: temporarily set `DB_PORT=5499` (an unused port
on the *same real host*, `192.168.168.171` — the real server itself was
never touched, only pointed at a port nothing listens on there) in
`infrastructure/development/.env`, then `docker compose -f office.yml up -d --force-recreate backend celery-worker celery-beat`.

**Expected** (`docs/09-TEST-PLAN.md` #2): "DB health fails;
persistence/retry behavior is safe."

**Actual — a materially larger failure than expected**:
```
GET /api/health/          -> curl exit 7 (connection refused) — NOT just DB health, the ENTIRE Django process
GET /api/health/database/ -> curl exit 7 (same)
GET /api/health/redis/    -> curl exit 7 (same)
```
`docker logs wamora-dev-office-backend-1` showed the root cause
precisely:
```
django.db.utils.OperationalError: connection to server at "192.168.168.171", port 5499 failed: Connection refused
```
raised from `django.core.management.commands.runserver`'s
`check_migrations()` — a **Django framework-level startup check**, run
by `manage.py runserver`'s autoreloader before the HTTP server binds to
its port at all. Because this check requires a live DB connection and
none was available, **the entire `runserver` process failed to start
serving HTTP** — not just the database-dependent parts. `LivenessView`
(`backend/apps/core/views.py`), which is coded to never touch the
database, became unreachable anyway, purely because the process that
would have served it never finished booting.

The container itself stayed reported as `Up` throughout (`docker ps`)
— **no Docker healthcheck exists for `backend`/`celery-worker`/
`celery-beat`** (only `redis` has one, confirmed in `office.yml`), so
this failure would be invisible to anyone only watching `docker ps`.

**Verdict: FAIL** (relative to the Test Plan's stated expectation and
the architecture's implied failure-isolation intent). `DatabaseHealthView`
itself, when actually reachable, does correctly report DB failure — but
the specific, real-world path exercised here (a dev-container restart
while Postgres is unreachable) takes down the *entire* API surface,
not an isolated "DB health" signal.

**Recovery**: restoring `DB_PORT=5432` in `.env` alone was **not**
sufficient — the already-crashed process did not self-heal
(`curl` to `/api/health/` still returned `HTTP:000` 5s after the env
fix, with no container restart). An explicit
`docker compose -f office.yml up -d --force-recreate backend celery-worker celery-beat`
was required; after that, all three health endpoints returned `ok`
within ~5s.

**Finding requiring attention (not fixed)**: the DEV `runserver`
command's own startup-time `check_migrations()` call couples an
otherwise DB-independent liveness signal to database availability at
process-start time, and recovery from this specific failure mode is
not automatic. Not verified whether the same coupling exists in a
production `gunicorn`-based deployment (gunicorn does not invoke
`manage.py runserver`, so this may be dev-environment-specific — not
tested here, out of this drill's scope since it targets only the dev
stack).

---

## 4. Scenario 3 — Redis Outage

**Action**: `docker compose -f office.yml stop redis` (Redis is a
project-owned Docker container, safe to stop directly — no external
infrastructure involved).

**Expected** (`docs/09-TEST-PLAN.md` #3): "Background jobs fail
visibly; WAHA remains independent."

**Actual — every DRF endpoint failed, not just background jobs**:
```
GET /api/health/          -> 500 {"error":{"code":"internal_error", ...}}
GET /api/health/database/ -> 500 {"error":{"code":"internal_error", ...}}
GET /api/health/redis/    -> 500 {"error":{"code":"internal_error", ...}}
```
`docker logs` gave the exact, unambiguous root cause:
```
File ".../rest_framework/views.py", line 416, in initial
    self.check_throttles(request)
File ".../rest_framework/throttling.py", line 123, in allow_request
    self.history = self.cache.get(self.key, [])
...
redis.exceptions.ConnectionError: Error -2 connecting to redis:6379. Name or service not known.
Internal Server Error: /api/health/redis/
```
**Root cause, cited precisely**:
- `backend/config/settings.py:383-388` — `CACHES['default']` is
  `django.core.cache.backends.redis.RedisCache` with no fallback
  backend of any kind.
- `backend/config/settings.py:420-423` — `DEFAULT_THROTTLE_CLASSES`
  (`AnonRateThrottle`, `UserRateThrottle`) is applied **project-wide, to
  every `APIView`**, per that setting's own comment: "every DRF view
  gets a general ... throttle unless it overrides `throttle_classes`
  itself." This was added by Phase 12 (Security hardening, MUST-FIX
  #5) — confirmed via `docs/generated/PHASE-12-SECURITY-HARDENING-IMPLEMENTATION-REPORT.md`.
- DRF's `SimpleRateThrottle.allow_request()` calls `self.cache.get(...)`
  **inside `dispatch()`'s `initial()`, before any view logic runs**,
  with no `try/except` around the Redis call anywhere in this
  project's own code or in DRF/Django's own throttle implementation.

**Consequence**: any Redis outage takes down the **entire Django API
surface** — including `LivenessView`, `DatabaseHealthView`, and
`RedisHealthView` themselves, the exact endpoints an operator would
reach for to diagnose the outage. This is a materially larger blast
radius than "background jobs fail visibly" — it is "everything fails,
loudly, including the tools meant to report what's failing."

**Verdict: FAIL.** This directly contradicts the Test Plan's stated
expectation for this scenario.

**Recovery**: `docker compose -f office.yml start redis` → all three
health endpoints returned `ok` within ~5s, **with no backend restart
needed** — a materially different (better) recovery characteristic
than Scenario 2's Postgres-outage-at-startup case, since here the
`runserver` process itself never crashed (only individual *requests*
failed while Redis was unreachable); once Redis returned, the very next
request succeeded immediately.

---

## 5. Scenario 4 — BFF/WAHA Outage

### 4a. BFF itself down

**Action**: `docker compose -f tencent.yml stop bff`.

**Actual**:
```
BFF /health       -> curl exit 7 (connection refused)
Frontend /        -> 200 (static shell still serves)
Django /api/health/ -> 200 {"status":"ok", ...} (completely unaffected)
```

**Verdict: PASS.** Failure domain is exactly BFF-dependent live
features (session control, sending) — Django-backed features (Inbox
history, Dashboard data) are architecturally independent of BFF and
were confirmed unaffected.

**Recovery**: `docker compose -f tencent.yml start bff` → `200
{"waha":{"reachable":true}}` within ~4s.

### 4b. WAHA unreachable (from BFF's perspective — the real WAHA server was never touched)

**Simulation method**: temporarily set
`WAHA_BASE_URL=http://192.0.2.1:3000` (RFC 5737 TEST-NET-1, guaranteed
non-routable, never resolves to anything real) in
`infrastructure/development/tencent.env`, then
`docker compose -f tencent.yml up -d --force-recreate bff`.

**Actual**:
```
GET /health -> 200 {"status":"ok","service":"bff","waha":{"reachable":false}}
   (took exactly 10.01s — matches tencent.env's own WAHA_TIMEOUT_MS=10000
    exactly, confirming the WAHA client has a real, correctly-configured
    bounded timeout, not a hang-forever or instant-fail)
Session-status route with a bad token -> 401 in 0.01s (BFF's own auth
    check still works, independent of WAHA reachability)
Django /api/health/ -> 200 (fully unaffected, different failure domain)
```

**Verdict: PASS.** BFF correctly and promptly reports WAHA as
unreachable via its own health endpoint rather than hanging
indefinitely or crashing; the failure domain is exactly WAHA-dependent
BFF routes. **Not verified**: the exact client-visible error shape for
an *authenticated* session-control call while WAHA is unreachable (no
valid test JWT was obtained during this drill) — the unauthenticated
401 and the health check's own bounded-timeout behavior are used as the
closest available evidence instead.

**Recovery**: restored the real `WAHA_BASE_URL`, recreated `bff` →
`200 {"waha":{"reachable":true}}` within ~3s.

---

## 6. Scenario 5 — Network Partition

**Action**: `docker network disconnect wamora-dev-office_default wamora-dev-office-backend-1`
— the `backend` container's process kept running throughout; only its
network attachment was severed (a materially different failure mode
than "stopped": the process is alive but cannot communicate at all,
including its own published port).

**Expected** (`docs/09-TEST-PLAN.md` #5): network partition in both
directions.

**Actual**:
```
BFF /health -> 200 {"waha":{"reachable":true}} (different container/network, fully unaffected)
Django /api/health/ -> HTTP:000 after a full 12s timeout (a HANG, not an
    instant refusal — a distinct, correctly-different signature from
    Scenario 1's "stopped" case, which refused in ~2s)
```

**Verdict: PASS.** The partition produced the expected qualitatively
different failure signature (timeout/hang vs. clean refusal), and
correctly did not propagate to any other container.

**Recovery**: `docker network connect wamora-dev-office_default wamora-dev-office-backend-1`
→ `200 {"status":"ok"}` in 0.008s, **instantly, no restart needed** —
since the process never crashed, only its connectivity was restored.

---

## 7. Scenario 6 — Recovery Summary Across All Scenarios

| Scenario | Self-heals once the underlying condition clears? |
|---|---|
| Office/backend stop | No — needs an explicit `start`, but that alone is sufficient (no extra flags). |
| PostgreSQL outage (during a container (re)start) | **No** — the crashed process does not retry; needed `--force-recreate`. |
| Redis outage | **Yes** — no restart needed at all; the very next request after Redis returns succeeds. |
| BFF stop | No — needs an explicit `start`, sufficient on its own. |
| WAHA unreachable (BFF-side) | No — needed a `--force-recreate` to pick up the restored URL (this is inherent to how env vars are read once at container start, not a bug). |
| Network partition | **Yes** — instant, no restart needed once reconnected. |

**Post-drill full-stack verification** (all scenarios complete):
```
docker ps: all 6 wamora-dev-* containers "Up" (redis, bff healthy per their own healthchecks)
GET /api/health/          -> 200 ok
GET /api/health/database/ -> 200 ok
GET /api/health/redis/    -> 200 ok
GET /health (BFF)         -> 200 ok, waha.reachable:true
GET / (frontend)          -> 200
```

**Data-integrity check (read-only, before vs. after)**:
```
Before: BlastCampaign {rejected:1, pending_approval:3}; BlastRecipient {pending:4}; OutboundOperation pending/unknown: 0
After:  BlastCampaign {rejected:1, pending_approval:3}; BlastRecipient {pending:4}; OutboundOperation pending/unknown: 0
```
**Identical** — no data was lost or duplicated by the drill itself.
Additionally, `SyncCheckpoint` for the real session (`no_epahari`) was
observed to have autonomously completed a real periodic reconciliation
run *during* this drill window, ending at `status=ok` (not stuck at
`RUNNING`) — organic, positive evidence that the Phase 4/9 stuck-checkpoint
fix (commit `2f18c0d`) continued working correctly even while the
surrounding environment was being disrupted.

---

## 8. Environment Restoration Confirmed

Both temporarily-edited files
(`infrastructure/development/.env`, `infrastructure/development/tencent.env`)
were re-read in full after the drill and confirmed **byte-for-byte
identical** to their state at the start of this task (same
`DB_PORT=5432`, same `WAHA_BASE_URL=http://100.124.162.223:3000`, every
other line unchanged). `git status`/`git diff --stat` confirm zero
tracked repository files were modified by this drill (both `.env` files
are gitignored and were never part of git's view regardless).

---

## 9. PASS/FAIL Summary

| # | Scenario | Verdict |
|---|---|---|
| 1 | Office/backend outage | **PASS** |
| 2 | PostgreSQL outage | **FAIL** — blast radius far exceeds "DB health fails"; entire process fails to start |
| 3 | Redis outage | **FAIL** — blast radius far exceeds "background jobs fail visibly"; entire API surface returns 500 |
| 4a | BFF outage | **PASS** |
| 4b | WAHA outage (simulated) | **PASS** |
| 5 | Network partition | **PASS** |
| 6 | Recovery | **MIXED** — automatic for Redis outage and network partition; manual restart required for Postgres-outage-during-startup and for picking up a restored WAHA URL |

---

## 10. Findings Requiring Further Attention (NOT fixed — for user decision)

### Finding 1 (Severity: HIGH) — Redis outage takes down the entire Django API, not just rate-limited/background paths

- **File/line**: `backend/config/settings.py:383-388` (`CACHES['default']`
  = Redis-only, no fallback) combined with `backend/config/settings.py:420-423`
  (`DEFAULT_THROTTLE_CLASSES` applied to every `APIView` project-wide).
- **Impact**: any Redis outage produces an uncaught
  `redis.exceptions.ConnectionError` inside DRF's own `check_throttles()`
  (called before any view logic runs), returning `500` from **every**
  Django endpoint — including `LivenessView`/`DatabaseHealthView`/
  `RedisHealthView`, the very tools meant to diagnose this exact
  outage. Directly contradicts `docs/09-TEST-PLAN.md` Failure scenario
  3's stated expectation ("background jobs fail visibly, WAHA remains
  independent") — the actual blast radius is the entire API, not just
  background jobs.

### Finding 2 (Severity: MEDIUM) — Postgres outage during a dev container (re)start crashes the entire `runserver` process, including DB-independent endpoints

- **File/line**: not a custom-code bug — this is Django's own
  `django.core.management.commands.runserver`'s `check_migrations()`,
  triggered by `infrastructure/development/office.yml`'s
  `command: python manage.py runserver 0.0.0.0:8000`.
- **Impact**: `LivenessView` (`backend/apps/core/views.py`), which
  never queries the database in its own code, becomes unreachable
  anyway whenever the backend container (re)starts while Postgres is
  unreachable — because the whole HTTP server never finishes booting.
  **Not verified** whether a production `gunicorn` deployment has the
  same coupling (out of this drill's dev-only scope).

### Finding 3 (Severity: LOW/Operational) — No auto-recovery from a startup-time Postgres-outage crash

- Restoring DB connectivity alone did not bring the crashed process
  back; an explicit container recreate/restart was required. Worth a
  documented runbook step for Phase 14, not necessarily a code fix.

### Finding 4 (Severity: LOW/Operational) — No Docker healthcheck on `backend`/`celery-worker`/`celery-beat`

- **File**: `infrastructure/development/office.yml` — only the `redis`
  service defines a `healthcheck:` block. `docker ps`/`docker compose ps`
  reported `backend` as `Up` throughout Finding 2's entire crashed
  window; only an active `curl` against `/api/health/` revealed the
  real state. An operator relying on `docker ps` alone would not notice.

**No code, configuration, or migration was changed to address any of
the four findings above** — they are reported for a decision on
whether/how to fix, per this task's explicit instruction.

---

## 11. Explicit Non-Findings (things that worked exactly as designed)

- BFF's JWT verification is genuinely independent of Django (RS256
  public-key check, no runtime callback) — confirmed live under both
  Scenario 1 and Scenario 4b.
- BFF's WAHA client has a real, correctly-configured, bounded timeout
  (`WAHA_TIMEOUT_MS=10000`, observed exactly) rather than hanging
  indefinitely or failing instantly.
- The architecture's central claim — "Office outage ≠ WAHA outage" — held
  up completely and cleanly under a live drill (Scenario 1), not just in
  design intent.
- Network partition produces a qualitatively distinct (hang vs. refuse)
  and correctly-isolated failure signature (Scenario 5).
- No data was lost or duplicated by any scenario (Section 7).
- The Phase 4/9 stuck-checkpoint fix (commit `2f18c0d`) was observed
  working correctly on a real, autonomous periodic reconciliation run
  during the drill window.

---

## 12. Explicit STOP

This was a live drill and report only. **No fix was applied for
Findings 1–4.** No migration was created. Blast, Phase 12's own
existing code, and any feature outside Phase 13's scope were not
modified. Nothing was committed. Not proceeding to Phase 14 or any
further phase.

Awaiting the user's decision on which (if any) of Findings 1–4 to
address, and in what order, before any further action.
