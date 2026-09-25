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

### Current BFF network-exposure reality (Phase 12)
This applies to **every** BFF route, not just Blast's internal dispatch
endpoint — stated here once, project-wide, rather than only in one Compose
file's comment.

- `infrastructure/tencent/docker-compose.yml` publishes the `frontend`
  (`80:80`) and `bff` (`8080:8080`) ports with no interface restriction of
  any kind. No NetBird/firewall configuration exists anywhere in this
  repository today.
- The BFF's **only application-level defenses** are JWT authentication
  (`requireAuth`) and scope checks (`requireScope`) for the frontend-facing
  routes (`session.ts`, `messages.ts`), the shared-secret check
  (`requireOfficeDispatchKey`) for the internal Blast dispatch route
  (`internalBlast.ts`), and, as of Phase 12, a general per-IP rate limit on
  the frontend-facing routes (`middleware/rateLimit.ts`). **There is no
  in-repo network-layer isolation backing any of this** — anyone who can
  reach the published Tencent port at all can attempt authentication
  against it.
- This is a known, accepted-for-now gap, not an oversight: NetBird/firewall
  rules remain an explicit **open item**
  (`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`'s "Open" list) that must be
  resolved at the infrastructure/ops layer — restricting which networks can
  reach the published frontend/BFF ports at all — before or during
  production deployment (Phase 14). Until that is done, this project's
  actual security boundary for the Tencent-published surface is
  authentication/authorization at the application layer only, not network
  isolation.

## SSRF
BFF only calls allowlisted WAHA endpoints. No arbitrary target URL.

## Rate limits
Login, send, session control, blast and expensive sync.

## Audit
Record actor, time, action, target and result for sensitive operations.

## Database
Least privilege, no public exposure, backups and restore testing.

Also apply secure cookies, CSRF/XSS defenses where applicable, validation, security headers, dependency updates and log redaction.
