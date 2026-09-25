# Phase 12 (Security Hardening) — Design Audit Report

**Read-only design audit.** No source, config, migration, Docker, or
dependency file was modified. No container was started, stopped, or
restarted. No migration or write/mutating endpoint was triggered. The
only file created by this task is this report.

Status classification used throughout: **VERIFIED FROM SOURCE** (read
the actual code/config and cite file:line), **INFERRED** (reasoned from
verified facts, not a direct citation), **NOT VERIFIED** (cannot be
confirmed either way from available evidence).

---

## 1. Objective

Turn `docs/generated/PHASE-ROADMAP-STATUS-AUDIT-REPORT.md`'s one-line
Phase 12 finding ("only incidental security-by-construction exists; no
dedicated pass, no generic rate limiting, no verified CSRF/XSS/DB-least-
privilege") into a scoped, evidence-backed design audit: what is
actually true today, item by item, classified as MUST-FIX / OBSERVATION
/ OUT-OF-SCOPE, with a recommended minimal first implementation slice.
No fixes are made here.

---

## 2. Phase 12 official scope (synthesized)

`docs/15-CODING-PHASES.md:15` gives zero elaboration beyond "12. Security
hardening" — **VERIFIED FROM SOURCE**. `docs/06-SECURITY.md` is the only
document that elaborates it, in full:

1. Authentication.
2. Authorization (separate permissions for session control, reading,
   sending, blast, user administration, system administration).
3. Network: frontend access restricted to LAN/NetBird.
4. Server-side secrets (WAHA key, DB credentials — never committed,
   never frontend-reachable).
5. SSRF: BFF only calls allowlisted WAHA endpoints, no arbitrary target.
6. Rate limits: login, send, session control, blast, expensive sync.
7. Audit: actor/time/action/target/result for sensitive operations.
8. Database: least privilege, no public exposure, backups/restore
   testing.
9. Catch-all: secure cookies, CSRF/XSS defenses where applicable,
   validation, security headers, dependency updates, log redaction.

**VERIFIED FROM SOURCE** — `docs/06-SECURITY.md:1-33` read in full.

Cross-checked against root/`docs/CLAUDE.md` hard rules for anything
security-relevant not already in the above list: rule 3 (WAHA key never
in frontend/localStorage/bundle), rule 4 (frontend never calls WAHA
directly), rule 5 (BFF allowlist discipline, not a generic proxy), rule
6/7 (webhook + outbound idempotency), rule 1/2 (no PostgreSQL Docker
service, never publicly exposed) — all already implied by
`docs/06-SECURITY.md` items 3–5 and 8 above, so no new scope item is
added; these are audited as explicit spot-checks in Section 3 instead.

Blast's own domain-specific rate limiting (60s/100/500) is explicitly
carved out of item 6 above per this task's instructions — already
audited end-to-end in `docs/generated/PHASE-11-BLAST-END-TO-END-AUDIT-REPORT.md`
Section 7, cited not re-derived.

---

## 3. Findings by requirement area

### 3.1 Authentication

**Status: adequate, no MUST-FIX.**

- Django is the sole issuer (RS256, asymmetric) — `backend/apps/authn/jwt_utils.py:66-71`,
  algorithm hardcoded as `settings.JWT_ALGORITHM = 'RS256'` (`backend/config/settings.py:275`),
  never attacker-influenced. **VERIFIED FROM SOURCE.**
- Django verifies its own issued tokens for direct frontend-facing
  endpoints (`/api/auth/me/`, `/api/dashboard/*`, `/api/chats/*`,
  `/api/sync/status/*`) via `JWTAuthentication.authenticate()`
  (`backend/apps/authn/authentication.py:46-53`) — `jwt.decode(..., algorithms=[settings.JWT_ALGORITHM], issuer=..., audience=...)`.
  A fixed one-element `algorithms` allowlist is passed explicitly, so
  PyJWT rejects `alg: none` and any algorithm other than `RS256` by
  construction — no algorithm-confusion risk. **VERIFIED FROM SOURCE.**
- The BFF independently verifies the same tokens for BFF-fronted routes:
  `jwt.verify(token, options.publicKey, { algorithms: ['RS256'], issuer, audience })`
  (`bff/src/jwt.ts:44-48`) — same fixed-algorithm-list posture, same
  library-level protection against algorithm confusion. **VERIFIED FROM
  SOURCE.**
- Both verifiers fail closed if the public key is unconfigured
  (`authentication.py:42-43`; `jwt.ts:40-42`), never echo the underlying
  JWT-library error text to the client (`authentication.py:54-59`;
  `jwt.ts:61-66`), and both use `payload.get('sub')`/`decoded.sub` to
  bind the token to a specific, still-`is_active` Django user
  (`authentication.py:61-66`). **VERIFIED FROM SOURCE.**
- Token lifetime: 8 hours, no refresh mechanism, an explicitly-approved
  v1 default (`settings.py:279-281`), documented as such. **VERIFIED
  FROM SOURCE.**
- `kid` is present in every issued token's header (`jwt_utils.py:70`)
  but read by neither verifier — inert, forward-compatibility-only, not
  a rotation mechanism, and the code says so explicitly
  (`jwt_utils.py:13-19`; `jwt.ts:7-15`). **VERIFIED FROM SOURCE** — not a
  gap, a documented limitation (single static key, no rotation), listed
  as OBSERVATION below since a compromised key cannot be rotated without
  redeploying config on both sides.

**OBSERVATION** — no key-rotation mechanism exists; a compromised
`JWT_PRIVATE_KEY`/`JWT_PUBLIC_KEY` pair requires a manual config change
on both Django and BFF, with no overlap window for in-flight tokens.
Acceptable for this project's scale/threat model (small number of
operators, LAN-restricted), not a Phase 12 blocker.

