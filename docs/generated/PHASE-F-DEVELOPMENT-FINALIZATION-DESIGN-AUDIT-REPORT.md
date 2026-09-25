# Phase F — Development Environment Finalization — Design Audit (Read-Only)

**Scope.** Read-only audit only. No file was modified while producing
this report. Every claim below was verified directly against current
source this task (git status/diff, `.gitignore`, both development
Compose files, all four `.env.example` files, `README.md` in full,
`docs/CLAUDE.md`/`docs/13`/`docs/14`), not assumed from Phase A–E's own
reports, though those reports agreed with everything found here.

---

## Executive Summary

The Docker development environment itself (Phase B/C/D's actual files)
is **functionally correct and internally consistent** — no architecture
defect was found. Two concrete, fixable gaps were found, both
documentation-only, neither requiring a `USER DECISIONS REQUIRED` escalation:

1. **README.md has a full "Office Development stack" section (Phase B)
   but no equivalent section for the Tencent Development stack (Phase
   C/D — BFF + frontend)** — a developer reading `README.md` top to
   bottom would learn how to Dockerize the backend but never discover
   that `infrastructure/development/tencent.yml` exists at all. This is
   the single largest gap blocking a true "clone → read README → run
   everything" first-time workflow (Section A).
2. **`infrastructure/development/.env.example`'s `INTERNAL_SERVICE_KEY`
   comment is stale** — it still says "This phase's Compose file does
   not include a BFF service... a separate, not-yet-implemented slice,"
   written during Phase B before Phase C/D existed. Now factually wrong.

Both are fixed in Phase F's implementation (Section 3 of the
implementation report). No architecture, security posture, external
dependency boundary, or Compose networking was found to need any change.

---

## A. First-Time Clone Workflow

**Walked through literally, step by step, against current `README.md`
and current files:**

1. **Clone** — no issue.
2. **Copy the correct `.env.example` files** — **partially documented**.
   `README.md`'s env-file table (lines 208-214) lists five files:
   `frontend/.env.example`, `bff/.env.example`, `backend/.env.example`,
   `infrastructure/tencent/.env.example`, `infrastructure/office/.env.example`.
   **It does not list `infrastructure/development/.env.example` or
   `infrastructure/development/tencent.env.example`** — both exist,
   both are real, both are required for the Docker development workflow,
   neither is mentioned in this table. A developer following only this
   table would not know these two files exist.
3. **Fill required values** — for the Office dev stack, the "Office
   Development stack" README section (lines 305-374) already gives a
   reasonable prepare-`.env` step, though it does not call out
   `DJANGO_ALLOWED_HOSTS`'s Phase-E-discovered nuance (that section's
   file itself now documents it, in its own comment — Section B below).
   **For the Tencent dev stack, there is no equivalent README section at
   all** — a developer has to discover `infrastructure/development/tencent.yml`
   and `tencent.env.example` exist by browsing the filesystem or reading
   `docs/generated/PHASE-C-*`/`PHASE-D-*` reports, neither of which
   `README.md` links to from its main body.
4. **Run the Office Compose project** — documented, step-by-step,
   already correct (verified live in Phase B/E).
5. **Run the Tencent Compose project** — **not documented anywhere in
   README.md**. The commands are simple
   (`cd infrastructure/development && cp tencent.env.example tencent.env`,
   `docker compose -f tencent.yml up --build`) and were proven correct
   live in Phase C/D/E, but nothing tells a new developer to run them.
6. **Access Django** (`:8000`) — implied by the Office section's own
   content but never explicitly stated as "open `http://localhost:8000/api/health/`
   to confirm it's up," unlike the Tencent section (which doesn't exist).
7. **Access BFF** (`:8080`) — not documented (falls under gap 5).
8. **Access frontend** (`:5173`) — not documented (falls under gap 5).

**Conclusion**: steps 4 and 2 (Office half) work today without
undocumented manual steps. **Steps 3/5/7/8 (the entire Tencent half) are
undocumented** — this is gap #1 from the executive summary, and the
single change with the most impact on "can a new developer actually do
this."

---

## B. Environment Files

**Verified directly, not assumed — exact variable inventory per file:**

