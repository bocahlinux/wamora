# Phase 6 — Authentication and API Decisions

Read-only research. No application code, models, migrations, frontend,
BFF routes, or authentication code were modified.

## Terminology flag — read this first

This task's own instructions describe the boundary as *"Frontend →
Django BFF → WAHA."* Every prior project document
(`docs/00-MASTER-SPEC.md`, `docs/01-ARCHITECTURE.md`,
`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` Final #11,
`docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`, `CLAUDE.md`) consistently and
repeatedly describes the BFF as a **separate Node.js/TypeScript/Express
process on the Tencent VPS**, distinct from **Django/DRF on the Office
server**. This is recorded as a "Final" (not "Open") decision. This
report treats "Django BFF" in the task instructions as informal shorthand
and proceeds using the standing, already-decided two-component
architecture (Node.js BFF + Django backend) as authoritative — but this
phrasing is flagged explicitly in case it actually signals an intent to
reconsider the architecture, which would itself need to be raised and
confirmed before Phase 6 proceeds, not decided silently here.

## 1. Already documented facts

- Authentication is a required capability
  (`docs/02-REQUIREMENTS.md`, "Security").
- **"Exact auth implementation" is explicitly listed as unresolved**
  (`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`, "Open" section, item 1).
- `docs/06-SECURITY.md` requires "separate permissions for session
  control, reading, sending, blast, user administration and system
  administration" (authorization scopes — not an authentication
  mechanism) and says to "apply secure cookies, CSRF/XSS defenses where
  applicable" (conditional language — doesn't mandate cookies, doesn't
  rule them out either).
- `CLAUDE.md`/`docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`: frontend access is
  restricted to LAN/NetBird — a **network-perimeter** control, separate
  from and in addition to whatever application-level authentication is
  chosen.
- `docs/00-MASTER-SPEC.md`, "Availability": *"WAHA/Tencent tetap dapat
  bekerja ketika server kantor mati"* (WAHA/Tencent keeps working when
  the office server is down) — this is an existing, non-negotiable
  requirement that turns out to bear directly on which auth mechanism is
  suitable (see Section 3).

## 2. Inferred requirements (not stated outright, but reasonably derived)

- Since the BFF is a genuinely separate process from Django, on a
  separate site, **whatever auth mechanism is chosen must be verifiable
  by the BFF** — either independently, or via a call back to Django. This
  choice has real consequences for the Availability requirement above.
- Given "separate permissions for session control, reading, sending,
  blast, user administration and system administration" (`06-SECURITY.md`),
  the chosen mechanism needs to be able to carry or look up
  per-user authorization scope somewhere in the request path.

## 3. Options comparison

### Option A — Django session/cookie authentication

Already installed and unused: `django.contrib.sessions`,
`django.contrib.auth`, `SessionMiddleware`, `AuthenticationMiddleware`
have been present in `INSTALLED_APPS`/`MIDDLEWARE` since Phase 0, but no
login view, no real `User` row, and no session flow has ever been
exercised.

- **Browser/frontend compatibility**: native browser support; requires
  `credentials: 'include'` on frontend requests and correct
  cross-origin cookie configuration (relevant since frontend and Django
  are on different sites — Tencent vs. Office).
- **CSRF implications**: required. Django's CSRF middleware is already
  installed but not wired for API use (token endpoint, header
  convention).
- **Session handling**: server-side, DB-backed by default (Django's
  `django_session` table) — Django can revoke a session immediately.
- **Authorization enforcement**: integrates directly with Django's
  built-in `Permission`/`Group` model, already used elsewhere in this
  project (`AuditLog.actor` references `AUTH_USER_MODEL`, Phase 2).
- **Logout behavior**: immediate server-side invalidation.
- **Security implications**: needs `HttpOnly`/`Secure`/`SameSite`
  cookie flags and a working CSRF flow; strong revocation story.
