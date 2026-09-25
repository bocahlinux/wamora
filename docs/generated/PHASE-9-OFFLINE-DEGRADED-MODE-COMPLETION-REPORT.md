# Phase 9 (Offline/Degraded Mode) — Completion Report

## 1. Objective

Close the two gaps identified by
`docs/generated/PHASE-ROADMAP-STATUS-AUDIT-REPORT.md` as keeping roadmap
Phase 9 ("Offline/degraded mode", `docs/15-CODING-PHASES.md`) at
**PARTIAL** instead of **COMPLETE**, quoted verbatim from that report's
Section 3 (Phase 9 row):

> "`SessionsPage.tsx` has **zero** matches for `ConnectivityIssue`/
> `reportPollOutcome` (grepped this task) — the Inbox's degraded-mode
> pattern was never extended there, and `DashboardPage.tsx` has zero
> matches for `getSyncStatus`/`SyncStatus` — no reconciliation-health card
> on the Dashboard."

This was a frontend-only, additive task: reuse the existing, already-proven
`InboxPage.tsx` pattern (connectivity indicator; `StatusBadge`/
`getSyncStatus`/`possibly_stuck`/admin-gated recovery) in the two places it
was missing. No backend, BFF, or Blast code was touched, and no new
backend endpoint was added — `getSyncStatus` and `recoverSyncCheckpoint`
(`frontend/src/lib/djangoApi.ts`) already existed and were reused verbatim.

## 2. Step 1 Findings (source read before implementing)

- **`frontend/src/pages/InboxPage.tsx`** (575 lines, read in full) —
  confirmed the reference pattern: a page-local `ConnectivityIssue =
  'unreachable' | 'unauthorized'` union fed by a `reportPollOutcome()`
  function with a `CONNECTIVITY_FAILURE_THRESHOLD = 2` (2 consecutive
  non-auth failures before showing a banner; immediate for
  `unauthorized`/`forbidden`; deliberately excludes first-load queries
  with their own `ErrorState` + retry, and excludes write actions with
  their own feedback UI); a `fetchSyncStatus` `useCallback` + a
  `SYNC_STATUS_POLL_MS = CHAT_LIST_POLL_MS * 4 = 32000` `setInterval`
  effect; a `possibly_stuck` warning chip (`TriangleAlert` icon,
  `.wa-inbox__sync-stuck` CSS) with an admin-gated
  (`claims?.scopes.includes('system administration') ?? false`) recovery
  button wired to a `ConfirmDialog` and `recoverSyncCheckpoint()`.
- **`frontend/src/pages/DashboardPage.tsx`** (original 261 lines, read in
  full) — confirmed it had zero `getSyncStatus`/`SyncStatus` references.
  Structure: a Row 1 "system health" grid of generic `HealthCard`s
  (WAHA/Backend/PostgreSQL/Redis) and a Row 2 grid of richer
  `wa-metric-card`-styled cards (Messages, Activity, Sessions — the
  Sessions card already mirrors `SessionsPage.tsx`'s own
  `getSessionStatus`/`mapWahaStatus`). Row 2's card shape (icon badge,
  title + inline `StatusBadge`, then free-form body content) is exactly
  what a sync-status card with an extra warning chip and recovery button
  needs — a generic `HealthCard` (Row 1) could not have held that extra
  content cleanly.
- **`frontend/src/pages/SessionsPage.tsx`** (original 376 lines, read in
  full) — confirmed the audit's "zero" finding via re-grep this task; also
  found the *specific* mechanism of the silence: the post-mutation
  settle-poll (`runTick`, driven by `getSessionStatus` on a
  `POLL_INTERVAL_MS`/`POLL_MAX_TICKS` generation-guarded loop) had a
  failure branch that called `setIsSyncing(false); return;` with **no
  error surfaced at all** — a single transient blip during a sync-settle
  window silently abandoned the poll with zero user feedback. The page's
  *initial* `statusQuery` load already had its own `ErrorState` + manual
  retry (same exclusion Inbox makes for first-load queries), so that path
  was not the gap.
- **`frontend/src/lib/djangoApi.ts`** — confirmed `getSyncStatus`,
  `recoverSyncCheckpoint`, and the `SyncStatus` type (with
  `possibly_stuck: boolean` and `last_webhook_received_at: string | null`)
  are exactly as `InboxPage.tsx` uses them; reused verbatim, no
  duplication or fork of this file's logic, no new function added to it.
