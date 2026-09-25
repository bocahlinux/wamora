# Celery Task Correlation — Design Audit Report

**This is a read-only design audit. No source, migration, Docker,
Compose, or Celery configuration file was modified. No container was
started, stopped, or restarted. No reconciliation was triggered. No
Celery task was called. No write endpoint was called. The existing
`possibly_stuck` detection and Phase 13.A's manual recovery endpoint
were not touched.**

**Conclusion up front:** the newly-added `last_run_trigger_source`/
`last_run_task_id` fields are genuinely useful — they close the
"which trigger path, and does a Celery task ID exist at all" gap the
prior observability audit identified — but they are **not sufficient**
to safely distinguish a dead execution from a live one, and this audit
found a **concrete, previously unexamined precision gap**: because the
two new fields are written only at the checkpoint's `RUNNING`-entry
save (not at its completion save), **`last_run_task_id` identifies
whichever task most recently *started* a run on this checkpoint, not
whichever task produced the checkpoint's current status** — under the
same concurrent-execution race both prior related audits already
proved possible today, these two facts can diverge, so a checkpoint
can show `status: OK` (or `ERROR`) correctly, while
`last_run_task_id` names a task that is unrelated to — or, worse,
still actively running underneath — that completed status. Automatic
recovery remains unsafe for every operation considered, for reasons
that are now more precisely evidenced than before, not merely
restated.

---

## 1. Objective

Determine, strictly from source, whether the execution metadata added
in the immediately preceding task (`last_run_trigger_source`,
`last_run_task_id`) is sufficient to safely distinguish a genuinely
stuck/dead reconciliation from a legitimately still-running one, a
retrying one, one whose worker disappeared, one that completed without
its checkpoint being finalized, and the two non-periodic trigger types
— without implementing anything.

---

## 2. Current Architecture

**VERIFIED FROM SOURCE**, every file below re-read directly this task
(not assumed from the implementation report):

- `backend/apps/sync/models.py` — `SyncCheckpoint.TRIGGER_PERIODIC`/
  `TRIGGER_TARGETED`/`TRIGGER_MANAGEMENT_COMMAND`,
  `last_run_trigger_source` (`CharField`, `blank=True`),
  `last_run_task_id` (`CharField`, `blank=True`) — both additive,
  non-nullable-with-empty-string-default, migrated
  (`0002_synccheckpoint_last_run_task_id_and_more.py`).
- `backend/apps/sync/reconciliation.py` — `reconcile_session()` accepts
  `trigger_source=None, task_id=None`; both are written **only** at the
  `RUNNING`-transition save (write A) — **re-confirmed this task**:
  the completion save (write B,
  `checkpoint.save(update_fields=['status', 'last_run_at', 'last_error', 'checkpoint_value', 'updated_at'])`)
  does **not** include either new field in its `update_fields` list.
  This single fact is the basis for Section 7's central finding.
- `backend/apps/sync/tasks.py` — `reconcile_session_task` passes
  `trigger_source=TRIGGER_PERIODIC, task_id=self.request.id`;
  `reconcile_chat_task` passes `task_id=self.request.id` through to
  `run_targeted_reconciliation_with_retry()`.
- `backend/apps/sync/executors.py` — `run_targeted_reconciliation_with_retry(..., task_id='')`
  (default); always passes `trigger_source=TRIGGER_TARGETED`.
- `backend/apps/sync/management/commands/reconcile.py` — passes
  `trigger_source=TRIGGER_MANAGEMENT_COMMAND, task_id=''`.
- `backend/apps/sync/views.py` — `_is_possibly_stuck()`,
  `SyncStatusView`, `SyncCheckpointRecoveryView` — **re-confirmed
  unchanged**: neither references `last_run_trigger_source` or
  `last_run_task_id` anywhere; `possibly_stuck` is still computed
  purely from `status`/`updated_at` against a single, global
  `settings.CELERY_TASK_TIME_LIMIT + 60` threshold.

---

## 3. Reconciliation Trigger Matrix

**VERIFIED FROM SOURCE** — re-traced every real caller this task
(`grep -rn "reconcile_session(\|reconcile_session_task\|reconcile_chat_task\|trigger_reconciliation("`,
excluding tests; no fourth path exists, matching the two prior audits):

