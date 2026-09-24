# Session Management — WAHA Configuration Audit

Read-only diagnostic. **No source, configuration, `.env`, or
infrastructure file was modified.** No secret value (`WAHA_API_KEY`, JWT
key material, `INTERNAL_SERVICE_KEY`, passwords, tokens) is printed
anywhere in this report or was echoed to any tool output — the API key
was used internally in one diagnostic request (Section 2) and
immediately discarded, never displayed.

## Summary of the finding, up front

**The `WAHA_SESSION_NAME` gap is a missing-configuration problem, not an
architecture problem, not a WAHA-reachability problem, and not a BFF
bug.** WAHA is actually running and reachable right now, with exactly one
real session on it, named **`no_epahari`**, status `WORKING` (i.e.
actively connected) — confirmed both directly against WAHA itself and
independently in Django's own `WahaSession` table. Two config files
currently disagree with that real name: `bff/.env`'s `WAHA_SESSION_NAME`
is empty, and `frontend/.env`'s `VITE_WAHA_SESSION_NAME` is set to a
leftover placeholder value (`test_session`) that was never the real
session. Both need to be corrected to `no_epahari` for Session Management
to work end-to-end locally — see Section 6 for the exact, minimal change.

A second, previously-mislabeled finding: the Dashboard's WAHA health card
showing "Not reachable" has **not actually meant WAHA is down** this
whole time — Section 3 explains why the BFF's own health check silently
skips its WAHA call entirely whenever `WAHA_SESSION_NAME` is empty,
which is exactly this gap, not a separate connectivity problem.

## 1. Existing WAHA-related configuration structure inspected

**Confirmed facts:**

- `bff/.env` variable *names* (grep only, no values beyond what's
  explicitly non-secret and noted below):
  `WAHA_BASE_URL`, `WAHA_API_KEY`, `WAHA_SESSION_NAME`, `WAHA_TIMEOUT_MS`,
  plus the unrelated CORS/JWT/internal-service vars already documented in
  earlier reports.
- `bff/.env`'s `WAHA_SESSION_NAME` line is present but **empty**
  (`WAHA_SESSION_NAME=`).
- `bff/.env`'s `WAHA_BASE_URL` (not a secret — a URL) is set to a real,
  reachable address on this network.
- `bff/.env.example` — read in full (it's an example file, safe to view
  entirely) — also ships `WAHA_SESSION_NAME=` empty, with the comment:
  *"this v1 BFF is provisioned for exactly one WAHA session; must match
  the session name configured on the Office/backend side."* **This
  confirms there is no project-wide canonical/hardcoded default session
  name anywhere in the repository** — it's explicitly meant to be filled
  in per-deployment, and the only place that documents what it should
  match is "the Office/backend side" (Django), not a fixed constant.
- `bff/src/config.ts`: `wahaSessionName: process.env.WAHA_SESSION_NAME ??
  ''` — a direct passthrough, no default, no fallback, no derivation
  from another source. Confirms the BFF has exactly one source of truth
  for this value: the env var itself.
- `bff/src/routes/sessionGuard.ts::validateSession()`: rejects any
  `:session` request-path value that doesn't exactly equal
  `config.wahaSessionName`, **and rejects everything unconditionally
  when `config.wahaSessionName` is falsy** (empty string included) — this
  is the exact code that produces every "Unknown session" 404 currently
  being seen.
- `frontend/.env`'s `VITE_WAHA_SESSION_NAME` is set to **`test_session`**
  — not empty, but not the real session name either (Section 2).
  `frontend/src/lib/config.ts` reads it directly
  (`import.meta.env.VITE_WAHA_SESSION_NAME ?? ''`), and
  `SessionsPage.tsx` uses that value, unmodified, for every session call
  — confirming the frontend code itself is wired correctly to *a*
  configured value; the value it's reading is simply the wrong one.
- `backend/.env` has **no `WAHA_SESSION_NAME`-equivalent variable at
  all** — by design: Django's `apps.waha_sessions.WahaSession` is a
  database table, not a single static config value, since Django's own
  architecture already supports (in principle) more than one session
  record. Only the BFF, which the Phase 6 contract provisions for
  exactly one session, needs a single static env var for this.
- `infrastructure/tencent/docker-compose.yml`: the `bff` service already
  declares `env_file: [.env]`, so in that deployment path this same
  variable would come from whatever `.env` sits next to that compose
  file at deploy time — not inspected further here since this is a local
  dev diagnostic, not a production one, and the task's scope is the
  local `WAHA_SESSION_NAME` gap.

## 2. Is WAHA actually running/reachable? What sessions exist?

**Confirmed by direct, read-only probes this task (no API key printed,
no state changed on the WAHA side — every request used was a `GET`):**

- `GET {WAHA_BASE_URL}/ping` → `200 {"message":"pong"}` — **WAHA is up
  and network-reachable from this machine**, no authentication needed for
  this endpoint.