- **`frontend/src/lib/api.ts`** — confirmed the `ApiError`/`describeError()`
  taxonomy (`validation`/`unauthorized`/`forbidden`/`not_found`/
  `server_error`/`network_error`/`timeout`/`unknown`). Grepped the whole
  `frontend/src` tree for `network_error`/`ConnectivityIssue`/
  `reportPollOutcome`: only `InboxPage.tsx` (the pattern) and `api.ts`
  (the taxonomy's own definition) matched — confirming no other page had
  any connectivity-specific handling to reuse or be consistent with
  besides Inbox's.

## 3. Step 2 — Design Decisions

### 3.1 Shared hook vs. duplication (explicit call, as required)

**Decision: duplicate, not extract.** A ~25–30 line block (fetch +
`never_synced`-fallback-on-404 + poll interval + recovery
confirm/submit/feedback) is now present in both `InboxPage.tsx` (unchanged)
and the new `SyncStatusCard` in `DashboardPage.tsx`.

Reasoning:
- Inbox's version is **entangled** with its own connectivity-indicator
  signal (`fetchSyncStatus` calls `reportPollOutcome()` on every result,
  sharing state with the chat-list/messages polls). Extracting a clean
  `useSyncStatus()` hook would have required either (a) baking a
  connectivity callback into the hook's API — a leaky, feature-specific
  abstraction for a "sync status" hook — or (b) leaving Inbox's own
  connectivity wiring untouched but partially reimplemented alongside the
  new hook, which risks the exact behavior drift the task explicitly
  warned against ("does not change `InboxPage.tsx`'s existing behavior").
- The task's own instructions explicitly sanctioned this fallback:
  "duplicating the same ~20-30 lines of fetch/poll logic in two places is
  an acceptable, safer alternative if extraction feels risky."
- No third consumer exists yet, so there is no immediate reuse pressure
  beyond these two call sites.
- The poll cadence was kept identical by literal value
  (`SYNC_STATUS_POLL_MS = 32000` in `DashboardPage.tsx`, matching Inbox's
  `CHAT_LIST_POLL_MS * 4 = 8000 * 4 = 32000`), with a comment explaining
  the value is the same as Inbox's rather than re-derived from a
  Dashboard-local constant that doesn't otherwise exist. `InboxPage.tsx`
  itself was **not modified** — zero risk to its already-verified
  behavior.

If a third page ever needs this pattern, extracting `useSyncStatus()` at
that point (three call sites, not two) would be a much safer, higher-value
refactor than doing it now for two.

### 3.2 Dashboard: what the sync-status card shows

A new `SyncStatusCard` component, placed as a fourth card in the existing
Row 2 grid (`wa-metric-card` shape, matching `MessagesCard`/`ActivityCard`/
`SessionsCard`), showing:
- Title "Reconciliation Sync" + `StatusBadge` (`mapSyncStatus`, same
  vocabulary as Inbox — "Synced"/"Syncing"/"Sync delayed"/"Sync
  error"/"Not synced").
- A one-line human-readable detail (`describeSyncDetail()` — "Last run N
  minutes/hours ago", or the `never_synced`/waiting-for-first-run cases),
  matching the one-line detail convention every other Row 1/2 card
  already uses (`query.data.detail`, `query.data.session`, "Hourly trend
  (UTC)", etc.).
- The same `possibly_stuck` warning chip (`TriangleAlert`, same copy) and
  the same admin-gated ("system administration" scope) recovery button →
  `ConfirmDialog` → `recoverSyncCheckpoint()` → refetch, as Inbox — laid
  out stacked (column) rather than Inbox's side-by-side row, since a
  ~260px-wide card is narrower than Inbox's full-width page banner.
- Deliberately does **not** duplicate a connectivity/"unreachable" signal
  — the Dashboard's Row 1 health cards already generically cover
  backend/BFF unreachability; this card is scoped purely to reconciliation
  data freshness, matching `mapSyncStatus`'s own documented discipline
  ("never says offline/disconnected here").

### 3.3 Sessions: what "connectivity issue" means on this page

Added the same `ConnectivityIssue` type, `CONNECTIVITY_FAILURE_THRESHOLD`,
and `reportPollOutcome()` function as Inbox (page-local duplicate, same
reasoning as 3.1 — different loop lifecycle, see below), fed **only** by
the settle-poll (`runTick`), and **not** by the initial `statusQuery` load
or by any write action (start/stop/restart/logout/pairing) — mirroring
Inbox's own exclusions exactly (first-load queries and write actions
already have their own `ErrorState`/`ActionFeedback`).

One behavioral fix was required to make this meaningful: `runTick`
previously **stopped polling outright** on the first failed
`getSessionStatus` call, so a threshold of 2 could never be reached — the
loop would never fire a second time to accumulate a second failure. This
was changed so a failed tick now reports the outcome (feeding the
connectivity banner) and **keeps retrying**, still bounded by the
pre-existing `ticksLeft`/`POLL_MAX_TICKS` (~30s) ceiling — never spins
forever, no new interval or budget was invented. This is the minimal fix
that makes "connectivity-issue handling" actually observable on this page:
previously a transient blip during a sync-settle window silently abandoned
the poll with zero feedback; now it shows the same
"Can't reach the server… showing the last known status" chip Inbox users
already see, and keeps trying within the existing budget.

No shared hook was extracted here either, for the same reason as 3.1: the
two pages' repeating-request loops have materially different lifecycle
mechanics (Inbox's are plain, unconditional `setInterval`s; Sessions'
`runTick` is a generation-guarded, self-terminating, settle-detecting
recursive `setTimeout` chain) — forcing them into one shared implementation
would be a larger, riskier change for a small, page-local win. The `type`
and threshold constant are duplicated (a few lines), with a comment cross-
referencing Inbox's identical values.

No genuine ambiguity requiring a "USER DECISIONS REQUIRED" stop was found —
both gaps were resolvable by extending the existing frontend pattern, per
the task's own expectation.

## 4. Step 3 — What Was Built

### `frontend/src/pages/DashboardPage.tsx`
- Added imports: `useCallback`/`useEffect`/`useState` (react),
  `RefreshCw`/`TriangleAlert` (lucide-react), `Button`, `ConfirmDialog`,
  `mapSyncStatus`, `ApiError` type, `getSyncStatus`/`recoverSyncCheckpoint`/
  `SyncStatus` type from `djangoApi.ts`, `useAuth`.
- Added `SYSTEM_ADMINISTRATION_SCOPE`, `SYNC_STATUS_POLL_MS`,
  `SYNC_STATUS_LABEL`, `describeSyncDetail()`.
- Added `SyncStatusCard` component (fetch/poll/recovery logic as described
  in 3.1/3.2).
- Mounted `<SyncStatusCard sessionName={sessionName} />` as the fourth card
  in the existing Row 2 `<section className="wa-dashboard__row2">`.

### `frontend/src/pages/DashboardPage.css`
- Added `.wa-metric-card__sync-stuck`, `.wa-metric-card__sync-stuck-text`,
  `.wa-metric-card__sync-recovery-feedback(--success)` — same warning-chip
  visual formula as `InboxPage.css`'s `.wa-inbox__sync-stuck`, adapted to a
  stacked (not side-by-side) layout for the narrower card.

### `frontend/src/pages/SessionsPage.tsx`
- Added `LogIn`/`WifiOff` icon imports.
- Added `CONNECTIVITY_FAILURE_THRESHOLD`, `ConnectivityIssue` type,
  `connectivityIssue`/`connectivityFailureCountRef` state, and
  `reportPollOutcome()` — page-local duplicate of Inbox's function.
- Modified `runTick`'s failure branch: now calls `reportPollOutcome(result)`
  and retries (bounded by existing `ticksLeft`) instead of silently
  stopping; also added `reportPollOutcome(result)` to the success branch
  (resets the indicator, mirrors Inbox).
- Added a connectivity banner (`<p className="wa-session-connectivity">`,
  `WifiOff`/`LogIn` icons, same copy style as Inbox's) rendered directly
  under `PageHeader`.

### `frontend/src/pages/SessionsPage.css`
- Added `.wa-session-connectivity` — same warning-chip visual formula as
  `InboxPage.css`'s `.wa-inbox__connectivity`.

No changes were made to `frontend/src/lib/djangoApi.ts`, `api.ts`,
`bffApi.ts`, `StatusBadge.tsx`, or any other shared file — every reused
piece (types, functions, components) was consumed as-is.

## 5. Verification

- **`npm run lint`** (oxlint) — clean. The only warnings reported are 7
  pre-existing `react(only-export-components)`/`react(set-state-in-effect)`
  warnings in `AuthContext.tsx`, `StatusBadge.tsx`, and `ThemeContext.tsx`
  — none of these files were touched by this task, and none of the warned
  lines are new.
- **`npm run build`** (`tsc -b && vite build`) — clean, zero TypeScript
  errors, build succeeded (`✓ built in 342ms`).
- No test framework exists in this project (confirmed by the task
  instructions, not re-verified independently here) — none was added.

## 6. Git Diff Summary

Files changed by this task (verified via `git diff --stat`, frontend only):
```
frontend/src/pages/DashboardPage.css   |  34 ++++
frontend/src/pages/DashboardPage.tsx   | 207 ++++++++++++++++++++-
frontend/src/pages/SessionsPage.css    |  16 ++
frontend/src/pages/SessionsPage.tsx    |  86 ++++++++-
```

**Note on unrelated pre-existing working-tree changes**: at the start of
this task, `git status` already showed a number of modified files outside
this task's scope — `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` and several
`docs/generated/NEXT-PHASE-*`/`PHASE-11-*`/`PHASE-13*` reports — plus an
untracked `docs/generated/PHASE-ROADMAP-STATUS-AUDIT-REPORT.md`. These are
the output of the parallel documentation-relabeling task referenced in this
task's own instructions (the "13.A"/"13.B" phase-labeling note). This task
did not create, edit, or revert any of them — they are pre-existing,
independent working-tree state, not part of this diff.

No file under `backend/`, `bff/`, `infrastructure/`, `apps/blast/`, any
`Blast*Page.tsx`/`BlastPage.css`, or any dependency manifest
(`package.json`, `package-lock.json`) was touched.

## 7. Phase 9 Status — Is It COMPLETE Now?

Per the roadmap audit's own Phase 9 criteria (Section 3): the two named
gaps — `SessionsPage.tsx` having zero connectivity-issue/degraded-mode
handling, and `DashboardPage.tsx` having no reconciliation sync-status card
— are both closed:

- `SessionsPage.tsx` now has a `ConnectivityIssue`/`reportPollOutcome`
  pattern (grep for these identifiers now matches this file, closing the
  audit's literal "zero matches" finding), with a genuine behavioral fix
  (the settle-poll no longer goes silent on a transient failure) making it
  observable in practice, not just present as dead code.
- `DashboardPage.tsx` now has a reconciliation sync-status card
  (`getSyncStatus`/`SyncStatus` now match, closing the audit's other
  "zero matches" finding), with the same `StatusBadge`/`possibly_stuck`/
  admin-gated-recovery vocabulary as Inbox, so the three frontend surfaces
  that show connectivity/sync state (Inbox, Dashboard, Sessions) are now
  consistent.

**Phase 9 (Offline/degraded mode) should now be considered COMPLETE**
per the roadmap audit's own stated criteria — it explicitly said Phase 9
was "functionally substantial but not fully and consistently applied
across all three frontend surfaces that show connectivity/sync state," and
named exactly these two gaps as the reason it was PARTIAL rather than
COMPLETE. Both are now closed, with no scope expansion beyond them.

This report does not re-litigate the audit's separately-noted, non-blocking
observations for Phase 9's lineage (e.g. `reconcile_session()`'s missing
`try/finally` around its fetch/parse/persist block, Section 3/Section 9
discrepancy #3 of the audit) — that is a `backend/apps/sync/` correctness
gap explicitly out of this task's scope ("Do NOT change the
reconciliation/`possibly_stuck` backend logic itself"), and the audit
itself frames it as an existing, independently-mitigated (not blocking)
gap in Phase 4/9's lineage, not one of the two gaps this task was scoped
to close.

## 8. Explicit Stop

Implementation, verification, and this report are complete. Per the task's
stop condition, no further phase (Phase 12 — Security hardening, or any
other) was started.
