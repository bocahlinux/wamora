# Phase 0 — Documentation Audit

Generated as part of Phase 0 (Project Initialization). Source of truth: `./docs/*.md`. Nothing in this report is inferred beyond what those files state.

## 1. Documents Found

| # | File | Purpose |
|---|------|---------|
| 1 | `00-MASTER-SPEC.md` | Product scope, feature list, tech stack summary, data ownership, non-goals |
| 2 | `01-ARCHITECTURE.md` | System topology diagram, BFF role, backend role, failure isolation principle |
| 3 | `02-REQUIREMENTS.md` | Functional / reliability / security / observability requirements |
| 4 | `03-UI-UX-SPEC.md` | Global status model (WAHA/WhatsApp/Backend/DB/Sync), screens, offline UX rules |
| 5 | `04-DATA-MODEL.md` | Suggested PostgreSQL entities, message identity rule, WebhookEvent/SyncCheckpoint fields |
| 6 | `05-WEBHOOK-SYNC-DESIGN.md` | Normal webhook flow, office-outage behavior, reconciliation flow, outbound idempotency |
| 7 | `06-SECURITY.md` | Trust zones, secret handling, WAHA access pattern, authorization model, SSRF/rate-limit/audit rules |
| 8 | `07-API-CONTRACT.md` | Frontend↔BFF, Frontend↔Django, WAHA↔Django webhook contract shape, API principles |
| 9 | `08-DEPLOYMENT.md` | Tencent/Office Docker service lists, PostgreSQL handling rules, WAHA persistence paths |
| 10 | `09-TEST-PLAN.md` | Unit/integration/failure/security test scenarios |
| 11 | `10-CLAUDE-CODING-GUIDE.md` | Required reading order, per-task workflow, phase discipline, escalation rule |
| 12 | `11-DECISIONS-AND-OPEN-QUESTIONS.md` | Finalized decisions vs. explicitly open questions |
| 13 | `12-WAHA-REFERENCE.md` | Observed WAHA image/engine/version, ports, volumes, observed endpoints |
| 14 | `13-FINAL-DEPLOYMENT-TOPOLOGY.md` | Authoritative final topology, request flow, hard rule on PostgreSQL |
| 15 | `14-REPOSITORY-STRUCTURE.md` | Target repository tree and component ownership |
| 16 | `15-CODING-PHASES.md` | Ordered list of 15 implementation phases (0–14) |
| 17 | `CLAUDE.md` | Hard coding rules, scope per directory, per-task workflow, offline rule |
| 18 | `README.md` | One-page pack overview, restates topology and principles |

A zip archive `WAHA-Dashboard-Claude-Engineering-Pack-FINAL.zip` exists at the project root. Its contents were verified to be identical (same 18 filenames/sizes) to `./docs/`. It is the original distribution archive, not an additional or conflicting source.

## 2. Architecture Rules (verbatim intent, aggregated)

- Tencent VPS (Docker): React frontend, BFF/API Gateway, WAHA (GOWS engine).
- Office server (Docker): Django/DRF backend, Celery worker, Celery beat, Redis.
- PostgreSQL is existing infrastructure, outside Docker, configured via environment variables (host/port/db/user/password).
- Tencent and Office communicate over NetBird/LAN.
- Frontend never calls WAHA directly — always through the BFF.
- BFF is a security boundary, not a generic proxy: it must use an allowlist of WAHA endpoints and protects WAHA credentials.
- Backend (Django) owns durable application data, webhook ingestion, reconciliation, audit, reporting, permissions, and business rules.
- Office outage must never be treated as WAHA outage, and must not automatically take down Tencent/WAHA. PostgreSQL outage must not be conflated with WAHA outage.
- UI must independently report: WhatsApp status, WAHA status, office backend status, PostgreSQL status, sync status (`03-UI-UX-SPEC.md`).

## 3. Technology Stack

| Component | Stack | Source |
|---|---|---|
| Frontend | React (+ TypeScript per `CLAUDE.md`) | `00-MASTER-SPEC.md`, `CLAUDE.md` |
| BFF/API Gateway | Node.js + TypeScript, Express — decided during Phase 0 (previously open) | `11-DECISIONS-AND-OPEN-QUESTIONS.md` |
| Backend | Django + Django REST Framework | `00-MASTER-SPEC.md` |
| Task queue | Celery worker + Celery beat | `00-MASTER-SPEC.md` |
| Broker/cache | Redis | `00-MASTER-SPEC.md` |
| Database | PostgreSQL (existing, external, non-Docker) | `00-MASTER-SPEC.md`, `08-DEPLOYMENT.md` |
| WhatsApp gateway | WAHA, image `devlikeapro/waha:gows`, GOWS engine, observed version 2026.9.1, API port 3000 | `12-WAHA-REFERENCE.md` |

## 4. Deployment Topology

