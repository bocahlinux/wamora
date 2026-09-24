# Final Deployment Topology

## Tencent VPS — Docker
- frontend
- bff
- waha

Flow:
Browser -> Frontend -> BFF -> WAHA -> WhatsApp

BFF should reach WAHA over Docker network where practical. Do not expose WAHA unnecessarily.

## Office Server — Docker
- backend
- celery-worker
- celery-beat
- redis

## Existing PostgreSQL
Backend -> PostgreSQL existing.

This is a hard rule: this project MUST NOT create a PostgreSQL Compose service.

## Office outage
Browser -> Tencent frontend/BFF -> WAHA continues.
Office backend/database are marked offline/degraded.

## Recovery
Office returns -> process/retry webhook deliveries where available -> reconciliation -> PostgreSQL.

Access is intended for authorized LAN/NetBird users with application-layer authentication/authorization.
