# Celery Worker Liveness — Design Audit Report

> **Phase labeling note (added 2026-09-26, per
> `docs/generated/PHASE-ROADMAP-STATUS-AUDIT-REPORT.md`):** this report
> refers repeatedly to "Phase 13.A"/"13.A". That label is NOT part of the
> canonical roadmap's Phase 13 ("Failure/security testing",
> `docs/15-CODING-PHASES.md`) — it is properly a continuation of Phase 4
> ("Reconciliation") and Phase 9 ("Offline/degraded mode"). The "13.A"
> numbering was informal, originating from an internal subsection label
> in `NEXT-PHASE-RECONCILIATION-RECOVERY-DESIGN-AUDIT-REPORT.md`, and is
> not an official roadmap sub-phase. See
> `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` for the recorded decision.

**This is a read-only design audit. No source, test, config, Docker,
Compose, `.env`, migration, or Celery configuration file was modified.
No container was started, stopped, or restarted. No reconciliation was
triggered. No WhatsApp/WAHA operation was performed. No write operation
against the application/database occurred. Phase 13.A's manual recovery
endpoint and the existing `possibly_stuck` detection were not touched.**

**Conclusion up front:** this codebase currently has **no mechanism of
any kind** that observes Celery worker liveness — not a `control.ping()`
call, not event monitoring, not a Docker healthcheck on the worker
containers, not a persisted task ID. The only "health" signal that
exists (`RedisHealthView`) explicitly, deliberately, and by its own
docstring **does not** claim to prove worker liveness — it proves only
that Redis itself answers `PING`. Every failure scenario this audit
traced confirms the same underlying fact already established by the
two prior related audits: `possibly_stuck` and Phase 13.A's manual
recovery are both correctly scoped to what is actually knowable today
(checkpoint age), and **automatic recovery remains unsafe**, now for an
additional, concretely-demonstrated reason beyond the prior audit's
concurrency findings — a routine, expected Celery retry-backoff
sequence can, by itself, trigger `possibly_stuck` while the task is
working exactly as designed (Section 8, scenario H).

---

## 1. Objective

Establish, strictly from source and configuration, exactly what this
project can and cannot currently know about Celery worker health, task
execution, and task loss — without implementing anything.

---

## 2. Scope

Read-only. Investigated: Celery/Django configuration, Docker Compose
files (dev and production Office), the full reconciliation/task code
path, `apps/audit`, `apps/authn`, `apps/core` (health endpoints),
`requirements.txt`, and a repository-wide search for any
inspection/heartbeat/monitoring mechanism. `docker ps` was run once to
confirm which containers are currently running (a live-environment
observation, not a live-behavior test) — no container was started,
stopped, or otherwise acted upon.

---

## 3. Current Celery Architecture

**VERIFIED FROM CONFIGURATION** — `backend/config/settings.py`, every
`CELERY_*` setting, re-enumerated directly this task (complete list,
nothing omitted):

```python
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TIMEZONE = TIME_ZONE  # 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 600
CELERY_TASK_SOFT_TIME_LIMIT = 540
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
```

**VERIFIED FROM CONFIGURATION** — worker/beat startup commands, both
Compose files re-read directly this task:

```yaml
# infrastructure/development/office.yml AND infrastructure/office/docker-compose.yml
# (identical commands in both; dev adds a healthcheck-gated depends_on
# and a source bind mount, production does not)
celery-worker:
  command: celery -A config worker -l info
celery-beat:
  command: celery -A config beat -l info
```

**No command-line options of any kind** are passed to either command —
no `--concurrency`/`-c`, no `--hostname`/`-n`, no `--queues`/`-Q`, no
`--events`/`-E`, no `--loglevel` beyond `info`. This means:
- **Concurrency**: Celery's own default (CPU core count via the
  `prefork` pool — the library default, not configured here).
- **Worker hostname**: Celery's auto-generated default
  (`celery@<container hostname>`), not deliberately set.
- **Queues**: the single default queue (`celery`) — no routing, no
  dedicated reconciliation queue.
- **Events**: `-E`/`worker_send_task_events` is **not** enabled —
  confirmed absent from both the command line and
  `settings.py` (no `CELERY_WORKER_SEND_TASK_EVENTS`/`CELERY_TASK_SEND_SENT_EVENT`
  anywhere, re-grepped this task).