```
Browser --(LAN/NetBird)--> Tencent VPS (Docker: frontend, bff, waha) --> WhatsApp
Tencent <--(NetBird/LAN)--> Office Server (Docker: backend, celery-worker, celery-beat, redis) --(TCP 5432)--> Existing PostgreSQL
```

- Preferred internal flow on Tencent: `frontend -> bff -> waha` (BFF reaches WAHA over the Docker network where practical; WAHA port should not be unnecessarily public).
- Office outage: browser → Tencent frontend/BFF → WAHA continues working; office backend/database are marked offline/degraded in the UI.
- Recovery: office returns → pending webhook deliveries are processed/retried where available → reconciliation job runs → PostgreSQL is brought up to date.
- Access is intended for authorized LAN/NetBird users only, with application-layer authentication/authorization on top.

## 5. Security Constraints

- WAHA API key and DB credentials: server-side only, never committed, never exposed to the browser (not in frontend code, bundle, localStorage, or browser config).
- Frontend must never call WAHA directly.
- BFF must use an endpoint allowlist (SSRF protection — no arbitrary target URL).
- Separate authorization scopes for: session control, reading, sending, blast, user administration, system administration.
- Frontend network access restricted to LAN and/or NetBird.
- Rate limiting required on: login, send, session control, blast, expensive sync operations.
- Audit logging required for sensitive operations: actor, time, action, target, result.
- Webhook endpoint must validate, authenticate, be idempotent, and record processing state.
- Outbound WhatsApp side effects must have idempotency handling (idempotency key), and an ambiguous outbound result must never cause a duplicate send.
- Database: least privilege application user, no public exposure, backups and restore testing.
- Also required: secure cookies, CSRF/XSS defenses where applicable, input validation, security headers, dependency updates, log redaction of secrets.

## 6. Data Ownership

- **WAHA**: live WhatsApp/session state (source of truth for what's happening right now).
- **PostgreSQL**: durable users, chats/messages, webhook records, sync checkpoints, outbound operations, audit log, reporting data.
- Suggested entities (`04-DATA-MODEL.md`): User, Role, Permission, WahaSession, Chat, Contact, Message, MediaReference, WebhookEvent, SyncCheckpoint, OutboundOperation, AuditLog, BlastCampaign, BlastRecipient, SystemHealthSnapshot.
- Message identity must use stable provider/WAHA identifiers scoped by session — never body/timestamp/sender alone.
- All schema changes require migrations.

## 7. Synchronization Model

- **Normal flow**: WhatsApp → WAHA → Django webhook → idempotency check → durable event record → normalize → PostgreSQL. Webhook delivery is explicitly *not* assumed to be exactly-once.
- **During office outage**: WAHA keeps operating; webhook delivery may fail; live messages remain accessible directly through WAHA.
- **Recovery/reconciliation**: WAHA → reconciliation job → fetch history → compare stable IDs → insert missing records → advance checkpoint. Must be repeatable, paginated, transaction-aware, and duplicate-safe.
- **Outbound during outage**: use an idempotency key, send through BFF/WAHA; when office returns, record/reconcile the provider message ID; never blindly resend an operation whose success is uncertain.

## 8. Unresolved Questions (explicitly listed as open in `11-DECISIONS-AND-OPEN-QUESTIONS.md`)

1. Exact authentication implementation.
2. Frontend framework/tooling versions (exact React/build tool versions).
3. WebSocket vs. SSE for real-time updates.
4. Blast limits/approval process.
5. Backup retention policy.
6. Exact PostgreSQL host/IP/database name.
7. TLS/domain setup.
8. NetBird/firewall rule specifics.

BFF language/framework was open at the time this audit was first written; it has since been decided (Node.js + TypeScript, Express) and moved to the "Final" section of `11-DECISIONS-AND-OPEN-QUESTIONS.md`.

## 9. Conflicts Between Documents

**None found.** All 18 documents are mutually consistent on topology, component placement, data ownership, and the hard rules (no PostgreSQL container, no WAHA credentials in frontend, no direct frontend→WAHA calls, mandatory webhook/outbound idempotency, mandatory reconciliation, office/WAHA failure-domain separation).

One cosmetic-only observation, not a conflict: `14-REPOSITORY-STRUCTURE.md` shows the repository root as `waha-dashboard/` in its example tree, while the actual project directory on disk is `waha-monitoring`. This does not affect any architecture rule and is treated as an illustrative root name, not a requirement — the internal structure (`frontend/`, `bff/`, `backend/`, `infrastructure/{tencent,office}/`, `docs/`, `scripts/`) is followed as specified.

## 10. Assumptions Still Required

- None taken silently. The one item that blocked concrete scaffolding (BFF language/framework) was raised to the user rather than assumed, and has since been decided: Node.js + TypeScript, Express — recorded in `11-DECISIONS-AND-OPEN-QUESTIONS.md`. See `PHASE-0-ARCHITECTURE-VALIDATION.md` for the resolution record.