- `GET {WAHA_BASE_URL}/` and `/health` → `401 Unauthorized` — also proves
  WAHA is up (a down/unreachable host would time out or refuse the
  connection outright, not return a structured 401 from the application
  itself); these specific endpoints just require the API key.
- `GET {WAHA_BASE_URL}/api/sessions` (with the configured `WAHA_API_KEY`,
  used only as a request header, never displayed) → `200`, returning
  **exactly one session**:
  ```
  name: no_epahari
  status: WORKING
  ```
  "WORKING" is WAHA's status value for an actively connected session
  (confirmed against `frontend/src/components/ui/StatusBadge.tsx`'s own
  `mapWahaStatus()` mapping, which already recognizes `'WORKING'` as the
  healthy state).

**Cross-checked independently against Django** (read-only query, no
write): `apps.waha_sessions.WahaSession.objects.all()` returns exactly
one row — `name = "no_epahari"`. This matches WAHA's live session name
exactly. `status`/`last_status_at` on that row are both blank/`None`,
meaning this record has a name but has never been synced/reconciled with
a live status update — a separate, minor observation, not the subject of
this diagnostic, and not changed here.

**Why the Dashboard's WAHA health card and the BFF's own `/health`
endpoint both report `reachable: false` despite WAHA genuinely being
reachable**: read `bff/src/routes/health.ts` directly —

```ts
if (config.wahaBaseUrl && config.wahaApiKey && config.wahaSessionName) {
  const result = await callWaha('getSessionStatus', config.wahaSessionName, {...});
  wahaReachable = result.outcome === 'success';
}
```

The reachability check only even **attempts** a call to WAHA when all
three of `wahaBaseUrl`/`wahaApiKey`/`wahaSessionName` are non-empty. With
`wahaSessionName` empty, this condition is false, so `wahaReachable`
defaults to `false` **without ever contacting WAHA** — not because WAHA
was checked and found down, but because the check was skipped entirely.
This is a **confirmed fact from reading the code**, not an inference: the
"Not reachable" status shown throughout this whole session's earlier
reports has been a symptom of this exact same missing `WAHA_SESSION_NAME`
value, not a separate WAHA connectivity problem.

## 3. Exact request path and where the 404 originates

**Confirmed, traced directly through the code, matching Section 1's
citations:**

```
Frontend (SessionsPage.tsx)
  → config.wahaSessionName (VITE_WAHA_SESSION_NAME = "test_session")
  → bffApi.ts's startSession/stopSession/.../getSessionQr/requestPairingCode
  → POST/GET {VITE_BFF_BASE_URL}/api/sessions/test_session/{action}
      ↓
BFF (bff/src/routes/session.ts, every handler)
  → validateSession(req, res)  [bff/src/routes/sessionGuard.ts]
  → compares req.params.session ("test_session", from the URL the
    frontend built) against config.wahaSessionName (currently "",
    from bff/.env)
  → "" is falsy → sendNotFound(res, 'Unknown session') → 404
      ↓
WAHA is never called at all for this request.
```

The 404 originates **entirely inside the BFF**, at the very first guard
in every session route, before any WAHA call is attempted — this is true
regardless of what session name the frontend sends, since an empty
`config.wahaSessionName` rejects every value unconditionally (Section 1).
Even if the frontend were already sending the correct `no_epahari`, the
BFF would still 404 today because its own side of the match is empty.

## 4. Is the frontend using the configured session identifier correctly?

**Yes — confirmed by reading `SessionsPage.tsx` again this task, no
change needed there.** Every call
(`getSessionStatus`/`startSession`/`stopSession`/`restartSession`/
`logoutSession`/`getSessionQr`/`requestPairingCode`) is passed the same
`sessionName` value, sourced once from `config.wahaSessionName`
(`frontend/src/lib/config.ts`), exactly as it was in the original Phase 7
implementation of this page (unchanged by the recent Session Management
work). The frontend code has no bug here — it faithfully sends whatever
`VITE_WAHA_SESSION_NAME` says, which is currently the wrong value
(`test_session` instead of `no_epahari`).

## 5. Confirmed facts / inferred findings / missing configuration / cannot verify

**Confirmed facts:**
- WAHA is up and reachable from this machine right now.
- WAHA has exactly one real session: `no_epahari`, status `WORKING`.
- Django's own `WahaSession` table already has a matching `no_epahari`
  row.
- `bff/.env`'s `WAHA_SESSION_NAME` is empty.
- `frontend/.env`'s `VITE_WAHA_SESSION_NAME` is `test_session` — not
  empty, but not `no_epahari` either.
- The BFF's `validateSession()` guard is the exact, sole source of every
  "Unknown session" 404 currently observed.
