# "Possibly Stuck" Reconciliation Detection — Implementation Report

**Conclusion: Complete.** `GET /api/sync/status/<session_name>/` now
returns a `possibly_stuck` boolean, computed entirely from the
already-loaded `SyncCheckpoint.status`/`updated_at`, with **zero
additional database queries**. Detection only — no recovery, no
Celery/worker inspection, no mutation of any kind. 306/306 backend
tests pass (298 pre-existing + 8 new), `manage.py check` is clean.
Implements exactly the design in
`docs/generated/NEXT-PHASE-POSSIBLY-STUCK-DETECTION-DESIGN-AUDIT-REPORT.md`.

---

## 1. Objective

Add a read-only `possibly_stuck` signal to the existing sync-status
endpoint, flagging a `SyncCheckpoint` that has remained `RUNNING` for
longer than a conservative, sourced threshold — without implementing
any form of recovery, reset, retry, or Celery/worker inspection.

---

## 2. Design Used

Followed `docs/generated/NEXT-PHASE-POSSIBLY-STUCK-DETECTION-DESIGN-AUDIT-REPORT.md`
exactly, with no contradiction discovered during implementation (the
design audit was not redone). Specifically:
- Section 6's detection function shape.
- Section 7's Option 1 threshold (`settings.CELERY_TASK_TIME_LIMIT` +
  a fixed safety margin), read live rather than cached at import time
  (see Section 4).
- Section 8's API contract (boolean, never `null`, additive,
  `false` for "no checkpoint" and "not RUNNING").
- Section 12's recovery boundary (nothing implemented beyond
  detection).

---

## 3. Detection Formula

`backend/apps/sync/views.py`:

```python
def _is_possibly_stuck(checkpoint):
    if checkpoint is None or checkpoint.status != SyncCheckpoint.STATUS_RUNNING:
        return False
    threshold_seconds = settings.CELERY_TASK_TIME_LIMIT + POSSIBLY_STUCK_SAFETY_MARGIN_SECONDS
    return _seconds_since(checkpoint.updated_at) > threshold_seconds
```

Uses `checkpoint.updated_at` only — never `checkpoint.last_run_at` (per
the design audit's Section 5 finding: `last_run_at` is only set on a
*completed* run and is stale/misleading while genuinely stuck).
Boundary is exclusive (`>`, not `>=`) — at exactly the threshold,
`possibly_stuck` is still `false`, mirroring `_derive_sync_status()`'s
own inclusive-for-the-healthy-side (`<=`) convention in the same file.

---

## 4. Threshold Rationale

```python
POSSIBLY_STUCK_SAFETY_MARGIN_SECONDS = 60  # module-level constant
```

Combined at call time with `settings.CELERY_TASK_TIME_LIMIT` (600s,
`config/settings.py`) → **660 seconds**, per the task's explicit
instruction. **Not hardcoded as a single `660` literal anywhere** —
`_is_possibly_stuck()` computes `settings.CELERY_TASK_TIME_LIMIT +
POSSIBLY_STUCK_SAFETY_MARGIN_SECONDS` live, inside the function, every
call — deliberately **not** cached as a module-level total. This
matters for correctness, not just style: `STALE_THRESHOLD_MULTIPLIER`/
`_derive_sync_status()` (same file) already reads
`settings.RECONCILIATION_INTERVAL_SECONDS` live for the identical
reason — a module-level constant computed once at Django import time
would silently stop responding to `@override_settings(CELERY_TASK_TIME_LIMIT=...)`
in tests (and to any real runtime settings change), which would have
made this feature harder to test deterministically and less honest
about tracking the actual configured value. Verified in practice: the
test suite (Section 9) uses `@override_settings(CELERY_TASK_TIME_LIMIT=600)`
at the test-class level and the live-read computation correctly
reflects it.

No new environment variable was introduced — `POSSIBLY_STUCK_SAFETY_MARGIN_SECONDS`
is a plain module-level Python constant (matching `STALE_THRESHOLD_MULTIPLIER`'s
own precedent, a fixed multiplier rather than an env-configurable one),
per the task's own instruction to prefer a constant unless the existing
architecture clearly requires an env var — it does not here, since the
margin is a code-level judgment call, not a per-environment deployment
setting the way `CELERY_TASK_TIME_LIMIT`/`RECONCILIATION_INTERVAL_SECONDS`
themselves are.

---

## 5. Files Changed

