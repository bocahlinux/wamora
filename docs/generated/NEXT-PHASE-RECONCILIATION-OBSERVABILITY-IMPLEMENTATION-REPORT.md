# Reconciliation Execution Observability — Implementation Report

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

**Conclusion: Complete.** `SyncCheckpoint` now carries two additive
fields — `last_run_trigger_source` and `last_run_task_id` — populated
at the start of every reconciliation run by all three trigger paths
this codebase actually has (periodic Celery, targeted
sync/Celery-executor, and the `manage.py reconcile` management
command). This is pure, read-only-consequence metadata: no automatic
recovery, no worker liveness, no heartbeat, no execution-history table,
no distributed lock, and no change to the reconciliation loop, retry
semantics, `checkpoint_value` behavior, or Phase 13.A's recovery
endpoint. 329/329 backend tests pass (318 pre-existing + 11 new),
`manage.py check` is clean, and `makemigrations --check` confirms the
model and migration are in sync. Implements exactly the recommendation
in `docs/generated/NEXT-PHASE-RECONCILIATION-OBSERVABILITY-DESIGN-AUDIT-REPORT.md`
Sections 8/13/14.

---

## 1. Objective

Make reconciliation execution provenance observable — which of the
three real trigger paths started a given `SyncCheckpoint`'s most recent
`RUNNING` state, and (for the two Celery-executed paths) the real
Celery task ID — with the smallest possible schema and code change, and
with zero change to recovery/detection semantics or the reconciliation
loop itself.

---

## 2. Initial State

Before this task: `SyncCheckpoint` had no notion of trigger provenance
or task identity at all — `possibly_stuck` (Section 6 of the earlier
detection audit) and Phase 13.A's manual recovery endpoint both operate
purely on `status`/`updated_at`. Every `.delay()` call's return value
was discarded at every call site (confirmed in both prior related
audits, re-confirmed this task before editing anything).

---

## 3. Trigger Sources Discovered (Step 1 — re-verified directly from source)

Re-traced this task, not assumed from the design audit report:

1. **Periodic** — Celery beat → `reconcile_all_sessions_task` →
   `reconcile_session_task.delay(session_name)` (`apps/sync/tasks.py`)
   — always Celery, regardless of `RECONCILIATION_EXECUTOR`.
2. **Targeted** — `apps.sync.executors.trigger_reconciliation()`, called
   from `apps/sync/internal_views.py`'s `ReconciliationTriggerView`
   (BFF-only, after a confirmed outbound send). Two sub-paths, both
   routed through the same `run_targeted_reconciliation_with_retry()`
   helper:
   - `RECONCILIATION_EXECUTOR='sync'`: in-process, no Celery task.
   - `RECONCILIATION_EXECUTOR='celery'`: `reconcile_chat_task.delay(...)`.
3. **Management command** — `python manage.py reconcile <session>`
   (`apps/sync/management/commands/reconcile.py`) — never Celery, runs
   in whatever foreground process invokes it.

No fourth path exists — re-confirmed via
`grep -rn "reconcile_session(\|reconcile_session_task\|reconcile_chat_task\|trigger_reconciliation("`
excluding tests, matching the design audit's own Section 2.1 exactly.
**No trigger-source vocabulary was invented beyond these three** — the
model's `TRIGGER_SOURCE_CHOICES` has exactly `periodic`/`targeted`/
`management_command`, nothing else. The two sub-paths within "targeted"
are distinguished by `last_run_task_id`'s presence/absence, not by a
fourth `trigger_source` value (per the design audit's own Section 8
reasoning — a targeted run is a targeted run regardless of which
executor ran it).

**No architectural change beyond the two fields was found necessary**
— Step 1's own STOP condition ("jika audit menemukan perubahan
arsitektur yang diperlukan di luar scope dua metadata field ini")
was not triggered.

---

## 4. Data Model Changes

`backend/apps/sync/models.py`, `SyncCheckpoint`:

