# Phase 9.1D — Connectivity Indicator — Implementation Report

**Scope of this task.** Implementation, frontend-only, exactly the slice
named "9.1D" in `docs/generated/PHASE9-1-DESIGN-AUDIT-REPORT.md` (Section
7, item 1 / Section 10). No backend endpoint was added (9.1A/B/C not
implemented). No Session Management, identity/`@lid`/JID, `status@broadcast`,
reconciliation logic, database schema, or send-message *mechanism* change
was made. `SyncCheckpoint.lag_seconds` was not touched or referenced. No
Redis/Celery health check was added. No live WhatsApp message was sent
during development or testing.

---

## 1. Root cause / gap addressed

Confirmed directly (re-read before coding, per the task's instruction):
`InboxPage.tsx`'s two background polling loops (chat list every 8000ms,
open-conversation messages every 5000ms) discard every failure completely —
`if (result.ok) setChats(...)` / `if (result.ok) setMessages(...)`, with no
`else` branch at all. A user with Inbox open had no way to tell "the server
just went unreachable" from "there's simply nothing new to show." This gap
was explicitly named in both prior Phase 9 design audits and was
**unaffected by Phase 9.0**, which only fixed the *write* path (send
outcome), never the *read*/polling path — confirmed unchanged by reading
the current file before starting this task.

## 2. Source files changed

| File | Nature of change |
|---|---|
| `frontend/src/pages/InboxPage.tsx` | New `ConnectivityIssue` type, `CONNECTIVITY_FAILURE_THRESHOLD` constant, `connectivityIssue` state + `connectivityFailureCountRef`, `reportPollOutcome()` function; both poll `useEffect`s now call `reportPollOutcome(result)`; one new conditional render block under `PageHeader`. Two new icon imports (`LogIn`, `WifiOff` from `lucide-react`, already a dependency). |
| `frontend/src/pages/InboxPage.css` | One new rule, `.wa-inbox__connectivity` — reuses the exact same warning-chip formula (`color-mix(in srgb, var(--color-warning) 14%, transparent)`, same padding/radius/font-size tokens) already established by Phase 9.0's `.wa-inbox__send-unknown`, so no new visual language was introduced. |

No other file was touched — confirmed by `git diff --stat` (Section 10).
Note: neither file has been committed since Phase 9.0, so their working-tree
diff against the last commit still includes Phase 9.0's own (already
reported, unmodified-by-this-task) changes alongside this task's new ones —
Section 10 identifies exactly which hunks belong to which task.

## 3. How `ApiError.kind` is used

No new error taxonomy was created — per the task's explicit instruction,
the existing 8-way `ApiError.kind` (`frontend/src/lib/api.ts`, unread and
unmodified this task, only consumed) is reused as-is via one classification
function, `reportPollOutcome()`:

```ts
function reportPollOutcome(result: ApiResult<unknown>) {
  if (result.ok) {
    connectivityFailureCountRef.current = 0;
    setConnectivityIssue(null);
    return;
  }
  if (result.error.kind === 'unauthorized' || result.error.kind === 'forbidden') {
    connectivityFailureCountRef.current = 0;
    setConnectivityIssue('unauthorized');
    return;
  }
  connectivityFailureCountRef.current += 1;
  if (connectivityFailureCountRef.current >= CONNECTIVITY_FAILURE_THRESHOLD) {
    setConnectivityIssue('unreachable');
  }
}
```

- `ok: true` → always resets to normal, unconditionally, regardless of prior
  state.
- `unauthorized` / `forbidden` → its own distinct branch, never folded into
  the "unreachable" bucket — satisfies the task's explicit requirement not
  to mislabel an auth problem as "server offline."
- Every other kind (`network_error`, `timeout`, `server_error`, `not_found`,
  `validation`, `unknown`) is treated uniformly as "connectivity-class" —
  the task explicitly said not to invent a finer taxonomy than what already
  exists, and none of `not_found`/`validation` can actually occur on these
  two plain, already-authenticated `GET` calls in practice; they're included
  in the same bucket only so the function is total over `ApiError.kind`
  rather than silently ignoring a value it doesn't recognize.

## 4. State / transitions

Two pieces of state, both scoped to `InboxPage`'s own component instance
(no context, no new persistence):

- `connectivityIssue: 'unreachable' | 'unauthorized' | null` (React state —
  drives rendering).
- `connectivityFailureCountRef` (a plain `useRef` counter — does **not**
  trigger a re-render by itself; only `setConnectivityIssue` does).

Transitions, exactly as implemented:

