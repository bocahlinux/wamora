# Phase 13.A — Manual Reconciliation Recovery — Implementation Report

**Conclusion: Complete.** `POST /api/sync/recover/<session_name>/` lets
an authenticated operator with the `system administration` JWT scope
manually mark a genuinely `possibly_stuck` `SyncCheckpoint` as `ERROR`,
guarded by a compare-and-set conditional update so a concurrent state
change is detected and rejected rather than overwritten. No automatic
recovery, no Celery revoke/enqueue/inspection, no distributed lock, no
migration, no new dependency. 318/318 backend tests pass (306
pre-existing + 12 new), `manage.py check` is clean. Implements exactly
13.A from
`docs/generated/NEXT-PHASE-RECONCILIATION-RECOVERY-DESIGN-AUDIT-REPORT.md`.

---

## 1. Objective

Add a **manual, human-triggered** mechanism for an operator to mark a
checkpoint that `possibly_stuck` has flagged as `ERROR`, closing the
lost-update race the design audit identified (Section 8 there) via a
compare-and-set write — without implementing automatic recovery, task
revocation, replacement-task enqueueing, worker inspection, or
distributed locking, all of which remain explicitly out of scope.

---

## 2. Initial State

Before this task: `possibly_stuck` (Phase "possibly stuck detection",
two tasks ago) was read-only — nothing in the codebase could act on it.
No admin/operator UI or endpoint existed for `SyncCheckpoint` at all
(re-confirmed by the design audit, Section 2). `apps/authn/permissions.py`
contained only `HasReadingScope`. `'system administration'`
(`settings.JWT_SCOPES`) was defined but checked by zero endpoints
anywhere in the codebase.

---

## 3. Design Audit Findings Applied

From `docs/generated/NEXT-PHASE-RECONCILIATION-RECOVERY-DESIGN-AUDIT-REPORT.md`,
applied without contradiction (the design audit was not redone):

- **Section 10, candidate A** (`RUNNING → ERROR`) — the least-risky
  candidate; implemented exactly, nothing else (no B/C/D/E/F/G).
- **Section 12** — the compare-and-set safeguard is the one safeguard
  this audit called "the single most important, immediately available"
  — implemented as the write's actual mechanism, not an optional
  extra.
- **Section 13.A** — the no-schema-change framing: `possibly_stuck`
  stays purely computed; recovery is just a new *caller* reaching the
  existing `RUNNING`/`ERROR` values, no new `SyncCheckpoint` field, no
  new `status` enum value.
- **Section 15** — reuse `apps.audit.AuditLog` verbatim, no schema
  change to it either.
- **Section 17** — the exact recommended shape: re-confirm
  `possibly_stuck` at request time, compare-and-set write, `AuditLog`
  entry, a response distinguishing "recovered" from "already changed."

---

## 4. Existing Patterns Reused

Audited before writing any code (per the task's own instruction), and
matched rather than reinvented:

- **View placement**: `apps/sync/views.py` (same file as
  `SyncStatusView`/`_is_possibly_stuck`), not a new file — this app
  already has exactly one views module for its one existing
  frontend-facing endpoint.
- **URL placement**: `apps/sync/api_urls.py` (same file, same prefix
  `api/sync/`), not a new URL module.
- **Auth pattern**: `authentication_classes = [JWTAuthentication]`,
  matching every other human-facing Django endpoint in this codebase.
- **Scope-permission pattern**: a new `HasSystemAdministrationScope`
  class in `apps/authn/permissions.py`, **structurally identical** to
  the existing `HasReadingScope` (same file, same shape — reads
  `request.auth['scopes']`) — the established "one small `BasePermission`
  subclass per scope" convention, applied to a scope
  (`'system administration'`) that was already defined in
  `settings.JWT_SCOPES`/`docs/06-SECURITY.md` but never wired to any
  endpoint. This is the first use of that scope, not a new pattern.
- **404 convention**: `get_object_or_404(WahaSession, name=session_name)`
  — identical to `SyncStatusView`'s own unknown-session handling.
- **"Known session, no checkpoint" convention**: treated as a rejection
  (`409`), not a `404` — matching `SyncStatusView`'s own
  `never_synced` framing (a *known* session's absent checkpoint is not
  the same kind of "not found" as an unknown session name).
- **Manual error-envelope pattern**: `{"error": {"code", "message",
  "request_id"}}`, built directly via `Response(...)`, mirroring
  `apps/webhooks/views.py`'s `WahaWebhookView` (the existing precedent
  for a view that needs a custom rejection response outside DRF's
  automatic exception handler).
