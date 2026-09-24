# Phase 7 Login Integration — CORS Fix Report

Implements the fix for the root cause identified in the prior read-only
diagnostic (Django emits no CORS response headers; the BFF's
`CORS_ALLOWED_ORIGIN` config existed but was never applied). Still Phase
7 integration work — no database model, migration, WAHA configuration,
or JWT authentication architecture was touched. Phase 8 was not started.

## Root cause (confirmed against current source before changing anything)

Re-read `docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md` and
`docs/generated/PHASE-7-IMPLEMENTATION-REPORT.md`, then re-inspected the
actual running configuration: `backend/config/settings.py` had zero CORS
handling (no `django-cors-headers`, no custom middleware, confirmed by
direct grep), and `bff/src/app.ts` never called any CORS middleware
despite `bff/src/config.ts` having read a `CORS_ALLOWED_ORIGIN` env var
since the Phase 0 scaffold. This matches the prior diagnostic exactly —
proceeded to fix as planned.

**One incident during this task, disclosed directly**: reading
`backend/.env` at one point (to find a safe insertion point for the new
setting) put its real contents — including `DJANGO_SECRET_KEY`,
`DB_PASSWORD`, and `WAHA_API_KEY` — into this session's own context,
instead of using the names-only `grep` pattern used everywhere else this
project. None of those values were reproduced anywhere in this report,
any file written, or any other output, and a targeted final grep of the
rebuilt frontend bundle for fragments of those specific values (not just
the generic secret-name patterns already checked routinely) confirmed
none reached it. Flagged here rather than left unmentioned.

## Django — implementation

- **Dependency**: `django-cors-headers==4.4.0` added to
  `backend/requirements.txt` — the standard, well-maintained solution;
  preferred over hand-written preflight-handling middleware given how
  easy that is to get subtly wrong (missing `Vary: Origin`, incomplete
  method/header negotiation).