| Path | Celery involved? | Task ID available? | Where `last_run_task_id` is written | Same ID across retry? | Stale after completion? | Checkpoint finalized? | Task state queryable later? |
|---|---|---|---|---|---|---|---|
| **Periodic** (`reconcile_session_task`) | Always | Yes — `self.request.id` | `reconcile_session()` write (A), via `tasks.py` | **INFERRED** yes (Celery's documented `Task.retry()` default reuses the same task ID unless a new one is explicitly passed — this codebase's `autoretry_for` wrapper does not pass one; **not independently live-tested**) | Not itself (the ID is real for as long as Celery tracks it) — but see Section 5/7: the **field** can show a *different* task's ID after this task's own completion, under concurrency | Yes, on normal completion (write B) | Only via `AsyncResult(task_id)`/`inspect().query_task()` — neither is called anywhere in this codebase (re-confirmed, zero hits) |
| **Targeted, `celery` executor** (`reconcile_chat_task`) | Yes | Yes — `self.request.id` | Same write (A), via `executors.py`'s helper | Same as periodic (**INFERRED**) | Same as periodic | Yes, on normal completion | Same — not queried anywhere |
| **Targeted, `sync` executor** | No | No — `task_id=''` (the helper's own explicit default, never fabricated) | Write (A), with the empty default | N/A — no Celery task, no retry in the Celery sense (only the 3-attempt, non-Celery `MAX_ATTEMPTS` loop in `executors.py`) | N/A | Yes, on normal completion | N/A — nothing to query |
| **Management command** | No | No — `task_id=''` (explicit) | Write (A) | N/A | N/A | Yes, on normal completion | N/A |

---

## 4. Celery Configuration Findings

**VERIFIED FROM CONFIGURATION** — `backend/config/settings.py`,
re-enumerated in full this task (unchanged from both prior related
audits — re-confirmed, not assumed):

```python
CELERY_BROKER_URL = ...          # redis
CELERY_RESULT_BACKEND = ...      # redis — configured, unused by any application code
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 600     # applies to EVERY task (app-wide default; no per-task
                                  # `time_limit=` override exists anywhere — re-confirmed
                                  # this task, zero hits for `time_limit=` in apps/sync/tasks.py)
CELERY_TASK_SOFT_TIME_LIMIT = 540
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
```

**Not set** (re-confirmed): `task_acks_late` (default `False`),
`task_reject_on_worker_lost` (default `False`), `worker_send_task_events`/
`-E` (events disabled), any task-uniqueness library.

**Specifically answering the task's six questions**, each
**VERIFIED FROM SOURCE** (the capability exists in the installed
`celery==5.4.0` library and `CELERY_RESULT_BACKEND` is configured) but
**NOT VERIFIED / UNAVAILABLE** for whether it is actually *useful in
this project's current state*, since nothing calls any of them:

| API | Meaningful today? |
|---|---|
| `AsyncResult(task_id)` | **Only now potentially meaningful** for the two Celery-executed paths, since `task_id` is finally persisted — but **nothing in this codebase calls it**. Its `.state` for a killed task would likely remain `STARTED` forever (`CELERY_TASK_TRACK_STARTED=True`, no `task_acks_late`) — **INFERRED**, not live-tested. |
| `inspect().active()` | Would list tasks *currently executing* on *connected* workers — meaningful only while a worker is alive and connected; **not called anywhere**. |
| `inspect().reserved()` | Would list tasks a worker has fetched but not yet started — same caveat; **not called anywhere**. |
| `inspect().scheduled()` | Would list ETA/countdown tasks — not used by this codebase's scheduling model (Celery beat, not per-task ETAs); **not called anywhere**, and not obviously applicable to this project's task shapes. |
| `inspect().query_task(task_ids)` | The most *directly* relevant capability now that `task_id` is persisted — would ask connected workers "what do you know about this specific ID." **Not called anywhere.** |
| `inspect().ping()` | Would confirm at least one worker is alive and responsive. **Not called anywhere** — this is the same capability the worker-liveness audit's own "option B" already named, unchanged. |

**Redis being reachable does not imply any of the above are
meaningful** — re-confirmed, matching `RedisHealthView`'s own
docstring (already quoted verbatim in the worker-liveness audit): a
broker `PING` proves nothing about whether any worker is connected,
registered, or would answer an `inspect()` call at all.

---

## 5. Task ID Semantics

Answering Step 3's seven questions directly:

**A. Does Celery retry preserve the same task ID?** **INFERRED, not
independently verified live**: Celery's documented `Task.retry()`
behavior reuses the calling task's own ID unless a caller explicitly
passes a new one; this codebase's `autoretry_for=(Exception,)` wrapper
(`celery/app/autoretry.py`, third-party code) calls
`task.retry(exc=exc, **retry_kwargs)` with no `task_id=` override —
re-confirmed by reading that library's own retry call in the traceback
captured during this session's own test runs (Section 11 of the
implementation report). **This project's test suite does not itself
assert ID-stability across a real retry sequence** — the existing
`test_worker_style_redelivery_after_retry_eventually_succeeds` test
never inspects `self.request.id` across attempts.

