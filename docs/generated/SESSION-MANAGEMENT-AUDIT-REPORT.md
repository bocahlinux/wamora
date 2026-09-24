# Session Management Audit Report

**Read-only.** No source, configuration, `.env`, dependency, migration,
infrastructure, or generated application file was modified while
producing this report — the only output is this file. No canonical
phase was started or renumbered.

**Evidence tagging used throughout**: **VERIFIED** = read directly from
current repository source/tests this task. **INFERENCE** = a reasonable
conclusion drawn from VERIFIED facts, not itself directly stated in the
code. **OPEN QUESTION** = genuinely undetermined by the repository;
not answered here, not guessed at.

**What was inspected this task**: `bff/src/routes/session.ts`,
`bff/src/routes/sessionGuard.ts`, `bff/src/routes/messages.ts` (for
contrast — see Section 5), `bff/src/wahaClient.ts`,
`bff/src/wahaAllowlist.ts`, `bff/src/errors.ts`, `bff/src/auditHelper.ts`,
`bff/src/djangoClient.ts`, `bff/src/middleware/auth.ts`,
`bff/src/config.ts`, `bff/test/routes.session.test.ts` (full),
`frontend/src/pages/SessionsPage.tsx`, `frontend/src/lib/bffApi.ts`,
`frontend/src/lib/auth.ts`, a repository-wide grep for any frontend
reference to session lifecycle/QR/pairing, `backend/config/settings.py`'s
`JWT_SCOPES`, `docs/15-CODING-PHASES.md`,
`wamora-design-assets/docs/WAMORA-FRONTEND-DESIGN-SPEC.md` Section 12,
and the relevant `docs/generated/PHASE-6-*` contract reports for
cross-reference.

---

## 1. Current session-management contract (BFF)

All routes below are mounted under `/api` (`app.use('/api', sessionRouter)`
in `bff/src/app.ts`) and live in `bff/src/routes/session.ts`. **VERIFIED**
against source directly.