| File | Owns | Belongs to |
|---|---|---|
| `infrastructure/development/.env.example` | `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_LOG_LEVEL`, `CORS_ALLOWED_ORIGINS`, `DB_HOST/PORT/NAME/USER/PASSWORD`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `RECONCILIATION_INTERVAL_SECONDS`, `RECONCILIATION_EXECUTOR`, `WAHA_WEBHOOK_HMAC_SECRET`, `WAHA_BASE_URL`, `WAHA_API_KEY`, `JWT_PRIVATE_KEY`(`_PATH`), `JWT_PUBLIC_KEY`(`_PATH`), `JWT_KID/ISSUER/AUDIENCE`, `JWT_ACCESS_TOKEN_LIFETIME_SECONDS`, `INTERNAL_SERVICE_KEY`, `OUTBOUND_OPERATION_STALE_SECONDS` | `office.yml`'s `backend`/`celery-worker`/`celery-beat` (all three read the same file, confirmed via each service's `env_file:`) |
| `infrastructure/development/tencent.env.example` | `PORT`, `WAHA_BASE_URL`, `WAHA_API_KEY`, `CORS_ALLOWED_ORIGIN`, `WAHA_SESSION_NAME`, `JWT_PUBLIC_KEY`(`_PATH`), `JWT_ISSUER/AUDIENCE`, `DJANGO_INTERNAL_BASE_URL`, `INTERNAL_SERVICE_KEY`, `DJANGO_INTERNAL_TIMEOUT_MS`, `WAHA_TIMEOUT_MS`, `VITE_BFF_BASE_URL`, `VITE_DJANGO_BASE_URL`, `VITE_WAHA_SESSION_NAME` | `tencent.yml`'s `bff` **and** `frontend` (both read the same file — confirmed; `frontend` ignores the BFF-only variables and vice versa, harmless, matching the existing pattern of `office.yml`'s three services sharing one file) |

**Not merged, deliberately, confirmed correct**: `frontend`'s own
`VITE_*` variables live in `tencent.env.example`, not a third file —
Phase D's design audit already established this (frontend joined the
*existing* Tencent-scoped file rather than getting its own), re-verified
here as still correct and still the only sensible reading of "which
variables belong to frontend" given frontend and BFF share one Compose
project.

**Which variables must be filled vs. can stay empty for
infrastructure-only development** (i.e., just proving Django↔Redis↔Celery
or BFF↔Django work, no real WAHA/PostgreSQL):

- **Must be filled for *any* meaningful development**: none, strictly —
  `DJANGO_SECRET_KEY` falls back to a safe placeholder
  (`config/settings.py`), every other field can stay empty and the
  stacks still start (confirmed live in Phase B/C/D/E).
- **Can safely stay empty for infrastructure-only development** (proven
  live, Phase E): `DB_HOST` and friends, `WAHA_*` (both files),
  `WAHA_WEBHOOK_HMAC_SECRET`, `JWT_PRIVATE_KEY`/`JWT_PUBLIC_KEY`,
  `INTERNAL_SERVICE_KEY` (BFF↔Django calls degrade to a logged
  "skipped," never crash — `bff/src/djangoClient.ts`'s own guard,
  re-confirmed this task).
- **Must be filled to reach a *real* PostgreSQL**: `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`
  — external, Section E.
- **Must be filled to reach a *real* WAHA**: `WAHA_BASE_URL`/`WAHA_API_KEY`
  (both files) — external, Section E.
