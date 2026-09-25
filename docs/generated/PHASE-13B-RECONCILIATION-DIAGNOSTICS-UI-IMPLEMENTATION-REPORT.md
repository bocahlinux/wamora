# Phase 13.B — Reconciliation Diagnostics UI — Implementation Report

> **Phase labeling note (added 2026-09-26, per
> `docs/generated/PHASE-ROADMAP-STATUS-AUDIT-REPORT.md`):** despite this
> report's filename/title using "13.B", this work is NOT part of the
> canonical roadmap's Phase 13 ("Failure/security testing",
> `docs/15-CODING-PHASES.md`). It is properly a continuation of Phase 4
> ("Reconciliation") and Phase 9 ("Offline/degraded mode"). The "13.A"/
> "13.B" numbering was informal, originating from an internal subsection
> label ("Section 13, options A and B") in
> `NEXT-PHASE-RECONCILIATION-RECOVERY-DESIGN-AUDIT-REPORT.md`, and is
> retained here only for continuity with existing links — it does not
> reflect the official roadmap. See
> `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` for the recorded decision.

## 1. Objective

Implement the minimal, approved scope from
`docs/generated/PHASE-13B-RECONCILIATION-DIAGNOSTICS-UI-DESIGN-AUDIT-REPORT.md`
Section 9: surface `possibly_stuck` in the existing `InboxPage.tsx`
reconciliation badge, and add a manually triggered, admin-gated recovery
action visible only when `possibly_stuck === true`. Nothing beyond this
approved scope was built (no Celery task-state UI, no automatic recovery,
no new backend/BFF endpoint).

## 2. Initial State

**VERIFIED FROM SOURCE** (re-confirmed at the start of this task, matching
the prior audit): `frontend/src/lib/djangoApi.ts`'s `SyncStatus` type did
not declare `possibly_stuck` or `last_webhook_received_at`; `InboxPage.tsx`
displayed only a coarse `StatusBadge` fed by `mapSyncStatus(sync_status)`;
`DashboardPage.tsx` does not call `getSyncStatus`; no frontend code
anywhere branched on JWT scopes
(`grep -rn "claims\.scopes\.includes" frontend/src` returned no matches
before this task); no caller of `POST /api/sync/recover/:session/` existed
anywhere in `frontend/src`.

## 3. Existing UI Patterns Reused

- **`StatusBadge` / `mapSyncStatus`** (`frontend/src/components/ui/StatusBadge.tsx`) —
  extended with an additive, optional second parameter rather than a new
  component or a sixth `sync_status` value.
- **`ConfirmDialog`** (`frontend/src/components/ui/ConfirmDialog.tsx`) —
  used as-is, no changes, same as its existing Stop/Logout usage in
  `SessionsPage.tsx`.
- **`ErrorState` / `ApiError` / `describeError()`** (`frontend/src/lib/api.ts`,
  `frontend/src/components/ui/ErrorState.tsx`) — used verbatim for the
  recovery action's failure path; no new error-handling code.
- **`useAuth()` / `JwtClaims`** (`frontend/src/lib/AuthContext.tsx`,
  `frontend/src/lib/auth.ts`) — `claims.scopes` (already decoded, already
  typed) read directly; no new decoding utility.
- **Existing polling loop** (`InboxPage.tsx`'s `SYNC_STATUS_POLL_MS`
  `useEffect`) — reused as-is; the fetch function was pulled out into a
  `useCallback` (`fetchSyncStatus`) so the post-recovery refetch could call
  the *same* function, not a duplicate. No new interval was created.
- **`ActionFeedback`-style success/error text pattern** (from
  `SessionsPage.tsx`) — mirrored for the recovery action's feedback
  (`recoveryFeedback` state: `success | error`), using the same CSS chip
  formula already used by `.wa-inbox__connectivity` /
  `.wa-inbox__send-unknown`.
- **`djangoApi.ts`'s existing mutation-function shape** (e.g.
  `markChatRead`) — `recoverSyncCheckpoint()` follows the same
  `request<T>(url, { method: 'POST', headers: authHeader() })` pattern,
  Frontend → Django direct, no BFF involvement.

