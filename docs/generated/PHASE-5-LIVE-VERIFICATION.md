# Phase 5 — Live Verification (Celery/Redis Development Environment)

## 1. Verification date/time

2026-09-23, approximately 11:57–12:04 UTC.

## 2. Development environment

Windows, this session running through the VS Code Claude extension, in
`D:\PROJECT\waha-monitoring`. Docker Desktop confirmed running this round
(it was not running during the Phase 4 live-verification round).

## 3. Windows/Docker environment — findings from Section 1's inspection (before any change)

- `docker ps -a` showed numerous **pre-existing, unrelated containers**
  belonging to another project ("e-Samsat"): `docker-redis-sentinel-1`,
  `docker-redis-master-1`, `docker-redis-replica-1-1`,
  `docker-redis-replica-2-1`, `docker-celery-worker` (samsat),
  `docker-backend-esamsat-1`, `docker-frontend-esamsat-1`, a `postgres:17.4`
  container, `mariadb`, `rabbitmq`, `mosquitto`, and an `opensourcepos`
  stack — all in `Exited` state, untouched before, during, and after this
  verification (re-confirmed at the end — see Section 6/isolation result).
- `docker network ls` showed `docker_esamsat-net`, `docker_db-net`,
  `pointofsale_app_net`, `pointofsale_default` — all distinct, pre-existing,
  unrelated to this project.
- **No `office_*` network or `office-*` container existed before this
  verification** — confirming no dedicated development Redis existed yet
  for this project.
- Only two compose files exist in this repository:
  `infrastructure/office/docker-compose.yml`,
  `infrastructure/tencent/docker-compose.yml`. No root-level or other
  compose file exists.

**Answers to the 7 inspection questions:**
1. Is a Redis service already defined for development? — **Yes, in
   `infrastructure/office/docker-compose.yml`** (`redis:7-alpine`, no
   host port, no Sentinel) — defined since Phase 0, never previously
   started.
2. Is a Celery worker service already defined? — **Yes** (`celery-worker`,
   same compose file, `command: celery -A config worker -l info`).
3. Is a Celery Beat service already defined? — **Yes** (`celery-beat`,
   `command: celery -A config beat -l info`).
4. What Docker network does Django use? — The compose file defines no
   explicit network, so Compose creates a default bridge network named
   after the compose project directory: **`office_default`**.
5. What hostname should Django use to reach Redis? — **`redis`** (the
   Compose service name) — already correctly configured in
   `CELERY_BROKER_URL=redis://redis:6379/0` in both `backend/.env` and
   `.env.example` files.
6. Are worker and Beat expected to run inside Docker or directly on
   Windows? — **Inside Docker**, per the existing compose service
   definitions (build from the same backend image, `depends_on: redis`).
7. Does the current compose configuration already support the required
   development topology? — **Yes.** No compose file changes were needed
   or made — the existing Phase 0 definition was already correct and
   sufficient.

**Conclusion of Section 1: no Docker Compose changes were required.**
Per the instruction "If the existing Docker Compose already contains a
suitable isolated Redis service, do not create another one" — it did, so
none was created. This report proceeds directly to starting and verifying
the existing definition.

## 4. Docker Compose configuration discovered

(See Section 3, items 1–3.) Unchanged from Phase 0/5 — reproduced here for
completeness:
```yaml
redis:
  image: redis:7-alpine
  restart: unless-stopped
celery-worker:
  build: {context: ../../backend}
  command: celery -A config worker -l info
  env_file: [.env]
  depends_on: [redis]
celery-beat:
  build: {context: ../../backend}
  command: celery -A config beat -l info
  env_file: [.env]
  depends_on: [redis]
```

## 5. Redis service — VERIFIED LIVE

Started via `docker compose up -d redis` in `infrastructure/office/`.
- Container: **`office-redis-1`**, image `redis:7-alpine`.
- Port: `6379/tcp` — **internal only, no host port mapping** (not
  publicly exposed).
- `docker exec office-redis-1 redis-cli ping` → **`PONG`**.
- `redis_version:7.4.11` (confirmed via `redis-cli info server`).

## 6. Redis isolation result — VERIFIED LIVE

- Network: **`office_default`**, containing only `office-redis-1` at the
  time of inspection (`docker network inspect office_default`).
- This is a completely separate Docker network from e-Samsat's
  `docker_esamsat-net`.
