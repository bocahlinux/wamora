# Phase 9.1E — Frontend Sync Status Consumption — Design Audit (Read-Only)

**Scope.** Design/read-only audit only. No source file was modified. Every
claim below was read directly from the current tree this task — `git
status` was checked first and confirmed the working tree contains exactly
Phase 9.0/9.1D's frontend diff (`InboxPage.tsx`/`.css`) and Phase 9.1A's
backend diff (`apps/sync/views.py`, `apps/sync/api_urls.py`,
`config/urls.py`, `apps/sync/tests/test_views.py`), nothing else — so
everything cited here reflects the actual, current, already-implemented
state of both the endpoint and the page it will be wired into.

**No material ambiguity was found that blocks producing this report** —
every open question below is a UX/tuning preference with a defensible
default this report proposes, not an unresolved fact about the API
contract, state semantics, or a genuine architectural fork. Per your
instruction, this report proceeds to completion rather than stopping
mid-audit; the preference-level questions are collected in Section 16.

---

## 1. Current-State Findings

**The backend endpoint (Phase 9.1A, `backend/apps/sync/views.py`, read in
full this task, unchanged since its own implementation report)**:
`GET /api/sync/status/<session_name>/`, `IsAuthenticated`-only,
`404` for an unknown session name (standard `{"error": {...}}` envelope),
`200` for every other case with body:

```json
{
  "session": "no_epahari",
  "sync_status": "healthy",
  "checkpoint_status": "ok",
  "last_run_at": "2026-09-25T10:00:00Z",
  "seconds_since_last_run": 320,
  "checkpoint_updated_at": "2026-09-25T10:00:00Z"
}
```

`sync_status` is exactly one of `never_synced | running | failed | healthy
| stale` — this report treats that enum as closed but not necessarily
exhaustively *known* to the frontend forever (Section 9's "malformed
response" handling).

**`InboxPage.tsx` (re-read in full this task, current post-9.0/9.1D
state)**:
- Two independent `setInterval` polling loops already exist: chat list
  (`CHAT_LIST_POLL_MS = 8000`, `InboxPage.tsx:31`, runs for the page's
  whole lifetime) and messages (`MESSAGES_POLL_MS = 5000`,
  `InboxPage.tsx:32`, runs only while `selectedChatId !== null`).
- A shared connectivity signal already exists:
  `connectivityIssue: 'unreachable' | 'unauthorized' | null`
  (`InboxPage.tsx:81`), fed by exactly one function,
  `reportPollOutcome(result: ApiResult<unknown>)`
  (`InboxPage.tsx:84-111`), called from both poll loops' tick callbacks.
  It classifies `ApiError.kind`: `unauthorized`/`forbidden` → immediate
  `'unauthorized'`; every other failure kind → a 2-consecutive-failure
  counter (`CONNECTIVITY_FAILURE_THRESHOLD = 2`) before showing
  `'unreachable'`. A single success resets it unconditionally.
- A separate, independent send-outcome signal already exists:
  `sendFeedback: {kind:'success'} | {kind:'unknown'} | {kind:'error', error}`
  (`InboxPage.tsx:201`), scoped entirely to `handleSend()`, rendered only
  inline under the composer, never touched by either poll loop.
- The connectivity banner renders once, directly under `PageHeader`
  (`InboxPage.tsx:237-252`) — the one existing precedent for a
  page-level (not per-chat) status element.

**Frontend API client conventions (`frontend/src/lib/djangoApi.ts`, read
in full this task, unchanged)**: every Django-direct read is a small,
named function returning `request<T>(url, {headers: authHeader()})`
(e.g. `getBackendHealth()`, `getChats(page)`), with a matching
hand-written TypeScript interface for the response shape — no generic
fetch wrapper beyond `lib/api.ts`'s `request()`, no serializer/decoder
library. `authHeader()` (`frontend/src/lib/auth.ts:87-90`) is the single,
already-used mechanism for attaching the bearer token — reused, not
reimplemented, by every existing Django-direct call.

**`ApiError` taxonomy (`frontend/src/lib/api.ts`, unchanged, re-confirmed
this task)**: `validation | unauthorized | forbidden | not_found |
server_error | network_error | timeout | unknown` — already includes
`not_found`, which nothing in the current codebase exercises in normal
polling yet (`ChatMessagesView`'s 404 is only reachable via a stale/invalid
`selectedChatId`, not normal operation) — this endpoint's 404 (Section 9)
will be the first *routinely reachable* `not_found` case in this file.

**UI primitives already available and well-suited (`frontend/src/components/ui/StatusBadge.tsx`,
`Badge.tsx`, both read in full this task)** — this is the most important
finding of this audit and materially changes the recommended design
compared to Phase 9.0/9.1D's approach:

- `StatusBadge`'s `StatusKind` union already includes `'healthy'` (tone
  `success`, `CircleCheck` icon), `'syncing'` (tone `info`, `RefreshCw`
  icon), `'warning'` (tone `warning`, `TriangleAlert`), `'error'` (tone
  `error`, `CircleX`), `'unknown'` (tone `neutral`, `Info`) —
  `StatusBadge.tsx:12-24`.
