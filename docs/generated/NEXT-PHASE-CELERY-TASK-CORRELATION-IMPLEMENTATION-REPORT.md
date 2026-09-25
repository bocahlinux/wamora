# Celery Task Correlation — Diagnostic Implementation Report

**Conclusion: Complete.** `GET /api/sync/task-state/<session_name>/`
lets an authenticated operator with the `system administration` scope
ask what Celery's own `AsyncResult` currently reports for the Celery
task ID recorded in `SyncCheckpoint.last_run_task_id`. This is a
**diagnostic-only, read-only** capability: no recovery, no revoke, no
retry, no replacement-task enqueue, no automatic invocation of Phase
13.A, no change to `reconcile_session()`, `possibly_stuck`, or any
existing field's semantics, no migration, no new dependency. 345/345
backend tests pass (329 pre-existing + 16 new), `manage.py check` is
clean, `makemigrations --check` confirms no schema change occurred.
Implements exactly the recommendation in
`docs/generated/NEXT-PHASE-CELERY-TASK-CORRELATION-DESIGN-AUDIT-REPORT.md`
Section 10.

---

## 1. Objective

Provide a human-readable diagnostic answer to "for a checkpoint marked
`possibly_stuck`, what does Celery currently say about the task ID
recorded in `last_run_task_id`" — without performing, triggering, or
enabling any automatic recovery action.

---

## 2. Existing Architecture

Re-confirmed directly this task, matching the design audit's own
Section 2 (re-read, not assumed):

