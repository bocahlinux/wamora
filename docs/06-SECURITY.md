# Security Architecture

## Zones
Browser -> Tencent -> Office -> PostgreSQL.

## Secrets
WAHA API key and DB credentials are server-side only. Never commit secrets.

## WAHA
Preferred flow:
Browser -> BFF -> WAHA

WAHA port should not be unnecessarily public if BFF can reach it over Docker network.

## Authorization
Separate permissions for session control, reading, sending, blast, user administration and system administration.

## Network
Frontend access is restricted to LAN and/or NetBird as defined in deployment.

## SSRF
BFF only calls allowlisted WAHA endpoints. No arbitrary target URL.

## Rate limits
Login, send, session control, blast and expensive sync.

## Audit
Record actor, time, action, target and result for sensitive operations.

## Database
Least privilege, no public exposure, backups and restore testing.

Also apply secure cookies, CSRF/XSS defenses where applicable, validation, security headers, dependency updates and log redaction.