- **Suitability for this project's topology — a real problem, not a
  generic tradeoff**: a Django-issued session cookie can only be
  *validated* by asking Django (a live DB lookup, or the BFF proxying
  the check to Django over the Office↔Tencent NetBird link). If the BFF
  needs to reach Django to validate every request, then **an office
  outage would also take down BFF authentication — meaning users could
  be locked out of the very live-WAHA features the BFF exists to keep
  available during an office outage.** This directly conflicts with the
  documented Availability requirement (Section 1) unless deliberately
  designed around (e.g. a short-lived local cache of "is this session
  currently valid," which reintroduces staleness/complexity this option
  doesn't naturally provide).

### Option B — JWT/Bearer authentication

Not currently used anywhere in this project, but no new dependency would
be needed on the Django side (JWT libraries are common, lightweight
additions) or the BFF side (Express JWT verification is a small,
well-established library).

- **Browser/frontend compatibility**: sent via `Authorization: Bearer`
  header; typically held in memory or `sessionStorage` (avoid
  `localStorage` for anything long-lived, due to XSS exposure).
- **CSRF implications**: not vulnerable by default, *provided* the token
  is never placed in a cookie the browser attaches automatically. If a
  cookie-based JWT pattern were chosen instead, CSRF defenses would be
  needed again.
- **Session handling**: stateless by design — a signature check is
  sufficient to validate the token, **no live database/session lookup
  required**, which is the key property that matters here (see below).
- **Authorization enforcement**: claims can be embedded directly in the
  token (e.g. permission scopes), letting the BFF authorize a request
  without a live call to Django.
- **Logout behavior**: harder — a stateless token can't be un-signed
  early. Needs either short expiry + refresh tokens, or a revocation
  list (which reintroduces a shared, live-checkable store — Redis
  already exists in this project's Office infrastructure since Phase 5,
  though using it for this would be a new use beyond its current
  Celery-broker role, and checking it live reintroduces the same
  Office-dependency problem Option A has, unless revocation-checking is
  explicitly best-effort/skipped during an outage).
- **Security implications**: token leakage risk depends entirely on
  storage choice (client-side); requires a shared verification
  secret/key distributed securely to both the Tencent BFF and the Office
  Django — an operational detail with its own exposure surface (though
  no worse in kind than the WAHA API key / webhook HMAC secret this
  project already manages this way).
- **Suitability for this project's topology — directly favorable to the
  stated Availability requirement**: because JWT verification doesn't
  require a live round-trip to Django, **the BFF could keep validating
  already-issued tokens locally even while Office is unreachable**,
  letting already-authenticated users keep using live WAHA features
  during an outage — the scenario `docs/00-MASTER-SPEC.md`'s
  Availability section explicitly cares about. This does **not** give
  full resilience: a *brand-new* login during an outage would still fail,
  since Django (the natural place to verify credentials against
  `Permission`/`Group`) is the issuer and is unreachable — but
  *continuity* for already-logged-in users is meaningfully better than
  Option A.

### Option C — DRF `TokenAuthentication` (already available via the installed `djangorestframework` dependency)

A middle ground: opaque, DB-backed bearer tokens (not self-verifying like
JWT). No new dependency needed (ships with DRF, already in
`requirements.txt`).

- Same browser/CSRF profile as JWT (header-based, not automatically
  attached by the browser).
- **Session handling**: stateful — requires a live DB lookup per
  request to validate the token, same as Option A. **Inherits Option
  A's Availability problem**: the BFF would still need to reach Django
  (or a shared, synchronously-queryable store) to validate every
  request.
- Simpler to implement and revoke instantly (delete the DB row) than
  JWT, at the direct cost of the offline-continuity property.

### Not a real fourth option, but worth naming: the existing webhook-HMAC pattern

`apps/webhooks/authentication.py` (Phase 3) implements shared-secret HMAC
verification for the WAHA→Django webhook. This is a **machine-to-machine**
pattern (verifying that a request genuinely came from WAHA), not a
user-facing browser authentication scheme — it's structurally unsuited to
authenticating a human frontend user, and is noted here only because the
task asked to consider "another existing mechanism already present in
the project."

## 4. Authentication decision status

**UNRESOLVED — explicitly marked "Open" in the project's own decisions
log, and not decided by this report.** Per the instruction not to select
a winner unless requirements clearly determine one: they don't
*fully* determine one, but they do weigh meaningfully — the documented
Availability requirement (Section 1) is a real, project-specific reason
Option B (JWT) or a hybrid deserves serious weight over Option A/C,
which would make BFF-level authentication itself dependent on Office
being reachable. This is surfaced as a decision input, not a decision.

**Requires your explicit confirmation before Phase 6 implementation
begins.**

## 5. Proposed options for approval (not implemented)

1. **JWT issued by Django, verified independently by both Django and the
   BFF** — best alignment with the Availability requirement; requires
   sharing a verification secret/key with the Tencent-side BFF and
   designing token expiry/refresh and a revocation story deliberately.
2. **Django session/cookie auth**, accepting that BFF-side authentication
   would depend on Office being reachable (a real regression against the
   documented Availability goal, but simpler to build and revoke, and
   fully reuses Django's already-installed auth stack with no new
   moving parts).
3. **DRF `TokenAuthentication`** — same Office-dependency limitation as
   #2, but a smaller, DB-simple mechanism if the Availability tradeoff
   in #2 is judged acceptable and JWT's added complexity isn't wanted.

This report does not recommend one over the others as final — it lays
out which tradeoffs are real and specific to this project versus which
are generic, so the decision can be made deliberately.