- `SyncCheckpoint.last_run_task_id` already exists (added in the
  immediately preceding task) — a plain `CharField`, empty string for
  the two non-Celery trigger paths (`targeted`'s `sync` sub-case,
  `management_command`), a real Celery task UUID for the two
  Celery-executed paths (`periodic`, `targeted`'s `celery` sub-case).
- `CELERY_RESULT_BACKEND` is already configured (`redis://redis:6379/0`)
  but was, before this task, **never read by any application code** —
  confirmed by the design audit's own repository-wide grep (zero hits
  for `AsyncResult`/`inspect(` outside Celery's own library).
- `_is_possibly_stuck()` and `SyncStatusView` are unchanged and were
  **re-read, not modified** — neither references the new view or
  either of the two `last_run_*` fields.
- Phase 13.A's `SyncCheckpointRecoveryView` is unchanged and was
  **re-read, not modified** — it does not call this new view, and this
  new view does not call it.

---

## 3. Design Decision

**A separate endpoint, not an extension of `SyncStatusView`'s
response** — decided before writing any code, per the task's own
instruction to justify this architecturally:

- `SyncStatusView`'s own docstring states it "never touches WAHA,
  Redis, or Celery" — this is a **guarantee**, not an implementation
  detail: it means every existing consumer of that endpoint (this
  session's own `InboxPage.tsx` polling, unaffected by this task) can
  rely on its latency/failure profile never depending on Celery/Redis
  reachability. Folding Celery correlation into that response would
  silently break that guarantee for every existing caller, not just
  add a field.
- The design audit's own instruction was explicit: "Do NOT make the
  task state part of the existing `possibly_stuck` boolean. Do NOT
  change the semantics of existing fields." A separate endpoint is the
  only way to add this capability without touching
  `SyncStatusView`'s response shape at all — confirmed unchanged,
  Section 10.
- `possibly_stuck` (a pure, always-available, Celery-independent
  heuristic) and Celery task-state correlation (an external,
  sometimes-unavailable lookup) are two genuinely different kinds of
  signal with different failure modes — keeping them in different
  responses keeps that distinction visible at the API level, not just
  in code comments.

---

## 4. API Shape

**`GET /api/sync/task-state/<session_name>/`** — no request body,
mirrors the existing `status/<session_name>/`/`recover/<session_name>/`
URL convention exactly (`apps/sync/api_urls.py`).

| Condition | Status | Body |
|---|---|---|
| No/invalid JWT | `401` | DRF default |
| Authenticated, missing `system administration` scope | `403` | DRF default |
| Unknown `session_name` | `404` | Standard error envelope |
| No checkpoint, or `last_run_task_id` is blank | `200` | `{"session", "last_run_task_id": "", "task_state": null, "reason": "no_task_id", "note": "..."}` |
| Celery/Redis unreachable | `200` | `{"session", "last_run_task_id", "task_state": null, "reason": "unavailable", "note": "..."}` |
| Celery reports a known state | `200` | `{"session", "last_run_task_id", "task_state": "<PENDING\|STARTED\|SUCCESS\|FAILURE\|RETRY\|REVOKED\|...>", "reason": null, "note": "<PENDING-ambiguity note, or null>"}` |

**"Unavailable" is deliberately a `200`, not a `503`** — a considered
choice, not an oversight: this endpoint's job is to attempt a
correlation and report the outcome truthfully; "Celery could not be
reached" is a legitimate, expected **result** of that attempt (the
endpoint itself did not fail), the same way `SyncStatusView` reports
`sync_status: 'stale'` as an ordinary `200` rather than an error.
`RedisHealthView`'s own `503` is not directly comparable — that view's
entire purpose is "is Redis healthy," so unreachability *is* its
failure signal; this view's purpose is "what does Celery say," and
"nothing, it's unreachable" is a valid, informative answer.

---

## 5. Authorization

`authentication_classes = [JWTAuthentication]`,
`permission_classes = [IsAuthenticated, HasSystemAdministrationScope]`
— reused verbatim from Phase 13.A's `SyncCheckpointRecoveryView`, **no
new JWT scope was introduced**. Chosen over `SyncStatusView`'s plain
`IsAuthenticated`-only gate because a Celery task ID is internal
system/worker detail, one step more sensitive than the checkpoint
status `SyncStatusView` already exposes to any authenticated user —
matching the task's own instruction to reuse
`HasSystemAdministrationScope` "if appropriate," judged appropriate
here for the same reason it was judged appropriate for Phase 13.A's
own administrative action.

**VERIFIED** by `test_unauthenticated_request_is_rejected` (`401`) and
`test_authenticated_without_system_administration_scope_is_rejected`
(`403`).

---

## 6. Celery Correlation Mechanism

```python
def _query_task_state(task_id):
    try:
        return AsyncResult(task_id, app=celery_app).state
    except Exception:
        logger.exception('Celery task-state correlation failed')
        return None
```

- **Uses Celery's existing `AsyncResult` API** against the
  already-configured `CELERY_RESULT_BACKEND` — no `inspect().query_task()`
  (which would require live, connected workers and its own timeout
  policy) was used, per the task's own "prefer the smallest
  implementation" instruction; `AsyncResult` reads the result backend
  directly and needs no worker to be currently online to answer.
- **No task-state model was invented** — the raw Celery-reported
  string (`state`) is relayed as-is; `RETRY` (a real Celery state not
  explicitly named in the task's own minimum list) is preserved
  verbatim rather than collapsed into a smaller enum, per the task's
  own "you may preserve it, but do not create unnecessary
  abstractions" instruction.
- **Isolated into its own function specifically to be mockable at the
  correct project boundary** — every test in Section 12 mocks either
  `apps.sync.views._query_task_state` (for the "known state" cases) or
  `apps.sync.views.AsyncResult` directly (for the "real exception
  handling actually works" case) — no live Celery worker or Redis
  connection is required for any test.
- **No task ID field was added or duplicated** — `SyncCheckpoint.last_run_task_id`
  is read as-is; no new column, no new model.

---

## 7. Task-State Semantics

The view relays Celery's own reported `state` string unmodified for
every known value (`PENDING`, `STARTED`, `SUCCESS`, `FAILURE`,
`RETRY`, `REVOKED`, and any other value Celery might report — none
are special-cased away). **VERIFIED** by six dedicated tests, one per
state named in the task's own minimum list plus `RETRY`
(`test_started_state`, `test_success_state`, `test_failure_state`,
`test_revoked_state`, `test_retry_state_is_preserved_verbatim_not_collapsed`,
and `test_pending_state_includes_the_ambiguity_note`).

---

## 8. Unknown/Unavailable Semantics

**The single most important correctness property of this
implementation, made explicit rather than glossed over**: Celery's
`AsyncResult.state` returns `'PENDING'` for **both** a genuinely
queued-but-not-yet-started task **and** a task ID it has never seen at
all — **INFERRED FROM SOURCE** (documented Celery/`kombu` result-backend
behavior; this project's own `CELERY_TASK_TRACK_STARTED=True` setting
does not change this default-state behavior for an unknown ID; not
independently live-tested against a real Redis result backend this
task, consistent with every prior related audit's own disclosed
limitation).

This implementation does **not** attempt to distinguish these two
cases (doing so reliably is not possible via `AsyncResult` alone,
confirmed by the design audit's own Section 8/9 analysis of Celery's
API surface) — instead, it **honestly surfaces the ambiguity**: every
`PENDING` response includes a `note` explaining exactly this,
verbatim, rather than silently presenting `PENDING` as if it
unambiguously meant "queued." **VERIFIED** by
`test_pending_state_includes_the_ambiguity_note` and
`test_unknown_stale_task_id_is_not_falsely_reported_as_success_or_failure`
(the latter additionally asserting the response never claims
`SUCCESS`/`FAILURE`/`REVOKED` for this ambiguous case).

**"Task state unavailable" (Celery/Redis unreachable) is a distinct,
separately-flagged outcome** (`reason: 'unavailable'`), never
conflated with `PENDING` or with `reason: 'no_task_id'` — **VERIFIED**
by `test_celery_unavailable_is_distinguished_from_unknown_state`
(asserts `reason == 'unavailable'` and explicitly
`reason != 'no_task_id'`) and
`test_real_connection_error_is_caught_and_reported_as_unavailable`
(exercises the real `try/except` in `_query_task_state`, not a mocked
version of that function itself).

---

## 9. Concurrency Limitation

**Documented explicitly, per the task's own mandatory instruction, not
merely implied**: this view's docstring states verbatim —

> "THIS RESULT IS NOT OWNERSHIP PROOF. The design audit traced
> precisely why: `last_run_task_id` identifies whichever task most
> recently STARTED a run on this checkpoint, not necessarily the task
> that produced its current status, under the concurrent-execution
> race that audit's Section 6 proved possible today. This view reports
> Celery's own last-known state for that recorded ID, honestly and
> only that — it is supporting evidence for a human decision (e.g. via
> Phase 13.A), never an automated trigger for one."

Nothing in the implementation (response fields, status codes, or
tests) describes the correlation result as authoritative, as proof of
exclusive ownership, or as a basis for automated action — consistent
with Section 17's mandatory requirement.

---

## 10. Files Changed

- **`backend/apps/sync/views.py`** — added `logging`/`AsyncResult`/
  `celery_app` imports, three module-level note constants
  (`PENDING_AMBIGUITY_NOTE`, `NO_TASK_ID_NOTE`, `UNAVAILABLE_NOTE`),
  `_query_task_state()`, and `SyncCheckpointTaskStateView`.
  `SyncStatusView`, `_is_possibly_stuck()`, and
  `SyncCheckpointRecoveryView` are byte-identical to before this task.
- **`backend/apps/sync/api_urls.py`** — one new `path(...)` entry and
  the corresponding import; the two existing routes are unchanged.
- **`backend/apps/sync/tests/test_views.py`** — one new test class,
  `SyncCheckpointTaskStateViewTests` (16 tests). Every pre-existing
  test class in this file is unchanged.

No other file was created, modified, or deleted.

---

## 11. Files Intentionally Not Changed

Per the task's explicit scope:
- **`backend/apps/sync/reconciliation.py`, `tasks.py`, `executors.py`,
  `management/commands/reconcile.py`** — reconciliation/Celery task
  logic untouched; `last_run_task_id` is only *read*, never written
  differently.
- **`backend/apps/sync/models.py`** — no new field; no migration
  (confirmed, Section 13).
- **`SyncStatusView`, `_is_possibly_stuck()`,
  `SyncCheckpointRecoveryView`** — all re-read, none modified; no
  automatic invocation of the recovery endpoint was added anywhere.
- **`backend/config/celery.py`, `backend/config/settings.py`** — no
  Celery configuration change; the existing `celery_app` object is
  only imported and read from.
- Any file under `bff/`, `frontend/`, `infrastructure/` — no
  involvement.
- Any dependency file — no new package (`celery.result.AsyncResult` is
  part of the already-installed `celery==5.4.0`).
- Any migration file — none created.

---

## 12. Tests

**VERIFIED** — targeted:
```
$ python manage.py test apps.sync.tests.test_views --settings=config.settings_test -v 1
...
Ran 57 tests in 14.516s
OK
```
(41 pre-existing + 16 new, all in `SyncCheckpointTaskStateViewTests`.)

Mapped to the task's own 12-item minimum:

| # | Requirement | Test |
|---|---|---|
| 1 | `last_run_task_id` missing/empty | `test_no_checkpoint_reports_no_task_id`, `test_blank_task_id_reports_no_task_id` |
| 2 | PENDING | `test_pending_state_includes_the_ambiguity_note` |
| 3 | STARTED | `test_started_state` |
| 4 | SUCCESS | `test_success_state` |
| 5 | FAILURE | `test_failure_state` |
| 6 | REVOKED | `test_revoked_state` |
| 7 | unknown/stale task ID | `test_unknown_stale_task_id_is_not_falsely_reported_as_success_or_failure` |
| 8 | Celery/Redis unavailable | `test_celery_unavailable_is_distinguished_from_unknown_state`, `test_real_connection_error_is_caught_and_reported_as_unavailable` |
| 9 | credentials/hostname not leaked | `test_no_secret_or_connection_detail_is_leaked_on_unavailability` |
| 10 | authorization behavior | `test_unauthenticated_request_is_rejected`, `test_authenticated_without_system_administration_scope_is_rejected` |
| 11 | existing sync-status behavior unchanged | All 29 pre-existing `SyncStatusViewTests` pass unmodified (Section 12.1 of full-suite run) |
| 12 | `possibly_stuck` behavior unchanged | Same — none of those tests were touched; `_is_possibly_stuck()` was not modified |

Plus `test_never_writes_anything` — asserts the checkpoint's
`status`/`updated_at`/`last_run_task_id` and the `AuditLog` table are
all completely unaffected by a full request cycle, directly proving
the "diagnostic only" claim rather than merely asserting it in prose.

**VERIFIED** — `test_no_secret_or_connection_detail_is_leaked_on_unavailability`
specifically injects a `ConnectionError` whose message contains a
realistic-looking Redis credential/hostname string
(`redis://:supersecretpassword@internal-redis-host:6379/0`) and
asserts neither substring appears anywhere in the JSON response body —
confirming `_query_task_state()`'s `logger.exception(...)` +
`return None` pattern (mirroring `RedisHealthView`'s own established
discipline) actually holds, not merely assumed from the code's shape.

**VERIFIED** — full `apps.sync` suite:
```
$ python manage.py test apps.sync --settings=config.settings_test
Ran 162 tests in 15.189s
OK
```

**VERIFIED** — full backend suite:
```
$ python manage.py test --settings=config.settings_test
Ran 345 tests in 33.285s
OK
```
**345 tests** (329 pre-existing baseline + 16 new).

**VERIFIED** — `manage.py check`:
```
System check identified no issues (0 silenced).
```

**VERIFIED** — `manage.py makemigrations --check --dry-run`:
```
No changes detected
```
Confirms no model change occurred — `last_run_task_id` was reused
exactly as it already existed, per the task's explicit instruction not
to introduce a second task-ID field or an unnecessary migration.

---

## 13. Regression Results

No BFF, frontend, or Docker file was touched (Section 11) — per the
task's own instruction, none of those suites were run merely for
ceremony. Full backend regression (Section 12) covers every app, not
just `apps.sync`. `SyncStatusView`'s and `SyncCheckpointRecoveryView`'s
own full test classes pass entirely unmodified, directly proving
requirements 11/12 of the task's own test list.

---

## 14. Live Verification

**NOT VERIFIED — LIVE CELERY CORRELATION UNAVAILABLE.** `docker ps`
before and after this task showed only
`wamora-dev-tencent-bff-1`/`wamora-dev-tencent-frontend-1` running —
the Office-side stack (Django/Celery/Redis) was not running and was
not started for this task, per the explicit instruction not to
start/restart it solely for this task. No live HTTP call was made
against a running Django instance, and no real Celery task ID was
ever correlated against a real Redis result backend. What was verified
instead: the full DRF request/response cycle through Django's real
test client (Section 12), including authentication, permission
checks, and `_query_task_state()`'s real exception-handling path
(exercised with a real `ConnectionError`, not merely a mocked return
value) — the same rigor as every other test in this suite, explicitly
not claimed as equivalent to a live Redis/Celery round-trip.

---

## 15. Security/Secret Verification

- **No new unauthenticated surface** — `401`/`403` enforced identically
  to Phase 13.A's own endpoint (Section 5).
- **No secret exposed in the success path** — the response contains
  only a session name, a Celery task ID (not a credential), a state
  string, and a static explanatory note.
- **No secret exposed in the failure path** — `_query_task_state()`
  never re-raises and never includes exception text in its return
  value; the view's own `UNAVAILABLE_NOTE` is a fixed, static string,
  never interpolated with any part of the caught exception. **VERIFIED**
  directly (Section 12, `test_no_secret_or_connection_detail_is_leaked_on_unavailability`),
  not merely asserted from the code's shape.
- **No SQL injection surface** — the only database query
  (`SyncCheckpoint.objects.filter(session=session).first()`) is
  unchanged from `SyncStatusView`'s own, already-parameterized ORM
  usage.
- **No CSRF concern beyond DRF's existing defaults** — JWT-bearer-token
  authenticated, same posture as every other endpoint in this
  codebase.

---

## 16. Known Limitations

- **The PENDING/unknown-ID ambiguity is inherent to Celery's own API**
  (Section 8) — not a defect in this implementation, but a real,
  disclosed limitation of what `AsyncResult` alone can ever tell an
  operator. Resolving it fully would require `inspect().query_task()`
  against live, connected workers (a heavier option this task
  deliberately did not build, per "prefer the smallest
  implementation") or a persisted execution-record table (the design
  audit's own Option D) — neither implemented here.
- **No live verification was possible** (Section 14).
- **Does not correlate anything for the two non-Celery trigger paths**
  (`targeted`'s `sync` sub-case, `management_command`) — `reason:
  'no_task_id'` is the honest, correct answer for those, not a gap in
  this specific implementation.
- **Does not resolve the concurrency ownership-ambiguity** (Section 9)
  — by design, not an oversight; resolving it is explicitly out of
  scope for this diagnostic-only task.

---

## 17. Why This Does NOT Enable Automatic Recovery

Stated explicitly, per the task's own requirement:

- This view performs **zero writes** of any kind — confirmed by
  `test_never_writes_anything` and by direct code review (no `.save()`,
  no `.update()`, no `AuditLog.objects.create()` anywhere in
  `SyncCheckpointTaskStateView`).
- It does not call, link to, or automatically invoke Phase 13.A's
  recovery endpoint — a human would need to separately decide to call
  that endpoint after reading this one's output.
- Its own result is explicitly documented (Section 9) as non-authoritative
  — even if a future task wanted to build automation on top of it, this
  implementation itself makes no claim that would make such automation
  safe, and the design audit's own Section 8 analysis (revoking a task
  whose correlation to the "actual" stuck execution cannot be proven)
  remains entirely unaddressed by anything in this task.
- The well-known `PENDING`-for-unknown-ID ambiguity (Section 8) means
  even a *well-intentioned* automatic policy reading this endpoint's
  output could not reliably distinguish "nothing to worry about, just
  queued" from "this ID doesn't even exist anymore" — a decisive
  reason, independent of the ownership question, that this data is not
  yet fit for unattended decision-making.

---

## 18. Final Conclusion

A diagnostic-only, human-facing Celery task-state correlation endpoint
is implemented exactly as designed: it reuses `last_run_task_id`
without any schema change, uses Celery's own already-configured result
backend without any new dependency, and honestly surfaces both of the
two fundamental ambiguities this audit lineage identified — the
PENDING/unknown-ID confusion inherent to Celery's own API, and the
non-authoritative nature of task-ID correlation under concurrent
execution — rather than glossing over either. 345/345 backend tests
pass; `manage.py check` and `makemigrations --check` are both clean.
No recovery, revoke, retry, replacement-task enqueue, lock, heartbeat,
execution-record table, or migration was added. Live verification was
not possible without the Office-side stack running and is honestly
disclosed as such.

**STOP.** Not proceeding to automatic recovery, Celery revoke/retry,
replacement-task enqueue, worker liveness, distributed locking, an
execution-record table, heartbeat, Dashboard changes, Phase G/H,
staging, or production. Awaiting further instructions.