No new UI primitive, dependency, or architectural pattern was introduced.
The one genuinely new idiom (per the audit's own Section 7/16) is
client-side JWT-scope UI hiding — kept to a single inline
`claims?.scopes.includes('system administration') ?? false` check, exactly
as the audit recommended, not generalized into a shared utility since this
is the only call site.

## 4. Files Changed

- `frontend/src/lib/djangoApi.ts` — added `possibly_stuck: boolean` and
  `last_webhook_received_at: string | null` to `SyncStatus`; added
  `SyncCheckpointRecoveryResult` type and `recoverSyncCheckpoint(session)`
  function (`POST /api/sync/recover/:session/`).
- `frontend/src/components/ui/StatusBadge.tsx` — `mapSyncStatus()` gained
  an optional second parameter `possiblyStuck?: boolean`; when
  `sync_status === 'running' && possiblyStuck`, returns the existing
  `'warning'` `StatusKind` instead of `'syncing'`. All other branches
  unchanged.
- `frontend/src/pages/InboxPage.tsx` — `SyncStatus`'s `not_found` fallback
  object extended with the two new fields; `fetchSyncStatus` extracted
  from the polling `useEffect` into a `useCallback` (reused by both the
  interval and the post-recovery refetch); new recovery state
  (`canRecover`, `recoveryConfirmOpen`, `recoveryBusy`,
  `recoveryFeedback`) and `handleRecoverConfirmed()`; new JSX: a
  `possibly_stuck` warning chip (with the recovery button inside it,
  admin-only), a recovery feedback line, and a `ConfirmDialog` instance.
- `frontend/src/pages/InboxPage.css` — added `.wa-inbox__sync-stuck`,
  `.wa-inbox__sync-stuck-text`, `.wa-inbox__sync-recovery-feedback`,
  `.wa-inbox__sync-recovery-feedback--success`, matching the existing
  warning-chip/feedback-line visual formula already used elsewhere in this
  file.

No other file was created or modified by this task. (`infrastructure/development/office.yml`
appears modified in `git status` but that change pre-dates this task —
confirmed via the conversation's own starting git-status snapshot, not
touched here.)

## 5. Sync Status UI Behavior

`syncStatus.possibly_stuck === false` (the existing five-value
`sync_status` badge, unchanged): `mapSyncStatus(sync_status, false)` takes
the same branches as before — behavior is byte-for-byte identical to
pre-task for every non-stuck case, since the new parameter only affects
the `running` branch when truthy.

## 6. `possibly_stuck` Behavior

When `sync_status === 'running' && possibly_stuck === true`:
- The header `StatusBadge` switches from the `'syncing'` tone/icon to the
  existing `'warning'` tone/icon (`TriangleAlert`, amber) — reusing the
  palette, not inventing a new one.
- A dedicated warning chip renders below the page header:
  *"Reconciliation may be stuck — it has been running longer than
  expected. This is a diagnostic signal, not confirmation that the run has
  failed."* — deliberately hedged language, never asserting the task is
  dead or the worker crashed, per the task's explicit certainty
  constraint.
- This rides the existing 32-second (`SYNC_STATUS_POLL_MS`) poll — no new
  interval.

## 7. Authorization Behavior

`canRecover = claims?.scopes.includes('system administration') ?? false`,
read from `useAuth()`'s already-decoded `JwtClaims`. The recovery button
is only rendered (not merely disabled) when `possibly_stuck === true`
*and* `canRecover === true`; a user without the scope never sees any
recovery affordance, even when `possibly_stuck` is true. No backend file
was touched — `HasSystemAdministrationScope` on
`SyncCheckpointRecoveryView` remains the sole actual authorization
boundary; this is a UX courtesy only, consistent with
`lib/auth.ts`'s own `decodeToken()` docstring warning. No new JWT scope
was introduced anywhere.

## 8. Recovery Flow

1. Admin clicks "Mark reconciliation as failed…" (visible only per
   Section 7) → opens the existing `ConfirmDialog`.
2. Dialog copy: *"Reconciliation is only suspected to be stuck — this is
   based on how long it has been running, not proof the process has
   stopped. Confirming will mark the current run as failed so a future
   reconciliation can start cleanly; it will not start a new run
   automatically, and this cannot be undone. Only continue if you believe
   this run is no longer active."* — states the destructive,
   non-reversible, non-auto-restarting nature explicitly, calm tone (no
   "danger"/urgency language beyond the dialog's existing default
   `variant="danger"` button styling).
3. On confirm: `recoverSyncCheckpoint(sessionName)` →
   `POST /api/sync/recover/:session/` via the existing Django API client
   pattern (`authHeader()`, no body) — never through the BFF.
4. Busy state (`recoveryBusy`) disables both the trigger button and the
   dialog's confirm button while in flight (mirrors `ConfirmDialog`'s own
   `busy` prop, already used by `SessionsPage.tsx`).