- Two existing mapper functions already establish the exact convention to
  extend: `mapWahaStatus(raw)` and `mapActivityResult(raw)`
  (`StatusBadge.tsx:48-86`), both explicit `switch` statements with a
  `default: return 'unknown'` fallback, both documented as "never invents
  a status the backend didn't report."
- `Badge`'s six tones (`success|warning|error|info|offline|neutral`,
  `Badge.tsx:5`) already cover every visual weight this feature needs,
  with zero new CSS.

Given this, Phase 9.0/9.1D's approach of hand-rolled `<p className="...">`
warning-chip banners is **not** the right template to copy here — those
were built because no existing component fit an *inline, sentence-length,
action-context* message. Sync status is a *point-in-time system state*
badge, exactly what `StatusBadge` + a new `mapSyncStatus()` mapper
(mirroring `mapWahaStatus`/`mapActivityResult` verbatim) already exists to
represent, with zero new CSS.

---

## 2. Relevant Existing Code Paths (traced, not assumed)

- `InboxPage.tsx`'s two poll loops → `reportPollOutcome()` → `connectivityIssue`
  → the one existing banner (`InboxPage.tsx:237-252`).
- `SessionsPage.tsx`'s `mapWahaStatus()` usage (`SessionsPage.tsx:192`,
  re-confirmed via `StatusBadge.tsx`) — the precedent for "raw backend
  string → `StatusKind` → `<StatusBadge>`" that `mapSyncStatus()` should
  mirror.
- `DashboardPage.tsx`'s `HealthCard` (read in the prior Phase 9 design
  audit this session, unchanged) — the precedent for an *always-visible*,
  compact, per-dependency status element, relevant to Section 6's
  visibility recommendation, though `HealthCard` itself is not reused
  directly here (it's Dashboard-specific, includes a title/detail-line
  layout heavier than a single inline badge needs).
- `frontend/src/lib/auth.ts`'s `authHeader()` and
  `frontend/src/lib/AuthContext.tsx`'s expiry timer + `ProtectedRoute`'s
  reactive redirect (both re-confirmed unchanged this task, not re-read
  line-by-line since no drift exists per `git status`) — the existing,
  sole session-expiry mechanism, reused as-is (Section 8).

---

## 3. Proposed UX / State Model

**One new piece of state**, independent of every existing one:

```ts
const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
```

where `SyncStatus` is the TypeScript interface matching the backend's JSON
shape verbatim (Section 1) — no derived/re-interpreted shape client-side,
mirroring how `ChatSummary`/`ChatMessage` already mirror their own
endpoints' shapes exactly.

**Rendering**: a single `<StatusBadge status={mapSyncStatus(syncStatus?.sync_status)} label="..."/>`, placed once, page-level (Section 6), using this label mapping:

| `sync_status` | `StatusKind` | Label (proposed) | Tone conveyed |
|---|---|---|---|
| `null` (not yet fetched) | *(render nothing)* | — | no flash of an incorrect state before the first fetch resolves |
| `never_synced` | `unknown` | "Not yet synced" | neutral, informational — a brand-new session legitimately starts here, not an error |
| `running` | `syncing` | "Syncing…" | info — active, expected, transient |
| `healthy` | `healthy` | "Synced" | success — deliberately *not* "All systems operational" or any phrase implying webhook/connectivity health too (Section 4) |
| `stale` | `warning` | "Sync delayed" | warning — data may lag; explicitly not "offline" |
| `failed` | `error` | "Sync error" | error — the most serious wording used, still scoped to *sync*, never to WhatsApp/connectivity |

**Wording discipline, directly addressing the task's two explicit
warnings**: no label anywhere in this table says or implies "offline,"
"disconnected," or "WhatsApp." Every label is scoped strictly to *data
freshness*, never to *connectivity* or *WhatsApp's own state* — satisfying
both "must never imply stale sync means WhatsApp is offline" and "must
never imply healthy sync guarantees the webhook channel is healthy" by
construction (the words simply never claim either thing).