- **AuditLog writer pattern**: `AuditLog.objects.create(actor=...,
  action=..., target=..., result=...)`, the same four-field call shape
  every existing writer uses (`apps/operations/views.py`,
  `apps/audit/views.py`) — no schema change, no new field.
- **`target` convention**: a compact, human-readable string identifying
  the session — the same field `apps/dashboard/views.py`'s
  `ActivityFeedView` already populates with `event.session.name` for
  webhook-type activity items.

---

## 5. Recovery Semantics

`backend/apps/sync/views.py`, `SyncCheckpointRecoveryView.post()`:

1. `get_object_or_404(WahaSession, name=session_name)` — 404 for an
   unknown session.
2. `checkpoint = SyncCheckpoint.objects.filter(session=session).first()`
   — the same plain lookup `SyncStatusView` uses.
3. **`checkpoint is None`** → `409 no_checkpoint`. No database write.
4. **`checkpoint.status != RUNNING`** → `409 not_running`. No database
   write — explicitly covers both `ERROR` (already failed/"recovered")
   and `OK`/`IDLE`.
5. **`not _is_possibly_stuck(checkpoint)`** → `409 not_stale`. This is
   the **exact same function** `SyncStatusView`'s `possibly_stuck` field
   calls — imported and reused verbatim, not reimplemented, per the
   task's explicit instruction not to introduce a second threshold.
   Reached this step only when `status == RUNNING`, so this branch is
   specifically "running, but not yet old enough."
6. Otherwise: the compare-and-set write (Section 6).

**Never touched**: `checkpoint_value` (excluded by name from the
`.update()` call), `last_run_at` (recovery is not a completed run, so
it must not claim one happened), any `Message`/`Chat`/`Contact` row (no
model imports for any of them anywhere in this view), any Celery task,
any WAHA endpoint.

---

## 6. CAS/Concurrency Protection

```python
updated_count = SyncCheckpoint.objects.filter(
    pk=checkpoint.pk,
    status=SyncCheckpoint.STATUS_RUNNING,
    updated_at=checkpoint.updated_at,
).update(
    status=SyncCheckpoint.STATUS_ERROR,
    last_error='Marked as failed by manual recovery (possibly_stuck) — Phase 13.A.',
    updated_at=timezone.now(),
)

if updated_count == 0:
    return Response({...'code': 'concurrent_state_change'...}, status=409)
```

- **No blind `checkpoint.save()`** anywhere in this view — confirmed by
  direct review of the diff; the only write is the conditional
  `QuerySet.update()` above.
- The `WHERE` clause matches on `pk` **and** `status='running'` **and**
  `updated_at=<the exact value just read>` — if any of the three has
  changed (the original task finished, a prior recovery attempt already
  acted, or — in principle — some other write occurred), `updated_count`
  is `0` and the view rejects the request rather than overwriting
  whatever the row now holds.