## 9. Error Handling

All non-2xx outcomes route through the single existing `ApiError`
taxonomy (`lib/api.ts`) with zero new error-handling code:
- **401** → `{ kind: 'unauthorized' }` → `describeError()`: "Your session
  has expired. Please sign in again."
- **403** → `{ kind: 'forbidden' }` → "You don't have permission to do
  this." (defense-in-depth: reachable if a token's scope is stale/forged
  relative to what the UI decoded).
- **404** → `{ kind: 'not_found' }` → "Not found."
- **409** (including `concurrent_state_change`) → `{ kind: 'validation',
  message: <server's own message> }` — the backend's own operator-facing
  sentence is rendered verbatim via `ErrorState`, unmodified, exactly as
  the design audit's Section 6.6 predicted required zero new code for.
  **Never auto-retried, never auto-reissued** — the failure is shown and
  the flow stops; the operator must explicitly re-click if they choose
  to.
- **Generic/other failures** (`server_error`, `network_error`, `timeout`,
  `unknown`) → their existing `describeError()` messages.

All of the above render through the existing `<ErrorState error={...} />`
component below the warning chip — no raw stack trace or backend detail
is ever shown, consistent with the project's existing discipline.

## 10. Post-Recovery Refetch

On a successful recovery response, `fetchSyncStatus()` (the same
`useCallback` the polling interval calls) is invoked directly — this is a
refetch of the existing read, not new polling infrastructure. The UI's
`syncStatus` state, and therefore the badge and the warning chip's
visibility, updates from whatever the server actually returns next (e.g.
`sync_status: 'failed'`, `possibly_stuck: false`) — the resulting status is
never fabricated or guessed locally. A plain success line is also shown:
*"Reconciliation for `<session>` was marked as failed. A future
reconciliation run can start cleanly."*

## 11. Task-State API Intentionally Not Used

No file added a caller for `GET /api/sync/task-state/:session/`. No
Celery task ID, Celery state string, `PENDING`, trigger source, or
`last_run_task_id` is displayed anywhere. This matches the task's explicit
exclusion and the design audit's Section 9/16 recommendation to defer
task-state detail entirely.

## 12. Testing

- `npm run lint` (oxlint) — **PASS**. Only pre-existing warnings unrelated
  to this change remain (`react(only-export-components)` in
  `StatusBadge.tsx`, `AuthContext.tsx`, `ThemeContext.tsx`; a
  `react(set-state-in-effect)` warning in `AuthContext.tsx`) — all on code
  this task did not add (the `StatusBadge.tsx` warnings are on
  `mapWahaStatus`/`mapActivityResult`/the file's other exported functions,
  not the edited `mapSyncStatus`; `AuthContext.tsx`/`ThemeContext.tsx` were
  not touched by this task). Zero new warnings or errors introduced.
- `npm run build` (`tsc -b && vite build`) — **PASS**, zero TypeScript
  errors, zero build errors. Output: `dist/assets/index-*.js` 311.94 kB
  (gzip 97.94 kB).
- No frontend test framework exists in this repository
  (`find frontend/src -iname "*.test.*" -o -iname "*.spec.*"` → no
  matches) — none was added, per the task's explicit prohibition.

Manual code-path verification (no browser automation tool available in
this environment):

1. **Normal status render** (`possibly_stuck: false`) — **VERIFIED**
   (traced through source): `mapSyncStatus(sync_status, false)` takes the
   exact same switch branches as the pre-existing single-argument calls;
   no new chip renders since `syncStatus?.possibly_stuck` is falsy.
2. **`possibly_stuck` status render** — **VERIFIED**: with
   `sync_status: 'running', possibly_stuck: true`,
   `mapSyncStatus` returns `'warning'` (first `if` branch short-circuits
   before the switch); `syncStatus?.possibly_stuck` is truthy so the
   warning chip JSX renders.
3. **Non-admin user (no recovery button)** — **VERIFIED**: `canRecover`
   evaluates `claims?.scopes.includes('system administration') ?? false`;
   for any `claims.scopes` array lacking that exact string, this is
   `false`, and the `{canRecover ? <Button>... : null}` conditional
   renders nothing — the button is absent from the DOM, not merely
   disabled.
