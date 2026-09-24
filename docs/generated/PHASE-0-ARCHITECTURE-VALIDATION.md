# Phase 0 — Architecture Validation

## Target topology under validation

```
Tencent:
    Frontend
    BFF/API Gateway
    WAHA

Office:
    Backend
    Redis
    Celery

Existing:
    PostgreSQL
```

## Result: Architecture baseline is consistent

Every document that touches topology, component placement, or data ownership agrees with the target topology above and with each other. Specifically cross-checked:

| Rule | Documents agreeing | Consistent? |
|---|---|---|
| Frontend + BFF + WAHA all run on Tencent, in Docker | `00-MASTER-SPEC.md`, `01-ARCHITECTURE.md`, `08-DEPLOYMENT.md`, `13-FINAL-DEPLOYMENT-TOPOLOGY.md`, `README.md` | Yes |
| Backend + Celery worker/beat + Redis all run on Office, in Docker | Same set as above | Yes |
| PostgreSQL is existing infrastructure, not a Docker service in this project | `00-MASTER-SPEC.md`, `04-DATA-MODEL.md`, `08-DEPLOYMENT.md`, `13-FINAL-DEPLOYMENT-TOPOLOGY.md`, `CLAUDE.md`, `README.md` | Yes — stated as a "hard rule" in `13-FINAL-DEPLOYMENT-TOPOLOGY.md` and rule #1 in `CLAUDE.md` |
| Frontend never calls WAHA directly; BFF is the only path | `01-ARCHITECTURE.md`, `06-SECURITY.md`, `11-DECISIONS-AND-OPEN-QUESTIONS.md`, `13-FINAL-DEPLOYMENT-TOPOLOGY.md`, `CLAUDE.md` | Yes |
| BFF is not a generic proxy; must allowlist WAHA endpoints | `01-ARCHITECTURE.md`, `06-SECURITY.md`, `CLAUDE.md` | Yes |
| Office outage is independent from WAHA outage (failure isolation) | `01-ARCHITECTURE.md`, `03-UI-UX-SPEC.md`, `05-WEBHOOK-SYNC-DESIGN.md`, `09-TEST-PLAN.md`, `13-FINAL-DEPLOYMENT-TOPOLOGY.md`, `CLAUDE.md` | Yes |
| Reconciliation is mandatory after office recovery | `05-WEBHOOK-SYNC-DESIGN.md`, `09-TEST-PLAN.md`, `11-DECISIONS-AND-OPEN-QUESTIONS.md`, `13-FINAL-DEPLOYMENT-TOPOLOGY.md` | Yes |
| Repository structure separates `frontend/`, `bff/`, `backend/`, `infrastructure/{tencent,office}/`, `docs/` | `14-REPOSITORY-STRUCTURE.md`, `CLAUDE.md` | Yes |

No document proposes an additional service, a different component placement, moving WAHA or the frontend to the office network, or a PostgreSQL container. No document contradicts another on any of the above points.

## Conflicts

None. Architecture baseline is consistent across all 18 documents.

## Non-blocking note (not a conflict, no decision needed)

`14-REPOSITORY-STRUCTURE.md`'s example tree uses root folder name `waha-dashboard/`; the actual project folder is `waha-monitoring`. This is cosmetic — the root folder name is not an architecture rule, and the actual project directory is kept as-is. Internal structure follows the document exactly.

## Item that required approval before further scaffolding — resolved

This was **not** a conflict between documents — it was a decision the documents themselves left open (`11-DECISIONS-AND-OPEN-QUESTIONS.md`, "Open" section, item 3: *BFF language/framework*). No other document filled the gap.

Why this needed approval rather than being assumed: it directly determined what Step 4 (environment configuration) and Step 5 (Docker configuration) had to produce for `bff/` — the base Docker image, the package manifest format, the runtime port convention, and the `.env.example` variables for that service. Per `10-CLAUDE-CODING-GUIDE.md` / `CLAUDE.md`: *"Jika ambiguity mempengaruhi architecture/security/data integrity, jangan menebak: tanyakan."* Choosing a BFF stack silently would have been exactly that kind of guess, since the BFF is explicitly a security boundary component (credential custody + SSRF allowlisting).

**Resolution**: the user selected Node.js + TypeScript for the BFF runtime/language; Express was subsequently confirmed as the concrete framework. This is now recorded as a Final decision (item 11) in `11-DECISIONS-AND-OPEN-QUESTIONS.md`, and reflected in `00-MASTER-SPEC.md` and `README.md`'s technology listings. Steps 4–5 (env config, Docker) for `bff/` were completed on this basis.

## Other open questions (from `11-DECISIONS-AND-OPEN-QUESTIONS.md`)

The following remain open but do **not** block Phase 0 skeleton work (no business logic, auth flow, realtime transport, blast logic, or infra provisioning is implemented in this phase): exact auth implementation, exact frontend tooling version, WebSocket vs. SSE, blast limits/approval, backup retention, exact PostgreSQL host/IP/db, TLS/domain, NetBird/firewall rule specifics. They should be revisited at the phases in `15-CODING-PHASES.md` where they become relevant (e.g. auth in Phase 1/6, realtime transport in Phase 7/8, blast in Phase 11, production networking in Phase 14).
