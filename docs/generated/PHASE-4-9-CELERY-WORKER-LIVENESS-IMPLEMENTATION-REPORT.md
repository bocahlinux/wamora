# Phase 4/9 Follow-Up — Celery Worker Liveness / Reconciliation Recovery — Implementation Report

**Naming note**: continuation of roadmap **Phase 4 (Reconciliation)** and
**Phase 9 (Offline/degraded mode)**, per
`docs/generated/PHASE-ROADMAP-STATUS-AUDIT-REPORT.md` and
`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` item 13 — explicitly NOT the
canonical roadmap's Phase 13. Matches the design audit's own filename
convention (`PHASE-4-9-CELERY-WORKER-LIVENESS-DESIGN-AUDIT-REPORT.md`).

## 1. Objective — the FAIL being closed

From `docs/generated/PHASE-4-9-CELERY-WORKER-LIVENESS-DESIGN-AUDIT-REPORT.md`,
Section 1.1/1.5 row D and Section 2, risk 1:

> `reconcile_session()` still has no `try/finally` around its
> RUNNING→terminal transition. An exception that is not `WahaClientError`
> ... propagates out of the function entirely, skipping the final
> `checkpoint.save(...)` at the bottom — the checkpoint is left `RUNNING`
> forever ... after retries are exhausted ... the checkpoint is stuck with
> no automatic resolution.

The audit's recommended minimal scope (Section 3/4): wrap
`reconcile_session()`'s RUNNING→terminal transition so **any** exception —
not only `WahaClientError` — reaches `STATUS_ERROR`, without adding a
worker-liveness ping, event monitoring, distributed locking, or automatic
recovery.

## 2. Step 1 findings

Read in full before implementing: `backend/apps/sync/reconciliation.py`,
`backend/apps/sync/executors.py`, `backend/apps/sync/tasks.py`,
`backend/apps/sync/models.py`, `backend/apps/sync/tests/test_reconciliation.py`,
`backend/apps/sync/tests/test_tasks.py`.

- `reconcile_session()` writes `STATUS_RUNNING` once, at the very start
  (write (A), pre-fix line 198). The only exception type it already
  catches is `WahaClientError`, per-chat, inside the `for chat in chats:`
  loop — that path already correctly reaches the terminal write at the
  bottom of the function (`result.had_error` → `STATUS_ERROR`) and was
  confirmed unaffected by this fix (regression tests below). Anything
  else raised inside that loop (e.g. a `persist_message` bug, an
  unexpected DB error) previously propagated straight out of the
  function, skipping the terminal write entirely.
- **The retry-exhaustion mechanics (the crux of this task).**
  `reconcile_session_task`/`reconcile_chat_task`
  (`backend/apps/sync/tasks.py`) both declare
  `bind=True, max_retries=3, autoretry_for=(Exception,), retry_backoff=True`.
  Celery's `autoretry_for` wraps the **entire task function**: on any
  matching exception it calls `self.retry(exc=exc)`, which re-schedules
  the whole task to run again from scratch after a backoff delay — this
  re-enters `reconcile_session()` from the top on the next attempt,
  immediately re-writing `STATUS_RUNNING` via write (A) regardless of
  what the previous attempt's checkpoint state was. `self.retry()`
  itself raises `MaxRetriesExceededError` instead of scheduling a real
  retry once `self.request.retries >= self.max_retries` — that is the
  one, precise moment "no more retries will happen" becomes true.
  `self.request.retries` is 0 on the original attempt and increments by
  one on each subsequent retry invocation, so
  **`self.request.retries >= self.max_retries` computed inside the task
  (where `self`/`self.request` are available — `reconcile_session()`
  itself has no access to this) is the correct, exact test for "this is
  the final attempt."** Verified directly against Celery's `Task.retry()`
  semantics, not inferred from the design audit's report (which flagged
  the question but explicitly left the mechanics for this task to
  verify).
- `run_targeted_reconciliation_with_retry`
  (`backend/apps/sync/executors.py`) has its own, unrelated internal
  retry loop (`MAX_ATTEMPTS=3`, retrying only when `messages_inserted==0`,
  never on exception) — a raised exception propagates out of that loop
  immediately, with no exception handling of its own. For the `sync`
  executor (`trigger_reconciliation` → `EXECUTOR_SYNC`) and the
  `manage.py reconcile` management command, no Celery retry wraps the
  call at all — a raised exception there is unconditionally the final
  attempt.
- `SyncCheckpoint` (`backend/apps/sync/models.py`) already has
  `STATUS_ERROR` and `last_error` (`TextField`) — no schema change
  needed. `SAFE_FAILURE_MESSAGE` in `backend/apps/blast/tasks.py:55`
  (`'This message could not be delivered.'`) is the existing
  sanitization precedent — a single, generic, operator-safe string,
  never the raw exception text.