**Optional, low-cost enrichment**: a `title` attribute (native browser
tooltip) on the badge summarizing `seconds_since_last_run`/`checkpoint_updated_at`
in human-readable form (e.g. "Last synced 5 minutes ago") for an operator
who wants more detail without adding any new visible chrome — proposed as
optional, not required for the core design (Section 16, item 5).

---

## 4. The Four-Way Distinction (Section 4 of the task — the most important question)

| Signal | Source | What it answers | What it must never imply |
|---|---|---|---|
| **Connectivity** (9.1D, existing, unmodified) | `ApiError.kind` on chat-list/messages/**now also sync-status** polls | "Can this page currently talk to Django at all?" | Nothing about data freshness or WhatsApp |
| **Sync status** (9.1A, new, this design) | `SyncStatus.sync_status` from a *successful* fetch of the new endpoint | "Is reconciliation itself healthy, independent of live connectivity?" | Never "WhatsApp is offline" (stale/failed), never "webhook channel is healthy" (healthy) |
| **"No new messages"** | The chat list/messages arrays themselves being empty or unchanged | Nothing is wrong — this is normal, quiet operation | Must never trigger either signal above — neither signal is keyed off message *content* or *volume* in any way |
| **Send error** (existing, `sendFeedback.kind==='error'`) | A single `handleSend()` call's own `ApiResult` | "This one send attempt definitely failed" | Scoped to one message, inline under the composer — never conflated with page-level sync/connectivity state |
| **Send unknown** (existing, `sendFeedback.kind==='unknown'`) | Same call site, ambiguous BFF/WAHA outcome | "This one send's outcome is unconfirmed" | Same scoping as send error — a `stale` sync badge elsewhere on the page must not be read as "that's why your send was ambiguous" (they are genuinely unrelated causes in the architecture — Section 5 of the 9.1A design audit already established reconciliation lag and send ambiguity are different failure classes) |

**How connectivity and sync status coexist, concretely (directly answering
"do not duplicate 9.1D's indicator")**: the new sync-status fetch's outcome
is split at the `ApiResult.ok` boundary:

- **`ok: false`, `kind` is `unauthorized`/`forbidden`/`network_error`/`timeout`/
  `server_error`/`unknown`** → fed into the **existing**
  `reportPollOutcome()` function, the exact same one the other two loops
  already call — **no new connectivity-tracking code is added**. If Django
  is unreachable, all three polls fail together and the one existing
  banner fires once, not three times.
- **`ok: false`, `kind === 'not_found'`** → **not** fed into
  `reportPollOutcome()` (a 404 here means "this session isn't known to
  Django yet," not "Django is unreachable" — feeding it into the
  connectivity signal would be actively misleading). Instead, treated
  identically to a `never_synced` response for display purposes (Section
  9) — `syncStatus` state set to a synthetic `{sync_status: 'never_synced',
  ...all-null}` shape.
- **`ok: true`** → `setSyncStatus(result.data)` — the sync badge updates
  to the real value; connectivity is implicitly `'live'` for this loop
  (already established by any of the *other* loops' own successes, since
  `reportPollOutcome` is shared).

**On a connectivity failure, the sync badge simply keeps showing its last
successfully-fetched value** — exactly the same "freeze, don't blank"
behavior chat list/messages already use — so during an outage, the
operator sees ONE connectivity banner (not reachable) plus a *possibly
stale-looking but unchanging* sync badge, which is honest (the last known
sync state really is the last known one) rather than showing two
independent, possibly-contradictory "something's wrong" signals.

---

## 5. Where the Request Should Live

**A third, independent poll loop — not reusing the chat-list or messages
cycle, not tied to `selectedChatId`.**

Reasoning:
- Sync status is a *page-level*, session-scoped fact (Section 6) — it must
  be fetched and displayed whether or not a chat is currently selected,
  ruling out piggy-backing on the messages loop (which only runs when
  `selectedChatId !== null`).
- Reusing the chat-list loop's *interval* would work mechanically, but
  mixing two semantically different fetches (`getChats` and
  `getSyncStatus`) inside one `setInterval` callback would blur the
  connectivity-attribution story (Section 4) and make the effect harder to
  reason about — a separate effect is clearer and costs nothing extra
  (Section 10's performance analysis: 2 trivial DB queries per call).
- Mirrors this file's own established idiom exactly: chat list already has
  its own **first-load** (`useApiQuery`) + **separate ongoing-poll**
  (`setInterval`) pair, kept apart. A new, independent pair for sync
  status is the same shape applied to a third concern, not a new pattern.

---

## 6. Polling Interval

**Proposed: `SYNC_STATUS_POLL_MS = CHAT_LIST_POLL_MS * 4` (32 000 ms ≈
32s)** — derived from the existing `CHAT_LIST_POLL_MS` constant already in
this file, not an independently invented number, directly satisfying the
task's explicit instruction ("derive it from existing application
constants/config... do not invent infrastructure settings").

Why a multiplier rather than reusing `CHAT_LIST_POLL_MS` directly: the
underlying data changes far more slowly than chat/message content —
`RECONCILIATION_INTERVAL_SECONDS` defaults to 900s (15 minutes;
`STALE_THRESHOLD_MULTIPLIER` in the backend view makes 30 minutes the
stale boundary) — polling every 8s would be needlessly frequent for data
that is architecturally expected to change on a 15-minute-or-longer
cadence. A 4× multiplier (~32s) is still far more responsive than the data
itself ever changes, avoids adding a disconnected, independently-chosen raw
millisecond value, and mirrors the exact design philosophy the backend
view's own `STALE_THRESHOLD_MULTIPLIER` already uses (a multiplier on an
existing constant, not a new independent number) — a deliberate,
documented consistency between the two layers, not a coincidence.

This does **not** touch `CHAT_LIST_POLL_MS`/`MESSAGES_POLL_MS`
themselves — both remain exactly as Phase 8 set them.

---

## 7. Visibility

**Proposed: always visible, compact** — not "only appears when degraded."

Reasoning: with `StatusBadge` as the rendering primitive (Section 1), the
element is already small (an icon + a few words, matching `SessionsPage`'s
own status pill) — not the heavier, sentence-length banner shape Phase
9.0/9.1D use for acute, action-context problems. An element that only
*appears* when something breaks can itself be more jarring (a new, unusual
UI element suddenly showing up draws attention) than a small, constantly-present
badge that simply changes color/icon/label — the latter matches
`DashboardPage`'s own existing `HealthCard` precedent (always shown,
regardless of status) more closely than it matches the acute-alert banner
pattern. This is presented as a recommendation with a clear, reasoned
default, not an unresolved technical question — but it is a genuine UX
preference, listed in Section 16 for your confirmation rather than assumed
silently.

---

## 8. Scope: Global vs. Per-Conversation

**Global (Inbox-page-level) only — never per-conversation.**

The endpoint is explicitly per-*session*, not per-*chat*
(`GET /api/sync/status/<session_name>/`), and this frontend is
architecturally single-session (`config.wahaSessionName` is the only
session `InboxPage.tsx` ever operates on, unchanged by anything in Phase
9.0/9.1D/9.1A). Showing it per-conversation would be actively misleading —
it would imply sync health varies by which chat is open, which nothing in
the data model supports (one `SyncCheckpoint` per session, not per chat).
Proposed placement: directly under `PageHeader`, alongside (not replacing)
the existing connectivity banner slot — visible regardless of which pane
(chat list vs. conversation) is showing, matching the connectivity
indicator's own existing placement precedent exactly.

---

## 9. Error Handling Per Case

| Case | Handling |
|---|---|
| `404` session not found | **Not** fed into `reportPollOutcome` (would wrongly imply a connectivity problem). Treated as equivalent to `never_synced` for display purposes — the badge shows "Not yet synced," the same label a genuinely-known-but-never-reconciled session would show. This is a deliberate simplification: technically a 404 (`WahaSession` row missing entirely) and a 200-with-`never_synced` (`WahaSession` exists, `SyncCheckpoint` doesn't) are different backend states, but from an operator's perspective both mean "nothing to show yet for this session," so one label suffices rather than inventing a sixth visible state for a technical distinction the UI has no actionable use for. |
| `401` unauthorized | Fed into the **existing** `reportPollOutcome()` — identical handling to the other two loops, reusing `AuthContext`/`ProtectedRoute`'s existing expiry mechanism as-is. No second auth system. |
| `5xx` / network failure / timeout | Fed into the **existing** `reportPollOutcome()` — same connectivity-class bucket as the other two loops (Section 4). |
| Malformed/unexpected response | Two sub-cases: (a) an unrecognized `sync_status` string value (e.g. a hypothetical future backend addition the frontend doesn't know about yet) — handled by `mapSyncStatus()`'s `default: return 'unknown'` fallback, mirroring `mapWahaStatus`/`mapActivityResult`'s exact existing convention, so the badge degrades to a neutral "Unknown" rather than rendering nothing or crashing; (b) a response that fails to parse as JSON at all or is missing expected fields — already caught by `lib/api.ts`'s existing `request()` (an empty/non-JSON 2xx body already becomes `{ok:false, error:{kind:'unknown'}}`, per `api.ts`'s own documented behavior), which then flows into the connectivity-class branch above — no new parsing/validation code needed. |

---

## 10. Existing API Client Patterns Reused

`frontend/src/lib/djangoApi.ts` gets one new, small addition, matching
every existing function in that file line-for-line in style:

```ts
export interface SyncStatus {
  session: string;
  sync_status: 'never_synced' | 'running' | 'failed' | 'healthy' | 'stale';
  checkpoint_status: string | null;
  last_run_at: string | null;
  seconds_since_last_run: number | null;
  checkpoint_updated_at: string | null;
}

/** GET /api/sync/status/:session/ — Phase 9.1A
 * (docs/generated/PHASE9-1A-SYNC-STATUS-IMPLEMENTATION-REPORT.md).
 * Read-only; never touches WAHA/Redis/Celery, never triggers
 * reconciliation. */
