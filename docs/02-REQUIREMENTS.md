# Requirements

## Functional
- session management;
- session status;
- QR/pairing;
- chats;
- messages;
- send/reply;
- mark read;
- webhook;
- durable persistence;
- reconciliation;
- infrastructure health;
- audit;
- controlled blast.

## Functional — proposed, not yet phased (2026-09-26)
See docs/11-DECISIONS-AND-OPEN-QUESTIONS.md "Open — new candidate
requirements" for open design questions on each of these before they can
be scoped into docs/15-CODING-PHASES.md.
- session-based auto-reply menu bot, with esamsat backend integration for
  vehicle-tax lookup (plat nomor + nomor rangka);
- per-session (1x24h) interaction log stored as JSON;
- typing-simulation delay (30s-1min) on automated replies;
- blast message templates integrated with the esamsat backend API;
- user manager: operator/admin handoff and reply for chats routed to
  "chat dengan petugas", with automatic sender initials on each
  operator/admin reply.

## Reliability
- duplicate-safe webhooks;
- recovery after backend outage;
- idempotent outbound operations;
- clear stale/live state.

## Security
- authentication;
- authorization;
- LAN/NetBird restriction;
- server-side secrets;
- rate limiting;
- audit;
- validation;
- CSRF/XSS protection where applicable;
- SSRF protection;
- least privilege DB user.

## Observability
Monitor WAHA, session, BFF, backend, PostgreSQL, Redis, webhook freshness, reconciliation and sync lag.
