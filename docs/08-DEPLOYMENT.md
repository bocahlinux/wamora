# Deployment

## Tencent Docker
Services:
- frontend
- bff
- waha

Preferred internal flow:
frontend -> bff -> waha

## Office Docker
Services:
- backend
- celery-worker
- celery-beat
- redis

## PostgreSQL
Use existing PostgreSQL. Configure host/IP, port, database, username and password manually.

DO NOT:
- create PostgreSQL service in Compose;
- expose PostgreSQL publicly;
- alter unrelated databases.

WAHA persistence uses configured `/app/.sessions` and `/app/.media`.

Secrets must be environment/secret-managed and never committed.
