# Phase 8C — BFF Environment Loading Fix

Focused remediation of the root cause confirmed in
`docs/generated/PHASE-8C-BFF-CORS-RUNTIME-REPORT.md`: `bff/.env` was
never loaded into the BFF's process environment by any mechanism, which
manifested as a missing CORS header but potentially affected every
`bff/.env`-sourced value (`WAHA_BASE_URL`, `WAHA_API_KEY`,
`JWT_PUBLIC_KEY`/`_PATH`, `INTERNAL_SERVICE_KEY`, etc.).

## 1. Problem statement

`GET http://localhost:8080/health` returned no
`Access-Control-Allow-Origin` header for `Origin: http://localhost:5173`,
even though `bff/.env` had the matching `CORS_ALLOWED_ORIGIN` value and
the CORS middleware itself was correctly wired. The prior runtime report
proved a clean process restart did not fix it, ruling out staleness.

## 2. Confirmed root cause (from the prior report, re-verified here)

`bff/.env` was never read by the BFF process at all — no `dotenv` (or
equivalent) dependency existed, no `--env-file` flag was used, and
`bff/src/config.ts` reads only from `process.env` directly. Whatever the
process's environment happened to already contain (nothing, in this
case) is what `config.ts` saw.

## 3. Existing startup/configuration behavior

- `bff/package.json`'s `"dev"` script: `tsx watch src/index.ts` (no env
  loading).
- `bff/src/config.ts`: reads `process.env.*` directly, with its own
  `readKey()` helper for the two-shape (`JWT_PUBLIC_KEY` inline vs.
  `JWT_PUBLIC_KEY_PATH` file path) pattern already shared with the Django
  side's `_read_key()`.
- Production (`infrastructure/tencent/docker-compose.yml`): the `bff`
  service already has `env_file: [.env]` at the **Docker Compose**
  level — Compose injects those variables into the container's
  environment before the Node process ever starts, completely
  independent of anything in `bff/package.json` or `bff/src/`. **This
  path was already correct and was not touched.**
- `bff/package.json`'s `"start"` script (`node dist/index.js`, used in
  production) was therefore **not** part of the problem and was **not**
  modified.

## 4. Chosen fix

Added Node's own native `--env-file-if-exists` flag to the `dev` script
only:

```diff
- "dev": "tsx watch src/index.ts",
+ "dev": "tsx watch --env-file-if-exists=.env src/index.ts",
```