export function getSyncStatus(session: string) {
  return request<SyncStatus>(`${config.djangoBaseUrl}/api/sync/status/${encodeURIComponent(session)}/`, {
    headers: authHeader(),
  });
}
```

No new HTTP client, no new request wrapper, no new error-handling layer —
`request()` and `authHeader()` are reused exactly as every other
Django-direct call already uses them (`encodeURIComponent` on the path
segment matches `bffApi.ts`'s `sendMessage()`'s own existing
`encodeURIComponent(session)` precedent for a session name in a URL path).

---

## 11. Existing UI Primitives Reused

Covered in depth in Section 1/3 — summarized: `StatusBadge` (component),
`Badge` (its underlying tone renderer), and a new `mapSyncStatus()`
function added to `StatusBadge.tsx` alongside `mapWahaStatus`/
`mapActivityResult`, following their exact existing shape (a `switch`,
`default: return 'unknown'`). **Zero new CSS** is required — `Badge.css`/
`StatusBadge.css` already style every tone this feature needs.

---

## 12. Interference Assessment

- **Chat polling / message polling**: unaffected — the new loop is a
  fully independent `useEffect`/`setInterval`, touching no state either
  existing loop reads or writes, aside from the shared, already-designed-
  for-multiple-callers `reportPollOutcome()`.
- **Send feedback**: unaffected — `sendFeedback` and `syncStatus` are
  separate `useState` calls, never read or written by each other's code
  paths, and rendered in different, non-overlapping parts of the JSX tree
  (Section 8 vs. the existing composer-area block).
- **Conversation selection**: unaffected — the new loop has no dependency
  on `selectedChatId` at all (Section 5).
- **Session selection**: not applicable — this frontend has no
  multi-session selection concept anywhere; `config.wahaSessionName` is a
  static, build-time value, unchanged by anything in this design.
- **One behavioral nuance worth naming, not a defect**: adding a third
  call site to `reportPollOutcome()` means that during a full Django
  outage, up to three independent poll ticks (instead of two) can each
  increment `connectivityFailureCountRef`, so the existing
  `CONNECTIVITY_FAILURE_THRESHOLD = 2` could be reached slightly faster in
  wall-clock time than before this change. This is judged desirable (more
  independent confirmations of failure reasonably accelerate flagging it),
  not a regression — the threshold's *meaning* ("2 consecutive
  connectivity-class failures, from any tracked source") is unchanged.

---

## 13. Exact File Scope

| File | Change |
|---|---|
| `frontend/src/lib/djangoApi.ts` | Add `SyncStatus` interface + `getSyncStatus(session)` function (Section 10). |
| `frontend/src/components/ui/StatusBadge.tsx` | Add `mapSyncStatus(raw: string): StatusKind` (Section 3/11), mirroring `mapWahaStatus`/`mapActivityResult`. |
| `frontend/src/pages/InboxPage.tsx` | Add `syncStatus` state, the new poll effect (first fetch + interval, Section 5/6), the two new call sites into the existing `reportPollOutcome()` (Section 4/9), and one new `<StatusBadge>` render (Section 3/8). |

**No other file** — no new CSS file, no new component file, no backend
change, no BFF change. This matches Phase 9.0/9.1D's own scope discipline
(2-3 files, no new architecture).

---

## 14. Dependency Analysis

- **Depends on**: Phase 9.1A's endpoint existing and behaving exactly as
  documented (confirmed unchanged, Section 1) — no other dependency.
- **Does not depend on, and does not require waiting for**: 9.1B (webhook
  timestamp — not in the current response shape, not assumed), 9.1C
  (Redis health — unrelated endpoint), 9.1F (Dashboard Redis card —
  unrelated page), 9.1G (live verification of 9.1A — this design can be
  implemented and manually verified independently once 9.1A's endpoint is
  reachable in a running environment).
- **Nothing in this design requires any change to**: `reconcile_session()`,
  the BFF, WAHA integration, Session Management, `@lid`/JID identity
  handling, or `status@broadcast` handling — none of these are read or
  referenced by anything proposed here.

---

## 15. Verification Plan

Per your instruction: no frontend test suite exists, and none should be
created merely to satisfy this task's own checklist. At minimum, when this
design is implemented:

- **`npm run build`** (`tsc -b && vite build`) — this project's only
  typecheck mechanism, must pass with zero TypeScript errors, exactly as
  every prior Phase 9 frontend task has verified.
- **`npm run lint`** (`oxlint`) — must introduce zero new warnings beyond
  the five pre-existing, unrelated ones already present before this
  change (re-confirmed present as of Phase 9.1D's own implementation
  report).
- **Manual browser verification cases** (to be performed when
  implemented, not claimed here):
  1. Inbox loads with a session that has never been reconciled → badge
     reads "Not yet synced," no connectivity banner.
  2. Inbox loads with a healthy, recently-reconciled session → badge
     reads "Synced," success tone.
  3. Simulate/observe a `stale` checkpoint (an old `last_run_at`) → badge
     switches to "Sync delayed," warning tone, **no** connectivity banner
     appears (Django is still reachable — only the *data* is stale).
  4. Simulate a genuine Django-unreachable condition → the existing
     connectivity banner appears (unchanged wording/behavior from 9.1D);
     the sync badge freezes at its last known value rather than
     disappearing or showing an error of its own.
  5. Simulate a `401`/expired token while Inbox is open → identical
     behavior to 9.1D's existing `unauthorized` case (no new/duplicate
     "please sign in" messaging).
  6. Simulate the sync-status endpoint specifically 404ing (e.g. a
     misconfigured `VITE_WAHA_SESSION_NAME` not matching any real
     session) → badge reads "Not yet synced," **no** connectivity banner.
  7. Send a message while a `stale`/`failed` sync badge is showing →
     confirm the existing Phase 9.0 send-outcome banner (success/unknown/error)
     behaves identically to before, with no visual or logical interaction
     between the two.
  8. Confirm the badge's position and small size don't shift/reflow the
     chat-list or conversation panes in a way that feels janky, at both
     desktop and the existing mobile breakpoint (`InboxPage.css`'s
     `@media (max-width: 1023px)` block, unchanged by this design).

---

## 16. USER DECISIONS REQUIRED

None of the following block implementation — each has a reasoned default
proposed above and this report's own analysis is confident in each, but
per your working style on this project, preference-level choices are
surfaced explicitly rather than assumed silently:

1. **Always-visible vs. only-when-degraded** (Section 7) — this report
   recommends always-visible-but-compact, reusing `StatusBadge`; confirm,
   or prefer the "only appears when degraded" alternative instead.
2. **Poll interval multiplier** (Section 6) — `CHAT_LIST_POLL_MS * 4`
   (~32s) proposed; confirm or adjust the multiplier.
3. **404-as-`never_synced` simplification** (Section 9) — confirm treating
   an unknown-session 404 identically to a known-but-unreconciled session
   is acceptable, or if you'd prefer a distinct sixth visible state/label
   for that specific case.
4. **Exact label wording** (Section 3's table) — "Not yet synced" /
   "Syncing…" / "Synced" / "Sync delayed" / "Sync error" are this report's
   proposed copy, chosen to avoid any connectivity/WhatsApp implication;
   confirm or adjust the exact wording.
5. **Tooltip enrichment** (Section 3, optional) — whether to add a
   `title` attribute surfacing `seconds_since_last_run`/`checkpoint_updated_at`
   for extra detail on hover, or keep the badge as label-only with no
   additional detail surface.

---

This was a design-only audit. No source file was created or modified.
Stopping here, per instruction — not proceeding to implementation, and not
starting Phase 9.1B, 9.1C, 9.1F, 9.1G, or Phase 11.
