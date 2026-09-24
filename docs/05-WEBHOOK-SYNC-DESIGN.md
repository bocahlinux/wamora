# Webhook and Synchronization

Normal flow:

WhatsApp -> WAHA -> Django webhook -> idempotency -> durable event -> normalize -> PostgreSQL

Webhook delivery is not assumed exactly-once.

## Office outage
WAHA continues operating. Webhook delivery may fail. Live messages remain accessible through WAHA.

## Recovery
WAHA -> reconciliation job -> fetch history -> compare stable IDs -> insert missing records -> advance checkpoint.

Reconciliation must be repeatable, paginated, transaction-aware, and duplicate-safe.

## Outbound during outage
Use an idempotency key. Send through BFF/WAHA. When office returns, record/reconcile provider message ID. Never blindly resend an operation whose success is uncertain.