**B. Does retry create a new task ID?** Following directly from A: no,
not under this project's actual configuration (**INFERRED**, same
basis).

**C. When `reconcile_session()` executes during retry, does it
overwrite `last_run_task_id`?** **VERIFIED FROM SOURCE**: yes — every
retry attempt re-enters `reconcile_session_task`'s full body, including
the `reconcile_session(..., task_id=self.request.id)` call, so write
(A) re-executes and re-writes whatever `self.request.id` currently is
(per A/B, almost certainly the same value as the first attempt) — a
harmless, idempotent re-write of the same string.

**D. Can `last_run_task_id` become stale after task completion?**
**VERIFIED FROM SOURCE, and more precisely than the implementation
report's own Section 17 stated**: yes, but not merely as "the same
pre-existing race that already affected `status`" — the mechanism is
narrower and worth stating exactly: **write (B), the completion save,
never includes `last_run_trigger_source`/`last_run_task_id` in its
`update_fields`.** These two fields are therefore only ever set at
write (A) and are **never refreshed or re-affirmed at write (B)**. A
checkpoint can reach `status: OK` (or `ERROR`) while
`last_run_task_id` still shows whatever the **most recent write (A)**
happened to set it to — which, under concurrency (Section 6), is not
guaranteed to be the same execution whose write (B) produced that
status.

**E. Can two concurrent reconciliation executions have different task
IDs for the same session?** **VERIFIED FROM SOURCE**: yes,
straightforwardly — each execution's own `reconcile_session()` call
receives its own `task_id` parameter from its own caller; two
concurrent Celery-executed runs for the same session (already
established as possible today by both prior related audits, e.g. a
periodic dispatch overlapping a targeted trigger) each pass their own,
different `self.request.id`.

**F. Can a management-command or targeted-synchronous execution have
an empty/blank task ID?** **VERIFIED FROM SOURCE**: yes, by explicit
design — `task_id=''` is passed for both, never `None`, never a
fabricated value (Section 3).

**G. Is the current database field sufficient to identify the
currently executing reconciliation?** **No — VERIFIED FROM SOURCE, via
the exact trace in Section 6.** `last_run_task_id` identifies "the
task that most recently entered `RUNNING`," not "the task currently
still executing" and not "the task that produced the current status."
These three concepts coincide only in the common, non-concurrent case.

---

## 6. Concurrency Analysis — The Exact Race, Traced

**VERIFIED FROM SOURCE**, re-tracing `reconciliation.py` line by line
for the task's exact requested scenario:

```
Task A: get_or_create() -> checkpoint_A (local object)
Task A: write(A): status=RUNNING, last_run_task_id=A, updated_at=tA1      [DB: task_id=A]

Task B (starts before A finishes): get_or_create() -> checkpoint_B (a SEPARATE local object)
Task B: write(A): status=RUNNING, last_run_task_id=B, updated_at=tB1>tA1  [DB: task_id=B]
        (both A and B read the SAME pre-run checkpoint_value watermark,
        since neither has reached write (B) yet — re-confirms the
        recovery/observability audits' own prior finding, not re-derived)

Task A finishes -> write(B): status=OK/ERROR, last_run_at, checkpoint_value(A's own),
                   updated_at=tA2
                   update_fields does NOT include last_run_task_id/last_run_trigger_source
                   [DB: task_id STILL = B — unchanged by this write]

RESULT: DB now shows status=OK (or ERROR) with last_run_task_id=B.
        This is Task A's completion, but the field names Task B —
        which is STILL RUNNING. A reader has no way to detect this
        mismatch from the checkpoint row alone.

Task B finishes (later) -> write(B): status=OK/ERROR (B's own outcome),
                            checkpoint_value (B's own, possibly regressed
                            relative to A's — already-established watermark
                            non-monotonicity finding, re-confirmed applicable
                            here), last_run_task_id unchanged (still B, and
                            now, coincidentally, correctly correlated again).
```