## 3. Fix implemented

**`backend/apps/sync/reconciliation.py`**

- New module constant `SAFE_UNEXPECTED_ERROR_MESSAGE` (line 63) —
  `'Reconciliation failed due to an unexpected error.'`, mirroring
  `apps.blast.tasks.SAFE_FAILURE_MESSAGE`'s precedent exactly.
- `reconcile_session()` (`def` at line 165) gains a new keyword parameter
  `is_final_attempt=True`.
- The existing `for chat in chats:` loop is now wrapped in an outer
  `try: ... except Exception:` (lines ~271–332). Anything reaching that
  `except` is, by construction, neither `WahaClientError` (still caught
  per-chat, inline, unchanged) nor `MessageParsingError` (still caught
  per-message, unchanged). On catch:
  - If `is_final_attempt` is `True`: writes `checkpoint.status =
    STATUS_ERROR`, `checkpoint.last_error = SAFE_UNEXPECTED_ERROR_MESSAGE`,
    `checkpoint.last_run_at = timezone.now()` (`checkpoint_value` is
    deliberately left untouched — same "only advances on a fully
    successful run" guarantee the pre-existing `had_error` branch already
    honors).
  - If `is_final_attempt` is `False`: no checkpoint write at all — the
    checkpoint is left exactly as write (A) already set it (`RUNNING`),
    since the next retry attempt will overwrite it again within moments
    regardless.
  - Either way, the original exception is **re-raised unchanged** — this
    fix only adds a checkpoint write, it never swallows or replaces the
    exception Celery/the caller needs to see.
- Docstring extended to document `is_final_attempt`'s contract and the
  retry-exhaustion reasoning in full.

**`backend/apps/sync/tasks.py`**

- `reconcile_session_task` now passes
  `is_final_attempt=self.request.retries >= self.max_retries` into
  `reconcile_session(...)`.
- `reconcile_chat_task` now passes the same expression into
  `run_targeted_reconciliation_with_retry(...)`.

**`backend/apps/sync/executors.py`**

- `run_targeted_reconciliation_with_retry(...)` gains an
  `is_final_attempt=True` parameter (default preserves today's behavior
  for the `sync` executor and any direct caller), threaded straight
  through to every `reconcile_session(...)` call in its internal retry
  loop.

No change to `apps/sync/models.py` (no migration), `apps/sync/views.py`,
Celery delivery-semantics settings, or any file outside `apps/sync/`.

## 4. Tests added

`backend/apps/sync/tests/test_reconciliation.py` (`ReconciliationCheckpointTests`):

- `test_unhandled_exception_on_final_attempt_marks_checkpoint_error_with_safe_message`
  — mocks `persist_message` to raise `KeyError('raw internal detail...')`;
  asserts the exception still propagates (`assertRaises`), the checkpoint
  reaches `STATUS_ERROR` with `last_error` exactly equal to the safe
  constant, the raw exception text is absent from `last_error`,
  `checkpoint_value` is untouched, and `last_run_at` is recorded.