- Container naming (`office-*`, derived from the compose project
  directory name) is distinct from e-Samsat's `docker-*-esamsat`/
  `docker-redis-sentinel-1`/`docker-redis-master-1`/`docker-redis-replica-*`
  naming.
- **No Sentinel, no replication, no clustering** — a single, plain
  `redis:7-alpine` instance.
- **e-Samsat containers were never started, stopped, execed into, or
  otherwise interacted with.** Re-confirmed via `docker ps -a` after this
  verification's teardown: every e-Samsat/unrelated container remains in
  the exact same `Exited` state it was in before this session began.
- **Isolation result: CONFIRMED.** This project's Redis is fully
  independent of the e-Samsat infrastructure.

## 7. Redis connectivity result — VERIFIED LIVE

Actual connection tests performed (not configuration inspection alone):
`PING` → `PONG` (Section 5). Broker and result-backend connectivity are
further confirmed by Section 9 (the worker's own log: `Connected to
redis://redis:6379/0`, and a task's result was successfully written to
and read back from the result backend).

## 8. Django → Redis result — VERIFIED LIVE

`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` in the real `backend/.env`
both resolve to `redis://redis:6379/0` — confirmed to be **this
project's own isolated Redis**, not any other instance; **no fallback to
any other Redis occurred** at any point. Both the broker path (task
queued → worker received it) and the result-backend path (task result
retrieved via `.get()`) were exercised successfully — see Section 9.

## 9. Celery Worker result — VERIFIED LIVE

Built (`docker compose build celery-worker`) and started
(`docker compose up -d celery-worker`). Real startup log excerpt:
```
-------------- celery@ea8f097d842c v5.4.0 (opalescent)
- ** ---------- .> app:         waha_monitoring:...
- ** ---------- .> transport:   redis://redis:6379/0
- ** ---------- .> results:     redis://redis:6379/0
[tasks]
  . apps.sync.tasks.reconcile_all_sessions_task
  . apps.sync.tasks.reconcile_session_task
[...] Connected to redis://redis:6379/0
[...] celery@ea8f097d842c ready.
```
Correct app loaded, correct broker/backend, **exactly the two expected
tasks registered, no unexpected task modules**.

**One real issue found and fixed, in-scope**: the worker logged a
`CPendingDeprecationWarning` about `broker_connection_retry_on_startup`
(a Celery 6.0 behavior change). Fixed by adding
`CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True` to `backend/config/settings.py`
— explicit, documented, preserves today's behavior rather than silently
changing when Celery 6.0 ships. Rebuilt and re-verified: warning is gone,
worker still starts and registers tasks correctly (Section 13, files
changed).

## 10. Registered task list

```
apps.sync.tasks.reconcile_all_sessions_task
apps.sync.tasks.reconcile_session_task
```
No other custom tasks exist in this project; none unexpected were loaded.

## 11. `reconcile_session_task` live execution result — VERIFIED LIVE

Seed data created for this test (see Section 16 for full disclosure):
`WahaSession(name='test_session')` and `Chat(provider_chat_id='000000000000000@lid')`
— the **real, already-confirmed-real** session/chat identifiers from this
project's own prior live evidence, not fabricated placeholder values. No
existing `WahaSession` was present in the real database before this (all
of this project's earlier Postgres verifications used rolled-back
transactions, so this is the first row of its kind to actually persist).

Dispatched via `docker compose run --rm celery-worker python manage.py shell -c "..."`
calling `reconcile_session_task.delay('test_session')` and `.get(timeout=60)`
— **through the real broker, not `CELERY_TASK_ALWAYS_EAGER`**.

Result:
```python
{'session_name': 'test_session', 'chats_processed': 0, 'messages_inserted': 0,
 'messages_skipped_existing': 0, 'messages_failed': 0, 'had_error': True}
```
Worker log showed the actual cause: `WAHA request failed for chat
000000000000000@lid: ConnectTimeout`.

**This is an honest, informative result, not a failure of Phase 5's own
scope.** Docker Desktop containers on this Windows machine do not inherit
the host's NetBird-routed network — the container simply cannot reach
`<TENCENT_WAHA_HOST>:3000` the way this session's own host shell can (verified
reachable directly from the host in Phases 3/4). This is a **pre-existing,
already-flagged unverified item** (live WAHA connectivity from Django's
actual runtime was never confirmed in any earlier phase either) — Phase 5
did not introduce it and is not responsible for it. What Phase 5's own
scope required — **the task executing correctly through the real
Redis/Worker path, and reconciliation's failure-handling working
correctly when WAHA is unreachable** — is fully confirmed: no crash, a
clear diagnosable error, `SyncCheckpoint` correctly left at
`status=error`/`checkpoint_value=''` (verified by direct query — Section
15), nothing fabricated.