### 3.2 Authorization

**Status: mostly consistent; one MUST-FIX (mechanical), one already-documented weaker-gate precedent worth surfacing as OBSERVATION.**

Full `permission_classes` inventory across every `backend/apps/*/views.py`
(grepped this task):

| View | permission_classes | Verdict |
|---|---|---|
| `core.LivenessView`/`DatabaseHealthView`/`RedisHealthView` | `[]` (public) | **PASS** — intentionally public health probes, never touch secret/user data (`backend/apps/core/views.py:31-32,43-44,72-73`). |
| `authn.LoginView` | `[]` (public) | **PASS** — this IS the credential check; documented as intentionally public (`backend/apps/authn/views.py:19-27`). |
| `authn.MeView` | `[IsAuthenticated]` | **PASS** — identity-only response, no scope-gated data. |
| `chats.ChatListView`/`ChatMessagesView`/`ChatMarkReadView` | `[IsAuthenticated, HasReadingScope]` | **PASS** (`backend/apps/chats/views.py:44,65,82`). |
| `sync.SyncStatusView` | `[IsAuthenticated]` (no scope) | **Weaker gate, but explicitly documented as a deliberate precedent** — see below. |
| `sync` recovery view (`HasSystemAdministrationScope`, ~`views.py:237,411`) | `[IsAuthenticated, HasSystemAdministrationScope]` | **PASS.** |
| `dashboard.MessagesStatsView`/`ActivityFeedView` | `[IsAuthenticated]` (no scope) | **Weaker gate — see below.** |
| `webhooks.WahaWebhookView` | `[]` + manual HMAC signature check | **PASS** — machine caller, not a user; correct pattern (`backend/apps/webhooks/views.py:19-27,33-35`). |
| `operations.OutboundOperationRegisterView`/`ResolveView` | `[HasInternalServiceKey]` | **PASS** — BFF-only internal endpoints. |
| `audit.AuditEventCreateView` | `[HasInternalServiceKey]` | **PASS.** |
| `blast.*` (5 views) | `HasBlastScope`/`HasSystemAdministrationScope`, OR-combined where documented | **PASS** — already audited end-to-end, cited not re-derived. |

**Finding — Dashboard (`MessagesStatsView`, `ActivityFeedView`) and
`SyncStatusView` require only `IsAuthenticated`, no scope check** —
`backend/apps/dashboard/views.py:52-53,99-100`; `backend/apps/sync/views.py:158-159`.
`SyncStatusView`'s own docstring states this is a deliberate decision,
matching the Dashboard precedent exactly, reasoning that this is
"operational/system state, not conversation content"
(`sync/views.py:145-149`). **VERIFIED FROM SOURCE** this reasoning is
real and pre-existing, not an oversight — but `ActivityFeedView` merges
in `AuditLog` rows (`dashboard/views.py:105`), which include the actor,
action, and target of every session-control/blast-approval/recovery
action recorded in the system — i.e., any authenticated user, even one
with zero assigned scopes (a Django user with no Group membership and
not a superuser, per `compute_scopes()`, `jwt_utils.py:44-47`), can read
this activity feed. This is a real gap against `docs/06-SECURITY.md`'s
"separate permissions for ... reading, ... user administration, system
administration" principle, even though it was a conscious choice, not
an accident.

**MUST-FIX for Phase 12** (mechanical, low-ambiguity — no escalation
needed): gate `MessagesStatsView`, `ActivityFeedView`, and
`SyncStatusView` behind `HasReadingScope`, exactly mirroring the
existing `chats.*` pattern (`permission_classes = [IsAuthenticated,
HasReadingScope]`). This reuses an existing scope, requires no new
permission class, and does not change any other endpoint's contract.