Plus a short comment added to `bff/src/config.ts` explaining that this
module intentionally never loads `.env` itself — both the dev path (this
flag) and the production path (Compose's `env_file:`) converge on
`process.env` before `config.ts` runs.

**No new dependency was added.** `--env-file-if-exists` is a built-in
Node.js CLI flag (this repo's Node is v24.18.0; the flag has been stable
since well before that). `tsx` transparently forwards unrecognized CLI
flags through to the underlying `node` process it wraps — confirmed
empirically (Section 10) before editing anything, per this task's own
instruction not to assume a mechanism works without checking it against
this exact `tsx watch` setup.

## 5. Why this mechanism was selected over alternatives

- **`dotenv` package**: would work, but adds a runtime dependency and a
  manual `import 'dotenv/config'` (or explicit `dotenv.config()` call)
  that has to be the very first thing executed, before any other module
  that reads `config.ts` — easy to get subtly wrong (e.g. an import order
  issue) and one more thing to keep in sync with Node's own native
  behavior. Not needed here since Node already solves this natively.
- **Plain `--env-file=.env`**: rejected — this variant throws a hard
  error and refuses to start if the file is missing (verified directly:
  exit code 9, `"not found"`). That would be safe for local dev (the file
  is expected to exist) but is a latent trap if this script is ever
  reused somewhere `.env` isn't present, and provides no benefit over the
  `-if-exists` variant locally.
- **`--env-file-if-exists=.env`** (chosen): same native loading, but
  silently continues if the file is absent — verified directly (Section
  10). This mirrors the exact safety property `backend/config/env.py`
  already established for Django (auto-load locally, silent no-op when
  `.env` doesn't exist, e.g. in a container where Compose already
  injected the variables another way) — the most project-consistent
  choice available, and it needed zero new code, zero new dependency.
- **Modifying `"start"`/production**: rejected — production already has
  a working, independent mechanism (Compose's `env_file:`), confirmed by
  reading `infrastructure/tencent/docker-compose.yml` before deciding.
  Touching it would be an unnecessary, unrequested change to a path that
  was never broken.

## 6. Exact files changed

- `bff/package.json` — one line (`"dev"` script).
- `bff/src/config.ts` — comment only, no logic change.

No file under `frontend/`, `backend/`, or any `infrastructure/` path was
touched. `bff/.env` itself was not modified (only its already-known,
non-secret variable *names*, and — solely for verification — whether
each named value is present, were inspected; see Section 8).

## 7. Dependencies changed

None. `bff/package.json`'s `dependencies`/`devDependencies` are
byte-for-byte unchanged.

## 8. Security considerations

- No secret value (`WAHA_API_KEY`, `JWT_PUBLIC_KEY`/key file contents,
  `INTERNAL_SERVICE_KEY`, any DB credential) was printed anywhere in this
  session's tool output or is reproduced anywhere in this report.
  Verification of configuration presence used a boolean
  `present`/`absent` check only (`!!process.env[name]`), never a value
  dump.
- The CORS fail-closed behavior is unchanged and was re-verified:
  an unconfigured/malicious origin (`http://evil.example.com`) still
  receives no `Access-Control-Allow-Origin` header (Section 11). No
  wildcard origin was introduced.
- JWT verification's fail-closed behavior is unchanged and was
  re-verified: no token and a garbage token both still return `401`
  (Section 12). Authentication was not weakened — if anything, this fix
  makes the *real* verification path reachable at all in this dev
  environment, where it was previously always failing closed for the
  wrong reason (no key loaded, rather than an actual bad token).
- `bff/src/corsOptions.ts` and `bff/src/middleware/auth.ts` were read for
  understanding but **not modified** — the fix is entirely about getting
  correct values *into* `process.env`, not about the logic that consumes
  them.

## 9. Tests executed

```
npm run test        (vitest run)
→ Test Files  9 passed (9)
→ Tests       84 passed (84)

npm run typecheck    (tsc --noEmit)
→ clean, 0 errors

npm run build        (tsc -p tsconfig.json)
→ clean, 0 errors
```

All existing CORS/auth tests (`test/cors.test.ts`, `test/authMiddleware.test.ts`,
`test/routes.health.test.ts`, etc.) mock `../src/config` directly and
never exercise the real environment-loading path — so this fix, by
construction, could not have changed their outcome, and it didn't (all
84 still pass unchanged). No new automated test was added for the
`--env-file-if-exists` flag itself: it's a Node CLI behavior, not
application logic, and the project's test suite has no precedent for
spawning the real CLI/process (every existing test drives `createApp()`
in-process via `supertest`). The runtime verification below (Sections
10–13) is the direct, real-process equivalent, run against the actual
`npm run dev` command rather than simulated.

## 10. Runtime verification results

Stopped the entire pre-fix BFF process tree (all four PIDs: the `cmd.exe`
wrapper, `npm`, the `tsx watch` supervisor, and its worker), confirmed
port 8080 was free, then started it via the **exact, unmodified,
documented command**: `npm run dev` (which now runs `tsx watch
--env-file-if-exists=.env src/index.ts`). Startup log:

```
> waha-monitoring-bff@0.1.0 dev
> tsx watch --env-file-if-exists=.env src/index.ts

bff listening on port 8080
```

**Configuration presence, values never printed** (`npx tsx
--env-file-if-exists=.env -e "..."`, checking only
`!!process.env[name]`, run against the same `bff/.env` the real server
now loads):

| Variable | Present |
|---|---|
| `CORS_ALLOWED_ORIGIN` | yes |
| `WAHA_BASE_URL` | yes |
| `WAHA_API_KEY` | yes |
| `WAHA_SESSION_NAME` | **no** (see Section 14) |
| `JWT_PUBLIC_KEY` (inline) | no (not the variant used) |
| `JWT_PUBLIC_KEY_PATH` | yes (the variant actually configured) |
| `JWT_ISSUER` | yes |
| `JWT_AUDIENCE` | yes |
| `INTERNAL_SERVICE_KEY` | **no** (see Section 14) |
| `DJANGO_INTERNAL_BASE_URL` | **no** (see Section 14) |

`CORS_ALLOWED_ORIGIN`, `WAHA_BASE_URL`, `WAHA_API_KEY`,
`JWT_PUBLIC_KEY_PATH`, `JWT_ISSUER`, `JWT_AUDIENCE` — every variable
this fix was meant to restore — are now present. The three "no" rows are
pre-existing gaps in this specific dev `.env` (not something this fix
could or should populate) — see Section 14.

## 11. CORS verification results

Against the freshly restarted, fix-loaded process:

| Origin | Status | `Access-Control-Allow-Origin` |
|---|---|---|
| (none) | 200 | (absent, correct for a same-origin-style request) |
| `http://localhost:5173` | 200 | **`http://localhost:5173`** ✅ |
| `http://evil.example.com` | 200 | absent ✅ (still correctly rejected) |

The exact header this whole investigation was chasing is now present for
the real allowed origin, and the negative case (malicious origin) still
correctly receives nothing — the CORS *policy* itself needed no change,
exactly as the prior report concluded.

## 12. WAHA configuration/reachability result

Distinguishing the two explicitly, as required:

- **Configuration loaded**: yes — `WAHA_BASE_URL` and `WAHA_API_KEY` are
  both now present in the running process (Section 10), where before
  this fix they were not.
- **Actual connectivity**: `GET /health` →
  `{"status":"ok","service":"bff","waha":{"reachable":false}}`. **WAHA
  is NOT reachable.** This is a real result against this local dev
  machine, which has no live WAHA instance running, and is unrelated to
  this fix — per this task's explicit Step 5/9, no attempt was made to
  make WAHA reachable, and none is claimed here.

## 13. Regression results

- CORS allowlist semantics: unchanged — allowed origin still gets the
  header, malicious origin still doesn't, no wildcard introduced
  (Section 11).
- JWT verification/signing: unchanged code; **now functionally
  reachable** for the first time in this dev environment. Verified with
  three real requests to the existing authenticated route `GET
  /api/sessions/:session/status`:
  - No `Authorization` header → `401 {"code":"unauthorized","message":"Missing Authorization: Bearer <token> header"}`
  - A garbage token → `401 {"code":"unauthorized","message":"Missing or invalid token"}`
  - A **real JWT issued by the actual Django dev server** for its one
    real user, using the existing signing mechanism (no key material
    printed, no token value reproduced in this report) → **`404
    {"code":"not_found","message":"Unknown session"}`** — not `401`.
    Reaching the session-name check (which lives *after*
    `requireAuth`/`requireScope('reading')` in the route) is only
    possible if JWT verification actually succeeded. The `404` itself is
    correct and expected (Section 14), not a new problem.
- WAHA URL/API-key handling: unchanged code; now actually populated
  (Section 12) — no behavior in `wahaClient.ts` was touched.
- Internal service-key handling: unchanged code; this dev `.env` simply
  doesn't configure `INTERNAL_SERVICE_KEY` (Section 10) — no BFF→Django
  internal route was exercised in this task, so this wasn't tested
  end-to-end, only confirmed as "not present, same as before."
- Existing BFF route behavior: the full existing test suite (84 tests,
  covering health, sessions, messages, auth middleware, CORS, WAHA
  client, audit helper, allowlist) passes unchanged (Section 9).

## 14. Anything still open

- **`WAHA_SESSION_NAME` and `INTERNAL_SERVICE_KEY` are not set in this
  dev `bff/.env`** — confirmed present-as-a-name but empty-as-a-value
  (same "line exists, value blank" shape seen for `JWT_PUBLIC_KEY_PATH`
  before the earlier Django fix). This is why `/api/sessions/.../status`
  returns `404 "Unknown session"` even with a perfectly valid token, and
  why any BFF→Django internal call would presumably fail. **Not fixed
  here** — out of this task's explicit scope (only the confirmed
  env-loading defect was in scope), and doing so would mean writing a
  real session name / generating a real internal service key, which
  this task did not ask for and which touches `.env` values themselves
  (explicitly restricted to only "if absolutely required by an
  explicitly demonstrated configuration defect" — this is a *missing
  value*, not a *loading defect*, so it's out of scope here). Flagging
  it as a separate, pre-existing gap for you to decide on.
- WAHA itself remains unreachable in this local environment (Section
  12) — expected, not attempted, not claimed otherwise.
- No automated test directly exercises the `--env-file-if-exists` CLI
  flag (Section 9 explains why) — the runtime verification in this
  report is the closest equivalent and was performed against the real,
  unmodified `npm run dev` command.

## 15. Phase 9 was NOT started

Confirmed — this task was scoped entirely to the BFF environment-loading
defect. No Inbox/chat, notifications, search, Redis health, or any other
Phase 9 work was started or implied by anything in this report.

---

Do not start Phase 9 automatically.
