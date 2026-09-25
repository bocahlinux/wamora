# Reconciliation Execution Observability — Design Audit Report

> **Phase labeling note (added 2026-09-26, per
> `docs/generated/PHASE-ROADMAP-STATUS-AUDIT-REPORT.md`):** this report
> refers to prior work as "Phase 13.A". That label is NOT part of the
> canonical roadmap's Phase 13 ("Failure/security testing",
> `docs/15-CODING-PHASES.md`) — it is properly a continuation of Phase 4
> ("Reconciliation") and Phase 9 ("Offline/degraded mode"). The "13.A"
> numbering was informal, originating from an internal subsection label
> in `NEXT-PHASE-RECONCILIATION-RECOVERY-DESIGN-AUDIT-REPORT.md`, and is
> not an official roadmap sub-phase. See
> `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` for the recorded decision.

**This is a read-only design audit. No source, config, test, Docker,
Compose, `.env`, migration, or database-schema file was modified. No
container was started, stopped, or restarted. No reconciliation was
triggered. No Celery task was called. No recovery was performed. The
running development stack was not touched.**

**Conclusion up front:** the smallest architectural change that would
materially improve "why is this checkpoint RUNNING?" does **not**
require a new database table — it requires **two new, nullable
`SyncCheckpoint` fields** (a trigger-provenance marker and an optional
Celery task ID), touched only at `reconcile_session()`'s existing
entry/exit points, never its internal loop. This audit also surfaces a
**third, previously-undocumented execution path** —
`python manage.py reconcile <session>` (`apps/sync/management/commands/reconcile.py`)
— a fully synchronous, foreground, non-Celery, non-HTTP-request-scoped
trigger with **zero** of the time-limit/retry protections either other
path has, making it the single most exposed path in this system for
the stuck-`RUNNING` problem. A richer, fully race-eliminating design
(a dedicated per-execution record, Option B below) is described but
**not recommended as the immediate next step**, per Step 6's own
"smallest change" instruction — it remains available as a larger,
separately-decided future option.

---

## 1. Objective

Design, without implementing, the minimum reliable information this
system would need to answer, for a given session: **"why is its
reconciliation checkpoint RUNNING?"** — distinguishing, as far as
technically possible, the ten cases the task named (periodic vs.
manual/sync trigger, queued vs. executing vs. retrying vs.
time-limit-killed, worker disappearance, success, failure, and an
unrecoverable stale state).

---

## 2. Current Execution Lifecycle

**VERIFIED FROM SOURCE** — every file below was re-read directly this
task, not carried over from either prior related audit.

### 2.1 — Three trigger paths (not two — a new finding)

Prior audits this session documented two trigger paths. Re-tracing
"all callers of `reconcile_session`" from scratch this task
(`grep -rn "reconcile_session(\|reconcile_session_task\|reconcile_chat_task\|trigger_reconciliation("`,
excluding tests) surfaces a **third**:

```
1. PERIODIC (always Celery, regardless of RECONCILIATION_EXECUTOR)
   Celery beat --(every RECONCILIATION_INTERVAL_SECONDS)--> reconcile_all_sessions_task
     --.delay()--> reconcile_session_task (bind=True, max_retries=3,
                    autoretry_for=(Exception,), retry_backoff=True,
                    retry_backoff_max=600, retry_jitter=True)
       --> reconcile_session(session_name)              [full session, all chats]

2. TARGETED (post-send, apps.sync.executors.trigger_reconciliation())
   settings.RECONCILIATION_EXECUTOR == 'sync':
     --> run_targeted_reconciliation_with_retry() runs IN-PROCESS,
         inside the Django request/response cycle that handled the
         internal /internal/reconciliation/trigger/ call from the BFF
       --> reconcile_session(session_name, chat_ids=[chat_id])
   settings.RECONCILIATION_EXECUTOR == 'celery':
     --.delay()--> reconcile_chat_task (same retry config as above)
       --> run_targeted_reconciliation_with_retry()
         --> reconcile_session(session_name, chat_ids=[chat_id])

3. MANUAL CLI — NEWLY DOCUMENTED THIS AUDIT
   `python manage.py reconcile <session_name> [--chat ID] [--limit N] [--max-pages N]`
   (apps/sync/management/commands/reconcile.py)
     --> reconcile_session(session_name, chat_ids=..., limit=..., max_pages=...)
   Runs synchronously in whatever foreground process invokes the
   management command — NOT a Celery task, NOT inside a Django HTTP
   request. No time limit, no retry, no ack semantics of any kind. If
   this process is killed (Ctrl+C, a dropped SSH session, a container
   restart mid-command), the checkpoint is left exactly as exposed as
   every other stuck-RUNNING scenario — with even less surrounding
   infrastructure than either other path.
```

### 2.2 — `reconcile_session()`'s own lifecycle (unchanged, re-verified line-by-line this task)

```
trigger (one of the three paths above)
  → session = WahaSession.objects.get(name=session_name)
  → checkpoint, _ = SyncCheckpoint.objects.get_or_create(session=session)
  → pre-run watermark read once (checkpoint.checkpoint_value)
  → QUEUED->EXECUTING BOUNDARY:
      checkpoint.status = RUNNING
      checkpoint.save(update_fields=['status', 'updated_at'])   -- (A), committed immediately
  → [chat discovery, best-effort, chat_ids is None only]
  → PROGRESS (per chat, per WAHA history page, per message):
      each persist_message() call is its OWN transaction.atomic(),
      committed immediately, independent of the checkpoint's own state
  → SUCCESS/FAILURE BOUNDARY:
      checkpoint.last_run_at = now()
      status = ERROR (any chat/message error) or OK
      checkpoint_value advanced ONLY on a fully-clean OK run
      checkpoint.save(update_fields=[...])                       -- (B), a single
                                                                     UPDATE statement,
                                                                     NOT wrapped in
                                                                     transaction.atomic()
                                                                     (re-confirmed this
                                                                     task — see Section 6,
                                                                     scenario 12)
```

