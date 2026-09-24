# CLAUDE.md — Coding Rules (root)

This is a pointer/summary. The canonical, full rules live in
[`docs/CLAUDE.md`](docs/CLAUDE.md) and [`docs/10-CLAUDE-CODING-GUIDE.md`](docs/10-CLAUDE-CODING-GUIDE.md).
`docs/` is the source of truth for this project — read it before making
architectural changes.

## Hard rules

1. Never create a PostgreSQL Docker service. PostgreSQL is existing
   infrastructure, configured via environment variables.
2. Never expose PostgreSQL to the public internet.
3. Never put the WAHA API key in the frontend, localStorage, the browser
   bundle, or any browser-reachable config.
4. The frontend must never call WAHA directly — only through the BFF.
5. The BFF is not a generic URL proxy; it must use an explicit allowlist
   of WAHA endpoints.
6. Webhooks must be idempotent.
7. Outbound WhatsApp side effects must use idempotency keys.
8. Never silently change the API contract or architecture.
9. Never mix Tencent and Office deployment concerns.
10. Never start the next coding phase (see `docs/15-CODING-PHASES.md`)
    without being asked.

## Scope

- `frontend/` — React + TypeScript.
- `bff/` — Node.js + TypeScript (Express), the Tencent-side gateway to WAHA.
- `backend/` — Django + DRF, the Office-side durable application backend.
- `infrastructure/tencent/` — Tencent VPS deployment (frontend, bff, waha).
- `infrastructure/office/` — Office server deployment (backend, celery, redis).
- `docs/` — specification (source of truth).

If a requirement is ambiguous and touches security, data integrity, or
architecture: do not guess — ask.