| Method | Path | Scope required | Body | Response (200) | Errors |
|---|---|---|---|---|---|
| `GET` | `/api/sessions/:session/status` | `reading` | — | `{session, status, engine, me}` (fields taken as-is from WAHA's JSON body) | `401` no/invalid token · `403` wrong scope · `404` unknown session (name mismatch) · `502 waha_unavailable` on any non-2xx/timeout/network error from WAHA |
| `POST` | `/api/sessions/:session/start` | `session control` | — | `{success: true, session, requestedAction: "start"}` | same 401/403/404 pattern · `502 waha_unavailable` |
| `POST` | `/api/sessions/:session/stop` | `session control` | — | `{success: true, session, requestedAction: "stop"}` | same |
| `POST` | `/api/sessions/:session/restart` | `session control` | — | `{success: true, session, requestedAction: "restart"}` | same |
| `POST` | `/api/sessions/:session/logout` | `session control` | — | `{success: true, session, requestedAction: "logout"}` | same |
| `GET` | `/api/sessions/:session/qr` | `session control` | — | `{session, format: "json"\|"image"\|"raw", data}` (`data` is WAHA's JSON, or base64 bytes for an image, per `format`) | `401`/`403`/`404` · `409 conflict` when WAHA returns 404 ("Session is not awaiting pairing") · `502` on any other failure |
| `POST` | `/api/sessions/:session/pairing-code` | `session control` | `{phoneNumber: string}` | `{session, code}` (`code` from WAHA's `body.code`, falling back to raw response text) | `400 invalid_request` if `phoneNumber` missing/empty · `401`/`403`/`404` · `502` on failure |

`:session` is validated against the single configured
`WAHA_SESSION_NAME` by `sessionGuard.ts::validateSession()` before any
WAHA call — **any other session name is rejected with 404**, regardless
of scope. **VERIFIED**.

**All seven endpoints are actually implemented, not merely referenced.**
Every one has a corresponding, currently-passing test in
`bff/test/routes.session.test.ts` (auth/scope/session-name/success/
error-mapping cases for each), and every one calls a real, allow-listed
WAHA endpoint via `wahaClient.ts`/`wahaAllowlist.ts` — there is no stub or
`// not implemented` path among them. **VERIFIED**.

---

## 2. Frontend coverage

| Capability | Frontend API function | Hook | Page/component | Button/control | Used? |
|---|---|---|---|---|---|
| Session status (read) | `getSessionStatus()` (`bffApi.ts`) | `useApiQuery` | `SessionsPage.tsx` | — (display only) | **Yes** |
| Start | none | none | none | none | **No — completely unused** |
| Stop | none | none | none | none | **No — completely unused** |
| Restart | none | none | none | none | **No — completely unused** |
| Logout (session, i.e. WAHA logout — distinct from the auth "Sign out" button) | none | none | none | none | **No — completely unused** |
| QR | none | none | none | none | **No — completely unused** |
| Pairing code | none | none | none | none | **No — completely unused** |

**VERIFIED** by direct grep: no file under `frontend/src` references
`startSession`/`stopSession`/`restartSession`/`logoutSession`/a `/qr`
call/pairing beyond (a) the icon import for `QrCode` in `StatusBadge.tsx`
(unrelated — it's part of the general status-icon vocabulary, not a
session action), and (b) `SessionsPage.tsx`'s own comment stating these
are deliberately not wired yet.

`SessionsPage.tsx`'s existing dependency note, read verbatim: *"Session
control (start, stop, restart, logout, QR pairing) is implemented by the
BFF (Phase 6) but its UI is scoped to a later phase."* This matches
exactly what this audit independently confirmed from the BFF source. Not
stale, not obsolete — **VERIFIED accurate**.

Note: the Sidebar's "Sign out" button (`Sidebar.tsx`) is the **frontend
JWT session** logout (clears the local token), unrelated to the BFF's
`POST /sessions/:session/logout` (which logs the **WhatsApp** session out
of WAHA). Naming collision worth being precise about in any future UI
copy.

---

## 3. Session state trace (WAHA → BFF → frontend)

- **Source of truth**: WAHA itself, called live on every request — the
  BFF holds no cached/stored session-status state of its own.
  **VERIFIED** (`session.ts`'s status handler calls `callWaha` directly,
  no caching layer anywhere in the BFF).
- **Mechanism**: **request-based, not polling or realtime.**
  `SessionsPage.tsx` fetches once on mount via `useApiQuery(..., [])`
  (empty dependency array — no interval, no WebSocket, no
  `EventSource`). **VERIFIED**. Refreshing the status requires either a
  page reload or `useApiQuery`'s `refetch()` (exposed by the hook but not
  currently wired to any UI control on `SessionsPage`).
- **QR state**: no persistent state — `GET /sessions/:session/qr` is a
  pure pass-through, called fresh every time, returning WAHA's response
  in whatever format it came in. No BFF-side caching, no expiry tracking,
  no "is a QR currently pending" flag anywhere. **VERIFIED**.
- **Pairing-code state**: same — no BFF-side state, pure pass-through per
  request. **VERIFIED**.
- **Session lists**: **not available.** There is no BFF or Django
  endpoint that lists sessions — `sessionGuard.ts` only ever validates a
  requested `:session` param against the single configured name; it
  cannot enumerate sessions because nothing asks WAHA to. **VERIFIED**
  (confirmed absent from `wahaAllowlist.ts`'s endpoint set — no `list`
  endpoint is defined there at all, and per `docs/CLAUDE.md`'s BFF rule,
  it structurally cannot call anything not in that allowlist).
- **Can the existing single-session status endpoint support a management
  UI?** **INFERENCE, moderately confident**: yes, for exactly one
  session — the status endpoint already returns everything a single-
  session management card needs (`status`, `engine`, `me`), and the
  lifecycle/QR/pairing endpoints are all keyed off the same single
  `:session` name. Nothing about the *existing* contract blocks building
  a one-session management UI today.
- **Is multi-session support required for the immediate UI?** **No —
  VERIFIED as unnecessary for the immediate case**: `WAHA_SESSION_NAME`
  is a single configured value BFF-wide (`bff/src/config.ts`), and
  `docs/00-MASTER-SPEC.md` itself describes the product as "Awal: 1
  session, kemungkinan maksimal 2–3" (initially 1 session, possibly up to
  2-3) — a single-session management UI is both what the current
  contract supports and consistent with the documented initial scope.
  Multi-session is a separate, larger, **not currently required**
  undertaking (session list endpoint, per-session credential handling,
  etc. — none of which exists).

---

## 4. Security

- **JWT authentication**: every lifecycle/QR/pairing/status route uses
  `requireAuth` (verifies the RS256 token against `config.jwtPublicKey`,
  same mechanism audited and fixed earlier this session) followed by
  `requireScope(...)`. **VERIFIED** directly in `session.ts`'s router
  definitions.
- **Scope enforcement, exact**: `status` requires `reading`;
  `start`/`stop`/`restart`/`logout`/`qr`/`pairing-code` all require
  `session control` — a stricter scope than `reading`. **VERIFIED**, and
  tested (`bff/test/routes.session.test.ts`'s `describe.each` block
  explicitly asserts 403 for a `reading`-only token on every lifecycle
  route).
- **Internal service authentication**: the BFF's own writes back to
  Django (`recordAudit` → `writeAuditEvent`) use a separate,
  non-JWT shared secret (`INTERNAL_SERVICE_KEY`, sent as
  `X-Internal-Service-Key`) — distinct from the end user's JWT, matching
  the same pattern already audited for the send-message flow.
  **VERIFIED**.
- **Session ownership/access control**: there is no per-user session
  ownership model — any authenticated user with the `session control`
  scope can control the **one** configured session; there is no concept
  of "this user owns this session" because there is only one session and
  scope is the only gate. **VERIFIED** (no user/session relation exists
  anywhere in the reviewed code). Whether this is sufficient is a product
  decision, not something this audit resolves.
- **Are start/stop/restart/logout protected correctly?** **VERIFIED
  yes**, per the scope check above and the session-name validation — an
  authenticated request with the `session control` scope for the
  *correct* session name is required for all four; anything else is
  401/403/404.
- **Does QR/pairing-code response expose anything that shouldn't reach
  the browser?** **VERIFIED no leakage of the WAHA API key** — `qr`'s
  response is `{session, format, data}` only; `wahaClient.ts` never
  returns the request headers it sent, so the API key can't leak through
  the response body by construction. The pairing-code response is
  `{session, code}` only. Both are explicitly tested for this
  (`routes.session.test.ts`: `"never leaks the API key"`-style assertion
  on the status route; the QR test explicitly asserts `not.toHaveProperty('apiKey')`).
  **OPEN QUESTION**: whether the raw WAHA QR/pairing payload itself
  (forwarded close to as-is) could contain something WAHA considers
  sensitive is not something this repository's code can answer — that
  depends on WAHA's own actual response content, which hasn't been
  live-verified against a real WAHA instance in any report on file.
- **Can the frontend safely call these endpoints directly, or must it go
  through the BFF?** **VERIFIED**: it must go through the BFF — this is
  a hard project rule (`docs/CLAUDE.md` rule 4: "The frontend must never
  call WAHA directly — only through the BFF") and is also the only path
  that exists; there is no Django-side session-control endpoint at all
  (`apps.waha_sessions` has no `urls.py`/`views.py` — confirmed in the
  prior roadmap audit and re-confirmed here).

---

## 5. Idempotency and failure behavior

**This is the most important finding of this audit — read carefully.**

**VERIFIED: the lifecycle actions (start/stop/restart/logout) and QR/
pairing-code have NO idempotency mechanism at the BFF layer at all.**
Contrast with the send-message route (`messages.ts`), which has a full
`Idempotency-Key`-header-driven state machine backed by
`operations.OutboundOperation` (register → check existing status → only
call WAHA if genuinely new/retryable → resolve). **Nothing like that
exists for `start`/`stop`/`restart`/`logout`/`qr`/`pairing-code`** — each
is a direct, unconditional pass-through: `validateSession` → `callWaha`
→ record an audit entry → respond. No idempotency key is accepted,
checked, or required by any of these six routes. **VERIFIED** by reading
`handleLifecycleAction()` and the `qr`/`pairing-code` handlers in full —
none reference an idempotency key or a prior-operation lookup.

Per-scenario behavior, **reporting only what the code actually does —
not inventing WAHA's own server-side behavior, which this repository
cannot observe**:

| Scenario | What the BFF actually does |
|---|---|
| Double-click **Start** | Two independent `POST /start` calls reach WAHA. The BFF applies no dedup — each becomes its own `callWaha('startSession', ...)` call, its own audit-fallback log line, and its own best-effort Django audit write. **OPEN QUESTION**: whether WAHA itself is idempotent for a second `start` call on an already-starting/started session is outside this repository's knowledge — no live WAHA verification exists in any report on file. |
| Click **Stop** while already stopped | Same pattern — an unconditional `POST /stop` reaches WAHA regardless of current state; the BFF never checks current status first. Outcome depends entirely on how WAHA itself responds to a stop-when-stopped request — **OPEN QUESTION**, not observable from this codebase. |
| Click **Restart** repeatedly | Same — no dedup, no rate limiting, no cooldown. Each click is an independent WAHA call. |
| Click **Logout** while disconnected | Same — no state check before calling WAHA. |
| Request **QR** repeatedly | Each request is a fresh `GET` to WAHA — no caching, no "a QR was already issued N seconds ago" tracking. If WAHA returns 404 (not awaiting pairing), the BFF maps that to `409 conflict`, so a client polling this repeatedly while the session isn't in a pairable state will get a clean, distinguishable 409 each time, not a generic error. |
| Request **pairing code** repeatedly | Same pass-through pattern as QR; no caching or replay protection at the BFF layer. |
| **Network loss during an operation** | `callWaha()` has a bounded timeout (`config.wahaTimeoutMs`, default 10000ms via `AbortController`). On timeout or a network error, `outcome` is `'timeout'`/`'network_error'` — for **lifecycle/QR/pairing routes, both collapse into the same path as a confirmed WAHA failure**: `success = false`, audit is recorded with `result: 'failure'`, and the client receives `502 waha_unavailable`. **This is a meaningful gap relative to the send-message flow**: `messages.ts` explicitly distinguishes a confirmed `http_error` (→ `failed`) from a `timeout`/`network_error` (→ `unknown`, "genuinely ambiguous, never assume success or failure" — its own comment, citing `docs/09-TEST-PLAN.md` Failure test #8). **The lifecycle/QR/pairing routes make no such distinction** — an ambiguous timeout (where WAHA may have actually started/stopped the session server-side even though the BFF never got a response) is recorded and reported identically to a confirmed failure. **VERIFIED** by direct comparison of the two code paths; this is a factual gap in the current implementation, not a hypothetical. |

**Do not invent behavior** was an explicit instruction — nothing above
states what WAHA itself guarantees; only what the BFF code visibly does
or does not do.

---

## 6. UI/design fit

- `docs/15-CODING-PHASES.md` assigns "Session management" to canonical
  **Phase 10**, after Inbox/chat (8) and Offline/degraded mode (9).
  **VERIFIED**, unchanged from the earlier roadmap audit.
- The design spec (`WAMORA-FRONTEND-DESIGN-SPEC.md` Section 12, "Session
  management visual direction") explicitly recommends: session
  name/status/phone-identifier/duration/activity per card, actions
  (Start/Stop/Restart/Logout/QR pairing), and — important — **"QR pairing
  should be visually isolated in a modal/card rather than mixed into the
  main session card."** **VERIFIED**, read directly this task.
- **Where should it live?** The spec and the existing route structure
  both point to the same place: `frontend/src/pages/SessionsPage.tsx`
  already exists, already fetches and renders the one real
  session-status endpoint, and is the sidebar's named "Sessions" nav
  destination (Section 7 of the spec: "Sessions" → `Smartphone` icon,
  already implemented in `Sidebar.tsx`). There is no repository evidence
  suggesting the Dashboard, a separate modal-only flow, or a different
  route — `SessionsPage` is the existing, natural home. QR pairing
  specifically should be a modal per the spec's own explicit instruction
  above, not inline on the card. **This is not a redesign recommendation
  beyond what the spec already states** — Section 12 already says this;
  this audit is reporting that fit, not inventing a new placement.
- Components the spec's Section 8 names that session-management UI would
  need and that **do not exist yet** in `frontend/src/components/ui/`:
  `Modal/Dialog` (for the QR pairing flow) and `ConfirmDialog` (spec
  Section 12: "Destructive actions must require appropriate confirmation
  where specified by the security/functional contract" — Stop/Logout are
  reasonable candidates for this, though the *exact* which-actions-need-
  confirmation list is not specified anywhere in the repository — **OPEN
  QUESTION**). **VERIFIED absent** by directory listing (confirmed again
  this task, same finding as the prior roadmap audit).

---

## 7. Dependencies

What must be completed before a Session Management **UI** can be
implemented, evaluated strictly against what exists today:

- **Backend (Django) changes**: **none required.** No Django endpoint is
  in this contract at all — the BFF talks to WAHA directly and to
  Django only for best-effort audit writes, which already work.
- **BFF changes**: **none required** for the MUST-HAVE scope (Section
  9) — every endpoint needed already exists and is tested. (See Section
  9 "Nice to have" for changes that would improve, not enable, the
  feature.)
- **Frontend changes**: the entire UI — API client functions (none exist
  yet for these six capabilities, only `getSessionStatus`), action
  buttons, a QR modal component, a confirm-dialog component (or reuse of
  a simpler pattern if a full `ConfirmDialog` isn't built first),
  wiring to `SessionsPage`.
- **API contract changes**: **none required** — the existing contract
  is usable as-is for a single-session UI.
- **Database/migrations**: **none.**
- **Environment/configuration**: **VERIFIED gap, found in the prior BFF
  env-loading fix report and re-confirmed here**: this local dev
  environment's `bff/.env` has `WAHA_SESSION_NAME` present as a variable
  name but **empty of value**
  (`docs/generated/PHASE-8C-BFF-ENV-LOADING-FIX-REPORT.md` Section 14).
  With it empty, `validateSession()` rejects every session name
  unconditionally (`if (!config.wahaSessionName || ...)`), so **no
  session-management call can succeed in this environment today**,
  regardless of frontend work, until that value is set. This is a
  configuration gap, not a code gap — out of this audit's read-only
  scope to fix, but directly relevant to whether the feature is
  *testable* right now.
- **WAHA availability**: this session's health checks
  (`docs/generated/PHASE-8C-BROWSER-ACCEPTANCE-REPORT.md`) show WAHA as
  "Not reachable" in this local environment. A session-management UI can
  be built and its error states exercised without live WAHA, but full
  positive-path browser verification needs a reachable WAHA instance
  and a configured `WAHA_SESSION_NAME` — neither is present right now.
- **Multi-session architecture**: **not a dependency** for the scope
  Section 9 recommends — confirmed in Section 3.
- **Authorization group assignment**: **VERIFIED, easy to miss**: scope
  membership for a non-superuser is Django-Group-based
  (`apps.authn.jwt_utils.compute_scopes()` — a user only gets the
  `session control` scope if they're in a Django `Group` named exactly
  `"session control"`, or are a superuser). This session's only real dev
  user (`udin`) is a superuser, so this hasn't been exercised for an
  ordinary account. Deploying this feature for a non-superuser operator
  requires an admin to create that Group and add the user to it — an
  operational step, not a code change, but a real dependency worth
  naming.

---

## 8. Gap analysis

| Capability | Backend (Django) | BFF | Frontend API | UI | Blocker |
|---|---|---|---|---|---|
| Status (read) | n/a (BFF→WAHA direct) | ✅ done | ✅ `getSessionStatus()` | ✅ `SessionsPage` | none |
| Start | n/a | ✅ done | ❌ | ❌ | frontend only |
| Stop | n/a | ✅ done | ❌ | ❌ | frontend only |
| Restart | n/a | ✅ done | ❌ | ❌ | frontend only |
| Logout | n/a | ✅ done | ❌ | ❌ | frontend only |
| QR | n/a | ✅ done | ❌ | ❌ (needs a Modal component too) | frontend only, + missing `Modal`/`Dialog` component |
| Pairing code | n/a | ✅ done | ❌ | ❌ | frontend only, likely shares the QR modal |
| Session list / multi-session | ❌ (no model exposure) | ❌ (no `list` in allowlist) | ❌ | ❌ | **not required for immediate scope** (Section 3) — real gap only if multi-session is later prioritized |
| Confirmation UX for destructive actions | n/a | n/a (not a backend concern) | n/a | ❌ (no `ConfirmDialog` component) | frontend component gap |
| Local testability (`WAHA_SESSION_NAME` unset, WAHA unreachable) | n/a | n/a | n/a | n/a | **environment configuration**, not code |

---

## 9. Recommended implementation scope

Strictly from repository evidence — this audit does not invent UI
requirements beyond what the design spec (Section 12) already states.

**MUST HAVE** (smallest useful, safely buildable today):
- Frontend API client functions for all six capabilities in
  `frontend/src/lib/bffApi.ts`, following the exact existing
  `getSessionStatus()` pattern (typed response, `authHeader()`).
- Action buttons on `SessionsPage` for Start/Stop/Restart/Logout, calling
  the existing BFF endpoints, using the existing `useApiQuery`/error-
  state conventions already used everywhere else in the app.
- A way to refresh status after an action resolves (the `useApiQuery`
  hook already exposes `refetch()` — wiring an existing capability, not
  new machinery).
- A QR pairing flow, isolated in a modal per the design spec's explicit
  instruction (Section 12) — this requires building a minimal
  `Modal`/`Dialog` primitive first, since none exists.

**NICE TO HAVE** (would improve the feature, not required to ship a
correct v1 given the current backend contract):
- A `ConfirmDialog` component for Stop/Logout, rather than firing
  immediately on click — the spec recommends confirmation for
  destructive actions but does not mandate a specific component; a
  simpler inline confirm state could satisfy this without a full new
  component if minimizing scope is preferred.
- Client-side double-click guarding (e.g. disabling the button while a
  request is in flight) to reduce, not eliminate, the double-call
  scenario documented in Section 5 — this does not fix the underlying
  lack of BFF-side idempotency, only reduces how often a user
  encounters it.

**NOT READY / SHOULD WAIT**:
- Any change to the BFF's idempotency behavior for lifecycle/QR/pairing
  actions (Section 5's gap) — fixing that is a **backend/BFF behavior
  change**, out of this audit's read-only scope and arguably out of a
  "smallest useful UI" scope too; flagged as a finding, not something to
  silently build around.
- Multi-session UI of any kind (Section 3) — not required, and the
  underlying `list` capability doesn't exist.
- Distinguishing "confirmed failure" from "ambiguous/unknown outcome" in
  the UI for lifecycle actions — the BFF itself doesn't make this
  distinction today (Section 5), so the frontend has no signal to
  surface even if it wanted to.

---

## 10. Roadmap impact

- **Can Session Management safely be implemented before canonical Phase
  8 (Inbox/chat)?** **INFERENCE, well-supported**: yes. It has no
  dependency on `apps.chats`, message history, or any Inbox
  infrastructure — it's a self-contained slice against a completely
  different backend surface (WAHA session lifecycle) that already exists
  end-to-end except for the frontend layer.
- **Does it change or block canonical Phase 8?** **No** — nothing about
  building this touches `chats.*` models, webhook ingestion, or any
  Inbox-related code path. The two are independent.
- **Relationship to canonical Phase 9 (Offline/degraded mode)?** Weak,
  indirect at most: session-management actions would need *some*
  behavior when WAHA/BFF is unreachable, but the existing `502
  waha_unavailable` + `ErrorState` pattern already used throughout this
  app (Dashboard, Sessions status today) already covers that — it does
  not require canonical Phase 9 to exist first. **INFERENCE**.
- **Should any existing roadmap item be modified?** This audit finds no
  evidence requiring a change to `docs/15-CODING-PHASES.md`'s numbering
  or content — implementing canonical Phase 10's frontend slice earlier
  than Phase 8/9 is an *ordering* choice, not a roadmap *content* change.
  That ordering choice is a product/process decision this audit
  surfaces but does not make.

---

## 11. Implementation plan (proposed sequence — NOT executed)

1. Add the six typed BFF client functions to `frontend/src/lib/bffApi.ts`.
2. Wire Start/Stop/Restart/Logout buttons into `SessionsPage.tsx`, reusing
   the existing `Button`/`useApiQuery`/`ErrorState` patterns already
   established on every other page.
3. Build a minimal `Modal`/`Dialog` primitive (none exists), following
   the existing component conventions (`Card`, `Badge`, etc.) and the
   spec's accessibility requirements (Section 16: focus trapping).
4. Build the QR pairing flow inside that modal, calling
   `GET /sessions/:session/qr` and `POST /sessions/:session/pairing-code`.
5. (Nice to have) Add a `ConfirmDialog` or an inline confirm step for
   Stop/Logout.
6. (Nice to have) Add in-flight-disable guarding on action buttons.
7. Update `SessionsPage.tsx`'s own dependency-note comment, since after
   this work the note stating these actions are "scoped to a later
   phase" would no longer be accurate.

Each step is independently small and testable; none requires backend or
BFF changes per Section 9.

---

## 12. Browser acceptance tests to run after implementation

(Provided as a checklist for future use — not run in this task, since
nothing was implemented.)

- Start/Stop/Restart/Logout each succeed against a real, reachable WAHA
  instance with `WAHA_SESSION_NAME` correctly configured, and the status
  display updates afterward.
- Each action correctly shows a loading state while in flight and an
  error state (via the existing `ErrorState`/`describeError` pattern) if
  WAHA is unreachable — verify the message is the existing generic
  "server encountered a problem"-style text, not a raw WAHA error.
- Double-clicking Start/Stop/Restart in quick succession does not crash
  the UI or leave it in an inconsistent state (per Section 5, the BFF
  will simply issue two calls — the UI should at minimum not double-
  render conflicting states).
- QR modal opens, displays either the JSON or image response format
  correctly, and closes cleanly; requesting QR when the session isn't in
  a pairable state shows the mapped 409 as a clear, non-crashing message.
- Pairing-code request with an empty phone number is rejected client-
  side or shows the BFF's 400 cleanly, not a raw error.
- A user with only the `reading` scope (no `session control`) sees the
  BFF's 403 handled gracefully, not a crash — confirms the frontend
  doesn't assume every logged-in user has every scope.
- Confirm the unrelated "Sign out" (JWT/auth logout) button still works
  and is visually distinct from any new "Logout session" (WAHA) control,
  given the naming collision noted in Section 2.
- Dark/light theme and sidebar collapse/expand still work on
  `SessionsPage` after the new controls are added (regression check,
  same as every other browser-acceptance pass this session).

---

## Summary of open questions (not resolved by this audit)

- Whether WAHA itself is idempotent for a repeated start/stop/restart
  call — cannot be determined without a live WAHA instance and is not
  documented anywhere in this repository.
- Exactly which actions require a confirmation dialog per the design
  spec's "where specified by the security/functional contract" clause —
  no document specifies this list concretely.
- Whether the raw WAHA QR/pairing response payload could ever contain
  something sensitive beyond the API key (which is already provably
  excluded) — not verifiable without a live WAHA instance.
- Whether fixing the lifecycle/QR/pairing idempotency gap (Section 5) or
  the ambiguous-timeout-collapse gap should happen before or after the
  frontend work — a product/priority decision, not resolved here.

---

This was a read-only audit. No implementation was performed, no
canonical phase was started or renumbered. Do not proceed automatically
to implementation.