- **A found-and-handled Django subtlety, worth stating explicitly**:
  `QuerySet.update()` does **not** trigger `auto_now` (that only fires
  on `.save()`) — `updated_at` is therefore set **explicitly** in the
  `.update()` call itself, or the row's `updated_at` would have stayed
  frozen at the value used in the CAS predicate, which would be
  functionally harmless but misleading (a checkpoint whose `updated_at`
  doesn't reflect when it was actually last touched).
- **Zero rows updated is treated as a normal rejection, not an error**:
  no `AuditLog` entry is written, no `500`, a clear `409
  concurrent_state_change` response.

**VERIFIED** by `test_concurrent_state_change_is_rejected_without_overwriting`
— simulates the race by making the view's own initial read return a
snapshot whose `updated_at` deliberately does not match the real row
(as if another process changed it between the read and the write),
using `unittest.mock` (already used elsewhere in this test suite, e.g.
`RedisHealthViewTests`) rather than real thread concurrency, which
Django's synchronous test client cannot exercise deterministically. The
test confirms: `409`, the real row's `status`/`updated_at` are
**unchanged**, and **zero** `AuditLog` entries are created.

---

## 7. Authorization

- `authentication_classes = [JWTAuthentication]`,
  `permission_classes = [IsAuthenticated, HasSystemAdministrationScope]`.
- **No public/unauthenticated path exists** — an unauthenticated
  request gets `401` (`test_unauthenticated_request_is_rejected`,
  VERIFIED, and confirms zero database writes).
- **An authenticated user *without* the `system administration` scope
  gets `403`**, not `200` (`test_authenticated_without_system_administration_scope_is_rejected`,
  VERIFIED) — the checkpoint is confirmed untouched afterward.
- **No bypass of any kind was added** specifically for this endpoint —
  `HasSystemAdministrationScope` is a generic, reusable permission
  class (any future administrative endpoint can reuse it), not a
  special case hardcoded into this one view.
- Scope granting in tests mirrors the exact existing convention
  (`apps/chats/test_views.py`): `Group.objects.get_or_create(name='system administration')`
  + `user.groups.add(group)`, relying on the unmodified
  `apps.authn.jwt_utils.compute_scopes()`.

---

## 8. AuditLog Behavior

Audited before writing (`apps/audit/models.py`): `AuditLog` has exactly
five fields (`actor`, `action`, `target`, `result`, `created_at`) and
**deliberately no metadata/JSON field**, per its own docstring ("Add
one later only if a concrete, documented need for it arises") — **not
changed by this task**, per the explicit instruction not to modify the
`AuditLog` schema.

Write, on success only:
```python
AuditLog.objects.create(
    actor=request.user,
    action='sync.checkpoint.recovery',
    target=f'{session.name} (running->error)',
    result=AuditLog.RESULT_SUCCESS,
)
```

- **`actor`**: the real authenticated `request.user` — not a
  serializer-supplied `actor_id` the way the BFF-mediated internal
  endpoints do (`OutboundOperationResolveView`), because this endpoint
  *is* the human-facing surface and already has the real user from
  JWT auth.
- **`action`**: `'sync.checkpoint.recovery'` — a new, dot-separated
  action name in the same style as the project's existing convention
  (e.g. `'session.start'`), specific enough to be unambiguous, no
  existing action name was reused or overloaded.
- **`target`**: encodes the session name **and** the previous→resulting
  transition (`'primary (running->error)'`) within the one available
  string field — the only place this information could go without a
  schema change, per Section 8's own constraint.
- **No secret is stored** — no token, no key, no raw WAHA/Celery
  internals; only a session name and a status-transition description.
- **Exactly one entry per successful recovery** — VERIFIED by
  `test_successful_recovery_creates_exactly_one_audit_log`.
- **Zero entries for every rejection path** (`no_checkpoint`,
  `not_running`, `not_stale`, `concurrent_state_change`, `403`) —
  VERIFIED across the corresponding tests (Section 12).

---

## 9. Files Changed

- **`backend/apps/authn/permissions.py`** (+15 lines) — added
  `HasSystemAdministrationScope`.
- **`backend/apps/sync/views.py`** — added `AuditLog`/
  `HasSystemAdministrationScope` imports and the
  `SyncCheckpointRecoveryView` class. `_is_possibly_stuck()`,
  `SyncStatusView`, and every other existing symbol in this file are
  byte-identical to before.
- **`backend/apps/sync/api_urls.py`** — added one `path(...)` entry and
  the corresponding import; `SyncStatusView`'s own route is unchanged.
- **`backend/apps/sync/tests/test_views.py`** — added `Group`,
  `AuditLog`, `mock` imports and a new `SyncCheckpointRecoveryViewTests`
  class (12 tests). `SyncStatusViewTests` is unchanged.

No other file was created, modified, or deleted.

---

## 10. Files Intentionally Not Changed

Per the task's explicit scope:
- `backend/apps/sync/reconciliation.py`, `tasks.py`, `executors.py` —
  reconciliation/Celery task logic untouched.
- `backend/apps/sync/models.py` (`SyncCheckpoint`) — no new field;
  `checkpoint_value` is explicitly never written by this view.
- `backend/apps/audit/models.py` — `AuditLog` schema untouched.
- `backend/apps/chats/models.py` — `Message`/`Chat`/`Contact` never
  imported or referenced by the new view.
- Any migration file — none created (confirmed via `git status` on both
  apps' `migrations/` directories).
- `backend/config/celery.py` — untouched; no revoke, no enqueue.
- Any file under `bff/`, `frontend/`, `infrastructure/` — no
  involvement; no UI was built (Section 14).
- Any dependency file — no new package (`unittest.mock` is part of the
  Python standard library, already used elsewhere in this test suite).

---

## 11. API Contract

**`POST /api/sync/recover/<session_name>/`** — no request body.

| Condition | Status | Body |
|---|---|---|
| No/invalid JWT | `401` | DRF default |
| Authenticated, missing `system administration` scope | `403` | DRF default |
| Unknown `session_name` | `404` | Standard error envelope |
| Known session, no `SyncCheckpoint` row | `409` | `{"error": {"code": "no_checkpoint", ...}}` |
| Checkpoint exists, `status != RUNNING` | `409` | `{"error": {"code": "not_running", ...}}` |
| Checkpoint `RUNNING`, not yet `possibly_stuck` | `409` | `{"error": {"code": "not_stale", ...}}` |
| Checkpoint changed between read and write (CAS lost) | `409` | `{"error": {"code": "concurrent_state_change", ...}}` |
| Success | `200` | `{"session": ..., "previous_status": "running", "status": "error", "recovered": true}` |

Every error body follows the same `{"error": {"code", "message",
"request_id"}}` shape this project already uses everywhere (manual
construction for the `409` cases, matching `WahaWebhookView`'s
precedent; DRF's automatic `api_exception_handler` for `401`/`403`/`404`).

---

## 12. Test Matrix

All 12 tests in the new `SyncCheckpointRecoveryViewTests` class,
**VERIFIED** passing:

| # | Test | Proves |
|---|---|---|
| 1 | `test_unauthenticated_request_is_rejected` | `401`, zero checkpoints created as a side effect |
| 2 | `test_authenticated_without_system_administration_scope_is_rejected` | `403`, checkpoint untouched |
| 3 | `test_unknown_session_returns_404` | `404` |
| 4 | `test_no_checkpoint_is_rejected` | `409 no_checkpoint`, zero `AuditLog` |
| 5 | `test_fresh_running_checkpoint_is_rejected` | `409 not_stale`, checkpoint untouched, zero `AuditLog` |
| 6 | `test_error_checkpoint_is_rejected` | `409 not_running`, `updated_at` untouched (no unnecessary write), zero `AuditLog` |
| 7 | `test_ok_checkpoint_is_rejected` | `409 not_running` for the non-`ERROR`, non-`RUNNING` case too |
| 8 | `test_stale_running_checkpoint_is_recovered` | `200`, `RUNNING → ERROR` |
| 9 | `test_recovery_does_not_change_checkpoint_value` | `checkpoint_value` byte-identical before/after |
| 10 | `test_recovery_never_touches_message_chat_contact` | succeeds with zero `Message`/`Chat`/`Contact` rows in existence |
| 11 | `test_successful_recovery_creates_exactly_one_audit_log` | exactly one `AuditLog`, correct `actor`/`action`/`target`/`result` |
| 12 | `test_concurrent_state_change_is_rejected_without_overwriting` | CAS race rejection (Section 6) |

This satisfies every item in the task's own 10-item minimum list
(stale→success, fresh→reject, `ERROR`→reject, no-checkpoint→reject,
concurrent-change→reject-with-0-rows, success→`AuditLog`,
failed-CAS→no-success-`AuditLog`, `checkpoint_value` unchanged,
authentication required, authorization required) — items 4/9/10 above
directly map to the prompt's items 6/7/10, items 1/2 map to items 9/10,
etc.

---

## 13. Regression Results

**VERIFIED**:
```
$ python manage.py test apps.sync.tests.test_views --settings=config.settings_test -v 2
...
Ran 41 tests in 10.537s
OK
```
(29 pre-existing `SyncStatusViewTests` + 12 new
`SyncCheckpointRecoveryViewTests`, all passing — `SyncStatusView`'s own
tests are byte-identical and unaffected.)

```
$ python manage.py test --settings=config.settings_test
...
Ran 318 tests in 29.370s
OK
```
**318 tests** (306 pre-existing baseline + 12 new), reported as
observed. No regression anywhere else in the backend.

```
$ python manage.py check --settings=config.settings_test
System check identified no issues (0 silenced).
```

---

## 14. Live Verification

**NOT VERIFIED — development stack unavailable.** `docker ps` showed
only `wamora-dev-tencent-bff-1`/`wamora-dev-tencent-frontend-1` running
— the Office-side stack (Django/Celery/Redis) was not running and was
not started for this task. No live HTTP call was made against a running
Django instance; no real WAHA session's reconciliation state was
touched, read, or reset — none was possible or attempted, consistent
with the task's explicit prohibition on resetting real reconciliation
state for testing purposes. What was verified instead: the full DRF
request/response cycle through Django's real test client (Section 13),
including authentication, permission checks, and the actual
conditional-`UPDATE` SQL executing against a real (SQLite, test)
database — the same rigor as every other test in this suite.

No frontend UI was built (Section this report doesn't otherwise cover,
see Section 16) — this audit found no explicit requirement for one, so
none was added; the endpoint is documented here for direct/manual
invocation.

**Manual invocation** (for a future operator, once the Office stack and
a real JWT with the `system administration` scope are available):
```
POST /api/sync/recover/<session_name>/
Authorization: Bearer <JWT with 'system administration' scope>
```
No request body. See Section 11 for the full response contract.

---

## 15. Security Considerations

- **No new unauthenticated surface** — `401`/`403` enforced exactly as
  every other JWT-authenticated Django endpoint in this project
  (Section 7).
- **No secret exposed** — the response body and `AuditLog` entry both
  contain only a session name and status values; `last_error`'s new
  content (a fixed, static recovery-marker string, never raw
  exception/WAHA/Celery text) is written to the database but **never
  echoed back in the response**, matching `SyncStatusView`'s own
  established discipline of never returning `last_error` to a client.
- **No SQL injection surface** — all queries use the Django ORM's
  parameterized query builder, no raw SQL anywhere in this view.
- **No CSRF concern beyond DRF's existing defaults** — this is a
  JWT-bearer-token-authenticated API endpoint (`SessionAuthentication`
  is not in `authentication_classes`), the same posture every other
  endpoint in this codebase already has.
- **No information disclosure via error codes** — the four `409`
  rejection reasons (`no_checkpoint`/`not_running`/`not_stale`/
  `concurrent_state_change`) reveal only checkpoint *state*, not
  message content, WAHA internals, or Celery task details.
- **This is a genuinely destructive/state-changing action**, correctly
  gated behind a scope that (before this task) had never been checked
  anywhere — this task is also the first real-world exercise of
  `'system administration'` actually meaning something operationally.

---

## 16. Known Limitations

- **No live HTTP verification was performed** (Section 14) — the
  Office-side stack was not running and was not started for this task.
- **No frontend/admin UI was built** — this audit found no explicit
  requirement for one in the task's own instructions ("Tidak perlu
  membuat frontend UI kecuali audit menemukan bahwa task ini secara
  eksplisit membutuhkan UI") and none was found; the endpoint is
  reachable only via direct API calls (e.g. `curl`, or a future
  dedicated UI task) for now.
- **`possibly_stuck`'s own known limitation carries over unchanged**:
  the 660-second threshold is a heuristic, not a proof (per the
  detection design audit) — this recovery action inherits that same
  false-positive possibility; the compare-and-set guard (Section 6)
  only protects against a *race*, not against acting on a checkpoint
  that is stale-by-the-heuristic but still genuinely, legitimately
  running (the design audit's own Section 11 finding: candidate A is
  "self-correcting if wrong," not "guaranteed correct").
- **No automatic recovery, no Celery revoke, no worker liveness check,
  no replacement-task enqueue, no distributed lock** — all explicitly
  out of scope for 13.A, per the design audit and this task's own
  instructions.

---

## 17. Git Status

```
$ git status --short backend/apps/authn/permissions.py backend/apps/sync/ backend/apps/audit/
 M backend/apps/authn/permissions.py
?? backend/apps/sync/api_urls.py
?? backend/apps/sync/tests/test_views.py
?? backend/apps/sync/views.py

$ git status --short backend/apps/sync/migrations/ backend/apps/authn/migrations/
(empty — no new migrations)

$ git diff --stat backend/apps/authn/permissions.py
 backend/apps/authn/permissions.py | 15 +++++++++++++++
 1 file changed, 15 insertions(+)
```

`apps/sync/views.py`, `api_urls.py`, and `tests/test_views.py` were
already untracked, uncommitted work from earlier Phase 9.1 tasks this
session (no prior commit exists to diff against) — this task's own
additions to them are confirmed by direct content review (Sections
5/6/9), not by `git diff` (which shows nothing for untracked files).
No file under `bff/`, `frontend/`, `infrastructure/`, or any migration
directory was touched. No secret was added anywhere.

---

## 18. Final Conclusion

Phase 13.A is implemented exactly as designed: a manual,
authenticated, scope-gated endpoint that marks a genuinely
`possibly_stuck` checkpoint `RUNNING → ERROR`, protected by a
compare-and-set conditional update that correctly detects and rejects
(rather than overwrites) a concurrent state change. `checkpoint_value`,
`Message`/`Chat`/`Contact`, Celery task state, and WAHA state are all
provably untouched. Every rejection path leaves the database unchanged
and writes no `AuditLog` entry; the one success path writes exactly
one. 318/318 backend tests pass; `manage.py check` is clean. No
migration, no new dependency, no Docker/BFF/frontend change, no
automatic recovery, no Celery revoke/inspection, and no distributed
lock were introduced — all correctly deferred as explicitly out of
scope for this phase.

**STOP.** Not proceeding to automatic recovery, Celery worker liveness,
task-ID persistence, task revoke, distributed locking, migrations,
replacement-task enqueue, a Dashboard recovery UI, Phase 13.B, or any
other feature. Awaiting further instructions.