- **Must be filled for the BFF↔Django hop to actually succeed** (not
  merely "not crash," proven live in Phase E): `DJANGO_ALLOWED_HOSTS`
  must include `host.docker.internal` (already documented in the Office
  file's own comment since the Phase E fix) — this is a
  Docker-development-specific requirement with no analog in the
  bare-host workflow, worth surfacing in README too (Section 3 of the
  implementation report).

**No variable was found to be blindly duplicated across files without
reason** — every shared-name variable (`WAHA_BASE_URL`, `JWT_ISSUER`,
`INTERNAL_SERVICE_KEY`, etc.) genuinely needs to exist independently on
each side of a trust/process boundary (BFF process vs. Django process),
matching the exact same duplication pattern the *production* `.env.example`
pair (`infrastructure/tencent/.env.example` + `infrastructure/office/.env.example`)
already has — not a new inconsistency introduced by the dev stack.

---

## C. Secrets

**Verified directly:**

- **`.gitignore`** (re-read in full): `.env`, `*/.env`, `**/.env`,
  `*.env`, `.env.*`, with `!**/.env.example` re-inclusion — covers
  `infrastructure/development/.env` and
  `infrastructure/development/tencent.env` correctly (confirmed live via
  `git check-ignore -v` in Phase B/C/D/E, not just by reading the
  pattern).
- **No secret values are committed** — `git status`/`git diff` show only
  `.env.example` files (all placeholder-only, confirmed by direct read,
  Section B) ever tracked; no real `.env` file appears in `git status`
  at any point in this session's history.
- **Celery beat schedule artifacts are ignored**: `celerybeat-schedule`,
  `celerybeat-schedule.*`, `celerybeat.pid` — added to `.gitignore`
  during Phase B specifically because this exact file was observed being
  written into the bind-mounted `backend/` directory live; re-confirmed
  present in the current `.gitignore` this task.
- **No other Docker-related temporary file class was found tracked or
  untracked-but-relevant** — `docker images`/`docker volume ls` were not
  part of this read-only audit (Step 1 forbids running anything), but
  `git status` shows nothing suspicious.

**No secret/Celery-artifact-related change is needed.**

---

## D. Compose Isolation

**Re-verified directly against the current files, not merely cited from
Phase B/C/D/E's own reports:**

- **Office (`office.yml`, implicit project name `development`) and
  Tencent (`tencent.yml`, explicit `name: wamora-dev-tencent`) remain
  fully separate** — confirmed by direct read: `tencent.yml`'s own
  comment (lines 32-40) explains exactly why the explicit `name:` is
  required (both files would otherwise default to the same
  directory-derived project name), and this was proven live in Phase
  C/E (`docker network ls` showing two genuinely distinct networks).
- **No shared Docker network** — neither file declares a `networks:`
  block referencing the other; each uses only its own project's default
  bridge network.
- **BFF reaches Django through the documented explicit URL** —
  `tencent.env.example`'s `DJANGO_INTERNAL_BASE_URL=http://host.docker.internal:8000`,
  confirmed still present, confirmed working live end-to-end in Phase E.
- **Frontend reaches published host URLs** — `VITE_BFF_BASE_URL=http://localhost:8080`,
  `VITE_DJANGO_BASE_URL=http://localhost:8000` in the same file,
  browser-resolved (Phase D's own source-level confirmation, re-verified
  this task by re-reading `frontend/src/lib/config.ts`: still exactly
  three `VITE_`-prefixed reads, no proxy).
- **Project names do not collide** — `development` vs.
  `wamora-dev-tencent`, confirmed distinct strings, confirmed live.
- **Starting/stopping one stack does not affect the other** — proven
  live in Phase E's clean-teardown-and-restart test (each `docker
  compose down`/`up` only ever touched its own project's containers and
  network, confirmed via `docker ps` between steps).

**No Compose isolation defect found.**

---

## E. External Dependencies

**Docker-managed** (all six confirmed running in their respective
Compose files this session): Django (`backend`), Celery worker, Celery
beat, Redis — `office.yml`; BFF, frontend — `tencent.yml`.

**External, confirmed intentionally absent from both files**:
PostgreSQL (hard rule #1, `docs/CLAUDE.md`, re-confirmed present and
unchanged this task — "Never create a PostgreSQL Docker service");
WAHA (no `waha` service defined in either development file, confirmed by
direct read — its only Compose definition anywhere remains
`infrastructure/tencent/docker-compose.yml`'s **production** file,
untouched by any of Phase B–F).

**Nothing in the current repository justifies adding either to the
development stack** — this audit does not propose doing so, and none of
Phase B/C/D/E's own design work ever considered it a gap; re-confirmed
here as still the correct boundary.

---

## F. Hot Reload

**Re-verified directly (source + the live results Phase E already
captured, re-read rather than re-run since Step 1 is read-only):**

| Component | Mechanism | Manual step ever needed? |
|---|---|---|
| Django | `runserver`'s `StatReloader` | No — automatic, proven live (Phase E) |
| BFF | `tsx watch` + `CHOKIDAR_USEPOLLING=true` | No — automatic, proven live |
| Frontend | Vite HMR + `CHOKIDAR_USEPOLLING=true` | No — automatic, proven live |
| Celery worker | **None** | **Yes** — manual `docker compose -f office.yml restart celery-worker celery-beat` after any change to task-affecting code, already honestly documented in `README.md`'s own Office Development section (line 358-366) |
| Celery beat | **None** | Same as worker |

**No `watchdog`/`watchmedo` exists anywhere in either file or either
component's dependency tree** — re-confirmed by direct read of both
Compose files (Section D) and `bff/package.json`/`frontend/package.json`
(no such dependency listed). The Celery limitation is already honestly
documented; nothing to change here.

---

## G. Port Map (Verified From Current Files, Not Assumed)

| Service | Host port | Container port | Published? |
|---|---|---|---|
| Django (`backend`) | `8000` | `8000` | Yes |
| Redis | — | `6379` | **No** — confirmed by direct read of `office.yml`: `redis` has no `ports:` entry, only a `healthcheck:`; reachable only via `docker compose exec redis redis-cli` (already documented in README) or from `backend`/`celery-worker`/`celery-beat` over the `development` project's own internal network |
| BFF | `8080` | `8080` | Yes |
| Frontend (Vite) | `5173` | `5173` | Yes |

**Redis's non-publication is intentional**, not an oversight — the
Phase B design audit's own reasoning (no code in this repository
connects to Redis directly outside a Django/Celery process) still holds,
re-confirmed by this task's own source read finding no new Redis client
usage anywhere.

---

## H. First-Time Setup — README Sufficiency

**Directly answering the task's own literal pipeline:**

```
git clone
↓
copy env examples          ← PARTIAL: table (README:208-214) omits the two dev-stack files (Section A/B)
↓
fill environment variables ← OK for Office; Tencent has no guidance at all (no section exists)
↓
start Office stack         ← OK, fully documented (README:305-374)
↓
start Tencent stack        ← MISSING — no README section exists
↓
verify services            ← OK for Office (curl examples implied by the health-endpoint prose elsewhere in README); MISSING for Tencent
↓
develop                    ← OK for Office (hot-reload behavior documented); MISSING for Tencent (never mentioned)
```

**Exact documentation changes required** (implemented in Phase F,
Section 3 of the implementation report): add a "Tencent Development
stack (Docker, hot reload)" section to `README.md`, mirroring the
existing Office section's structure and depth exactly (prepare env →
build/start → detached → logs → stop → hot-reload notes → dev-vs-prod
comparison table), and add the two missing rows to the env-file table.

---

## I. Cleanup Commands (Verified Correct, for Documentation)

Derived directly from Docker Compose's own documented behavior and
re-confirmed against this session's own extensive live use of these
exact commands in Phase B–E:

- **Stop one stack**: `docker compose -f infrastructure/development/office.yml down`
  (or `tencent.yml`) — removes that project's containers + network,
  leaves the other project entirely untouched (Section D).
- **Stop everything**: run `down` on both files.
- **Rebuild one service**: `docker compose -f <file> build <service>`
  (or `up -d --build <service>` to rebuild and restart in one step).
- **Rebuild everything in a file**: `docker compose -f <file> up --build -d`.
- **View logs**: `docker compose -f <file> logs -f <service>` (already
  documented for Office; needs the Tencent equivalent, Section A/H).
- **Check status**: `docker compose -f <file> ps`.
- **Remove containers** (already covered by `down`, no separate command
  needed for the normal case).
- **Remove volumes**: `docker compose -f <file> down -v` — **destructive,
  labeled as such**; the only anonymous volumes in either file are the
  `node_modules` ones (`tencent.yml`'s `bff`/`frontend` services) and
  neither file has a named, data-bearing volume (Redis has none, by
  design, Section G) — so `-v` here only ever discards a reinstallable
  `node_modules` cache, never real data, but this audit still recommends
  documenting it as an explicit, opt-in flag rather than defaulting to
  it in any instruction.

---

## USER DECISIONS REQUIRED

**None.** Every finding in this audit is documentation-only
(README content, one stale code comment) — no new service, no
Compose-networking change, no dependency addition, no change to the
external PostgreSQL/WAHA boundary, and no security-behavior change was
found or is proposed. Per the task's own guidance, these are exactly the
class of "preference-level documentation choices" (heading wording,
section structure, comment accuracy) that should be resolved directly
rather than escalated. Proceeding to implementation.