**The reverse ordering is the more concerning one, traced explicitly
per the task's own request:**

```
Task A crashes (after its own write (A), never reaches write (B)).
Task B continues normally to its own write(B): status=OK/ERROR (B's own outcome),
    last_run_task_id unchanged = B — CORRECTLY correlated in this ordering,
    since B was also the last to write(A).
```

```
Task B crashes (after its own write (A), never reaches write (B)).
Task A continues normally to its own write(B): status=OK/ERROR (A's own outcome),
    last_run_task_id STILL = B (set by B's write(A), never touched by A's write(B))
    — MISCORRELATED: the checkpoint shows A's real outcome, but names a
    task (B) that actually crashed and never finished.
```

```
Task A completes its own work successfully, then loses the worker/process
before reaching its own write(B) (the exact "data complete, bookkeeping
stuck" gap the observability audit's Section 2.3/6 already named):
    DB stays at whatever the most recent write(A) set — status=RUNNING,
    last_run_task_id = whichever of A/B most recently entered RUNNING
    (not necessarily A, even though A is the one whose data is actually
    fully, correctly persisted).
```

**Conclusion, directly answering the task's own framing question**:
the current metadata **cannot** establish "ownership" of a `RUNNING`
(or a just-completed `OK`/`ERROR`) checkpoint under concurrency.
`last_run_task_id` is a **last-write-wins label on entry**, not an
**ownership token** — nothing in this codebase enforces that only the
execution which set a given `task_id` is the one permitted to later
transition that checkpoint's status. **No fix is proposed here**, per
the task's own instruction — this section only establishes that the
metadata, as implemented, does not solve the ownership question, and
explains precisely why (write (B)'s `update_fields` omission), not
merely that "the same pre-existing race still applies."

---

## 7. `possibly_stuck` Correlation

**VERIFIED FROM SOURCE**: `_is_possibly_stuck()` (`apps/sync/views.py`)
is **completely unchanged** by the prior task — it still reads only
`checkpoint.status`/`checkpoint.updated_at` against a single,
trigger-source-agnostic threshold
(`settings.CELERY_TASK_TIME_LIMIT + 60` = 660s under default
settings). It does not reference `last_run_trigger_source` or
`last_run_task_id` at all.

**Whether it can safely be combined with the new fields**: the fields
are *available* to combine (no technical obstacle), but doing so
usefully requires resolving what Section 6 already shows is unresolved
— using `last_run_task_id` to look up Celery's own task state (Section
4/8, option C) would still be asking about a task ID that might not be
the one actually associated with the checkpoint's current `RUNNING`
state, under the exact race just traced.

**False-positive scenarios, made precise by trigger source (not
previously stated this specifically)**:

- **`retry_backoff` (up to `retry_backoff_max=600`)** — applies **only**
  to the two Celery-executed paths (`periodic`, and `targeted` when
  `last_run_task_id` is non-empty) — both `reconcile_session_task` and
  `reconcile_chat_task` share this exact decorator configuration
  (re-confirmed, Section 2). A fully healthy multi-attempt retry
  sequence can legitimately exceed 660s, **re-confirming** (not
  newly discovering) the worker-liveness audit's own scenario H finding
  — restated here specifically scoped to which trigger sources it
  applies to.
- **`CELERY_TASK_TIME_LIMIT` (600s)** — applies **uniformly to every
  Celery task in this project** (confirmed no per-task override exists,
  Section 4) — so both Celery-executed paths share the same enforced
  ceiling that makes 660s a well-grounded threshold *for them
  specifically*.