4. **Admin user (recovery button shown)** — **VERIFIED**: when
   `claims.scopes` contains `'system administration'` *and*
   `syncStatus.possibly_stuck === true` (both conditions are `&&`'d via
   nested conditionals — the outer `syncStatus?.possibly_stuck` gate, the
   inner `canRecover` gate), the button renders.
5. **Recovery success path** — **VERIFIED**: `handleRecoverConfirmed()`
   calls `recoverSyncCheckpoint`, and on `result.ok === true` sets
   `recoveryFeedback` to `{ kind: 'success' }` and calls
   `fetchSyncStatus()` — traced line-by-line above (Section 10).
6. **Recovery 409 path** — **VERIFIED**: `request<T>()` in `lib/api.ts`
   maps any `400`/`409` status to `{ kind: 'validation', message:
   <server's error.message> }` (`errorForStatus()`, `api.ts:33-39`); the
   component's `!result.ok` branch sets `recoveryFeedback = { kind:
   'error', error: result.error }`, which renders via
   `<ErrorState error={recoveryFeedback.error} />` → `describeError()`
   returns `error.message` verbatim for `kind: 'validation'`.
7. **Recovery generic failure path** — **VERIFIED**: any other
   `ApiError.kind` (`unauthorized`, `forbidden`, `not_found`,
   `server_error`, `network_error`, `timeout`, `unknown`) takes the same
   `!result.ok` branch and renders through the same `ErrorState` with that
   kind's `describeError()` message — no special-casing needed or added.
8. **Post-recovery refetch** — **VERIFIED**: `fetchSyncStatus()` is called
   unconditionally after a successful recovery (Section 10), which calls
   `getSyncStatus(sessionName)` and, on success, calls
   `setSyncStatus(result.data)` — the exact same code path the polling
   interval uses, so the UI updates from a real server response, never a
   fabricated one.

**NOT VERIFIED** (would require a live browser + an authenticated
system-administration-scoped session, unavailable in this environment):
actual pixel-level rendering, real click-through of the `ConfirmDialog`,
and the live JSON shape of a genuine `possibly_stuck: true` or `409`
response body (see Section 13 for what *was* live-checked).

## 13. Live Verification

The Office-side dev stack (`development-backend-1`,
`development-celery-worker-1`, `development-celery-beat-1`,
`development-redis-1`) was found already running (`docker ps`) — it was
**not** started, stopped, or restarted by this task, per the constraint.

One read-only GET was issued, without credentials, to sanity-check the
endpoint's reachability and error-response shape (no POST/recovery call
was made, matching the task's explicit prohibition):

```
GET http://localhost:8000/api/sync/status/no_epahari/
→ HTTP/1.1 401 Unauthorized
  {"error":{"code":"not_authenticated","message":"Authentication credentials were not provided.","request_id":"..."}}
```

**VERIFIED (live)**: the endpoint is reachable at the URL
`frontend/src/lib/djangoApi.ts`'s `getSyncStatus()` constructs, and an
unauthenticated request returns a `401` with a JSON `error.message` field
— exactly the shape `errorForStatus()` (`lib/api.ts:29-42`) expects and
maps to `{ kind: 'unauthorized' }`.

**NOT VERIFIED (live)**: the authenticated response shape (i.e. that
`possibly_stuck`/`last_webhook_received_at` are actually present in a real
`200` response body) — no test credentials with a valid JWT were available
to this task, and creating/using one was outside this task's scope. This
matches the design audit's own Section 3 finding, taken on backend source
inspection (`backend/apps/sync/views.py:185-194`) rather than a live
authenticated call, which this task also did not newly establish. The
`POST /api/sync/recover/...` endpoint was never called, per the explicit
prohibition.

## 14. Regression Verification

```
git status
  modified:   frontend/src/components/ui/StatusBadge.tsx
  modified:   frontend/src/lib/djangoApi.ts
  modified:   frontend/src/pages/InboxPage.css
  modified:   frontend/src/pages/InboxPage.tsx
  modified:   infrastructure/development/office.yml   <- pre-existing, not from this task
  untracked:  docs/generated/PHASE-13B-...DESIGN-AUDIT-REPORT.md  <- pre-existing, not from this task