```python
TRIGGER_PERIODIC = 'periodic'
TRIGGER_TARGETED = 'targeted'
TRIGGER_MANAGEMENT_COMMAND = 'management_command'
TRIGGER_SOURCE_CHOICES = [
    (TRIGGER_PERIODIC, 'Periodic'),
    (TRIGGER_TARGETED, 'Targeted'),
    (TRIGGER_MANAGEMENT_COMMAND, 'Management command'),
]

last_run_trigger_source = models.CharField(max_length=32, choices=TRIGGER_SOURCE_CHOICES, blank=True)
last_run_task_id = models.CharField(max_length=64, blank=True)
```

Type/nullable/default conventions matched to this **same model's own
existing fields**, not invented fresh: `checkpoint_value`/`last_error`
are both `CharField`/`TextField` with `blank=True` and no `null=True` —
empty string is this model's own established "no value yet" marker.
Both new fields follow that exact precedent (Step 1's own instruction:
verify existing checkpoint write semantics before designing). Neither
field is nullable at the database level; both default to `''` for
existing rows.

---

## 5. Migration

`backend/apps/sync/migrations/0002_synccheckpoint_last_run_task_id_and_more.py`
— generated by `manage.py makemigrations sync`, reviewed before
applying:

```python
operations = [
    migrations.AddField(model_name='synccheckpoint', name='last_run_task_id',
                         field=models.CharField(blank=True, max_length=64)),
    migrations.AddField(model_name='synccheckpoint', name='last_run_trigger_source',
                         field=models.CharField(blank=True, choices=[...], max_length=32)),
]
```

- **Reversible**: `AddField` operations are natively reversible by
  Django's migration framework (`RemoveField` on reverse) — no custom
  `RunPython` was written or needed.
- **No existing data touched**: both are pure `AddField` operations;
  Django's `CharField` (non-nullable, no explicit `default=`) resolves
  to its own empty-string default for the new column on every existing
  row automatically — **VERIFIED**: `makemigrations` completed
  non-interactively with no prompt for a one-off default value,
  confirming Django resolved this itself rather than requiring
  intervention.
- **Does not touch `status`/`checkpoint_value`/any other existing
  column** — confirmed by direct review of the generated migration file
  (two `AddField` operations only).
- **VERIFIED**: `manage.py makemigrations sync --check --dry-run` (run
  after all code changes) reports "No changes detected in app 'sync'"
  — the model and the migration are in sync, no second migration is
  pending.
- **VERIFIED**: the full test suite (Section 11) exercises Django's
  test-database creation, which runs every migration from `0001` through
  `0002` — both the fresh-migration path and (implicitly, since `0001`
  already existed) the existing-migration-path both succeed, every test
  run.

---

## 6. Integration Points

Exactly the files the design audit's own Section 14 predicted:

- **`backend/apps/sync/reconciliation.py`** —
  `reconcile_session()` gains two new, optional keyword parameters
  (`trigger_source=None, task_id=None`), used only at the existing
  write (A) — the checkpoint's `RUNNING`-transition save. **The
  per-chat/per-page loop body is untouched** — confirmed by direct diff
  review: the only lines changed are the signature, the docstring, and
  the `update_fields` list construction immediately before write (A).
  `None` (the default for both) means "don't touch this field" —
  every pre-existing caller/test that doesn't pass them is unaffected.
- **`backend/apps/sync/tasks.py`** — `reconcile_session_task` passes
  `trigger_source=SyncCheckpoint.TRIGGER_PERIODIC, task_id=self.request.id`;
  `reconcile_chat_task` passes `task_id=self.request.id` through to
  `run_targeted_reconciliation_with_retry()`.
