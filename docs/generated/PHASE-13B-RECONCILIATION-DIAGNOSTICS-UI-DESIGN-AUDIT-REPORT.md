# Phase 13.B — Reconciliation Diagnostics UI — Design Audit Report

**This is a read-only design audit. No source, migration, Docker,
Compose, or configuration file was modified. No container was started,
stopped, or restarted. No reconciliation was triggered. No write
endpoint (`POST /api/sync/recover/...`) was called. No Celery task was
called. The only file created by this task is this report.**

**Conclusion up front:** the frontend currently exposes **none** of
Phase 13.A/13.B's backend observability surface — not `possibly_stuck`,
not `last_run_task_id`/`last_run_trigger_source`, not Celery task
state, not a recovery control. `InboxPage.tsx` already polls
`GET /api/sync/status/<session>/` every 32s and shows only a coarse
`sync_status` badge; its own frontend type (`djangoApi.ts`) doesn't
even declare `possibly_stuck` or `last_webhook_received_at`, both of
which the backend already returns. A minimal, safe next step exists
(Section 9) that surfaces `possibly_stuck` plus a manual recovery
button, admin-gated, confirm-required, non-polling; Celery task-state
detail is recommended as an on-demand, admin-only expansion, never
polled, never implying more certainty than the backend itself claims.
No polling infrastructure, JWT scope, or dependency needs to be added.

---

## 1. Objective

Determine whether the current frontend gives an administrator enough
operational visibility into reconciliation problems, and specifically
whether `SyncCheckpoint` observability metadata (Section 2/3 of the
prompt), the diagnostic Celery task-state endpoint (Section 4), and the
Phase 13.A manual-recovery endpoint (Section 5) should remain API-only
or be surfaced in the frontend — as a design audit only, per the task's
own strict stop condition.

---

## 2. Current Frontend Architecture

**VERIFIED FROM SOURCE.**

### 2.1 Request paths