**Not set anywhere** (re-confirmed by direct grep this task, matching
the recovery design audit's own enumeration — not assumed carried
over): `task_acks_late` (default `False`), `task_reject_on_worker_lost`
(default `False`), `worker_prefetch_multiplier` (default `4`),
`task_expires` (default `None`), any broker/worker heartbeat
setting (`broker_heartbeat` — Celery/kombu's own default applies,
un-tuned by this project), any task-uniqueness library.

**VERIFIED FROM CONFIGURATION — Redis persistence**: neither Compose
file mounts a volume for the `redis` service or overrides its command
with `--appendonly yes` or any other persistence flag — plain
`redis:7-alpine` with only the image's own baked-in defaults. Whether
a queued-but-undelivered task survives a Redis restart therefore
depends entirely on the base image's default RDB snapshot interval, not
on anything this project explicitly configured — **NOT VERIFIABLE IN
CURRENT ENVIRONMENT** without inspecting the image's actual default
`redis.conf`, which this audit did not do (out of scope for a
read-only, no-container-interaction audit).

---

## 4. Worker Lifecycle

**VERIFIED FROM SOURCE/CONFIGURATION**, retraced this task end to end:

```
Celery beat (own process, `celery -A config beat`)
  → every RECONCILIATION_INTERVAL_SECONDS (config/celery.py's
    add_periodic_task, unchanged since Phase 5), publishes
    'apps.sync.tasks.reconcile_all_sessions_task' to the broker
  → a celery-worker process consumes it, executes
    reconcile_all_sessions_task() (apps/sync/tasks.py), which loops
    over every known WahaSession and calls
    reconcile_session_task.delay(session_name) for each — a SEPARATE
    published message per session
  → some celery-worker process consumes each reconcile_session_task
    message, executes reconcile_session() (apps/sync/reconciliation.py)
  → checkpoint.status = RUNNING, committed to Postgres/SQLite
    IMMEDIATELY (before any WAHA call) — re-verified unchanged this
    task
  → ... reconciliation work ...
  → checkpoint.status = OK or ERROR, committed at the end
```

