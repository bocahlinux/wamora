# "Possibly Stuck" Reconciliation Detection — Design Audit Report

**This is a read-only design audit. No source, config, test, migration,
dependency, database, or documentation file was modified. No container
was started, stopped, or restarted. No Celery task, reconciliation run,
or WAHA write endpoint was triggered. Recovery is explicitly NOT
designed here — only detection.**

**Conclusion up front:** a `possibly_stuck` boolean can be added to the
existing `GET /api/sync/status/<session_name>/` response with **zero
new database queries**, **zero schema change**, and **zero dependency
on Celery worker liveness**, computed purely from
`SyncCheckpoint.status` and `SyncCheckpoint.updated_at` — both already
fetched by the view today. The threshold is not arbitrary: this audit
found a real, sourced, already-configured value
(`settings.CELERY_TASK_TIME_LIMIT = 600` seconds) that bounds the
dominant path by which a checkpoint enters `RUNNING`. Two candidate
threshold formulas are presented in Section 7, not a single invented
number.

---

## 1. Objective

Design — without implementing — a read-only signal that flags a
`SyncCheckpoint` which has remained in `RUNNING` for an abnormally long
time, so this can be surfaced to an operator via the existing
sync-status endpoint. Detection and recovery are treated as strictly
separate concerns; this audit deliberately does not design recovery.

---

## 2. Current Reconciliation Lifecycle

**VERIFIED FROM SOURCE** — `backend/apps/sync/reconciliation.py`,
`reconcile_session()`, traced line by line this task:

```
1. session = WahaSession.objects.get(name=session_name)
2. checkpoint, _ = SyncCheckpoint.objects.get_or_create(session=session)
3. stop_at_timestamp read from checkpoint.checkpoint_value (pre-run watermark)
4. checkpoint.status = STATUS_RUNNING
   checkpoint.save(update_fields=['status', 'updated_at'])   <-- (A)
5. client = WahaClient()  (or injected)
6. [optional] chat discovery (_discover_chats) — best-effort, never raises
7. for each Chat row belonging to this session:
     for each page of WAHA history (bounded: page-size / watermark / max_pages):
       for each raw message: parse -> persist (idempotent, DB-constraint-backed)
     (WahaClientError for one chat is caught locally — recorded, loop continues)
8. checkpoint.last_run_at = timezone.now()
9. if result.had_error: checkpoint.status = STATUS_ERROR; checkpoint.last_error = ...
   else:                checkpoint.status = STATUS_OK; checkpoint.checkpoint_value = latest_timestamp
10. checkpoint.save(update_fields=['status','last_run_at','last_error','checkpoint_value','updated_at'])  <-- (B)
```

