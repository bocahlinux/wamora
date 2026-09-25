# Phase 9.1E — Frontend Sync Status Integration — Implementation Report

**Scope of this task.** Frontend implementation only, exactly the slice
scoped as "Phase 9.1E" in `docs/generated/PHASE9-1E-DESIGN-AUDIT-REPORT.md`.
No backend file was touched (Phase 9.1A's endpoint, `SyncCheckpoint`,
`reconcile_session()`, Celery, Redis, webhook ingestion, WAHA client,
Session Management, and backend authentication are all unread-for-editing
this task). `SyncCheckpoint.lag_seconds`, Redis health, Celery worker
health, webhook heartbeat, and stuck-running detection were not activated —
none of them are referenced anywhere in this change. No live WhatsApp
message was sent, no write endpoint was called, no `.env`/config/database
was touched. Phase 9.1B/C/F/G and Phase 11 were not started.

**Path correction, noted rather than treated as scope creep**: the task
named `frontend/src/api/djangoApi.ts` and
`frontend/src/components/StatusBadge.tsx`. The actual, only matching files
in the repository are `frontend/src/lib/djangoApi.ts` and
`frontend/src/components/ui/StatusBadge.tsx` (confirmed via a repo-wide
search before editing — no other candidates exist). These are
unambiguously the same files the task meant; the three files actually
changed are exactly the three the task listed under "scope discipline," at
their real paths.

---

## 1. What was implemented

`GET /api/sync/status/<session_name>/` (Phase 9.1A, unchanged, not
touched) is now consumed by `InboxPage.tsx`: a compact `StatusBadge`
appears in the Inbox page header showing the current session's sync
health, polled independently on its own cadence, sharing the existing
Phase 9.1D connectivity mechanism for connectivity-class failures, and
never confusing sync freshness with WhatsApp/connectivity state.

---

## 2. Files changed

| File | Change |
|---|---|
| `frontend/src/components/ui/StatusBadge.tsx` | Added `mapSyncStatus(raw: string \| undefined): StatusKind` — a new mapper, mirroring `mapWahaStatus`/`mapActivityResult`'s exact existing shape (a `switch`, `default: return 'unknown'`). No new `StatusKind` values, no new CSS. |
| `frontend/src/lib/djangoApi.ts` | Added `SyncStatus` interface (mirrors the backend response verbatim) and `getSyncStatus(session)`, following the exact style of every existing function in this file (`request<T>(url, {headers: authHeader()})`). |
| `frontend/src/pages/InboxPage.tsx` | Added: `SYNC_STATUS_POLL_MS` constant, `SYNC_STATUS_LABEL` lookup, `syncStatus` state, one new polling `useEffect`, two new `reportPollOutcome(result)` call sites inside that effect, and one new `actions` prop on the existing `<PageHeader>` call. |

No other file was touched — confirmed by `git diff --stat` (Section 9).
`backend/config/urls.py` and `frontend/src/pages/InboxPage.css` show as
modified in `git status` only because they are Phase 9.1A's and Phase
9.0/9.1D's own already-completed, already-reported, unmodified-by-this-task
changes, uncommitted from before this task started.

---

## 3. Design decisions carried from the design audit, and one implementation-time refinement

Every decision in `docs/generated/PHASE9-1E-DESIGN-AUDIT-REPORT.md` was
followed as written, with one deliberate, documented refinement:

