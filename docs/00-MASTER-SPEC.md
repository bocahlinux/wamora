# Master Specification

## Product
Dashboard internal untuk monitoring dan operasi WAHA. Awal: 1 session, kemungkinan maksimal 2–3.

## Fitur
- monitoring session;
- start/stop/restart;
- QR/pairing;
- chat list;
- message history;
- receive/send/reply;
- mark as read;
- webhook;
- audit;
- reconciliation;
- health monitoring;
- controlled blast.

## Availability
WAHA/Tencent tetap dapat bekerja ketika server kantor mati. Fitur yang membutuhkan persistence kantor menjadi degraded dan diberi status jelas. Setelah kantor hidup, reconciliation memperbaiki data.

## Technology
### Tencent Docker
- WAHA GOWS
- React frontend
- BFF/API Gateway (Node.js + TypeScript, Express)

### Office Docker
- Django/DRF
- Celery worker/beat
- Redis

### Existing
- PostgreSQL existing, bukan Docker service.

## Ownership
WAHA: live WhatsApp/session state.
PostgreSQL: durable users, chats/messages, webhook records, sync checkpoints, outbound operations, audit, reporting.

## Non-goals
- PostgreSQL container baru;
- public database;
- frontend direct-to-WAHA;
- generic BFF proxy.