### 2.3 — Where information is currently lost

**VERIFIED FROM SOURCE**, each a concrete, named point:

1. **At the `.delay()`/`run_targeted_reconciliation_with_retry()`/CLI
   call site**: which of the three trigger paths initiated this run is
   known to the caller at that exact moment, and is never passed into
   `reconcile_session()` or recorded anywhere — `reconcile_session()`'s
   own signature has no `trigger_source` parameter.
2. **At the same call sites**: the real, usable `AsyncResult`/task `.id`
   (for the two Celery-executed paths) is available and discarded —
   re-confirmed, zero assignment of any `.delay()` return value anywhere
   in `apps/sync/`.
3. **Inside a bound task's own execution**: `self.request.id`
   (the task's own ID), `self.request.retries` (current retry count),
   and `self.request.hostname` (the worker processing it) are all
   real, standard Celery `Context` attributes available to
   `reconcile_session_task`/`reconcile_chat_task` (both `bind=True`) —
   **INFERRED** (documented Celery API, not exercised or tested by
   this codebase) — and none of the three is ever read.
4. **At checkpoint write (A)**: no marker distinguishes *why* this
   particular `RUNNING` transition happened (periodic vs. targeted vs.
   manual) — every path converges on the identical
   `checkpoint.status = RUNNING; checkpoint.save(...)` call.
5. **Between the end of the per-chat loop and write (B)**: if the
   process is killed in this exact window, every already-processed
   `Message` is durably committed (each had its own
   `transaction.atomic()`), but `checkpoint.status` never advances past
   `RUNNING` and `checkpoint_value` never advances at all — the
   underlying *data* is completely correct and complete, but the
   *bookkeeping* is indistinguishable from a run that made zero
   progress. Section 6, scenario 5, elaborates.

---

## 3. Existing Identifiers

**VERIFIED FROM SOURCE**, each traced to its origin, current existence,
persistence, survival, and correlatability:

| Identifier | Origin | Currently exists? | Persisted? | Survives process/task failure? | Correlatable with `SyncCheckpoint`? |
|---|---|---|---|---|---|
| Celery task ID (`AsyncResult.id`) | Return value of every `.delay()` call | Yes, momentarily, at the call site | **No** — discarded everywhere | N/A — never stored | **No** |
| `self.request.id` (task's own view of its ID) | Celery's `Context`, inside `bind=True` tasks | Yes, inside the task body | No | No | No |
| Session ID | `WahaSession.pk`/`.name` | Yes | Yes (it's the FK on `SyncCheckpoint` itself) | Yes | **Yes — this is the only identifier that already works.** |
| Reconciliation "run ID" | N/A | **Does not exist as a concept anywhere** — there is no per-execution row of any kind, only the one mutable `SyncCheckpoint` per session | No | No | No |
| Worker hostname | `self.request.hostname` | Yes, inside the task body (Celery-executed paths only — N/A for manual CLI/`'sync'` executor, which run in a Django/CLI process, not a Celery worker) | No | No | No |
| Worker PID | — | **Not available to application code at all** via any documented, portable Celery API this project uses — **INFERRED**, not confirmed present anywhere. |
| Task state (`PENDING`/`STARTED`/`SUCCESS`/`FAILURE`/`RETRY`) | Celery's result backend (`CELERY_RESULT_BACKEND`, configured, unused) | Exists in Redis *if* the task ID were known and queried via `AsyncResult(id).state` | Yes, in Redis, transiently (Celery's own `result_expires` default) | Only if the *state transition itself* was written before the failure — a killed task's last recorded state would likely remain `STARTED` forever (`CELERY_TASK_TRACK_STARTED=True`) — **INFERRED**, not live-tested. | No — moot without a persisted task ID. |
| Retry count | `self.request.retries` | Yes, inside the task body | No | No | No |
| Execution start time | `checkpoint.updated_at` at the moment of write (A) | Yes — but this is the **checkpoint's** timestamp, not a specific *execution's* — if two executions race (Section 5), this single value cannot represent both. | Yes (on `SyncCheckpoint`) | Yes | Yes, but ambiguously shared. |
| Execution heartbeat | — | **Does not exist** — nothing updates any timestamp *during* the per-chat/per-page loop; `updated_at` only moves at write (A) and write (B), never in between. | No | No | No |
| Execution completion time | `checkpoint.last_run_at` | Yes — but only written on a *fully executed* run (write B) — a killed/crashed run never reaches it. | Yes | **No** — this is exactly the gap `possibly_stuck` exists to approximate. | Yes, but only for completed runs. |

**Bottom line, matching the worker-liveness audit's own Section 9,
re-verified independently this task**: every identifier that *could*
answer "which execution, on which worker, in what state" exists for at
most the lifetime of one function call or one task's in-memory
`Context` — none of it reaches durable storage.

---

## 4. Information Currently Lost — Summary

Consolidating Section 2.3/3 into the specific list the task asked to
distinguish:

| # | Distinction needed | Currently answerable? |
|---|---|---|
| 1 | Periodic Celery reconciliation | No — not recorded at the checkpoint |
| 2 | Manual/synchronous trigger | No — and this audit found a *third* manual path (2.1) beyond the two previously documented |
| 3 | Queued but not yet executing | No — `SyncCheckpoint` has no state for "dispatched, not yet started"; it only ever sees `RUNNING` once execution has already begun |
| 4 | Currently executing | Only as `status == RUNNING`, indistinguishable from cases 5–7 below |
| 5 | Retry/backoff in progress | No — a retrying task re-enters at write (A) exactly like a fresh run |
| 6 | Exceeded hard time limit | No — inferred only indirectly, after the fact, via `possibly_stuck`'s elapsed-time heuristic |
| 7 | Worker disappeared during execution | No — identical observable state to case 6 |
| 8 | Completed successfully | Yes — `status == OK` |
| 9 | Failed | Yes — `status == ERROR` |
| 10 | Stale `RUNNING`, origin unrecoverable | Yes, this is exactly what `possibly_stuck` reports — but it cannot say *which* of cases 3–7 produced it |

---

## 5. Concurrency Analysis

**VERIFIED FROM SOURCE**, re-confirmed this task (not assumed from
either prior audit): no `select_for_update()`, no distributed lock, no
task-uniqueness mechanism exists anywhere in `backend/`.
`reconcile_all_sessions_task` dispatches per known `WahaSession` without
checking that session's current checkpoint status — two executions for
the same session can start today without any code change, from any
combination of the three trigger paths (e.g. a periodic dispatch
overlapping a manually-run `manage.py reconcile`).

**The requested race, traced exactly against the real code**
(`reconciliation.py:183-246`):

```
Task A: checkpoint.status = RUNNING; checkpoint.save(['status','updated_at'])   -- both read
Task B: checkpoint.status = RUNNING; checkpoint.save(['status','updated_at'])   -- the SAME
                                                                                    pre-run
                                                                                    checkpoint_value
                                                                                    watermark
                                                                                    (neither has
                                                                                    advanced it yet)
Task A: [... processes its chats, computes its own latest_timestamp ...]
Task B: [... processes its chats, computes its own latest_timestamp ...]
Task A: checkpoint.save(['status','last_run_at','last_error','checkpoint_value','updated_at'])
Task B: checkpoint.save(['status','last_run_at','last_error','checkpoint_value','updated_at'])
```

- **Which state wins**: whichever of A/B's final write (B) commits
  **last** — a plain, unconditional `.save()`, no compare-and-set, no
  version check. This is the exact same lost-update mechanism the
  recovery design audit already identified for a *recovery* write
  racing an *original* task; here it is the **original tasks racing
  each other**, an even more fundamental instance of the same root
  cause.
- **What information is lost**: whichever of A/B's `checkpoint_value`/
  `last_run_at`/`status` was NOT the last one written is silently
  discarded — if A processed *more* history than B but B finishes
  *later*, the final `checkpoint_value` reflects B's (possibly less
  complete) view, not A's. No data is lost at the `Message` level
  (idempotent, Section 6 notes this again), but the *watermark*'s
  accuracy is not guaranteed to reflect the *most complete* of the two
  runs, only the *most recent to finish*.
- **Can task IDs alone solve this?** **No** — persisting a task ID
  (Section 7, option A) tells you *which* task wrote last, but does
  not by itself *prevent* the write, nor does it tell a reader which
  of two IDs represents the "better" outcome — it's a forensic aid,
  not a concurrency control.
- **Is row locking required?** `select_for_update()` would serialize A
  and B's *final writes* (whichever acquires the lock first blocks the
  other until it commits) — this would prevent the lost-update
  specifically, though the two runs' *duplicate WAHA fetching* would
  still have already happened by the time either reaches the lock.
