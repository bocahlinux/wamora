# API Contract

## Frontend -> BFF
Examples:
- session status
- send text
- session lifecycle
- QR/pairing

## Frontend -> Django
Examples:
- application data;
- durable conversation views (chat list, message history, mark as read —
  see `docs/generated/INBOX-CHAT-DECISION-REPORT.md` Section 1: resolved
  in favor of Frontend -> Django direct, matching this data's ownership
  below and the Dashboard endpoints' own precedent; superseding this
  file's earlier "chats/messages/mark read" listing under
  "Frontend -> BFF" above, which is now stale and has been corrected);
- audit;
- monitoring;
- reports;
- blast;
- sync status.

## WAHA -> Django
Webhook endpoint must validate, authenticate, be idempotent, and record processing state.

## Principles
JSON, consistent errors, request IDs, pagination, timestamps, permissions, and idempotency keys for side-effecting operations.
