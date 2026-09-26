# Phase 4/9 Follow-Up — Celery Worker Liveness / Reconciliation Recovery — Design Audit Report

**Read-only design audit.** No source, test, config, Docker, Compose,
`.env`, migration, or Celery configuration file was modified. No
container was started, stopped, or restarted. No reconciliation was
triggered, no Celery task was called, no WAHA/WhatsApp operation was
performed, no write endpoint was called. The only file created is this
report.

**Naming note**: this is a continuation of roadmap **Phase 4
(Reconciliation)** and **Phase 9 (Offline/degraded mode)** — per
`docs/generated/PHASE-ROADMAP-STATUS-AUDIT-REPORT.md` and
`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` item 13. It is explicitly NOT
the canonical roadmap's Phase 13 ("Failure/security testing",
`docs/15-CODING-PHASES.md`). Referred to throughout as "Phase 4/9
follow-up," never "Phase 13."

**Conclusion up front**: Since
`docs/generated/NEXT-PHASE-CELERY-WORKER-LIVENESS-DESIGN-AUDIT-REPORT.md`
was written, a materially large amount of related work has landed —
task-ID persistence (`last_run_task_id`/`last_run_trigger_source`), a
diagnostic Celery task-state endpoint
(`SyncCheckpointTaskStateView`), and a manual, admin-gated,
compare-and-set recovery endpoint (`SyncCheckpointRecoveryView`), plus
its diagnostics UI. Several of the old audit's six open questions are
now **effectively answered by direct precedent**: Blast just closed the
exact same class of problem (a claim written before a side effect,
worker dies mid-flight, thing stuck forever) with a **manual,
admin-gated, compare-and-set "resolve" endpoint — not automatic
retry/resume**. Reconciliation's own worker-death-mid-task scenario is
the **same shape of problem**, but with one materially different,
favorable fact this audit re-verified directly from source:
reconciliation is **strictly read/pull** (`WahaClient.fetch_chats`/
`fetch_chat_messages` are both plain HTTP `GET` calls; nothing in
`apps/sync/` ever calls a WAHA write endpoint), so recovering a stuck
reconciliation checkpoint carries **none** of Blast's
"must-not-double-send" constraint — the only integrity property that
matters is not corrupting `SyncCheckpoint`'s own state, which the
existing CAS-guarded `SyncCheckpointRecoveryView` already provides.

The one gap this audit confirms is still open, re-verified directly
from `apps/sync/reconciliation.py`: **`reconcile_session()` still has
no `try/finally`** around its RUNNING→terminal transition. An
exception that is not `WahaClientError` (the only exception type the
per-chat loop catches) propagates out of the function entirely,
skipping the final `checkpoint.save(...)` at the bottom — the
checkpoint is left `RUNNING` forever, identical in shape to Blast's
"claimed before the side effect, never resolved" bug. This is
**mitigated, not eliminated**, by the existing manual recovery
endpoint (which requires a human to notice `possibly_stuck` and act)
and by Celery's own `autoretry_for=(Exception,)` (which re-enters
`reconcile_session()` from the top, re-writing `RUNNING`, up to 3
times) — but after retries are exhausted, or for any executor path
that isn't retried the same way, the checkpoint is stuck with no
automatic resolution, exactly matching the shape Blast's fix closed
for `BlastRecipient`.

---

## 1. Findings

Each finding: PASS / FAIL / NOT VERIFIED, with file:line citation and
VERIFIED FROM SOURCE / INFERRED / NOT VERIFIED classification.

### 1.1 Worker-liveness ping API — does one exist?

**FAIL (does not exist) — VERIFIED FROM SOURCE.**