No endpoint anywhere in `backend/apps/` was found with `permission_classes`
entirely absent (falling through to DRF's global default) or explicitly
`AllowAny` on a state-changing or data-returning endpoint. **VERIFIED
FROM SOURCE** (full grep, Section above).

### 3.3 LAN/NetBird restriction

**Status: NOT enforced in-repo, project-wide — confirmed, not just for Blast.**

- `infrastructure/tencent/docker-compose.yml:1-4,21-22` publishes
  `frontend` on `80:80` and `bff` on `8080:8080` with no interface
  restriction, and its own top comment states plainly: "Port access must
  be restricted at the network layer (LAN/NetBird), not by this file."
  **VERIFIED FROM SOURCE.**
- No NetBird/firewall config exists anywhere under `infrastructure/`
  (confirmed this task, matching the Blast audit's prior finding for the
  internal Blast endpoint specifically — `PHASE-11-BLAST-END-TO-END-AUDIT-REPORT.md:112`,
  cited not re-derived). This means the same "no application-level
  network isolation" gap applies not just to `/internal/blast/send` but
  to **every** BFF route, including the frontend-facing
  `/api/sessions/:session/*` and `/api/sessions/:session/messages`
  routes — their only defenses, verifiable from this repository, are
  JWT auth (`requireAuth`) and scope checks (`requireScope`), not
  network isolation. **VERIFIED FROM SOURCE.**
- Django's `ALLOWED_HOSTS` is env-driven and empty by default (fails
  closed — Django itself refuses to serve any host header until this is
  set — `backend/config/settings.py:37`), and `CORS_ALLOWED_ORIGINS` is
  likewise empty-by-default/fail-closed with `CORS_ALLOW_CREDENTIALS =
  False` (`settings.py:47,54`). These are real, correctly-configured
  controls, but they restrict which *origins/hosts* are accepted, not
  which *network* can reach the port at all — they do not substitute for
  LAN/NetBird firewalling. **VERIFIED FROM SOURCE.**
- `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md:45` still lists "NetBird/firewall
  rules" under "Open" — confirming this is a known, not-yet-decided gap,
  not a silent omission.

**OUT OF SCOPE for Phase 12 as an implementation item** — this is an
infra/ops firewall-configuration concern outside this repository
(`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`'s own "Open" list already
carries it separately from the numbered phases). Phase 12 cannot itself
"fix" this from source. What Phase 12 *can* do is documented below as a
MUST-FIX: state this limitation plainly in `docs/06-SECURITY.md`/deployment
docs so it isn't mistaken for a solved problem (it is currently stated
correctly in the Tencent compose file's own comment, but nowhere
consolidated as a cross-cutting "here is our actual exposure" statement
covering all BFF routes, not just Blast's).

### 3.4 Server-side secrets

**Status: correct pattern almost everywhere; one real MUST-FIX (Django `SECRET_KEY`).**

Every credential grepped this task — `WAHA_API_KEY`, `JWT_PRIVATE_KEY`/`JWT_PUBLIC_KEY`,
`INTERNAL_SERVICE_KEY`, `OFFICE_DISPATCH_SERVICE_KEY`, `DB_PASSWORD`,
webhook HMAC secret — is read from `os.environ`/`process.env` only,
defaults to `''` (fails closed: every consumer explicitly checks for
falsy and refuses to operate), and none is ever logged:
- `backend/config/settings.py:128-133` (`DB_*`), `:243-244` (`WAHA_*`),
  `:273-274` (JWT keys), `:306` (`INTERNAL_SERVICE_KEY`), `:328`
  (`OFFICE_DISPATCH_SERVICE_KEY`) — all `os.environ.get(..., '')`.
- `bff/src/config.ts:31-32,46,52,69` — same pattern, all
  `process.env.X ?? ''`.
- Fail-closed consumers: `authentication.py:42-43` (JWT), `internal_auth.py:24-26`
  (`HasInternalServiceKey`), `bff/src/middleware/officeAuth.ts:35-39`
  (constant-time `crypto.timingSafeEqual`, explicit empty-secret guard).
- Zero hits for `WAHA_API_KEY`/`apiKey` anywhere under `frontend/src`
  (grepped this task) — confirms hard rule 3 project-wide, not just for
  Blast. **VERIFIED FROM SOURCE.**
- No `console.log`/`logger`/`print` found emitting any of the above
  secret values in `bff/` or `backend/` (spot-checked `auditHelper.ts`,
  `officeAuth.ts`, `authentication.py`, `internal_auth.py`) —
  `authentication.py:54-59` and `jwt.ts:61-66` both deliberately return a
  single generic message rather than the underlying JWT-library error,
  which could otherwise leak claim/signature detail. **VERIFIED FROM
  SOURCE.**

