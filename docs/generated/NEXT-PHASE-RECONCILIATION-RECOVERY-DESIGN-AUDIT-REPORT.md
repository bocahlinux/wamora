# Possibly-Stuck Reconciliation Recovery — Design Audit Report

**This is a read-only design audit. No source, test, config, Docker,
Compose, `.env`, migration, or Celery configuration file was modified.
No container was started, stopped, or restarted. No reconciliation was
triggered. No WhatsApp message was sent. No WAHA write endpoint was
called. No database state was altered. The existing `possibly_stuck`
detection (`backend/apps/sync/views.py`) was not touched.**

**Conclusion up front:** automatic, unattended recovery is **not
currently safe** to implement, for one concrete, sourced reason: this
codebase has **zero concurrency control** over `SyncCheckpoint` writes
(no row locking, no compare-and-set, no distributed lock, no task-ID
tracking) and **zero test coverage of concurrent/overlapping
reconciliation runs for the same session** — only sequential
reruns are proven idempotent. Any recovery action that writes to a
checkpoint risks a lost-update race against the very task it is trying
to recover from. A **manual, human-triggered, audited** recovery action
— gated behind a conditional (compare-and-set) database update that
requires no schema change — is identified as the safe minimum next
step. Fully automatic recovery is not recommended without first adding
either database-level locking or task-ID-based worker-liveness
verification, both of which are architectural additions, not
implementation details.

---

## 1. Objective

Audit whether, and how, a **safe** recovery mechanism could ever be
built for a `SyncCheckpoint` that `possibly_stuck` has flagged —
without implementing it, and without touching the already-implemented,
already-verified detection logic.

---

## 2. Verified Current Architecture

Re-verified directly this task (not assumed from the prior detection
design audit or its implementation report):

- **`backend/apps/sync/models.py`** — `SyncCheckpoint`: `session`
  (`OneToOneField`, one checkpoint per session), `checkpoint_value`
  (watermark), `last_run_at`, `status` (`idle/running/ok/error`),
  `lag_seconds` (dead field — never written anywhere, re-confirmed by
  grep this task), `last_error`. No `Meta.indexes` beyond the implicit
  unique index on `session`. **No task-identity field of any kind**
  (no `celery_task_id`, no `AsyncResult` reference, nothing).
- **`backend/apps/sync/views.py`** — `SyncStatusView` (unchanged by
  this audit) already returns `possibly_stuck`, computed from
  `status`/`updated_at`, added in the immediately preceding task this
  session. **VERIFIED FROM SOURCE**, re-read in full.
- **No Django admin registration exists for `SyncCheckpoint`** —
  `grep -rln "SyncCheckpoint" --include=admin.py apps/` returned zero
  files this task. **There is currently no operator/admin mechanism of
  any kind for inspecting or manually resetting a stuck checkpoint** —
  not a UI gap, a complete absence.
- **`backend/requirements.txt`** — no task-uniqueness library
  (`celery-once`, `celery-singleton`, etc.), no distributed-locking
  library (`django-redis-lock`, `python-redis-lock`, etc.). Only
  `celery==5.4.0`, `redis==5.0.8`, `psycopg2-binary==2.9.9` (confirming
  the production database is PostgreSQL, relevant to Section 12's
  locking discussion — `SELECT ... FOR UPDATE` is available there,
  unlike the SQLite database this project's own test suite runs
  against).
- **No `select_for_update(`, no Redis lock/`Lock(` usage, anywhere in
  `backend/`** — grepped this task, zero hits. **There is no
  concurrency control of any kind over `SyncCheckpoint` writes today.**

---

## 3. Reconciliation Lifecycle

**VERIFIED FROM SOURCE** — `backend/apps/sync/reconciliation.py`,
`reconcile_session()`, re-traced line by line this task (unchanged
since the detection design audit two tasks ago):

```
1. session = WahaSession.objects.get(name=session_name)
2. checkpoint, _ = SyncCheckpoint.objects.get_or_create(session=session)
3. stop_at_timestamp <- checkpoint.checkpoint_value (pre-run watermark, read once)
4. checkpoint.status = RUNNING; checkpoint.save(['status','updated_at'])   (A)
5. client = WahaClient()
6. [chat_ids is None only] chat discovery — best-effort, never raises
7. for each Chat: for each WAHA history page: for each message: parse -> persist
   (per-chat WahaClientError caught locally; loop continues to next chat)
8. checkpoint.last_run_at = now()
9. status = ERROR (if had_error) or OK; checkpoint_value advanced only on OK
10. checkpoint.save([...])   (B)
```

**Callers**, both re-confirmed this task to reach the exact same
function and the **same per-session checkpoint row**:
- **Periodic, full-session**: Celery beat → `reconcile_all_sessions_task`
  (always Celery, regardless of `RECONCILIATION_EXECUTOR`) →
  `reconcile_session_task.delay(session_name)` per known session.
  **VERIFIED**: `reconcile_all_sessions_task` dispatches unconditionally
  for every `WahaSession`, with **no filter on that session's current
  checkpoint status** — a session already `RUNNING` still gets a fresh
  `reconcile_session_task.delay()` call every `RECONCILIATION_INTERVAL_SECONDS`.
  This is itself a latent concurrent-invocation source, independent of
  any recovery mechanism (Section 8, scenario 9).