- **`backend/apps/sync/views.py`** — added
  `POSSIBLY_STUCK_SAFETY_MARGIN_SECONDS` constant, `_is_possibly_stuck()`
  function, and one new key (`'possibly_stuck': _is_possibly_stuck(checkpoint)`)
  in `SyncStatusView.get()`'s response dict. The only production file
  changed.
- **`backend/apps/sync/tests/test_views.py`** — added
  `TEST_CELERY_TASK_TIME_LIMIT`/`POSSIBLY_STUCK_THRESHOLD_SECONDS` test
  constants, `CELERY_TASK_TIME_LIMIT=TEST_CELERY_TASK_TIME_LIMIT` to the
  class-level `@override_settings`, and 8 new test methods (Section 9).

No other file was created, modified, or deleted.

---

## 6. Files Intentionally Unchanged

Per the task's explicit scope:
- `backend/apps/sync/reconciliation.py` — write path untouched; detection
  reads the checkpoint after the fact, no instrumentation added.
- `backend/apps/sync/tasks.py`, `executors.py` — Celery task/executor
  logic untouched.
- `backend/apps/sync/models.py` (`SyncCheckpoint`) — no new field; the
  value is computed, not stored.
- Any migration file — none created; no schema change.
- Any file under `bff/`, `frontend/`, `infrastructure/` — no
  involvement.
- `backend/config/celery.py` — Celery configuration untouched (only
  *read* via `settings.CELERY_TASK_TIME_LIMIT`, already exported through
  Django settings, not through this module).
- Any authentication/JWT file — `SyncStatusView`'s existing
  `JWTAuthentication`/`IsAuthenticated` gate is unmodified.
- Any dependency file — no new package.

---

## 7. API Response Change

**Before:**
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

**After:**
```json
{
  "session": "no_epahari",
  "sync_status": "running",
  "checkpoint_status": "running",
  "last_run_at": null,
  "seconds_since_last_run": null,
  "checkpoint_updated_at": "2026-09-25T10:00:00Z",
  "last_webhook_received_at": "2026-09-25T09:58:00Z",
  "possibly_stuck": false
}
```

Every previously-existing field, name, type, and meaning is unchanged
— **VERIFIED** by `test_possibly_stuck_does_not_alter_other_response_fields`,
which asserts the exact response-key set and spot-checks two
pre-existing field values on a checkpoint that also exercises the new
field. `possibly_stuck` is `true`/`false` in every case — never `null`
(no checkpoint → `false`; not-`RUNNING` → `false`; `RUNNING` and fresh →
`false`; `RUNNING` and stale → `true`).

---

## 8. Query-Count Impact

**VERIFIED** — `test_possibly_stuck_adds_no_additional_query` confirms
the endpoint still performs exactly the same **3** domain queries it
did immediately after the 9.1B task (`WahaSession` lookup,
`SyncCheckpoint` lookup, `WebhookEvent` `Max()` aggregate). The
pre-existing `test_query_count_is_bounded_no_n_plus_one` was **not**
modified — its assertion of `3` remains correct and unaffected, exactly
as the design audit predicted (Section 9 there): `possibly_stuck` reads
only attributes already present on the in-memory `checkpoint` object
fetched earlier in the same request; no `.filter()`, `.aggregate()`, or
related-object access was added.

---

## 9. Test Results

**VERIFIED** — targeted suite, using the project's local `venv`
(`backend/venv/Scripts/python.exe`) and `--settings=config.settings_test`:

```
$ python manage.py test apps.sync.tests.test_views --settings=config.settings_test -v 2
...
test_running_checkpoint_newer_than_threshold_is_not_possibly_stuck ... ok
test_running_checkpoint_exactly_at_threshold_is_not_yet_possibly_stuck ... ok
test_running_checkpoint_older_than_threshold_is_possibly_stuck ... ok
test_non_running_checkpoint_with_old_updated_at_is_not_possibly_stuck ... ok
test_error_checkpoint_is_not_possibly_stuck_regardless_of_age ... ok
test_no_checkpoint_is_not_possibly_stuck ... ok
test_possibly_stuck_does_not_alter_other_response_fields ... ok
test_possibly_stuck_adds_no_additional_query ... ok
...
----------------------------------------------------------------------
Ran 29 tests in 7.518s

OK
```

All 8 new tests pass (the 7 minimum cases the task specified, plus one
extra covering `STATUS_ERROR` specifically — `_derive_sync_status()`
groups `RUNNING`/`IDLE` together and `ERROR` separately, so both
non-`RUNNING` branches are exercised, not just one). Every pre-existing
`apps.sync` test still passes unmodified.

