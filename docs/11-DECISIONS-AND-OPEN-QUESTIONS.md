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

## Open
- exact auth implementation;
- frontend versions;
- WebSocket vs SSE;
- blast limits/approval;
- backup retention;
- exact PostgreSQL host/IP/db;
- TLS/domain;
- NetBird/firewall rules.