- **Refinement**: the design report's Section 5 described mirroring the
  chat-list loop's exact two-part shape (`useApiQuery` for first load +
  a separate `setInterval` for ongoing polling). On implementation, this
  was simplified to **one** effect (an immediate fetch plus its own
  `setInterval`), because `useApiQuery`'s first-load split exists
  specifically to drive a `LoadingState`/`ErrorState` — and the design's
  own Section 3 already decided sync status needs neither ("not yet
  fetched" renders nothing). Using `useApiQuery` here would have added a
  loading/error branch this feature was designed not to have. This is
  noted explicitly as a refinement of *implementation shape*, not a
  deviation from the design's actual intent (which loop timing to attach
  to, Section 5's real point) or from any of its stated behavior
  requirements.
- Everything else — `StatusBadge` reuse, the `mapSyncStatus()` shape, the
  `CHAT_LIST_POLL_MS * 4` interval, always-visible-but-compact placement,
  global (not per-conversation) scope, the 404-as-`never_synced`
  treatment, and the exact label wording — was implemented exactly as
  proposed.

---

## 4. Mapping: backend `sync_status` → `StatusBadge`

```ts
export function mapSyncStatus(raw: string | undefined): StatusKind {
  switch (raw) {
    case 'healthy': return 'healthy';
    case 'running': return 'syncing';
    case 'stale': return 'warning';
    case 'failed': return 'error';
    case 'never_synced': return 'unknown';
    default: return 'unknown';
  }
}
```

| `sync_status` | `StatusKind` | Tone | Label shown |
|---|---|---|---|
| `healthy` | `healthy` | success | "Synced" |
| `running` | `syncing` | info | "Syncing" |
| `stale` | `warning` | warning | "Sync delayed" |
| `failed` | `error` | error | "Sync error" |
| `never_synced` | `unknown` | neutral | "Not synced" |
| *(unrecognized string)* | `unknown` (via `default`) | neutral | *(not reachable via `SYNC_STATUS_LABEL`, which is typed over the known union — see Section 8)* |

No label anywhere says or implies "WhatsApp offline," "disconnected," or
"unavailable" — every label is scoped strictly to sync/data freshness, per
the task's explicit instruction and its example do/don't list.

---

## 5. Polling behavior

- `SYNC_STATUS_POLL_MS = CHAT_LIST_POLL_MS * 4` = **32 000 ms (~32s)** —
  computed, not a new independent literal.
- A single `useEffect`, keyed on `[sessionName]`:
  - Resets `syncStatus` to `null` immediately whenever `sessionName`
    changes (satisfies "status lama jangan terbawa ke session baru" —
    though `config.wahaSessionName` is a static build-time value in this
    app today, so this branch is defensive, not exercised in practice).
  - If there's no configured session, the effect returns without
    scheduling anything — no interval, no request, nothing to clean up.
  - Otherwise: fetches once immediately, then every `SYNC_STATUS_POLL_MS`
    via `setInterval`.
  - Cleanup: `return () => clearInterval(interval)` — React runs this
    automatically both on unmount and immediately before the effect
    re-runs on a `sessionName` change, so there is exactly one live
    interval for this concern at any time; no duplicate timers, no leak.
- This is a **third**, fully independent polling loop — it does not
  piggyback on the chat-list (`CHAT_LIST_POLL_MS`) or messages
  (`MESSAGES_POLL_MS`, `selectedChatId`-gated) loops, and has no
  dependency on which chat (if any) is selected.

---

## 6. 404 behavior

A `getSyncStatus()` result with `error.kind === 'not_found'` is handled in
its own branch, **before** falling through to the generic
connectivity-class branch:

```ts
if (result.error.kind === 'not_found') {
  setSyncStatus({
    session: sessionName,
    sync_status: 'never_synced',
    checkpoint_status: null,
    last_run_at: null,
    seconds_since_last_run: null,
    checkpoint_updated_at: null,
  });
  return; // never reaches reportPollOutcome
}
```

This is **not** fed into `reportPollOutcome()` — a 404 here means "Django
has never heard of this session name," not "Django is unreachable"; the
badge instead shows the same "Not synced" label a known-but-never-reconciled
session would show. The connectivity banner never fires for this case.

---

## 7. Integration with `reportPollOutcome()` (Phase 9.1D)

**No new connectivity-tracking state was created.** The existing
`connectivityIssue`/`connectivityFailureCountRef`/`reportPollOutcome()`
(all defined once, unmodified in shape or logic) now has a **third** call
site:

```ts
async function fetchSyncStatus() {
  const result = await getSyncStatus(sessionName);
  if (result.ok) {
    setSyncStatus(result.data);
    reportPollOutcome(result);          // success -> resets the shared signal
    return;
  }
  if (result.error.kind === 'not_found') {
    setSyncStatus({ ...synthetic never_synced... });
    return;                              // deliberately skips reportPollOutcome
  }
  reportPollOutcome(result);             // auth/network/timeout/server_error/unknown
}
```

- **Success** → `reportPollOutcome(result)` contributes a "connectivity is
  fine" signal, exactly as a successful chat-list/messages tick already
  does — one shared signal, not a duplicate.
- **`not_found`** → excluded, per Section 6.
- **Every other failure kind** (`unauthorized`, `forbidden`,
  `network_error`, `timeout`, `server_error`, `unknown`) → fed into the
  same shared function, same threshold (`CONNECTIVITY_FAILURE_THRESHOLD = 2`),
  same resulting banner (`InboxPage.tsx`'s existing
  `connectivityIssue`-driven `<p>`, unmodified). **No second banner exists
  or was added.**

---

## 8. Behavior during a connectivity failure

`syncStatus` is **never** cleared or overwritten on a connectivity-class
failure — the failing branch calls only `reportPollOutcome(result)` and
returns, leaving whatever `syncStatus` already held untouched. The badge
therefore keeps showing its last successfully-fetched value while the
existing connectivity banner (unchanged) communicates that the page can't
currently reach the server — the same "freeze, don't blank" discipline the
chat list and messages panes already use, applied consistently to a third
data source.

**Unrecognized backend value, defensively handled at two layers**:
`mapSyncStatus()`'s `default: return 'unknown'` (Section 4) prevents a
crash or a blank badge if the backend ever returns a `sync_status` string
outside the five documented values. `SYNC_STATUS_LABEL` itself is typed as
`Record<SyncStatus['sync_status'], string>` — TypeScript's own known-union
type, matching the interface `getSyncStatus()` already declares — so this
was verified by the compiler to be exhaustive over every value the
frontend's own type system expects; an actually-unrecognized *runtime*
string (a value TypeScript can't see, e.g. a hypothetical new backend
state) would only reach `mapSyncStatus()`'s already-safe fallback for the
badge's tone/icon — the label lookup itself is only ever indexed by values
this effect explicitly constructs (either the typed response or the
synthetic `never_synced` object), so it cannot throw.

---

## 9. Verification results

- **`npm run build`** (`tsc -b && vite build`): **passed**, zero
  TypeScript errors — `✓ 1950 modules transformed`, `✓ built in 631ms`.
- **`npm run lint`** (`oxlint`): **passed**. Output shows **6** warnings,
  one more than the 5 present immediately before this task
  (`StatusBadge.tsx:74:17`, `react(only-export-components)`). This is
  **not a new category of issue** — it is the exact same warning class
  already present on the two sibling functions in the same file
  (`mapWahaStatus` at line 48, `mapActivityResult` at line 97 in the
  updated file — both pre-existing, both already warned about before this
  task), now also reported for the new, identically-shaped `mapSyncStatus`.
  No `InboxPage.tsx` or `djangoApi.ts` warning was introduced.
- **`git status --short`**:
  ```
   M backend/config/urls.py
   M frontend/src/components/ui/StatusBadge.tsx
   M frontend/src/lib/djangoApi.ts
   M frontend/src/pages/InboxPage.css
   M frontend/src/pages/InboxPage.tsx
  ?? backend/apps/sync/... (Phase 9.1A, unchanged by this task)
  ?? docs/generated/... (this report and prior Phase 9 reports)
  ```
- **`git diff --stat`** for the three files this task actually edited:
  ```
   frontend/src/components/ui/StatusBadge.tsx |  26 ++++
   frontend/src/lib/djangoApi.ts              |  23 ++++
   frontend/src/pages/InboxPage.tsx           | 207 ++++++++++++++++++++++++++---
   3 files changed, 238 insertions(+), 18 deletions(-)
  ```
  `backend/config/urls.py` and `InboxPage.css` are **not** part of this
  task's diff — both are Phase 9.1A's and Phase 9.0/9.1D's own prior,
  uncommitted work, confirmed unread-for-editing this task.
- **Live browser testing**: not performed — the task's own instruction
  says this is not required when the environment isn't available for it,
  and no attempt was made to fabricate or imply one. No WhatsApp message
  was sent, no write endpoint was called.

---

## 10. Regression check — behavior confirmed unchanged

Verified by inspection of the diff itself (every line below is either
untouched or additive-only):

- **Chat list polling**: the only change inside its interval callback is
  one added line, `reportPollOutcome(result)`, after the existing
  `if (result.ok) setChats(...)` — that line itself is untouched (it was
  already present from Phase 9.1D, re-confirmed by reading the file before
  this task's edits began).
- **Message polling**: identical situation — no line inside its callback
  was modified; nothing new was added to it by this task (its own
  `reportPollOutcome(result)` call site is Phase 9.1D's, not new here).
- **Send message / Phase 9.0's unknown-send warning**: `handleSend()`,
  `SendFeedback`, and the composer's render block are **byte-for-byte
  unchanged** — confirmed absent from this task's actual edits (only
  visible in the cumulative `git diff` as prior, already-reported Phase
  9.0 content).
- **Phase 9.1D's connectivity indicator**: `connectivityIssue`,
  `connectivityFailureCountRef`, and `reportPollOutcome()`'s own internal
  logic are **unmodified** — this task only added new *callers* of the
  existing function, never changed its behavior, its threshold, or its
  rendered banner.
- **Mark as read**: `handleSelectChat()` — untouched, not referenced
  anywhere in this task's changes.
- **Session selection / Session Management**: not applicable/untouched —
  this frontend has no runtime session-selection concept, and
  `SessionsPage.tsx`/`.css` were not opened by this task.

---

## 11. What was deliberately NOT touched

- Any backend file — `apps/sync/views.py`, `apps/sync/models.py`,
  `apps/sync/reconciliation.py`, `apps/sync/executors.py`,
  `apps/sync/tasks.py`, Celery/Redis config, webhook ingestion, the WAHA
  client, Session Management, backend authentication — none opened.
- `SyncCheckpoint.lag_seconds` — never referenced (the backend endpoint
  itself already excludes it; the frontend consumes only the fields the
  endpoint actually returns).
- Redis health check, Celery worker health check, webhook heartbeat,
  stuck-running detection — none exist anywhere in this change; the
  `StatusBadge`/label vocabulary used here is scoped strictly to the five
  documented `sync_status` values.
- `CHAT_LIST_POLL_MS`, `MESSAGES_POLL_MS` — both untouched; only a new,
  independent constant (`SYNC_STATUS_POLL_MS`) derived from the former.
- Any new CSS file or rule — `StatusBadge`/`Badge`'s existing styles cover
  every tone this feature needs; `PageHeader`'s already-existing,
  previously-unused `actions` prop was used for placement, requiring no
  markup or CSS change to `PageHeader` itself.
- No frontend test file was created — no test infrastructure exists in
  this project (re-confirmed, unchanged), and none was added merely to
  satisfy this task.

---

This implementation is complete: `StatusBadge` mapper + API client
function + `InboxPage.tsx` integration, verified via build/lint, scoped to
exactly the three intended files. Stopping here, per instruction — not
proceeding to Phase 9.1B/C/F/G, Phase 11, or any additional refactor.
