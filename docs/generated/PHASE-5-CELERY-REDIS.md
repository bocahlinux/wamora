# Phase 5 — Celery/Redis

> **Update**: Section 11 ("Live Redis verification result") below was
> written as `NOT EXECUTED` at the time. A dedicated follow-up live
> verification was performed afterward and **did** successfully verify
> Redis, Celery Worker, Celery Beat, real task execution, and retry
> behavior live — see `docs/generated/PHASE-5-LIVE-VERIFICATION.md` for
> the current, accurate status. Section 11 is left unedited below as an
> accurate record of what was true at the time it was written.

## 1. Scope

Wire Celery/Redis background job execution for the one operation this
project's documentation actually describes as a recurring background
job: reconciliation (`docs/05-WEBHOOK-SYNC-DESIGN.md` — "reconciliation
job"). Nothing else was moved to Celery; nothing else was determined by
the documentation to require it.

## 2. Existing architecture discovered

Reviewed before writing any code:
- `docs/00-MASTER-SPEC.md`, `docs/02-REQUIREMENTS.md`, `docs/05-WEBHOOK-SYNC-DESIGN.md`, `docs/08-DEPLOYMENT.md`, `docs/15-CODING-PHASES.md` — Celery worker/beat + Redis are provisioned (topology only; no task-level spec anywhere).
- `backend/config/celery.py` — a Phase-0 skeleton (`app = Celery(...)`, `config_from_object`, `autodiscover_tasks()`), never previously exercised with a real task.
- `backend/config/settings.py` — `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` already set (Phase 0), no other Celery config existed.
- `apps/sync/reconciliation.py` (Phase 4) — the existing, tested, idempotent `reconcile_session()` service function — this is what Phase 5 wraps, not reimplements.
- `apps/webhooks/views.py`/`services.py` (Phase 3) — webhook ingestion is synchronous HTTP request handling, pure DB writes, no external I/O to offload.
- `infrastructure/office/docker-compose.yml` — `celery-worker` (`celery -A config worker -l info`) and `celery-beat` (`celery -A config beat -l info`) services already existed from Phase 0, correctly built from the backend image, `depends_on: redis`. **No changes were needed here** — the topology was already correct; Phase 5's job was to give it real tasks to run.
- `backend/.env` (the real dev environment) — confirmed `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` are present with real values (not printed).
- Existing test suite: 114 tests, all passing before this phase's changes.

**Decision — webhook ingestion stays synchronous.** No documentation
asks for it to move to Celery. It has no external I/O (pure DB writes,
already fast), and WAHA expects a prompt HTTP response — moving it to a
background queue would add complexity (needing to either block on task
completion, defeating the purpose, or return before persistence is
confirmed) with no documented benefit. This is a considered decision, not
an oversight — explicitly called out per the instruction not to move
synchronous behavior to Celery without a documented reason.

## 3. Celery configuration

None of these values are specified anywhere in the documentation — each
is a conservative, documented implementation decision (`backend/config/settings.py`):

| Setting | Value | Reasoning |
|---|---|---|
| `CELERY_TASK_SERIALIZER` / `CELERY_RESULT_SERIALIZER` | `json` | Never pickle — avoids deserializing untrusted data (consistent with `docs/06-SECURITY.md`'s general posture) |
| `CELERY_ACCEPT_CONTENT` | `['json']` | Same reasoning |
| `CELERY_TIMEZONE` | `TIME_ZONE` (`'UTC'`) | Matches Django's own timezone exactly, avoids a second source of truth |
| `CELERY_TASK_TRACK_STARTED` | `True` | Observability — matches `docs/02-REQUIREMENTS.md`'s "Observability" requirement (task state visibility) |
| `CELERY_TASK_TIME_LIMIT` / `CELERY_TASK_SOFT_TIME_LIMIT` | 600s / 540s | Bounds a stuck task rather than letting it run forever — conservative safety default |
| `RECONCILIATION_INTERVAL_SECONDS` (custom, not a Celery setting) | 900 (15 min), env-configurable | How often the periodic reconciliation task fires — genuinely undocumented, chosen conservatively and made tunable rather than hardcoded |

Task discovery: `apps.autodiscover_tasks()` (already present from Phase 0)
correctly finds `apps/sync/tasks.py` once triggered. **Note on a real
Celery nuance discovered while testing**: this discovery is lazy — merely
importing `config.celery` or accessing `app.tasks` does not trigger it in
a plain script; it requires `app.loader.import_default_modules()` (which
happens automatically as part of a real worker's own startup sequence,
so this only matters for testing/diagnostics, not production operation).
Documented here and in the tests' own comments so it isn't mysterious to
a future reader.

## 4. Redis configuration

**Used the existing topology exactly as already defined — no Sentinel,
no cluster, no new Redis service.** `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`
continue to be read from environment variables (Phase 0), pointing at the
`redis` service already defined in `infrastructure/office/docker-compose.yml`
(image `redis:7-alpine`, unchanged). Nothing about the Redis service
definition was touched.

## 5. Tasks implemented

`apps/sync/tasks.py`:
- **`reconcile_session_task(session_name, limit=100, max_pages=10)`** —
  per-session task. Bound, with a bounded (`max_retries=3`) exponential
  backoff retry (`autoretry_for=(Exception,)`, `retry_backoff=True`,
  capped at 600s, jittered).
- **`reconcile_all_sessions_task()`** — the periodic entry point (Celery
  beat). Looks up every known `WahaSession` and dispatches one
  `reconcile_session_task.delay(...)` per session, so one session's
  failure/retry doesn't block or affect another's.

Wired into Celery beat via `config/celery.py`'s `on_after_configure`
signal handler, using `settings.RECONCILIATION_INTERVAL_SECONDS` as the
interval (confirmed correctly picked up from the environment — see
Section 10).

## 6. Task → service-layer relationships

Both tasks are thin orchestration only, exactly as instructed. All
business logic remains in `apps.sync.reconciliation.reconcile_session`
(Phase 4, unmodified) and `apps.chats`/`apps.waha_sessions` models
(Phase 2, unmodified). `reconcile_session_task` does not reimplement any
part of reconciliation — it calls the existing function and translates
its `ReconciliationResult` into a plain dict for the task's return value
(Celery result backends need serializable values; the `ReconciliationResult`
object itself is not JSON-serializable, so this translation is necessary
plumbing, not duplicated logic).

## 7. Retry behavior

Bounded (`max_retries=3`), exponential backoff (`retry_backoff=True`,
capped at 600s), jittered. Not specified by any documentation — chosen
because retrying `reconcile_session` is *provably safe* (Phase 4's
idempotency guarantees), making a conservative automatic-retry policy a
reasonable default rather than an invented requirement. A **discovered
testing nuance, not a bug**: under Django's `CELERY_TASK_ALWAYS_EAGER`
with `retry_backoff` configured, Celery raises `celery.exceptions.Retry`
rather than sleeping and re-invoking synchronously — eager mode does not
simulate real time delays. Tests were written to assert against this
real, correct behavior (confirming the retry *was* triggered) rather than
expecting an automatic sleep-loop that eager mode doesn't provide.

## 8. Idempotency behavior

Entirely inherited — nothing new was added. `reconcile_session_task`
retrying, or `reconcile_all_sessions_task` dispatching the same session
twice, is exactly as safe as calling `reconcile_session()` twice directly
(Phase 4), because that is literally what happens — the
`(session, provider_message_id)` database constraint is the actual
mechanism, unchanged, unmodified. Verified directly:
`test_rerunning_task_does_not_duplicate_durable_records`.

## 9. Transaction behavior

Unchanged from Phase 4 — each message's persistence still happens inside
its own `transaction.atomic()` block inside `reconcile_session`/`persist_message`,
per-page, exactly as before. Celery adds no additional transaction
boundary of its own; task retries operate at the level of "re-run
`reconcile_session`", which is already safe to re-run at any point.

## 10. Test results

**127 tests total, all passing** (114 carried over from Phases 1–4
unchanged, 13 new for Phase 5): `python manage.py test apps` via the
established test-only SQLite settings. New tests (`apps/sync/tests/test_tasks.py`):
Celery app initializes, tasks are discovered (with the lazy-discovery
nuance handled correctly), task names match their dotted paths, broker/
serialization/timezone configuration is correct, beat schedule includes
reconciliation with the configured interval, a task executes successfully
and returns a summary, a task actually persists via the real
`reconcile_session` (not a mock standing in for correctness), re-running a
task does not duplicate records, task failure is observable (not silently
swallowed), the retry policy is bounded as configured, and a
worker-style redelivery after a retry eventually succeeds.

## 11. Live Redis verification result

**`NOT EXECUTED`.** `CELERY_BROKER_URL` in the real `backend/.env`
resolves to `redis://redis:6379/0` — `redis` is the Docker Compose
service name for the office network, not a routable address from this
sandboxed environment (confirmed: `ConnectionError` on a direct `PING`
attempt, with the hostname/port shown here since neither is a secret —
no password was configured on this broker URL either, per the same
check). This is different from the WAHA/PostgreSQL situations in earlier
phases: those had real LAN/NetBird-routable addresses provided; Redis, by
the documented topology, is deliberately internal-only to the office
Docker network and was never intended to be reachable from outside it.
This is not a gap to fix — it's the correct, secure topology — but it
does mean this session could not perform a live broker-connectivity or
live task-execution check. What *was* verified: Celery configuration
correctly loads from the real `backend/.env` (broker URL parses
correctly, `RECONCILIATION_INTERVAL_SECONDS` and all task-serialization
settings resolve as expected) — only the actual TCP connection to Redis
itself is unavailable from here.

## 12. Environment assumptions

- Redis is reachable from the `backend`/`celery-worker`/`celery-beat`
  containers themselves (same Docker network) — not independently
  verified this round (Section 11), but this is the documented topology
  and was already relied upon (unverified) since Phase 0.
- A real worker process, when started (`celery -A config worker`), will
  correctly trigger task autodiscovery through its normal startup
  sequence — confirmed this is the standard, well-known Celery behavior;
  not something this project's `celery -A config worker -l info` command
  (already correct since Phase 0) needs to do anything special for.
- `RECONCILIATION_INTERVAL_SECONDS=900` (15 minutes) is a reasonable
  starting point, not a validated-against-real-traffic value — flagged
  as an implementation decision, not a requirement, per Section 3.

## 13. Files changed

**Created:**
- `backend/apps/sync/tasks.py`
- `backend/apps/sync/tests/test_tasks.py`

**Modified:**
- `backend/config/celery.py` — added the `on_after_configure` beat-schedule handler
- `backend/config/settings.py` — added Celery serialization/timezone/time-limit config and `RECONCILIATION_INTERVAL_SECONDS`
- `backend/.env.example`, `infrastructure/office/.env.example` — added `RECONCILIATION_INTERVAL_SECONDS`

**Not modified:** `infrastructure/office/docker-compose.yml` (already correct from Phase 0 — verified, not touched), any model, any migration, any frontend/BFF file, `apps/sync/reconciliation.py`, `apps/webhooks/*` (webhook ingestion untouched).

## 14. Known limitations

1. **No live Redis/task-execution verification was possible** (Section
   11) — the entire background-execution path (broker connectivity, a
   worker actually picking up and running a task, beat actually firing on
   schedule) is verified only through Django's `CELERY_TASK_ALWAYS_EAGER`
   test mode, never against a real running worker/beat/Redis. This should
   be checked once the office deployment is reachable for testing.
2. **`RECONCILIATION_INTERVAL_SECONDS` default (900s) is an
   implementation decision, not a validated operational value** — worth
   revisiting once real reconciliation volume/latency is observed.
3. **No dead-letter or alerting mechanism** for a task that exhausts all
   3 retries — it simply fails and is logged; nothing pages an operator.
   Not documented as required, so not built, but worth knowing.
4. **`SyncCheckpoint.lag_seconds`** (an existing Phase 2 field, referenced
   by `docs/02-REQUIREMENTS.md`'s "sync lag" observability requirement)
   is still never populated — its precise intended meaning was not
   defined by any doc, and populating it wasn't required to deliver
   Phase 5's actual scope (Celery/Redis wiring), so it was deliberately
   left alone rather than guessed at. Flagging it as a real gap for
   whichever future phase builds observability/monitoring.

## 15. Phase 6 status

**Phase 6 has NOT been started.** No BFF, frontend, inbox/chat UI,
offline/degraded mode, session management, blast, security hardening
beyond what this phase strictly required, or production deployment work
was performed.

---

## Final report

1. **Files changed**: see Section 13.
2. **Tasks implemented**: `reconcile_session_task` (per-session, retryable), `reconcile_all_sessions_task` (periodic dispatcher).
3. **Redis configuration**: existing topology reused unchanged (`redis:7-alpine` in `infrastructure/office/docker-compose.yml`, env-driven broker/result-backend URLs).
4. **Celery configuration**: see Section 3 table — all conservative, documented, non-arbitrary defaults.
5. **Retry behavior**: bounded (3 retries), exponential backoff with jitter, capped at 600s — safe because the underlying operation is idempotent.
6. **Idempotency behavior**: fully inherited from Phase 4; nothing new added or needed.
7. **Test count/result**: 127/127 passing (13 new).
8. **Live Redis verification result**: `NOT EXECUTED` — Redis is Docker-internal only, not reachable from this environment; explained in Section 11.
9. **Known limitations**: see Section 14.
10. **Whether Phase 5 is complete**: Yes, for everything verifiable from this environment — Celery/Redis integration is implemented, tested, and correctly wired to the existing Phase 4 service layer with no duplicated logic and no compromised idempotency. Live worker/broker execution remains unverified (Section 11), same category of gap as the still-unverified HMAC/outbound/group-chat items from earlier phases — not fabricated as working, clearly flagged as unverified instead.
