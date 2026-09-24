# Test Plan

## Unit
Normalization, webhook idempotency, permissions, validation, reconciliation checkpoint, outbound idempotency.

## Integration
WAHA -> webhook -> PostgreSQL; BFF -> WAHA; Django -> Redis/Celery; frontend -> BFF/Django.

## Failure
1. Office server off: WAHA remains working; live operations remain possible; office shows offline.
2. PostgreSQL off: DB health fails; persistence/retry behavior is safe.
3. Redis off: background jobs fail visibly; WAHA remains independent.
4. BFF/WAHA off: live features unavailable with exact failure domain.
5. Network partition in both directions.
6. Duplicate webhook produces no duplicate durable message.
7. Recovery reconciles missing data.
8. Ambiguous outbound result does not cause duplicate send.

## Security
Verify frontend cannot obtain WAHA key, unauthorized actions return 401/403, BFF rejects arbitrary URLs, DB is not public, and secrets are absent from logs.