**Finding — `DJANGO_SECRET_KEY` has a hardcoded, non-empty, insecure
fallback**: `SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-dev-only-placeholder')`
(`backend/config/settings.py:32`). Unlike every other secret on this
page, this one does **not** fail closed — if the env var is unset in a
real deployment, Django silently starts up and runs with a
well-known, publicly-guessable secret key (used for session signing,
password-reset tokens, and other Django-internal cryptographic
purposes) rather than refusing to start. The comment directly above it
(`:29-31`) acknowledges this is a placeholder and says production "MUST"
set it explicitly, but nothing in code enforces that "must." **VERIFIED
FROM SOURCE.**

**MUST-FIX for Phase 12** (mechanical, low-ambiguity): when `DEBUG` is
`False`, fail closed if `DJANGO_SECRET_KEY` is unset (raise
`ImproperlyConfigured`, mirroring the existing `JwtNotConfigured`/
`HasInternalServiceKey` fail-closed pattern already used consistently
elsewhere in this codebase) rather than silently falling back to the
placeholder value. Keep the placeholder fallback for `DEBUG=True` local
dev only.

`.gitignore` was not independently re-verified this task for excluding
real `.env` files — **NOT VERIFIED** (out of the file-reading budget for
this pass); `docs/generated/GITHUB-SECURITY-AUDIT.md` and
`GITHUB-PUBLICATION-REMEDIATION.md` already exist and cover this exact
question, so this is cited as likely-already-covered rather than
re-derived; if not already closed by those reports, it should be folded
into Phase 12's implementation, not re-audited fresh here.

### 3.5 Rate limiting

**Status: confirmed — zero generic rate limiting exists anywhere outside Blast's own domain-specific limits.**

- No `DEFAULT_THROTTLE_CLASSES`/`DEFAULT_THROTTLE_RATES` in
  `REST_FRAMEWORK` (`backend/config/settings.py:339-356`, read in full —
  absent). No `throttle_classes` on any view (grepped
  `throttle`/`THROTTLE` across all of `backend/` — the only hits are
  Blast's own domain-specific *message-spacing* throttle in
  `apps/blast/tasks.py`/`test_tasks.py`, an unrelated concept from DRF
  request throttling). **VERIFIED FROM SOURCE.**
- No rate-limiting middleware in the BFF: `bff/package.json:14-18`
  lists exactly `cors`, `express`, `jsonwebtoken` as dependencies — no
  `express-rate-limit` or equivalent. `bff/src/app.ts` mounts no such
  middleware. **VERIFIED FROM SOURCE.**
- `LoginView` explicitly documents the gap in its own docstring: "Rate
  limiting (docs/06-SECURITY.md 'Rate limits: login, ...') is explicitly
  Phase 12 (Security hardening) scope, not implemented here" —
  `backend/apps/authn/views.py:22-26`. This confirms the gap was a
  deliberate, tracked deferral, not an oversight the team was unaware
  of. **VERIFIED FROM SOURCE.**
- Concretely unprotected today: `POST /api/auth/login/` (brute-force
  credential guessing — no lockout, no throttle, no CAPTCHA, and no
  audit trail either, see 3.6), `POST /sessions/:session/messages`
  (send), `/sessions/:session/{start,stop,restart,logout,qr,pairing-code}`
  (session control), and the sync-status/reconciliation-recovery
  endpoints (expensive sync) — i.e. exactly the five categories
  `docs/06-SECURITY.md:24-25` names, none generically covered.

**MUST-FIX for Phase 12** (the gap itself is unambiguous; the specific
mechanism/thresholds are not — see USER DECISIONS REQUIRED, Section 5):
add rate limiting for at minimum login-attempt throttling (highest
severity — unauthenticated, credential-guessing surface) and ideally the
other four named categories.

### 3.6 Audit

**Status: real mechanism, applied broadly but inconsistently — one MUST-FIX.**

`AuditLog` (`backend/apps/audit/models.py:5-37`) is a genuine
actor/action/target/result/created_at record, append-only, already used
by:
- BFF-mediated session lifecycle/QR/pairing-code actions
  (`bff/src/routes/session.ts:76-93,137-144,191-197`, written via
  `recordAudit()`/`writeAuditEvent` → `apps.audit.AuditEventCreateView`).
- Send-message flow (`bff/src/routes/messages.ts:103-123`, written via
  the combined `OutboundOperationResolveView` call,
  `backend/apps/operations/views.py:103-111`).
- Blast approve/reject/recovery and sync reconciliation-recovery
  (confirmed by grep: `apps/blast/views.py`, `apps/sync/views.py` both
  call `AuditLog.objects.create`) — already covered by their own prior
  audits, cited not re-derived.

