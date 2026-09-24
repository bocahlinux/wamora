# Dashboard Data & UI Gap Audit

Read-only. No source code, configuration, `.env`, dependency, database,
migration, API contract, or infrastructure was modified. This is an
audit/planning document only — nothing described here as "missing" was
built. Despite the filename prefix, this is **not** the start of
coding-Phase 8 ("Inbox/chat" per `docs/15-CODING-PHASES.md`) — it's a
diagnostic round about Dashboard/Topbar data gaps specifically, at your
own request.

## 1. Design source of truth (re-read directly, not from memory)

`wamora-design-assets/docs/WAMORA-FRONTEND-DESIGN-SPEC.md`, Sections 7
("Header"), 9 ("Status visualization"), 10 ("Dashboard visual
structure") — quoted verbatim, not paraphrased from an earlier round:

- **Header** ("Recommended," not mandatory): "page/search context,
  global search where applicable, notifications, theme toggle,
  user/profile menu."
- **Dashboard Row 1 — system health**: WAHA, Backend/Django, PostgreSQL,
  Redis; each card: system icon, status, short operational detail,
  optional latency/last-check.
- **Dashboard Row 2 — sessions + activity**: WhatsApp sessions summary,
  messages today / message volume, system activity feed.
- **Row 3+**: trends, reconciliation/sync indicators, operational
  metrics, future reports.

The reference boards (`assets/reference/*.png`) show these rendered
with real-looking numbers (`1,284` messages, `+12%`, a bar chart, a
timestamped activity list) — the design package's own README already
states these boards are "visual references, not pixel-perfect
implementation screenshots," so the exact numbers shown are
illustrative, not a data contract.

## 2. Existing frontend implementation (re-inspected directly)

| Layer | Files | Covers |
|---|---|---|
| API clients | `frontend/src/lib/bffApi.ts` | `getBffHealth()`, `getSessionStatus(session)` — 2 functions, both already used |
| | `frontend/src/lib/djangoApi.ts` | `getBackendHealth()`, `getDatabaseHealth()` — 2 functions, both already used |
| | `frontend/src/lib/auth.ts` | `login()` only — no "get current user" call exists |
| Hooks | `frontend/src/lib/useApiQuery.ts` | Generic loading/success/error state machine — reusable as-is for any new endpoint |
| Auth state | `frontend/src/lib/AuthContext.tsx` | Decodes the JWT client-side for `sub`/`scopes`/`exp` only — **no username/display-name is available anywhere**, because the JWT doesn't carry one (contract-confirmed, Section 3 below) |
| Pages | `DashboardPage.tsx` | Row 1 only (3 of the 4 design cards — Redis omitted, already documented) |
| | `SessionsPage.tsx` | Single hardcoded session's live status only (`config.wahaSessionName`) — not a list |
| | `WhatsAppPage.tsx`, `InboxPage.tsx`, `ReportsPage.tsx`, `SettingsPage.tsx` | `EmptyState` placeholders, no data fetching |
| Layout | `TopBar.tsx` | Menu toggle + theme toggle only — no search input, no notification bell, no avatar/user menu exist in the component at all (confirmed by reading the file directly, not inferred) |
| | `Sidebar.tsx` | Has a generic `User` icon + "Signed in" text + sign-out button — the only "identity" UI anywhere in the app, and it's static text, not derived from any profile data |

**No frontend type/interface for sessions-summary, messages-today,
message-trend, activity-feed, notification, or search exists anywhere**
— checked directly (`grep` across `frontend/src` for each concept):
confirmed absent, not merely unused.

## 3. Backend/BFF audit — what data actually exists

Checked directly: which Django apps have a `views.py`/`urls.py` at all
(not assumed from the data model).

| App | Has `views.py`/`urls.py`? | User-facing (non-internal) endpoints |
|---|---|---|
| `apps.core` | Yes | `GET /api/health/`, `GET /api/health/database/` |
| `apps.authn` | Yes | `POST /api/auth/login/` only — **no `/me`/profile endpoint** |
| `apps.webhooks` | Yes | Webhook ingestion only (WAHA→Django, not frontend-facing) |
| `apps.operations` | Yes | **Internal only** (`HasInternalServiceKey`-gated, BFF-to-Django) |
| `apps.audit` | Yes | **Internal only** (same gating) |
| `apps.waha_sessions` | **No `views.py`/`urls.py` at all** | None |
| `apps.chats` | **No `views.py`/`urls.py` at all** | None |
| `apps.sync` | No `views.py`/`urls.py` | None (Celery tasks + management command only) |

BFF (`bff/src/app.ts` + every file under `bff/src/routes/`, enumerated
directly): exactly 8 routes exist —
`GET /health`, `GET/POST /api/sessions/:session/{status,start,stop,restart,logout,qr,pairing-code}`,
`POST /api/sessions/:session/messages`. **No sessions-list, no
dashboard-aggregate, no notifications, no search route exists.** The
BFF is architecturally scoped to exactly one configured session
(`WAHA_SESSION_NAME`) — confirmed in `bff/src/config.ts` and
`sessionGuard.ts` — not a list of sessions.

### Per Row-2/Topbar item

- **WhatsApp sessions summary (total/active count)**: `WahaSession`
  model (`apps/waha_sessions/models.py`) has `name`, `status`,
  `last_status_at` — rows exist (created via `get_or_create` in webhook
  ingestion and the Phase 6 internal endpoints). **But `status` is never
  actually updated by anything**: `apps/webhooks/parsing.py`'s
  `SUPPORTED_EVENT_TYPES = {'message'}` — `session.status` webhook
  events are received (when the webhook target is even correctly
  configured, which it currently isn't — a pre-existing, separately
  documented gap) but marked `unsupported` and dropped; reconciliation
  never touches `WahaSession.status` either (checked
  `apps/sync/reconciliation.py` directly — it only updates
  `SyncCheckpoint.status`). **The real-time status genuinely does exist,
  but only live, per-session, via the BFF's already-built
  `GET /api/sessions/:session/status`** — not as a durable, queryable
  Django aggregate. → **Category B** (data source exists, but stale on
  the Django side; real-time data exists but only per-session, not as a
  list, since the BFF isn't multi-session-aware yet).
- **Messages today / message volume**: `Message` model
  (`apps/chats/models.py`) has `timestamp`, `direction`, `session` —
  real rows, populated by webhook ingestion and reconciliation. A
  `count(timestamp >= today)` query is a legitimate aggregate over real
  data. → **Category B** (data exists, no API).
- **Message trend/chart**: same `Message.timestamp` field could support
  a time-bucketed count query. → **Category B**.
- **System activity feed**: no dedicated "activity" model exists, but
  `AuditLog` (actor, action, target, result, `created_at`) and
  `WebhookEvent` (session, event_type, received_at, status) both hold
  real, already-populated rows that could serve as an activity feed
  (`AuditLog` for BFF-initiated actions like session start/stop;
  `WebhookEvent` for inbound WAHA activity). → **Category B**.
- **Current authenticated user / profile**: the JWT's only identity
  claim is `sub` (a numeric Django user PK — confirmed in
  `apps/authn/jwt_utils.py`'s `issue_access_token`, no
  username/email/display-name claim is added). The underlying
  `django.contrib.auth.User` row is real and has a real username, but
  **no endpoint returns it** to the frontend. → **Category B**.
- **Notifications / unread count**: no model, no field, no concept of a
  "notification" exists anywhere in any app's `models.py` — checked all
  eight apps directly. → **Category C**.
- **Search**: no search index, no search service, no search-related
  model or endpoint anywhere. → **Category C**.
- **Redis (Row 1's 4th card, already omitted per the Phase 7 report)**:
  still no Redis health-check code anywhere. → **Category C**, restated
  for completeness, not re-litigated.

## 4. API/UI mapping table

| Design element | Frontend component | Existing API | Real data available | Additional backend work | Safe to implement now |
|---|---|---|---|---|---|
| Sessions summary | *(none — not built)* | None | **Partially** — live per-session via BFF; Django-side `WahaSession.status` is stale/unmaintained | New Django or BFF endpoint; BFF is single-session-scoped today, so a true multi-session summary also needs that extended | **No** |
| Messages today | *(none)* | None | **Yes** (`Message` rows are real) | New Django aggregate endpoint | **No** |
| Message chart | *(none)* | None | **Yes** (same table) | New Django time-bucketed aggregate endpoint | **No** |
| Activity feed | *(none)* | None | **Yes** (`AuditLog`/`WebhookEvent` rows are real) | New Django list endpoint | **No** |
| User/avatar | Sidebar's static `User` icon + "Signed in" text | None | **Yes** (real `auth.User` row), but no claim/endpoint exposes it | New Django `/api/auth/me/`-style endpoint (or add a claim to the JWT) | **No** |
| Notifications | *(none)* | None | **No** | New model + write path + read API — the largest of these gaps | **No** |
| Search | *(none)* | None | **No** | New search mechanism entirely | **No** |

**Every Row 2/Topbar item requires at least one new backend (Django) or
BFF endpoint before any frontend work on it would display real data.**
None can be implemented frontend-only right now without either
fabricating data (explicitly forbidden) or shipping a non-functional
control (already avoided in the Phase 7 pass).

## 5. Is the BFF boundary being respected?

**Yes — checked against the standing architecture, not assumed.**
`docs/00-MASTER-SPEC.md`'s "Ownership" section (already the basis for
the Phase 6 chat/message source-of-truth decision) is unambiguous:
*"WAHA: live WhatsApp/session state. PostgreSQL: durable ... chats/messages
..."* This means:

- **Messages today, message chart, activity feed** (durable,
  PostgreSQL-owned data) → belong on a **new Django endpoint**,
  `Frontend → Django` directly — the same existing path
  `docs/07-API-CONTRACT.md` already documents, not the BFF. This is not
  a new architectural decision; it's the same one already made for
  chat/message history in `docs/generated/PHASE-6-BLOCKER-RESOLUTION.md`.
- **Current user/profile** → Django-owned (`auth.User`) → `Frontend →
  Django`, analogous to the existing `/api/auth/login/`.
- **Sessions summary** → genuinely mixed: real-time correctness can only
  come from WAHA (BFF), but a *summary across sessions* needs the BFF to
  know about more than the one session it's currently scoped to. This
  is the one item that isn't a clean "add a Django endpoint" — it's a
  BFF architecture extension already anticipated (`docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md`
  Section 6: *"extending to 2–3 sessions later means adding a lookup,
  not redesigning anything"*) but not yet done.

**No architectural change is being proposed here beyond what's already
documented as anticipated.**

## 6. Missing backend capabilities — exact list

1. **Django**: a list/read endpoint over `Message` for "count today" +
   a time-bucketed trend query. No new model or migration needed.
2. **Django**: a list/read endpoint over `AuditLog`/`WebhookEvent` for
   an activity feed. No new model or migration needed.
3. **Django**: a `/me`-style endpoint (or a JWT claim addition) exposing
   the authenticated user's username/display name. No new model needed;
   a JWT claim change would touch `apps/authn/jwt_utils.py`
   (`issue_access_token`) specifically.
4. **BFF (+ Django, for provisioning)**: multi-session awareness — a way
   for the BFF to report on more than one configured session, needed for
   a true "sessions summary." Bigger than the other three; explicitly
   flagged as its own item, not bundled in.
5. **A new `Notification` model + write path + read API** — nothing
   currently produces or stores a notification of any kind. The largest
   gap of the six.
6. **A search mechanism** — no existing model, index, or service
   supports this at all today.

None of these were built or started this round.

## 7. Current dashboard vs. design — structured

### Already implemented correctly
- Row 1 health cards (WAHA/Backend/PostgreSQL) — real data, real
  endpoints, correct visual treatment per the Phase 7 pass.
- Sidebar navigation, theme system, application shell — match the
  design's Section 7 structural requirements.

### Implementable now with real data
**None found beyond what's already built.** Every remaining Row
2/Topbar item requires new backend work first (Section 4).

### Requires backend/BFF work first
- Messages today, message chart, activity feed, user/profile display,
  sessions summary — all six items in Section 6.

### Design-only / intentionally deferred
- Notifications and search specifically — no data source exists at all
  (Category C), meaningfully different from the other four (Category
  B, "just" needs an endpoint over already-real data). These two need a
  product decision on scope before backend work even starts, not just
  an implementation task.
- The Redis Row-1 card — same category, restated from the Phase 7
  report.

## 8. Constraints honored

No number, session, message count, activity event, notification, or
search result was invented anywhere in this document or elsewhere this
round. No backend, frontend, `.env`, dependency, or migration file was
touched.

## 9. Recommended implementation sequence

**Phase 8A — frontend-only work safely doable now: minimal.** Honestly,
there isn't substantial frontend-only work left for the Dashboard/Topbar
specifically — the Phase 7 visual pass already closed the styling gaps
that didn't require data. Doing more frontend work here now would mean
either fabricating data or building a control with nothing behind it,
both explicitly out of bounds. (Non-dashboard frontend work, e.g.
polishing the `Reports`/`Settings` placeholder copy, is possible but
wasn't what this audit was asked to scope.)

**Phase 8B — backend/BFF work required before more UI can be built**,
recommended in this order:

1. **Django `/me` endpoint or JWT claim** (item 3) — smallest, most
   self-contained, and unblocks the Topbar's user/profile area, which
   the design spec lists first among header items.
2. **Django messages-today + activity-feed endpoints** (items 1–2) —
   both read over already-real, already-durable data; no schema change;
   naturally grouped since both are "Django owns this data" reads.
3. **BFF multi-session support** (item 4) — larger and more
   architectural than 1–2; recommended after them since it's the one
   item that isn't a simple additive endpoint, and the other two don't
   depend on it.
4. **Notifications and search** (items 5–6) — recommended last, and
   only after a deliberate product-scope decision (what counts as a
   notification; what search actually needs to search), since unlike
   1–3 there's no existing data to read from at all — these are new
   product surfaces, not new views over existing data.

**Phase 8C — frontend integration**, after each corresponding 8B item
lands: wire the already-built `useApiQuery` hook (no new hook needed)
to each new endpoint, following the exact same pattern the Row 1 health
cards already use. This is expected to be small per-endpoint, since the
loading/error/empty-state machinery, the `Card`/`StatusBadge`
components, and the API-client pattern (`lib/*Api.ts`) all already exist
and were built specifically to be reused this way.

**Why this order**: 8B before 8C is forced (no UI can show real data
that doesn't exist yet — the entire point of this audit). Within 8B,
smallest/most-isolated-first (profile, then durable-data reads, then
the BFF extension, then the two genuinely-new product surfaces last)
minimizes the chance of discovering a larger redesign need midway
through smaller work.