- **Targeted execution, `sync` sub-case (no Celery task,
  `last_run_task_id=''`)** — has **no enforced ceiling at all**; its
  only empirical bound (re-confirmed, not re-derived, from both prior
  related audits) is `WahaClient`'s `DEFAULT_TIMEOUT_SECONDS=10` ×
  `MAX_ATTEMPTS=3` in `executors.py`'s own retry loop — comfortably
  under 660s in realistic cases, but not *guaranteed* the way the
  Celery time limit is.
- **Management command** — **no enforced ceiling of any kind** — bound
  only by whatever the operator's own terminal session survives
  (already established, re-confirmed, not re-derived).

**Should the threshold differ by trigger source?** Now technically
possible (the data exists) but **not a clean win**: for the two
Celery-executed paths, 660s remains the *best-grounded* number
available, backed by an actual enforced system limit. For the two
non-Celery paths, **no enforced ceiling exists to derive an equally
well-grounded number from** — a different threshold for them would
have to come from operational observation (typical real-world run
durations), not from a system-enforced guarantee, making it a
*weaker*, not *stronger*, basis than what already exists. **This
audit does not recommend introducing per-source thresholds** on the
evidence available — it would trade one well-justified number for a
mix of one well-justified and two weakly-justified ones, adding real
complexity (a lookup table instead of one constant) for a benefit this
audit cannot currently substantiate. Flagged as a genuine, open
question for Section 12, not resolved here.

---

## 8. Recovery Safety Analysis

**Re-assessed with the new metadata, not merely restated from the
recovery design audit** — Phase 13.A's own code (re-read, Section 2)
references neither new field, so **its existing safety property is
completely unaffected** by anything in this report; it remains sound
regardless of Section 6's finding, precisely because it never trusted
`last_run_task_id` for anything.

### A. `RUNNING → ERROR` (automatic)

**Still unsafe.** The retry-backoff false positive (Section 7) is
unchanged and unresolved. `trigger_source` *could* let a policy scope
itself to only Celery-executed checkpoints (closing the
worker-liveness audit's "Missing guarantee #3"), narrowing exposure —
but does not eliminate the retry-backoff false positive *within* that
narrowed scope. **Missing guarantee: a signal that distinguishes
"legitimately retrying" from "actually dead," which trigger_source
alone does not provide.**

### B. `RUNNING → enqueue replacement task` (automatic)

**Still unsafe**, now for a more precisely evidenced reason: even
if a policy wanted to check "is the task named by `last_run_task_id`
still alive before enqueueing a replacement," Section 6 shows that ID
might not even *be* the execution actually associated with the current
`RUNNING` state. **Missing guarantee: reliable ownership correlation
(Section 6) plus actual liveness confirmation (Section 4's unused
`inspect`/`AsyncResult` capabilities) — neither exists.**

### C. Celery revoke (automatic)

**Materially re-evaluated**: the prior recovery audit's blocking
reason was "no task ID is persisted at all" — **that specific
prerequisite is now satisfied** for the two Celery-executed paths.
However, revoking is only as trustworthy as the ID's correlation to
the *actual* stuck execution — Section 6 shows that correlation can be
wrong. Revoking the *wrong* task ID either no-ops harmlessly (if that
task already finished) or, in the worst traced case, could revoke a
task unrelated to the actually-still-running one, while the real
culprit remains unidentified and untouched. **Missing guarantee: proof
that the persisted `task_id` is the one currently occupying `RUNNING`
on this checkpoint, not merely the most recent one to have started
it.**

### D. Retry (automatic, externally triggered)

**Unchanged, still not meaningfully implementable**: Celery's own
`self.retry()` must be called from inside the executing task's own
context — an external actor holding a `task_id` cannot invoke it.
**Missing guarantee: N/A — the operation itself has no external
API to safely gate in the first place.**

### E. Reset checkpoint timestamp (automatic)

**Still the most dangerous option**, and arguably **worse now**: a
bare timestamp reset (already flagged as actively unsafe in the
recovery audit) would leave a now-**more clearly wrong**
`last_run_task_id`/`last_run_trigger_source` sitting on the row
indefinitely — compounding, not just repeating, the correlation
problem Section 6 identifies. **Missing guarantee: unchanged — this
operation actively defeats the purpose of the very detection it would
be resetting.**

**Conclusion**: Phase 13.A remains safe to keep as the **sole**
recovery mechanism. Nothing in this audit weakens that; several
findings (Section 6/8.C) strengthen the case for continuing to require
a human in the loop specifically because task-ID correlation cannot
yet be trusted for an unattended decision.

---

## 9. Design Options

Presented without ranking, per the task's own instruction. Options
A/B/F overlap in substance with the worker-liveness audit's own
options and are not re-derived in full; C and D are meaningfully
advanced by this session's own recent work (task_id now exists).

### A. Redis-only worker liveness

Already implemented (`RedisHealthView`). **Files affected**: none (no
change proposed). **Migration**: none. **Dependencies**: none.
**Complexity**: none (existing). **Solves**: broker reachability only.
**Remains**: everything about worker/task liveness (Section 6 of the
worker-liveness audit, unchanged). **Enables safe automatic
recovery?**: no, alone.

### B. Celery `inspect().ping()`

**Files affected**: one new function/view (e.g. in `apps/core/views.py`
or a new module) — no existing file needs modification. **Migration**:
none. **Dependencies**: none (`celery` already installed).
**Complexity**: moderate — timeout policy, "zero workers responded" vs.
"timed out" ambiguity. **Solves**: "is at least one worker alive and
responsive" — a genuine, currently entirely absent signal. **Remains**:
does not correlate to a *specific* task (Section 4) — a responsive
master process on the `prefork` pool does not prove a specific busy
child isn't wedged (**INFERRED**, Celery's documented architecture,
unchanged from the worker-liveness audit). **Enables safe automatic
recovery?**: only as one ingredient among several — not alone.