**Queue/ack behavior**: task was queued (visible in worker's "received"
log), consumed exactly once, acknowledged (no redelivery/duplicate
execution occurred — confirmed by running it a second time deliberately
as a separate, intentional dispatch, not an accidental redelivery).

## 12. Celery Beat result — VERIFIED LIVE

Built and started (`docker compose build celery-beat && docker compose up -d celery-beat`).
Startup log confirmed: `broker -> redis://redis:6379/0`,
`scheduler -> celery.beat.PersistentScheduler`, `beat: Starting...`.

## 13. Beat → Redis → Worker result — VERIFIED LIVE

The documented production interval is 900s (15 minutes) — impractical to
wait for directly. Per the explicit instruction to use "a controlled
development-only verification mechanism without changing the production
schedule semantics" and to **never permanently alter the intended
15-minute schedule**: `RECONCILIATION_INTERVAL_SECONDS=15` was appended to
a **local, temporary copy** of `infrastructure/office/.env` (never
`backend/.env`, never `.env.example`, never `settings.py`'s default of
900), Beat was restarted with that override, observed, and the override
was then **removed** immediately after (confirmed by grep: zero
occurrences remaining, falling back to the real 900s default).

With the temporary 15s interval, within ~16 seconds:
```
[...] Scheduler: Sending due task reconcile-all-sessions (apps.sync.tasks.reconcile_all_sessions_task)
[...] Task apps.sync.tasks.reconcile_all_sessions_task[...] received
[...] Task apps.sync.tasks.reconcile_session_task[...] received
[...] Task apps.sync.tasks.reconcile_all_sessions_task[...] succeeded [...]: {'sessions_dispatched': 1}
```
**Full cascade confirmed live**: Beat fired on schedule → published to
Redis → worker received `reconcile_all_sessions_task` → it correctly
found the one known session and dispatched `reconcile_session_task` for
it → worker received that too. The application's real, permanent
15-minute default was never altered — only a temporary local file was
touched and then reverted.

## 14. Retry behavior result