- **`backend/apps/sync/executors.py`** —
  `run_targeted_reconciliation_with_retry()` gains a `task_id=''`
  parameter (default — correct for the `sync` executor, which has no
  Celery task) and always passes
  `trigger_source=SyncCheckpoint.TRIGGER_TARGETED` to
  `reconcile_session()`. `trigger_reconciliation()`'s own two branches
  are otherwise unchanged — the `sync` branch's call site was not
  modified (it relies on the helper's own default).
- **`backend/apps/sync/management/commands/reconcile.py`** — passes
  `trigger_source=SyncCheckpoint.TRIGGER_MANAGEMENT_COMMAND, task_id=''`.

---

## 7. Celery Task ID Handling

Per Step 4's explicit constraints, all satisfied:

- **Uses Celery's own provided request context** — `self.request.id`,
  inside `reconcile_session_task`/`reconcile_chat_task`, both already
  `bind=True` (unchanged, pre-existing) — **no UUID is generated by
  this codebase**.
- **Never uses the checkpoint's own timestamp or any fabricated value**
  as a task ID — confirmed by direct code review.
- **Never persists a task object** — only the string `self.request.id`
  is passed through; no `AsyncResult`, no Celery internals stored.
- **Available before `reconcile_session()` is called** — `self.request.id`
  is read directly in `tasks.py` before the call, matching the
  requirement exactly.
- **VERIFIED** (via `test_records_periodic_trigger_source_and_real_task_id`/
  `test_records_targeted_trigger_source_and_real_task_id`,
  `apps/sync/tests/test_tasks.py`): the value that ends up on
  `SyncCheckpoint.last_run_task_id` is a real, non-empty string
  produced by Celery's own task machinery (even under
  `CELERY_TASK_ALWAYS_EAGER=True`, Celery still assigns a genuine task
  ID to `self.request.id` — confirmed by the test asserting a truthy
  value, not a fixed/mocked one).

---

## 8. Management Command Handling

`apps/sync/management/commands/reconcile.py`'s `handle()` now passes
`trigger_source=SyncCheckpoint.TRIGGER_MANAGEMENT_COMMAND, task_id=''`
directly to `reconcile_session()` — **no Celery task was added to this
command** (it remains exactly what it was: a synchronous, foreground,
non-Celery call). **VERIFIED** by a new test file,
`apps/sync/tests/test_management_commands.py`
(`test_records_management_command_trigger_source_and_blank_task_id`).

---

## 9. HTTP/Synchronous Handling

The one real HTTP/synchronous path found (Step 6) is the
`RECONCILIATION_EXECUTOR='sync'` branch of
`trigger_reconciliation()` → `run_targeted_reconciliation_with_retry()`,
called in-process from `apps/sync/internal_views.py`'s
`ReconciliationTriggerView` (an internal, BFF-only endpoint, unchanged
by this task). It now records `trigger_source=TRIGGER_TARGETED,
last_run_task_id=''` via the helper's own default. **No endpoint
contract was changed** — `ReconciliationTriggerView`'s own request/
response shape is byte-identical (not modified at all this task); the
new metadata lands only on `SyncCheckpoint`, not in that endpoint's own
response. **No new endpoint was added.**

---

## 10. Existing Behavior Preserved

**VERIFIED**, each by a passing, unmodified-assertion test:

- `checkpoint_value`/`status`/`last_run_at`/`last_error` semantics —
  byte-identical; every pre-existing `ReconciliationCheckpointTests`
  test (`test_successful_run_advances_checkpoint_to_latest_timestamp`,
  `test_failed_fetch_does_not_advance_checkpoint`, etc.) passes
  unmodified.
- `Message`/`Chat`/`Contact` persistence — byte-identical; every
  idempotency test in `test_reconciliation.py` passes unmodified, plus
  a new explicit test
  (`test_trigger_metadata_does_not_affect_checkpoint_value_or_messages`)
  confirms the new parameters don't change message-count or
  checkpoint-value outcomes for the same fixture.
- **`possibly_stuck` detection** (`apps/sync/views.py`) — not touched
  by this task at all; still computed purely from `status`/`updated_at`,
  confirmed via `test_query_count_is_bounded_no_n_plus_one` and every
  `possibly_stuck`-specific test passing unmodified.
- **Phase 13.A's recovery endpoint** — not touched; its compare-and-set
  `.filter(pk=..., status=RUNNING, updated_at=...)` predicate does not
  reference either new field, so it is entirely unaffected. All 12
  `SyncCheckpointRecoveryViewTests` pass unmodified.
