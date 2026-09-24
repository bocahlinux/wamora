# Phase 9 — Project Roadmap & Next-Phase Audit

**This was a read-only audit.** No source, configuration, `.env`,
dependency, database, migration, infrastructure, test, or other
documentation file was modified while producing this report — the only
output is this file.

**What was inspected** (this task, directly, not relying on memory of
earlier work): `docs/15-CODING-PHASES.md`, `docs/00-MASTER-SPEC.md`,
`wamora-design-assets/docs/WAMORA-FRONTEND-DESIGN-SPEC.md` (full text),
every `frontend/src/pages/*.tsx` file, `frontend/src/components/layout/*`,
every backend Django app's directory listing (`apps/{core, waha_sessions,
chats, webhooks, sync, operations, audit, authn, dashboard}`), the models
and URL configuration of each, `bff/src/routes/*.ts` in full, a
repository-wide grep for `TODO`/`FIXME`/`XXX`/placeholder/mock-data
language, and the prior generated reports under `docs/generated/` for
context on what was already decided and why.

## A finding that shapes this whole report: numbering mismatch

**The canonical phase list in `docs/15-CODING-PHASES.md` has never had a
"Phase 8" completed — and this document's own numbering ("Phase 9") is
therefore ambiguous.** The canonical list is:

```
0. Repository skeleton        8. Inbox/chat
1. Backend foundation         9. Offline/degraded mode
2. Database models+migrations 10. Session management
3. Webhook ingestion          11. Blast
4. Reconciliation             12. Security hardening
5. Celery/Redis               13. Failure/security testing
6. BFF                        14. Production deployment
7. Frontend foundation
```

The work this session has been informally calling "Phase 8" / "Phase 8C"
(dashboard backend foundation — `/api/auth/me/`,
`/api/dashboard/messages/`, `/api/dashboard/activity/` — plus wiring them
into the frontend, plus the BFF CORS/env-loading fixes) was **explicitly
scoped, in the task that started it, as "NOT the full Phase 8 Inbox/chat
implementation"** (`docs/generated/PHASE-8-DASHBOARD-BACKEND-FOUNDATION-REPORT.md`'s
own opening scope note). It's real, tested, working infrastructure — but
it is not the canonical Phase 8, and canonical Phase 8 (Inbox/chat) has
**not been started**: `apps.chats` and `apps.waha_sessions` have no
`urls.py`/`views.py` at all (confirmed by directory listing — Section 1),
and no frontend chat UI exists beyond an honest `EmptyState` placeholder
(`frontend/src/pages/InboxPage.tsx`).

This matters directly for Section 7/8 below: canonical Phase 9
("Offline/degraded mode") is about degrading *existing* durable-data
features gracefully when the office server is unreachable — but the
main durable-data feature that spec names (chat/message history) doesn't
exist yet to degrade. Read Section 7 before assuming "Phase 9" is
next.

---

## 1. Current product surface

### Authentication
- **Implemented and functional**: Django login (`POST /api/auth/login/`,
  RS256 JWT), `GET /api/auth/me/` (identity), frontend login page,
  `sessionStorage` token storage, 8h-expiry client-side logout,
  logout button. Both Django and the BFF independently verify the same
  JWT (confirmed working end-to-end this session, including a BFF env-
  loading defect found and fixed).
- **Broken/unverified**: none found.
- **Backend-only, unused by frontend**: JWT `scopes` claim
  (`compute_scopes()`, `apps/authn/jwt_utils.py`) is issued but the
  frontend never reads or branches on it (e.g. to hide nav items a user
  lacks scope for) — `frontend/src/lib/auth.ts`'s `decodeToken()` exists
  and could support this, but nothing calls it for authorization
  decisions today.

### Dashboard
- **Implemented and functional**: Row 1 health cards (WAHA via BFF,
  Backend, PostgreSQL — all real), Row 2 Messages card (real count +
  24-hour trend) and Activity card (real merged `AuditLog`/`WebhookEvent`
  feed), both backed by real Django endpoints, manually browser-verified
  this session (`docs/generated/PHASE-8C-BROWSER-ACCEPTANCE-REPORT.md`).
- **Placeholder/EmptyState**: WhatsApp Sessions summary card (Row 2's
  third slot) — intentional, documented dependency on BFF multi-session
  support that doesn't exist.
- **Implemented but incomplete relative to the design spec**: no Redis
  health card (spec Section 10 lists WAHA/Backend/PostgreSQL/**Redis**
  for Row 1; no Redis health endpoint exists anywhere in the backend —
  confirmed by `apps/core/urls.py` only exposing `/health/` and
  `/health/database/`), no Row 3 ("trends, reconciliation/sync
  indicators, operational metrics, future reports").

### Sessions
- **Implemented but incomplete**: `SessionsPage.tsx` shows real,
  live status for one configured session
  (`GET /api/sessions/:session/status`, via the BFF) — read-only.
- **Backend-only, unused by frontend** (a significant finding — see
  Section 3): the BFF already implements the **entire** session
  lifecycle control surface — `POST /api/sessions/:session/start`,
  `/stop`, `/restart`, `/logout`, `GET /qr`, `POST /pairing-code`
  (`bff/src/routes/session.ts`) — none of it is wired into any frontend
  button. `SessionsPage.tsx`'s own comment confirms this is deliberate,
  deferred to canonical Phase 10 ("session management").
- **Intentionally deferred**: multi-session summary/list (only one
  session name is configurable BFF-side —
  `bff/src/routes/sessionGuard.ts` rejects any `:session` other than the
  single configured `WAHA_SESSION_NAME`).

### WhatsApp
- **Placeholder/EmptyState** (`WhatsAppPage.tsx`) — explicitly flagged in
  its own code comment as having no defined scope in any functional doc,
  distinct from Dashboard/Sessions/Inbox. Confirmed: neither
  `docs/00-MASTER-SPEC.md` nor the design spec define what this page
  should contain beyond what the other three pages already cover.

### Health/status monitoring
- **Implemented and functional**: backend liveness, database
  reachability, BFF process + WAHA reachability — all real, all
  independently checkable, all currently exercised by the Dashboard.
- **Not implemented**: Redis health (Celery broker/result backend — see
  Section 5).

### Navigation
- **Implemented and functional**: all six sidebar items route
  correctly, active-state highlighting, collapse/expand (manually
  browser-verified), mobile drawer behavior present in code
  (`Sidebar.css`'s `@media (max-width: 1023px)` block) but not called
  out as separately browser-tested in any report on file.

### Settings
- **Placeholder/EmptyState** — explicitly flagged as having no backing
  API "in any coding phase completed so far."

### Account/user functionality
- **Implemented and functional**: real identity display (`/me/`),
  sign-out.
- **Not implemented**: no profile editing, no password change, no
  user-administration UI — consistent with Settings being an unstarted
  area and with `docs/00-MASTER-SPEC.md` not naming user-facing account
  management as a v1 feature.

### Backend APIs (Django)
| App | Endpoints | Status |
|---|---|---|
| `core` | `/api/health/`, `/api/health/database/` | Functional |
| `authn` | `/api/auth/login/`, `/api/auth/me/` | Functional |
| `dashboard` | `/api/dashboard/messages/`, `/api/dashboard/activity/` | Functional |
| `webhooks` | `/api/webhooks/waha/` | Functional (inbound only) |
| `audit` | `/internal/audit-events/` (BFF-only, internal key) | Functional |
| `operations` | `/internal/outbound-operations/`, `/internal/outbound-operations/<id>/` (BFF-only, internal key) | Functional |
| `chats` | **none** | **No HTTP API at all** — models exist, nothing exposes them |
| `waha_sessions` | **none** | **No HTTP API at all** |
| `sync` | none (Celery task + management command only, no HTTP surface) | Functional as a background job, not web-exposed by design |

### BFF APIs (Node/Express)
| Route | Status |
|---|---|
| `GET /health` | Functional |
| `GET /api/sessions/:session/status` | Functional, used by frontend |
| `POST /api/sessions/:session/start`\|`/stop`\|`/restart`\|`/logout` | **Implemented, not used by frontend** |
| `GET /api/sessions/:session/qr` | **Implemented, not used by frontend** |
| `POST /api/sessions/:session/pairing-code` | **Implemented, not used by frontend** |
| `POST /api/sessions/:session/messages` (send text, full idempotency state machine) | **Implemented, not used by frontend** |

---

## 2. Design/reference requirements — fulfilled vs. not

Source: `wamora-design-assets/docs/WAMORA-FRONTEND-DESIGN-SPEC.md` (read
in full this task, not from memory).

**Fulfilled:**
- Brand name "WAMORA" used consistently; no reversion to the old generic
  name (grep-confirmed absent from `frontend/src`).
- Color tokens, typography scale, spacing scale, radius/shadow — all
  defined as CSS custom properties in `frontend/src/styles/tokens.css`,
  matching the spec's Section 4/5 values exactly (verified earlier this
  session, Phase 7 visual-fidelity pass).
- Lucide icon family used exclusively (no mixed icon families found in
  any grep this session).
- Sidebar nav order (Dashboard, WhatsApp, Inbox, Sessions, Reports,
  Settings) matches spec Section 7 exactly.
- StatusBadge = icon + text + color (spec Section 9's "not color alone"
  rule).
- Dark mode as a first-class theme, semantic colors unchanged across
  themes, no pure-black background — matches spec Section 13
  (`tokens.css`'s dark-mode block).
- Dashboard Row 1 (spec Section 10) — WAHA/Backend/PostgreSQL cards
  present and real.

**Partially fulfilled:**
- Dashboard Row 2 (spec Section 10) — 2 of 3 recommended cards are real
  (messages today/volume, activity feed); the third (sessions summary)
  is an honest placeholder, not fabricated, but not delivered either.
- Header (spec Section 7 "Recommended: page/search context, global
  search, notifications, theme toggle, user/profile menu") — theme
  toggle exists; global search, notifications, and an explicit
  user/profile *menu* (as opposed to the sidebar's own identity area) do
  not.
- Responsive design (spec Section 14) — mobile/tablet CSS rules exist in
  source for the sidebar and page layout, but no report on file claims
  they were checked at an actual narrow viewport in a browser.

**Not yet implemented (spec sections with zero corresponding code):**
- Section 11, Inbox/chat visual direction (3-pane layout) — nothing
  built; `InboxPage.tsx` is a placeholder.
- Section 12, Session management visual direction (action buttons,
  confirmation dialogs, QR modal) — nothing built, despite the BFF
  already supporting every action this section describes (Section 1
  above).
- Dashboard Row 3+ ("trends, reconciliation/sync indicators, operational
  metrics, future reports") — nothing built.
- Several named-but-unbuilt core UI components (spec Section 8):
  `SearchInput`, `Select`, `Tabs`, `Modal/Dialog`, `Drawer`, `Dropdown`,
  `Tooltip`, `Toast/Notification`, `DataTable`, `ConfirmDialog`,
  `Pagination` — none of these exist under
  `frontend/src/components/ui/` today (confirmed by directory listing:
  only `Button`, `IconButton`, `Input`, `Card`, `Badge`, `StatusBadge`,
  `LoadingState`, `EmptyState`, `ErrorState`, `PageHeader` exist). Any
  future phase touching Inbox, session actions, or a data table will
  need to build some of these first.

---

## 3. Frontend → API/BFF → Backend → data-source mapping

| Feature | Frontend | BFF | Django | Data source |
|---|---|---|---|---|
| Login | `LoginPage` | — | `POST /api/auth/login/` | `auth.User` |
| Identity | `Sidebar` | — | `GET /api/auth/me/` | `auth.User` |
| WAHA health | `DashboardPage` | `GET /health` | — | live WAHA ping |
| Backend/DB health | `DashboardPage` | — | `GET /api/health/`, `/database/` | Django process / `SELECT 1` |
| Messages today/trend | `DashboardPage` | — | `GET /api/dashboard/messages/` | `chats.Message` |
| Activity feed | `DashboardPage` | — | `GET /api/dashboard/activity/` | `audit.AuditLog` + `webhooks.WebhookEvent` |
| Session status (read) | `SessionsPage` | `GET /sessions/:s/status` | — | live WAHA |
| **Session start/stop/restart/logout/QR/pairing** | **none** | `bff/src/routes/session.ts` (complete) | `AuditLog` via internal audit-events endpoint | live WAHA — **existing capability, no UI** |
| **Send message** | **none** | `POST /sessions/:s/messages` (complete, idempotent) | `operations.OutboundOperation` via internal endpoints | live WAHA + durable record — **existing capability, no UI** |
| Chat list / message history | **none** | — | **none** | `chats.Chat`/`chats.Message` exist but have zero HTTP exposure |
| Webhook ingestion (inbound) | — | — | `POST /api/webhooks/waha/` | writes `chats.*`, `webhooks.WebhookEvent` |
| Reconciliation | — | — | Celery task, no HTTP surface | `chats.*` via `apps.sync.reconciliation` |

**Existing backend capability that could support currently-unfinished
UI, found this task:**
- The entire BFF session-control surface (start/stop/restart/logout/QR/
  pairing) is implemented, tested (per the BFF's own test suite,
  `bff/test/routes.session.test.ts` was listed among the 9 test files
  this session's earlier work ran green), and completely unused by the
  frontend. This is the single largest "backend already exists, UI
  doesn't" gap in the repository.
- The BFF's send-message endpoint (`POST /sessions/:session/messages`)
  is fully built with the exact idempotency contract
  `docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md` Section 9
  describes, and is also completely unused.

**Duplicated functionality**: none found.

**Dead/unreachable code**: none found — every route/view/component
inspected is reachable from at least one real entry point (a URL
pattern, an Express router mount, or a rendered page).

**Placeholders whose backend already exists**: the session-management UI
gap above is exactly this case — the placeholder is purely a frontend
scope boundary, not a missing backend.

---

## 4. TODO/FIXME/placeholder inventory

A repository-wide, case-insensitive search for `TODO`, `FIXME`, `XXX`,
"not implemented", "coming soon", "placeholder", "mock data", "demo
data" found:

- **No literal `TODO`/`FIXME`/`XXX` comment anywhere** in `frontend/src`,
  `backend/`, or `bff/src` (grep returned zero matches for that specific
  pattern set — this codebase's convention throughout this session has
  been to write a full explanatory comment citing the relevant doc/phase
  instead of a bare TODO marker).
- `frontend/src/pages/{InboxPage,WhatsAppPage,ReportsPage,SettingsPage,PlaceholderPage}.tsx`
  — all genuinely unfinished, each with its own comment stating exactly
  why (no backend/no spec) and which phase is expected to complete it.
  Classified: **genuinely unfinished + intentionally deferred** (not
  obsolete, not stale — each still accurately describes the current
  state, confirmed by this task's own independent re-inspection of the
  backend, not just trusting the comment).
- `frontend/src/pages/DashboardPage.tsx` — the third Row 2 card
  (`EmptyState`, "WhatsApp Sessions … Not available yet"). Classified:
  **intentionally deferred**, matches Section 1's sessions-summary
  finding.
- `frontend/src/components/ui/Input.tsx`/`.css` — matched the grep only
  because of the word "placeholder" used in its literal HTML/CSS sense
  (an `<input placeholder="...">` attribute), not a code placeholder.
  Classified: **false positive, not a gap**.
- `frontend/src/routes/AppRoutes.tsx`, `frontend/src/components/layout/Sidebar.tsx`
  — matched only via their own comments *referencing* the placeholder
  pages above (e.g. "no route exists for functionality belonging to a
  later phase beyond a placeholder shell"). Classified: **descriptive,
  not a separate gap**.
- No hardcoded value anywhere in `frontend/src` was found that
  represents future functionality masquerading as real data — every
  numeric/status value traced back to a real API response this session
  (Dashboard) or in prior sessions (health cards, session status).

---

## 5. Architectural gaps

- **Chat/message read API does not exist.** `apps.chats` has models
  (`Contact`, `Chat`, `Message`, `MediaReference` — confirmed via
  `apps/chats/models.py` and its test file) but zero `urls.py`/`views.py`.
  This is the single largest blocker to canonical Phase 8.
- **No "read/unread" data model.** `docs/00-MASTER-SPEC.md` lists "mark
  as read" as a core feature, but neither `Message` nor `Chat` has any
  field representing read state (confirmed by reading the full model
  file). Any Inbox implementation will need to decide and add this —
  not something this audit invents a value for.
- **BFF is single-session by construction**
  (`bff/src/routes/sessionGuard.ts` rejects any session name other than
  the one configured `WAHA_SESSION_NAME`). The Dashboard's sessions-
  summary card and any multi-session UI both depend on this changing.
- **No Redis health endpoint.** Celery/Redis are configured
  (`CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` — confirmed as
  configured *names* in `backend/.env`, not read for values) and
  actively used by the reconciliation task, but nothing checks/reports
  Redis reachability, unlike the symmetric Database/Backend health
  checks that already exist. This is a small, self-contained gap (see
  Section 6).
- **JWT has no refresh mechanism** (documented, not new — `frontend/src/lib/auth.ts`'s
  own comment: "The 8-hour access token has no refresh mechanism in
  v1"). Not a bug, a known v1 limitation from the Phase 6 contract.
- **Rate limiting is deferred to Phase 12** (`LoginView`'s own comment;
  confirmed still true — no rate-limiting code found anywhere in
  `backend/` or `bff/` this task).
- **No fine-grained per-user data authorization model** — every
  authenticated user sees every `Message`/`AuditLog`/`WebhookEvent` row;
  documented as a known, deliberate posture in the Phase 8 backend
  foundation report, re-confirmed unchanged by this audit's own
  re-reading of the dashboard views.
- **Two known-but-unfixed missing indexes** (from the Phase 8 backend
  foundation report, re-confirmed present in the current model files):
  `chats.Message` has no index supporting a chat-agnostic `timestamp`
  filter (only `(chat, timestamp)`); `webhooks.WebhookEvent` has no index
  on `received_at` (only `status`). Both were explicitly reported, not
  silently added, and remain open.
- **Local dev configuration gaps** (operational, not code — found and
  partially fixed this session): `bff/.env`'s `WAHA_SESSION_NAME` and
  `INTERNAL_SERVICE_KEY` are present as variable names but empty of
  value in this environment (confirmed in
  `docs/generated/PHASE-8C-BFF-ENV-LOADING-FIX-REPORT.md` Section 14) —
  this blocks live-testing session control and BFF→Django internal
  calls locally, though it does not affect the reviewed source code's
  correctness.
- **`CORS_ALLOWED_ORIGIN`/`CORS_ALLOWED_ORIGINS` are single-origin only**
  on both Django and the BFF (a comma-split list is supported by the
  BFF's `buildCorsOptions()`, but only one origin is currently
  configured in this dev environment) — fine for one dev frontend
  instance, worth remembering if multiple environments need to reach the
  same backend simultaneously.
- **Error handling/loading/empty states**: consistently implemented
  across every page inspected this task (`useApiQuery` +
  `LoadingState`/`ErrorState`/`EmptyState`, used uniformly) — **not** a
  gap; called out here because the task asked me to check.

---

## 6. Candidate next phases

Presented as alternatives with factual dependencies — not ranked.

### A. Canonical Phase 8 — Inbox/chat

- **Purpose**: chat list, message history, receive/send/reply, mark as
  read (`docs/00-MASTER-SPEC.md`'s own feature list).
- **Builds upon**: `chats.Contact`/`Chat`/`Message`/`MediaReference`
  models (already exist), webhook ingestion (already writes to these
  tables), the BFF's already-built, already-tested send-message endpoint.
- **Backend work required**: new Django read endpoints (chat list,
  message list per chat) under `apps.chats` — no `urls.py`/`views.py`
  exists yet, so this is new-app-surface work, not a tweak. A "mark as
  read" data model decision and endpoint.
- **BFF work required**: none for sending (already done); possibly wiring
  the existing send endpoint into whatever contract the new Inbox UI
  expects.
- **Frontend work required**: the entire 3-pane Inbox UI (spec Section
  11), several core components that don't exist yet
  (`Tabs`/`SearchInput` at minimum for chat list search/filter).
- **Database/migration impact**: likely a new field/table for read
  state; otherwise reuses existing tables.
- **Dependencies**: none blocking — all prerequisite data already flows
  in via webhook ingestion.
- **Risks**: "mark as read" semantics aren't specified beyond the one
  phrase in the master spec — needs a product decision (per-message?
  per-chat? synced with WAHA's own read receipts, if any exist?) before
  implementation, not an engineering risk.
- **Independently implementable**: yes.
- **What must be decided first**: the read/unread data model; whether
  message history depth is bounded (pagination — no `Pagination`
  component exists yet either).

### B. Canonical Phase 10 — Session management (UI only; BFF already done)

- **Purpose**: start/stop/restart/logout/QR pairing UI (spec Section 12).
- **Builds upon**: the BFF's complete, tested, already-implemented
  lifecycle endpoints (Section 1/3 above) — this is almost entirely a
  frontend task.
- **Backend work required**: none identified.
- **BFF work required**: none — already built.
- **Frontend work required**: action buttons on `SessionsPage`, a
  confirmation dialog for destructive actions (`ConfirmDialog` doesn't
  exist yet), a QR pairing modal (`Modal/Dialog` doesn't exist yet).
- **Database/migration impact**: none.
- **Dependencies**: none blocking.
- **Risks**: low — the hard part (idempotent, audited backend actions)
  is already done and tested; the remaining work is UI wiring and the
  two missing dialog/modal components.
- **Independently implementable**: yes, and notably **cheaper than
  Phase 8** since almost no backend work remains.
- **What must be decided first**: confirmation-dialog copy/UX for
  destructive actions (logout/stop) — not a technical blocker.

### C. Canonical Phase 9 — Offline/degraded mode

- **Purpose**: define and surface degraded states when the office server
  (Django/PostgreSQL) is unreachable while Tencent/WAHA stays up
  (`docs/00-MASTER-SPEC.md` "Availability").
- **Builds upon**: the existing health-check separation (backend vs.
  database vs. WAHA already report independently) is a solid foundation.
- **Backend work required**: unclear — depends on which *durable*
  features need degraded-mode UX, and the main durable feature
  (chat/message history) doesn't exist as a UI yet (Phase A above).
- **Risks**: implementing this before Phase 8 means designing
  degradation for a feature surface that isn't built, which risks
  guessing at requirements rather than deriving them from a real
  feature.
- **Independently implementable**: partially — the Dashboard's existing
  health cards already demonstrate the pattern; a *fuller* offline mode
  is hard to scope without Phase 8 existing first.
- **What must be decided first**: whether "offline/degraded mode" means
  (i) extending the existing health-card pattern to more surfaces, or
  (ii) a broader UX for every durable-data page going dark — the latter
  needs Phase 8 to exist first to have a concrete surface to degrade.

### D. Small, self-contained — Redis health card

- **Purpose**: complete the Dashboard's Row 1 exactly as specified
  (spec Section 10 names 4 cards; 3 exist).
- **Builds upon**: the exact existing pattern of
  `DatabaseHealthView`/`LivenessView` (`apps/core/views.py`) — a new
  `RedisHealthView` following the same shape, using the already-
  configured `CELERY_BROKER_URL`.
- **Backend work required**: one new view + URL, minimal.
- **BFF work required**: none.
- **Frontend work required**: one new `HealthCard` call, following the
  exact existing `DashboardPage.tsx` pattern for the other three.
- **Database/migration impact**: none.
- **Dependencies**: none.
- **Risks**: minimal — smallest-scoped candidate in this list.
- **Independently implementable**: yes, and could be done alongside any
  other candidate without conflict.
- **What must be decided first**: nothing technical; purely whether it's
  worth a dedicated small task or bundled into a larger one.

### E. Reports / Settings / WhatsApp overview / Notifications / Search

- **Purpose**: unclear — **no functional specification exists for any of
  these** (confirmed: `docs/00-MASTER-SPEC.md` doesn't name them beyond
  the sidebar nav order in the visual spec; `WhatsAppPage.tsx`,
  `ReportsPage.tsx`, `SettingsPage.tsx`'s own comments already say this).
- **What must be decided first, for all of these**: product requirements
  don't exist yet. This audit does not invent them. Not a candidate for
  implementation until someone defines what each page is actually for.

---

## 7. Is Phase 9 (canonically numbered) ready to implement?

**A. Is there enough information in the repository to define a concrete
Phase 9 implementation task?**

**No, not as the canonically-numbered "Offline/degraded mode" phase.**
The repository has enough information to define canonical **Phase 8**
(Inbox/chat) or canonical **Phase 10** (Session management) concretely —
both have clear feature descriptions in `docs/00-MASTER-SPEC.md` and, for
Phase 10 particularly, nearly all the backend work already exists.
Canonical Phase 9 (Offline/degraded mode) depends on a durable-data
feature surface (chat/message history) that doesn't exist as a UI yet —
defining "what should this look like when it goes offline" for a screen
that isn't built would mean guessing at a UI that hasn't been designed,
which this audit was explicitly told not to do.

**C. Decisions required before canonical Phase 9 specifically:**
1. Does "Phase 9" in this task's title mean the literal, canonically-
   numbered "Offline/degraded mode" phase, or does it mean "whatever
   phase comes next in practice"? This report cannot resolve that
   ambiguity on its own — it's a product/process decision, not a
   technical one.
2. If it does mean the canonical phase: which durable-data feature(s)
   should have offline/degraded UX defined first? Without Phase 8
   (Inbox/chat) existing, there's no concrete feature surface to design
   degradation for beyond what the Dashboard's health cards already do.
3. If "next phase" is meant loosely: a decision between Candidate A
   (Inbox/chat — larger, matches the master spec's most-named feature
   set) and Candidate B (Session management — smaller, backend already
   built) is a genuine product/priority call this audit does not make
   for you.

## 8. Proposed specification

Per Section 7: the evidence does not support a concrete canonical Phase
9 implementation task right now.

**PHASE 9 BLOCKED — DECISIONS REQUIRED**

1. Confirm whether "next phase" means the canonical numbering
   (`docs/15-CODING-PHASES.md` item 9, "Offline/degraded mode") or the
   next practical phase regardless of number.
2. If canonical numbering: canonical **Phase 8 (Inbox/chat)** must be
   decided and scoped first — Phase 9 depends on a durable-data feature
   existing to degrade.
3. If proceeding out of canonical order: choose between Candidate A
   (Inbox/chat) and Candidate B (Session management) from Section 6 —
   both are concretely specifiable from what's already in the
   repository, but which one to build first is a product priority
   decision, not something this audit will choose silently.
4. For whichever is chosen, the specific open sub-decisions from Section
   6 (read/unread semantics for Inbox; confirmation-dialog UX for
   Session management) still need an answer before implementation
   begins.

## 9. What remains uncertain

- Whether "Phase 9" in this task's own title was meant literally or
  loosely (Section 7).
- The intended semantics of "mark as read" (Section 5/6A) — the master
  spec names the feature but not its data model.
- Whether the WhatsApp/Reports/Settings pages have any planned scope at
  all, or whether they're placeholders for a future product decision not
  yet made (Section 6E) — nothing in the repository answers this.
- Whether multi-session support (needed for the Dashboard's sessions
  summary and any future multi-session BFF work) is still a real v1
  goal — `docs/00-MASTER-SPEC.md` says "Awal: 1 session, kemungkinan
  maksimal 2–3," which reads as a soft future possibility, not a
  committed near-term requirement; this audit does not resolve that
  ambiguity.

---

This was a read-only audit. No implementation was performed. Do not
proceed automatically after this report.
