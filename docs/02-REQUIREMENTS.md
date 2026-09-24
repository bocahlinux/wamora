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