### C. Celery task-state correlation using `last_run_task_id`

**Now meaningfully possible for the first time**, since the ID is
persisted. **Files affected**: one new function (e.g. calling
`AsyncResult(checkpoint.last_run_task_id).state` or
`celery_app.control.inspect().query_task([task_id])`) — could live in
`apps/sync/views.py` as a read-only addition, or a separate diagnostic
tool. **Migration**: **none** — reuses the field already added.
**Dependencies**: none. **Complexity**: moderate — needs timeout
handling and honest handling of "no answer" (ambiguous, not
"confirmed dead"). **Solves**: gives a real (if imperfect) signal for
whether Celery's own bookkeeping still shows this specific ID as
known/active, for the two Celery-executed paths. **Remains**: Section
6's ownership-ambiguity — a stale-but-persisted ID might not be the
execution actually associated with the current `RUNNING` state; and
this option is **not applicable at all** to the two non-Celery paths
(`last_run_task_id=''`). **Enables safe automatic recovery?**: not
alone — narrows uncertainty for a human decision (Phase 13.A) more
than it justifies removing the human.

### D. Persisted execution records (a dedicated per-execution table)

Same option as the observability audit's own "B" — **the option that
most directly and completely resolves Section 6's exact finding**,
since each execution would own its own row rather than sharing one
mutable field. **Files affected**: a new model, `reconcile_session()`'s
entry/exit points (to create/update a row instead of/in addition to
the two `SyncCheckpoint` fields), all four call sites. **Migration**:
yes — a new table, the largest schema change among these options.
**Dependencies**: none. **Complexity**: moderate-high — needs a
retention policy for a growing table, and a design decision on
per-retry-attempt granularity (one row per attempt vs. one row updated
across attempts — not resolved here, same open question the
observability audit already named). **Solves**: Section 6's exact
ownership-ambiguity, structurally, by construction. **Remains**:
worker liveness itself is still not proven by this option alone (a
dead execution's own row just sits at `running` forever, same
fundamental gap, now on a richer row). **Enables safe automatic
recovery?**: the strongest foundation of any option here, per the
observability audit's own prior assessment, re-confirmed — still not
sufficient alone without a liveness signal (B/C/F).

### E. Distributed lock / ownership token