- **Targeted, single-chat**: after a confirmed outbound send →
  `trigger_reconciliation()` → `'sync'` (in-process, same request) or
  `'celery'` (`reconcile_chat_task.delay()`) → both call
  `reconcile_session(session_name, chat_ids=[chat_id])` — same
  checkpoint row, narrower chat scope.

---

## 4. Current Failure Modes

**VERIFIED FROM SOURCE**, re-confirmed unchanged from the detection
design audit:

| Trigger | Result |
|---|---|
| Worker crash / `SIGKILL` / OOM-kill | `status` stuck at `RUNNING` permanently — no `try/finally`, no redelivery (`task_acks_late` unset → Celery default `False`, "early ack"). |
| Task revoked (`terminate=True`) | Same — not exercised anywhere in this codebase (`grep -rn "revoke("` → zero hits), analyzed as a hypothetical operator action. |
| Retry exhausted (3 attempts) | Each retry re-enters `reconcile_session()`, re-writing `RUNNING`; final failure leaves the checkpoint at whatever the last attempt left it (`STATUS_ERROR` if it reached step 9, otherwise still `RUNNING`). |
| Unhandled exception, `'celery'` path (periodic job **always** this path) | Caught by `autoretry_for=(Exception,)`, retried up to 3x, then as above. |
| Unhandled exception, `'sync'` executor path | Propagates directly through the Django request/response cycle — **no retry, no Celery safety net at all.** |
| Normal completion | `status` → `OK`/`ERROR`, `last_run_at`/`updated_at` refreshed. No stuck state. |

---

## 5. Celery Behavior

**VERIFIED FROM SOURCE** — every `CELERY_*` setting in
`backend/config/settings.py` re-read and enumerated this task (the
complete set; nothing omitted):

```python
CELERY_BROKER_URL = ...                          # redis
CELERY_RESULT_BACKEND = ...                       # redis
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 600
CELERY_TASK_SOFT_TIME_LIMIT = 540
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
```

**Not set anywhere** (confirmed absent, Celery's documented default
therefore applies):

| Setting | Default when unset | Implication |
|---|---|---|
| `task_acks_late` | `False` | No redelivery if a worker dies mid-task (Section 4). |
| `task_reject_on_worker_lost` | `False` | A lost worker does not cause the broker to requeue the task either. |
| `worker_prefetch_multiplier` | `4` | A worker can hold multiple tasks in its local buffer; not directly a stuck-checkpoint cause, but relevant to how many reconciliation tasks one worker process might be juggling at once. |
| `task_expires` | `None` (never) | A queued-but-not-yet-started task has no expiry — Section 8 scenario 4. |
| `result_expires` | Celery's own default (1 day) | Result-backend lookups for an old task ID would still resolve for a day — relevant only if task IDs were ever persisted (Section 12), which they are not today. |
| Task uniqueness (e.g. `celery-once`) | N/A — no such library | Nothing prevents two `reconcile_session_task` invocations for the same `session_name` from being enqueued or running concurrently. |

`CELERY_TASK_TRACK_STARTED = True` means a task's `AsyncResult.state`
would include `STARTED` (not just `PENDING`/`SUCCESS`/`FAILURE`) **if**
its task ID were known — but **no task ID is persisted anywhere**
(Section 2), so this tracking capability is currently unusable for
recovery purposes without first adding task-ID persistence.

**Existing test evidence, re-read this task**
(`backend/apps/sync/tests/test_tasks.py`):
- `test_rerunning_task_does_not_duplicate_durable_records` — proves two
  **sequential** (not concurrent) full task invocations for the same
  session produce exactly 1 `Message` row, not 2 (idempotent via the
  DB unique constraint).
- `test_worker_style_redelivery_after_retry_eventually_succeeds` — proves
  a transient-failure-then-success sequence recovers correctly.
- `test_retry_policy_is_bounded` — confirms `max_retries=3`,
  `autoretry_for=(Exception,)`.
- **No test anywhere exercises two *concurrent/overlapping*
  `reconcile_session()` calls for the same session** — `grep -in
  "concurrent\|race\|overlap.*session\|simultaneous"
  backend/apps/sync/tests/test_reconciliation.py backend/apps/sync/tests/test_tasks.py`
  found only unrelated hits (WAHA *pagination* overlap, a different
  concept — Section 8 elaborates). This is a genuine, sourced test-
  coverage gap directly relevant to recovery safety.

---

## 6. `RECONCILIATION_EXECUTOR=sync` Behavior

**VERIFIED FROM SOURCE**, re-confirmed unchanged: `apps.sync.executors.trigger_reconciliation()`,
when `RECONCILIATION_EXECUTOR='sync'`, calls
`run_targeted_reconciliation_with_retry()` **directly, in-process,
inside the Django request/response cycle that handled the triggering
outbound send** — no Celery task is created at all for this path. This
means:
- `CELERY_TASK_TIME_LIMIT`/`task_acks_late`/retry policy — **none of
  these apply**, because no Celery task exists to apply them to.
- The only bound on this path's duration is `WahaClient`'s own
  `DEFAULT_TIMEOUT_SECONDS = 10` per HTTP call, multiplied by
  `executors.py`'s `MAX_ATTEMPTS = 3` and (for a full, non-targeted run)
  `DEFAULT_MAX_PAGES = 10` — an **INFERRED**, not enforced, upper bound
  (Section 7 of the prior detection design audit already established
  this; re-confirmed, not re-derived, this task).
