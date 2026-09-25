# Decisions and Open Questions

## Final
1. WAHA engine: GOWS.
2. Initial session: 1; expected max 2–3.
3. Tencent: WAHA + frontend + BFF, all Docker.
4. Office: Django + Celery + Redis, all Docker.
5. PostgreSQL: existing infrastructure, not Docker.
6. Frontend never directly calls WAHA.
7. BFF protects WAHA credentials.
8. Office outage != WAHA outage.
9. Reconciliation mandatory after recovery.
10. Frontend access restricted to LAN/NetBird.
11. BFF stack: Node.js + TypeScript, Express.
12. Blast limits: max 100 recipients/campaign; max 500 recipients/day/session; 60s delay between messages; dispatch must be queued/throttled; admin ("system administration" scope) approval required before dispatch.

## Open
- exact auth implementation;
- frontend versions;
- WebSocket vs SSE;
- backup retention;
- exact PostgreSQL host/IP/db;
- TLS/domain;
- NetBird/firewall rules.

## Open — new candidate requirements (2026-09-26, not yet phased)
Captured from user notes; none of these are scoped, designed, or slotted into
docs/15-CODING-PHASES.md yet. Each needs its own design audit and phase
placement before implementation.
- **Session-based auto-reply menu bot**: on first inbound message in a 1x24h
  session, send a dynamic menu (e.g. a. cek pajak, b. aduan, c. lapor jual,
  d. chat dengan petugas). "a. cek pajak" collects plat nomor then 5-digit
  nomor rangka, then calls the esamsat backend API and returns the result.
  Whole session's interaction log is stored as JSON (one row per 1x24h
  session). Replies simulate typing with a 30s–1min delay to avoid
  WhatsApp bot detection. Open: menu content/config mechanism, esamsat API
  contract, session/log data model, relationship to the existing
  session/reconciliation model.
- **Blast template + esamsat integration**: blast messages sendable from a
  template, sourced from/integrated with the esamsat backend API. Delay of
  1 minute between bulk sends (distinct from the 60s per-message delay
  already decided for generic Blast above — confirm whether these are the
  same limit or esamsat-blast has its own). Open: relationship to the
  generic Blast phase (same feature, or a variant/extension), esamsat API
  contract for template data.
- **User manager (operator/admin handoff)**: lets an operator/admin reply
  directly to a chat where the user picked "d. chat dengan petugas"; every
  operator/admin reply automatically appends the sender's initials on the
  line below the message. Open: role/permission model for operators vs
  admins, how a chat is handed off from bot to human and back, where
  initials come from (user profile field?), multi-operator concurrency
  (can two operators reply to the same chat?).
