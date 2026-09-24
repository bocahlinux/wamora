# UI/UX Specification

Global status must answer:
1. Is WhatsApp online?
2. Is WAHA online?
3. Is office backend online?
4. Is PostgreSQL online?
5. Is synchronization healthy?

Example:

WAHA       ONLINE
WhatsApp   WORKING
Backend    OFFLINE
Database   OFFLINE
Sync       STALE

## Screens
- Dashboard
- Inbox
- Session management
- Monitoring
- Blast

## Offline UX
When office is down, do not show the whole system as offline. Keep live WAHA features when available. Label data as live/cached/stale/unavailable. Disable only features that genuinely require office persistence.

Status must not rely on color alone.