- **`backend/config/settings.py`**:
  - `'corsheaders'` added to `INSTALLED_APPS`.
  - `'corsheaders.middleware.CorsMiddleware'` added to `MIDDLEWARE`,
    placed immediately after `SecurityMiddleware` and before
    `CommonMiddleware` — the library's own required placement.
  - `CORS_ALLOWED_ORIGINS` — parsed from a new `CORS_ALLOWED_ORIGINS` env
    var (comma-separated), empty by default. **Fails closed**: no
    variable set means no origin is permitted, not a wildcard.
  - `CORS_ALLOW_CREDENTIALS = False` — set explicitly (matches the
    library's own default) with a comment explaining why: this
    project's auth is a Bearer token in an `Authorization` header, never
    a cookie, and the frontend's `fetch()` calls never set `credentials:
    'include'` — credentialed CORS is genuinely not needed.
  - Allowed methods/headers were left at the library's defaults
    (`GET/POST/PUT/PATCH/DELETE/OPTIONS`; `accept, authorization,
    content-type, user-agent, x-csrftoken, x-requested-with`) — this
    already covers the login POST's `Content-Type: application/json`
    and every future authenticated call's `Authorization: Bearer`, so no
    narrower or broader custom list was written.
  - Existing security middleware/settings (SecurityMiddleware, CSRF,
    XFrameOptions, `SECURE_CONTENT_TYPE_NOSNIFF`, etc.) — untouched.

## BFF — implementation

- **Dependency**: `cors` (+ `@types/cors`) added to `bff/package.json` —
  the standard Express CORS middleware, same reasoning as the Django
  choice.
- **`bff/src/corsOptions.ts`** (new) — `buildCorsOptions(corsAllowedOrigin)`:
  splits the existing `CORS_ALLOWED_ORIGIN` config value on commas
  (forward-compatible with multiple origins despite the singular
  variable name, which was kept as-is since it already existed and
  renaming it wasn't required to fix the bug), returns `origin: false`
  (deny all) when unconfigured, `credentials: false` always — same
  Bearer-token reasoning as the Django side.
- **`bff/src/app.ts`** — now calls `app.use(cors(buildCorsOptions(config.corsAllowedOrigin)))`
  as the very first middleware, before `express.json()` and every route.
  This is the actual fix: the config value existed since Phase 0 and was
  simply never wired to anything.
- `bff/.env`'s `CORS_ALLOWED_ORIGIN` was found **already populated** (you
  had evidently set it) — left untouched, not overwritten.

## Environment variables introduced

| Variable | Component | Default | Notes |
|---|---|---|---|
| `CORS_ALLOWED_ORIGINS` | Django (`backend/.env.example`, `infrastructure/office/.env.example`) | empty (fails closed) | New. Comma-separated exact origins. |
| `CORS_ALLOWED_ORIGIN` | BFF | empty (fails closed) | Not new — existed since Phase 0; now actually applied. |

Real `.env` files updated with the local dev value (not a secret, just a
URL, same convention already used for `VITE_DJANGO_BASE_URL` etc.):
`backend/.env` now has `CORS_ALLOWED_ORIGINS=http://localhost:5173`.
`bff/.env` was left as you'd already configured it.

Neither `.env.example` change invents a new authentication mechanism —
these are transport-layer (browser same-origin policy) settings, not
identity/authorization settings; the JWT architecture is unchanged.

## Tests added

**Django** — `backend/apps/authn/tests/test_cors.py`, 6 tests:
- Preflight `OPTIONS /api/auth/login/` for the configured origin returns
  `Access-Control-Allow-Origin` + `POST` in `Access-Control-Allow-Methods`.
- Same preflight for an unconfigured/malicious origin (`evil.example.com`)
  returns **no** `Access-Control-Allow-Origin` header at all.
- The actual login `POST` response (not just the preflight) carries the
  header for the configured origin.
- Never emits `Access-Control-Allow-Origin: *`.
- Never emits `Access-Control-Allow-Credentials`.
- With `CORS_ALLOWED_ORIGINS=[]` (unconfigured), no origin is allowed —
  proves fail-closed, not permissive-by-default.

**BFF** — `bff/test/cors.test.ts`, 6 tests: the same six properties,
mirrored for the BFF (`Access-Control-Allow-Origin` present for the
configured origin on both a real request and a preflight `OPTIONS`;
absent for an unconfigured origin; never `*`; never
credentialed; empty config denies all origins).

## Tests executed and results

| Suite | Result |
|---|---|
| Django full suite (`manage.py test`, `config.settings_test`) | **178/178 passing** (172 pre-existing + 6 new) |
| `manage.py check` | Clean, run bare (real `.env`, no manual export) |
| `manage.py makemigrations --check --dry-run` | `No changes detected` |
| BFF full suite (`vitest run`) | **84/84 passing** (78 pre-existing + 6 new) |
| BFF `tsc --noEmit` | Clean |
| BFF production build | Clean |
| Frontend `tsc -b --noEmit` | Clean (untouched this round — regression check only) |
| Frontend production build | Clean, identical bundle composition to the prior report |
| Frontend `oxlint` | Same 4 pre-existing style warnings, 0 errors — no new findings |

## Verification performed (real server, not just test client)

**No browser was available in this environment — stated explicitly, not
claimed.** Verified instead at the HTTP level against an actual running
Django dev server (a scratch instance on `127.0.0.1:8001`, using the
real `backend/.env` including the real JWT key path — started and later
stopped by exact PID; your own server, if running separately on `:8000`,
was never touched):

```
OPTIONS /api/auth/login/, Origin: http://localhost:5173
  Access-Control-Request-Method: POST
  Access-Control-Request-Headers: content-type
→ 200, access-control-allow-origin: http://localhost:5173
  access-control-allow-headers: accept, authorization, content-type, ...
  access-control-allow-methods: DELETE, GET, OPTIONS, PATCH, POST, PUT

OPTIONS /api/auth/login/, Origin: http://evil.example.com
→ 200, no access-control-allow-* headers at all

POST /api/auth/login/, Origin: http://localhost:5173, bad credentials
→ 401 {"error":{"code":"invalid_credentials",...}}
  access-control-allow-origin: http://localhost:5173  (present even on
  a non-2xx response — necessary for the browser to expose the error
  body to the frontend's own error handling)
```

Real (non-placeholder) credentials were **not** used for this
server-level check — deliberately, since verifying the CORS header's
presence doesn't require a successful login, and you had already proven
login itself succeeds (your PowerShell test, and the prior diagnostic
round). This confirms:

- **Login still returns a JWT** — unaffected; `LoginView` itself was not
  modified, only middleware was added ahead of it.
- **The frontend can receive the login response** — the missing
  ingredient (the CORS header) is now present, on both the preflight and
  the real response.
- **BFF authentication remains intact** — `bff/src/jwt.ts` and the auth
  middleware were not touched; the BFF's own test suite (JWT
  verification, scope checks, all 8 routes) is unchanged and still
  fully passing.
- **No secret is exposed in frontend bundles or HTTP responses** — the
  frontend bundle was rebuilt and re-grepped (including for fragments of
  the specific real values that appeared in this session's own context
  during the incident above); the CORS response headers themselves carry
  no credential, only the origin string and method/header names.

## Limitations

- **No actual browser was used** — HTTP-level verification (`curl`
  simulating the exact preflight sequence a browser sends) was
  substituted, as instructed when a browser isn't available. This is
  strong evidence the mechanism is correct, but is not the same as
  confirming `LoginPage.tsx`'s own fetch call succeeds inside a real
  browser tab — recommend a manual check when convenient.
- **Rate limiting on `/api/auth/login/` remains unimplemented** —
  unchanged from the Phase 7 report, still explicitly Phase 12 scope.
- **CORS is now scoped to exactly one configured origin per
  deployment** (or a comma-separated few) — if the frontend is ever
  served from more than one origin in production (e.g. a staging domain
  alongside the main one), `CORS_ALLOWED_ORIGINS`/`CORS_ALLOWED_ORIGIN`
  need every one of them listed; this wasn't asked for and wasn't
  designed further.

## Files changed

`backend/.env`, `backend/.env.example`, `infrastructure/office/.env.example`,
`backend/config/settings.py`, `backend/requirements.txt`,
`backend/apps/authn/tests/test_cors.py` (new); `bff/package.json`,
`bff/package-lock.json`, `bff/src/app.ts`, `bff/src/corsOptions.ts` (new),
`bff/test/cors.test.ts` (new). `bff/.env` was inspected but not modified
(already correctly configured). No file under `frontend/` was modified.

---

## PHASE 7 LOGIN INTEGRATION FIX VERIFIED
