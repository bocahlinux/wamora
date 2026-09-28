# Wamora — WAHA WhatsApp Monitoring Dashboard

Internal dashboard for monitoring and operating a WAHA-based WhatsApp
gateway, with a durable Django backend, a Node.js/TypeScript BFF that
guards WAHA credentials, and a React frontend.

The full specification is the source of truth and lives in [`docs/`](docs/)
— start with [`docs/00-MASTER-SPEC.md`](docs/00-MASTER-SPEC.md) and
[`docs/CLAUDE.md`](docs/CLAUDE.md) before making architectural changes.

## Architecture

The system is split across two independently-deployable Docker stacks plus
one piece of existing infrastructure:

**Tencent VPS** (`infrastructure/tencent/`)
- WAHA (GOWS engine) — the live WhatsApp gateway
- `frontend/` — React + TypeScript
- `bff/` — Node.js + TypeScript (Express), the only thing allowed to talk
  to WAHA directly

**Office server** (`infrastructure/office/`)
- `backend/` — Django + DRF, the durable application backend
- Celery worker + beat
- Redis

**Existing infrastructure**
- PostgreSQL — not a Docker service in this project, configured via
  environment variables

### Hard rules

- The frontend never receives the WAHA API key and never calls WAHA
  directly — only through the BFF.
- The BFF is not a generic proxy; it uses an explicit allowlist of WAHA
  endpoints.
- Webhooks are idempotent; outbound WhatsApp side effects use idempotency
  keys.
- WAHA/Tencent keeps working when the office server is down. Office-only
  persistence degrades with a clear status; reconciliation repairs data
  once the office stack is back.

See [`docs/CLAUDE.md`](docs/CLAUDE.md) for the full list.

## Repository structure

```text
wamora/
├── CLAUDE.md              # coding-rules pointer (root)
├── README.md              # this file
├── docs/                  # specification — source of truth
├── frontend/              # React + TypeScript
├── bff/                   # Node.js + TypeScript (Express)
├── backend/               # Django + DRF
└── infrastructure/
    ├── development/       # local Docker dev stacks (Tencent-side, Office-side)
    ├── tencent/            # Tencent VPS deployment
    └── office/             # Office server deployment
```

## Local development

Two independent Docker Compose stacks under `infrastructure/development/`
mirror the Tencent/Office split:

```bash
# Office stack: Django + Celery worker/beat + Redis
docker compose -f infrastructure/development/office.yml up -d

# Tencent stack: BFF + frontend (hot-reload)
docker compose -f infrastructure/development/tencent.yml up -d
```

Copy each stack's `*.env.example` to a real env file first (see the
comments in each example file — they explain which values are dev-only
and which must match across stacks, e.g. `INTERNAL_SERVICE_KEY`).

Backend management commands run inside the Office container, e.g.:

```bash
docker compose -f infrastructure/development/office.yml exec backend python manage.py test
docker compose -f infrastructure/development/office.yml exec backend python manage.py migrate
```

## Current status

WAMORA follows a canonical 22-phase development roadmap. The current,
authoritative phase-by-phase status — what's complete, in progress, not
started, or deferred — is maintained in
[`docs/16-MASTER-ROADMAP.md`](docs/16-MASTER-ROADMAP.md). That document
supersedes the original engineering sequence in
[`docs/15-CODING-PHASES.md`](docs/15-CODING-PHASES.md) (kept as a
historical record, not deleted) and any individual report under
[`docs/generated/`](docs/generated/), which can go stale as work
continues past the point a given report was written.

As of the last audit: the core platform (auth, WAHA session management,
webhook ingestion, reconciliation, Inbox, multi-tenant Office model,
security hardening, Blast) is complete; a superadmin-editable Dynamic
RBAC system (canonical Phase 14) is complete and committed;
production-deployment hardening (TLS/reverse-proxy, image
rollback/versioning, rate-limit resilience under a Redis/Postgres outage)
is well underway with several items still open before a real go-live.
See `docs/16-MASTER-ROADMAP.md` Section 2 for the full per-phase table
with evidence, and Section 7 for the current actionable next steps.

A Conversation/Bot Engine foundation (fully admin-configurable menus,
triggers, and per-Office/global config — no hardcoded bot content) is also
now built, superseding the old Phase 12/13 plain-text auto-reply handlers.
It has no canonical phase number yet (see `docs/16-MASTER-ROADMAP.md`
Section 5) and is live-verified against the real dev WAHA/BFF stack for
outbound delivery; a genuine device-originated inbound test is still
outstanding.
