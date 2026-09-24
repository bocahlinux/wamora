# WAMORA — WhatsApp Operations & Monitoring

Internal dashboard for monitoring and operating a WAHA (WhatsApp HTTP
API) deployment — session health, chat/message visibility, and
operational controls for a small number of WhatsApp sessions (starting
with 1, expected to grow to a maximum of 2–3). Formerly "WAHA Monitoring
Dashboard"; user-facing UI now uses the WAMORA brand.

> **Status**: active development. Backend data ingestion/sync (Phases
> 0–5), the BFF (Phase 6), and the frontend foundation (Phase 7) are
> implemented and, where applicable, live-verified against a real WAHA
> deployment. A Dashboard data pass (auth identity, messages/activity
> widgets), the canonical **Phase 10 Session Management** UI (start/
> stop/restart/logout/QR/pairing, with BFF-side duplicate-request
> hardening and frontend status-sync polling), and the canonical
> **Phase 8 Inbox/Chat** (chat list, conversation view, inbound via
> webhook, outbound via the BFF's send endpoint with a reconciliation
> fallback for this WAHA deployment's lack of an outbound-message
> webhook, mark-as-read, and name/phone-number display identity) are
> implemented and manually verified against a real, live WhatsApp
> session. Offline/degraded mode (Phase 9), Blast, and production
> hardening have not been started. **This repository is not
> production-ready.** See [Project status](#project-status) below.

Full specification lives in [`docs/`](docs/) — that is the source of
truth for this project. This README is an operational summary; if it
ever disagrees with `docs/`, `docs/` wins.

## Architecture

```
Browser
   │  (LAN / NetBird)
   ▼
Tencent VPS (Docker)
   Frontend (React+TS) ──▶ BFF (Node/TS gateway) ──▶ WAHA (GOWS) ──▶ WhatsApp
   │
   │  NetBird / LAN
   ▼
Office Server (Docker)
   Backend (Django/DRF) ──▶ Celery worker / beat ──▶ Redis
   │
   │  TCP 5432
   ▼
Existing PostgreSQL (NOT a Docker service of this project)
```

| Component | Role |
|---|---|
| **Frontend** (React + TypeScript) | Browser UI. Never calls WAHA directly — only the BFF. Login, Dashboard (system health + messages/activity), Sessions (status + full lifecycle control + QR/pairing), and Inbox (chat list, conversation view, composer, mark-as-read) are implemented; WhatsApp overview, Reports, and Settings are placeholder shells pending their own phases/product decisions. |
| **BFF** (Node.js + TypeScript, Express) | Server-side boundary between the browser and WAHA on the Tencent VPS. Verifies the same Django-issued JWT the backend issues, protects the WAHA API key, enforces an explicit endpoint allowlist (not a generic proxy — `bff/src/wahaAllowlist.ts`), and implements session status/lifecycle/QR/pairing, idempotent message sending, and a duplicate-request guard on the mutating session routes. |
| **WAHA** (`devlikeapro/waha:gows`) | The WhatsApp HTTP API engine itself (GOWS engine). Owns live session/connection state. |
| **Backend** (Django + DRF) | Runs on the Office server. Owns durable application data: chats/messages, webhook records, sync checkpoints, outbound operations, audit log. Issues and verifies RS256 JWTs; serves `/api/auth/me/` and the dashboard aggregate endpoints directly to the frontend. |
| **Celery worker / beat** | Background processing and periodic reconciliation on the Office server. |
| **Redis** | Celery broker/result backend (Office server only) — not currently used for anything beyond that (no pub/sub, no Channels). |
| **PostgreSQL** | **Existing infrastructure**, not provisioned by this repository. The backend connects to it via environment variables; nothing here creates a PostgreSQL container or exposes it publicly. |

See [`docs/01-ARCHITECTURE.md`](docs/01-ARCHITECTURE.md) and
[`docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`](docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md)
for the authoritative diagrams and rules.

### Tencent ↔ Office: independent failure domains

The two Docker deployments communicate over NetBird/LAN and are designed
as independent failure domains:

- If the Office backend or PostgreSQL goes offline, WAHA and the
  frontend are designed to keep working — WhatsApp features stay live
  via WAHA directly. The UI is specified to mark backend/database/sync
  status independently of WAHA/WhatsApp status (see
  [`docs/03-UI-UX-SPEC.md`](docs/03-UI-UX-SPEC.md)), and the Dashboard's
  three health cards (WAHA, Backend, PostgreSQL) already do this today,
  each checked and reported independently. A fuller offline/degraded UX
  (canonical Phase 9) is documented as a future phase but not yet
  implemented beyond that.
- Writes made while the Office is offline are designed to be reconciled
  once it comes back, via a dedicated reconciliation job that compares
  stable WAHA message IDs against PostgreSQL and fills in gaps (see
  [`docs/05-WEBHOOK-SYNC-DESIGN.md`](docs/05-WEBHOOK-SYNC-DESIGN.md)).
  **This is implemented and live-verified**, including chat discovery
  (a chat WAHA has that Django has never received a webhook for gets a
  row created the next reconciliation run).
- **This same reconciliation mechanism also covers a real WAHA
  deployment gap**: this project's WAHA instance does not deliver a
  webhook for self-sent (outbound) messages, so the BFF triggers a
  *targeted*, single-chat reconciliation right after a confirmed
  outbound send, reusing the exact same `reconcile_session()` logic as
  the periodic job. See
  [`docs/generated/INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md`](docs/generated/INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md).

## Repository structure

```
waha-monitoring/
├── CLAUDE.md                 # coding rules (root pointer to docs/CLAUDE.md)
├── README.md                 # this file
├── docs/                     # specification — source of truth
│   └── generated/            # generated phase audit/implementation/verification reports
├── wamora-design-assets/     # WAMORA visual design spec + reference boards (design source of truth for frontend)
├── frontend/                 # React + TypeScript (Vite) — login, Dashboard, Sessions, Inbox implemented;
│                              #   WhatsApp overview/Reports/Settings are placeholder shells
├── bff/                      # Node.js + TypeScript (Express) — auth, session lifecycle/QR/pairing,
│                              #   idempotent send, health — implemented and tested
├── backend/                  # Django + DRF — apps: core, waha_sessions, chats, webhooks, sync,
│                              #   operations, audit, authn, dashboard
├── infrastructure/
│   ├── tencent/               # docker-compose for Tencent VPS (frontend, bff, waha)
│   └── office/                 # docker-compose for Office server (backend, celery, redis)
└── scripts/                  # operational/dev helper scripts (empty, populated as later phases need them)
```

Ownership: `frontend` = UI, `bff` = Tencent/WAHA boundary, `backend` =
Django data/business layer, `infrastructure` = deployment, `docs` =
specification. PostgreSQL is external, existing infrastructure. A task
scoped to one component should not modify another unless an
integration/API contract requires it.

## Project status

Tracked against [`docs/15-CODING-PHASES.md`](docs/15-CODING-PHASES.md).
**Note**: canonical Phase 10 (Session Management) was implemented ahead
of canonical Phases 8/9, by an explicit, deliberate decision — its BFF
backend was already substantially complete, making it the cheapest
next slice of real functionality. This is an ordering choice, not a
change to the phase list itself (see
[`docs/generated/PHASE-9-ROADMAP-AUDIT-REPORT.md`](docs/generated/PHASE-9-ROADMAP-AUDIT-REPORT.md)).

| # | Phase | Status |
|---|---|---|
| 0 | Repository skeleton | Done |
| 1 | Backend foundation | Done |
| 2 | Database models + migrations | Done |
| — | LID/JID identity verification (Phase 2.5) | Done, live-verified against the real WAHA deployment |
| 3 | Webhook ingestion | Done, live-verified |
| 4 | Reconciliation | Done, live-verified (including retry/backoff behavior against a real Celery worker, chat discovery, and the targeted single-chat trigger used by Inbox/Chat outbound sends). |
| 5 | Celery/Redis | Done, live-verified against real Redis + worker + beat containers |
| 6 | BFF | **Done.** JWT verification, session status/start/stop/restart/logout/QR/pairing, idempotent message send (`Idempotency-Key` + `OutboundOperation`), a duplicate-request guard on mutating session routes, and CORS/env-loading fixes — all implemented and tested (`bff/test/`). |
| 7 | Frontend foundation | **Done.** WAMORA design system (tokens, components), shell/nav/theme, login, and visual-fidelity pass against the design spec. |
| — | Dashboard data pass (informal, not a numbered phase) | **Done.** `GET /api/auth/me/`, `/api/dashboard/messages/`, `/api/dashboard/activity/` on the Django side; Django-side JWT verification (previously BFF-only); Dashboard UI wired to real data (identity, messages-today/trend, activity feed). Explicitly **not** the canonical Phase 8 Inbox/chat work. |
| 8 | Inbox/chat | **Done — implemented and manually verified against a real, live WhatsApp session.** Chat list + conversation view (`GET /api/chats/`, `GET /api/chats/:id/messages/`, `POST /api/chats/:id/read/`, Frontend → Django direct), inbound via the WAHA webhook, outbound via the BFF's existing send endpoint with a targeted-reconciliation fallback (this WAHA deployment sends no webhook for self-sent messages), and name → phone-number → raw-ID display identity (WhatsApp `PushName`, no `@lid`/`@s.whatsapp.net` auto-merge). See [`docs/generated/INBOX-CHAT-DECISION-REPORT.md`](docs/generated/INBOX-CHAT-DECISION-REPORT.md), [`INBOX-CHAT-IMPLEMENTATION-REPORT.md`](docs/generated/INBOX-CHAT-IMPLEMENTATION-REPORT.md), [`INBOX-IDENTITY-DISPLAY-IMPLEMENTATION-REPORT.md`](docs/generated/INBOX-IDENTITY-DISPLAY-IMPLEMENTATION-REPORT.md), and [`INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md`](docs/generated/INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md). `status@broadcast` is not yet filtered out of the chat list (documented, deferred). |
| 9 | Offline/degraded mode | Not started — intentionally deferred; depends on Phase 8 existing first (see the Phase 9 roadmap audit). |
| 10 | Session management | **Done, ahead of order — implemented and manually browser-verified.** Start/stop/restart/logout/QR/pairing UI, a BFF-side in-process duplicate-request lock, confirmed-vs-ambiguous (timeout) outcome handling, and frontend settlement-polling so the UI never shows a stale status after an action. See `docs/generated/SESSION-MANAGEMENT-*.md`. |
| 11 | Blast | Not started |
| 12 | Security hardening | Not started |
| 13 | Failure/security testing | Not started |
| 14 | Production deployment | Not started |

**This project is not production-ready.** Rate limiting, fine-grained
per-user data authorization, and full offline/degraded UX are all
still-open items (Phase 12/9). See
[Security](#security) for the current, accurate state of what's
actually enforced today.

### What's actually verified vs. what's only documented

- **Implemented and live-verified against a real WAHA deployment**:
  webhook ingestion (HMAC-authenticated), the Chat/Contact/Message data
  model and its identity/deduplication rules, reconciliation (pagination,
  checkpoints, retry behavior, chat discovery), the Celery/Redis
  background-task pipeline, JWT issuance and verification (both Django-
  and BFF-side), the full BFF session-lifecycle/QR/pairing/send-message
  contract (including its automated test suite), the Session Management
  frontend, and Inbox/Chat (chat list, conversation view, inbound
  webhook, outbound send + targeted-reconciliation fallback, mark-as-read,
  display identity) — all manually browser/WhatsApp-tested by the
  project owner against a real, live WhatsApp session.
- **Implemented and covered by automated tests, not yet exercised
  against real production traffic**: the Dashboard's messages/activity
  aggregation endpoints (verified against the real dev database's actual
  — currently near-empty — data, and via the Django/BFF automated test
  suites); the `RECONCILIATION_EXECUTOR=celery` path (unit-tested with
  Celery's eager mode — no real Celery worker/Redis runs in this
  project's current manual dev environment; see
  [`docs/generated/INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md`](docs/generated/INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md)).
- **Specified and decision-documented, not yet implemented**: offline/
  degraded mode, Blast, rate limiting, fine-grained per-user data
  authorization, and filtering `status@broadcast` out of the Inbox chat
  list.
- **Known, documented gaps, not hidden**: two missing database indexes
  (`chats.Message.timestamp`, `webhooks.WebhookEvent.received_at`) for
  queries that don't currently need them at this project's scale; no
  automatic `@lid`/`@s.whatsapp.net`/`@c.us` identity merge (the same
  WhatsApp contact can appear as more than one `Chat` row — a display-only
  fix, not a merge, is in place; see
  [`INBOX-IDENTITY-DISPLAY-AUDIT-REPORT.md`](docs/generated/INBOX-IDENTITY-DISPLAY-AUDIT-REPORT.md));
  no real-time push mechanism exists (Dashboard/Sessions/Inbox all use
  plain polling — WebSocket/SSE were evaluated and deliberately
  deferred, see the Inbox/Chat decision report).

## Development prerequisites

- Node.js 22+ and npm (frontend, bff)
- Python 3.10+ (backend)
- Docker + Docker Compose (running each deployment topology locally)
- Access to an **existing** PostgreSQL instance (dev/staging), or point
  `DB_*` at a local Postgres you manage yourself — this project will
  never create one for you, and never will (see
  [`docs/CLAUDE.md`](docs/CLAUDE.md) rule 1).
- A running WAHA instance (or the `devlikeapro/waha:gows` image) for
  bff/backend integration work.

## Environment variables

Each component has its own `.env.example`; copy it to `.env` locally and
fill in real values. **Never commit `.env` files** — only
`.env.example` files are tracked (enforced by `.gitignore`).

| File | Used for |
|---|---|
| `frontend/.env.example` | `VITE_`-prefixed vars only — BFF/Django base URLs and the WAHA session name to display/control. No secrets. |
| `bff/.env.example` | WAHA base URL/API key (server-side only), JWT public key (verification), `DJANGO_INTERNAL_BASE_URL` + `INTERNAL_SERVICE_KEY` (BFF → Django internal endpoints), port, CORS origin, WAHA session name. |
| `backend/.env.example` | Django secret key, allowed hosts, JWT private key (issuance), existing PostgreSQL connection, `WAHA_WEBHOOK_HMAC_SECRET`, Celery/Redis URLs, `RECONCILIATION_EXECUTOR`, `INTERNAL_SERVICE_KEY`, CORS origin. |
| `infrastructure/tencent/.env.example` | Merged env for the Tencent `docker-compose.yml` (frontend/bff/waha). |
| `infrastructure/office/.env.example` | Merged env for the Office `docker-compose.yml` (backend/celery/redis). |

**`INTERNAL_SERVICE_KEY` must be set to the exact same value in both
`bff/.env` and `backend/.env`** — it authenticates the BFF process to
Django's `internal/` endpoints (register/resolve an outbound send,
trigger reconciliation, write an audit event). A mismatch (or either
side left empty) fails closed with `403`. Never write the actual value
into any file other than `.env` itself. See
[`docs/generated/INTERNAL-SERVICE-KEY-FINGERPRINT-AUDIT-REPORT.md`](docs/generated/INTERNAL-SERVICE-KEY-FINGERPRINT-AUDIT-REPORT.md)
for how to diagnose a `403` here if one ever recurs.

**`WAHA_WEBHOOK_HMAC_SECRET`** (backend only) must match the HMAC key
configured on the WAHA session's own webhook config — WAHA must POST to
`http://<django-host>:8000/api/webhooks/waha/` (note the trailing
slash) with that same secret. See
[`docs/generated/INBOX-WEBHOOK-FIX-REPORT.md`](docs/generated/INBOX-WEBHOOK-FIX-REPORT.md).

**Server-side secret boundary**: the WAHA API key, JWT private key, and
all other credentials are read only by server-side components (`bff`,
`backend`). They must never be exposed to the frontend bundle, browser
storage, or any browser-reachable config — see [Security](#security).

## Local development

**Frontend** — login, Dashboard (health + messages/activity), Sessions
(status + full lifecycle control + QR/pairing), and Inbox (chat list,
conversation view, composer, mark-as-read) are implemented; WhatsApp
overview/Reports/Settings are placeholder shells.
```
cd frontend
npm install
cp .env.example .env   # fill in BFF/Django base URLs and the WAHA session name
npm run dev
```

**BFF** — auth, session lifecycle/QR/pairing, idempotent message send,
and health are implemented and tested.
```
cd bff
npm install
cp .env.example .env   # fill in WAHA_BASE_URL / WAHA_API_KEY / WAHA_SESSION_NAME / JWT_PUBLIC_KEY(_PATH)
npm run dev             # loads .env automatically (Node's --env-file-if-exists), no manual export needed
npm run test             # vitest — full route/middleware/idempotency test suite
```

**Backend** — migrations, webhook ingestion, reconciliation, Celery
tasks, JWT auth, chats/Inbox, and the dashboard endpoints all exist and
have tests. `backend/.env` is loaded automatically by
`config/settings.py` for any bare `python manage.py ...` invocation
(`config/env.py`) — no manual `export`/`source` step is needed; an
already-exported shell variable, or one inherited from a still-running
process, still wins over the same key in `.env`. This is a
local-development convenience only — Docker/production never depend on
`backend/.env` being present (it's excluded from the image by
`.dockerignore`; Compose injects configuration via `env_file:` instead).
```
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in existing PostgreSQL connection details, JWT_PRIVATE_KEY(_PATH), INTERNAL_SERVICE_KEY, WAHA_WEBHOOK_HMAC_SECRET
python manage.py migrate
python manage.py runserver
```

> **Only one `manage.py runserver` process should ever be listening on
> port 8000 at a time.** Because `.env` values are only read once, at
> process startup, and an already-running process's environment always
> wins over a newer `.env` edit (see above), an old, forgotten
> `runserver` process left running from an earlier session can keep
> silently answering requests with stale config (e.g. an old
> `INTERNAL_SERVICE_KEY`) even after you've edited `.env` and started a
> "new" one elsewhere — Windows in particular does not always refuse a
> second process binding the same port. If BFF → Django internal calls
> ever start failing with `403` for no apparent reason, check
> `netstat -ano | findstr :8000` for more than one PID before assuming a
> config bug (full diagnostic writeup: `INTERNAL-SERVICE-KEY-FINGERPRINT-AUDIT-REPORT.md`
> above).

**Full Tencent stack (Docker)**
```
cd infrastructure/tencent
cp .env.example .env
docker compose up --build
```

**Full Office stack (Docker)**
```
cd infrastructure/office
cp .env.example .env   # point DB_* at the existing PostgreSQL
docker compose up --build
```

## Database

PostgreSQL is **existing infrastructure**, not provisioned by this
project. Nothing here creates a PostgreSQL container, and nothing here
should ever expose it publicly. Connection details (host, port,
database, user, password) are supplied entirely via environment
variables — see `backend/.env.example` and
`infrastructure/office/.env.example`. See
[`docs/CLAUDE.md`](docs/CLAUDE.md) for the hard rules governing this.

## Security

This summarizes what's **already implemented today**. It is not a claim
that the system is fully secured — several items (listed explicitly
below) are still open.

- **Secrets stay server-side.** The WAHA API key, JWT private key, and
  database credentials are read only by the BFF and backend — never by
  the frontend, and never committed to the repository.
- **The frontend never calls WAHA directly.** All WAHA access goes
  through the BFF.
- **The BFF is not a generic proxy.** It only ever calls an explicit
  allowlist of WAHA endpoints (`bff/src/wahaAllowlist.ts`) — implemented
  and enforced structurally (`callWaha()` only accepts a name from that
  allowlist; there is no code path that can construct an arbitrary WAHA
  URL).
- **JWT authentication is implemented on both sides.** Django issues an
  RS256 JWT on login; both Django (`apps/authn/authentication.py`) and
  the BFF (`bff/src/jwt.ts`) independently verify it. Scoped BFF actions
  (`session control`, `sending`, `reading`) are enforced per-route.
  `/api/auth/me/` and the dashboard aggregates require authentication
  only; the Inbox/Chat endpoints (`/api/chats/...`) additionally require
  the `reading` scope (`apps/authn/permissions.py::HasReadingScope`) —
  the first Django-side scope-gated endpoints in this project.
- **BFF → Django internal calls are authenticated separately from the
  end-user JWT** — a static shared secret (`INTERNAL_SERVICE_KEY`,
  `apps/core/internal_auth.py::HasInternalServiceKey`), fails closed if
  unconfigured or mismatched on either side.
- **Webhook ingestion is authenticated and idempotent** — inbound WAHA
  webhooks are verified via HMAC signature before processing, and
  duplicate deliveries are handled safely at the database-constraint
  level.
- **Outbound WhatsApp sends use idempotency keys** — implemented:
  `POST /sessions/:session/messages` requires an `Idempotency-Key`
  header and is backed by `OutboundOperation`'s register/resolve state
  machine, distinguishing a confirmed failure from a genuinely ambiguous
  (timeout) outcome rather than guessing.
- **Session-control mutations (start/stop/restart/logout/pairing-code)
  have an in-process duplicate-request guard** — a second request for
  the same session+action while the first is still in flight is
  rejected (`409`), and a WAHA timeout is reported as a distinct
  "unknown" outcome, never silently treated as a confirmed failure.
- **Sensitive BFF actions are audited** — session lifecycle, QR/pairing,
  and send actions each write a best-effort audit record to Django,
  with a local structured-log fallback if Django is unreachable.
- **Still open**: rate limiting (deferred to Phase 12) and fine-grained
  per-user data authorization (every authenticated user with the
  `reading` scope currently sees all chats/messages/dashboard/audit
  data — a documented, deliberate v1 posture, not an oversight).

Full detail: [`docs/06-SECURITY.md`](docs/06-SECURITY.md),
[`docs/generated/PHASE-6-ARCHITECTURE-CONTRACT.md`](docs/generated/PHASE-6-ARCHITECTURE-CONTRACT.md),
and [`docs/generated/SESSION-MANAGEMENT-AUDIT-REPORT.md`](docs/generated/SESSION-MANAGEMENT-AUDIT-REPORT.md).

## Documentation

[`docs/`](docs/) is the **authoritative specification** for this
project — if anything here disagrees with it, `docs/` wins. Start with:

- [`docs/00-MASTER-SPEC.md`](docs/00-MASTER-SPEC.md) — product scope, features, availability requirements.
- [`docs/01-ARCHITECTURE.md`](docs/01-ARCHITECTURE.md) — component roles and failure isolation.
- [`docs/06-SECURITY.md`](docs/06-SECURITY.md) — security requirements.
- [`docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`](docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md) — deployment topology.
- [`docs/15-CODING-PHASES.md`](docs/15-CODING-PHASES.md) — the phase plan this README's status table tracks.
- [`wamora-design-assets/docs/WAMORA-FRONTEND-DESIGN-SPEC.md`](wamora-design-assets/docs/WAMORA-FRONTEND-DESIGN-SPEC.md) — the frontend visual design system.
- [`docs/generated/`](docs/generated/) — generated phase audit/implementation/verification reports (architecture reviews, live-verification evidence against the real WAHA deployment, and decision records) produced as each phase was built out. Grouped by area: `PHASE-6-*` (BFF), `PHASE-7-*` (frontend foundation), `PHASE-8-*`/`PHASE-8C-*` (Dashboard data pass — not the canonical Phase 8), `SESSION-MANAGEMENT-*` (canonical Phase 10), `INBOX-*`/`INTERNAL-SERVICE-*` (canonical Phase 8: audit, decision, implementation, and live-debugging reports for chat/messaging, outbound reconciliation, and the BFF↔Django internal channel), `PHASE-9-ROADMAP-AUDIT-REPORT.md` (project-wide next-phase audit).

## Contributing to this repository

A task scoped to one component (e.g. `bff/`) should not modify another
(e.g. `backend/`) unless an integration/API contract genuinely requires
it. See [`CLAUDE.md`](CLAUDE.md) and [`docs/CLAUDE.md`](docs/CLAUDE.md)
for the full set of coding rules, including the hard rules around
PostgreSQL, WAHA credentials, and the BFF's allowlist boundary.