**Files affected**: wraps `reconcile_session()`'s callers (or
`reconcile_session()` itself) with acquire/release logic. **Migration**:
none, for a pure Redis-key-based lock (Redis already provisioned).
**Dependencies**: none if hand-rolled; a library if not. **Complexity**:
moderate — must correctly handle the exact `try/finally`-shaped gap
already missing from `reconcile_session()` (recovery audit, Section 4)
to guarantee release on every exit path, including a crash (which a
plain Python `finally` cannot guarantee against a `SIGKILL` — a lock
TTL is still needed as a backstop, reintroducing a threshold-choice
problem structurally similar to `possibly_stuck`'s own). **Solves**:
prevents Section 6's race **at its root** — if only one execution can
ever hold `RUNNING` for a session at a time, there is never an
ownership question to answer after the fact. **Remains**: a lock held
by a dead process is its own classic problem, needing the same kind of
staleness threshold this whole audit lineage has been examining.
**Enables safe automatic recovery?**: meaningfully closer than any
single option here, specifically because it removes the *concurrent
execution* failure mode (Section 6) that undermines options B/C/D
individually.

### F. In-task heartbeat

Same option as the worker-liveness audit's own "E"/"C" —
**proves**: the most direct still-alive signal, updated from *inside*
the currently-executing loop. **Does not prove**: anything if the
wedge point never reaches the heartbeat-touching code. **Files
affected**: `reconcile_session()`'s internal loop body — the **one**
change in this whole list that touches code every related audit and
implementation this session has deliberately left untouched.
**Migration**: yes, a new field (or repurposed use of an existing one).
**Complexity**: moderate to implement, conceptually simple.
**Enables safe automatic recovery?**: strong liveness signal, but the
highest-risk option to implement given its loop-internal footprint.

### G. Combination (task state + ownership + heartbeat)

The union of, most plausibly, **E (ownership) + C or D (correlation) +
F (heartbeat)** — this is the only combination this audit's evidence
suggests would close essentially every gap traced across all three
related audits (worker-liveness, recovery, observability, and this
one): E removes the concurrency ambiguity Section 6 depends on; C/D
gives external verifiability; F gives the most direct liveness signal
available. **Highest complexity and schema/code footprint of any
option** — **not recommended as the next step** (Section 10), named
here as the eventual, complete answer *if* automatic recovery is ever
genuinely wanted, not as an immediate recommendation.

---

## 10. Recommended Next Task

**No automatic recovery. No schema change. No new dependency.**

The smallest, most directly evidence-backed next step is **Option C,
scoped explicitly as a read-only, human-facing diagnostic
capability** — e.g., exposing (to an operator, via a narrowly-scoped,
already-authenticated surface, or simply as an investigative tool) what
Celery's own `AsyncResult`/`inspect().query_task()` currently reports
for a checkpoint's `last_run_task_id`, when that field is non-empty.

**Why this, and not something larger:**
- **Smallest safe change**: uses data that already exists (no
  migration); uses a Celery capability already installed and configured
  (no new dependency); adds one new, purely additive read path.
- **Strongest evidence**: Section 4/9 established this is the one
  option that becomes *meaningfully possible for the first time* as a
  direct consequence of the prior task's own work — it is not a
  speculative feature, it is the natural next use of data that was
  explicitly persisted as "the minimum handle a future, separately-decided
  liveness check would need" (the observability design audit's own
  Section 8 language).
- **Compatible with existing architecture**: read-only, no change to
  `reconcile_session()`, `possibly_stuck`, or Phase 13.A.
- **Honest about its own limit**: this option does **not** resolve
  Section 6's ownership-ambiguity, and this report does not claim it
  does — it is explicitly recommended as a **decision-support aid for
  the existing human-in-the-loop (Phase 13.A) process**, not as a step
  toward automating anything. **Automatic recovery remains unsafe**,
  full stop, regardless of whether Option C is built.

**Explicitly not recommended as the next step**: Option D (execution
records) or E (locking) — both real, larger, schema/architecture-level
changes that Section 12's user decisions should gate before either is
pursued; Option F (heartbeat) — the one option that would touch
`reconcile_session()`'s internal loop, a materially different risk
class than every other option; Option G — the full combination, too
large a jump from the current state.

---

## 11. User Decisions Required

Per the task's own escalation bar (architecture/data-integrity only):