**VERIFIED** — full backend suite:

```
$ python manage.py test --settings=config.settings_test
...
----------------------------------------------------------------------
Ran 306 tests in 26.569s

OK
```

**306 tests** (298 pre-existing baseline + 8 new — reported as
observed, not assumed against the task's approximate "298" figure). No
regression anywhere else in the backend. The Redis-connection-error
tracebacks visible in the raw output belong to
`apps.core.tests.RedisHealthViewTests`'s own pre-existing mocked-failure
scenarios, unrelated to this task.

**VERIFIED** — `manage.py check`:
```
$ python manage.py check --settings=config.settings_test
System check identified no issues (0 silenced).
```

---

## 10. `manage.py check` Result

Clean — see Section 9 (`System check identified no issues (0 silenced).`).

---

## 11. Live Verification Result

**NOT VERIFIED — development stack unavailable.** `docker ps`
immediately before and after this task showed only
`wamora-dev-tencent-bff-1` and `wamora-dev-tencent-frontend-1` running
— the Office-side stack (`backend`/`celery-worker`/`celery-beat`/`redis`,
which would serve the actual `GET /api/sync/status/...` HTTP endpoint)
was **not running**, and this task did not start it, per the explicit
instruction not to restart/start the stack solely for this
implementation. No live HTTP round-trip against a running Django
instance was performed or is claimed.

What was verified instead (Section 9): the full DRF request/response
cycle through Django's real test client (`self.client.get(...)`),
including authentication and actual `Response({...})` serialization —
the same rigor as every other test in this suite, but explicitly not
equivalent to a live container round-trip.

---

## 12. Recovery Explicitly Excluded

Confirmed, by direct review of the diff (Section 5) and by design
(Section 2): this implementation contains **no** code that:
- resets `status` from `RUNNING` to any other value,
- retries, revokes, or otherwise touches a Celery task,
- calls `reconcile_session()`, `trigger_reconciliation()`, or any other
  mutation entry point,
- inspects Celery worker/queue state in any way,
- schedules any new periodic or one-off job.

`_is_possibly_stuck()` performs a single boolean comparison over
already-loaded, in-memory Python attributes and returns a value — it
has no side effects of any kind. Recovery remains a separate,
not-yet-designed, not-yet-approved future feature, exactly as the
design audit's Section 12 stated.

---

## 13. Known Limitations

- **No live HTTP verification was performed** (Section 11) — the
  Office-side stack was not running and was not started for this task.
- **No frontend consumes `possibly_stuck` yet** — by design (matching
  the design audit's Section 14/9.1B's own precedent); no frontend file
  was touched.
- **The `'sync'`-executor targeted-reconciliation path** (single-chat,
  in-request, no Celery time limit) is bounded by the same 660s
  threshold as the periodic Celery path, even though — per the design
  audit's Section 7 — that path has no *enforced* ceiling of its own
  (only an empirically-bounded realistic worst case well under 660s).
  This is an inherited, already-documented design trade-off, not a new
  gap introduced by this implementation.
- **`POSSIBLY_STUCK_SAFETY_MARGIN_SECONDS = 60`** is the value the task
  explicitly specified; no alternative margin was evaluated or
  benchmarked against real production timing data (none was available
  in this environment).

---

## 14. Final Conclusion

`possibly_stuck` is implemented exactly as designed: a pure, read-only,
additive boolean on the existing sync-status response, sourced solely
from `SyncCheckpoint.status`/`updated_at` (never `last_run_at`, never
Celery/Redis/WAHA state), computed with zero additional database
queries, and with the 660-second threshold read live from
`settings.CELERY_TASK_TIME_LIMIT` rather than hardcoded. 306/306
backend tests pass; `manage.py check` is clean. No recovery, retry,
reset, or Celery/worker-inspection logic was added anywhere. Live HTTP
verification was not possible without starting the currently-stopped
Office-side stack and was correctly not attempted, per instruction —
disclosed as NOT VERIFIED rather than assumed. `git status` confirms
only the two intended files changed; no migration, Docker, secret, or
unrelated file was touched.

**STOP.** Not proceeding to recovery, Celery worker liveness, Dashboard
sync-status UI, staging, production, Phase 9.1C/9.1F changes, or any
other feature. Awaiting further instructions.