- **A stuck checkpoint originating from this path has no Celery task
  to revoke, retry, or inspect at all** — any recovery strategy that
  assumes a Celery task exists (candidates D and, partially, C in
  Section 10) **cannot apply** to a checkpoint stuck via this path.
  Recovery limited to "reset the checkpoint row" (candidates A/B/F)
  would be the only kind of action even theoretically available here.

---

## 7. Concurrency Analysis

Each of the 12 scenarios the task specified, evaluated against the
current, verified source (Section 2's confirmed absence of any locking
mechanism applies to all of them):

| # | Scenario | What the system actually does today |
|---|---|---|
| 1 | Worker alive, reconciliation genuinely takes >660s | `possibly_stuck` reports `true` (a **false positive** relative to actual health) — nothing else happens; detection is read-only (re-confirmed, Section 2 of the detection implementation report). |
| 2 | Worker dead, checkpoint stuck `RUNNING` | `possibly_stuck` reports `true` (a **true positive**) — indistinguishable from scenario 1 by the system itself. **This is the core problem recovery must solve without being able to tell 1 and 2 apart on its own.** |
| 3 | Worker temporarily unreachable (e.g. network partition from Redis) | The task simply hasn't been picked up / can't report progress; from the checkpoint's perspective, identical to scenario 2 until connectivity returns. |
| 4 | Task queued, not yet started | Checkpoint is whatever it was before this task (not yet `RUNNING` from *this* task's perspective) — `task_expires` is unset (`None`), so a queued task waits indefinitely for a free worker slot; not itself a stuck-checkpoint cause. |
| 5 | Task is retrying (within its 3-retry budget) | Checkpoint is `RUNNING` (re-set at the top of every retry attempt) — `possibly_stuck` could still fire if backoff delays push total elapsed time past 660s, even though the task is legitimately, automatically retrying. **Another sourced false-positive path.** |
| 6 | Original task still running when recovery starts | **VERIFIED**: nothing today would even attempt recovery (none exists) — analyzed as the central risk for any *future* recovery: no code path checks "is this still legitimately in progress" before acting. |
| 7 | Original task finishes immediately after recovery marks it failed | **Lost-update race, confirmed by direct code reading**: `reconcile_session()`'s final `.save(update_fields=[...])` (step 10) is a plain, unconditional UPDATE-by-primary-key with no WHERE-clause guard on the row's prior state. If a hypothetical recovery action's write and the original task's own completion write both target the same row, **whichever commits last wins**, silently overwriting the other — Django's ORM `.save()` performs no compare-and-set by default. |
| 8 | Two recovery processes execute simultaneously | Not applicable today (no recovery exists) — for any *future* implementation, this is the same class of race as #7, one level up (two recovery attempts racing each other, not just recovery racing the original task). |
| 9 | Two reconciliation tasks start for the same session | **VERIFIED as already possible today, independent of recovery**: `reconcile_all_sessions_task` dispatches unconditionally per `WahaSession` regardless of that session's checkpoint status (Section 3) — if `RECONCILIATION_INTERVAL_SECONDS` is configured shorter than a session's actual reconciliation time (an operator misconfiguration, not a code bug), or if a targeted trigger fires while a periodic run is still in progress, two `reconcile_session()` calls execute for the same session concurrently **today, with no code change needed to reach this state.** |
| 10 | `'sync'`-executor request still executing while another process reads `possibly_stuck` | Safe today — `SyncStatusView.get()` performs only reads (`SyncCheckpoint.objects.filter(...).first()`), never blocks on or interferes with the in-flight write; Django's default autocommit means the reader sees the last **committed** state, which — depending on timing — could be mid-run (`RUNNING`, `updated_at` from step 4) or post-completion. No corruption risk from the read side. |
| 11 | Django process restarts while reconciliation is running (`'sync'`-executor path) | The in-flight HTTP request is aborted mid-execution by the restart; whatever was last durably committed to the DB (almost certainly still `RUNNING`, from step (A)) remains — functionally identical to a worker crash (Section 4), just for the non-Celery path. |
| 12 | Redis becomes unavailable while recovery is being evaluated | Not applicable to *detection* (`possibly_stuck` reads only PostgreSQL, never Redis — Section 11 of the detection design audit). For a *future* recovery that enqueues a replacement task (candidates C/E), an unavailable Redis broker would simply fail that enqueue attempt (raising a connection error) — recovery logic would need to handle this failure explicitly rather than assume the enqueue always succeeds. |

**Central finding**: scenarios 1/2/3/5 are **indistinguishable from
each other using only `SyncCheckpoint` data** — the system cannot tell
"legitimately slow," "dead worker," "network partition," and
"legitimately retrying" apart without additional information (Celery
worker/task-state visibility, explicitly out of scope for detection and
not yet built for recovery either).

---

## 8. Race-Condition Analysis

(Continues directly from Section 7's per-scenario table; this section
focuses on the two races with the most concrete data-integrity
implications.)

**Checkpoint lost-update race** (Section 7, scenario 7/8) — **VERIFIED
FROM SOURCE**: neither `reconcile_session()`'s writes nor any
hypothetical recovery write use `select_for_update()`,
`F()`-expression-based atomic increments, or a conditional
`.filter(...).update(...)` guarded by the row's previously-read state.
Every write in this codebase's reconciliation path is a plain
`instance.save(update_fields=[...])` — last write wins, unconditionally.

**`checkpoint_value` (watermark) non-monotonicity under concurrent runs**
— **INFERRED** (traced from source, not exercised live): both a
"stuck" run and a "replacement" run that started after it would read
the **same pre-run `checkpoint_value`** as their `stop_at_timestamp`
(Section 3, step 3 — read once, before either has advanced it). If both
runs independently compute their own `latest_timestamp` from the
messages *they* individually observed and persisted, and the *later*-finishing
run happens to have seen an **older** maximum timestamp than the
earlier-finishing run already wrote (plausible if the two runs process
chats/pages in different orders, or one covers a subset the other
doesn't), the later write could **regress** `checkpoint_value` to an
older point than it already reached. This would not lose data (the
`(session, provider_message_id)` unique constraint still prevents
duplicate `Message` rows, Section 9), but it could cause a **future**
run to needlessly re-fetch/re-scan history already covered, in the
worst case a mildly wasteful WAHA re-scan pattern, not a correctness
failure in what's ultimately persisted.

---

## 9. Idempotency Analysis

**VERIFIED FROM SOURCE.**

- **Message persistence is idempotent** by database constraint:
  `Message.Meta.constraints` — `UniqueConstraint(fields=['session',
  'provider_message_id'], name='unique_message_per_session')`
  (`backend/apps/chats/models.py`, re-read this task). `persist_message()`
  catches the resulting `IntegrityError` as `DuplicateMessage`
  (`apps/webhooks/services.py`), and both webhook ingestion and
  reconciliation share this exact function — re-confirmed unchanged.
  `test_rerunning_task_does_not_duplicate_durable_records`,
  `test_rerunning_reconciliation_is_idempotent`, and
  `test_rerunning_paginated_reconciliation_is_idempotent`
  (`apps/sync/tests/test_reconciliation.py`, re-read this task) all
  **prove this for sequential reruns**, not concurrent ones.
- **Chat/Contact identity is idempotent** by the same pattern:
  `UniqueConstraint(fields=['session', 'provider_chat_id'])` and
  `UniqueConstraint(fields=['session', 'provider_contact_id'])`
  (`apps/chats/models.py`), both used via `get_or_create()`.
- **Webhook event ingestion is idempotent**: `WebhookEvent`'s
  `UniqueConstraint(fields=['session', 'provider_event_id'])`
  (`apps/webhooks/models.py`, re-confirmed in the 9.1B task).
- **What is NOT proven idempotent**: `SyncCheckpoint`'s own bookkeeping
  fields (`status`, `last_run_at`, `checkpoint_value`, `last_error`)
  under **concurrent** writes — Section 8's lost-update race is real
  precisely because these fields have **no** uniqueness/idempotency
  guarantee analogous to `Message`'s DB constraint; they are a single
  mutable row updated by plain `.save()` calls.
- **WAHA calls are not idempotent from WAHA's own perspective in any
  way this codebase controls** — reconciliation only performs GET/read
  calls against WAHA history (`WahaClient.fetch_chat_messages`/
  `fetch_chats`), never a write; re-fetching the same history twice
  (e.g. from two concurrent runs) causes redundant read traffic, not a
  WAHA-side data-integrity issue. **Recovery must never call a WAHA
  write endpoint** — none of the candidate strategies in Section 10 do.

**Conclusion**: replaying reconciliation (sequentially OR concurrently)
cannot duplicate durable message/chat/contact/webhook-event records —
this is soundly proven by existing constraints and tests. It **can**
produce an incorrect/regressed `SyncCheckpoint.checkpoint_value` or a
checkpoint `status` that doesn't reflect the true, most-recent outcome,
under concurrent execution — this is the actual risk surface for
recovery, not data loss.

---

## 10. Candidate Recovery Strategies

For each, per the task's required dimensions:

### A. `RUNNING → ERROR`

- **Source evidence**: `ERROR` is already a legitimate, existing
  transition `reconcile_session()` itself makes on a real failure
  (Section 3, step 9) — recovery would just be a *different caller*
  reaching the same state.
- **Safety implications**: if the flagged checkpoint is a **true
  positive** (worker actually dead), this correctly surfaces `sync_status:
  'failed'` (a stronger, already-existing signal) instead of a
  perpetual, silent `'running'`. If it is a **false positive**
  (Section 7, scenarios 1/3/5), this mislabels an actually-healthy,
  in-progress run as failed — but see Section 8: because the *original*
  task's own eventual completion write happens **after** recovery's
  write (if the original truly is still running), the original task's
  write will simply **overwrite** recovery's premature `ERROR` with the
  real outcome once it finishes — self-correcting, **unless** timing is
  adversarial (Section 7, scenario 7), which is exactly the case a
  compare-and-set write (Section 12) would close.
- **Race conditions**: Section 8's lost-update race applies directly.
- **Data corruption**: none at the `Message`/`Chat`/`Contact` level
  (Section 9) — only checkpoint bookkeeping is at risk, and only
  temporarily/cosmetically.
- **Duplicate execution risk**: none from A alone (A does not enqueue
  anything) — only if something else (an operator, or an automatic
  policy) reacts to the new `ERROR` state by re-triggering.
- **Idempotency**: the write itself (`status=ERROR`) is idempotent
  (applying it twice has the same end state) — the *risk* is the race
  with an unrelated, concurrent write, not repetition of A itself.
- **Reversible**: yes — the next periodic cycle (Section 3 — dispatched
  unconditionally regardless of checkpoint status) will naturally
  attempt reconciliation again and can move the checkpoint to `OK`.
- **Affects WAHA/message state**: no — a pure DB write.

### B. `RUNNING → IDLE`

- **Source evidence**: `IDLE` is the model's default value but is
  **never observably reached by any real code path** today (confirmed
  in the 9.1A/9.1B design work, re-confirmed here) — using it for
  recovery would be the **first** code path to ever intentionally set
  it.
- **Safety implications**: **worse than A for observability** —
  `_derive_sync_status()` groups `IDLE` together with `RUNNING`,
  reporting `sync_status: 'running'` (re-verified this task, Section 2
  of the file). A checkpoint "recovered" to `IDLE` would still display
  as `'running'` to any API consumer — actively **more** misleading
  than `ERROR`, not less, since it looks identical to a healthy,
  currently-executing run.
- **Race conditions**: identical to A.
- **Duplicate execution risk**: also does **not** itself trigger a new
  run — `reconcile_all_sessions_task` doesn't filter by checkpoint
  status at all (Section 3), so `IDLE` has no functional advantage over
  `ERROR` for "making the next run happen sooner." **Not recommended.**

### C. `RUNNING → retry` (recovery explicitly re-invokes reconciliation)

- Functionally overlaps with E; see E's analysis. The distinguishing
  feature of "retry" (as opposed to a fresh independent enqueue) would
  be reusing the *same* Celery task's retry mechanism — but Celery's
  own retry (`self.retry()`) can only be invoked from **inside** the
  currently-executing task itself, not from an external recovery
  process acting on a checkpoint row. An external actor cannot "retry"
  a task it doesn't have the task instance/context for. **Without a
  persisted task ID (Section 2), C is not implementable as a distinct
  concept from E at all** — it collapses into E.

### D. Revoke an existing Celery task

- **Source evidence**: `celery_app.control.revoke()` is a real Celery
  API, but **completely unused anywhere in this codebase** (Section 2).
- **Blocking prerequisite, not just a risk**: revoking requires a task
  ID. **None is persisted anywhere** (Section 2) — `reconcile_session_task.delay()`/
  `reconcile_chat_task.delay()` are both fire-and-forget calls whose
  returned `AsyncResult.id` is discarded (`apps/sync/executors.py`,
  `apps/sync/tasks.py`, re-confirmed this task). **D cannot be
  implemented today without first adding task-ID persistence — a
  schema change (Section 14).**
- **Safety implications** (if the prerequisite were met): `terminate=True`
  sends `SIGTERM`/`SIGKILL` to a worker process that may be
  legitimately, successfully midway through real work — destroying that
  work (though not corrupting data, Section 9) and wasting it. Also
  **inapplicable** to a checkpoint stuck via the `'sync'`-executor path
  (Section 6) — there is no Celery task to revoke there at all.

### E. Enqueue a replacement task

- **Source evidence**: technically simple —
  `reconcile_session_task.delay(session_name)` is already public,
  tested, working code; a recovery action *could* call it without any
  new capability.
- **Safety implications**: if the flagged checkpoint is a false
  positive, this creates a genuine **second, concurrent**
  `reconcile_session()` execution for the same session (Section 7,
  scenario 9 — notably, this exact scenario is **already possible today
  without any recovery code at all**, Section 3's finding about
  `reconcile_all_sessions_task`'s lack of status filtering). Message-level
  data is safe (Section 9); checkpoint bookkeeping is not
  (Section 8).
- **Race conditions**: the watermark non-monotonicity risk (Section 8)
  applies specifically to this candidate and to C.
- **Duplicate execution risk**: real, by construction — this candidate
  **is** the duplicate-execution scenario.
- **Idempotency**: the *replacement* task's own execution is internally
  idempotent (same guarantees as any `reconcile_session()` call) — the
  risk is entirely in the *interaction* between it and a possibly-still-
  running original, not in either task alone.
- **Reversible**: the enqueue itself cannot be un-sent once it reaches
  Redis (no unsend), though its *effects* (Message rows) are safe by
  construction.

### F. Reset checkpoint timestamps (without changing `status`)

- **Safety implications — the most dangerous candidate found**: setting
  `updated_at` to "now" while leaving `status = RUNNING` unchanged would
  make `possibly_stuck` **recompute to `false`** immediately (Section
  6/8 of the detection design audit — `possibly_stuck` is entirely a
  function of these two fields). If the underlying task is genuinely
  dead, this **actively hides** the exact condition detection exists to
  reveal — a checkpoint could be kept perpetually "fresh-looking" by
  repeated timestamp resets while never actually progressing, which is
  a **worse** outcome than doing nothing. **Not recommended under any
  circumstance** without also changing `status` to something that isn't
  `RUNNING`.

### G. Combine multiple actions

- Inherits the full union of A/B/C/D/E/F's individual risks. Any
  combination must satisfy the *strictest* constituent action's
  safeguards (Section 12) — e.g., combining A with E requires both the
  compare-and-set guard (for A's write) and acceptance of concurrent-
  execution risk (for E's enqueue).

---

## 11. Safety Analysis Summary

No candidate is safe to run **fully automatically and unattended**
today, because none of them can reliably distinguish a true positive
(Section 7, scenario 2/6) from a false positive (scenarios 1/3/5) using
only `SyncCheckpoint` data — this is the same limitation the detection
design audit already named for detection itself, now shown to matter
more acutely for recovery, where an incorrect action has a real (if
bounded — Section 9) cost. **A (`RUNNING → ERROR`), gated by a
compare-and-set write (Section 12), is the least-risky candidate** —
self-correcting if wrong, does not itself cause duplicate execution,
and matches an existing, well-understood status value. **F is actively
unsafe. B offers no advantage over A and is more misleading. D is
currently unimplementable without a schema change.**

---

## 12. Required Safeguards

Evaluated against source evidence, not assumed necessary by default:

| Safeguard | Necessary for which candidate(s)? | Schema change needed? | Basis |
|---|---|---|---|
| **Atomic conditional UPDATE (compare-and-set)** — e.g. `SyncCheckpoint.objects.filter(pk=cp.pk, status=RUNNING, updated_at=cp.updated_at).update(status=ERROR, ...)`, checking the affected-row count | **A, B, C/E, G** — any write-based candidate | **No** — pure query-logic change, no new column | Directly closes the lost-update race (Section 8) — a write only applies if the row is still exactly as recovery last observed it; if the original task already finished, the conditional UPDATE matches 0 rows and recovery correctly no-ops. **The single most important, immediately available safeguard.** |
| **Database row locking (`select_for_update()`)** | An alternative/complement to compare-and-set | No | Works on PostgreSQL (production, `psycopg2-binary` confirms) but **not** on SQLite (this project's own test database, `config.settings_test`) — a portability consideration for whoever implements and tests this. Compare-and-set achieves a similar safety property without this portability gap. |
| **Task ID tracking** (new `celery_task_id` field) | **D only** (revoke); would also strengthen C/E by letting recovery check `AsyncResult(task_id).state` before acting | **Yes** — new column, a migration | Currently absent entirely (Section 2) — an explicit architectural prerequisite for D, not an optional nicety. |
| **Worker liveness verification** (`celery_app.control.ping()`) | Would reduce false positives for **any** candidate, especially distinguishing scenario 1/3 from 2 (Section 7) | No (no schema change; a runtime capability addition) | Not implemented anywhere (re-confirmed, matching the prior roadmap audit's finding) — a real risk-reducer, but adds its own failure modes (a ping timeout is itself ambiguous) and was explicitly out of scope for detection; the same "not required, but valuable" framing applies to recovery. |
| **Recovery cooldown / max recovery attempts** | Any *automatic, periodic* recovery policy | Depends — a simple cooldown could be computed from `updated_at` alone (no schema change); a true attempt *counter* needs a new field | Prevents a flapping loop repeatedly "recovering" the same session if the underlying cause (e.g. a persistent WAHA/network issue) hasn't actually cleared. Not needed for a one-shot, manually-triggered action. |
| **Audit trail** | Any recovery action, manual or automatic | No — `apps.audit`'s existing `AuditLog` model already exists and is already used for sensitive operations elsewhere in this codebase | A recovery action changing operational state should be recorded the same way this project already records other sensitive actions — a reuse of existing infrastructure, not a new mechanism. |
| **Manual (human-triggered) recovery, not automatic** | Strongly recommended as the *first* safe increment | No | A human can cross-check other signals (WAHA's own dashboard, logs, Sentry/monitoring if any) before acting, and naturally rate-limits by not clicking repeatedly — sidesteps the cooldown/attempt-counter requirement entirely for a first version. |
| **Session-level lock / Redis distributed lock** | Would prevent concurrent `reconcile_session()` invocation **at its root**, for both recovery-triggered and ordinary periodic/targeted overlap (Section 7, scenario 9 — already possible without recovery) | No new dependency (Redis already provisioned), but a genuine new usage pattern/architecture | Arguably higher-leverage than any recovery safeguard, since it would also fix the pre-existing, recovery-independent concurrent-dispatch gap named in Section 3. A real architectural option, not a minor detail — flagged as a **user decision** (Section 16). |
| **Celery task uniqueness** (e.g. adopting a library, or a Redis-lock-backed custom check in `trigger_reconciliation()`/`reconcile_all_sessions_task`) | Same root-cause fix as the above, implemented at the Celery layer instead of the DB layer | No new dependency required if hand-rolled via Redis; a new dependency if using a library | Alternative implementation of the same idea; a genuine architectural choice, not a detail. |

---

## 13. Proposed State Machine

**Two framings, deliberately not collapsed into one, because they
require different schema commitments:**

### 13.A — Derived-only (no schema change; matches today's actual model)

```
             ┌─────────────────────────────┐
             │ SyncCheckpoint.status        │
             │ (persisted: idle/running/ok/error) │
             └──────────────┬────────────────┘
                             │
        RUNNING ──(possibly_stuck: true, ephemeral, computed)──▶ shown to operator
                             │
              (human reviews, decides to act)
                             │
                    RUNNING ──▶ ERROR   (candidate A, compare-and-set guarded)
```

`possibly_stuck` remains exactly what it is today — a purely computed,
never-persisted overlay on the existing four-value `status` enum. A
manual recovery action is just an ordinary, existing `RUNNING → ERROR`
transition, performed by a new caller (an authenticated operator
action) instead of `reconcile_session()` itself, gated by the
compare-and-set safeguard (Section 12). **No new persisted state, no
migration.** This is the framing this audit recommends starting with.

### 13.B — Attempt-tracked (schema change required)

```
RUNNING → POSSIBLY_STUCK (still just the existing possibly_stuck flag,
                           not a new status value — "possibly stuck" is
                           a read-time judgment, not a state the row
                           itself should durably claim to be in, to
                           avoid a checkpoint whose OWN status field
                           contradicts itself in ambiguous ways)
    │
    ▼ (automatic or manual recovery attempt)
RECOVERY-CANDIDATE → mark attempted (new field: recovery_attempted_at,
                                       recovery_count)
    │
    ├─▶ RECOVERED   (checkpoint moved to ERROR or a fresh RUNNING from a
    │                replacement task; requires the compare-and-set guard,
    │                Section 12, to avoid racing the original task)
    ├─▶ ABANDONED    (recovery_count exceeds a max-attempts safeguard —
    │                 requires the same new counter field)
    └─▶ MANUAL-INTERVENTION (explicitly requires a human — the honest
                              terminal state when automatic recovery
                              cannot safely proceed, e.g. because task-ID-based
                              worker-liveness cannot be established)
```

**This framing requires new `SyncCheckpoint` fields** (at minimum
`recovery_attempted_at`, and a `recovery_count` if a max-attempts
safeguard is wanted) **— an explicit schema change, flagged here as an
architectural decision (Section 14), not assumed or designed further in
this audit.** `possibly_stuck` itself is deliberately **not** proposed
to become a new persisted `status` enum value (e.g. adding
`STATUS_POSSIBLY_STUCK` to `STATUS_CHOICES`) — doing so would conflate
a read-time heuristic with the row's own durable claim about itself,
and would require updating `_derive_sync_status()`'s existing five-value
`sync_status` contract (an API-breaking change per `docs/CLAUDE.md`
rule 8), which nothing in this task's evidence justifies.

---

## 14. Schema Requirements

**Explicitly flagged as architectural, per the task's own instruction —
none of these are designed or implemented here:**

- **13.A (recommended starting point) requires NO schema change** —
  confirmed: a manual, compare-and-set-guarded `RUNNING → ERROR`
  transition uses only fields that already exist.
- **13.B (attempt-tracked automatic recovery) requires new
  `SyncCheckpoint` fields** — at minimum a timestamp
  (`recovery_attempted_at`), and a counter (`recovery_count`) if a
  max-attempts safeguard is wanted (Section 12) — **a migration.**
- **Candidate D (revoke) requires a new `celery_task_id` field** —
  **a migration**, and a corresponding change to
  `apps/sync/tasks.py`/`executors.py` to actually capture and persist
  the ID returned by `.delay()` (currently discarded everywhere,
  Section 2) — **this alone is a non-trivial scope addition**, touching
  files this audit's own no-touch rule (and the recovery boundary
  established by the detection design audit) currently keeps untouched.
- **Session-level/distributed locking** (Section 12) does not require a
  `SyncCheckpoint` schema change (a Redis key is not a Django model
  field) but is a genuine new architectural component regardless.

---

## 15. Operational/Audit Requirements

- **`apps.audit`'s `AuditLog` model already exists** in this codebase
  and is already used for other sensitive operations (confirmed present
  via the app listing in the prior roadmap audit, re-confirmed by its
  continued presence in `backend/apps/` this task) — any recovery
  action, manual or automatic, should write an entry here, reusing
  existing infrastructure rather than inventing a parallel logging
  mechanism.
- **No admin/operator UI exists today** (Section 2) — a manual recovery
  action would need *some* authenticated surface to trigger it (a new,
  narrowly-scoped API endpoint, or Django admin registration + a custom
  admin action) — this is itself a design choice for the follow-up
  implementation task, not resolved here.
- **No monitoring/alerting integration was found anywhere in this
  codebase** (no Sentry, no PagerDuty, no webhook-out-on-alert
  mechanism) — `possibly_stuck` is visible only to whoever/whatever
  polls `GET /api/sync/status/`; recovery cannot assume an operator
  will notice promptly unless something is built to surface it more
  actively (out of scope for this audit, named for completeness).

---

## 16. User Decisions Required

Per the task's own escalation bar (architecture/data-safety only):

1. **Whether recovery should ever be automatic, or should start (and
   possibly remain) manual/human-triggered only.** This is the single
   most consequential decision — Section 11 recommends manual-first,
   but this is a product/risk-tolerance call, not something this audit
   can decide unilaterally.
2. **Whether recovery may mark `RUNNING → ERROR`.** Materially affects
   what an operator sees (`sync_status: 'failed'`) and could surprise
   someone expecting `'running'` to always mean "actually in progress."
   Section 10/11 recommend this as the least-risky candidate, but it is
   still a real behavior change requiring sign-off.
3. **Whether recovery may enqueue a replacement task** (candidates C/E)
   — this creates genuine concurrent-execution exposure (Section 7,
   scenario 9) that, while not data-corrupting (Section 9), is a
   meaningful operational behavior change (duplicate WAHA traffic,
   checkpoint watermark risk, Section 8).
4. **Whether task identity must be persisted** (a schema change,
   Section 14) — required before candidate D (revoke) can even be
   considered; without this decision, D remains off the table entirely.
5. **Whether schema changes are acceptable for 13.B's attempt-tracking
   framing**, or whether 13.A's no-schema-change framing should be the
   permanent design, not just a starting point.
6. **Whether Redis/distributed locking (or an equivalent Celery
   task-uniqueness mechanism) should be introduced** — Section 12 notes
   this would fix the concurrent-dispatch gap at its root (and is
   already latent today, independent of recovery, Section 3) — a
   genuine architectural addition, not a recovery implementation detail
   alone.

**Not escalated** (naming, formatting, minor implementation choices,
per the task's own instruction): exact endpoint path/method for a
manual-recovery trigger, exact `AuditLog` field values, exact cooldown
duration if one is eventually built.

---

## 17. Recommended Implementation Scope For A Future Task

**If the user decisions in Section 16 are resolved in favor of starting
with 13.A (manual, no schema change):**

- A new, narrowly-scoped, authenticated endpoint or admin action that:
  1. Reads the target checkpoint and re-confirms `possibly_stuck` is
     still `true` at the moment of the request (never trusts a stale
     client-side read).
  2. Performs the `RUNNING → ERROR` transition via a **compare-and-set**
     `.filter(pk=..., status=RUNNING, updated_at=<the exact value just
     read>).update(...)` — treating an affected-row-count of 0 as "the
     checkpoint already changed underneath us, do nothing" rather than
     an error.
  3. Writes an `AuditLog` entry recording who triggered it and when.
  4. Returns a clear response distinguishing "recovered" from "already
     no longer stuck" (the compare-and-set's 0-row case).
- **This would very likely require no `SyncCheckpoint` migration at
  all** — confirmed by Section 14.
- **Explicitly out of scope for that future task, per this audit's own
  findings**: automatic/periodic recovery (needs Section 16 decisions
  1 and, likely, 6), task revocation (needs decision 4 + a migration),
  worker-liveness checking (a separate, heavier feature, per the prior
  roadmap audit).

---

## 18. Explicit Non-Goals

- **This audit does not implement anything** — no code, no migration,
  no endpoint.
- **Automatic recovery is not designed in detail** — only its
  prerequisites (Section 12) and risks (Sections 7/8/10/11) are
  established.
- **Celery worker liveness checking is not designed** — named only as a
  risk-reducer that recovery could optionally build on later.
- **The existing `possibly_stuck` detection logic is unchanged and was
  not re-audited for correctness** — this task took it as a given,
  verified-elsewhere input.
- **No change to `sync_status`'s existing five-value contract** — 13.B's
  framing explicitly avoids adding a new `status` enum value.
- **No distributed-locking implementation** — named as a candidate
  safeguard/architectural option (Section 12/16), not designed.

---

## 19. Verification Limitations

**VERIFIED FROM SOURCE** (directly read/grepped this task): full
`reconcile_session()` control flow and both callers (re-confirmed
unchanged); complete `CELERY_*` settings enumeration and confirmed
absence of `task_acks_late`/`task_reject_on_worker_lost`/task-uniqueness
libraries/locking code/admin registration/task-ID persistence;
`Message`/`Chat`/`Contact`/`WebhookEvent` unique constraints; existing
test coverage for sequential (not concurrent) reruns.

**INFERRED** (reasoned from documented Celery/library behavior or from
tracing code paths, not exercised live): Celery's default
`task_acks_late=False`/`task_reject_on_worker_lost=False` behavior when
unset; the checkpoint-watermark non-monotonicity risk under concurrent
runs (Section 8 — plausible from tracing the code, not observed);
`revoke(terminate=True)`'s effect on an in-flight task.

**NOT VERIFIED** (would require live infrastructure this audit did not
touch, per its strict read-only scope):
- Whether the lost-update race (Section 8) has ever actually occurred in
  this project's real deployment.
- Real-world timing of how often scenario 7 (recovery-vs.-original-task
  finish-ordering) would actually occur in practice.
- Whether `CELERY_TASK_TIME_LIMIT` is honored by the specific worker
  pool configuration in the real deployment (same limitation already
  named in the detection design audit, not re-resolved here).
- Any behavior of a Django admin action or new endpoint, since none was
  implemented.

---

## 20. Final Conclusion

Automatic, unattended recovery is **not recommended today**. The
blocking reason is concrete and sourced, not speculative: this
codebase has no mechanism — no row lock, no compare-and-set, no
distributed lock, no persisted task ID — to prevent a recovery action
from racing the very reconciliation run it is trying to recover from,
and this exact concurrent-execution scenario has **zero test coverage**
anywhere in the existing suite. Message-level data is safe under
concurrency (proven by existing unique constraints), but
`SyncCheckpoint`'s own bookkeeping fields are not.

The safe path forward identified by this audit is narrow and
achievable without a schema change: a **manual, human-triggered**
`RUNNING → ERROR` action, gated by a **compare-and-set** conditional
update (closing the one race that matters most, Section 8/12), audited
via the existing `AuditLog` mechanism (Section 15). Fully automatic
recovery, task revocation, and root-cause distinction (dead worker vs.
merely slow) all remain explicitly future, separately-decided work,
gated on the user decisions in Section 16.

**STOP.** This was a design audit only. No recovery code, no Celery
worker-liveness code, and no change to `possibly_stuck` or any other
file was implemented. Awaiting the user's decisions in Section 16
before any further action.