git diff --stat
 frontend/src/components/ui/StatusBadge.tsx |  13 ++-
 frontend/src/lib/djangoApi.ts              |  32 ++++++
 frontend/src/pages/InboxPage.css           |  35 ++++++
 frontend/src/pages/InboxPage.tsx           | 166 +++++++++++++++++++++++------
 infrastructure/development/office.yml      |   1 +
```

Confirmed:
- Only the four intended frontend files were changed by this task.
- No dependency manifest changed (`package.json`/`package-lock.json`
  absent from the diff).
- No `backend/` or `bff/` file changed.
- No Docker/Compose file changed by this task (the one modified Compose
  file, `infrastructure/development/office.yml`, was already modified
  before this task started, per the conversation's own starting git-status
  snapshot — not touched here).
- No secret, credential, or WAHA API key was introduced anywhere (the only
  new network call, `recoverSyncCheckpoint`, uses the existing
  `authHeader()`/JWT mechanism, identical to every other `djangoApi.ts`
  function).

## 15. Security Considerations

- The recovery button's visibility is UX-only; `HasSystemAdministrationScope`
  on `SyncCheckpointRecoveryView` (unmodified, backend-side) remains the
  actual and only enforcement boundary. A forged/stale client-side claim
  cannot obtain a successful recovery — the server independently verifies
  the JWT's signature and scope on every request, so even a manipulated
  client that showed the button anyway would still receive a `403` from
  the real request. Section 9 above traces this exact failure path
  through the ordinary `403`/`ErrorState` rendering, with no special
  handling required.
- `possibly_stuck` itself required no new authorization tier — it was
  already returned to any authenticated user by `SyncStatusView` before
  this task; this task did not change that endpoint's server-side
  behavior or scope requirements.
- No WAHA API key, database credential, or other secret was added to any
  frontend file, `localStorage`, or the browser bundle. The frontend
  continues to call Django directly for sync/recovery (never WAHA
  directly, and never through the BFF for this data path) — matching hard
  rules 3/4/5.
- `crypto`/idempotency: the recovery endpoint's own compare-and-set
  semantics (backend, unmodified) are what actually prevents a
  double-apply; this task did not add a client-side idempotency key
  because `SyncCheckpointRecoveryView` was explicitly out of scope to
  modify and its existing CAS logic was not altered or duplicated
  client-side.

## 16. Known Limitations

- The `possibly_stuck` badge/chip can lag real backend state by up to the
  existing ~32-second poll interval — an already-accepted, pre-existing
  staleness window (Section 4 of the design audit), not newly introduced.
- `last_webhook_received_at` was added to the `SyncStatus` TypeScript type
  for accuracy only; per the hard scope constraint, it is not rendered by
  any UI in this phase (no existing, established place in `InboxPage.tsx`
  it naturally belongs, per the design audit's own finding).
- No live-authenticated verification of the exact `possibly_stuck: true`
  JSON payload or of a genuine `409 concurrent_state_change` response was
  performed (Section 13) — only source-level backend contract inspection
  (already done in the prior design audit) and the frontend's own
  type/error-mapping logic (this task) back these claims.
- No browser/visual verification was performed — every UI-behavior claim
  in Sections 5–10 and 12 is a source-level trace, not an observed
  rendered page.

## 17. Git Status

Working tree at the end of this task (see Section 14's literal output):
four modified frontend files (`StatusBadge.tsx`, `djangoApi.ts`,
`InboxPage.css`, `InboxPage.tsx`), plus this new report file. No commit
was created by this task (not requested).

## 18. Final Conclusion

The approved minimal scope — surfacing `possibly_stuck` in the existing
`InboxPage.tsx` badge, and a `system administration`-scoped, confirm-gated
manual recovery action — was implemented entirely by extending existing
patterns (`StatusBadge`'s mapper, `ConfirmDialog`, the existing sync-status
poll/refetch, the existing `ApiError`/`ErrorState` taxonomy, and
`useAuth()`'s already-decoded JWT claims). No new backend/BFF endpoint,
database field, migration, Docker change, npm dependency, polling loop, or
JWT scope was introduced. `npm run lint` and `npm run build` both pass
cleanly with no new warnings or errors. No file outside the expected scope
was modified. Celery task-state detail, trigger-source display, and
automatic recovery remain explicitly out of scope and were not built, per
the task's stop condition.

**STOP.** This implementation is complete. No further phase, automatic
recovery, Celery worker liveness feature, or production/staging concern
was started.