**Finding — `authn.LoginView` never writes an `AuditLog` entry, for
either successful or failed login attempts** — confirmed by reading
`backend/apps/authn/views.py:32-59` in full: the credential check, the
generic-401 failure path, and the success path all return directly with
no `AuditLog.objects.create` call anywhere in the file. Authentication
is the single most classic "sensitive operation" in
`docs/06-SECURITY.md`'s own audit requirement, and it is the one
completely unaudited action-with-a-result in the system — this also
means there is no source-of-truth trail for detecting brute-force
attempts (compounding the 3.5 rate-limiting gap). **VERIFIED FROM
SOURCE.**

**MUST-FIX for Phase 12** (mechanical, low-ambiguity): write an
`AuditLog` row (`action='auth.login'`, `target=username` or similar,
`result='success'`/`'failure'`) in `LoginView.post`, for both the
success path and the invalid-credentials path, mirroring the pattern
already used by `session.ts`'s `recordAudit()` calls.

`chats.ChatMarkReadView` (mark-as-read) is not audited — **OBSERVATION**,
not MUST-FIX: this is UI-attention-state, not a sensitive operation in
any reasonable reading of `docs/06-SECURITY.md`'s list, consistent with
`AuditLog`'s own model docstring naming exactly five fields for
"sensitive operations" specifically.

### 3.7 Validation

**Status: broadly solid; one MUST-FIX (Login), everything else spot-checked is adequately bounded.**

Every non-Blast DRF serializer under `backend/apps/*/serializers.py`
was read in full this task:
- `apps/audit/serializers.py` — `action` (max_length=128), `target`
  (max_length=255), `result` (`ChoiceField`) — bounded. **PASS.**
- `apps/operations/serializers.py` — `session`/`idempotency_key`/`destination`/`operation_type`/`provider_message_id`/`action`/`target`
  all `max_length`-bounded, `status`/`result` are `ChoiceField` — bounded.
  Internal-only endpoint (`HasInternalServiceKey`), not directly user
  reachable. **PASS.**
- `apps/chats/serializers.py` — read-only serializers, no writable
  fields exposed (mark-as-read is a dedicated view with no body). **PASS.**

**Finding — `apps/authn/serializers.py`'s `LoginSerializer` has no
length bound on either field**: `username = serializers.CharField()`,
`password = serializers.CharField(trim_whitespace=False)`
(`backend/apps/authn/serializers.py:4-6`), i.e. unbounded strings, on
the one endpoint in the system that is both public/unauthenticated and
currently unprotected by any rate limit (3.5) — an attacker can submit
arbitrarily large `username`/`password` values repeatedly with no
resource-consumption guard beyond whatever Django/WSGI-level request-body
limits exist upstream (not verified here). **VERIFIED FROM SOURCE.**

**MUST-FIX for Phase 12** (mechanical, low-ambiguity): add reasonable
`max_length` bounds to both `LoginSerializer` fields (e.g. 150 to match
Django's own default `AbstractUser.username` max length, and a
generous-but-bounded value such as 128 for `password`).

`bff/src/routes/messages.ts:33` validates `chatId`/`text` are non-empty
strings but applies no upper length bound before forwarding to WAHA
(`sendText`). **OBSERVATION**, not MUST-FIX: WhatsApp/WAHA itself
enforces a practical message-length ceiling downstream, this is at most
a minor resource-consumption/DoS nice-to-have, not a data-integrity or
auth gap, and no `docs/06-SECURITY.md` line explicitly names a message
length limit the way it does for login/rate limits.

### 3.8 CSRF/XSS protection where applicable

**Status: adequate as-is — no MUST-FIX.**