- **Retry/backoff semantics** — `max_retries`, `autoretry_for`,
  `retry_backoff`, `retry_backoff_max`, `retry_jitter` on both Celery
  tasks: byte-identical, not touched.
- **`GET /api/sync/status/` response contract** — unchanged; the new
  fields are **not** exposed by `SyncStatusView` (a deliberate choice,
  Section 16) — its response body is identical to before this task.

---

## 11. Tests

**VERIFIED** — targeted:
```
$ python manage.py test apps.sync --settings=config.settings_test -v 1
...
Ran 146 tests in 11.059s
OK
```
(135 pre-existing + 11 new: 5 in `test_reconciliation.py`, 2 in
`test_executors.py`, 2 in `test_tasks.py`, 2 in the new
`test_management_commands.py`.)

New tests, mapped to Step 8's requirements:

| Requirement | Test |
|---|---|
| A. Celery path — source/task ID correct | `test_records_periodic_trigger_source_and_real_task_id`, `test_records_targeted_trigger_source_and_real_task_id` |
| B. Management command — source/blank task ID | `test_records_management_command_trigger_source_and_blank_task_id` |
| C. HTTP/synchronous — source/blank task ID | `test_records_targeted_trigger_source_and_given_task_id`, `test_task_id_defaults_to_blank_for_the_sync_executor` |
| D. Metadata survives completion | `test_trigger_metadata_survives_to_a_failed_run_too` (present after `STATUS_ERROR`, not only `STATUS_OK`) |
| E. Existing behavior unchanged | `test_trigger_metadata_does_not_affect_checkpoint_value_or_messages` + every pre-existing checkpoint/idempotency test passing unmodified |
| F. Existing recovery/`possibly_stuck` unaffected | All 12 `SyncCheckpointRecoveryViewTests` + all `possibly_stuck` tests pass unmodified (none reference the new fields) |
| G. Existing endpoint response unchanged | `SyncStatusViewTests` (29 tests) pass unmodified — response shape untouched |
| H. Migration | `makemigrations --check --dry-run` (Section 5) + full test suite's own migrate-from-scratch on every run |
| I. Concurrency | **Not claimed beyond what the code guarantees** — see Section 17; no lock was added, no concurrency test was written beyond what already existed (matching the task's own explicit instruction not to silently design a lock) |

Four **pre-existing** tests needed their mock signatures widened
(`**kwargs`) because they hardcoded a fixed call arity that the new,
additive keyword arguments now exceed — this is normal test-double
maintenance for a backward-compatible signature change, not a
correctness fix:
`test_tasks.py::test_rerunning_task_does_not_duplicate_durable_records`,
`::test_task_actually_persists_via_real_reconcile_session`,
`::test_delegates_to_run_targeted_reconciliation_with_retry` (now
asserts `task_id=mock.ANY` plus a truthy-string check, since the real
value is a fresh UUID per run), `::test_actually_persists_via_the_real_shared_retry_helper`,
and `test_internal_views.py::test_end_to_end_with_a_stubbed_waha_client_actually_triggers_reconciliation`.
No test's *assertions about outcome* (message counts, status values)
were weakened — only the mocked callables' own signatures were widened
to accept the new, additive parameters.

**VERIFIED** — full backend suite:
```
$ python manage.py test --settings=config.settings_test
...
Ran 329 tests in 29.544s
OK
```
**329 tests** (318 pre-existing baseline + 11 new).

**VERIFIED** — `manage.py check`:
```
System check identified no issues (0 silenced).
```

---

## 12. Regression

No BFF, frontend, or Docker file was touched by this task (confirmed,
Section 19) — per the task's own instruction, none of those suites
were run merely for ceremony. Full backend regression (Section 11)
covers every app, not just `apps.sync`.

---

## 13. Live Verification

**NOT VERIFIED — DEVELOPMENT STACK UNAVAILABLE.** `docker ps` before
and after this task showed only `wamora-dev-tencent-bff-1`/
`wamora-dev-tencent-frontend-1` running — the Office-side stack
(Django/Celery/Redis) was not running and was not started for this
task. No live reconciliation was triggered, no WhatsApp/blast message
was sent, and no real WAHA/Celery/Redis state was touched or could be
touched. What was verified instead: the full DRF/Django/Celery-eager
test cycle (Section 11), including real `self.request.id` values from
Celery's own task machinery under `CELERY_TASK_ALWAYS_EAGER=True` —
the same rigor as every other test in this suite, explicitly not
claimed as equivalent to a live container round-trip.

---

## 14. Files Changed

- **`backend/apps/sync/models.py`** — two new fields + three new
  `TRIGGER_*` constants + `TRIGGER_SOURCE_CHOICES` on `SyncCheckpoint`.
- **`backend/apps/sync/migrations/0002_synccheckpoint_last_run_task_id_and_more.py`**
  (new file) — two `AddField` operations.
- **`backend/apps/sync/reconciliation.py`** — `reconcile_session()`
  gains two optional parameters, used only at write (A).
- **`backend/apps/sync/tasks.py`** — both `@shared_task` functions pass
  the new context (`SyncCheckpoint` now imported).
- **`backend/apps/sync/executors.py`** —
  `run_targeted_reconciliation_with_retry()` gains a `task_id=''`
  parameter; always passes `trigger_source=TRIGGER_TARGETED`
  (`SyncCheckpoint` now imported).
- **`backend/apps/sync/management/commands/reconcile.py`** — passes
  `trigger_source=TRIGGER_MANAGEMENT_COMMAND, task_id=''`
  (`SyncCheckpoint` now imported).
- **`backend/apps/sync/tests/test_reconciliation.py`** — 5 new tests.
- **`backend/apps/sync/tests/test_executors.py`** — 2 new tests
  (`SyncCheckpoint` now imported).
- **`backend/apps/sync/tests/test_tasks.py`** — 2 new tests + 4
  existing mock signatures widened.
- **`backend/apps/sync/tests/test_internal_views.py`** — 1 existing
  mock signature widened.
- **`backend/apps/sync/tests/test_management_commands.py`** (new file)
  — 2 tests.

---

## 15. Files Intentionally Not Changed

Per the task's explicit scope:
- **`backend/apps/sync/views.py`** (`SyncStatusView`,
  `SyncCheckpointRecoveryView`, `_is_possibly_stuck()`) — not touched;
  the new fields exist but are not exposed or consulted by either view
  (Section 16).
- **`backend/config/celery.py`, `backend/config/settings.py`** — no
  Celery configuration change.
- **`backend/apps/sync/internal_views.py`** — the internal trigger
  endpoint's own contract untouched; it calls `trigger_reconciliation()`,
  already listed as changed.
- **The per-chat/per-page loop body inside `reconcile_session()`**
  (lines processing WAHA history pages) — untouched; only the
  entry-point write (A) changed.
- Any Docker/Compose/`.env` file, any BFF or frontend file — no
  involvement.
- Any dependency file — no new package.
- **Phase 13.A's recovery logic and `possibly_stuck`'s detection
  logic/threshold** — both re-read, neither modified.

---

## 16. Security Considerations

- **No new unauthenticated surface** — no new endpoint was added
  (Step 6's explicit instruction); the two new fields are only ever
  written internally by `reconcile_session()`'s own trusted callers,
  never accepted as untrusted input from any request.
- **No secret stored** — a Celery task UUID and a fixed trigger-source
  enum string carry no credential material.
- **Deliberately not exposed via `SyncStatusView`** — a conscious
  choice (matching the design audit's own Section 14 framing that
  exposure is "a separate, later decision") — keeping this task's
  actual surface area to the database layer only, the smallest
  possible increment. Exposing the fields later, if wanted, is a
  small, separate, additive change to that view's `Response({...})`
  dict — not designed or implemented here.
- **No change to authentication/authorization anywhere** — `apps/authn`
  was not touched by this task.

---

## 17. Concurrency Limitations

**Explicitly not claimed to be solved.** Per the task's own Step 8.I
instruction, this task does not claim concurrency safety beyond what
the existing code actually guarantees, and no lock was silently
designed:

- The two new fields are written via the **same** plain
  `checkpoint.save(update_fields=[...])` call at write (A) that already
  existed — **no new race was introduced**, but **the pre-existing
  race** (two concurrent `reconcile_session()` calls for the same
  session, documented in both prior related audits) applies to these
  two fields exactly as it does to `status`/`updated_at`: whichever
  concurrent run's write (A) commits last determines which
  trigger_source/task_id the row shows, same as it always has for
  `status`.
- **No correctness issue caused by this specific change was found** —
  the STOP condition in Step 8.I was not triggered; this is a restatement
  of an already-documented, pre-existing limitation, not a new one this
  change introduces.
- Phase 13.A's own compare-and-set guard (Section 10) remains the only
  concurrency safeguard in this subsystem, unchanged and unaffected by
  this task.

---

## 18. Known Limitations

- **The new fields are not yet exposed via any API** (Section 16) — a
  human or automated consumer would need direct database access to read
  them today; this is the deliberate, minimal scope of this task.
- **Live verification was not possible** (Section 13) — the Office-side
  stack was not running.
- **Worker liveness, automatic recovery, task revocation, heartbeats,
  and an execution-history table remain entirely undesigned-further and
  unimplemented** — this task's data is a prerequisite ingredient for
  some of those (per the design audit's Section 9), not a step toward
  implementing any of them.
- **Concurrent-execution ambiguity for the new fields is inherited, not
  solved** (Section 17).

---

## 19. Git Status

```
$ git status --short backend/apps/sync/ backend/apps/authn/permissions.py
 M backend/apps/sync/executors.py
 M backend/apps/sync/management/commands/reconcile.py
 M backend/apps/sync/models.py
 M backend/apps/sync/reconciliation.py
 M backend/apps/sync/tasks.py
 M backend/apps/sync/tests/test_executors.py
 M backend/apps/sync/tests/test_internal_views.py
 M backend/apps/sync/tests/test_reconciliation.py
 M backend/apps/sync/tests/test_tasks.py
?? backend/apps/sync/api_urls.py                 (pre-existing, untracked from an earlier task)
?? backend/apps/sync/migrations/0002_synccheckpoint_last_run_task_id_and_more.py
?? backend/apps/sync/tests/test_management_commands.py
?? backend/apps/sync/tests/test_views.py         (pre-existing, untracked from an earlier task)
?? backend/apps/sync/views.py                    (pre-existing, untracked from an earlier task)
```

No file under `bff/`, `frontend/`, `infrastructure/`, `config/`
(outside what's listed), or any migration directory other than
`apps/sync/migrations/` was touched. No `.env` file, no secret, no
generated artifact outside the intended scope. `backend/apps/authn/permissions.py`
(shown as modified in the broader repo status) is **pre-existing,
untouched work from Phase 13.A**, not from this task.

---

## 20. Final Conclusion

Reconciliation execution provenance is now durably observable at the
database layer: every `SyncCheckpoint` row's most recent `RUNNING`
transition records which of the three real trigger paths started it,
and — for the two Celery-executed paths — the real, Celery-assigned
task ID, captured via `self.request.id` and never fabricated. This was
achieved with the smallest change the design audit identified as
necessary: two additive `SyncCheckpoint` fields, one small migration,
and parameter threading only at `reconcile_session()`'s existing
entry point — the reconciliation loop itself, retry semantics,
`checkpoint_value` logic, `possibly_stuck` detection, and Phase 13.A's
recovery endpoint are all byte-identical to before this task. 329/329
backend tests pass; `manage.py check` and `makemigrations --check` are
both clean. Live verification was not possible without the Office-side
stack running and is honestly disclosed as such, not fabricated.

**STOP.** Not proceeding to automatic recovery, Celery worker liveness,
task revoke, retry redesign, distributed locking, heartbeat, an
execution-history table, Dashboard changes, new API endpoints, or
Phase 9.1C/9.1F changes. Awaiting further instructions.