- `test_unhandled_exception_with_retries_remaining_does_not_prematurely_mark_error`
  — same trigger with `is_final_attempt=False`; asserts the checkpoint
  stays `RUNNING` with `last_error` still empty (the subtle "don't fire
  too early" case).
- `test_waha_client_error_path_is_unaffected_by_is_final_attempt` — proves
  the pre-existing `WahaClientError` handling reaches `STATUS_ERROR`
  regardless of `is_final_attempt`, since it never reaches the new outer
  `except`.

`backend/apps/sync/tests/test_tasks.py`:

- `ReconcileSessionTaskTests.test_first_attempt_is_not_final`,
  `test_intermediate_retry_attempt_is_not_marked_final`,
  `test_final_retry_attempt_is_marked_final` — the last two use Celery's
  own `task.push_request(retries=...)`/`pop_request()` to directly control
  `self.request.retries` and call `.run()` synchronously (bypassing eager
  mode's `Retry`-raising simulation, which the pre-existing
  `test_task_failure_is_observable_not_silently_swallowed` test already
  documents as not representative of true re-invocation), proving the
  `retries >= max_retries` computation itself is correct at both
  boundaries.
- `ReconcileChatTaskTests.test_intermediate_retry_attempt_is_not_marked_final`,
  `test_final_retry_attempt_is_marked_final` — same technique for the
  second Celery entry point.
- Updated `test_delegates_to_run_targeted_reconciliation_with_retry`'s
  strict `assert_called_once_with(...)` to include the new
  `is_final_attempt=False` kwarg (first attempt, retries=0 < max_retries=3)
  — the only pre-existing test whose exact-kwargs assertion needed
  updating for the new parameter.

## 5. Verification results

1. Targeted `apps.sync` suite:
   `docker exec -e DJANGO_SETTINGS_MODULE=config.settings_test development-backend-1 python manage.py test apps.sync`
   → **171/171 OK** (up from a pre-existing baseline of 163; +8 new tests).
2. Full backend suite:
   `docker exec -e DJANGO_SETTINGS_MODULE=config.settings_test development-backend-1 python manage.py test`
   → **447/447 OK** (baseline reported as 439/439 after Phase 12; +8 new
   tests, zero regressions, zero failures/errors elsewhere).
3. `python manage.py check` → `System check identified no issues (0
   silenced).`
4. `python manage.py makemigrations --check --dry-run` → `No changes
   detected`, exit code 0 — confirmed pure code fix, no schema change.
5. `git diff --stat` — only
   `backend/apps/sync/{reconciliation.py,tasks.py,executors.py}` and
   `backend/apps/sync/tests/{test_reconciliation.py,test_tasks.py}`
   changed. No changes to `apps/blast/`, `apps/operations/`, `frontend/`,
   `bff/`, any Docker/Compose file, or any dependency manifest.
6. No real WhatsApp/WAHA call was made — every test uses `StubWahaClient`
   or mocks; verification used the existing PostgreSQL-backed dev
   container only for `manage.py check`/tests (via
   `config.settings_test`, an in-memory SQLite test database, since the
   configured `waha` DB user has no `CREATEDB` privilege on the real
   PostgreSQL instance — no PostgreSQL Docker service was created or
   modified, per the project's hard rules).

**Note on test infrastructure**: the pre-existing `development-backend-1`
container (already running against the real, existing PostgreSQL
instance per project rules) was reused as-is — no new container, image,
or service was created. Running `manage.py test` against the real
Postgres connection failed with `permission denied to create database`
(the `waha` DB user correctly has no `CREATEDB` grant); tests were
instead run with `DJANGO_SETTINGS_MODULE=config.settings_test`, an
existing, pre-provisioned, test-only settings module
(`backend/config/settings_test.py`) built exactly for this situation
("no PostgreSQL instance is reachable [for test-database creation]") —
no new settings file was created, no production database file was
touched.

## 6. Git diff summary

```
backend/apps/sync/executors.py                 |  15 ++-
backend/apps/sync/reconciliation.py            | 148 +++++++++++++++++++------
backend/apps/sync/tasks.py                     |  11 +-
backend/apps/sync/tests/test_reconciliation.py |  61 +++++++++-
backend/apps/sync/tests/test_tasks.py          |  70 +++++++++++-
5 files changed, 264 insertions(+), 41 deletions(-)
```

## 7. Verdict

**CLOSED.** `reconcile_session()`'s RUNNING→terminal transition is now
guaranteed: on success, unchanged; on `WahaClientError`, unchanged
(re-verified via regression test); on any other exception, the checkpoint
reaches `STATUS_ERROR` with a safe, non-leaking `last_error` exactly once
Celery's own retries are genuinely exhausted (`self.request.retries >=
self.max_retries`, computed at the task level and passed down as
`is_final_attempt`) — never prematurely, mid a legitimate retry-backoff
sequence that may yet succeed. The `sync` executor and the management
command, which have no Celery retry wrapping them at all, correctly treat
every failure as final via the same parameter's `True` default.

## 8. Explicitly out of scope, confirmed untouched

- **Worker-liveness ping API** (`celery.control.ping()`/`inspect()`) — not
  added; not needed for this fix, `possibly_stuck` remains purely
  age-based.
- **Event monitoring / Flower** — not added.
- **Distributed locking / concurrency guard** for overlapping
  reconciliation runs (Section 1.3 of the design audit) — explicitly
  deferred per the finalized user decision; no locking mechanism of any
  kind was added. The pre-existing plain read-then-write of
  `checkpoint.status = RUNNING` is unchanged.
- **Automatic recovery/resume** — not added. `SyncCheckpointRecoveryView`
  (`backend/apps/sync/views.py`) remains the only recovery path; this fix
  changes only whether a checkpoint correctly *reaches* `STATUS_ERROR` on
  its own, never what happens after — the manual recovery endpoint, the
  `possibly_stuck` badge, and the diagnostics UI needed no changes and
  received none.
- `apps/blast/`, `OutboundOperation`, `CELERY_TASK_ACKS_LATE`/
  `CELERY_TASK_REJECT_ON_WORKER_LOST`, frontend, BFF, Docker/Compose,
  dependency manifests — all confirmed untouched by `git diff --stat`
  (Section 6 above).