- **Is compare-and-set sufficient?** For *detecting* that a race
  happened (Phase 13.A's own technique) — yes. For *preventing* two
  runs from happening in the first place — no; CAS only protects one
  specific write against overwriting a state it didn't expect, it does
  not stop two writers from attempting.
- **Is distributed locking required?** Only to prevent the race at its
  *source* (stop the second execution from ever starting) — genuinely
  the most complete fix, but a real new architectural component
  (already named as Option F in the worker-liveness audit; not
  re-designed here).
- **Would a dedicated execution record eliminate the ambiguity?**
  **Partially, structurally, by construction** — if each execution
  wrote to its **own** new row (Section 7, option B) rather than a
  single shared `SyncCheckpoint` row, A and B's own bookkeeping could
  never collide with each other. The **session-level watermark**
  (`checkpoint_value`) would still need eventual, shared coordination
  across whichever executions touch it — so option B reduces, but does
  not by itself fully eliminate, this race; it would still need a
  final "which execution's result is authoritative" reconciliation
  step of its own.

---

## 6. Failure Matrix

All 12 scenarios the task specified, **VERIFIED FROM SOURCE** unless
marked otherwise:

| # | Scenario | State that exists now | What an observer can know | What remains ambiguous | Automatic recovery safe? |
|---|---|---|---|---|---|
| 1 | Task queued (dispatched, not yet started) | No `SyncCheckpoint` change at all — `RUNNING` is only written once execution *begins* (write A), not at dispatch. | Nothing — a queued task is invisible to this system entirely. | Whether it's queued, lost, or the broker never received it. | N/A — nothing to recover; the checkpoint hasn't even transitioned yet. |
| 2 | Worker starts task | `checkpoint.status = RUNNING`, `updated_at` = now. | That *some* execution has begun. | Which of the three trigger paths; which worker; the task's own ID. | N/A — this is the normal, expected first moment of a healthy run. |
| 3 | Worker dies before checkpoint update (i.e., before write A even completes) | Checkpoint unchanged from whatever it was before this attempt (e.g. still `OK`/`ERROR` from the prior run, or `IDLE` if brand new). | Nothing distinguishes "about to start" from "never dispatched." | Whether an attempt was even made. | N/A — no `RUNNING` state exists to recover from. |
| 4 | Worker dies during reconciliation (after write A, mid-loop) | Checkpoint stuck at `RUNNING`, `updated_at` frozen at write-A's timestamp. | That *an* execution started and never finished. | Which path, which worker, how much progress was made. | Per the worker-liveness audit — only with a reliable liveness/time-limit signal, not from checkpoint data alone. |
| 5 | Worker dies after successful data writes but before checkpoint finalization | **All `Message` rows for this run ARE durably committed** (each `persist_message()` call is its own `transaction.atomic()`, already flushed) — but `checkpoint.status` is still `RUNNING` and `checkpoint_value` never advanced, **identical in appearance to scenario 4 despite the underlying data being 100% complete.** | Nothing distinguishes this from scenario 4 — this is the same observable state. | Whether *any* useful work happened at all (it did, fully) — this ambiguity has a real, if modest, cost: the *next* successful run will safely (idempotently) re-fetch and re-skip all the same messages, since `checkpoint_value` never advanced — wasted WAHA calls, not data loss. | Same as 4 — and marking `ERROR` here (via 13.A or automatically) is *functionally* safe (no data risk) even though it undersells how much progress actually happened. |
| 6 | Task retries (healthy, working-as-designed) | Checkpoint cycles back to `RUNNING` on each attempt; `retry_backoff_max=600` (re-verified this task) means a legitimate multi-hundred-second gap between attempts is normal. | That a retry is in progress **only if** the worker-liveness audit's own scenario H analysis is consulted — `SyncCheckpoint` alone cannot show "attempt 2 of 3, backing off" vs. "genuinely stuck." | Current retry count (`self.request.retries`, available but unread). | **Not safe** — re-confirms the worker-liveness audit's strongest finding; a routine retry sequence can trivially exceed `possibly_stuck`'s 660s threshold. |
| 7 | Task reaches hard time limit (600s) | Pool forcibly kills the child; checkpoint stuck `RUNNING`. | The **most confident true positive** available (Section 4 of the worker-liveness audit, re-confirmed) — but only for the periodic/Celery-executed path, which is the only one this specific limit applies to. | Whether *this specific* stuck checkpoint came from the time-limited path or one of the other two (Section 2.1) — currently indistinguishable. | Best-justified case *if* provenance were known (Section 9). |
| 8 | Manual synchronous execution (`'sync'`-executor OR the newly-documented CLI path, 2.1) | Identical `RUNNING`→`OK`/`ERROR` cycle, but with **zero** Celery-level protections — no time limit, no retry, no ack semantics. The CLI path additionally has no Django-request-timeout bound either. | Nothing distinguishes a stuck CLI-triggered checkpoint from any other — currently the *most* exposed, *least* observable of all three paths. | Everything Section 4 already lists, plus: for the CLI path, there isn't even a request/response cycle whose failure would be logged anywhere structured (just whatever the operator's own terminal/shell session captured). | Not safe — same ambiguity as every other RUNNING state, with even less surrounding context. |
| 9 | Duplicate/overlapping execution for the same session | Section 5's exact race. | That the checkpoint is `RUNNING` (or shows a possibly-inconsistent final state). | Which of the overlapping executions "won" the final write; whether the watermark reflects the more complete run. | Not safe — an automatic actor acting on one instance's stale read multiplies the race surface (recovery design audit, Section 7). |
| 10 | Process restart (Django process, mid the `'sync'`-executor or CLI path) | Identical to worker-death scenarios (4/5) — whatever was last durably committed remains; the in-flight Python call is simply gone. | Same as 4/5. | Same as 4/5. | Same as 4/5. |
| 11 | Redis restart | If mid-execution (task already dispatched and consumed, `task_acks_late=False`): the in-progress task's own work is **unaffected** — it needs the broker again only to publish its own result, not to continue its own HTTP/DB work (**VERIFIED FROM SOURCE reasoning**, re-confirmed from the worker-liveness audit's own Section 7, not re-derived). If a message was queued but not yet consumed: survival depends on Redis's own persistence configuration, which this project does not explicitly set (Section 3 of the worker-liveness audit — **NOT VERIFIABLE IN CURRENT ENVIRONMENT** without inspecting the base image's default `redis.conf`). | Whether Redis is currently reachable (`RedisHealthView`). | Whether any specific queued message survived. | N/A directly — this scenario's risk is to *dispatch*, not to an already-`RUNNING` checkpoint's data. |
| 12 | Database (PostgreSQL) restart | If this happens exactly during write (A) or write (B): the UPDATE statement itself fails outright (connection error) rather than partially applying — **VERIFIED FROM SOURCE**: write (B) is a single, unwrapped `.save(update_fields=[...])` call, i.e. one SQL `UPDATE` statement, which is atomic at the statement level regardless of the surrounding Python not being wrapped in `transaction.atomic()`. The exception then propagates exactly as an "unexpected exception" (Section 4 of the worker-liveness audit) — caught/retried for the Celery paths, uncaught for `'sync'`/CLI. | That the checkpoint remains at whatever its last *successfully committed* state was (almost always still `RUNNING`, since write A already succeeded earlier). | Whether the failure happened at (A) or deep into the loop. | Not safe — identical ambiguity to every other mid-run failure. |