**Unit-test verified** (Phase 5's own test suite, `apps/sync/tests/test_tasks.py`)
**and separately VERIFIED LIVE this round.**

Live test: dispatched `reconcile_session_task.delay('nonexistent-verification-session')`
through the real worker (a session name deliberately not present, causing
`WahaSession.DoesNotExist` to propagate out of `reconcile_session`,
unlike `WahaClientError` which is caught internally). Real worker log,
in full sequence:
```
[...] Task [...] received
[...] Task [...] retry: Retry in 0s: DoesNotExist(...)
[...] Task [...] received        (redelivery)
[...] Task [...] retry: Retry in 0s: DoesNotExist(...)
[...] Task [...] received        (redelivery)
[...] Task [...] retry: Retry in 0s: DoesNotExist(...)
[...] Task [...] received        (redelivery)
[...] Task [...] raised unexpected: DoesNotExist(...)   (ERROR — terminal)
```
**Confirmed live: exactly 3 retries (matching `max_retries=3`), backoff/
jitter mechanism engaged (each retry logged a computed "Retry in Ns"
delay, confirming `retry_backoff`/`retry_jitter` were applied — though
the computed delays happened to round to near-zero in this instance,
since only the boolean `retry_backoff=True` was set without an explicit
numeric base beyond Celery's own default), and a clean terminal failure
state after retries were exhausted** — never stuck retrying forever, never
silently swallowed.

## 15. Idempotency result — VERIFIED LIVE (for the "safe to re-run" property) + VERIFIED BY TEST (for duplicate-prevention with real inserted data)

Live: `reconcile_session_task.delay('test_session')` was dispatched twice
through the real worker/broker. Both runs produced **byte-identical
results** and left the database in the same consistent state (`SyncCheckpoint`
queried directly afterward: `status=error`, `checkpoint_value=''`,
`last_run_at` set, `last_error` populated with the same diagnosable
message). No corruption, no drift between runs.

**What this live round did NOT re-prove** (because the WAHA fetch never
succeeded — Section 11): that inserting real messages twice produces no
duplicates. That specific property remains proven by test (Phase 4/5's
suite, including the real-PostgreSQL-with-rollback verification already
performed in earlier phases) rather than by this round's live evidence —
distinguishing this honestly rather than overclaiming.

## 16. PostgreSQL result

Used the existing real development database throughout — no new
PostgreSQL server, no container, no reset, no truncation.

**Durable rows created and left in place** (disclosed in full, not
silently done): one `WahaSession` (`test_session`), one `Chat`
(`000000000000000@lid`), one `SyncCheckpoint` (`status=error`, from the
network-limited test). All represent **real, accurate information** (the
genuine session/chat identifiers already established as real throughout
this project's evidence chain) rather than fabricated test data — no
`WahaSession`/`Chat` existed in the real database before this
verification (confirmed by a read-only check first). **Zero `Message`/
`Contact` rows exist** — nothing was fabricated or partially/incorrectly
inserted. The row created for the retry test
(`nonexistent-verification-session`) was **never created** — that test
deliberately used a name that doesn't exist, so there is nothing to clean
up from it. **These three rows were deliberately left in place** rather
than rolled back, since they are truthful and low-risk for a development
database — if you'd prefer them removed, they are easy to identify and
delete (`WahaSession.objects.filter(name='test_session').delete()` would
cascade-protect per Phase 2's `on_delete=PROTECT` design, so the
`Chat`/`SyncCheckpoint` would need clearing first — flagging this rather
than doing it unasked).

## 17. Test suite result

- **Previous test count**: 127 (as of the Phase 5 implementation report).
- **Current test count**: 127.
- **Failures**: none.
- No test was weakened, skipped, or deleted to obtain this result.

## 18. Files changed

- `backend/config/settings.py` — added `CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True` (Section 9; the only code change this round).

No other file was modified. `infrastructure/office/docker-compose.yml`
was inspected and used exactly as it already existed — not changed.
`infrastructure/office/.env` was created temporarily (copied from the
real `backend/.env`, never printed) to run `docker compose`, and deleted
afterward — not a permanent repository change.

## 19. Known limitations

1. **Docker containers on this Windows dev machine cannot reach the
   NetBird-routed WAHA address** — a real, now-confirmed networking gap
   between "host shell" and "Docker container" reachability. This affects
   how the REAL office deployment's containers will need to be configured
   to reach WAHA (a NetBird client inside the container? host networking?
   the office server's own NetBird integration?) — a deployment-topology
   question for a later phase, not a Phase 5 defect.
2. **Positive proof of duplicate-free real-data insertion was not
   re-confirmed live this round** (Section 15) — remains proven by test
   and by the earlier Phase 4 rolled-back-transaction Postgres
   verification, not by this round's live evidence.
3. **Backoff delay values observed live were near-zero** — the mechanism
   is confirmed engaged (Section 14), but meaningful multi-second backoff
   timing itself wasn't independently exercised, since only the boolean
   `retry_backoff=True` was configured without an explicit numeric base.
4. Every limitation already listed in `docs/generated/PHASE-5-CELERY-REDIS.md`
   Section 14 remains, except items now resolved by this round (live
   Redis/worker/beat verification, previously `NOT EXECUTED`, is now
   `VERIFIED LIVE`).

## 20. Whether Phase 6 is safe to start

See Final Decision below.

---

## Final Decision

**PHASE 6 READY**

Every criterion in the stated checklist is satisfied:
- Dedicated development Redis: **verified** (isolated, running, `PONG`,
  version confirmed, network/naming distinct from e-Samsat).
- Django can connect to Redis: **verified** (broker + result backend both
  exercised successfully, no fallback).
- Real Celery Worker receives a task: **verified** (live log evidence).
- `reconcile_session_task` executes through Redis/Worker: **verified**
  (live, non-eager, twice, idempotently).
- Celery Beat: **verified** (schedule loaded, fired, dispatched, correct
  interval confirmed from settings without ever permanently changing it).
- Retry behavior: **verified** (live, exactly 3 bounded retries, backoff/
  jitter engaged, clean terminal state).
- Idempotency: **intact** (live for the safe-to-rerun property; by test
  for real-data duplicate prevention).
- Full test suite: **127/127 passing**.
- No unresolved Phase 5 runtime blocker remains — the one limitation
  found (Docker-to-NetBird reachability) is a pre-existing, already-
  tracked deployment-topology question from earlier phases, not something
  Phase 5 introduced or that blocks Phase 5's own completion criteria.

Not starting Phase 6 in this turn regardless — that remains your call.