`grep -rn "celery.control\|\.ping(\|inspect(\|\.active(\|\.revoke(" backend/`
re-run this task: the only hits are `backend/apps/core/views.py:67`
(a docstring explicitly stating `RedisHealthView` does **not** call
`celery.control.ping()`) and `:82` (`client.ping()` — this is a
`redis-py` client's own `PING`, not a Celery control-plane call).
**Zero** `celery.control.ping()`/`.inspect()`/`.active()`/`.revoke()`
calls exist anywhere in `backend/`. This exactly re-confirms the prior
audit's Section 5 finding — nothing has changed on this specific
point since it was written.

Is one needed? See Section 3 (Scope) — this audit's judgment is **not
required for the minimal recommended scope**, for the same reason
Blast's fix didn't need one: the manual recovery endpoint does not
need to *prove* a worker is dead to be useful; it only needs
`possibly_stuck` (checkpoint age), which is already computed without
any worker inspection.

### 1.2 Task-ID/state persistence — reliable?

**PASS, with one pre-existing, disclosed limitation — VERIFIED FROM
SOURCE.**

Contrary to the old audit's Section 4/9 (written before this landed):
task ID is now genuinely captured and persisted, not discarded.

- `backend/apps/sync/models.py:59-65` — `SyncCheckpoint.last_run_trigger_source`
  and `last_run_task_id` are real, persisted `CharField`s.
- `backend/apps/sync/reconciliation.py:161-206` — `reconcile_session()`
  accepts `trigger_source`/`task_id` keyword args and writes them to
  the checkpoint **at the START of the run** (write (A), before any
  WAHA call), specifically so the metadata survives even if the run
  never reaches its own end.
- `backend/apps/sync/tasks.py:53` (`reconcile_session_task`) and `:95`
  (via `run_targeted_reconciliation_with_retry`, called with
  `task_id=self.request.id`) — both Celery entry points pass their own
  real `self.request.id`, not a discarded `.delay()` return value.
- `backend/apps/sync/views.py:381-454` (`SyncCheckpointTaskStateView`)
  — a diagnostic, admin-gated, read-only endpoint that correlates
  `last_run_task_id` against Celery's own `AsyncResult(task_id).state`,
  with explicit, honest ambiguity framing (`PENDING_AMBIGUITY_NOTE`,
  `NO_TASK_ID_NOTE`, `UNAVAILABLE_NOTE`) and its own docstring stating
  plainly: **"THIS RESULT IS NOT OWNERSHIP PROOF"** — `last_run_task_id`
  identifies whichever task most recently *started* a run, not
  necessarily the task that produced the checkpoint's *current*
  status, under concurrent execution.

**Disclosed limitation (unchanged, inherent to the design, not a
regression)**: under scenario I (two reconciliation tasks for the same
session overlapping — Section 1.4 below), the second task to start
overwrites `last_run_task_id` with its own ID, so the field always
reflects the most recent *starter*, never a queryable full history.
This is a known, accepted trade-off (no execution-history table was
built, by explicit design-audit decision), not a bug.

### 1.3 Distributed locking / concurrency

**FAIL (none exists) — VERIFIED FROM SOURCE.**

- `backend/apps/sync/tasks.py:108-117` (`reconcile_all_sessions_task`)
  dispatches one `reconcile_session_task.delay(session_name)` per
  known `WahaSession` **without checking any existing checkpoint
  state** — re-confirmed by direct reading; no `SyncCheckpoint`
  query of any kind appears in this function.
- `backend/apps/sync/reconciliation.py:186-206` (`reconcile_session`)
  itself performs a **plain read-then-write** of
  `checkpoint.status = RUNNING; checkpoint.save(...)` — not a
  conditional `UPDATE ... WHERE status != 'running'`. Two concurrently
  executing calls for the same session (e.g. beat's periodic dispatch
  racing a targeted dispatch from a just-sent message,
  `apps/sync/executors.py`) can both proceed past this write; each
  will each independently run its own per-chat loop and each write its
  own terminal status/`checkpoint_value` at the end — a lost-update
  race on the checkpoint's own final state, though not a data-integrity
  risk for `Message`/`Chat`/`Contact` rows (protected by the unrelated
  `(session, provider_message_id)` unique constraint,
  `persist_message`'s own duplicate-safety).
- No `select_for_update()`, no Redis-based lock, no Celery
  task-uniqueness library (`django-celery-beat` uniqueness add-ons,
  `celery-once`, etc.) appears anywhere in `backend/requirements.txt`
  or `backend/apps/sync/`.

This exactly matches the prior audits' own findings (recovery design
audit Section 7/8; worker-liveness audit Section 10, scenario I) — **no
new concurrency protection has been added since**, and none was needed
for the manual-recovery scope that *was* implemented (the CAS guard in
`SyncCheckpointRecoveryView` protects that endpoint's own write from
racing an in-progress task, but does nothing for the underlying
dispatch-level race itself).

### 1.4 Existing recovery/reconciliation mechanisms — coverage

**PASS for what exists; FAIL for the worker-death-mid-task scenario
specifically (same shape as Blast's now-closed gap) — VERIFIED FROM
SOURCE.**

- `backend/apps/sync/views.py:207-348` (`SyncCheckpointRecoveryView`,
  `POST /api/sync/recover/<session_name>/`) — re-read in full. Marks a
  genuinely `possibly_stuck` (`_is_possibly_stuck()`, reused verbatim,
  no second threshold) checkpoint `RUNNING → ERROR` via a real
  compare-and-set `UPDATE ... WHERE pk=... AND status='running' AND
  updated_at=<value just read>` (`:302-310`) — a lost concurrent write
  is detected (`updated_count == 0`) and rejected with `409
  concurrent_state_change`, never silently overwritten. Gated by
  `HasSystemAdministrationScope`. Writes exactly one `AuditLog` entry
  on success, zero on any rejection path. `checkpoint_value`,
  `Message`/`Chat`/`Contact` are provably never touched (no import of
  the latter three anywhere in this file).
- Frontend surface: `frontend/src/pages/InboxPage.tsx` and
  `frontend/src/pages/DashboardPage.tsx` (`SyncStatusCard`) both now
  show a `possibly_stuck` warning chip with an admin-gated,
  `ConfirmDialog`-protected "mark as failed" button wired to this same
  endpoint — per `PHASE-13B-...-IMPLEMENTATION-REPORT.md` and
  `PHASE-9-OFFLINE-DEGRADED-MODE-COMPLETION-REPORT.md`, both
  re-confirmed present in this audit's reading of the background
  reports (not independently re-diffed against source this task, since
  no frontend source file needed re-verification for this audit's
  backend-focused goals).
- **What this covers**: exactly the same class of problem 13.A was
  designed for — a checkpoint stuck `RUNNING` past
  `CELERY_TASK_TIME_LIMIT + 60s` for *any* reason (worker killed,
  process crashed, hard time-limit kill, genuinely wedged worker) can
  be manually marked `ERROR` by an admin, unblocking the *next*
  scheduled/targeted run from starting cleanly (a fresh
  `reconcile_session()` call always begins its own new write cycle
  regardless of the old row's terminal value).
- **What this does NOT cover, re-verified as still true**: there is no
  equivalent of Blast's `_maybe_finalize_campaign`-blocking scenario
  here — `SyncCheckpoint` is a single row per session with only four
  possible statuses, not a multi-row batch with a separate
  "does-everything-add-up" finalization step, so there is no
  "permanently blocked container object" analog to a stuck Blast
  campcampaign. What *is* structurally identical to Blast's gap: **the
  underlying cause (worker dies mid-task, no `try/finally`) is the same
  code smell**, and the **remedy that exists today is identical in
  spirit to Blast's chosen fix** — a manual, human-triggered,
  CAS-protected "mark it resolved" action. The difference is Blast's
  fix was built as a *reaction* to a specific FAIL finding; reconciliation's
  equivalent (13.A) was already built **proactively**, before this
  audit, and already covers the scenario.

### 1.5 Stuck/lost/ambiguous conditions — enumerated and re-verified

| # | Scenario | Current behavior | Detected by `possibly_stuck`? | Recoverable via `SyncCheckpointRecoveryView`? |
|---|---|---|---|---|
| A | Worker dies/killed before `reconcile_session()` starts | No checkpoint write occurs; nothing to detect (the *previous* checkpoint value, if any, is untouched) | No (nothing entered `RUNNING`) | N/A — nothing to recover |
| B | Worker dies mid-run, after `checkpoint.status=RUNNING` save but before the final save | Checkpoint stuck `RUNNING` forever (`reconciliation.py:198-206` write (A) already committed; the final write at `:255-268` never reached) — **re-verified this task, no `try/finally` exists** | Yes, once `CELERY_TASK_TIME_LIMIT + 60s` elapses (660s) | **Yes** — exactly 13.A's designed case |
| C | Task exceeds hard time limit (600s), pool kills the child | Same as B (the kill is an uncatchable external signal to the task's own code) | Yes — the single most confident true positive (margin deliberately chosen to sit just past this ceiling, per the prior audit) | Yes |
| D | An exception occurs that is NOT `WahaClientError` (e.g. an unexpected DB error, a bug in `persist_message`, an `IntegrityError` not converted to `DuplicateMessage`) | Propagates out of `reconcile_session()` uncaught by anything in that function; Celery's `autoretry_for=(Exception,)` catches it **at the task level** and retries (re-entering `reconcile_session()` from the top, re-writing `RUNNING`) up to 3 times; if all 3 retries also raise, the task is marked `FAILURE` by Celery but **the checkpoint itself is never written to a terminal status** — stuck `RUNNING` | Yes, once stale enough | Yes, same manual path |
| E | Two reconciliation tasks race for the same session (Section 1.3) | Each completes independently; whichever writes last "wins" the checkpoint's final `status`/`checkpoint_value` — a lost-update, not a corruption (no `Message`/`Chat` risk) | Ambiguous — depends on timing of the read | The CAS guard prevents 13.A's *own* write from being fooled by this, but does not prevent the race itself |
| F | Celery task itself is lost (at-most-once delivery, per the Blast audit's project-wide config finding — Section 1.6 below) before ever starting | No checkpoint write occurs at all (task never ran) | **No** — `possibly_stuck` requires `status == RUNNING`; a never-started task leaves the checkpoint at whatever its *previous* terminal status was, which surfaces instead as `sync_status: 'stale'` once `RECONCILIATION_INTERVAL_SECONDS * 2` elapses (`_derive_sync_status()`, `views.py:87-118`) — a different, already-existing signal, not `possibly_stuck` | N/A — nothing `RUNNING` to recover; `stale` has no dedicated recovery action today (arguably doesn't need one — the next periodic cycle will simply try again) |
| G | Celery beat itself misses a scheduled run (beat process down/restarted) | Same externally-observable shape as F — no new `RUNNING` write occurs on schedule | Same as F — surfaces as `stale`, not `possibly_stuck` | Same as F |
| H | Legitimate retry-backoff sequence (Celery's own `retry_backoff_max=600`, `tasks.py:38-40,77-79`) | Checkpoint cycles `RUNNING` → (retry re-enters, re-writes `RUNNING`) → ... — a fully healthy sequence can legitimately span several hundred seconds | **Yes — a known, sourced FALSE positive** (unchanged from the prior audit's scenario H finding, re-confirmed: `retry_backoff=True, retry_backoff_max=600, retry_jitter=True` still present verbatim at `tasks.py:38-40` and `:77-79`) | Technically yes (the endpoint would succeed), but doing so mid-legitimate-retry wastes that attempt — the same risk the prior audit already flagged, unchanged |

**Row D is this audit's one materially new, concretely-sourced
finding beyond what the prior two audits already established**: the
old audit treated "worker dies" as a single category; this audit
traced that an in-process **exception this codebase's own retry
policy is specifically designed to survive** (per `tasks.py`'s own
docstring: "retrying is provably safe... A permanent failure...simply
exhausts its 3 retries and is recorded as failed") does **not**, in
fact, "record as failed" at the `SyncCheckpoint` level — only the
Celery `AsyncResult` reaches `FAILURE`; the checkpoint itself is left
exactly as stuck as a hard `SIGKILL` would leave it. This is the same
shape gap `reconcile_session()`'s missing `try/finally` has always
been described as (per the roadmap-status audit and the Phase 9
completion report's own footnote), now traced to its precise
consequence for the retry-exhaustion path specifically, not just the
external-kill path.

### 1.6 Celery config re-confirmation (project-wide fact, not
Blast-specific)

**PASS (re-confirmed, unchanged) — VERIFIED FROM SOURCE.**

`backend/config/settings.py:213-232`, the complete `CELERY_*` block,
re-read in full this task:

```python
CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 600
CELERY_TASK_SOFT_TIME_LIMIT = 540
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
```

`CELERY_TASK_ACKS_LATE` and `CELERY_TASK_REJECT_ON_WORKER_LOST` are
**still never set anywhere** (re-grepped the full file this task, zero
hits) — Celery's own defaults apply (`acks_late=False`,
`reject_on_worker_lost=False`), meaning **at-most-once delivery**:
a task acknowledged to the broker on receipt, before execution, is
gone forever if the worker dies mid-execution — no redelivery, ever.
This is the exact project-wide fact the Blast audit found (Section 3
there) — re-confirmed here as applying identically to
`reconcile_session_task`/`reconcile_chat_task`.

**No static `CELERY_BEAT_SCHEDULE` dict exists** — the periodic
schedule is registered via `config/celery.py`'s
`@app.on_after_configure.connect` handler calling
`sender.add_periodic_task(settings.RECONCILIATION_INTERVAL_SECONDS,
app.signature('apps.sync.tasks.reconcile_all_sessions_task'), ...)`
(`config/celery.py:12-28`, re-read this task) — functionally
equivalent to a static schedule, deliberately deferred into a signal
handler so it reads the live Django setting rather than a value frozen
at import time. No change from what the prior audits described.

### 1.7 Container-level health/restart configuration

**PASS for what exists (re-confirmed); no change since prior audits —
VERIFIED FROM SOURCE.**

Both `infrastructure/development/office.yml` and
`infrastructure/office/docker-compose.yml`, re-read in full this task:
`celery-worker`/`celery-beat` run `celery -A config worker -l info` /
`celery -A config beat -l info` verbatim, with `restart: unless-stopped`
on every service in both files. **No Docker `healthcheck:` block
exists on `celery-worker` or `celery-beat` in either file** — only
`redis` has one, and only in the dev compose file
(`infrastructure/development/office.yml:73-77`); the production file
(`infrastructure/office/docker-compose.yml`) has no healthcheck
anywhere. `restart: unless-stopped` means Docker will restart a
container whose **process exits** (crash, `SIGKILL` from an OOM
killer, etc.) — but does **nothing** for a process that is alive but
wedged (deadlocked, stuck in a blocking call with no timeout), and
does nothing to resolve an already-orphaned `SyncCheckpoint` row left
`RUNNING` by the crashed attempt — a fresh worker process starting
under the same `restart` policy has no way to know a previous
in-flight task's checkpoint needs cleanup; that remains the manual
recovery endpoint's job.

### 1.8 WAHA side effects — read-only confirmation (audit goal 7)

**PASS — reconciliation is strictly read/pull, VERIFIED FROM SOURCE,
directly contradicts the possibility of a Blast-shaped double-send
risk.**

`backend/apps/sync/waha_client.py` — `fetch_chat_messages` (`:53-94`)
and `fetch_chats` (`:96-...`) are both implemented as plain
`requests.get(...)` calls (re-grepped: `grep -n "requests\.\(get\|post\|put\)"
apps/sync/waha_client.py` → two hits, both `requests.get`, zero
`requests.post`/`requests.put` anywhere in this file). `reconcile_session()`
(`apps/sync/reconciliation.py`) calls only these two read methods plus
`persist_message()` (`apps/webhooks/services.py`, a pure Django-DB
write, no WAHA call) and `Chat.objects.get_or_create(...)` (pure
Django DB). **There is no WAHA write call anywhere in the
reconciliation code path** — no "mark as read," no send, no session
mutation. This is a materially different risk profile than Blast's
problem: Blast's stuck-recipient recovery had to guard against a
second real WhatsApp send (hence "never imports/calls the BFF client");
reconciliation recovery has **no equivalent constraint to violate in
the first place** — marking a checkpoint `ERROR` and letting the next
run start cleanly cannot cause a duplicate WhatsApp-visible message,
because reconciliation never causes one to begin with. This determines
that reconciliation recovery's safety properties are a strict *subset*
of Blast's — easier to reason about, not harder.

### 1.9 `OutboundOperation`/idempotency relationship (audit goal 8)

**PASS — fully orthogonal, VERIFIED FROM SOURCE.**

`grep -rn "OutboundOperation" backend/apps/sync/` → **zero matches**.
`OutboundOperation` (`backend/apps/operations/models.py`) tracks
outbound sends (idempotency key, destination, `operation_type`,
status) — a concern that belongs entirely to the *sending* side
(Blast, 1:1 messages). Reconciliation reads/persists *inbound* history
and advances its own, unrelated `SyncCheckpoint` watermark. Any future
reconciliation-recovery work has **no reason to touch, reference, or
duplicate** `OutboundOperation`'s idempotency mechanism — they operate
on disjoint models for disjoint purposes.

---

## 2. Risks Found

1. **`reconcile_session()`'s missing `try/finally` remains the true
   root cause** of every "stuck `RUNNING`" scenario in Section 1.5
   (rows B, C, D). This has been known since the original recovery
   design audit and is still present, unchanged, in current source
   (`apps/sync/reconciliation.py:186-268` — the RUNNING write at
   `:198-206` and the terminal write at `:255-268` are not wrapped in
   any exception-safety construct). It is *mitigated* (not eliminated)
   by Celery's `autoretry_for`/`retry_backoff` policy for the two
   Celery-executed task entry points, and by the existing manual
   recovery endpoint for whatever slips through — but the underlying
   fragility is unchanged.
2. **No distributed lock protects against overlapping reconciliation
   runs for the same session** (Section 1.3) — a plain read-then-write,
   not a conditional `UPDATE`. This remains a latent, un-mitigated race
   (lost-update on `SyncCheckpoint`'s own final state only; no
   `Message`/`Chat`/`Contact` integrity risk, since that is protected
   by an unrelated unique constraint).
3. **`possibly_stuck` false-positive risk under legitimate retry
   backoff (row H)** is unchanged from the prior audit — a healthy,
   working-as-designed 3-attempt retry sequence can legitimately exceed
   the 660s threshold, meaning an operator (or any future automatic
   policy) acting on `possibly_stuck` alone can interrupt a task that
   was never actually stuck.
4. **No container-level healthcheck exists for `celery-worker`/
   `celery-beat`** in either Compose file (Section 1.7) — a wedged
   (not crashed) worker process is invisible to Docker's own
   `restart:` policy and to every mechanism in this codebase.
5. **Beat/task-loss scenarios (rows F/G) are invisible to
   `possibly_stuck` entirely** — they surface only as `sync_status:
   'stale'` once `RECONCILIATION_INTERVAL_SECONDS * 2` elapses, a
   different, already-existing code path with no dedicated recovery
   action (arguably none is needed, since the next periodic cycle
   self-heals it, but this is worth stating plainly rather than
   assuming `possibly_stuck`'s coverage is exhaustive).

None of these risks is new discovery beyond what the prior two audits
already established in substance — this audit's contribution is (a)
re-verifying every one of them still holds against current source,
(b) the row-D exception-vs-retry-exhaustion trace (Section 1.5), and
(c) the precedent-based framing (Section 3) that a heavier fix (worker
liveness API, distributed locking, event monitoring) is not what this
project's own recent, closely-analogous decision (Blast) chose to
build for the identical shape of problem.

---

## 3. Scope of Implementation Actually Needed

**Recommendation: none of the heavy options are needed. The minimal,
honest scope — if anything is built at all — is a single, small,
low-risk addition: wrap `reconcile_session()`'s RUNNING→terminal
transition in a `try/finally` so an exception that currently escapes
uncaught (row D, Section 1.5) still reaches a terminal `ERROR` write,
closing the one gap that is structurally different from "worker got
`SIGKILL`'d" (an event no Python code can intercept) and is instead "a
Python exception this codebase's own code could catch, but currently
doesn't."**

This recommendation deliberately follows the Blast precedent's shape
(manual/mitigated, not automatic) for the scenarios that are
**inherently uncatchable** (`SIGKILL`, hard time-limit kill) — for
those, the existing `SyncCheckpointRecoveryView` is already the
correct, sufficient, already-built answer, exactly as it was designed
to be. The `try/finally` addition is narrower than that: it does not
add any new recovery *mechanism* — it makes the **existing** terminal
write reachable in one specific case (an in-process exception) where
it currently silently fails to run, rather than leaving `RUNNING`
forever *unnecessarily*, in a case that is not actually unrecoverable
from inside the task's own code.

**Explicitly NOT recommended, absent new evidence changing this
audit's conclusion**:
- A worker-liveness ping API (`celery.control.ping()`) — not needed to
  make `possibly_stuck` + manual recovery usable; the age-based
  heuristic already works today without it, exactly as it does for
  Blast's stuck-recipient case, which also has no worker-liveness
  check.
- Event monitoring / Flower — a new, separately-operated long-running
  component; disproportionate to the problem this audit found (one
  missing `try/finally`).
- Distributed locking (Section 1.3's race) — real, but not the cause
  of any user-facing symptom this audit or the prior ones found; the
  worst-case outcome is a lost-update on `SyncCheckpoint`'s own
  status field, not data corruption or a duplicate WhatsApp message.
  Worth a future, separate, explicitly-scoped look if it is ever
  observed to matter in practice — not bundled into this fix.
- Automatic recovery / auto-resume — explicitly rejected by the
  project's own very recent, closely-analogous decision (Blast
  finalized decision 6: "no automatic resume/recovery in v1"); nothing
  in this audit's findings provides new evidence to revisit that for
  reconciliation, which has an *easier* safety profile (Section 1.8)
  than Blast, not a harder one.
- A recipient-equivalent "resolve" UI/endpoint beyond what already
  exists — `SyncCheckpointRecoveryView` **already is** reconciliation's
  equivalent of Blast's `BlastRecipientResolveView`; it does not need a
  second, parallel mechanism.

---

## 4. Files Likely to Change (if the minimal scope is approved)

**Backend only, one file, no migration, no new endpoint:**

- `backend/apps/sync/reconciliation.py` — wrap the body of
  `reconcile_session()` (specifically the section between the RUNNING
  write at `:198-206` and the terminal write at `:255-268`) in a
  `try/finally` (or `try/except Exception/else/finally`, exact shape
  to be decided at implementation time) so that **any** exception —
  not only ones already handled by the per-chat `except WahaClientError`
  block — still results in the checkpoint reaching `STATUS_ERROR`
  with a recorded `last_error`, rather than being left `RUNNING`.
  Must preserve every existing guarantee this function's own docstring
  and the recovery/observability audits already established:
  `checkpoint_value` still only advances on a fully successful run;
  `last_run_at` semantics unchanged; `trigger_source`/`task_id`
  recording unchanged; no new WAHA call, no new DB model touched.
- `backend/apps/sync/tests/test_reconciliation.py` (or wherever
  `reconcile_session()`'s existing tests live) — a new test asserting
  that a non-`WahaClientError` exception raised mid-run (e.g. via a
  mocked `persist_message` side effect) still results in the
  checkpoint reaching `STATUS_ERROR`, not staying `RUNNING`.

**Not expected to change**: `apps/sync/models.py` (no schema change —
`STATUS_ERROR`/`last_error` already exist and are already the correct
terminal values), `apps/sync/views.py` (`SyncCheckpointRecoveryView`/
`SyncCheckpointTaskStateView`/`_is_possibly_stuck()` are already
correct and need no change for this fix), `apps/sync/tasks.py`
(Celery's own `autoretry_for` policy is unaffected — this fix changes
what happens *inside* `reconcile_session()` on the final, non-retried
failure, not the retry policy itself), any migration, any
Docker/Compose file, `backend/config/settings.py`/`celery.py`.

**Frontend/BFF**: **no change expected**. The existing
`possibly_stuck` badge + recovery button (`InboxPage.tsx`,
`DashboardPage.tsx`) already correctly surfaces and resolves *any*
checkpoint stuck `RUNNING`, regardless of *why* it got stuck — a
`try/finally` fix that makes fewer checkpoints get stuck in the first
place requires no new UI; it simply means the existing recovery button
appears less often, for a narrower set of genuinely-uncatchable
causes (`SIGKILL`, hard time-limit kill) rather than also catching
ordinary Python exceptions that the code could have handled itself.
This mirrors the Blast precedent's own frontend footprint (a
mirrored-pattern "resolve" UI), except here the equivalent UI already
exists and needs no new work.

---

## 5. USER DECISIONS REQUIRED

Re-checked against the old audit's six open sub-questions
(`NEXT-PHASE-CELERY-WORKER-LIVENESS-DESIGN-AUDIT-REPORT.md` Section 13)
— most are now answered by direct, in-repo precedent (Blast) and this
audit's own findings; stated as recommendations, not unilateral
decisions, per the task's own instruction.

1. **Whether the `try/finally` addition to `reconcile_session()`
   (Section 3/4) is an acceptable scope** — this is the one item from
   the old audit's question 6 that remains a genuine decision: it is
   the only option in this whole audit that touches
   `reconcile_session()`'s own logic, a file every prior related task
   this session has otherwise deliberately left untouched. This audit
   recommends it (it is small, additive, and closes a real,
   concretely-traced gap — row D, Section 1.5) but flags it for
   explicit sign-off before any implementation task touches this file.
2. **Whether the Section 1.3 concurrency race (two reconciliation runs
   overlapping for one session) is worth a future, separately-scoped
   look** — this audit does not recommend addressing it now (no
   observed user-facing symptom, no data-integrity risk beyond a
   lost-update on `SyncCheckpoint`'s own status field), but it remains
   a genuinely open architectural question if the project's operators
   ever want a stronger guarantee here. Not blocking the Section 3
   recommendation.

**Now effectively answered by precedent, not re-opened as questions**
(old audit's items 1, 3, 4, 5):
- Worker-liveness ping API (old item 1): **not needed** — Blast's own
  equivalent fix required none, and reconciliation's existing
  `possibly_stuck` + manual recovery already works without one.
- Event monitoring (old item 3): **not needed** — same reasoning,
  disproportionate to the actual gap found.
- Distributed locking (old item 4): **not needed as part of this
  fix** — see decision 2 above; recommend deferring, not building now.
- Automatic recovery (old item 5): **not needed / not recommended** —
  directly follows the project's own very recent Blast decision
  (finalized decision 6, "no automatic resume/recovery in v1"), and
  this audit finds no new evidence specific to reconciliation that
  would justify departing from that decision here, where the safety
  case is if anything easier (Section 1.8) than Blast's.

Old item 2 (persist task IDs) is **already done** — see Section 1.2;
not a remaining question at all.

---

## 6. Recommended Implementation Order (after approval)

1. Add the `try/finally` (or equivalent) to
   `reconcile_session()` (`apps/sync/reconciliation.py`), ensuring the
   terminal `STATUS_ERROR` write happens for **any** exception, not
   only `WahaClientError` — while preserving `checkpoint_value`'s
   "only advances on a fully successful run" guarantee and every other
   existing field-write contract in that function.
2. Add/extend `apps/sync/tests/test_reconciliation.py` with a test that
   forces a non-`WahaClientError` exception mid-run (e.g. mocking
   `persist_message` to raise) and asserts the checkpoint reaches
   `STATUS_ERROR` with a non-empty `last_error`, not left `RUNNING`.
3. Run the full backend test suite (`manage.py test`) to confirm no
   regression in `reconcile_session()`'s existing, already-tested
   behavior (pagination stopping conditions, `checkpoint_value`
   advancement, `trigger_source`/`task_id` recording, chat-discovery
   best-effort behavior).
4. `manage.py check` / `makemigrations --check --dry-run` (expect: no
   migration, since no schema changes).
5. No frontend/BFF work is expected (Section 4) — confirm this
   assumption once the backend change's exact shape is known, in case
   the `last_error` message format for this new path warrants a
   distinct, operator-legible string (mirroring the existing
   `'Marked as failed by manual recovery...'` convention already used
   by `SyncCheckpointRecoveryView`).

**STOP.** This was a design audit only. No source, config, Docker, or
migration file was modified. No reconciliation was triggered, no
Celery task was called, no WAHA/WhatsApp operation was performed.
Awaiting the user's decisions in Section 5 (specifically item 1) before
any implementation task proceeds.