---

## 7. Observability Options A–J

Presented without ranking, per the task's own instruction — options
A/D/G/H overlap in substance with the worker-liveness audit's own B/D/C/—
respectively; restated here in this task's own lettering and extended
with the genuinely new options (B, F, I, J) that audit did not cover.

### A. Persist Celery task ID on `SyncCheckpoint`

- **Proves**: task identity survives past the `.delay()` call.
- **Does not prove**: liveness (Section 3 — `AsyncResult.state` for a
  killed task likely stays `STARTED` forever, **INFERRED**, unchanged
  finding from the worker-liveness audit).
- **Schema**: one new nullable column, a migration.
- **Race conditions**: does not itself prevent Section 5's race; two
  concurrent executions would each want to write *their own*
  `task_id` to the *same* shared column — another instance of the
  same lost-update pattern, one field wider.
- **After worker crash**: the ID remains on the row, pointing at a
  task that will never report back — useful only in combination with
  a liveness check (options G/H).
- **During retry**: each retry attempt could be a fresh `self.request.id`
  or the same one, depending on Celery's own retry mechanics
  (**INFERRED**, not tested) — would need explicit handling either way.
- **During manual `'sync'`/CLI execution**: N/A — no Celery task exists;
  the field would simply stay `null` for these paths, itself a useful
  signal (Section 8).
