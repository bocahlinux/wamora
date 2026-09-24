# Data Model

PostgreSQL is existing infrastructure and outside Docker.

Suggested entities:
- User
- Role
- Permission
- WahaSession
- Chat
- Contact
- Message
- MediaReference
- WebhookEvent
- SyncCheckpoint
- OutboundOperation
- AuditLog
- BlastCampaign
- BlastRecipient
- SystemHealthSnapshot

## Message identity
Use stable provider/WAHA identifiers scoped by session. Do not use body/timestamp/sender alone.

## WebhookEvent
Store provider event ID, session, type, received time, status, attempts, safe payload representation, processed time and error information. Processing must be idempotent.

## SyncCheckpoint
Track session, checkpoint, last run, status and lag/error.

## OutboundOperation
Track idempotency key, session, destination, operation, status, provider message ID if available, timestamps and audit relation.

All schema changes require migrations.
