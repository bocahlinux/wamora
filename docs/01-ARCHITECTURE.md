# Architecture

```text
Authorized Client
   |
 LAN / NetBird
   |
   v
Tencent VPS
 Docker:
   React Frontend
   BFF/API Gateway
   WAHA GOWS
   |
 WhatsApp

NetBird/LAN
   |
   v
Office Server
 Docker:
   Django/DRF
   Celery Worker
   Celery Beat
   Redis
   |
 TCP 5432
   |
   v
Existing PostgreSQL
```

## BFF
BFF adalah server-side boundary antara browser dan WAHA. BFF melindungi credential WAHA, melakukan validation/authorization, dan hanya mengekspos endpoint yang diperlukan. BFF bukan generic proxy.

## Backend
Django/DRF menangani durable application data, webhook ingestion, reconciliation, audit, reporting, permissions, dan business rules.

## Failure isolation
Office outage tidak boleh otomatis mematikan Tencent/WAHA. PostgreSQL outage tidak boleh dianggap sebagai WAHA outage.