- **Operational complexity**: low.
- **Supports safe automatic recovery?**: only as one ingredient among
  several (Section 9) — not sufficient alone.

### B. Dedicated reconciliation run/execution record (a new model)

- **Proves**: the richest option here — a genuinely new,
  **append-only** row per execution attempt (session, trigger_source,
  executor, celery_task_id, started_at, finished_at, status, and
  optionally the full `ReconciliationResult` summary currently computed
  in-memory and discarded — directly closing the original Phase 9.1
  design audit's own named "gap 5," durable record of how much a run
  recovered).
- **Does not prove**: worker liveness by itself (same limitation as A)
  — still needs a liveness signal to distinguish a genuinely dead
  execution from a slow one.
- **Schema**: a new table, a migration — the largest schema change of
  any option here.
- **Race conditions**: **structurally reduced, not eliminated** —
  Section 5's exact race becomes impossible *at the execution-record
  level* (each execution gets its own row, `.objects.create()` not a
  shared mutable row), but the session-level `checkpoint_value`
  watermark on `SyncCheckpoint` would still need a final, shared
  reconciliation step across whichever execution records finish —
  narrower race, not zero.
- **After worker crash**: the execution row stays `running` forever
  (same fundamental gap as today, just on a richer row) — still needs
  a stuck-detection heuristic, now with far more context available to
  it (trigger_source, executor, task_id all present on that same row).
- **During retry**: a real design decision this audit does not resolve
  — one row per Celery-level retry attempt, or one row updated across
  attempts — both are defensible, with different implications for
  "how many rows accumulate."
- **During manual `'sync'`/CLI execution**: works uniformly — the model
  is executor-agnostic by construction, its `executor`/`trigger_source`
  fields are exactly what would record this distinction directly.
- **Operational complexity**: moderate — a new table to query/prune
  over time (an execution-record history could grow unboundedly
  without a retention policy, itself a new, small operational concern).
- **Supports safe automatic recovery?**: **the strongest foundation of
  any option in this list** — with `trigger_source`/`executor` on the
  SAME row as `started_at`, a policy could correctly scope itself to
  *only* auto-act on periodic-Celery-sourced executions past the
  600s+margin hard limit (closing the worker-liveness audit's own
  "Missing guarantee #3" precisely) while leaving `'sync'`/CLI-sourced
  executions to manual review only.

### C. Add heartbeat timestamps

Same option as the worker-liveness audit's own "E" (in-task heartbeat)
— not re-derived in full here. **Proves**: the most direct
still-alive signal. **Does not prove**: anything if the wedge point
never reaches the heartbeat-touching code. **Schema**: a new field.
**Risk**: touches `reconcile_session()`'s internal loop body — the
only option (besides B, if execution-scoped heartbeats were added to
it) that requires modifying code *inside* the loop, not just its
entry/exit points.

### D. Add execution status/state (beyond the current 4-value `STATUS_CHOICES`)

- **Proves**: a richer vocabulary than `idle/running/ok/error` could
  represent (e.g. `queued`, `retrying`, `time_limit_exceeded`) — but
  **only if something actually writes these more granular values**,
  which nothing currently does or is designed here to do.
- **Does not prove**: anything on its own — a schema/enum change
  without a corresponding write-path change is inert.
- **Schema**: extending `STATUS_CHOICES` is a data-only change (no
  migration needed for the choices tuple itself, since Django
  `CharField` choices are validated at the application layer, not the
  database schema) — but *populating* the new values correctly would
  require the same trigger_source/task_id context options A/B provide.
- **Risk**: extending `_derive_sync_status()`'s existing five-value
  `sync_status` contract to reflect new granularity would be an API
  contract change (`docs/CLAUDE.md` rule 8) — worth flagging
  explicitly, not silently assumed acceptable.

### E. Add executor type

- **Proves**: which of `'sync'`/`'celery'` handled a given targeted
  trigger — a narrower slice of what B's `executor` field would
  capture.
- **Does not prove**: which of the *three* trigger paths (periodic vs.
  targeted vs. manual CLI) initiated the run — `RECONCILIATION_EXECUTOR`
  only governs the *targeted* path's own dispatch mechanism (Section
  2.1); the periodic path is unconditionally Celery, and the CLI path
  is unconditionally neither.
