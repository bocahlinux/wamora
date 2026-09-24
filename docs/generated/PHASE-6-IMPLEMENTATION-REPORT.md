# Phase 6 — Implementation Report

Implementation performed against `docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md`
as the binding contract, using the explicitly-approved defaults (RS256;
8-hour single access token, no v1 refresh; 30-second `OutboundOperation`
staleness threshold; `INTERNAL_SERVICE_KEY` shared-secret for BFF↔Django;
session-scoped WAHA key design, with the dedicated-key fallback
documented, not implemented as a separate code path since both are "an
API key in a header" at the BFF's call site). No live WAHA call was made
at any point — every test mocks `fetch`/HTTP; `no_epahari` (the real
session) was never touched, queried, or referenced by any code or test.
No database model was modified; no migration was created (verified via
`makemigrations --check --dry-run`: "No changes detected"). Phase 7 was
not started.

## 1–2. Test suite run, exact counts

**Django (`backend/`)**: `manage.py test` (via `config.settings_test`,
the pre-existing SQLite test-settings override — used because the
configured PostgreSQL `DB_USER` still lacks `CREATEDB` in this sandbox,
a pre-existing environment limitation unrelated to this work).

```
Ran 168 tests in 3.262s
OK
```

168 = 122 pre-existing (untouched, still passing — confirms no
regression) + 46 new this round.

**BFF (`bff/`)**: `npx vitest run` (new test tooling this round — no
tests existed for the BFF before Phase 6).

```
Test Files  7 passed (7)
     Tests  68 passed (68)
```

**Combined: 236 tests, 236 passing, 0 failing.** `npx tsc --noEmit` and
`npm run build` both succeed cleanly.

## 3. Files changed

**Backend — new**:
`apps/authn/{__init__,apps,jwt_utils,serializers,views,urls}.py`,
`apps/authn/tests/{__init__,keys,test_jwt_utils,test_views}.py`,
`apps/core/internal_auth.py`, `apps/core/test_internal_auth.py`,
`apps/operations/{serializers,views,urls,test_views}.py`,
`apps/audit/{serializers,views,urls,test_views}.py`.

**Backend — modified**: `config/settings.py` (JWT/`INTERNAL_SERVICE_KEY`/staleness
config, `apps.authn` added to `INSTALLED_APPS`), `config/urls.py` (three
new `include()`s), `requirements.txt` (+`PyJWT`, +`cryptography`),
`.env.example`.

**BFF — new**: `src/app.ts`, `src/jwt.ts`, `src/errors.ts`,
`src/auditHelper.ts`, `src/djangoClient.ts`, `src/wahaClient.ts`,
`src/middleware/auth.ts`, `src/routes/{session,messages,health,sessionGuard}.ts`,
`test/{testKeys,jwt,authMiddleware,wahaAllowlist,wahaClient,routes.session,routes.messages,routes.health}.test.ts`.

**BFF — modified**: `src/config.ts` (new settings), `src/wahaAllowlist.ts`
(populated — was an empty array), `src/index.ts` (now imports `createApp()`),
`package.json` (+`jsonwebtoken`, +devDeps `vitest`/`supertest`/`@types/*`,
+`test` script), `.env.example`.

**Infrastructure**: `infrastructure/office/.env.example`,
`infrastructure/tencent/.env.example` — new variable documentation only;
neither `docker-compose.yml` was touched (both already use
`env_file: .env`, so no compose change was needed for new variables).

47 files total. No file outside `backend/`, `bff/`, and the two
`.env.example` files under `infrastructure/` was touched. `frontend/`
was not touched.

## 4. Schema/migration changes

**None.** `OutboundOperation` and `AuditLog` were used exactly as they
already existed — `OutboundOperation.audit_log` (the existing FK) links
a resolved send to its audit row; `TimeStampedModel.updated_at`
(`auto_now=True`, already present) backs the staleness policy. Confirmed
via `manage.py makemigrations --check --dry-run`: "No changes detected."
The contract's own instruction ("if the schema cannot represent a
required state safely, STOP and report") was not triggered — nothing
required it.

## 5. Remaining limitations

- **No refresh-token mechanism** — by design (approved default #3); a
  session longer than 8 hours, or an Office outage longer than 8 hours,
  requires re-login once Office is reachable.
- **No individual token revocation** before natural expiry — documented,
  accepted limitation from the contract (Section 4); mitigations are
  disabling the Django user (blocks new tokens) or full key rotation
  (invalidates everything).
- **The residual double-send window** named in the contract (Section 9):
  a retry after the 30-second staleness threshold, in the rare case the
  BFF crashed after a successful WAHA dispatch but before resolving the
  operation — implemented exactly as specified, risk not eliminated by
  construction (it can't be, without a WAHA-side correlatable ID, which
  doesn't exist).
- **QR/pairing field-level mapping is a generic, content-type-driven
  adapter** (`json`/`image`/`raw`), not a WAHA-field-specific one — WAHA's
  exact response shape remains undocumented at the field level; the
  adapter is isolated to one place in `routes/session.ts` for exactly
  this reason.
- **The BFF supports exactly one configured WAHA session** (`WAHA_SESSION_NAME`),
  not a session→key map — a deliberate v1 scope decision matching this
  project's actual current scale (1 session), not an oversight; extending
  to 2–3 sessions later means adding a lookup, not redesigning anything.
- **Rate limiting** (`docs/06-SECURITY.md`: "login, send, session control,
  blast...") was **not implemented** — explicitly Phase 12 per the
  contract's own phase boundary (Section 15), and explicitly excluded by
  this task's constraints ("Do not implement Phase 12 security
  hardening").
- **Django's `LoginView` does not rate-limit or lock out repeated failed
  attempts** — same reason as above.

## 6. Status breakdown

**Implemented and tested** (unit/integration, mocked HTTP — no live
WAHA):
- RS256 JWT issuance (Django) and verification (BFF), including expiry,
  wrong issuer, wrong audience, invalid signature, and an algorithm-confusion
  attempt (HS256-signed token using the public key as an HMAC secret —
  rejected).
- Scope→route authorization mapping, all 8 BFF routes.
- WAHA allowlist — structurally closed (only the 8 named endpoints are
  constructible at all, not just runtime-checked).
- All 8 BFF routes (status, start, stop, restart, logout, qr,
  pairing-code, messages) plus `/health`.
- The two Django internal endpoints (`OutboundOperation` register/resolve,
  `AuditLog` write), `INTERNAL_SERVICE_KEY` authentication (including the
  fail-closed-when-unconfigured case).
- The full outbound-idempotency state machine: first request, duplicate
  with PENDING/SENT/FAILED/fresh-UNKNOWN/stale-UNKNOWN, WAHA
  success/failure/timeout, Django-unreachable-at-registration degradation.
- Audit-after-resolution sequencing (never before — matches the schema
  constraint the contract identified), actor linkage, Django-unreachable-at-audit-time
  degradation (response to frontend still succeeds).
- No WAHA credential appears in any BFF response body (asserted directly
  in multiple tests).
- `/health` distinguishing BFF-process health from WAHA reachability.

**Implemented but not live-verified** (per this task's explicit
prohibition on destructive/state-changing calls against the real
session):
- Actual WAHA response bodies for start/stop/restart/logout/QR/pairing-code
  — the code handles them defensively (no field assumed with false
  confidence), but has not been exercised against a real WAHA instance.
- Whether the session-scoped WAHA API key (contract Section 6) is
  actually mintable/usable on this deployment — the BFF code path is
  identical for a scoped or dedicated key (just an API key value), so
  nothing here is blocked by this, but it's unverified.
- End-to-end behavior against real Django/WAHA over an actual network
  (NetBird/LAN) — only mocked in this round.

**Documented dependency, correctly out of this task's scope**:
- The frontend (Phase 7) — nothing to consume this API yet.
- Django chat/message read endpoints (Phase 8).
- Webhook target correction and `session.status` parser extension
  (Phase 14 / `apps/webhooks`, per the contract's Section 15 handoff
  table) — Phase 6's own audit design doesn't depend on either.
- Rate limiting / security hardening (Phase 12).

**Remaining blocker**: **none identified.** Every item in the contract
was either implemented as specified or was already labeled DEPENDENCY
(not BLOCKED) in the contract itself, and none of those dependencies
prevented writing or testing Phase 6's own code.