- The BFF's own `/health` WAHA-reachability check silently no-ops when
  `WAHA_SESSION_NAME` is empty, which is why "Not reachable" has been
  reported even though WAHA is actually up.
- No canonical/hardcoded default session name exists anywhere in this
  repository (`.env.example` ships it empty, by design, per its own
  comment).

**Inferred findings (reasonable conclusions, not directly stated
anywhere as a single fact):**
- `no_epahari` is almost certainly the correct value for both
  `WAHA_SESSION_NAME` (BFF) and `VITE_WAHA_SESSION_NAME` (frontend) —
  inferred from it being the *only* session WAHA has, and from it
  already existing as a named record in Django's own database. This
  audit does not *assert* it as project policy (no document states "the
  session shall be named no_epahari"), only as the one consistent,
  corroborated value across two independent live sources.
- `test_session` in `frontend/.env` is very likely a leftover value from
  earlier local development/testing (this exact string is used
  extensively as a generic placeholder throughout the BFF's and
  Django's own automated test suites), not a deliberately chosen real
  value.

**Missing configuration:**
- `bff/.env`'s `WAHA_SESSION_NAME` (currently empty).
- `frontend/.env`'s `VITE_WAHA_SESSION_NAME` (currently wrong, not
  empty).

**Cannot verify:**
- Whether `no_epahari` is the *permanent* intended session name for this
  deployment going forward, versus a temporary/test WhatsApp number
  someone connected while testing WAHA directly — that's a product fact
  only you know, not something derivable from the repository or from
  WAHA's API.
- Whether the production/Tencent deployment (`infrastructure/tencent/`)
  has the same or a different value configured in its own separate
  `.env` — out of scope for this local diagnostic, not checked.
- Whether WAHA's `no_epahari` session will still be `WORKING` by the
  time you act on this report — session state is live and can change
  independently of anything in this repository.

## 6. Exact minimal change required (not applied — for you to make manually)

Two variables, both currently wrong, in two different files:

| # | Variable | File | Current value | Required value | Format |
|---|---|---|---|---|---|
| 1 | `WAHA_SESSION_NAME` | `bff/.env` | *(empty)* | `no_epahari` | Plain string, no quotes, matching WAHA's exact session name |
| 2 | `VITE_WAHA_SESSION_NAME` | `frontend/.env` | `test_session` | `no_epahari` | Plain string, no quotes |

**After editing `bff/.env`**: the BFF **must be restarted**. Confirmed in
this session's earlier BFF env-loading work: `.env` is only read once, at
process startup (via the `--env-file-if-exists` flag now wired into
`npm run dev`); `tsx watch`'s auto-reload only reacts to source-file
changes, not `.env` changes, so editing the file alone does not take
effect on the already-running process.

**After editing `frontend/.env`**: restarting the Vite dev server
(`npm run dev` in `frontend/`) is the safe, verified action to take —
this session did not specifically re-verify whether Vite's dev server
auto-reloads on a plain `.env` file edit without a restart, so a restart
is the recommended, unambiguous way to guarantee the new value is picked
up, rather than assuming a live-reload behavior that wasn't tested here.

No other file needs to change. No code change is required — both the BFF
and the frontend already read and use these variables correctly; they
just currently hold the wrong values.

## 7. Architectural changes

**None recommended.** The current architecture (a single, statically
configured session name on the BFF side; the frontend reading its own
copy of the same value via `VITE_WAHA_SESSION_NAME`) is not broken — it
is working exactly as designed for this project's documented v1 scope
("Awal: 1 session," `docs/00-MASTER-SPEC.md`). The problem diagnosed here
is a configuration-value mismatch, not a design flaw, so per this task's
own instruction, no architectural change is proposed.

---

## Concise summary

- **WAHA is up and reachable.** It has exactly one real session:
  **`no_epahari`** (status `WORKING`).
- **`bff/.env`'s `WAHA_SESSION_NAME` is empty**, and
  **`frontend/.env`'s `VITE_WAHA_SESSION_NAME` is `test_session`** (a
  leftover placeholder) — neither matches the real session name.
- Every "Unknown session" 404 comes from the BFF's own
  `validateSession()` guard rejecting the mismatch — confirmed as the
  sole cause, no other bug found in the request path.
- The Dashboard's "WAHA Not reachable" status has the same root cause:
  the BFF's health check skips calling WAHA entirely whenever
  `WAHA_SESSION_NAME` is empty, so it isn't reporting a real
  connectivity failure.
- **Minimal fix** (not applied): set `WAHA_SESSION_NAME=no_epahari` in
  `bff/.env` (restart the BFF afterward) and
  `VITE_WAHA_SESSION_NAME=no_epahari` in `frontend/.env` (restart the
  Vite dev server afterward). No code change needed.
- No architectural change is recommended.

Stopping here, as requested. Not proceeding to Inbox/Chat or Phase 9.