- **CSRF**: `django.middleware.csrf.CsrfViewMiddleware` is enabled
  (`backend/config/settings.py:91`, Django's own default, not disabled).
  Every DRF endpoint in this project sets `authentication_classes`
  explicitly to `[]` (public) or `[JWTAuthentication]` (Bearer-token,
  stateless) — never DRF's `SessionAuthentication` — so no API endpoint
  relies on the session cookie for auth, which is the precondition under
  which CSRF would matter for an API. Confirmed by reading every
  `views.py`'s `authentication_classes` value alongside its
  `permission_classes` (Section 3.2's table). `django.contrib.admin` is
  installed and does use session-cookie auth, and it remains protected
  by the same, un-disabled `CsrfViewMiddleware` — Django's normal
  default posture, appropriate here. **VERIFIED FROM SOURCE.** CSRF is
  therefore correctly moot for the JWT-based API surface and still
  actively enforced for the one part of the system (`/admin/`) that
  would need it.
- **Frontend XSS**: zero matches for `dangerouslySetInnerHTML` or
  `innerHTML` anywhere under `frontend/src` (grepped this task, whole
  directory) — chat message bodies render as plain React children
  (auto-escaped by JSX by construction), not raw HTML. **VERIFIED FROM
  SOURCE.**
- Access token storage: `frontend/src/lib/auth.ts:28-42` deliberately
  uses `sessionStorage`, not `localStorage`, with an explicit
  XSS-exposure-aware comment citing the same design contract report —
  a real, already-made, documented threat-model tradeoff (still
  script-readable if an XSS existed, but scoped to tab lifetime and a
  short 8h token). Not a gap given no XSS injection vector was found.
  **VERIFIED FROM SOURCE.**

**Security headers**: `X_FRAME_OPTIONS = 'DENY'`, `SECURE_CONTENT_TYPE_NOSNIFF
= True` are set (`settings.py:366-367`). `SECURE_SSL_REDIRECT`/HSTS are
explicitly and intentionally *not* set, with a comment stating this is
blocked on the still-open TLS/domain decision
(`settings.py:360-363`, `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md:44`
"TLS/domain" under Open). **OBSERVATION**, not MUST-FIX: correctly
sequenced — forcing HTTPS redirect/HSTS before TLS termination is
decided would break deployments; revisit once that open decision is
resolved (likely Phase 14, production deployment, per this project's own
comment).

### 3.9 SSRF protection

**Status: DONE, project-wide, not just Blast — no MUST-FIX.**

- `bff/src/wahaAllowlist.ts:12-38` — `WAHA_ALLOWED_ENDPOINTS` is a fixed,
  closed `Record<WahaEndpointName, ...>` with exactly 8 named entries;
  each entry's `path` is a template function taking only the (validated)
  session name, URL-encoded (`enc = encodeURIComponent`). No entry
  accepts an arbitrary path or host.
- `bff/src/wahaClient.ts:29-35` — `callWaha()` is structurally the only
  function that dispatches to WAHA; it looks up the endpoint by name
  from the fixed map and builds the URL as `new URL(endpoint.path(session),
  options.baseUrl)` — `baseUrl` always comes from `config.wahaBaseUrl`
  (server-side env var, `bff/src/config.ts:31`), never from request
  input. This is true for **every** BFF route that calls WAHA, not only
  Blast's: `messages.ts:69-74` (`sendText`), `session.ts:23,73,135,186`
  (status/lifecycle/QR/pairing) all go through this same single
  chokepoint. **VERIFIED FROM SOURCE** — confirms the general
  `messages.ts`/`session.ts` routes, not just Blast, satisfy hard rule 5.
- `bff/src/routes/sessionGuard.ts:11-18` — `validateSession()` further
  restricts the `:session` path parameter to exactly one
  server-configured name (`config.wahaSessionName`) before any WAHA call
  is made, rejecting anything else with 404 — an attacker cannot even
  select among sessions the BFF might hold, let alone inject an
  arbitrary path segment.
- Django → BFF (Office/Celery dispatch, used by Blast) and BFF → Django
  internal calls both use a fixed `baseUrl` from server-side settings
  (`BFF_INTERNAL_BASE_URL`/`DJANGO_INTERNAL_BASE_URL`), never
  user-supplied — already covered by the Blast audit for its own call
  path, consistent with what this task found for the general routes.

### 3.10 Least-privilege DB user

**Status: NOT VERIFIABLE from source — confirmed, not merely assumed.**

`backend/config/settings.py:125-134`'s `DATABASES['default']` reads
`DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT` purely from
environment variables, all defaulting to `''` — the actual Postgres role
`DB_USER` resolves to (superuser/owner vs. a scoped least-privilege
role) is determined entirely by the external, existing PostgreSQL
infrastructure this project explicitly does not own or provision
(`docs/CLAUDE.md` hard rule 1, `docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`).
No grant/role-creation SQL, no privilege documentation, and no
Postgres-side config exists anywhere in this repository. **NOT
VERIFIED** — this is correctly an infra/ops concern outside what source
review can confirm, matching the prior roadmap audit's same conclusion
(`PHASE-ROADMAP-STATUS-AUDIT-REPORT.md:177`, cited not re-derived).
`docs/02-REQUIREMENTS.md:47` and `docs/06-SECURITY.md:31` both name this
requirement but neither states how it is verified operationally.

**OUT OF SCOPE for Phase 12 as a code-level implementation item** — no
in-repo change can close this; it requires an operational action against
the existing Postgres instance (create/verify a scoped role, confirm
`DB_USER` in the real `.env` is that role, not the instance owner). Worth
naming explicitly as a Phase 14 (production deployment) checklist item
rather than silently dropped.

---

## 4. CLAUDE.md hard-rule spot-checks (security-relevant, cross-cutting)

1. **WAHA API key never frontend-reachable** — re-confirmed project-wide
   this task (Section 3.4): zero grep hits in `frontend/src`. **PASS.**
2. **BFF allowlist discipline holds for every route, not just Blast** —
   `bff/src/routes/` has exactly 5 route files
   (`sessionGuard.ts`, `health.ts`, `session.ts`, `messages.ts`,
   `internalBlast.ts`); `health.ts` was not read in full this task but
   is a standard liveness probe by name and mounted with no auth
   requirement at the app root (`app.ts:20`) — **NOT VERIFIED** in
   detail (out of this task's read budget) but low-risk by construction
   (a health endpoint has no WAHA-call surface). `session.ts` and
   `messages.ts` both route exclusively through `callWaha()`'s fixed
   allowlist (Section 3.9) — **PASS, project-wide**, not merely
   Blast-scoped. `internalBlast.ts` already covered by its own audit.
3. **Webhook idempotency** — already established
   (`docs/generated/PHASE-ROADMAP-STATUS-AUDIT-REPORT.md` Section 3,
   Phase 3 entry: `UniqueConstraint(fields=['session','provider_event_id'])`,
   `get_or_create` ingestion) — cited, not re-derived.
4. **PostgreSQL never publicly exposed** — `infrastructure/office/docker-compose.yml`
   defines no `postgres`/`db` service at all (correctly, per hard rule
   1) and no service in either compose file publishes a `5432` port.
   `redis` in `infrastructure/office/docker-compose.yml` has no
   published port either (internal Docker network only) — not a stated
   requirement but consistent with the same least-exposure posture.
   **VERIFIED FROM SOURCE**, both compose files read in full.

---

## 5. Consolidated MUST-FIX list

1. **Gate `dashboard.MessagesStatsView`/`ActivityFeedView` and
   `sync.SyncStatusView` behind `HasReadingScope`**, not bare
   `IsAuthenticated` — mirrors the existing `chats.*` pattern exactly.
   *Files*: `backend/apps/dashboard/views.py:52-53,99-100`,
   `backend/apps/sync/views.py:158-159`.
2. **Fail closed on missing `DJANGO_SECRET_KEY` when `DEBUG=False`**,
   instead of silently falling back to the known placeholder value.
   *File*: `backend/config/settings.py:32`.
3. **Audit `LoginView`'s success and failure outcomes** via
   `AuditLog.objects.create(action='auth.login', ...)`, mirroring the
   existing `recordAudit()`/`AuditEventCreateView` pattern used
   elsewhere. *File*: `backend/apps/authn/views.py:32-59`.
4. **Add `max_length` bounds to `LoginSerializer.username`/`.password`**.
   *File*: `backend/apps/authn/serializers.py:4-6`.
5. **Add rate limiting for at minimum the login endpoint** (brute-force
   guessing is the highest-severity unprotected surface, compounded by
   findings 3–4 above); ideally extend to send/session-control/blast/sync
   per `docs/06-SECURITY.md`'s own named list. *Mechanism/thresholds are
   a USER DECISION — see Section 6*, but the existence of the gap itself
   is not in question (Section 3.5).
6. **State the actual BFF network-exposure posture project-wide in
   documentation** (not just for Blast) — the Tencent compose file's own
   comment is accurate but Phase 12 should consolidate this into
   `docs/06-SECURITY.md`/deployment docs as a stated, accepted-for-now
   risk covering all BFF routes (Section 3.3), not merely note it in one
   compose file's header comment.

## 6. Consolidated OBSERVATION list

1. No JWT key-rotation mechanism — `kid` is present but inert; a
   compromised key pair requires manual, unstaged reconfiguration
   (Section 3.1).
2. `ActivityFeedView` exposing `AuditLog` rows to any authenticated user
   regardless of scope is being fixed by MUST-FIX #1 above, but is noted
   separately as a *design* observation: this was a conscious, documented
   precedent (`sync/views.py:145-149`), not an accident — worth a
   deliberate confirmation it's actually intended once fixed, not just a
   silent scope bump.
3. `bff/src/routes/messages.ts`'s `text` field has no upper length bound
   before forwarding to WAHA — minor resource-consumption nice-to-have,
   not a named requirement (Section 3.7).
4. `SECURE_SSL_REDIRECT`/HSTS intentionally deferred pending the TLS/domain
   open decision — correctly sequenced, revisit once that decision lands
   (Section 3.8).
5. `.gitignore`/committed-`.env` re-verification was not independently
   redone this task; likely already covered by
   `docs/generated/GITHUB-SECURITY-AUDIT.md`/`GITHUB-PUBLICATION-REMEDIATION.md`
   — fold into Phase 12 implementation only if those reports show it
   isn't actually closed (Section 3.4).
6. Dependency-update currency (`docs/06-SECURITY.md`'s catch-all line)
   was not audited this task (would require running `npm audit`/`pip`
   tooling, treated as out of this design-audit's read-only-source
   scope) — **NOT VERIFIED**, flag for a dedicated dependency-audit pass
   if desired, separate from this report.

## 7. Consolidated OUT-OF-SCOPE list (with pointers)

1. **Blast-specific security** (recipient caps, approval gate, dispatch
   throttling, BFF network-exposure finding for `/internal/blast/send`
   specifically) — fully covered by
   `docs/generated/PHASE-11-BLAST-END-TO-END-AUDIT-REPORT.md` Section 7.
   Cited in Section 3.3/3.9 above, not re-derived.
2. **Reconciliation/`possibly_stuck`/`SyncCheckpoint` internals** —
   covered by `docs/generated/NEXT-PHASE-RECONCILIATION-RECOVERY-DESIGN-AUDIT-REPORT.md`
   and related, relabeled Phase 4/9 work per
   `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` item 13.
3. **LAN/NetBird firewall rules themselves** (the actual network-layer
   configuration, as opposed to documenting the current gap, which is
   MUST-FIX #6 above) — an infra/ops action against real network
   equipment/NetBird config, already tracked separately in
   `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`'s "Open" list.
4. **Least-privilege DB user's actual creation/verification** — an
   operational action against the existing, externally-owned PostgreSQL
   instance; best tracked as a Phase 14 (production deployment)
   checklist item (Section 3.10).
5. **`SECURE_SSL_REDIRECT`/HSTS activation** — blocked on the still-open
   TLS/domain decision, not a Phase 12 code change today (Section 3.8).
6. **Any esamsat auto-reply bot / user-manager-handoff security design**
   — explicitly out of scope per this task's own instructions; these are
   unscoped, unphased candidate requirements
   (`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`'s "Open — new candidate
   requirements" section), not part of Phase 12.
7. **Dependency-CVE audit** — not performed this task (Section 6,
   Observation 6); if wanted, scope as its own pass.

---

## 8. USER DECISIONS REQUIRED

1. **Rate-limiting mechanism and thresholds.** The gap itself (no
   generic rate limiting exists anywhere) is unambiguous, but closing it
   requires choosing: (a) library/approach — DRF's built-in
   `throttle_classes`/`AnonRateThrottle`/`ScopedRateThrottle` on the
   Django side and a package such as `express-rate-limit` on the BFF
   side are the obvious defaults, but this project may prefer something
   else (e.g. a shared Redis-backed limiter, since Redis already exists
   in this stack); (b) which of the five named categories
   (login/send/session-control/blast/expensive-sync) to cover in a first
   slice vs. defer; (c) specific numeric thresholds for each. This
   report does not pick one — it is a genuine design choice with
   tradeoffs (in-memory vs. Redis-backed limiter, per-IP vs. per-user
   limiting, lockout duration for login).
2. **Whether to also add login lockout/backoff** (e.g. account-level
   temporary lockout after N failed attempts) beyond plain request-rate
   limiting — a stronger, more disruptive control with its own
   tradeoffs (denial-of-service-via-lockout risk against a legitimate
   user), not decided by `docs/06-SECURITY.md`'s one-line "rate limits:
   login" requirement alone.
3. **Whether to consolidate the BFF network-exposure statement (MUST-FIX
   #6) into a single doc now, or defer it to whenever the LAN/NetBird
   firewall rules themselves are finally configured** (Phase 14-adjacent)
   — a documentation-sequencing question, not a technical blocker.

No decision is required for MUST-FIX items #1–#4 — each has a single,
low-ambiguity mechanical fix already used as a working precedent
elsewhere in this exact codebase.

---

## 9. Closing recommendation — minimal first-slice Phase 12 scope

Given the findings above, the smallest coherent first implementation
slice (recommended, not decided) is:

**Tier 1 — purely mechanical, no design decisions needed, do first:**
MUST-FIX #1 (Dashboard/SyncStatus scope gate), #2 (SECRET_KEY fail-closed),
#3 (login audit), #4 (LoginSerializer length bounds). All four reuse
existing patterns already proven elsewhere in this codebase, touch only
`backend/apps/{authn,dashboard,sync}/`, and carry effectively zero
architectural risk.

**Tier 2 — requires the USER DECISIONS in Section 8 first:** MUST-FIX
#5 (rate limiting) — the highest-severity remaining gap (unprotected
login brute-force surface), but implementation must wait for the
mechanism/threshold decisions rather than being guessed at.

**Tier 3 — documentation only, no code:** MUST-FIX #6 (network-exposure
statement) — cheap, can be done alongside Tier 1.

This report does not implement any of the above. Explicit user approval
is required before any Phase 12 implementation work begins, per this
project's own hard rule 10 and this task's own stop condition.

---

## 10. Explicit STOP

This was a read-only design audit. Nothing was implemented, no fix was
applied, and no file other than this report was created or modified.
