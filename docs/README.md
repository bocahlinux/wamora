# WAHA Dashboard — Claude Engineering Pack

Blueprint implementasi dashboard WAHA dengan arsitektur terpisah antara Tencent, server kantor, dan PostgreSQL existing.

## Topologi final
Tencent Docker:
- WAHA GOWS
- React frontend
- BFF/API Gateway (Node.js + TypeScript, Express)

Server kantor Docker:
- Django + DRF
- Celery worker
- Celery beat
- Redis

PostgreSQL:
- Existing infrastructure
- BUKAN container Docker project ini
- Host/IP/database/credential dikonfigurasi manual

## Prinsip
- Frontend tidak pernah menerima WAHA API key.
- Frontend tidak memanggil WAHA langsung; gunakan BFF.
- Backend kantor menjadi durable application backend.
- WAHA menjadi live WhatsApp gateway.
- Webhook harus idempotent.
- Reconciliation wajib setelah office outage.
- Sistem harus membedakan WAHA online dari backend/database kantor offline.

Baca `CLAUDE.md` sebelum coding.