- **Sync status is Frontend → Django direct**, never through the BFF.
  `frontend/src/lib/djangoApi.ts:179-183` (`getSyncStatus`) calls
  `${config.djangoBaseUrl}/api/sync/status/${session}/` with
  `authHeader()` (the user's own JWT). `frontend/src/lib/bffApi.ts` has
  **zero** references to `/api/sync/` — confirmed by
  `grep -rn "sync/status|sync/recover|sync/task-state" bff/src` (no
  matches) and a files-with-matches scan of `bff/src` for `sync`/
  `reconcil`, whose 7 hits are all unrelated words (`synchronous`,
  etc.) in `djangoClient.ts`, `routes/messages.ts`, `routes/session.ts`,
  `config.ts`, `auditHelper.ts`, `routes/health.ts`, `wahaClient.ts`.
  This matches `backend/apps/sync/views.py`'s own module docstring:
  "the same Frontend -> Django direct pattern `apps.chats`/
  `apps.dashboard` already use, not a new BFF hop."
- **The BFF is used only for WAHA-touching calls**: session
  status/start/stop/restart/logout/QR/pairing/send
  (`frontend/src/lib/bffApi.ts`), matching hard rule 4 (frontend never
  calls WAHA directly) — irrelevant to sync/reconciliation, which never
  touches WAHA (`SyncStatusView`'s own docstring: "never touches WAHA,
  Redis, or Celery").
- **Task-state (`/api/sync/task-state/<session>/`) and recovery
  (`/api/sync/recover/<session>/`) have no frontend caller of any
  kind** — confirmed: `grep -rn "task-state|sync/recover" frontend/src`
  returns no matches (checked as part of this audit; also consistent
  with the Phase 13.A implementation report's own Section 16, "No
  frontend/admin UI was built").

### 2.2 Auth model (frontend side)

`frontend/src/lib/auth.ts` decodes the JWT client-side
(`decodeToken()`) purely for display purposes (`JwtClaims.scopes` is
typed and available), explicitly documented as **not** a security
decision: "This is NOT verification... the frontend must never make a
security decision based on this decoded value alone." **VERIFIED**:
`grep -rn "claims\.scopes|scopes\.includes|scopes\?\.|\.scopes\b" frontend/src`
returns **zero matches** — no frontend code anywhere currently branches
UI on JWT scopes. `ProtectedRoute.tsx` gates only on
`isAuthenticated` (any valid, non-expired JWT), not on any scope.
`Sidebar.tsx`'s nav list (`NAV_ITEMS`) is static and unconditional.
**There is no existing "admin-only UI" pattern in this frontend to
reuse** — this is a genuinely new UI pattern, not a precedent-following
one, if Phase 13.B builds anything scope-gated.

### 2.3 Shared primitives already available

- `components/ui/StatusBadge.tsx` — a `StatusKind` union
  (`healthy|working|scan_qr|starting|syncing|warning|error|offline|unknown`)
  with three existing mapper functions (`mapWahaStatus`,
  `mapSyncStatus`, `mapActivityResult`), each documented as "never
  invents a status the backend didn't report; unrecognized falls back
  to `unknown`."
- `components/ui/ConfirmDialog.tsx` — used today only for session
  Stop/Logout (`SessionsPage.tsx`), per its own comment: "design spec
  Section 12: Destructive actions must require appropriate
  confirmation... not added to Start/Restart, which aren't
  destructive."
- `components/ui/{Card,EmptyState,ErrorState,LoadingState,PageHeader,Badge,Button,Modal,Input,IconButton}.tsx`
  — the full existing UI kit; no reconciliation-specific component
  exists among them.
- `lib/useApiQuery.ts` — shared fetch-once-per-deps-change
  loading/success/error hook, used by every fetch-on-mount card
  (Dashboard's four health cards, Sessions' status query). **Not** used
  by `InboxPage.tsx`'s sync-status polling, which is a hand-rolled
  `useEffect` + `setInterval` specifically because it needed no
  dedicated loading/error UI (its own comment: "not yet fetched" renders
  nothing).
- `lib/api.ts` — the shared `ApiError` taxonomy
  (`validation|unauthorized|forbidden|not_found|server_error|
  network_error|timeout|unknown`) and `describeError()`, which already
  maps a `403` to "You don't have permission to do this." — the exact
  message a scope-gated recovery/task-state call would surface today
  with **zero new code**, if a non-admin user's JWT lacked the scope
  (defense in depth; Section 7).

---

## 3. Existing Reconciliation Visibility

**VERIFIED FROM SOURCE.**

- **The only place reconciliation/sync status is visible today is
  `InboxPage.tsx`'s `PageHeader` action slot** (lines 305-315): a single
  `StatusBadge` driven by `mapSyncStatus(syncStatus.sync_status)`,
  labeled via a local `SYNC_STATUS_LABEL` map
  (`healthy→"Synced"`, `running→"Syncing"`, `stale→"Sync delayed"`,
  `failed→"Sync error"`, `never_synced→"Not synced"`).
- **`DashboardPage.tsx` does not call `getSyncStatus` at all** —
  re-confirmed this task (its imports list `getBffHealth`,
  `getSessionStatus`, and four `djangoApi` health/messages/activity
  functions; `getSyncStatus` is absent). The Dashboard's existing Redis
  card and WhatsApp Session card (Section 2.3 of the prompt) report
  broker reachability and live WAHA connection state respectively —
  neither says anything about reconciliation.
- **`SessionsPage.tsx` shows WAHA session lifecycle status only**
  (`mapWahaStatus`), never `SyncCheckpoint`/reconciliation state — a
  different concern entirely (confirmed by re-reading the full file;
  no `getSyncStatus` import).
- **The frontend's own `SyncStatus` type
  (`frontend/src/lib/djangoApi.ts:166-173`) is stale relative to the
  backend's actual response shape**: it declares `session`,
  `sync_status`, `checkpoint_status`, `last_run_at`,
  `seconds_since_last_run`, `checkpoint_updated_at` — but **not**
  `last_webhook_received_at` (added by Phase 9.1B) and **not**
  `possibly_stuck` (added by the possibly-stuck-detection phase),
  both of which `SyncStatusView.get()` (`backend/apps/sync/views.py:185-194`)
  already returns in every response today. This is not a bug per se —
  the possibly-stuck design audit itself explicitly deferred this
  ("Any frontend display of this field — left as a natural, separate
  future task", `NEXT-PHASE-POSSIBLY-STUCK-DETECTION-DESIGN-AUDIT-REPORT.md`,
  Section 15) — but it means **`possibly_stuck` is invisible to an
  administrator today even though the backend has been computing and
  returning it correctly since that phase shipped.**
- **`last_run_trigger_source`, `last_run_task_id`, and both diagnostic
  endpoints (`task-state`, `recover`) have no frontend representation
  whatsoever** — no type, no API-helper function, no component, no
  route.

---

## 4. `possibly_stuck` Analysis

**VERIFIED FROM SOURCE** (`backend/apps/sync/views.py:121-139`,
Section 3 above).

- **Not currently displayed anywhere.**
- **Natural fit**: the existing `InboxPage.tsx` `StatusBadge` slot,
  additively — `possibly_stuck: true` only ever co-occurs with
  `sync_status: 'running'` (`_is_possibly_stuck()` returns `False`
  immediately unless `checkpoint.status == STATUS_RUNNING`), so it can
  be layered as a **more specific badge state**
  (`running` + `possibly_stuck` → a distinct `StatusKind`, e.g.
  reusing the existing `warning` tone/icon already in
  `StatusBadge.tsx`) rather than a second, competing indicator. It
  does **not** require inventing a new visual language — `warning`
  (`TriangleAlert`, amber) is already in the palette and is not
  currently used by `mapSyncStatus` (which maps `stale` to `warning`
  today, a different, non-overlapping condition — `stale` requires
  `status == STATUS_OK` with `possibly_stuck` always `false` for that
  status, per `_is_possibly_stuck`'s own guard — so the two conditions
  are mutually exclusive and can share the tone without ambiguity).
- **Reuses `mapSyncStatus` or requires a small addition?** Requires a
  **small, additive change**: `mapSyncStatus`'s current signature takes
  only `sync_status: SyncStatus['sync_status']`, a five-value string;
  `possibly_stuck` is a separate boolean field, not a sixth
  `sync_status` value (the backend design audit was explicit:
  "Boolean, not enum... keeps `sync_status`'s existing five-value
  contract completely unchanged"). The frontend mapping logic would
  need to consider **both** fields together (e.g. a small helper that
  special-cases `sync_status === 'running' && possibly_stuck` before
  falling through to the existing `mapSyncStatus` switch) — this is a
  few lines, not a new component.
- **New frontend type required**: yes, minimally — `SyncStatus` in
  `djangoApi.ts` needs `possibly_stuck: boolean` added (and, while at
  it, the already-missing `last_webhook_received_at: string | null`,
  Section 3, though that field is out of this audit's direct scope).
- **Polling**: `InboxPage.tsx` **already polls** `getSyncStatus` every
  `SYNC_STATUS_POLL_MS` (32000ms, `= CHAT_LIST_POLL_MS * 4`) — this is
  the **one place** in the whole frontend where sync status is already
  refreshed on an interval, established **before** this audit, not
  introduced by it. Surfacing `possibly_stuck` in that same badge
  therefore requires **zero new polling infrastructure** — it rides
  the existing interval. Per the task's own instruction ("Do NOT
  introduce polling unless source proves it's already the established
  pattern"): **source proves it is** — this is not a new decision, it
  is reusing an existing one.
- **Fetch-on-mount elsewhere (e.g. Dashboard)?** If `possibly_stuck`
  were *also* wanted on `DashboardPage.tsx` (which does not call
  `getSyncStatus` at all today, Section 3), the audit recommends
  **fetch-once-on-mount only** (matching every existing Dashboard
  health card's `useApiQuery` pattern), explicitly **not** a second
  independent polling loop — introducing Dashboard polling for this
  single field would be a new pattern this audit does not find
  justified by anything in the prompt's requirements.
- **Staleness risk**: a `possibly_stuck: true` badge on a 32-second
  poll cycle can lag reality by up to ~32s (e.g., the checkpoint
  recovers or a genuine completion lands between polls) — a bounded,
  already-accepted staleness window (the existing `sync_status` badge
  has the identical exposure today, unrelated to this task). Not a new
  risk category; no additional mitigation is proposed beyond what
  `InboxPage.tsx` already does (freeze last-known value on a
  connectivity-class poll failure, never blank it — see
  `reportPollOutcome`'s existing "freeze, don't blank" discipline).

---

## 5. Celery Task-State Analysis

**VERIFIED FROM SOURCE** (`backend/apps/sync/views.py:341-445`,
`NEXT-PHASE-CELERY-TASK-CORRELATION-DESIGN-AUDIT-REPORT.md`).

### 5.1 State taxonomy and what the UI may safely claim

| Celery state | Backend's own framing | Safe UI claim |
|---|---|---|
| `PENDING` | **Explicitly ambiguous** — "reports PENDING for both a genuinely queued-but-not-yet-started task and a task ID it has never seen at all" (`PENDING_AMBIGUITY_NOTE`, verbatim in the API response as `note`) | Must display literally as ambiguous — e.g. "Pending (or unknown to Celery)" — **never** "Task is running" or "Task is queued" |
| `RECEIVED` | Not special-cased by the backend; passed through raw | Display as-is, no added interpretation |
| `STARTED` | Not special-cased; `CELERY_TASK_TRACK_STARTED=True` per the correlation audit's Section 4, but that same audit notes a killed task's `.state` may remain `STARTED` forever ("**INFERRED**, not live-tested") | Display as-is; must **not** claim "currently executing" as a certainty |
| `RETRY` | Not special-cased | Display as-is; the correlation audit's Section 7 notes a legitimate multi-attempt retry sequence can exceed the 660s `possibly_stuck` threshold — worth a UI hint that RETRY is not itself evidence of a dead task |
| `SUCCESS` | Not special-cased | Display as-is |
| `FAILURE` | Not special-cased | Display as-is |
| `REVOKED` | Not special-cased (and this codebase never calls `.revoke()` anywhere — confirmed by the correlation audit's own grep) | Display as-is; would only ever appear if revoked by a means outside this application, so flag as unexpected if seen |
| No task ID recorded | `reason: 'no_task_id'`, `NO_TASK_ID_NOTE` | Display literally: "No Celery task ID recorded for this run (management-command, synchronous-targeted run, or never reconciled)" |
| Celery/Redis unreachable | `reason: 'unavailable'`, `UNAVAILABLE_NOTE` | Display literally as an infrastructure-reachability problem, **distinct from** the task's own state — never conflated with `PENDING`/`FAILURE` |

**The single most important UI constraint, directly from the backend's
own docstring**: *"THIS RESULT IS NOT OWNERSHIP PROOF... `last_run_task_id`
identifies whichever task most recently STARTED a run on this
checkpoint, not necessarily the task that produced its current
status."* Any UI surfacing this data **must** carry that caveat
adjacent to the value, not bury it in a tooltip a busy operator will
skip — this is a correctness-of-understanding requirement, not a
cosmetic one, per the task's own Step 4 instruction not to imply more
certainty than the backend provides.

### 5.2 Should task ID be displayed?

Yes, but only to a system-administration-scoped viewer (Section 6), and
always accompanied by the ambiguity/ownership caveats above — a bare
task ID with no state or caveat would be actively misleading (implies
false precision).

### 5.3 Should trigger source be displayed?

Yes — `last_run_trigger_source` (`periodic|targeted|management_command`)
is unambiguous, purely descriptive metadata with no correctness caveat
attached in the backend's own documentation, and is cheap context for
an operator investigating why a run looks stuck (e.g., a
`management_command` run has no enforced time ceiling at all, per the
correlation audit's Section 7 — materially different operational
meaning than a `periodic` run bound by `CELERY_TASK_TIME_LIMIT`).
Note: `trigger_source` is **not currently returned by any endpoint**
(re-confirmed: neither `SyncStatusView` nor
`SyncCheckpointTaskStateView` includes `last_run_trigger_source` in
its response — only `last_run_task_id` is exposed via `task-state`).
Surfacing trigger source in the UI would therefore require **adding it
to an existing response** (most naturally `SyncCheckpointTaskStateView`,
which is already the "internal diagnostic detail" endpoint) — a small,
additive backend change, not a UI-only task. This audit flags it as an
**optional** enhancement (Section 11), not required for a minimal
Phase 13.B.

### 5.4 Admin-only visibility

Yes — the backend already enforces this
(`HasSystemAdministrationScope` on `SyncCheckpointTaskStateView`,
Section 6.2), and the design rationale is explicit in the view's own
docstring: "a Celery task ID is internal system/worker detail, one
step more sensitive than the plain operational status `SyncStatusView`
already exposes to any authenticated user." The frontend should not
weaken this by, e.g., caching/exposing the value somewhere a
non-admin viewer's session could read it.

### 5.5 Should infrastructure errors be exposed to ordinary users?

No — and this is moot for `task-state` specifically, since the entire
endpoint is already admin-gated server-side; an ordinary user's request
gets `403` before `reason: 'unavailable'` is ever computed. This
matches the project's existing discipline elsewhere (e.g.
`RedisHealthView` is public but reports only `status: 'ok'|'error'`,
never a raw exception).

### 5.6 Polling for task state?

**No** — this audit does not recommend polling `task-state`. It is a
point-in-time diagnostic snapshot ("what does Celery say *right now*"),
explicitly framed by its own docstring as "supporting evidence for a
human decision," not a live-updating monitor. An admin investigating a
`possibly_stuck` checkpoint would open this detail, read it once, and
act (or not) via Phase 13.A — a manual "refresh" affordance (reusing
the existing `refetch()` pattern from `useApiQuery`) is sufficient and
matches the one-shot nature of every other diagnostic read in this
codebase (e.g. `SessionsPage.tsx`'s QR code has a manual "Refresh QR"
button, not auto-polling).

---

## 6. Manual Recovery UI Analysis

**VERIFIED FROM SOURCE** (`SyncCheckpointRecoveryView`,
`backend/apps/sync/views.py:197-338`, Section 11 of the 13.A
implementation report).

### 6.1 Should it have a frontend control at all?

This audit finds **yes, conditionally** — the endpoint exists
specifically for human-triggered action ("manual, human-triggered
recovery... closing the lost-update race... via a compare-and-set
write", 13.A implementation report Section 1), and today it is
reachable **only** via direct API call (`curl` or equivalent) per that
report's own Section 16 ("no frontend/admin UI was built... the
endpoint is reachable only via direct API calls... for now"). An
endpoint whose entire purpose is "let a human operator act on
`possibly_stuck`" is of limited practical use to a non-engineer
operator without a UI — but this is a **user decision**, not something
this audit can resolve unilaterally (escalated in Section 14/9 below,
consistent with the task's own Step 9 bar: "changing recovery
semantics" is escalation-worthy, and *adding* the first-ever UI
control for a destructive admin action is adjacent to that bar).

### 6.2 Required authorization

`IsAuthenticated` + `HasSystemAdministrationScope`
(`backend/apps/sync/views.py:236-237`) — **already enforced
server-side**; the frontend control, if built, must be gated on the
same scope for UX purposes only (hiding a button the backend would
reject anyway is a usability courtesy, not a security boundary — the
security boundary is, and remains, server-side, per hard-rule spirit
and the existing `decodeToken()` docstring's own warning against
client-side security decisions).

### 6.3 Confirmation requirement

**Yes, required** — this is a genuinely destructive, state-changing
action (RUNNING → ERROR, marks a run as having failed) and the
project's own existing convention already requires confirmation for
exactly this class of action: `ConfirmDialog.tsx`'s own comment
("design spec Section 12: Destructive actions must require appropriate
confirmation... used only for genuinely destructive session actions
(Stop, Logout)"). Recovery is at least as destructive as Stop/Logout —
arguably more, since it also writes an immutable `AuditLog` entry and
cannot be undone by re-running recovery (the endpoint's own `409
not_running` guard prevents re-firing on an already-`ERROR`
checkpoint).

### 6.4 Wording to prevent accidental recovery

Should state plainly, using the same session-scoped language the
backend itself already returns, e.g.: *"Mark reconciliation for
`<session>` as failed? This session's reconciliation appears stuck
(running longer than expected). This will mark the current run as
failed so a future reconciliation can start cleanly. This cannot be
undone."* — deliberately avoiding euphemism ("recover", alone, could
be misread as "fix it now" rather than "mark the current attempt as
failed"); should explicitly **not** promise that a new reconciliation
run will start automatically, since the endpoint provably does not
enqueue one (13.A docstring: "NOT a replacement-task enqueue").

### 6.5 Should it only appear when `possibly_stuck === true`?

**Yes** — the backend's own `not_stale` (409) rejection already proves
this is the correct precondition (Section 3 of the 13.A implementation
report: "`not _is_possibly_stuck(checkpoint)` → `409 not_stale`...
reached this step only when `status == RUNNING`"). Showing the button
only when `possibly_stuck === true` (Section 4 above) means the UI's
own gating mirrors the server's own rejection logic — the same
"detection and recovery share one definition of stuck" discipline the
backend's own docstring insists on ("Reuses `_is_possibly_stuck()`
verbatim... no second threshold, no duplicated logic"). A frontend
that computed its own, independent "should I show this button" logic
would violate that same discipline the backend was careful to
preserve.

### 6.6 Presenting a `409 concurrent_state_change`

The existing `ApiError` taxonomy already classifies any `400`/`409`
as `{ kind: 'validation', message: <server message> }`
(`frontend/src/lib/api.ts:33-39`), extracting the server's own
`error.message` string — which for this specific case is already a
clear, non-technical sentence: *"This checkpoint changed since it was
last read; recovery was not applied, to avoid overwriting a newer
state."* This can be rendered with the existing `ErrorState` component
verbatim, with **zero new error-handling code** — the existing
generic-validation-error path already does the right thing for this
specific 409, since the backend's own message is already
operator-appropriate (confirmed: no raw stack trace, no internal
detail, per Section 15 of the 13.A implementation report). The other
three 409 codes (`no_checkpoint`, `not_running`, `not_stale`) would
route through the same path — though `not_stale`/`no_checkpoint`
should be structurally unreachable if the button is correctly gated by
`possibly_stuck` (Section 6.5), so seeing one of those in practice
would itself be a signal of a stale/raced UI state, not a normal user
error.

### 6.7 What should happen after a successful recovery?

- The success response (`{ recovered: true, previous_status: 'running',
  status: 'error' }`) should be shown as plain confirmation text (same
  pattern as `SessionsPage.tsx`'s existing
  `wa-session-feedback--success` treatment).
- **The UI should refetch sync status** — reusing `InboxPage.tsx`'s
  existing `getSyncStatus` call (or, if built as a dedicated admin
  panel, its own equivalent) so the badge immediately reflects
  `sync_status: 'failed'` / `possibly_stuck: false` rather than showing
  stale `running`/`possibly_stuck: true` state until the next poll
  tick. This is a **refetch of an existing read**, not new polling
  infrastructure.
- Should **not** auto-navigate away or auto-retry reconciliation — the
  endpoint provably does not enqueue a replacement task, so the UI must
  not imply one is coming.

### 6.8 Is `AuditLog` sufficient for auditability?

**Yes, for the recovery action itself** — `AuditLog.objects.create(actor=request.user, action='sync.checkpoint.recovery', target=f'{session.name} (running->error)', result=AuditLog.RESULT_SUCCESS)`
already captures who, what, and the exact state transition, and is
already surfaced today in `DashboardPage.tsx`'s existing `ActivityCard`
(`GET /api/dashboard/activity/`, which merges `AuditLog` +
`WebhookEvent` — `apps/dashboard/views.py`'s `ActivityFeedView`,
re-confirmed by `DashboardPage.tsx`'s own imports). **No new
audit/logging mechanism is needed** — a recovery action performed via
a future UI would automatically appear in the existing Dashboard
activity feed with zero additional backend work, since that view
already reads the same `AuditLog` table.

---

## 7. Security Analysis

**VERIFIED FROM SOURCE.**

- **`last_run_task_id`, Celery state, and the recovery control are
  already gated by `HasSystemAdministrationScope` server-side** — the
  only scope class this involves; **no new JWT scope needs to be
  introduced** (matching the task's own instruction). `trigger_source`,
  if added to a response (Section 5.3), should be added to the same
  already-admin-gated `SyncCheckpointTaskStateView`, not to the
  public-to-any-authenticated-user `SyncStatusView` — keeping the
  existing two-tier sensitivity split (`SyncStatusView`: any
  authenticated user; `SyncCheckpointTaskStateView`/
  `SyncCheckpointRecoveryView`: system-administration scope only)
  intact rather than blurring it.
- **`possibly_stuck` itself is safe for the existing, broader
  `IsAuthenticated`-only audience** — it is already returned by
  `SyncStatusView` today (Section 3), which has no additional scope
  gate; this audit does not recommend adding one, since doing so would
  be a scope-tightening change to an already-shipped, already-public
  (to any authenticated user) field — out of this audit's mandate and
  not requested.
- **No existing frontend mechanism enforces scope-based UI hiding**
  (Section 2.2) — building one for this feature would be a genuinely
  new pattern. This is safe in principle (hiding is UX only; the
  backend is the actual gate) but is worth calling out explicitly
  because it is new, not a reuse of an established idiom — any
  implementation should keep the hiding logic trivial (a single
  `claims?.scopes.includes('system administration')` check) rather
  than building infrastructure around it.
- **No information-disclosure risk found** beyond what the backend
  already accepts as intentional: task IDs and trigger source are
  internal scheduling metadata, not conversation content, secrets, or
  WAHA/Celery credentials — consistent with the correlation design
  audit's own security framing (no new sensitive-data category is
  introduced by displaying what the backend already decided is safe to
  return to an admin-scoped caller).
- **No source evidence supports exposing this diagnostic information
  to ordinary (non-admin) users** — the backend's own authors were
  explicit that a task ID is "one step more sensitive" than plain
  status; this audit does not propose loosening that.

---

## 8. UX State Model

Derived strictly from fields the backend actually returns today
(Section 3), separated into **FACT** (verbatim backend data), **SIGNAL**
(a UI-level interpretation of one or more facts), and **UNKNOWN**
(what cannot be determined from available data).

| State | FACT (from `/status`, `/task-state`) | SIGNAL (UI-derived) | UNKNOWN |
|---|---|---|---|
| No checkpoint | `sync_status: 'never_synced'`, `checkpoint_status: null` | "This session has never been reconciled" | Whether it ever will be |
| Running (normal) | `sync_status: 'running'`, `possibly_stuck: false` | "Reconciliation in progress" | Exact progress/ETA (not tracked anywhere) |
| Running, possibly stuck | `sync_status: 'running'`, `possibly_stuck: true` | "This may be stuck — running longer than the configured time limit + margin" | **Not proof of a dead task** — the backend's own design audit is explicit this is a heuristic, not a certainty; a legitimate retry-backoff sequence can also trigger it (Section 5.1) |
| Completed successfully | `sync_status: 'healthy'` or `'stale'` (both imply `checkpoint_status: 'ok'`) | "Last run completed" (`healthy`) vs. "Last successful run is older than expected" (`stale`) | Whether the *next* scheduled run will succeed |
| Failed | `sync_status: 'failed'` | "Last run ended in error" | The specific error cause — `last_error` is **never returned** by `SyncStatusView` (confirmed: absent from the response dict, `views.py:185-194`) or by any other frontend-facing endpoint; this is a genuine, permanent UNKNOWN from the frontend's vantage point, by the backend's own deliberate design ("never echoed back in the response", 13.A report Section 15) |
| Celery unavailable | `task-state`'s `reason: 'unavailable'` | "Could not confirm task state — Celery/Redis unreachable" | Whether the underlying reconciliation task itself is fine; this says nothing about `SyncCheckpoint` correctness (`RedisHealthView`-style scope separation) |
| Task state PENDING/ambiguous | `task-state`'s `task_state: 'PENDING'`, `note: PENDING_AMBIGUITY_NOTE` | Must not be rendered as "queued" or "running" — literally "ambiguous: may be queued, or Celery has never seen this task ID" | Which of the two is actually true — **provably undeterminable from this API alone** (backend's own documented limitation) |
| No task ID recorded | `task-state`'s `reason: 'no_task_id'` | "No Celery task was involved in the most recent run (management command, synchronous targeted run, or never reconciled)" | — |
| Manual recovery available | `possibly_stuck: true` AND `checkpoint_status: 'running'` | "An operator can mark this run as failed" | Whether doing so is the *correct* call for this specific stuck run — the backend's own Section 8 finding (correlation audit) is that even `last_run_task_id` cannot prove ownership under concurrency; recovery remains a human judgment call, not something the UI can validate for the operator |

**Deliberately no invented "healthy" top-level state** — matching the
task's own Step 7 instruction. `sync_status: 'healthy'` is the closest
existing concept, and even that is itself already a heuristic
(`_derive_sync_status()`'s threshold-based `STALE_THRESHOLD_MULTIPLIER`
comparison, not a proof of correctness) — the UX model does not
strengthen that framing, only reuses it as-is.

---

## 9. Recommended Minimal Implementation Scope

**Not implemented — recommendation only, per the strict stop
condition.**

A minimal, low-risk Phase 13.B, if pursued, consists of exactly two
additive pieces, both riding existing patterns rather than introducing
new ones:

1. **Surface `possibly_stuck` in the existing `InboxPage.tsx` badge**
   (Section 4) — add the field to the `SyncStatus` type, extend the
   status-mapping logic to special-case `running + possibly_stuck`,
   reuse the existing `warning` tone. Zero new polling, zero new
   component, zero new dependency.
2. **A single admin-gated "Recovery" affordance**, shown only when
   `possibly_stuck === true` (Section 6.5), behind
   `ConfirmDialog` (Section 6.3), calling the existing
   `POST /api/sync/recover/<session>/` endpoint, followed by a
   `getSyncStatus` refetch (Section 6.7). Natural placement: the same
   `InboxPage.tsx` header area, or (this audit's mild preference, not
   escalated as it's cosmetic) a small "Reconciliation" section on
   `SessionsPage.tsx`, which already has the project's only existing
   destructive-confirm precedent (Stop/Logout) and is already framed
   around session-level operational controls rather than message
   content — keeping conversation UI (`InboxPage`) focused on messages,
   and operational controls (`SessionsPage`) focused on
   session/reconciliation state. **This placement choice is cosmetic,
   not escalated.**

**Explicitly not part of the minimal scope** (optional, Section 11, or
out of scope entirely, Section 12):
- Celery task-state detail view (Section 5) — genuinely useful but
  materially larger (new type, new API helper, new admin-only
  component, careful ambiguity-safe copywriting) and not required to
  make `possibly_stuck` actionable, since Phase 13.A's recovery flow
  already works without it (13.A's own view never reads task state).
- `trigger_source` display — requires a backend response-shape addition
  first (Section 5.3), which is outside a UI-only task's scope.
- Any polling of `task-state` or `recover` — never recommended
  (Sections 5.6, and recovery is user-invoked, not polled, by
  definition).

---

## 10. Required Files (IF implemented — nothing was modified)

For the minimal scope (Section 9):

- **`frontend/src/lib/djangoApi.ts`** — add `possibly_stuck: boolean`
  (and, to keep the type accurate, `last_webhook_received_at: string | null`)
  to `SyncStatus`; add a `recoverSyncCheckpoint(session)` function
  (`POST /api/sync/recover/${session}/`, `authHeader()`, no body,
  matching every existing mutation helper's shape in this file).
- **`frontend/src/components/ui/StatusBadge.tsx`** — extend
  `mapSyncStatus` (or add a small adjacent helper) to consider
  `possibly_stuck` alongside `sync_status`.
- **`frontend/src/pages/InboxPage.tsx`** — pass `possibly_stuck` into
  the badge mapping call (one-line change at the existing call site,
  line ~312).
- **Wherever the recovery button/`ConfirmDialog` is placed**
  (`InboxPage.tsx` or `SessionsPage.tsx`, Section 9) — new local
  state (`busy`/`confirmOpen`/`feedback`, mirroring
  `SessionsPage.tsx`'s existing `ActionFeedback` pattern verbatim)
  and JSX for the button + `ConfirmDialog` + post-action refetch.

---

## 11. Optional Files (IF a fuller scope is later chosen — not required for the minimal recommendation)

- **`frontend/src/lib/djangoApi.ts`** — a `getSyncTaskState(session)`
  function + `SyncTaskState` type for
  `GET /api/sync/task-state/<session>/`, if task-state detail is
  pursued (Section 5).
- **A new, dedicated diagnostic component** (e.g. a collapsible
  "Diagnostics" panel/`Modal`) — reuses `Modal.tsx`, `LoadingState.tsx`,
  `ErrorState.tsx` verbatim; the only genuinely new piece would be its
  own PENDING-ambiguity-aware copy (Section 5.1), which cannot be
  auto-generated from any existing mapper.
- **`backend/apps/sync/views.py`** — only if `trigger_source` display
  is pursued (Section 5.3), a one-field addition to
  `SyncCheckpointTaskStateView`'s response dict — a backend change, so
  outside a frontend-only task's normal scope, named here only because
  it is a prerequisite for that specific optional UI piece.
- **A frontend scope-check utility** (e.g. `lib/scopes.ts`, a single
  exported `hasScope(claims, name)` helper) — mildly nicer than an
  inline `claims?.scopes.includes(...)` at each of the (at most two)
  call sites this task would introduce; not required for two call
  sites, worth it only if a third admin-gated UI element appears later.

---

## 12. Files That Must Not Change

Per the task's own scope boundary and this audit's own findings:

- `backend/apps/sync/reconciliation.py`, `tasks.py`, `executors.py`,
  `models.py` — no reconciliation logic, schema, or execution-path
  change of any kind; every capability this audit evaluates already
  exists and is already correct per the three prior related design
  audits (possibly-stuck detection, recovery, task correlation).
  `_is_possibly_stuck()` and `SyncCheckpointRecoveryView`'s
  compare-and-set logic (`backend/apps/sync/views.py`) must not be
  touched — the frontend must consume, never reimplement, that
  threshold/CAS logic (Section 6.5).
- `backend/apps/authn/permissions.py` — `HasSystemAdministrationScope`
  already exists and is sufficient; no new permission class or scope
  name.
- `backend/apps/audit/models.py` — `AuditLog`'s five-field shape is
  already sufficient (Section 6.8); no metadata/JSON field addition.
- Any migration file.
- Any Docker/Compose/`.env`/CI file.
- `bff/` — confirmed (Section 2.1) to have no role in this data path
  and none is proposed.
- Any dependency manifest (`package.json`, `requirements*.txt`) — every
  recommendation in Section 9 reuses already-installed libraries and
  already-existing local components.

---

## 13. Verification Plan (for a future implementation task, not performed here)

If Section 9's minimal scope is implemented:

1. **Backend regression**: `python manage.py test` — must remain
   318/318 (or higher, if new backend tests are added for an optional
   `trigger_source` field) with zero change to existing test outcomes,
   since no backend file in the minimal scope is touched at all.
2. **Frontend type-check/build**: `npm run build` (or equivalent) in
   `frontend/` — the added `possibly_stuck` field is additive to an
   existing interface, so this should be a mechanical, low-risk check.
3. **Manual/API-level verification of the new UI's calls** (once a dev
   stack is available): confirm the recovery button only renders when
   `possibly_stuck === true`; confirm a `409 concurrent_state_change`
   renders via the existing `ErrorState`; confirm a successful recovery
   triggers a `getSyncStatus` refetch and the badge updates without a
   manual page reload; confirm a non-admin JWT (no `system
   administration` scope) never sees the recovery control, and that a
   direct API call from such a session still correctly receives `403`
   (defense-in-depth check — the button being hidden must not be the
   *only* thing preventing the action).
4. **No live verification was possible during this audit** — consistent
   with the 13.A implementation report's own Section 14, the Office-side
   stack (Django/Celery/Redis) was not confirmed running and was not
   started for this task (per this task's own explicit prohibition on
   starting/restarting the stack).

---

## 14. User Decisions Required

Per the task's own escalation bar (architecture/security only —
cosmetic decisions, e.g. exact button placement or copy wording beyond
Section 6.4's safety-relevant content, are **not** escalated):

1. **Whether a frontend recovery control should be built at all**
   (Section 6.1) — this audit finds it would make Phase 13.A
   meaningfully more usable for a non-engineer operator, but building
   the *first-ever* UI trigger for a destructive, audit-logged,
   scope-gated backend action is a product/risk decision this audit
   does not consider itself authorized to make unilaterally, even
   though the endpoint itself is already fully implemented and safe.
2. **Whether Celery task-state detail (Section 5) should be built now,
   deferred, or skipped** — it is genuinely useful decision support but
   is not required to make `possibly_stuck` + recovery usable end to
   end; deferring it does not block Section 9's minimal scope.
3. **Whether `last_run_trigger_source` should be added to
   `SyncCheckpointTaskStateView`'s response** (Section 5.3) — this is a
   small **backend** change (not covered by a frontend-only task) that
   would need its own, separate, explicit approval before any
   implementation task touches `backend/apps/sync/views.py` again.
4. **Whether `InboxPage.tsx` or `SessionsPage.tsx` is the right home**
   for the recovery control (Section 9) — flagged as this audit's mild
   preference for `SessionsPage.tsx`, but treated as cosmetic and not
   formally escalated; included here only so the choice is visible
   before implementation, not because it requires a security/architecture
   ruling.

**Not escalated** (cosmetic, per the task's own instruction): exact
badge color/icon choice beyond reusing the existing `warning` tone,
exact confirmation-dialog copy beyond Section 6.4's safety-relevant
content, exact component file/function naming.

---

## 15. Risks and Limitations

- **This audit did not run the frontend or backend dev stack** — no
  browser automation tool was used, and none of this report's findings
  rest on a live-rendered page; every claim about current UI state is
  based on direct source reading (Sections 2-3), not observed runtime
  behavior. Explicitly: **no browser verification was performed.**
- **`possibly_stuck`'s own known limitation (heuristic, not proof)
  carries forward unchanged into any UI that displays it** — the
  660-second threshold can false-positive under a legitimate
  Celery retry-backoff sequence (Section 5.1, correlation audit
  Section 7); any UI copy must avoid asserting certainty the backend
  itself does not claim.
- **`last_run_task_id` cannot prove ownership of the current `RUNNING`
  state under concurrency** (Section 5, correlation audit Section 6) —
  a task-state UI, if built, must not present a `SUCCESS`/`FAILURE`
  Celery state for that ID as proof the checkpoint's *current* status
  is explained by it; the backend's own docstring already warns of
  this, and the UI must not silently drop that warning through a
  simplified rendering.
- **This audit's file-impact estimates (Sections 10-11) are
  reasoned from the existing patterns, not from an actual
  implementation attempt** — real effort could differ once a developer
  touches the exact styling/CSS module conventions each page uses
  (`*.css` files per page, BEM-ish class naming) not itself audited in
  detail here beyond confirming their existence.
- **No test framework change was evaluated as unnecessary because none
  is proposed** — this audit did not investigate whether a frontend
  test framework exists at all (out of this audit's necessary scope,
  since Section 9's recommendation explicitly rules out adding one).

---

## 16. Final Recommendation

Build the minimal scope in Section 9 **once Section 14's decisions are
made**, specifically decision 1 (whether a recovery UI is wanted at
all) — everything else in Section 9 is comparatively low-risk and
consistent with existing patterns. Do **not** build Celery task-state
detail or `trigger_source` display as part of a first pass; both are
genuinely useful but are optional decision-support layers on top of a
system (Phase 13.A) that already works correctly without them. Do not
introduce any new polling loop, JWT scope, dependency, or backend
schema change for this UI work. The frontend's existing patterns
(`StatusBadge`, `ConfirmDialog`, `useApiQuery`/refetch,
`ApiError`/`ErrorState`) are sufficient to build the minimal scope
without inventing new infrastructure — the one genuinely new pattern
required is client-side JWT-scope-based UI hiding (Section 7), which
does not exist anywhere in this codebase today and should be kept as
small and boring as possible (a single inline check) rather than
generalized ahead of an actual second use case.

**STOP.** This was a design audit only. No frontend or backend source
file was modified. No migration, Docker, or configuration file was
touched. No container was started or restarted. No reconciliation was
triggered. No write endpoint (including `POST /api/sync/recover/...`)
was called. No Celery task was called. The only artifact produced by
this task is this report. Awaiting the user's decisions in Section 14
before any implementation task proceeds.