| Event | Effect |
|---|---|
| Any poll tick succeeds | Counter → 0, `connectivityIssue` → `null` (immediately, unconditionally). |
| Poll tick fails, `kind ∈ {unauthorized, forbidden}` | `connectivityIssue` → `'unauthorized'` **immediately** (no threshold — retrying will not fix an auth problem, so there is no reason to wait for a second failure). |
| Poll tick fails, any other kind | Counter += 1; if counter ≥ `CONNECTIVITY_FAILURE_THRESHOLD` (= **2**), `connectivityIssue` → `'unreachable'`. Below the threshold: **counter increments internally, but nothing is rendered** — this is what guarantees a single isolated blip produces zero visible change, directly satisfying "jangan membuat polling error menghasilkan banner berkedip setiap 5 detik." |
| Poll tick fails again while already `'unreachable'`/`'unauthorized'` | State stays as-is (idempotent — `setConnectivityIssue` is called with the same value, no flicker). |

Both the chat-list poll (8000ms) and the messages poll (5000ms, only while a
chat is open) feed the **same** shared state — a deliberate, single
combined signal rather than two independent indicators, per the design
report's explicit recommendation (Section 7: in practice both loops hit the
same Django origin and fail together).

**Explicitly not fed into this signal** (kept exactly as they already were,
untouched): the two pages' *first*-load queries (`useApiQuery`, which
already show `ErrorState` + a manual retry button on first-load failure —
this indicator only ever governs *ongoing* polling after at least one
success, matching the design report); `markChatRead()`'s failure (currently
silently ignored, pre-existing behavior, not touched); `handleLoadOlder()`'s
failure (same); the send/`handleSend()` path (Phase 9.0's own, separate,
already-correct three-way feedback — completely independent state,
confirmed untouched, see Section 7).

## 5. UI behavior per outcome

Rendered as one `<p role="status" className="wa-inbox__connectivity">`
directly under the page's `PageHeader`, visible regardless of which pane
(chat list vs. conversation) is currently shown, since it reflects a
whole-page connectivity property, not a per-pane one.

| Outcome | UI shown |
|---|---|
| **success** (any poll tick) | Nothing — the banner is not rendered at all, and any previously-shown banner disappears on this very tick. Identical to pre-9.1D behavior in every other respect (chat list / messages update exactly as before). |
| **network_error / timeout / server_error / unknown** (2+ consecutive) | `<WifiOff>` icon + "Can't reach the server right now — showing the last data loaded. Retrying automatically; this doesn't mean WhatsApp itself is offline." The explicit last clause is the direct implementation of the task's requirement to distinguish a connectivity problem from "WhatsApp is offline." |
| **network_error / timeout / server_error / unknown** (only 1, isolated) | **Nothing shown** — by design, per Section 4's threshold. |
| **unauthorized / forbidden** | `<LogIn>` icon + "Your session needs to be renewed — sign in again to continue." — a categorically different message, never implying "server offline." Shown on the very first such failure, no threshold. |
| **"no new messages"/quiet chat** | Not a failure at all (`result.ok === true`) — never triggers this indicator under any circumstance; the existing `EmptyState`/unread-driven UI is completely untouched. |

## 6. How the indicator returns to normal

Automatically, on the very next successful poll tick of either loop — no
manual "reconnect" action exists or is needed, since both intervals already
retry unconditionally forever (unchanged, pre-existing behavior). The
`unauthorized` state recovers the same way *if* a subsequent poll somehow
succeeds (e.g. a transient false-401); in the far more common real case of
an actually-expired token, `AuthContext`'s own existing, separate
`setTimeout`-driven expiry check (confirmed by reading
`frontend/src/lib/AuthContext.tsx` and `frontend/src/routes/ProtectedRoute.tsx`
before coding, both unmodified) will have already redirected the user to
`/login` before polling gets a chance to keep failing — this indicator's
`unauthorized` branch is a narrow backstop for a server-side 401 the
client's own decoded-JWT-expiry timer didn't predict, not the primary
mechanism for handling session expiry (that mechanism already existed and
was not touched).

## 7. Testing performed

- **Frontend automated tests**: none exist in this project (re-confirmed —
  no `test` script, no `vitest`/`jest` dependency, zero `*.test.tsx` files
  anywhere under `frontend/src`). Per the task's own conditional
  instruction, none was added.
- **Typecheck + build**: `npm run build` (`tsc -b && vite build`) —
  **passed**, zero TypeScript errors, `✓ 1950 modules transformed`,
  `✓ built in 619ms`.
- **Lint**: `npm run lint` (`oxlint`) — **passed**, output showed the exact
  same 5 pre-existing warnings as before this task (`StatusBadge.tsx`,
  `AuthContext.tsx`, `ThemeContext.tsx`) — zero new warnings from
  `InboxPage.tsx`/`InboxPage.css`, including no missing-dependency warning
  for the new `reportPollOutcome` reference inside the two `useEffect`
  intervals (consistent with the file's pre-existing pattern of not
  listing stable outer-scope functions in those same effects' dependency
  arrays).
- **Manual/live browser verification**: **not performed** — no browser was
  opened, no network condition was simulated, no real send/poll cycle was
  observed live. This is stated plainly rather than implied — see Section
  11.
