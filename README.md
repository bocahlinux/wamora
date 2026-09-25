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

Progress follows the coding-phase roadmap in
[`docs/15-CODING-PHASES.md`](docs/15-CODING-PHASES.md). Detailed design
audits and implementation reports for each phase are written to
[`docs/generated/`](docs/generated/) as work lands.

| Phase | Status |
|---|---|
| 0–8 — Skeleton, backend/frontend foundation, data model, webhook ingestion, reconciliation, Celery/Redis, BFF, Inbox/chat | Complete |
| 9 — Offline/degraded mode | Complete — connectivity/sync-status indication is consistent across Inbox, Dashboard and Sessions |
| 10 — Session management | Complete |
| 11 — Blast (controlled bulk send) | Complete — campaign draft/approval workflow, per-session throttled dispatch, `OutboundOperation`-based idempotency, manual stuck-recipient recovery |
| 12 — Security hardening | In progress — see [`docs/generated/PHASE-12-SECURITY-HARDENING-DESIGN-AUDIT-REPORT.md`](docs/generated/PHASE-12-SECURITY-HARDENING-DESIGN-AUDIT-REPORT.md) |
| 13 — Failure/security testing | Pending |
| 14 — Production deployment | Pending |

Recent notable work:
- **Blast (Phase 11)**: campaign-based bulk WhatsApp send with admin
  approval (no self-approval), a 60-second per-message throttle, a
  100-recipient/campaign and 500-recipient/day/session cap (Asia/Jakarta
  calendar day), and a manual recovery path for a recipient left stuck
  mid-dispatch by a worker crash.
- **Phase 9 completion**: reconciliation sync-status visibility and
  connectivity-issue indication, previously Inbox-only, extended to the
  Dashboard and Sessions pages.
- **Phase 12 (security hardening, in progress)**: scope-gating on
  under-permissioned read endpoints, fail-closed `DJANGO_SECRET_KEY`,
  audit logging on login attempts, bounded login input, and rate limiting
  (DRF throttling on the backend, `express-rate-limit` on the BFF, with a
  stricter limit on the login endpoint).

For the full, evidence-based status of every phase (including known,
explicitly-tracked gaps), see
[`docs/generated/PHASE-ROADMAP-STATUS-AUDIT-REPORT.md`](docs/generated/PHASE-ROADMAP-STATUS-AUDIT-REPORT.md).