- **Schema**: one small field, a migration.
- Genuinely useful only in combination with a `trigger_source` field
  (Section 8's actual recommendation combines both, minimally).

### F. Add worker hostname/task metadata

- **Proves**: which physical/container worker processed a given task
  (`self.request.hostname`, already available, Section 3) — useful
  forensic detail once a stuck checkpoint is being investigated.
- **Does not prove**: liveness — a hostname is a static label, not a
  live signal.
- **Schema**: a field (or bundled into B's richer row).
- **Operational complexity**: low to capture, low value without a
  liveness mechanism to act on it.

### G. Use Celery task result backend (`AsyncResult`)

Same option as the worker-liveness audit's own "D+" combination —
**proves**: task state as Celery's own result backend recorded it
(`PENDING`/`STARTED`/`SUCCESS`/`FAILURE`/`RETRY`). **Does not prove**:
a `STARTED` task is still alive rather than silently dead
(`CELERY_TASK_TRACK_STARTED=True` means "started" is recorded, but
nothing updates it again until completion) — **INFERRED**, unchanged
from the worker-liveness audit. **Requires** a persisted task ID
(option A) as a hard prerequisite — this option is not independently
useful without one.

### H. Use Celery events/monitoring

Same option as the worker-liveness audit's own "C" — a new, separately
operated long-running consumer (Flower or custom) — not re-derived
here. Highest operational complexity of the non-locking options.

### I. Use Redis as an ephemeral execution registry

- **Proves**: a live, non-durable "this session is currently being
  reconciled, by this task ID, as of this timestamp" marker — e.g. a
  Redis key with a short TTL, refreshed periodically by the task
  itself (structurally similar to a heartbeat, option C, but stored
  outside Postgres/SQLite).
- **Does not prove**: anything once the key expires or Redis itself is
  unavailable (Section 6, scenario 11) — trades durability for
  low-latency, low-schema-impact signaling.
- **Schema**: **none** — no migration, since Redis is not a Django
  model.
- **Race conditions**: a `SETNX`-style key could *also* serve as a
  cheap distributed lock (overlapping with the worker-liveness audit's
  own option F) — genuinely dual-purpose if designed for both roles at
  once, though this audit does not design that combination.
- **Operational complexity**: low to moderate — reuses the
  already-provisioned Redis instance, but introduces a second source
  of truth (Redis ephemeral state vs. Postgres/SQLite durable state)
  that must be reasoned about together.
- **Risk**: if Redis itself is the thing that's unavailable (scenario
  A in the worker-liveness audit's own matrix), this option's own
  signal disappears at exactly the moment a checkpoint's REAL status
  becomes hardest to assess by other means too — a shared-fate risk
  worth naming.

### J. Combine multiple approaches

Inherits the union of whichever options are combined. The
**smallest, most directly justified combination this audit's own
evidence supports** is discussed as the recommendation in Section 8:
a minimal version of A + E (two small fields), not the full B, and not
C/H/I, which each carry materially higher complexity or risk relative
to the specific, narrow gap Section 8 targets.

---

## 8. Minimum Viable Observability

**Per Step 6's explicit instruction to prefer minimal schema changes
and prove whether a migration is genuinely necessary rather than
assume one:**

**A true zero-schema-change step exists, and is nearly free, but is
insufficient for the stated goal.** Each of the three trigger-path call
sites (Section 2.1) could pass a `trigger_source` string as a new
*parameter* to `reconcile_session()`, used only in the existing
`logger.info(...)` calls (`apps/sync/tasks.py` already logs a summary
line per completed run) — this requires no migration, touches no
loop-internal code, and gives a human reading container logs a way to
know provenance *after the fact*. **This does not, however, make the
information available to the `possibly_stuck`/`GET /api/sync/status/`
API** — logs are not queryable by `SyncStatusView`, so this alone
cannot answer the stated question programmatically, only for a human
manually correlating log lines with a specific stuck session.

**Proving a migration is genuinely necessary**: to make the
distinction available to the *API* (the surface both `possibly_stuck`
and any future automated recovery would consult), the information must
live in the database, on `SyncCheckpoint` itself (the only row
currently associated with a session's reconciliation state) — no
existing column can carry this meaning without overloading an
unrelated field's semantics (e.g. abusing `last_error` for provenance
would violate that field's own established, error-message-only
contract). **Therefore a migration is required** for anything beyond
the log-only step above.

**The smallest schema change that materially helps**, per this
audit's own evidence (not the full option B model):

```python
# Two new, nullable fields on SyncCheckpoint — additive, backward-compatible.
last_run_trigger_source = models.CharField(
    max_length=16, blank=True,
    choices=[('periodic', 'Periodic'), ('targeted', 'Targeted'), ('manual', 'Manual CLI')],
)
last_run_task_id = models.CharField(max_length=64, blank=True)  # empty for 'sync'/manual runs
```

- Set once, at write (A) — `reconcile_session()` gains two new optional
  parameters (`trigger_source=None, task_id=None`), threaded through
  from each of the three call sites (Section 2.1) — **the loop body
  itself (lines 197-231) is never touched**, unlike option C/heartbeat.
- **Why this specific pair, and not more**: `trigger_source` is the
  single piece of information that changes how *confidently*
  `possibly_stuck` should be trusted (Section 6, scenario 7 — only the
  periodic/Celery path has a proven, enforced 600s ceiling); `task_id`
  is the minimum handle a *future*, separately-decided liveness check
  (option G/H) would need to attempt correlation — persisting it now,
  even before anything consumes it, is the same "make the data durable
  before deciding how to use it" discipline `possibly_stuck` itself
  already followed for `updated_at`.
- **What this does NOT solve**: worker liveness itself (still needs a
  separate decision, per the worker-liveness audit); Section 5's
  concurrency race (still needs locking or the fuller option B to
  meaningfully reduce); scenario 6's routine-retry false positive
  (`self.request.retries` would need to be persisted too, a reasonable
  *third* field to bundle into the same migration if this is
  implemented, though not strictly required for the minimum).

This two-field addition is recommended over the fuller execution-record
model (option B) as the *next* step specifically because Step 6 asks
for the smallest change, not the most complete one — option B remains
available, described in full (Section 7), as a larger, separately
justified future step if the two-field version proves insufficient in
practice.

---

## 9. Automatic Recovery Prerequisites

**Not implemented here.** Per the task's own instruction, the exact
evidence required before each operation could be considered safe:

### `RUNNING → ERROR` (automatically, not manually — Phase 13.A already handles the manual case safely)

Minimum conditions, ALL required:
1. A **compare-and-set** guard identical in kind to Phase 13.A's own
   (already available, no new work).
2. A **reliable staleness signal stronger than plain elapsed time** —
   e.g., `possibly_stuck` scoped specifically to `last_run_trigger_source
   == 'periodic'` (Section 8's minimum field), since only that path has
   a proven, enforced ceiling; elapsed time alone is not sufficient
   given scenario 6/H's routine false positive.
3. A **cooldown / max-automatic-attempts guard** per session, to
   prevent a persistent underlying cause (e.g. a real, ongoing WAHA
   outage) from producing a flapping cycle of automatic `ERROR` marks.
4. An **audit trail** — already available (`AuditLog`, reused
   unmodified by Phase 13.A).

### `RUNNING → replacement execution` (automatic re-enqueue)

All of the above, **plus**:
5. Confirmation the *original* execution cannot still deliver a result
   later — i.e., an actual liveness check (option G/H), not merely
   elapsed time — because firing a replacement while the original might
   still complete risks Section 5's watermark race becoming *more*
   likely, not less.
6. A **single-flight guarantee** — at most one replacement in flight
   per session at any time — pointing to option F/I-style locking as a
   near-hard prerequisite specifically for *this* operation (more so
   than for plain `ERROR`-marking, which makes no new dispatch at all).

### Task revoke/retry (automatic)

7. **Task ID persistence is an absolute prerequisite** (option A/B) —
   revoke/retry are Celery operations on a specific task identity;
   without it, this operation cannot exist at all, full stop.
8. **Confirmation the stuck checkpoint's origin is even revocable** —
   `trigger_source`/`executor` must show a Celery-executed path; the
   `'sync'`-executor and manual-CLI paths have no Celery task to revoke.
9. An **actual liveness/state check** (option G, ideally combined with
   H) before revoking — revoking a task that is genuinely still
   legitimately working destroys real (if redundant, per idempotency)
   effort; this is the operation most sensitive to a false positive of
   all three.

---

## 10. Security Implications

- **None of the options in Section 7 introduce a new unauthenticated
  surface** — any new field is read via the existing, already-JWT-gated
  `SyncStatusView`; any new endpoint (e.g. a future liveness-ping view)
  would need the same `IsAuthenticated`/scope discipline Phase 13.A
  already established (`HasSystemAdministrationScope`), not designed
  fresh here.
- **Task IDs and worker hostnames are not secrets** — Celery task UUIDs
  and container hostnames carry no credential material; exposing them
  via an already-authenticated endpoint is not a new disclosure risk
  beyond what `SyncStatusView` already exposes (session names,
  timestamps).
- **A Redis-backed ephemeral registry (option I) would reuse the
  already-provisioned `CELERY_BROKER_URL` connection** — no new
  credential surface, but does mean Redis becomes a second
  source-of-truth an attacker with Redis access could manipulate to
  spoof "still alive" signals — worth naming as a reason option I is
  weaker than a durable, access-controlled Postgres/SQLite field for
  anything security-sensitive (though nothing in this system's current
  design treats liveness as a security-relevant signal today).
- **An execution-record table (option B) would, over time, accumulate
  a history of reconciliation attempts** — not sensitive data by this
  project's own existing classification (no message content, no WAHA
  payload), consistent with `SyncCheckpoint`'s own current field set,
  but worth a retention-policy decision if adopted (Section 12).

---

## 11. Operational Implications

- **Section 8's minimum (two fields)**: negligible new operational
  burden — no new process, no new monitoring target, a two-column
  migration.
- **Option B (execution record)**: a new table that grows unboundedly
  without a retention/pruning policy — a genuine new operational
  concern (though a common, well-understood one).
- **Option H (events/Flower)**: the highest operational burden of any
  option — a new long-running service that itself needs deployment,
  monitoring, and restart-handling, ironically reintroducing the exact
  "is this process alive" question this whole audit is about, one
  layer up.
- **Option I (Redis registry)**: low burden to add, but couples
  liveness-signal availability to Redis's own availability — during
  exactly the scenario (Redis down) where other signals also degrade.
- **The newly-documented manual-CLI path (Section 2.1)** has an
  operational implication independent of any option chosen: operators
  running `manage.py reconcile` directly should be aware it has none of
  Celery's safety net — worth a documentation note regardless of which
  observability option (if any) is eventually implemented.

---

## 12. User Decisions Required

Per the task's own escalation bar (architecture-materially-changing
only):

1. **Whether to adopt Section 8's minimal two-field addition** (a
   migration) — the smallest change this audit identifies as
   genuinely necessary for the stated goal to be answerable via the
   API at all.