**Callers** (both reach the exact same function, `apps.sync.reconciliation.reconcile_session`,
per this codebase's own stated design — "nothing here adds a second
persistence path"):
- **Periodic, full-session**: Celery beat → `reconcile_all_sessions_task`
  (unconditionally a Celery task, regardless of
  `RECONCILIATION_EXECUTOR`) → `reconcile_session_task.delay(session_name)`
  per known session → `reconcile_session(session_name)` (no `chat_ids`,
  so ALL of that session's chats, plus chat discovery).
- **Targeted, single-chat**: after a confirmed outbound send →
  `apps.sync.executors.trigger_reconciliation()` → dispatches per
  `settings.RECONCILIATION_EXECUTOR`:
  - `'sync'`: calls `run_targeted_reconciliation_with_retry()` **directly,
    in-process, inside the Django request/response cycle** — no Celery
    involvement at all.
  - `'celery'`: enqueues `reconcile_chat_task.delay(...)`, which then
    calls the same retry helper from inside a Celery worker.
  Both ultimately call `reconcile_session(session_name, chat_ids=[chat_id])`
  — **the same checkpoint row** as the periodic job, just scoped to one
  chat.

**Important, previously under-examined finding**: both call paths write
to the **same per-session `SyncCheckpoint` row** (`OneToOneField`,
Section 5). A `possibly_stuck` checkpoint could therefore originate from
either the periodic Celery job *or* a targeted single-chat trigger — the
detection design (Section 6) must not assume the periodic path is the
only source of a `RUNNING` state.

---

## 3. Current `RUNNING` State Behavior

**VERIFIED FROM SOURCE.**

- `checkpoint.status` becomes `RUNNING` at line (A) above — **before**
  any WAHA call, any parsing, or any message persistence happens. This
  write is committed to the database immediately (`.save()`, not merely
  held in memory).
- `checkpoint.updated_at` (from `TimeStampedModel`,
  `apps/core/models.py`, `auto_now=True`) is updated by **every**
  `.save()` call on this model — including the write at (A). This means
  **`updated_at` is set to "now" at the exact moment a checkpoint enters
  `RUNNING`**, and is not touched again until the run reaches its own
  final save (B), whether that happens 2 seconds or 2 hours later (or
  never, if the process dies first).
- `checkpoint.last_run_at` is **only** set at step 8, near the very end
  of a run, immediately before the final save. **A checkpoint stuck in
  `RUNNING` still shows whatever `last_run_at` value the *previous*,
  successfully-completed run left behind (or `None`, if this is the
  session's very first run).** This makes `last_run_at` actively
  misleading for stuck-state measurement — Section 5 elaborates.
- Nothing else in this codebase reads or writes `SyncCheckpoint.status`
  outside `reconciliation.py` — confirmed by a repository-wide grep for
  `SyncCheckpoint` (all hits are in `models.py`, `reconciliation.py`,
  `views.py` (read-only), and test files).

---

## 4. Failure/Crash Paths

Each scenario the task asked for, evaluated **VERIFIED FROM SOURCE**
where the codebase determines the outcome, and **INFERRED**/
**NOT VERIFIABLE WITHOUT RUNTIME DATA** where it depends on
Celery/infrastructure behavior this audit cannot execute:

| Scenario | What happens to the checkpoint | Basis |
|---|---|---|
| **Celery worker process crashes** (segfault, container OOM-killed, `docker kill`) | Checkpoint stays `RUNNING` **permanently**. No code path resets it. `CELERY_TASK_ACKS_LATE`/`task_reject_on_worker_lost` are **not set anywhere** in `config/settings.py` (grepped this task, zero hits) — Celery's documented default is `task_acks_late=False` ("early ack": the broker is told the task was received *before* it runs), which means **the broker does not know to redeliver the task to another worker** if this worker dies mid-execution. | VERIFIED FROM SOURCE (absence of the setting) + INFERRED (Celery's documented default behavior for an unset `task_acks_late`, not independently re-verified against a live broker this task). |
| **Process is killed (`SIGKILL`)** | Same as above — a `SIGKILL` cannot be caught by any Python `except` or `finally`; whatever was last written to the DB (the `RUNNING` state from step (A)) remains. | VERIFIED FROM SOURCE (no signal handling anywhere in this code path) — general OS/process behavior, not project-specific. |
| **Task is revoked** (`celery_app.control.revoke(..., terminate=True)`) | Not exercised anywhere in this codebase — **no code calls `.revoke()`** (grepped this task, zero hits). Analyzed as a hypothetical operator action: `terminate=True` sends `SIGTERM`/`SIGKILL` to the executing worker process, which — like the scenarios above — does not run `reconcile_session()`'s remaining Python code (steps 8–10), leaving the checkpoint at `RUNNING`. | INFERRED (Celery's documented `revoke(terminate=True)` semantics) — this codebase has no code path that triggers it, so this is a theoretical operator-initiated scenario, not a self-inflicted one. |
| **Task retry exhausted** (`reconcile_session_task`'s `max_retries=3` all fail) | Each retry attempt re-enters `reconcile_session()` from the top, re-setting `status=RUNNING` again (harmless — already `RUNNING`) before failing again. After the 3rd retry's final failure, Celery marks the task `FAILURE` — but **nothing in `apps/sync/tasks.py` catches this to reset the checkpoint**; the checkpoint is left exactly as the last failed attempt left it, almost always still `RUNNING` (unless that attempt's exception happened to occur *after* step 9's status write but before step 10's save completed — an even narrower window, still leaving `RUNNING` or a half-written state). | VERIFIED FROM SOURCE (`tasks.py` has no `on_failure`/`link_error` handler for either task; `reconciliation.py` has no outer `try/finally`). |
| **Reconciliation raises an unexpected exception** (e.g. a bug, a DB error mid-loop) | For `RECONCILIATION_EXECUTOR='celery'` (periodic job is **always** this path, regardless of the setting — Section 2): caught by `@shared_task(autoretry_for=(Exception,), max_retries=3, retry_backoff=True, ...)`, retried up to 3 times, then same as "retry exhausted" above. For the **targeted, `'sync'`-executor** path: the exception propagates directly up through the Django request/response cycle (caught only by DRF's generic `EXCEPTION_HANDLER`, which returns a 500 to the caller) — **no retry, no Celery safety net at all**, checkpoint left at `RUNNING` immediately on the very first failure. | VERIFIED FROM SOURCE. |
| **Reconciliation completes normally** | Step 9–10: status becomes `OK` or `ERROR`, `last_run_at` and `updated_at` both refreshed. No stuck state. | VERIFIED FROM SOURCE. |

**Additional sourced finding — the "sync" executor path is the more
exposed one**: for the targeted single-chat trigger, `RECONCILIATION_EXECUTOR='sync'`
means `reconcile_session()` runs synchronously inside an HTTP
request/response cycle with **no Celery time limit, no autoretry, no
redelivery mechanism whatsoever** — the entire safety net analyzed above
only applies when Celery is actually involved. An unhandled exception
here (e.g. an unexpected `WahaClientError` subtype, a DB integrity
error not already caught) leaves the checkpoint `RUNNING` on the very
first occurrence, with zero built-in recovery attempt. This was not
previously called out this explicitly in earlier reports and is a
directly relevant input to Section 7's threshold analysis.

---

## 5. Existing Checkpoint/Timestamp Fields

**VERIFIED FROM SOURCE**, `backend/apps/sync/models.py` +
`apps/core/models.py`:

| Field | Type | Set when | Suitable for "time since entering RUNNING"? |
|---|---|---|---|
| `status` | `CharField`, choices `idle/running/ok/error` | Steps (A), (B) | N/A — this is the state itself, not a timestamp |
| `updated_at` | `DateTimeField(auto_now=True)` | **Every** `.save()`, including (A) | **Yes — the correct field.** Reflects exactly when the checkpoint last transitioned (into `RUNNING`, or out of it). |
| `last_run_at` | `DateTimeField(null=True)` | **Only** at step 8/9, i.e. only on a *completed* run | **No — actively misleading while stuck.** Holds the previous run's completion time (or `None`), not "when did the current, still-`RUNNING` attempt begin." |
| `created_at` | `DateTimeField(auto_now_add=True)` | Row creation only | No — irrelevant to a specific run's duration. |
| `checkpoint_value` | `CharField`, watermark | Only on successful completion | No — unrelated to timing. |
| `lag_seconds` | `PositiveIntegerField(null=True)` | **Never written anywhere** (confirmed by the same grep used in the original Phase 9.1 design audits — a known, pre-existing, unrelated gap) | No — dead field, not usable. |

**Indexes**: `SyncCheckpoint.Meta` declares **no explicit `indexes =
[...]`** (re-read this task, confirmed absent). The only index is the
implicit unique index Django creates for the `OneToOneField(session)`
column. This is irrelevant to detection performance (Section 9) because
the view already fetches this row by that same unique-indexed
`session` filter — no new lookup pattern is introduced.

**Conclusion**: `updated_at` is the correct, and only correct, existing
field for measuring "how long has this checkpoint been `RUNNING`."

---

## 6. Detection Design

**Proposed shape** (design only — not implemented):

```python
POSSIBLY_STUCK_THRESHOLD_SECONDS = ...  # see Section 7

def _is_possibly_stuck(checkpoint):
    if checkpoint is None or checkpoint.status != SyncCheckpoint.STATUS_RUNNING:
        return False
    age_seconds = (timezone.now() - checkpoint.updated_at).total_seconds()
    return age_seconds > POSSIBLY_STUCK_THRESHOLD_SECONDS
```

- **No new query**: `checkpoint` is already fetched by
  `SyncStatusView.get()` (`SyncCheckpoint.objects.filter(session=session).first()`,
  present since 9.1A, unchanged by 9.1B) — this is pure Python
  computation over an object already in memory.
- **No dependency on Celery/worker liveness** — confirmed independently
  in Section 4's trace: the signal is entirely a function of
  `status`/`updated_at`, both already-existing `SyncCheckpoint` columns.
  This matches, and is now more rigorously sourced than, this session's
  prior (unimplemented) roadmap-audit finding that revised an earlier
  report's "tightly coupled to worker liveness" claim.
- **`checkpoint is None`** (session never synced at all — `never_synced`
  in `_derive_sync_status()`) → `possibly_stuck: false`. There is no
  `RUNNING` state to be stuck in; `false`, not `null`, keeps the field's
  type a plain boolean in every case (Section 8 elaborates on why
  boolean, not nullable).
- **`status != RUNNING`** (`idle`/`ok`/`error`) → always `false`. A
  checkpoint that isn't currently claiming to be running cannot be
  "stuck running" — this also means a `failed` (`STATUS_ERROR`)
  checkpoint, however old, is never reported as `possibly_stuck`
  (it's already visible as `sync_status: 'failed'`, a stronger, already-
  confirmed signal — no need to layer an uncertain heuristic on top of
  a certain one).

---

## 7. Threshold Analysis

**Explicitly not arbitrary — grounded in three already-configured,
sourced values** (`backend/config/settings.py`, re-read this task):

```python
CELERY_TASK_TIME_LIMIT = 600        # hard kill after 10 minutes (line 192)
CELERY_TASK_SOFT_TIME_LIMIT = 540   # graceful-cleanup window starts at 9 minutes (line 193)
RECONCILIATION_INTERVAL_SECONDS = int(os.environ.get(..., '900'))  # periodic schedule, default 15 min (line 203)
```

Also relevant: `apps/sync/waha_client.py`'s `DEFAULT_TIMEOUT_SECONDS = 10`
per HTTP call to WAHA, and the targeted-retry helper's
`MAX_ATTEMPTS = 3` (`executors.py`) — bounding the **targeted, `'sync'`-executor**
path's realistic worst case at roughly `3 attempts × (up to 10 pages ×
10s WAHA timeout)` ≈ a few hundred seconds in the worst pathological
case (every single WAHA call timing out), though this is an **INFERRED**
upper bound (multiplying documented per-call/per-page ceilings), not an
enforced hard limit the way `CELERY_TASK_TIME_LIMIT` is for the Celery
path.

**Two candidate thresholds, with trade-offs** (per the task's own
instruction not to force a single number without justification):

### Option 1 — Derive from `settings.CELERY_TASK_TIME_LIMIT` (recommended)

```python
POSSIBLY_STUCK_THRESHOLD_SECONDS = settings.CELERY_TASK_TIME_LIMIT + SAFETY_MARGIN_SECONDS
# e.g. 600 + 60 = 660 seconds
```

- **Pros**: directly sourced from an actual *enforced* system limit —
  for the periodic (Celery) path, which is how a `RUNNING` checkpoint
  is expected to arise under normal operation, a run genuinely cannot
  legitimately still be executing past `CELERY_TASK_TIME_LIMIT` (+ a
  small margin for signal-delivery/scheduling jitter) without something
  having gone wrong. Reading it from `settings` (not hardcoding `600`)
  means it automatically tracks whatever an environment actually
  configures — the same reasoning `_derive_sync_status()`'s existing
  `STALE_THRESHOLD_MULTIPLIER` comment already gives for reading
  `RECONCILIATION_INTERVAL_SECONDS` live rather than hardcoding it.
- **Cons**: does not itself have the same hard-enforced backing for the
  **`'sync'`-executor targeted path** (Section 4's finding — no Celery
  time limit applies there at all). In practice this is a minor
  concern: that path's realistic worst case (a few hundred seconds,
  above) is comfortably under 660s in all but a pathological
  every-call-times-out scenario, but it is not a *guarantee* the way it
  is for the Celery path.

### Option 2 — `max(settings.CELERY_TASK_TIME_LIMIT, N × RECONCILIATION_INTERVAL_SECONDS)` for some small `N`

- **Pros**: also accounts for a deployment that has changed
  `RECONCILIATION_INTERVAL_SECONDS` to something unusually large,
  ensuring the threshold never sits below the actual scheduling cadence
  (would otherwise be a strange signal: "stuck" alongside a period
  shorter than the flag's own threshold).
- **Cons**: more complex than necessary for the *primary* purpose
  (detecting a wedged run) — `RECONCILIATION_INTERVAL_SECONDS` governs
  how *often* runs start, not how *long* one run should take; conflating
  the two (as `_derive_sync_status()`'s own `STALE_THRESHOLD_MULTIPLIER`
  already does, but for a *different* purpose — detecting "no run
  happened recently enough," not "a run is wedged") risks a threshold
  that moves for reasons unrelated to stuck-detection.

**Not recommended as a sole basis**: reusing `STALE_THRESHOLD_MULTIPLIER × RECONCILIATION_INTERVAL_SECONDS`
(1800s under today's defaults) alone — this measures a fundamentally
different thing (staleness of the *last completed* run) and, under a
deployment with a short custom interval (e.g. `RECONCILIATION_INTERVAL_SECONDS=300`),
could produce a threshold *below* `CELERY_TASK_TIME_LIMIT`, flagging a
run as "stuck" before Celery's own hard kill would even have fired —
a false positive against the system's own documented behavior.

**Edge case worth naming, not designing around**: because
`CELERY_TASK_TIME_LIMIT` (600s) is comfortably less than
`RECONCILIATION_INTERVAL_SECONDS`'s 900s default, a legitimate run
should never still be executing when the *next* periodic dispatch for
the same session fires, under default settings — but the codebase has
no explicit lock preventing two concurrent `reconcile_session()` calls
for the same session if an operator configures a shorter interval, or
if a targeted (`'sync'`/`'celery'`) trigger overlaps with a periodic
run. This is a **related but separate** gap (concurrency, not staleness
of the `RUNNING` flag itself) — named here for completeness, **not**
proposed to be addressed by this design.

**This audit's recommendation**: Option 1, as the primary, sourced,
low-complexity choice — with the explicit caveat about the `'sync'`-
executor path documented in the implementation (not hidden), rather
than adding Option 2's extra complexity to close a gap that is already
very unlikely in practice given `WahaClient`'s own 10s per-call timeout.
**The exact `SAFETY_MARGIN_SECONDS` value (e.g. 30s, 60s, 120s) is not
resolved by source evidence alone** and is flagged as a small,
non-blocking implementation-time judgment call (Section 13).

---

## 8. API Response Proposal

**Current response** (`GET /api/sync/status/<session_name>/`, re-read
this task, unchanged since the 9.1B implementation two tasks ago):

```json
{
  "session": "no_epahari",
  "sync_status": "running",
  "checkpoint_status": "running",
  "last_run_at": null,
  "seconds_since_last_run": null,
  "checkpoint_updated_at": "2026-09-25T10:00:00Z",
  "last_webhook_received_at": "2026-09-25T09:58:00Z"
}
```

**Proposed addition**:

```json
{
  "...": "...",
  "possibly_stuck": false
}
```

Design decisions, each checked against existing convention rather than
invented fresh:

- **Field name**: `possibly_stuck` — matches, verbatim, the name already
  proposed in `docs/generated/PHASE9-1-DESIGN-AUDIT-REPORT.md` Section 5
  ("Optionally sub-flagged `possibly_stuck: true`..."), the only prior
  naming precedent found for this exact concept. No reason found to
  deviate.
- **Boolean, not enum**: this endpoint already has one derived enum
  (`sync_status`) computed server-side specifically so the frontend
  "never re-implements the threshold logic" (9.1A's own design
  rationale, `apps/sync/views.py` module docstring). Adding a *second*,
  independent enum would force frontend code to reason about the
  cross-product of two enums. A plain boolean **sub-flag**, additive to
  the existing `sync_status: 'running'` value (never replacing it), is
  simpler, matches the original proposal's own framing ("sub-flagged"),
  and keeps `sync_status`'s existing five-value contract completely
  unchanged (`docs/CLAUDE.md` rule 8 — never silently change the API
  contract; this is additive, not a redefinition).
- **Null behavior**: **never `null`** — always a concrete `true`/`false`,
  even when `checkpoint` is `None` (`false`) or `status != RUNNING`
  (`false`). This differs deliberately from `last_run_at`/
  `checkpoint_updated_at`/`last_webhook_received_at` (which use `null`
  for "no data yet") because `possibly_stuck` is not itself a piece of
  data that can be *absent* — it is always a computable yes/no answer
  given the checkpoint's current state (including "no checkpoint" as a
  well-defined "no" case). A `null` here would force every frontend
  consumer to handle a third state for no real benefit.
- **Behavior when checkpoint does not exist**: `false` (Section 6) —
  consistent with `never_synced` already meaning "nothing to report,"
  not "something is wrong."
- **Behavior when status is not RUNNING**: `false` (Section 6).
- **Timestamp source**: `checkpoint.updated_at` only (Section 5) — never
  `last_run_at`.
- **Threshold**: Section 7's Option 1 (recommended), read from
  `settings.CELERY_TASK_TIME_LIMIT` at request time, not hardcoded —
  matching `_derive_sync_status()`'s own established discipline of
  reading the relevant setting live.
- **Timezone handling**: no new concern — `checkpoint.updated_at` is
  already a `USE_TZ=True`-aware, UTC `datetime` (project-wide
  convention, unchanged); the comparison is `timezone.now() -
  checkpoint.updated_at`, the exact same pattern `_seconds_since()`
  already uses in this same file for `seconds_since_last_run`. No new
  formatting is needed for a boolean field (no `_isoformat()` call
  applies here, unlike every other field in this response).
- **Backward compatibility**: purely additive — every existing field,
  name, type, and meaning stays exactly as-is. A client that doesn't
  read `possibly_stuck` is completely unaffected.

---

## 9. Query/Performance Analysis

**VERIFIED FROM SOURCE.**

- **No additional query required.** `checkpoint` is already loaded by
  the existing `SyncCheckpoint.objects.filter(session=session).first()`
  call (present since 9.1A). `possibly_stuck` is computed entirely in
  Python from two attributes already on that in-memory object
  (`status`, `updated_at`) — no `.filter()`, `.get()`, `.aggregate()`,
  or related-object access is introduced.
- **Query count unaffected**: the current, already-updated (by the
  9.1B task) test,
  `test_query_count_is_bounded_no_n_plus_one`, asserts **exactly 3**
  domain queries (`WahaSession` lookup, `SyncCheckpoint` lookup,
  `WebhookEvent` `Max()` aggregate for `last_webhook_received_at`).
  Adding `possibly_stuck` would **not** change this count — no new
  table is touched. **This is a stronger position than 9.1B's own
  change**, which did need a new query; this one needs none.
- **No N+1 risk**: the computation is O(1) per request, entirely
  attribute access and a `timedelta` comparison — not a loop over any
  collection.
- **Indexes**: irrelevant to this addition specifically (Section 5) —
  no new query pattern is introduced that could benefit or suffer from
  an index either way.

---

## 10. Test Impact

**VERIFIED FROM SOURCE** (current test file re-read this task,
post-9.1B):

- `backend/apps/sync/tests/test_views.py`'s
  `test_query_count_is_bounded_no_n_plus_one` would **not** need its
  assertion count changed (still 3) — but re-running it after
  implementation is still recommended (as a regression check, not
  because this design predicts a change).
- New tests recommended for the eventual implementation (not written in
  this audit):
  1. `RUNNING` checkpoint, `updated_at` recent (within threshold) →
     `possibly_stuck: false`.
  2. `RUNNING` checkpoint, `updated_at` older than threshold →
     `possibly_stuck: true`.
  3. `RUNNING` checkpoint, `updated_at` exactly at the threshold
     boundary → confirms the chosen `>`/`>=` semantic explicitly (this
     design proposes `>`, i.e. boundary-exclusive/not-yet-stuck at
     exactly the threshold, mirroring `_derive_sync_status()`'s own
     boundary-inclusive-for-healthy choice — `<=` means healthy there,
     so the "not yet a problem" side is consistently the inclusive one
     in both places).
  4. `OK`/`ERROR`/`IDLE` status, `updated_at` arbitrarily old →
     `possibly_stuck: false` in every case (proves the flag is gated on
     `status == RUNNING`, not merely on age).
  5. No `SyncCheckpoint` row at all (`never_synced`) →
     `possibly_stuck: false`.
  6. Query-count regression test re-run, confirming still exactly 3.
- **No frontend test impact** — no test framework exists in this
  project (re-confirmed unchanged, consistent with every prior audit
  this session); irrelevant regardless since Section 14 recommends a
  backend-only scope.

---

## 11. Security/Data-Integrity Considerations

**VERIFIED FROM SOURCE / reasoned from existing code:**

- **No writes**: the proposed computation is a pure read — no
  `.save()`, no `.update()`, no new query even. Strictly stronger than
  9.1B (which was also read-only but did add a query).
- **No secrets exposed**: a boolean carries no data of any kind beyond
  yes/no.
- **No Celery internals exposed**: by design (Section 6/9), the
  computation never inspects Celery task state, queue depth, or worker
  registry — it only ever reads `SyncCheckpoint` columns already present
  in this same response. There is nothing to leak because nothing
  Celery-specific is ever touched.
- **No infrastructure details exposed**: no broker URL, no worker
  hostname, no task ID — consistent with this endpoint's existing
  discipline (`last_error` already deliberately excluded, per 9.1A's
  own design report).
- **Cannot trigger reconciliation**: the proposed code path has no call
  into `reconcile_session`, `trigger_reconciliation`, `.delay()`, or any
  other mutation entry point — purely a `GET`-side read.
- **Does not change existing status semantics**: `sync_status`'s
  existing five-value contract (`never_synced/running/failed/healthy/stale`)
  is completely unmodified — `possibly_stuck` is a new, independent,
  **additive** field, not a sixth `sync_status` value and not a
  replacement for `running`.
- **Auth**: inherits `SyncStatusView`'s existing `JWTAuthentication` +
  `IsAuthenticated`-only gate — no new authorization surface, same as
  every other field on this response.

---

## 12. Recovery Boundary

**Recovery is explicitly NOT designed in this audit**, per the task's
own instruction. Named here only to state clearly why it must remain a
separate, later design:

- **Detection is reversible and consequence-free**: computing
  `possibly_stuck` wrong (e.g. threshold too aggressive) produces a
  misleading *display*, correctable by adjusting a constant — no data
  is at risk.
- **Recovery is not consequence-free**: automatically resetting
  `status` away from `RUNNING` (to `idle`, `error`, or anything else),
  or enqueueing a fresh reconciliation, or killing/retrying a task,
  risks acting on a checkpoint that is **not actually stuck** — e.g. a
  genuinely large backlog still legitimately processing past the
  threshold (the threshold in Section 7 is a *heuristic*, not a proof).
  Interfering with a real in-flight run could corrupt `checkpoint_value`
  bookkeeping or cause two concurrent runs for the same session (a
  scenario this codebase has no lock against — Section 7's edge-case
  note).
- **Recovery needs information this design deliberately avoids
  depending on**: distinguishing "genuinely still running" from "dead
  worker, stuck forever" reliably would need Celery worker/task-state
  visibility (e.g. `celery_app.control.ping()`, task result backend
  lookups) — a materially larger, infrastructure-coupled design this
  audit does not attempt, matching this session's own prior roadmap
  audit's conclusion that recovery and worker-liveness are the items
  genuinely coupled to each other, even though detection alone is not
  coupled to either.

**Any recovery work must go through its own, separate design audit**,
explicitly informed by an explicit user decision on recovery *policy*
(Section 13, item 2) — not assumed or sketched here.

---

## 13. User Decisions Required

Per the task's own escalation bar (architecture/semantics only):

1. **Whether possibly-stuck detection is desired at all.** Not yet
   explicitly confirmed as "build this" in this session's visible
   history — the immediately prior roadmap audit *recommended* it as
   the next task, but recommendation is not the same as approval. This
   audit surfaces the question rather than assuming the answer, exactly
   as 9.1B's own audit did for its own field.
2. **Whether automatic recovery is desired, ever, under any policy.**
   Explicitly **not** part of this task (Section 12) and, if pursued
   later, requires its **own separate design audit** — stated here only
   to make sure it is not silently bundled into whatever implements
   detection.
3. **The exact `SAFETY_MARGIN_SECONDS` added to `settings.CELERY_TASK_TIME_LIMIT`**
   (Section 7, Option 1) — source evidence supports the *base* value
   (600s, an enforced system limit) but not one specific margin; this
   is a minor, non-blocking implementation-time judgment call, not a
   hard blocker, flagged for visibility rather than escalated as
   architecturally material.

**Not escalated** (naming/formatting/implementation-preference, per the
task's own instruction not to treat these as blockers): the exact field
name (`possibly_stuck` already has a clear, singular precedent — Section
8), boundary operator choice (`>` vs `>=` — Section 10 already resolves
this by precedent-matching), whether to add a database index (none is
needed — Section 9).

---

## 14. Recommended Implementation Scope

**If/when the user decisions in Section 13 are resolved affirmatively**,
the minimal implementation would be:

- **`backend/apps/sync/views.py`** — the only file expected to need a
  production change: a small helper function (e.g. `_is_possibly_stuck()`,
  mirroring `_derive_sync_status()`'s existing style in the same file)
  and one new key in the existing `Response({...})` dict. No new
  import beyond what may already be present (`timezone` is already
  imported in this file).
- **`backend/apps/sync/tests/test_views.py`** — new test cases only
  (Section 10); the existing query-count test needs re-running, not
  editing.

**Not expected to change**: `backend/apps/sync/reconciliation.py`
(detection reads the checkpoint after the fact; it does not need to
instrument the write path at all), `backend/apps/sync/tasks.py`,
`backend/apps/sync/executors.py`, `backend/apps/sync/models.py` (no
new field — computed, not stored), any migration, any BFF file, any
frontend file (matching 9.1B's own "backend-only, field available but
not yet consumed" precedent — `InboxPage.tsx` already carries three
unused timestamp-shaped fields from this same endpoint today), any
Docker/Compose/`.env` file, any dependency.

---

## 15. Explicit Non-Goals

- **Recovery of any kind** (Section 12) — reset, retry, unlock, kill,
  re-enqueue. Not designed, not scoped, not implied by this report.
- **Celery worker liveness checking** — not required for detection
  (Section 6), and not designed here as a separate feature either;
  remains a distinct, unscoped, heavier future item (per the prior
  roadmap audit).
- **Concurrency locking** for overlapping reconciliation runs on the
  same session (Section 7's edge case) — named, not addressed.
- **A durable record of *how much* a stuck run had recovered before
  wedging** — the pre-existing, already-named "gap 5" from the original
  Phase 9.1 design audit, unrelated to and not solved by this design.
- **Any change to `sync_status`'s existing five-value contract** —
  `possibly_stuck` is strictly additive.
- **Any frontend display of this field** — left as a natural, separate
  future task, exactly like `last_run_at`/`checkpoint_updated_at`/
  `last_webhook_received_at` today.

---

## 16. Verification Status

**VERIFIED FROM SOURCE** (directly read/grepped this task):
- Full `reconcile_session()` control flow and both its callers.
- `SyncCheckpoint`/`TimeStampedModel` field definitions and absence of
  explicit indexes.
- `CELERY_TASK_TIME_LIMIT=600`, `CELERY_TASK_SOFT_TIME_LIMIT=540`,
  `RECONCILIATION_INTERVAL_SECONDS` (default 900), `WahaClient`'s
  `DEFAULT_TIMEOUT_SECONDS=10`, `executors.py`'s `MAX_ATTEMPTS=3`.
- Absence of `task_acks_late`/`task_reject_on_worker_lost` settings
  anywhere in `config/settings.py`.
- Absence of any `.revoke(` call anywhere in `backend/`.
- Current exact shape of `GET /api/sync/status/<session_name>/` and its
  test file, post-9.1B.
- No frontend file currently reads any timestamp field from this
  endpoint besides `sync_status` itself (`InboxPage.tsx`), and
  `DashboardPage.tsx` does not consume this endpoint at all.

**INFERRED** (reasoned from documented Celery/library behavior, not
independently exercised against a live broker/worker this task):
- Celery's default `task_acks_late=False` behavior when the setting is
  absent.
- `revoke(terminate=True)`'s effect of not running a task's remaining
  Python code.
- The targeted `'sync'`-executor path's empirical worst-case duration
  (multiplying documented per-call timeouts/attempt counts, not
  measured live).

**NOT VERIFIABLE WITHOUT RUNTIME DATA**:
- Whether `CELERY_TASK_TIME_LIMIT` is actually honored by the specific
  worker pool implementation/configuration in this project's real
  production or development deployment (this audit did not start the
  Office-side stack, consistent with the strict read-only scope; a live
  test would require actually killing a worker mid-task and observing
  the result).
- Real-world frequency of any of the crash scenarios in Section 4 in
  this project's actual production usage.
- Whether a production deployment has ever actually left a checkpoint
  stuck in `RUNNING` — no live database was queried for this audit.

---

**STOP.** This was a design audit only. No detection code, no recovery
code, and no other file was implemented or modified. Awaiting the
user's decisions in Section 13 before any implementation begins.