- **Regression check, Phase 9.0**: `handleSend()`, the `SendFeedback` union,
  and the composer's success/unknown/error rendering block were read
  (unchanged) but not modified by this task's edits, and are structurally
  independent state (`sendFeedback` vs. `connectivityIssue` — two separate
  `useState` calls, never read or written by each other's logic) — a send
  succeeding, failing, or resolving `unknown` cannot affect
  `connectivityIssue`, and vice versa. Confirmed by inspection, not by a
  live send (none was performed, per the hard rule).
- **Regression check, success path unchanged**: the `if (result.ok)
  setChats(...)` / `setMessages(...)` lines were **not modified** — only a
  new line, `reportPollOutcome(result)`, was added immediately after each,
  strictly additive.

## 8. What was NOT touched

- Backend (`backend/`) — zero files.
- BFF (`bff/`) — zero files.
- Database, migrations, `.env`, any configuration file.
- WAHA session / any WAHA API call.
- Session Management (`SessionsPage.tsx`/`.css`) — read only, in the prior
  design audit, to study its `ActionFeedback` precedent; not opened at all
  in this task.
- Identity/`@lid`/JID resolution, `chatDisplay()`, any Contact/Chat
  auto-merge.
- `status@broadcast` — not mentioned, not filtered, not referenced anywhere
  in this task's changes.
- Reconciliation logic, `SyncCheckpoint`, `reconcile_session()` — not read
  or modified this task (this task's diff never touches any `backend/apps/sync`
  file).
- Send-message mechanism/idempotency (`bff/src/routes/messages.ts`,
  `OutboundOperation`) — not touched; only the already-existing,
  Phase-9.0-built composer feedback was read (unchanged) to confirm no
  interaction with the new state.
- 9.1A (backend sync-status endpoint), 9.1B (webhook-timestamp addition),
  9.1C (Redis health endpoint), 9.1E (sync-status frontend badge), 9.1F
  (Dashboard Redis card), 9.1G (live verification) — none started, per the
  task's explicit stop instruction.

## 9. No out-of-scope dependency was hit

Per the task's instruction to stop and report rather than expand scope: no
such dependency was found. This slice required no backend, BFF, or database
change — it consumes only data (`ApiError.kind`) already flowing through
the frontend's existing HTTP client on every request, exactly as scoped in
the design report.

## 10. `git diff --stat` (final)

```
frontend/src/pages/InboxPage.css |  31 ++++++++++
frontend/src/pages/InboxPage.tsx | 125 +++++++++++++++++++++++++++++++++------
2 files changed, 139 insertions(+), 17 deletions(-)
```

`git status --short`:
```
 M frontend/src/pages/InboxPage.css
 M frontend/src/pages/InboxPage.tsx
```
— exactly the same two files Phase 9.0 touched, no others. Since neither
file has been committed since Phase 9.0, this diff is cumulative (Phase
9.0's send-outcome change plus this task's connectivity-indicator change,
both against the last real commit). The hunks specific to this task are:
the `LogIn`/`WifiOff` import addition, the `CONNECTIVITY_FAILURE_THRESHOLD`/
`ConnectivityIssue` block, the `connectivityIssue`/`reportPollOutcome`
block, the two one-line `reportPollOutcome(result)` additions inside the
existing poll intervals, the new conditional render block under
`PageHeader`, and the one new CSS rule — every other hunk in the diff is
unchanged Phase 9.0 content, already reported in
`docs/generated/PHASE9-0-UNKNOWN-SEND-OUTCOME-IMPLEMENTATION-REPORT.md`.

## 11. Risks / follow-up for Phase 9.1A–G

- **No live browser verification was performed** (Section 7) — the state
  machine's correctness rests on code-reading and the type-checker/lint
  passing, not on having actually watched the banner appear/disappear in a
  running browser against a real or simulated failure. This is the same
  honesty standard every other UI change in this project's history has
  held to.
- **`CONNECTIVITY_FAILURE_THRESHOLD = 2` is an implementation choice, not
  a value the design report mandated a specific number for** (it proposed
  2–3 as a range) — worth confirming this concrete value is acceptable, or
  adjusting it, since it's a one-line constant with no other coupling.
- **This indicator says nothing about sync/reconciliation health**
  (Signal B, 9.1E) — a perfectly reachable Django with a stale
  `SyncCheckpoint` produces no indicator at all under this task's change,
  exactly as designed (the two signals are deliberately independent), but
  worth restating so it isn't mistaken for a complete "is my data current"
  answer — it only ever answers "can this page currently talk to the
  server."
- **`markChatRead()` and `handleLoadOlder()` failures remain silent**,
  exactly as before this task — not addressed, since the design report
  scoped Signal A to the two polling loops specifically; if you want these
  write/pagination actions to also feed (or at least surface) connectivity
  problems, that would be a distinct, small follow-up, not something this
  task assumed into scope.
- **No new dependency, no schema change, no backend change** was needed for
  this slice — confirms the design report's Section 10 assessment that
  9.1D was independent of every decision in that report's Section 12.

---

This implementation is complete and scoped to exactly Phase 9.1D. Stopping
here, per instruction — not continuing to 9.1A or any other Phase 9 slice
without further direction.