1. **Whether Celery task-state correlation (Option C) should be
   implemented**, and if so, whether as a human-facing diagnostic only
   (this audit's recommendation) or as an input to some future
   decision logic.
2. **Whether worker-liveness observation (Option B,
   `inspect().ping()`) should be added** — a real new capability,
   independent of Option C, not required for it.
3. **Whether a distributed lock/ownership token (Option E) is
   acceptable** — the option that most directly resolves Section 6's
   ownership-ambiguity at its root; a genuine architectural addition
   to reconciliation's concurrency model.
4. **Whether persisted execution records (Option D) should be pursued
   instead of, or in addition to, the current two-field approach** — a
   materially larger schema change than anything implemented so far in
   this lineage.
5. **Whether in-task heartbeat tracking (Option F) is an acceptable
   scope**, given it is the only option requiring a change inside
   `reconcile_session()`'s own loop.
6. **Whether automatic recovery is desired at all**, under any of
   Section 8's five operations — restated a fourth time across this
   session's four related audits, because each has added new, distinct,
   concrete evidence bearing on the same still-open decision; this
   audit's own contribution is the precise ownership-ambiguity finding
   (Section 6).
7. **Whether per-trigger-source `possibly_stuck` thresholds (Section
   7) are worth the added complexity** — this audit does not recommend
   them on current evidence, but flags the trade-off explicitly rather
   than deciding it unilaterally.

**Not escalated**: exact function/view naming, exact timeout values for
an `inspect()` call, exact log message formats.

---

## 12. Files Inspected

`backend/apps/sync/models.py`, `reconciliation.py`, `tasks.py`,
`executors.py`, `management/commands/reconcile.py`, `views.py`,
`internal_views.py` (re-confirmed unchanged/uninvolved),
`backend/config/settings.py` (full `CELERY_*` block),
`backend/apps/sync/migrations/0002_synccheckpoint_last_run_task_id_and_more.py`,
plus repository-wide greps for every caller of `reconcile_session`/
`reconcile_session_task`/`reconcile_chat_task`/`trigger_reconciliation`
and for `AsyncResult`/`inspect(`/`task_id`/`time_limit=` usage. `git
status` was checked before and after this task (no changes made).

---

## 13. Verification Limitations

**VERIFIED FROM SOURCE**: every claim in Sections 2–8 about this
codebase's own code and configuration, traced directly this task.

**NOT VERIFIED / UNAVAILABLE** (would require live infrastructure this
audit's strict read-only scope did not touch):
- Whether Celery retry genuinely preserves the same task ID in this
  project's actual deployed configuration (Section 5.A/B — based on
  Celery's documented default behavior, not exercised live).
- Whether `AsyncResult(task_id).state` for a genuinely killed task
  actually remains `STARTED` forever in practice, as opposed to
  eventually expiring or erroring (Section 4 — based on
  `CELERY_TASK_TRACK_STARTED`'s documented meaning, not observed).
- Real-world frequency of the exact concurrency race traced in Section
  6 in this project's actual production usage — no live database was
  queried.
- Whether `inspect().ping()`/`query_task()` would actually receive
  responses from real workers in the current deployment (the Office-side
  stack was not running at any point during this task, confirmed via
  `docker ps`, unchanged from every prior related audit this session).

---

## 14. Final Conclusion

The execution-provenance metadata added in the immediately preceding
task is a genuine, correctly-scoped improvement — it answers "which
trigger path, and was a Celery task involved" for the first time. It
does **not**, however, answer "is this specific `RUNNING` checkpoint
still owned by a live execution," and this audit traced precisely why:
the two new fields are written only when a run *starts*, never
re-affirmed when a run *finishes*, so under the same concurrent-execution
race every related audit this session has already proven possible
today, `last_run_task_id` can name a task that is unrelated to — or
still silently running underneath — the checkpoint's own current,
correctly-computed status. Celery's own task-state inspection
capabilities (`AsyncResult`, `inspect()`) remain entirely unused, and
would themselves inherit this same ownership ambiguity if consulted
naively. Automatic recovery remains unsafe for all five operations
considered (Section 8), each now gated on a more precisely identified
missing guarantee than before. The recommended next step (Section 10)
is narrow, additive, and explicitly scoped as a human-decision aid, not
a step toward automation — closing the gap between "we have a task ID"
and "we can do something useful with it" without pretending to close
the larger, still-open ownership question that only a lock (Option E)
or per-execution records (Option D) can structurally resolve.

**STOP.** This was a design audit only. No recommended option was
implemented. No automatic recovery, worker-liveness endpoint,
migration, lock, or heartbeat was added. `possibly_stuck` and Phase
13.A remain exactly as they were. Awaiting the user's decisions in
Section 11 before any further action.