2. **Whether to instead (or additionally, later) adopt the fuller
   execution-record model** (option B) — a materially larger schema
   and architecture change, with its own retention-policy question.
3. **Whether distributed locking (option F, carried from the
   worker-liveness audit) or a Redis-backed registry (option I) should
   be introduced** — both change reconciliation's concurrency model.
4. **Whether Celery events/monitoring (option H) should be
   introduced** — a new, separately-operated long-running component.
5. **Whether reconciliation semantics should change** at all to support
   any of this (e.g. whether retries should each get their own
   execution-record row vs. update one shared row, Section 7 option B)
   — a real design choice, not resolved here.
6. **Whether automatic recovery is desired at all**, and if so, under
   which of Section 9's three operations — restated a third time across
   this session's three related audits because each has added new,
   concrete evidence bearing on the same still-open decision.

**Not escalated**: exact field names, exact log message formats, exact
migration file naming.

---

## 13. Recommended Next Phase

**Minimal observability improvement** — Section 8's two-field addition
to `SyncCheckpoint` (`last_run_trigger_source`, `last_run_task_id`),
threaded through `reconcile_session()`'s existing entry point only
(never its internal loop), populated by all three trigger call sites
(Section 2.1).

This is not a preference — it is the smallest change this audit's own
evidence shows is *necessary* (Section 8's migration-necessity proof)
and *sufficient* to make one concrete, currently-unanswerable question
answerable: **whether a given stuck checkpoint originated from the one
trigger path that has a proven, enforced time ceiling (periodic/Celery,
600s) or one of the two that do not** — directly closing "Missing
guarantee #3" from the worker-liveness audit, the single most
actionable, lowest-risk gap this whole audit lineage has identified.

**Explicitly not recommended as the next phase**: the full
execution-record model (option B — larger, real value, but not the
*smallest* justified step); any Celery-events/monitoring component
(option H — highest operational cost); distributed locking (option F/I
— addresses concurrency, a related but distinct problem from
observability); any form of automatic recovery (Section 9's
prerequisites are not yet met even with Section 8's minimum in place).

---

## 14. Exact Files That Would Change If Section 13's Recommendation Were Implemented

(Not implemented in this task — listed for the benefit of whichever
future task carries this out, per this session's own established
audit-report convention.)

- **`backend/apps/sync/models.py`** — two new nullable fields on
  `SyncCheckpoint`.
- **A new migration file** — `backend/apps/sync/migrations/000X_....py`.
- **`backend/apps/sync/reconciliation.py`** — `reconcile_session()`
  gains two new optional parameters, used only at write (A)/(B); the
  per-chat/per-page loop body (lines 197-231) is untouched.
- **`backend/apps/sync/tasks.py`** — both `@shared_task` functions pass
  `trigger_source='periodic'`/`'targeted'` and `task_id=self.request.id`
  when calling `reconcile_session()`.
- **`backend/apps/sync/executors.py`** — `run_targeted_reconciliation_with_retry()`
  passes `trigger_source='targeted'` (and `task_id=None` for the
  `'sync'`-executor path, since no Celery task exists there).
- **`backend/apps/sync/management/commands/reconcile.py`** — passes
  `trigger_source='manual'`.
- **`backend/apps/sync/views.py`** — `SyncStatusView`'s response could
  optionally surface the new fields (a separate, later decision — not
  required merely to *have* the data durably).
- **`backend/apps/sync/tests/test_reconciliation.py`,
  `test_tasks.py`, `test_views.py`** — new/updated tests for the two
  fields' population and (if exposed) serialization.

**Would NOT change**: `config/celery.py`, `config/settings.py`, any
Docker/Compose file, any BFF/frontend file, `apps/sync/internal_views.py`
(the internal trigger endpoint itself doesn't call `reconcile_session()`
directly — it goes through `executors.py`, already listed).

---

## 15. Explicit Non-Goals

- **No automatic recovery of any kind** — Section 9's prerequisites are
  descriptive, not an implementation plan.
- **No worker liveness mechanism** (`control.ping()`, events, Flower) —
  remains a separate, unresolved decision (worker-liveness audit,
  restated here, not re-decided).
- **No task ID persistence, no migration, no heartbeat** — none
  implemented; Section 8/13's recommendation is a *recommendation*,
  explicitly not carried out in this task.
- **No change to `possibly_stuck`'s existing detection logic or
  threshold** — unchanged, re-read, not modified.
- **No change to Phase 13.A's manual recovery endpoint** — unchanged,
  re-read, not modified.
- **No distributed locking, no Redis registry, no execution-record
  model** — all described (Section 7), none implemented.
- **No change to `reconcile_session()`'s actual reconciliation
  behavior** — even Section 13's own recommendation is scoped to
  never touch the per-chat/per-page loop body.

---

## 16. Final Conclusion

This audit traced three trigger paths for reconciliation execution
(uncovering a previously-undocumented third, `manage.py reconcile`),
confirmed that no execution-level identity (task ID, worker hostname,
retry count, trigger provenance) survives past the moment it is
created, and demonstrated precisely — via the exact code path, not
inference — both the shared-row concurrency race (Section 5) and a
previously-unexamined "data complete, bookkeeping stuck" scenario
(Section 6, scenario 5). None of the nine observability options (A–I)
alone or combined (J) is recommended wholesale; the evidence instead
points to a narrow, minimal, migration-requiring but loop-untouched
two-field addition (Section 8) as the smallest change that makes the
system's most actionable current blind spot — "did this stuck
checkpoint come from the one path with a proven time ceiling, or not"
— answerable via the existing API. Automatic recovery remains
unsafe under every operation considered (Section 9), each gated on
prerequisites this audit makes explicit rather than assumes.

**STOP.** This was a design audit only. No source, configuration,
schema, or Docker file was modified. No worker liveness, heartbeat,
task ID persistence, migration, or automatic recovery was implemented.
Awaiting the user's decisions in Section 12 before any further action.