- **Who schedules**: Celery beat, driven purely by
  `RECONCILIATION_INTERVAL_SECONDS` — no code anywhere checks whether a
  previous cycle's tasks have finished before beat fires the next one
  (re-confirmed, matching the recovery design audit's own finding).
- **Who publishes**: beat publishes the outer task; the outer task's
  own execution (inside whichever worker picks it up) publishes the
  inner, per-session tasks — **VERIFIED**, both are ordinary
  `.delay()` calls.
- **How it reaches the worker**: via the Redis broker (list-based
  queue, Celery's/kombu's standard Redis transport) — no custom
  routing.
- **Task ID availability**: `reconcile_session_task.delay(...)` and
  `reconcile_chat_task.delay(...)` both return a real `AsyncResult`
  object with a genuine `.id` — **VERIFIED FROM SOURCE** this is a
  real, usable value at the call site (`apps/sync/tasks.py`,
  `apps/sync/executors.py`) — but **the return value is discarded at
  every call site**, re-grepped this task (`grep -rn "\.delay("
  apps/sync/` shows every call as a bare statement, its return value
  never assigned to a variable). **No task ID is persisted anywhere** —
  re-confirmed, zero hits for `task_id`/`celery_task_id`/`AsyncResult`
  outside Celery's own library code.
- **Correlation with `SyncCheckpoint`**: **impossible today** — a
  `SyncCheckpoint` row has no column referencing any Celery task, and
  no `AuditLog` entry is written anywhere in the reconciliation path
  (periodic or targeted) — re-confirmed by grep: `apps/sync/` contains
  zero `AuditLog.objects.create(` calls (the only `AuditLog` writer in
  this app is the *new*, Phase 13.A recovery endpoint, which records a
  *recovery action*, not the *original task's* identity).

---

## 5. Existing Health/Liveness Mechanisms

**VERIFIED FROM SOURCE** — the complete result of a repository-wide
search for every term the task asked about
(`inspect|ping|heartbeat|worker_ready|worker_offline|worker_online|events|Flower|health|readiness|liveness|active_tasks|reserved_tasks|scheduled|registered`,
re-run this task):

| Mechanism | Exists? |
|---|---|
| `celery_app.control.inspect()`/`.ping()` | **No** — zero calls anywhere in `backend/`. |
| Worker heartbeat/event consumption (`-E`, `worker_send_task_events`, a `celery events` listener) | **No** — not enabled on the command line or in settings (Section 3). |
| Flower or any other Celery monitoring UI | **No** — not in `requirements.txt` (full list re-read this task: Django, DRF, `psycopg2-binary`, `celery`, `redis`, `gunicorn`, `requests`, `PyJWT`, `cryptography`, `python-dotenv`, `django-cors-headers` — nothing else). |
| Django admin for `SyncCheckpoint` or any Celery-related model | **No** (re-confirmed, matching the recovery design audit's Section 2 finding). |
| Docker healthcheck on `celery-worker`/`celery-beat` | **No** — only the `redis` service has a `healthcheck:` block (dev Compose only; production Compose has none at all, Section 6). |
| `RedisHealthView` (`GET /api/health/redis/`) | **Yes** — but see Section 6; explicitly does not check worker liveness, by its own docstring. |
| `possibly_stuck` (`GET /api/sync/status/`) | **Yes** — but is a `SyncCheckpoint`-derived heuristic (checkpoint age), never a direct worker observation (re-confirmed, unchanged). |

**No existing mechanism exposes**: broker reachable *implies nothing
about* worker process alive, worker registered, worker responding to
commands, worker executing tasks, worker idle, or worker unavailable —
none of these six specific claims can be answered by anything in this
codebase today.

---

## 6. Broker vs. Worker Health — Explicit Distinction

**This is the audit's central, most consequential finding, verified
directly from `RedisHealthView`'s own docstring this task**
(`backend/apps/core/views.py:60-70`, quoted verbatim):

> "Deliberately narrow: a raw `PING` against Redis only, nothing else.
> Does NOT call `celery.control.ping()` or any Celery worker-inspection
> API, and does NOT infer or imply that a reachable Redis means a
> Celery worker is alive — those remain separate, unresolved questions."

**This was written into the code at Phase 9.1C (before this session's
Phase 9.1-lineage work began in earnest) — the project's own prior
authors already explicitly flagged this exact distinction as
unresolved.** This audit re-confirms it remains unresolved, and makes
the full chain of claims explicit:

| Claim | Proven by what exists today? |
|---|---|
| Redis reachable | **Yes** — `RedisHealthView`, a real `PING`. |
| Celery broker reachable | **Same claim as above** — Celery's broker *is* this same Redis instance (`CELERY_BROKER_URL` points at it) — a reachable Redis is a reachable broker, this equivalence genuinely holds. |
| Celery worker process alive | **No.** A `PING` to Redis says nothing about whether any consumer is attached to the queue at all. |
| Celery worker registered (i.e., knows about `reconcile_session_task` etc.) | **No.** Not checked anywhere. |
| Celery worker responsive (answers `control.ping()`/`inspect()`) | **No.** No such call exists in this codebase. |
| Celery task executing | **No.** Only inferable indirectly, after the fact, via `SyncCheckpoint.status == RUNNING` — itself ambiguous (Section 8). |
| Celery task completed | **Yes, indirectly** — `SyncCheckpoint.status` becomes `OK`/`ERROR` — but only if the task got far enough to write that; a killed/crashed task never reaches this write (re-confirmed, unchanged from prior audits). |

**Redis `PING` succeeding proves nothing about Celery worker liveness.**
This is not an inference — it is what the code's own author already
documented, re-verified as still true and still unaddressed.

---

## 7. Reconciliation Task Lifecycle (Detailed)

Already traced in full in Section 4; this section adds the specific
failure-mode answers the task asked for, each **VERIFIED FROM SOURCE**
unless marked otherwise:

- **When checkpoint becomes RUNNING**: immediately, before any WAHA
  call — `reconcile_session()` step (A), unchanged.
- **When checkpoint becomes SUCCESS/ERROR**: only at the very end of a
  fully-executed `reconcile_session()` call — step (B).
- **Worker dies (any cause)**: checkpoint stays `RUNNING` forever — no
  `try/finally`, no redelivery (`task_acks_late=False`).
- **Process killed (`SIGKILL`)**: identical to "worker dies" — a signal
  the task's own Python code cannot intercept.
- **Redis disappears mid-task**: the *already-running* task's own work
  (WAHA HTTP calls via `requests`, direct DB writes via Django's ORM)
  does **not** depend on the broker connection to continue executing —
  **INFERRED** (general Celery/kombu architecture: broker connectivity
  is needed for task dispatch/ack/result-publishing, not for a task
  body's own unrelated I/O) — but the task's *final* result-backend
  write (also Redis, via `CELERY_RESULT_BACKEND`) could fail silently
  if Redis is still down at that moment; this would not prevent the
  `SyncCheckpoint.save()` (a Postgres/SQLite write, unrelated to
  Celery's result backend) from succeeding — **VERIFIED FROM SOURCE**
  that the checkpoint write path has no dependency on
  `CELERY_RESULT_BACKEND` at all.
- **Task exceeds hard time limit (600s)**: the worker pool forcibly
  terminates the child process executing it — **VERIFIED FROM
  CONFIGURATION** that this setting exists; **INFERRED** that it is
  honored by the actual deployed worker pool (Celery's documented
  `prefork`-pool behavior, the implicit default given no `--pool` flag
  is set — not independently live-tested this task, consistent with
  every prior report's same disclosed limitation).
- **Task retries**: re-enters `reconcile_session()` from the top on
  each attempt, re-writing `RUNNING` — up to `max_retries=3`, with
  `retry_backoff=True, retry_backoff_max=600` (`apps/sync/tasks.py`,
  re-read this task) — meaning a **fully healthy, working-as-designed**
  retry sequence can legitimately span several hundred seconds of
  backoff delay alone, before even counting execution time (Section 8,
  scenario H).
- **Task ID availability/persistence/correlation**: Section 4 — real
  but always discarded; never persisted; correlation with
  `SyncCheckpoint` is impossible today.

---

## 8. Failure Scenario Matrix

Each scenario the task specified, with the four required judgments:

| # | Scenario | What the system observes | What it does | What remains unknown | `possibly_stuck` detects it? | 13.A can safely recover it? | Automatic recovery safe? |
|---|---|---|---|---|---|---|---|
| A | Redis unavailable | `RedisHealthView` reports `error`/`503` (VERIFIED — this is exactly what it checks). New task dispatch fails/is delayed. | No new reconciliation starts. An **already-RUNNING** checkpoint (from before Redis went down) is unaffected by this alone. | Whether any queued-but-undelivered message is lost depends on Redis persistence (Section 3 — not verifiable without inspecting the image). | **Not directly** — if nothing is `RUNNING`, `sync_status` shows `stale` (via the *OK*-branch staleness check), not `possibly_stuck` (which requires `status == RUNNING`). A subtle, sourced distinction. | N/A — 13.A's `not_running` rejection correctly no-ops here. | N/A — nothing to recover. |
| B | Worker process stopped (Redis/beat still up) | `RedisHealthView` reports **`ok`** — broker is fine. Queue backs up silently. Any checkpoint already `RUNNING` when the worker stopped stays `RUNNING` forever. | Nothing — no code detects "zero workers." | Whether *any* worker exists at all. | **Yes** — a true positive once 660s elapses (VERIFIED by design). | **Yes** — genuinely safe: with `task_acks_late=False`, an already-acked task cannot be resumed by a later-restarted worker; nothing will ever race 13.A's write for this specific stuck instance. | Only for *this exact* scenario, in isolation — but the system cannot distinguish B from C/D/F/H without more information, so "automatic" would still act blindly across all of them. |
| C | Worker alive but unresponsive (e.g. deadlocked in-task) | Externally identical to B — `RedisHealthView` still `ok`, checkpoint still stuck. | Nothing. | Whether the process is dead or merely wedged. | Yes, same true/ambiguous positive as B. | **Weaker than B**: 13.A only rewrites the *checkpoint row* — it does **not** touch the actual OS process, which (if truly deadlocked) keeps occupying a worker slot indefinitely, silently degrading future task throughput even after the checkpoint is marked `ERROR`. Recovering the *data model's view* is not the same as recovering the *worker*. | No — same ambiguity as B, and the "self-correcting if wrong" safety property (recovery design audit, Section 10) is weaker here: a temporarily-slow-but-alive worker could still finish moments after an automatic action fired. |
| D | Worker killed while `RUNNING` | Checkpoint stuck `RUNNING`. | Nothing. | The kill event itself is never observed by this codebase — only inferred after the fact from staleness. | Yes, true positive. | **Yes**, safest case in this matrix — a `SIGKILL`'d process categorically cannot resume. | Best-case for automatic recovery *if* this scenario could be reliably distinguished from the others — it currently cannot be. |
| E | Worker crashes (Python-level, e.g. unhandled fatal error) | Same as D. | Same as D. | Same as D. | Same as D. | Same as D. | Same as D. |
| F | Worker loses broker connection (network partition, worker process alive) | `RedisHealthView` may report `ok` or `error` depending on whether *this Django process's own* Redis check succeeds — independent of whether the *worker's* connection is partitioned (they are separate TCP connections to the same Redis). An in-progress task's own execution is **not** blocked by this (Section 7). | Kombu's own reconnection logic applies (**INFERRED**, general library behavior, not this project's explicit configuration — only `CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP` is set, which governs *startup* reconnection only, not a later drop). | Whether/when the worker's connection recovers. | Same ambiguity as B/C. | Same ambiguity as B/C. | Same ambiguity as B/C. |
| G | Task exceeds hard time limit (600s) | The pool forcibly kills the child process (INFERRED, per Section 7); checkpoint stuck `RUNNING` at whatever it was at kill time. | Nothing observes the kill event itself. | Whether the limit is actually honored by the real deployed pool (not live-tested). | **Yes — the single most confident true positive this system can identify**, since `POSSIBLY_STUCK_SAFETY_MARGIN_SECONDS=60` was deliberately chosen to sit just past this exact, sourced, enforced ceiling. | **Yes**, safe for the same reason as D — the limit *guarantees* the original task cannot still be legitimately executing past 660s (for the Celery/periodic path specifically — the `'sync'`-executor path has no such guarantee, an already-documented distinction). | Best-justified case for automatic recovery *of all nine scenarios* — but still only for checkpoints known to have entered `RUNNING` via the time-limited Celery path, a provenance this schema cannot currently distinguish from a `'sync'`-executor-originated `RUNNING` state. |
| H | Task retry occurs (normal, healthy operation) | Checkpoint cycles `RUNNING` → (retry) → `RUNNING` → ... — `retry_backoff_max=600` means **a fully healthy 3-attempt retry sequence can legitimately take longer than the 660s `possibly_stuck` threshold**, entirely by design, with nothing wrong at all. | Celery's own retry machinery, unmodified, working exactly as intended. | Whether a given "stuck" reading is a real problem or just Celery doing its job. | **Yes — a concrete, sourced FALSE positive**, not merely a theoretical one (arithmetic: up to 600s of backoff alone, plus execution time per attempt, comfortably exceeds 660s). | **Risky** — an operator (or worse, an automatic policy) marking `ERROR` mid-legitimate-retry wastes that attempt; the CAS guard (Phase 13.A) prevents *data corruption* from this, but does not prevent the *wasted, premature intervention* itself. | **This is the strongest argument in this whole audit against automatic recovery** — a policy that fires on every `possibly_stuck: true` would routinely interrupt healthy, working-as-designed retries. |
| I | Two reconciliation tasks overlap for the same session | Already fully analyzed in the recovery design audit (Section 7/8 there) — re-cited, not re-derived: `reconcile_all_sessions_task` dispatches without checking existing checkpoint status (Section 4), so this is possible **today, without any recovery code at all**. | Checkpoint lost-update race on completion; `Message`/`Chat`/`Contact` remain safe (unique constraints). | Which of the two instances "owns" the checkpoint's final state. | Ambiguous — could fire based on either instance's view of the shared row. | The CAS guard specifically protects 13.A from being fooled by this (matches its design intent, re-confirmed). | No — automatic action based on a read of one instance's state while the other is actively writing multiplies the race surface. |

---

## 9. Task Identity Analysis

**VERIFIED FROM SOURCE** (Section 4, restated for directness): task
identity — `SyncCheckpoint ↔ Celery task ↔ Celery worker` — **does not
exist as a queryable relationship anywhere in this codebase.**

- `task_id`: never captured, never stored — every `.delay()` call's
  return value is discarded (`apps/sync/tasks.py`, `apps/sync/executors.py`).
- `AsyncResult`: never constructed anywhere outside Celery's own
  internals — confirmed by grep, zero application-level usage.
- `request.id` (a task's own reference to itself, from inside its
  `bind=True` context — `reconcile_session_task`/`reconcile_chat_task`
  both use `bind=True`, so `self.request.id` **is available to the
  task's own code**, but is never read or persisted by
  `apps/sync/tasks.py`'s bodies — a real, sourced "the data exists for
  one instant and is thrown away" finding).
- `AuditLog` correlation: none — reconciliation writes zero `AuditLog`
  entries (Section 4).
- **Exactly where identity is lost**: at the `.delay()` call site
  itself, in `apps/sync/tasks.py::reconcile_all_sessions_task()` and
  `apps/sync/executors.py::trigger_reconciliation()` — the return value
  is available in the same statement and simply not assigned to
  anything.

---

## 10. Concurrency Analysis

Re-confirms, does not re-derive, the recovery design audit's own
findings (Sections 7/8 there), with the additions this task's
specific investigation surfaced:

- **No distributed lock, no `select_for_update()`, no task-uniqueness
  library** — re-confirmed absent, zero hits, this task.
- **Two reconciliation tasks for the same session can start today,
  without any code change** — `reconcile_all_sessions_task` does not
  check checkpoint state before dispatching (Section 4/8, scenario I).
- **The compare-and-set guard in Phase 13.A is the only concurrency
  safeguard anywhere in this subsystem** — it protects *that one
  endpoint's write* from racing an in-progress task; it does nothing
  for the underlying dispatch-level race (scenario I) itself, which
  remains fully latent and unaddressed by anything built so far.
- **New this task**: the retry-backoff arithmetic (scenario H) means
  `possibly_stuck`'s false-positive rate under *routine* operation is
  not merely theoretical — `retry_backoff_max=600` alone can produce a
  legitimate multi-hundred-second delay sequence, on top of whatever
  execution time each of the 3 attempts consumes.

---

## 11. Automatic Recovery Implications

**Based strictly on the evidence gathered in Sections 3–10, automatic
recovery is not safe to implement today.** This audit does not merely
repeat the recovery design audit's conclusion — it adds a concrete,
sourced reason beyond concurrency alone:

- **Missing guarantee #1 (already known)**: no way to distinguish a
  dead worker (scenarios B/D/E/G — where 13.A-style recovery would be
  safe) from an alive-but-slow/retrying one (scenarios C/F/H — where it
  would not) using only `SyncCheckpoint` data.
- **Missing guarantee #2 (newly concretized this task)**: scenario H
  shows this is not a rare edge case — Celery's own, already-configured
  `retry_backoff_max=600` makes a false `possibly_stuck` reading a
  *routine*, *expected* outcome of normal retry behavior, not merely a
  theoretical possibility requiring bad luck.
- **Missing guarantee #3**: even in the *best* case for automatic
  recovery (scenario G, the hard time-limit kill), there is no way to
  know *which* checkpoints entered `RUNNING` via the time-limited
  Celery path versus the un-time-limited `'sync'`-executor path — the
  schema does not record provenance, so a policy calibrated for G's
  guarantee cannot be safely scoped to only G's cases.
- **Missing guarantee #4 (recovery design audit, re-confirmed)**: no
  compare-and-set-equivalent protection exists anywhere except the one
  endpoint Phase 13.A itself added — any *automatic* actor would need
  the same CAS discipline, correctly implemented, every time it acts.

**Conclusion, unchanged in substance from the recovery design audit,
now more concretely evidenced**: automatic recovery requires at least
one of (a) reliable worker-liveness information (Section 12, option B
or C) to distinguish true from false positives, or (b) task-identity
persistence (option D) combined with a way to confirm a specific task
is truly gone, or (c) a fundamentally different detection signal than
checkpoint age alone (option E, task-emitted heartbeats) — none of
which exist today.

---

## 12. Future Design Options

Presented without ranking, per the task's own instruction — each
option's proof/non-proof, required changes, and risk, strictly as this
audit's evidence supports:

### A. Redis/broker health only

**Already implemented** (`RedisHealthView`) — listed for completeness
of the taxonomy. Proves: Redis/broker reachable. Does not prove:
anything about worker liveness (Section 6). No further change
described here since it already exists.

### B. Celery inspect/ping endpoint (`celery_app.control.ping(timeout=N)`)

- **Proves**: at least one worker process is alive, connected to the
  broker, and responsive to control-plane messages within `N` seconds.
- **Does NOT prove**: that the *specific* worker/child process
  executing a *particular* stuck reconciliation task is not itself
  wedged — **INFERRED**: Celery's default `prefork` pool architecture
  has the *master* process (not necessarily the busy *child*) answer
  control commands, so a successful `ping()` does not, by itself,
  prove the exact task in question is progressing.
- **Source/config changes**: a new code path only (a view or management
  command) — no `CELERY_*` setting change required.
- **Schema/migration impact**: none.
- **Operational complexity**: moderate — needs a timeout policy and
  must distinguish "zero workers responded" from "timed out" from
  "responded, all idle."
- **Risk to reconciliation data**: none directly — a read-only control
  command.

### C. Worker heartbeat/event monitoring (Celery events, Flower, or a custom event consumer)

- **Proves**: richer, near-real-time worker/task state (online/offline,
  task-started/succeeded/failed) — but **only if actively consumed and
  durably stored somewhere**; the event stream itself is ephemeral.
- **Does NOT prove**: anything, by itself, without a running consumer —
  this option is really "add a new, separate long-running service,"
  not a configuration flag.
- **Source/config changes**: `-E`/`worker_send_task_events=True`, plus
  a new consumer process (Flower or custom).
- **Schema/migration impact**: likely yes, if durability across
  restarts is wanted (a new model to persist observed events).
- **Operational complexity**: highest of the non-automatic options — a
  new component that itself needs to be kept running and monitored.
- **Risk to reconciliation data**: low directly, but adds a new failure
  surface (the monitor's own downtime).

### D. Persist Celery task ID (new `celery_task_id` field on `SyncCheckpoint`)

- **Proves**: task *identity* is retained, enabling later
  `AsyncResult(task_id)` lookups.
- **Does NOT prove liveness by itself**: with `task_acks_late=False`
  and no event backend, a killed task's `AsyncResult.state` would
  likely remain `STARTED` (since `CELERY_TASK_TRACK_STARTED=True`)
  forever too — **INFERRED** — so D alone does not resolve the
  ambiguity Section 8 identifies; it becomes useful mainly in
  combination with B (ping first, then use the ID to inspect further)
  or as a prerequisite for task revocation (the recovery design audit's
  candidate D).
- **Source/config changes**: capture `.delay()`'s return value at each
  call site (`apps/sync/tasks.py`, `apps/sync/executors.py`).
- **Schema/migration impact**: yes — a new column, a migration.
- **Operational complexity**: low-moderate.
- **Risk to reconciliation data**: none directly, but touches the exact
  write path every prior Phase 9-lineage task this session has
  deliberately left untouched — a real scope expansion, not a trivial
  addition.

### E. Task state tracking / in-task heartbeat (e.g., `reconcile_session()` itself periodically touches a `last_heartbeat_at` field)

- **Proves**: the most *direct* possible signal — progress reported
  from inside the task's own execution, not inferred externally.
- **Does NOT prove**: anything if the task is wedged in a way that
  never reaches the heartbeat-touching code (mitigated, not
  eliminated, by `WahaClient`'s existing 10s per-call timeout bounding
  any single blocking point).
- **Source/config changes**: modifies `reconcile_session()`'s actual
  write path — the loop body itself.
- **Schema/migration impact**: yes — a new field (or a repurposed
  meaning for an existing one).
- **Operational complexity**: moderate to implement, but conceptually
  the most direct of all seven options.
- **Risk to reconciliation data**: **highest of the detection-only
  options** — it is the only one that touches the reconciliation loop's
  own logic, the file every prior related audit and implementation this
  session has been careful to leave untouched; a bug in heartbeat-writing
  code could itself slow or corrupt the main loop.

### F. Distributed locking (Redis-based lock, or Celery task uniqueness)

- **Proves**: (if implemented correctly) at most one
  `reconcile_session()` execution is active per session at a time —
  **prevents** scenario I rather than merely detecting its aftermath.
- **Does NOT prove**: worker liveness on its own — a lock held by a
  dead worker is its own classic problem, requiring a lock TTL (which
  reintroduces a threshold-choice problem structurally similar to
  `possibly_stuck`'s own).
- **Source/config changes**: new acquire/release logic wrapping
  `reconcile_session()`'s callers, correctly handling the exact kind of
  `try/finally`-shaped gap already identified as missing from
  `reconcile_session()` itself (recovery design audit, Section 4).
- **Schema/migration impact**: none required for a pure Redis-key lock.
- **Operational complexity**: moderate.
- **Risk to reconciliation data**: a buggy lock could itself silently
  stop reconciliation from ever running (a fail-closed risk this
  project does not have today).

### G. Automatic recovery

- **Proves nothing by itself** — it is an *action*, not a detection
  mechanism; its safety is entirely a function of how well-informed the
  decision to act is (i.e., depends on B–F above).
- **Does NOT prove correctness of any individual decision** — Section
  11's findings apply in full.
- **Source/config changes, schema impact, complexity, risk**: as
  extensively covered in the recovery design audit (Sections 10–14
  there) — not re-derived here; this audit's contribution is Section
  8/11's concrete evidence that the false-positive surface is larger
  and more routine than previously demonstrated (scenario H).

---

## 13. User Decisions Required

Per the task's own escalation bar (architecture/security/data-integrity/
schema/operational behavior only):

1. **Whether worker liveness should be exposed as an API** (option B) —
   a genuine new capability decision; not required for anything built
   so far to keep working.
2. **Whether task IDs should be persisted** (option D) — a schema
   change (migration) touching the reconciliation write path directly.
3. **Whether worker events should be introduced** (option C) — a new,
   separately-operated long-running component, a real operational
   commitment beyond this codebase's current footprint.
4. **Whether distributed locking should be introduced** (option F) — an
   architectural addition that changes reconciliation's concurrency
   model, independent of and prior to any worker-liveness question.
5. **Whether automatic recovery is desired at all** — already asked in
   the recovery design audit; restated here because this audit's
   scenario H finding (Section 8) is new, concrete evidence directly
   bearing on that same decision.
6. **Whether an in-task heartbeat (option E) is an acceptable scope** —
   this is the one option that would require modifying
   `reconcile_session()`'s own logic, a file every related task this
   session has otherwise kept untouched by deliberate choice; flagged
   separately because it's a materially different kind of change than
   B/C/D/F (all of which can be built *around* reconciliation without
   touching it).

**Not escalated** (per the task's own instruction): naming, README
wording, report formatting, command ordering.

---

## 14. Files Inspected

`backend/config/settings.py` (full `CELERY_*` block),
`backend/config/celery.py`, `backend/apps/sync/tasks.py`,
`backend/apps/sync/executors.py`, `backend/apps/sync/reconciliation.py`,
`backend/apps/sync/models.py`, `backend/apps/sync/views.py`,
`backend/apps/core/views.py` (`RedisHealthView`),
`backend/apps/audit/models.py`, `backend/apps/authn/permissions.py`
(read, not modified), `backend/requirements.txt`,
`infrastructure/development/office.yml`,
`infrastructure/office/docker-compose.yml`, plus repository-wide greps
for every term the task's Section 2/7 asked about. `docker ps` was run
once (live-environment observation only — confirmed only
`wamora-dev-tencent-bff-1`/`wamora-dev-tencent-frontend-1` running,
Office-side stack not running, unchanged from every prior task this
session).

---

## 15. Files Intentionally Not Changed

Every file this audit read (Section 14) — confirmed via `git status`
before and after this task showing no new modifications beyond what
already existed from prior, separate tasks this session. Specifically
untouched, per the task's explicit scope: `config/celery.py`,
`config/settings.py`, `apps/sync/reconciliation.py`, `apps/sync/tasks.py`,
`apps/sync/executors.py`, `apps/sync/models.py`, `apps/sync/views.py`
(including the just-implemented `SyncCheckpointRecoveryView` and
`_is_possibly_stuck()` — both re-read, not re-written), any migration,
any Docker/Compose file, any `.env` file, any BFF or frontend file.

---

## 16. Final Conclusion

**What is currently provable**: Redis/broker reachability
(`RedisHealthView`); a `SyncCheckpoint`'s own recorded status and how
long it has held that status (`possibly_stuck`); that a manual,
CAS-protected operator action can safely mark a flagged checkpoint
`ERROR` without racing a concurrent write (Phase 13.A).

**What is not currently provable**: whether any Celery worker process
exists at all; whether a specific worker is registered, responsive, or
executing a specific task; whether a `possibly_stuck` reading reflects
a dead worker, a merely-slow one, a network partition, or — routinely —
a perfectly healthy retry-backoff sequence (Section 8, scenario H).
Task identity (`SyncCheckpoint ↔ Celery task ↔ worker`) is available
for a single instant at each `.delay()` call site and is discarded
every time (Section 9).

**Whether automatic recovery is currently safe**: **no.** Beyond the
concurrency risks the recovery design audit already established, this
audit adds concrete evidence that the detection signal itself
(`possibly_stuck`) produces false positives under **routine, working-
as-designed** operation (Celery's own configured retry backoff),
meaning an automatic policy would not merely risk rare edge cases but
would predictably interfere with ordinary retries.

**Exact USER DECISIONS REQUIRED**: Section 13, items 1–6 — whether to
build a worker-liveness API (B), persist task IDs (D), introduce event
monitoring (C), introduce distributed locking (F), pursue automatic
recovery at all (G), and whether modifying `reconcile_session()`'s own
logic for an in-task heartbeat (E) is an acceptable scope, given every
other option can be built without touching it.

**STOP.** This was a design audit only. No worker-liveness mechanism,
no Celery inspect endpoint, no heartbeat, no task ID persistence, no
migration, no distributed locking, no reconciliation/Celery/Docker
change, and no automatic recovery were implemented. Phase 13.B and any
other future phase were not started. Awaiting the user's decisions in
Section 13 before any further action.
