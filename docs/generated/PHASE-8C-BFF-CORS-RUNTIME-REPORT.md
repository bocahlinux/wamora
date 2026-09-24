# Phase 8C — BFF Runtime CORS Verification

Runtime-only investigation of the one finding left open by the Phase 8C
acceptance report: `GET http://localhost:8080/health` returning no
`Access-Control-Allow-Origin` header for `Origin: http://localhost:5173`,
despite `bff/.env` already having `CORS_ALLOWED_ORIGIN=http://localhost:5173`
and the CORS middleware being correctly wired in `bff/src/app.ts`.

**No source, config, or `.env` file was modified.** The only action taken
was stopping and restarting the existing BFF development process, exactly
as this task's scope allowed.

## 1. Process/runtime action performed

1. Identified the process listening on port 8080: a `tsx watch
   src/index.ts` tree (`cmd.exe` → `tsx watch` supervisor → `node`
   worker running `src/index.ts`), started at `2026-09-24 14:11:29` — i.e.
   before the acceptance check that surfaced this finding.
2. Stopped the full process tree (all four PIDs in the chain — the
   `cmd.exe` wrapper, the `tsx watch` supervisor, and the running
   worker).
3. Confirmed port 8080 was no longer listening.
4. Restarted it cleanly with `npm run dev` (`tsx watch src/index.ts`,
   the project's own existing script — no flags added, no different
   invocation) from the `bff/` directory.
5. Confirmed it came up: `bff listening on port 8080`, `GET /health` →
   `200`.

## 2. Endpoint tested, Origin used, HTTP status

| # | Request | Origin header | Status |
|---|---|---|---|
| 1 | `GET http://localhost:8080/health` | (none) | 200 |
| 2 | `GET http://localhost:8080/health` | `http://localhost:5173` | 200 |

## 3. Relevant CORS response headers

Both requests, against the **freshly restarted** process, returned the
identical header set:

```
HTTP/1.1 200 OK
X-Powered-By: Express
Content-Type: application/json; charset=utf-8
Content-Length: 58
ETag: W/"3a-PL2fjqzIpM7F2vsr6Nj/Inko/88"
Date: Thu, 24 Sep 2026 11:55:25 GMT
Connection: keep-alive
Keep-Alive: timeout=5
```

**`Access-Control-Allow-Origin` is still absent after a clean restart.**
The acceptance report's "stale process" hypothesis is therefore **not**
the cause — a full stop/restart reproduces the exact same missing-header
symptom.

## 4. WAHA health value

```json
{"status":"ok","service":"bff","waha":{"reachable":false}}
```

Identical to the value observed in the acceptance report before this
restart — `waha.reachable: false` is a real, unattempted-to-fix value (no
WAHA connectivity configuration was touched, per this task's explicit
Step 5). No unrelated field or value changed as a result of the restart.

## 5. Whether a code/config change was required

**No — and none was made.** This report is verification/root-cause-only,
per this task's explicit "DO NOT modify source/config yet" instruction
for exactly this outcome (header still missing after a clean restart).

## 6. Root cause

**`bff/.env` is never loaded into the BFF process's environment by any
mechanism — this is structural, not a stale-process symptom.** Evidence:

- `bff/src/config.ts` reads configuration directly from `process.env`
  (`process.env.CORS_ALLOWED_ORIGIN ?? ''`, etc.) with no call to load an
  `.env` file anywhere in that module.
- `bff/src/index.ts` and `bff/src/app.ts` were also checked — neither
  loads an `.env` file either.
- `bff/package.json`'s `"dev"` script is exactly `tsx watch src/index.ts`
  — no `--env-file` flag (Node.js's own native `.env` support, available
  since Node 20.6, is opt-in via that flag and was never passed here).
- `dotenv` (or any equivalent package) is not a dependency anywhere in
  `bff/package.json`, and a repo-wide search of `bff/` for `dotenv` found
  no references at all — unlike the Django side, which has its own
  explicit auto-load fix (`backend/config/env.py`, added in an earlier
  phase specifically to solve this same class of problem for Django).
- Checked for a persistent OS-level fallback that could otherwise explain
  a working value: `[Environment]::GetEnvironmentVariable('CORS_ALLOWED_ORIGIN', 'User'|'Machine'|'Process')`
  all returned empty, and the shell used to restart the process had no
  such variable exported either. There is no hidden global source
  supplying this value.

Put simply: `bff/.env` is a file that documents the intended
configuration, but nothing in the BFF's own code or its `npm run dev`
script ever reads it. Whatever value `CORS_ALLOWED_ORIGIN` resolves to at
runtime depends entirely on whether the *shell that launches* `npm run
dev` happened to already have that variable exported (e.g. via a shell
profile) — for the instance restarted in this session, it did not, so it
fell back to the code's own default (`''`), which `buildCorsOptions('')`
correctly (per its own fail-closed design) turns into "no origin
allowed," producing exactly the symptom observed.

This is very likely the same reason the *original* (pre-restart) process
also showed the missing header — not because it started before `.env`
was edited, but because `.env` was never going to be read by that process
regardless of when it started.

**Caveat, stated explicitly**: this session's shell never exports
`CORS_ALLOWED_ORIGIN`. If your own terminal (the one you'd normally use
to run `npm run dev` yourself) has it exported some other way, a restart
from *that* terminal specifically could behave differently than the
restart performed here. Nothing observed in this session rules that out
with certainty — but no such mechanism was found anywhere in the
repository, which is the more likely explanation.

## 7. Confirmation: Phase 8C frontend/Django implementation unchanged

Confirmed. This task touched only the BFF's already-running **process**
(stopped and restarted via its own existing `npm run dev` script) — no
file under `frontend/`, `backend/`, or `bff/src/` was read for editing or
written to. `bff/.env` was read (names and the already-known
non-secret `CORS_ALLOWED_ORIGIN` value) but not modified. No Django code,
no frontend code, no API contract, and no dependency was changed.

## 8. Can this finding now be considered closed?

**Root cause is identified and confirmed — but the underlying issue is
not fixed, because fixing it (adding an `.env`-loading mechanism to the
BFF, mirroring `backend/config/env.py`) is a source-code change, and this
task's scope was explicitly restart/investigate-only.** This should be
treated as **open**, not closed, with a clear, narrow next step if you
want it fixed: give the BFF the same kind of `.env` auto-load Django
already has (e.g. a `dotenv`-based loader invoked at the top of
`bff/src/index.ts`, or an `--env-file=.env` flag added to the `dev`
script) — a small, self-contained change, not a CORS redesign; the CORS
middleware itself (`bff/src/corsOptions.ts`, `bff/src/app.ts`) is correct
as-is and would need no change.

This finding does **not** affect any of the three Phase 8C dashboard
endpoints — those are served entirely by Django (`:8000`), which already
has its own working `.env` auto-load, confirmed independently in the
acceptance report. It only affects the pre-existing BFF `/health` (and by
extension any other BFF route depending on `bff/.env` values — e.g.
`WAHA_BASE_URL`, `WAHA_API_KEY`, `JWT_PUBLIC_KEY`/`_PATH`,
`INTERNAL_SERVICE_KEY` — all read the same unloaded way).

---

Do not proceed to Phase 9 automatically.
