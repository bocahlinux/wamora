# Phase B — Development Docker Environment — Design Audit (Read-Only)

**Scope.** Design/read-only audit only, following
`docs/generated/DOCKER-ENVIRONMENT-ARCHITECTURE-AUDIT-REPORT.md` and the
now-complete `docs/generated/PHASE-A-RECONCILIATION-EXECUTOR-IMPLEMENTATION-REPORT.md`
(Phase A — not modified, not repeated, not re-audited here beyond
confirming its one file's state, Section 1). No source code, Dockerfile,
Compose file, `.env`, database, or deployment configuration was modified.
No container was started, no live deployment was run. Every relevant file
named in this report was re-read directly this task — not assumed from
the prior audit — and every place a prior finding is reused, it is
reused because it was independently re-confirmed unchanged, not because
it was trusted at face value.

---

## 1. Current Docker/Deployment Architecture (Re-Verified)

**CONFIRMED FROM CURRENT CODE, re-read in full this task.**

- Three Dockerfiles (`backend/Dockerfile`, `bff/Dockerfile`,
  `frontend/Dockerfile`) and two Compose files
  (`infrastructure/office/docker-compose.yml`,
  `infrastructure/tencent/docker-compose.yml`) exist — **unchanged in
  shape and content** from the prior audit; Phase A touched only
  `infrastructure/office/.env.example` (confirmed: `git diff --stat`
  from Phase A shows exactly `14 insertions(+)`, zero other lines).
- **No `infrastructure/development/` directory exists yet** — confirmed
  by directory listing (`infrastructure/` contains only `office/` and
  `tencent/`).
- **No `networks:`, `develop:`, `profiles:`, or `healthcheck:` block
  exists in either Compose file** — re-confirmed by direct grep this
  task, matching the prior audit exactly.
- **`frontend/vite.config.ts` still has no `server.host` configuration**
  — re-read in full this task: `defineConfig({ plugins: [react()] })`,
  nothing else. The prior audit's finding on this point is **still
  true**, not stale.
- **`bff/package.json`'s `dev` script is still
  `tsx watch --env-file-if-exists=.env src/index.ts`**, and
  **`frontend/package.json`'s is still `vite`** — both re-confirmed
  unchanged.
- **`backend/config/settings.py`'s `DATABASES` block** (re-read in full
  this task, lines 117-133): reads `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`
  purely from `os.environ.get(...)`, with `postgresql` as the fixed
  engine — no hardcoded host, no SQLite fallback in `config.settings`
  itself (only `config.settings_test` overrides this, and only for the
  test suite). **No `STATIC_ROOT`, `MEDIA_ROOT`, or `MEDIA_URL` setting
  exists anywhere in `settings.py`** — grepped this task, zero matches.
  This project stores no media on the Django filesystem at all (WAHA
  owns `.sessions`/`.media`, a separate, already-provisioned volume pair
  in `infrastructure/tencent/docker-compose.yml`, untouched by this
  audit) — **static/media handling is a non-issue for backend Docker dev,
  not a gap to design around.**

---

## 2. Existing Dockerfiles and Their Suitability

**CONFIRMED FROM CURRENT CODE, re-read in full this task — identical to
the prior audit's findings, restated here because this task explicitly
requires re-verification, not reuse-on-trust:**

- **`backend/Dockerfile`**: single-stage `python:3.12-slim`, installs
  `libpq-dev`/`gcc`, `pip install -r requirements.txt`, `COPY . .`, `CMD
  gunicorn config.wsgi:application --bind 0.0.0.0:8000`. **Directly
  reusable for development, unmodified** — Django, all of
  `requirements.txt` (including `celery==5.4.0`, `redis==5.0.8`), and the
  full application source are already present in the built image; only
  the `command:` (not the image) needs to differ for `runserver` vs.
  `gunicorn`, and for `celery worker`/`celery beat` vs. either of those —
  **all four backend-side dev containers (Django, worker, beat, plus any
  one-off `manage.py` invocation) can share this exact same image.** No
  `Dockerfile.dev` is needed for the backend.
- **`bff/Dockerfile`**: two stages; the final (production) stage runs
  `npm install --omit=dev`, so `tsx` is **not installed** in it — the
  production image cannot run `npm run dev`. The **`build` stage**,
  however, already runs a full `npm install` (dependencies +
  devDependencies, `tsx` included) before its own `RUN npm run build`
  step — `docker build --target build` against this exact, unmodified
  file produces an image with everything `tsx watch` needs, without
  writing a new file. This is a genuine, real option (Section 13/22
  decides between this and a `Dockerfile.dev`).
- **`frontend/Dockerfile`**: two stages; the final stage is
  `nginx:1.27-alpine` with **no Node.js runtime at all** — structurally
  cannot run Vite in any form. Same "the `build` stage already has
  everything needed" option applies here too (Section 12/22).

---

## 3. Current Production Compose Architecture (Unchanged, Not Modified)

**CONFIRMED, re-read in full this task — byte-identical to the prior
audit's Section 5 table except for Phase A's one `.env.example` line,
which is outside either Compose file.** Restated briefly since Section
20 builds directly on it:

`infrastructure/office/docker-compose.yml`: `backend` (build:
`../../backend`, `8000:8000`, `depends_on: redis`), `celery-worker`
(same build, `command: celery -A config worker -l info`, no published
port), `celery-beat` (same build, `command: celery -A config beat -l
info`, no published port), `redis` (`redis:7-alpine`, no volume, no
published port). All three backend-image services share `env_file:
.env`.

`infrastructure/tencent/docker-compose.yml`: `frontend` (nginx,
`80:80`), `bff` (`8080:8080`, `env_file: .env`), `waha`
(`devlikeapro/waha:gows`, no published port, two named volumes).

**This report proposes zero changes to either file** — confirmed
out-of-scope per the task's own explicit constraint #6.

---

## 4. Recommended Development Compose Architecture

**PROPOSED DESIGN.** Mirrors the *existing, already-established*
location-based ownership pattern (`infrastructure/office/`,
`infrastructure/tencent/`) rather than either (a) one flat file
combining everything, or (b) one directory per component
(`backend/docker-compose.yml`, etc. — explicitly rejected, Section 5).

**Two Compose files, one new directory, not one and not three**:

```
infrastructure/development/
├── office.yml       # backend, celery-worker, celery-beat, redis
├── tencent.yml       # frontend, bff (waha stays external — Section 11)
└── .env.example       # one shared file — Section 17
```

**Why two files, not one combined file**: the task explicitly asks not
to *assume* a single combined project, and the network/reachability
analysis in Section 14 finds a concrete, technical reason to keep them
separate — the browser reaches `frontend`/`bff` via published host ports
regardless of Compose-project membership (Section 14), so nothing about
browser-facing reachability requires combining the two; the **one** real
cross-boundary hop (BFF → Django) is solved without a shared network
(Section 14's `host.docker.internal` recommendation) — so there is no
technical requirement forcing a single project, only convenience, and
Section 14 shows that convenience is achievable without the fusion too
(`docker compose -f infrastructure/development/office.yml -f infrastructure/development/tencent.yml up`
brings up everything in one command when wanted, while still allowing
`-f office.yml up` alone for backend-only work).

**Why two files, not three (or more) per-component files**: **the same
architectural reasoning the prior audit already established for
staging/production applies here unchanged** — `docs/14-REPOSITORY-STRUCTURE.md`'s
"infrastructure = deployment" ownership statement doesn't stop applying
just because the environment is "development" rather than "production";
a `backend/docker-compose.yml`/`bff/docker-compose.yml`/`frontend/docker-compose.yml`
split would fragment "what runs together" across three directories for
development the same way it would for staging/production, for no new
benefit development specifically needs (developers do not, in this
project's actual usage pattern, mix-and-match backend/frontend/BFF
independently across unrelated combinations — Section 11's confirmed
production topology already groups them exactly as `office`/`tencent`
does).

---

## 5. Recommended Repository Location

Already answered by Section 4 — `infrastructure/development/`, **not**
`backend/docker-compose.yml`/`frontend/docker-compose.yml`/`bff/docker-compose.yml`
(explicitly ruled out per Section 4's reasoning) and **not**
`infrastructure/development/backend/`, `.../frontend/`, `.../bff/`
(the task's own named "unnecessarily fragmented" candidate — rejected
for the same reason: it re-introduces per-component ownership one level
deeper than the flat `office.yml`/`tencent.yml` split needs, without a
concrete justifying difference between this and every other environment
this repository already organizes by location).

---

## 6. Backend Container Design

**PROPOSED DESIGN**, built on Section 2's confirmed reusability:

- **Image**: the existing `backend/Dockerfile`, built exactly as-is —
  `docker compose build` against `context: ../../backend` (same relative
  path pattern `infrastructure/office/docker-compose.yml` already uses).
- **Command override**: `command: python manage.py runserver 0.0.0.0:8000`
  (binding `0.0.0.0`, not `127.0.0.1`, is required for the container's
  published port to actually reach the process inside it — a Docker
  networking fact, not a Django-specific one).
- **Bind mount**: `./backend:/app` (relative to `infrastructure/development/office.yml`'s
  own location, i.e. `../../backend:/app`, matching the existing
  `context: ../../backend` convention already used one directory over in
  `infrastructure/office/docker-compose.yml`). Overlays only the
  application source tree at `/app` — Python's installed packages live
  under the image's system site-packages path, **outside** `/app`, so
  the bind mount does not hide or interfere with the `pip install`
  layer already baked into the image.
- **`env_file`**: `infrastructure/development/.env.example` (copied to
  `.env` by the developer, same convention as both existing Compose
  files) — **not** `backend/.env`; Section 17 covers this in detail.
- **Migrations**: **not run automatically by this design** — a
  deliberate choice, not an oversight: `manage.py migrate` is a stateful,
  one-time-per-schema-change operation; auto-running it on every
  container start risks masking a forgotten/failed migration behind a
  container that "just works" anyway. **PROPOSED**: document
  `docker compose exec backend python manage.py migrate` as an explicit
  step in the startup workflow (Section 18), matching how `README.md`
  already documents it as a distinct step even in the bare-host
  workflow — not a new burden Docker introduces, just preserved.
- **Static/media**: confirmed non-issue (Section 1) — no configuration
  needed.
- **The Windows stale-multiple-`runserver`-process problem — structural
  fix, not a new mitigation layered on top**: `README.md`'s documented
  incident (an old, forgotten `runserver` process left running from an
  earlier terminal session silently keeps answering on port 8000 with
  stale config, because Windows doesn't always refuse a second process
  binding the same port) **cannot recur in this design as long as the
  developer only ever starts the backend via
  `docker compose up`/`down`**: Docker Engine's own port-publishing
  mechanism refuses to start a second container publishing an
  already-claimed host port — `docker compose up` fails fast with a
  clear "port is already allocated" error rather than silently
  succeeding, and `docker compose down`/`stop` deterministically
  terminates the exact container that's supposed to stop, visible in
  `docker compose ps`, unlike an orphaned background host process that
  has no single, obvious place to be listed. **This is a genuine
  structural improvement**, not merely a documented workaround — it is a
  direct consequence of using Docker's own container/port lifecycle
  instead of bare host processes, requiring no new tooling of this
  project's own to achieve.

---

## 7. Celery Worker Design

**PROPOSED DESIGN**: same image as `backend` (Section 6), same bind
mount, **same `env_file`**, `command: celery -A config worker -l info` —
**identical to production's own command**, unmodified, confirmed correct
per `config/celery.py`'s `app.autodiscover_tasks()` (task discovery is
Django-app-registry-based, not path-based, so it works identically
whether the container is running `runserver` or `gunicorn` alongside it —
no coupling between the worker's command and the web process's command).

**Requires `RECONCILIATION_EXECUTOR=celery`** in the development `.env`
(Section 17) for this container to actually be exercised at all by
Django's own request-handling path — without it, `trigger_reconciliation()`
runs in-process regardless of whether this container is running, exactly
as Phase A's own finding already established for production
(`apps/sync/executors.py`, re-confirmed unchanged this task).

---

## 8. Celery Beat Design

**PROPOSED DESIGN**: same image, same bind mount, same `env_file`,
`command: celery -A config beat -l info` — identical to production.
**This is the container that makes the periodic `reconcile-all-sessions`
task actually fire** (`config/celery.py`'s `add_periodic_task`,
`settings.RECONCILIATION_INTERVAL_SECONDS`-driven, re-confirmed
unchanged this task) — notably, **this periodic path requires no BFF and
no frontend at all** to exercise the Celery/Redis pipeline end-to-end;
only `backend` + `celery-worker` + `celery-beat` + `redis` are needed for
the task's own stated top priority ("development should be able to run
with `RECONCILIATION_EXECUTOR=celery`") to be **fully, independently
achievable** — a finding worth stating plainly since it means Section
4's `office.yml` alone, without `tencent.yml`, already delivers the
task's central goal.

---

## 9. Redis Design

**PROPOSED DESIGN**: `redis:7-alpine`, **unchanged from production** —
no new image, no new version. **No published port** (Section 8 of the
prior audit's reasoning applies identically in development: nothing in
this codebase connects to Redis directly outside a Django/Celery
process, and the not-yet-implemented Phase 9.1C health check, if it is
ever built, runs *inside* the Django container, never needing a
published port either). **No persistence volume** — matches production
exactly (an intentional parity choice, not an oversight: development
losing queued/in-flight task state on a `redis` container restart is an
acceptable, low-stakes characteristic to mirror faithfully, precisely
*because* it mirrors what production itself does today, per the prior
audit's Section 8/17 open item, still unresolved and not decided by this
Phase B audit either).

---

## 10. PostgreSQL Connectivity Design

**PostgreSQL remains fully external — never a development container**,
per hard rule #1, applying identically to every environment including
development (the task's own constraint #4/#9 and the original repo-wide
hard rule agree; no tension found).

**How the `backend`/`celery-worker`/`celery-beat` containers reach it**:
`DB_HOST` is read purely from the environment (Section 1) — the
container has no special knowledge of "where Postgres is." Two realistic
shapes, both already representable by the existing `DB_HOST` mechanism
with **no code or Dockerfile change**:

1. **A real, already-reachable PostgreSQL instance** (shared dev/staging
   database, or a remote host) — `DB_HOST` is that instance's real
   hostname/IP, identical in shape to how `infrastructure/office/.env.example`
   already documents it for production.
2. **A PostgreSQL instance running directly on the developer's own host
   machine, outside any container** (a common local-development pattern,
   and consistent with how this project's `README.md` already documents
   bare-host development today) — reachable from inside the `backend`
   container via **`host.docker.internal`** as `DB_HOST`, a Docker
   Desktop-provided DNS name that resolves to the host machine.
   **CONFIRMED environment detail**: this session's own environment
   reports `Platform: win32`, meaning Docker Desktop for Windows is the
   applicable case, where `host.docker.internal` is supported
   out-of-the-box with no extra Compose configuration.
   **INFERRED, not confirmed from this repository**: on native Linux
   Docker Engine (no Docker Desktop), `host.docker.internal` requires an
   explicit `extra_hosts: ["host.docker.internal:host-gateway"]` entry
   (a standard, well-documented Compose feature, not a novel one) — this
   audit cannot verify which host OS any given future developer will use,
   so this is named as an environment-dependent detail, not asserted as
   universally automatic.

**This is not a new mechanism invented for this report** — it is the
same "always reach anything outside this specific Compose project via an
explicit, real host/URL, never assume a shared Docker network" principle
already governing how production's BFF reaches Django (NetBird/LAN,
Section 14 restates this once and applies it consistently to every
external dependency: PostgreSQL here, WAHA in Section 11, BFF→Django in
Section 14).

---

## 11. WAHA Connectivity Design

**WAHA remains fully external to Phase B's development Compose files —
not included in either `office.yml` or `tencent.yml`.** Reasoning:

- The task's own "Development target topology" section does not list
  WAHA among the four required backend containers, and Section 8 already
  established that the task's central goal (real Celery/Redis
  reconciliation) requires no WAHA connectivity at the periodic-task
  level at all (the periodic task calls `reconcile_session()`, which
  does call WAHA's REST API — but that's an *external HTTP call*, not a
  Docker-network dependency; `WAHA_BASE_URL`/`WAHA_API_KEY` work exactly
  like `DB_HOST` above, pointing at a real, already-running WAHA
  instance's URL, wherever it is).
  the outbound reconciliation and webhook paths do reach out to a real
  WAHA over plain HTTP(S) using whatever `WAHA_BASE_URL` is configured —
  not a Docker Compose concern either way.
- WAHA's **canonical service definition already lives in**
  `infrastructure/tencent/docker-compose.yml` (image, volumes,
  no-published-port convention) — duplicating that definition into a
  new development file would create two sources of truth for the exact
  same service shape, a genuine maintenance cost with no offsetting
  benefit given WAHA's connectivity is already env-var-driven, not
  Docker-network-driven, from Django/BFF's perspective either way.
- **If a developer wants a local, disposable WAHA instance for
  integration work**: they can already run
  `infrastructure/tencent/docker-compose.yml`'s `waha` service standalone
  (`docker compose -f infrastructure/tencent/docker-compose.yml up waha`)
  — no new file needed for this, and outside this report's scope to
  design further (WAHA/session logic is explicitly off-limits per the
  task's constraint #5).

---

## 12. Frontend/Vite Development Design

**PROPOSED DESIGN, built on Section 1's re-confirmed `vite.config.ts`
gap and Section 2's Dockerfile findings:**

- **Should Vite run inside the container?** Yes, for parity with the
  rest of this design (source bind-mounted, dev server inside the
  container, matching the backend/BFF pattern) — the alternative (Vite
  running on the bare host while everything else runs in Docker) is
  achievable too (Vite's dev server would just proxy/fetch a
  Docker-published BFF/Django port exactly as it does in today's fully
  bare-host setup) and is **not wrong**, but is inconsistent with this
  task's own stated goal of moving the workflow *into* Docker — this
  audit recommends the in-container form as the primary design, while
  noting the bare-host alternative remains fully compatible with
  everything else in this report and requires zero Docker work at all if
  ever preferred.
- **Required `host` configuration — CONFIRMED, re-verified this task
  (Section 1)**: `vite.config.ts` still has no `server.host` set. Vite's
  dev server binds to `localhost` by default, which is **not reachable
  from outside the container** even with a published port. **This one
  file needs `server: { host: true }`** (or `--host` on the CLI) for
  Docker dev to work at all — the single unavoidable application-source
  change this entire Phase B design requires, matching the prior audit's
  own finding, still true, not yet made (out of scope for this
  read-only audit; named here as a Phase B implementation prerequisite,
  Section 23).
- **Port mapping**: `5173:5173` (Vite's own default dev port,
  unchanged), published on the `tencent.yml` file's `frontend` service
  override.
- **Bind mount**: `../../frontend:/app`, matching the backend pattern
  (Section 6).
- **`node_modules` handling**: **PROPOSED — use an anonymous/named Docker
  volume for `/app/node_modules`, layered over the source bind mount**
  (a standard, widely-documented Compose pattern: `volumes: [
  "../../frontend:/app", "/app/node_modules" ]`) — without this, the host
  bind mount would shadow the image's already-`npm install`-ed
  `node_modules` with whatever (likely absent, or host-OS-mismatched
  native-binary) `node_modules` exists on the host filesystem. This is a
  well-known, standard Compose idiom, not a new mechanism invented for
  this report.
- **Should `npm install` happen at image build or container startup?**
  **PROPOSED: at image build** (via the `build` stage already present in
  the existing `frontend/Dockerfile`, Section 2), **not** at container
  startup — an `npm install` on every `docker compose up` would be
  slow and would fight with the `node_modules` volume strategy above
  (the volume should be *seeded* by the image's own build-time install,
  then persisted/reused across restarts — re-running `npm install` at
  startup is only needed after a genuine `package.json` change, at which
  point rebuilding the image is the correct trigger, not a startup
  script).
- **Environment variables**: `VITE_`-prefixed vars (Section 1's
  confirmed `frontend/.env.example` convention) — Vite reads these at
  **build/dev-server-start** time via its own `.env` loading, not via
  Compose `environment:`/`env_file:` injection into the running Node
  process the way Django/BFF consume theirs — **PROPOSED**: still supply
  via Compose `env_file:` pointing at a `frontend`-scoped `.env` (Vite's
  own dotenv loading picks up a `.env` file present in its working
  directory the same way it already does today on bare host, so a bind
  mount that includes a developer-created `frontend/.env` — already
  git-ignored, Section 16 of the prior audit — continues to work
  unmodified inside the container).

---

## 13. BFF/tsx Development Design

**PROPOSED DESIGN:**

- **Can `tsx watch` be used?** Yes — `bff/package.json`'s existing `dev`
  script (`tsx watch --env-file-if-exists=.env src/index.ts`, re-confirmed
  unchanged, Section 1) works unmodified inside a container, given an
  image that actually has `tsx` installed (Section 2 — the existing
  `build` stage already does, via `--target build`; a `Dockerfile.dev`
  is the alternative, same undecided choice as the prior audit,
  Section 22).
- **Bind mount**: `../../bff:/app`, with the same `node_modules`
  anonymous-volume pattern as Section 12 (`/app/node_modules`) — same
  reasoning: the image's own `build`-stage `npm install` already seeded
  real, correctly-installed dependencies; a bind mount alone would
  shadow them.
- **`node_modules` handling / install timing**: same as Section 12 — at
  image build (via the existing `build` stage), not container startup.
- **`.env` handling**: **the existing `--env-file-if-exists=.env` flag
  already works correctly inside a container, unmodified** — it's a
  plain Node.js CLI flag (`tsx`/Node's own `--env-file-if-exists`) that
  reads a file relative to the process's working directory; a bind-mounted
  or Compose-`env_file:`-populated `.env` at `/app/.env` (or real
  environment variables injected by Compose's own `environment:`/`env_file:`,
  which — like Django's `config/env.py`, Section 1 of the prior
  audit — always wins if already set) satisfies this identically to
  running on bare host. **No change needed to this flag or script.**
- **Port mapping**: `8080:8080` (unchanged from production).
- **How BFF reaches Django, and via what transport**: this is Section
  14's central question — answered there once, not duplicated here.

---

## 14. Docker Networking Design

**PROPOSED DESIGN — the report's most architecturally consequential
section**, directly answering the task's explicit instruction not to
assume `office.yml`/`tencent.yml` share a Compose project.

**Within each file**: Compose's own default per-project bridge network
(unchanged pattern from both existing production files, Section 3) —
`backend`/`celery-worker`/`celery-beat`/`redis` in `office.yml` resolve
each other by bare service name (`redis`, exactly as production already
does); `frontend`/`bff` in `tencent.yml` resolve each other the same way
if ever needed (today, `frontend` doesn't call `bff` over the Docker
network at all — Section 6 of the prior audit already established that
frontend's own calls happen from the **browser**, which is outside
Docker networking entirely, Section 6 restated below).

**The browser's own requests (frontend → BFF, frontend → Django) are
unaffected by Compose-project membership, in every case**: `VITE_BFF_BASE_URL`/`VITE_DJANGO_BASE_URL`
are consumed by code running in the developer's actual browser, which
only ever sees **published host ports** (`localhost:8080`,
`localhost:8000`) — never a Docker-network hostname, whether `frontend`
and `backend` live in the same Compose project or not. **This is the key
fact that makes keeping `office.yml`/`tencent.yml` separate
technically painless**: nothing about the browser-facing half of this
architecture depends on shared Compose-project membership at all.

**The one real cross-project hop: BFF → Django** (`DJANGO_INTERNAL_BASE_URL`,
Section 3 of the prior audit). Two options, evaluated on their technical
merits rather than assumed:

1. **A shared external Docker network** (`docker network create
   wamora-dev`, then both `office.yml` and `tencent.yml` attach to it via
   `networks: { wamora-dev: { external: true } }`) — a standard,
   well-documented Compose pattern for cross-project communication, not
   invented for this report. Lets BFF reach Django via a bare service
   name (`http://backend:8000`) across the project boundary. Requires
   one extra manual setup step (`docker network create`, Section 18) not
   otherwise needed.
2. **`http://host.docker.internal:8000`** (or, on native Linux Docker
   Engine without Docker Desktop, requiring an explicit
   `extra_hosts: ["host.docker.internal:host-gateway"]` entry on the
   `bff` service — Section 10's same OS-dependent caveat applies here
   identically) — BFF reaches Django via the **published host port**,
   the exact same mechanism the browser itself uses, requiring zero
   shared-network setup at all.

**Recommendation, derived from the existing architecture rather than
either option's raw convenience**: **option 2**. It requires no new
Docker networking primitive to learn/operate, and — more importantly —
it **preserves this project's own consistent architectural principle,
observed in every environment so far**: BFF always reaches Django via an
explicit, real reachable URL (`DJANGO_INTERNAL_BASE_URL`), never via an
assumed shared Docker network — true in production (NetBird/LAN,
Section 3), and, with option 2, **also true in development**, correcting
a real gap in the *prior* audit's own Section 11 (which had assumed
BFF and backend would share one Compose project and communicate via bare
Docker DNS — a same-network shortcut this Phase B audit, on closer
inspection, does not recommend taking, precisely because it would be the
*one* environment where BFF↔Django stops being "reach via an explicit
URL" and becomes "assume shared network," a real, nameable
production-parity difference the earlier report itself flagged as a risk
in its own Section 17 without fully resolving it). Choosing option 2
here removes that specific parity gap rather than merely naming it.

---

## 15. Volume/Bind-Mount Design

**PROPOSED DESIGN, consolidating Sections 6/12/13:**

| Service | Bind mount | Additional volume |
|---|---|---|
| `backend` | `../../backend:/app` | none needed (no `node_modules`-equivalent problem for Python — installed packages live outside `/app`, Section 6) |
| `celery-worker` | same as `backend` | none |
| `celery-beat` | same as `backend` | none |
| `redis` | none | none (Section 9 — no persistence, matching production) |
| `frontend` | `../../frontend:/app` | anonymous volume at `/app/node_modules` (Section 12) |
| `bff` | `../../bff:/app` | anonymous volume at `/app/node_modules` (Section 13) |

No volume in this design holds durable business data — PostgreSQL (external,
Section 10) and WAHA's own media/session volumes (external, owned by
`infrastructure/tencent/docker-compose.yml`, Section 11) remain the only
places anything durable lives, unchanged by this report.

---

## 16. Hot-Reload Strategy

**Per-component, re-derived from Sections 6/7/8/12/13 — restated once
here as the task's own Section 16 requires:**

| Component | Mechanism | New dependency needed? |
|---|---|---|
| Django | Built-in `runserver` `StatReloader` (stat-polling; no `watchdog` installed, confirmed absent from `requirements.txt` this task, same as the prior audit) | **No** — works out of the box |
| BFF | `tsx watch` (already the project's own script) | **No** |
| Frontend | Vite HMR (already the project's own script) | **No** — only the `server.host` config addition (Section 12), not a new dependency |
| Celery worker | **No built-in mechanism** (Celery 5 removed `--autoreload`, re-confirmed unchanged this task) | — |
| Celery beat | Same as worker | — |

**Celery worker/beat — explicitly not solved with `watchdog`/`watchmedo`
in this design, per the task's own instruction.** Documented here as a
**real, named limitation**, with the **safest workflow proposed instead
of a fragile auto-reload mechanism**:

- **Primary recommended workflow**: after editing any file that affects
  task behavior (in practice, almost exclusively `apps/sync/tasks.py` and
  whatever it imports — a small, stable module, not the whole
  `backend/` tree), the developer runs
  `docker compose restart celery-worker celery-beat`. This is a manual
  step, not automatic — stated plainly as the limitation this section
  exists to document, not hidden behind a claim of full hot-reload parity
  with the other four components.
- **An optional, zero-new-dependency enhancement, not required for Phase
  B and not decided by this audit**: Docker Compose's own `develop.watch`
  (a `sync+restart` action targeting `celery-worker`/`celery-beat`'s bind
  mount) could automate the restart above **without adding any Python
  package** — purely a Compose-file feature. **Not proposed as part of
  this design's required scope**, since (a) it needs a Docker Compose CLI
  version this audit cannot confirm from the repository, and (b) the
  task's own goal (real Celery/Redis execution in development) is fully
  achieved by the manual-restart workflow above; `develop.watch` would
  only remove one manual step, not enable anything the manual workflow
  can't already do. Named here as a possible **future** refinement,
  explicitly not chosen now.
- **`watchdog`/`watchmedo` is not proposed anywhere in this design**, per
  the task's explicit instruction — not as a rejected option requiring a
  decision, simply omitted, since constraint #8 ("do not add dependencies
  unless the audit proves they are necessary") is not met: the manual-restart
  workflow above already satisfies the task's actual stated goal without
  any new dependency.

---

## 17. Environment-Variable Strategy

**PROPOSED DESIGN**, built directly on Section 1's re-confirmed
`config/env.py` behavior:

- **One shared `infrastructure/development/.env.example`** (not one per
  service) — mirrors both existing production Compose files' own
  single-`.env`-per-location convention (`infrastructure/office/.env.example`,
  `infrastructure/tencent/.env.example`) exactly; `office.yml`'s three
  backend-image services already share one `env_file:` today in
  production (Section 3), and this design preserves that.
  **PROPOSED, not yet decided (Section 22)**: whether `office.yml` and
  `tencent.yml` should each get their own `.env.example` (mirroring the
  production split, two files) or share one combined file (mirroring
  this design's own two-Compose-file-but-conceptually-one-environment
  framing) — a real, small open question, not resolved here.
- **Values that would differ from `infrastructure/office/.env.example`'s
  Phase-A-updated content**: `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`
  stay `redis://redis:6379/0` (bare service name, unchanged — Section 9's
  `redis` service is named identically); `RECONCILIATION_EXECUTOR=celery`
  (the task's own explicit requirement, and now consistent with Phase
  A's production fix rather than contradicting it — Section 20 discusses
  this parity point further); `DB_HOST` would be the developer's real
  reachable Postgres (Section 10) — **never guessed or hardcoded by this
  audit**, left as an empty template field exactly like every existing
  `.env.example`'s `DB_HOST=` already is; `DJANGO_ALLOWED_HOSTS` and
  `CORS_ALLOWED_ORIGINS` would need real values for the published
  ports/origins in play (`localhost:8000`, `localhost:5173`) — **this
  audit does not invent these values**, since both fields fail closed by
  design (Section 7 of the prior audit) and must be filled deliberately
  by whoever writes the real `.env`, not defaulted to something
  permissive in a checked-in template.
- **`config/env.py`'s `load_env_file` remains a no-op inside any
  container** (Section 1, re-confirmed) — `backend/.dockerignore`
  excludes `.env` from the image, and the bind mount (Section 6) does
  not change this, since a developer's real `backend/.env` (if one
  exists on the host for bare-host work) is a **different file** from
  `infrastructure/development/.env`, consumed via Compose's own
  `env_file:` mechanism directly into the container process's
  environment — exactly like both existing production Compose files
  already do, not a new mechanism.

---

## 18. Development Startup Workflow

**PROPOSED DESIGN**, not yet implemented (Section 23 sequences the actual
file creation):

1. `docker network create wamora-dev` — **only if Section 14's option 1
   is chosen instead of the recommended option 2**; **not needed** under
   this report's actual recommendation (`host.docker.internal`).
2. `cd infrastructure/development && cp .env.example .env` — fill in
   `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` (Section 10),
   `WAHA_BASE_URL`/`WAHA_API_KEY` (Section 11), JWT keys, `DJANGO_ALLOWED_HOSTS`,
   `CORS_ALLOWED_ORIGINS` (Section 17) — same "copy and fill in real
   values" pattern `README.md` already documents for both existing
   production stacks.
3. `docker compose -f office.yml up --build` — backend, Celery
   worker/beat, Redis. Add `-f tencent.yml` in the same command (or run
   it separately, in a second terminal) for frontend/BFF too — both are
   valid, matching Section 4's "independently startable" design goal.
4. **One-time, or after a schema change**: `docker compose -f office.yml
   exec backend python manage.py migrate` (Section 6 — deliberately not
   automatic).
5. Edit source under `backend/`, `frontend/`, or `bff/` on the host —
   Django/BFF/Vite reload automatically (Section 16); Celery
   worker/beat require the manual restart step named in Section 16 if
   task-affecting code changed.

---

## 19. Development Shutdown Workflow

**PROPOSED DESIGN**:

- `docker compose -f office.yml -f tencent.yml down` — stops and removes
  every container cleanly (contrast with the bare-host workflow's
  documented Windows failure mode, Section 6, where a forgotten
  `runserver` process could keep running invisibly).
- `redis`'s in-memory state is discarded on `down` (Section 9 — no
  volume, matching production) — expected, not a data-loss concern given
  nothing durable lives there.
- The `node_modules` anonymous volumes (Section 15) **persist across
  `down`/`up`** by default (Compose only removes anonymous volumes with
  an explicit `-v` flag) — intentional, avoids re-running `npm install`
  on every restart; `docker compose down -v` (or rebuilding the image) is
  the explicit, deliberate way to reset them if ever needed (e.g. after a
  suspected `node_modules` corruption), not a routine step.

---

## 20. Production/Staging Separation Strategy

**PROPOSED DESIGN — directly extends the prior audit's own Section
15/18 recommendation ("Option E first, Option B as the eventual shape"),
now made concrete for Phase B specifically:**

- **This design does not share files with `infrastructure/office/docker-compose.yml`
  or `infrastructure/tencent/docker-compose.yml`** — `office.yml`/`tencent.yml`
  under `infrastructure/development/` are wholly new, self-contained
  files (Section 4), touching neither existing production file, matching
  the task's own constraint #6 and the prior audit's "lowest-disruption
  first" recommendation exactly.
- **What *can* be extracted later, once staging is actually being built
  (not now)**: the **service list/shape** (which services exist, what
  they're named, how they reach Redis/each other) is already
  **identical** between this development design and production for the
  `office.yml` side (`backend`, `celery-worker`, `celery-beat`, `redis`,
  same names, same `redis://redis:6379/0` pattern) — only `command:`
  (`runserver` vs. `gunicorn`), the presence of a bind mount, and
  `env_file:` contents actually differ. This is precisely the shape a
  future `base.yml` (prior audit's Option B) could factor out, with
  `development.yml`/`staging.yml`/`production.yml` each layering only
  their own `command:`/volume/`env_file:` differences on top — **not
  performed now**, named here only to confirm this design doesn't
  foreclose that later refactor; if anything, building `office.yml` with
  a service list intentionally identical to production's (which this
  design already does, Sections 6-9) makes that future extraction
  **easier**, not harder.
- **`RECONCILIATION_EXECUTOR` parity, directly connecting Phase A to
  Phase B**: with Phase A's fix already in place
  (`infrastructure/office/.env.example` now says `celery`) and this
  Phase B design also proposing `celery` for development (Section 17),
  **both environments now agree on this axis** — resolving the exact
  "development becomes more production-like than production itself"
  risk the prior audit's Section 17 named as a live concern before Phase
  A existed. Staging, whenever it's built, would naturally inherit
  `celery` too, having nothing left to reconcile on this specific point.

---

## 21. Risks and Trade-Offs

- **`host.docker.internal` portability** (Section 10/14): the
  recommended cross-boundary mechanism (BFF→Django, backend→host
  Postgres) works natively on Docker Desktop (confirmed applicable to
  this session's own `win32` environment) but needs an explicit
  `extra_hosts` entry on native Linux Docker Engine — a real, named
  portability caveat, not silently glossed over, affecting any developer
  who later works from a native-Linux Docker host.
- **Manual Celery worker/beat restart** (Section 16): the one component
  in this design without automatic hot-reload — a real, accepted
  limitation, not a defect; the task explicitly asked for this to be
  named rather than papered over with a new dependency.
  `docker compose restart celery-worker celery-beat` (or, later,
  `develop.watch`) are the mitigation.
  `node_modules` anonymous-volume staleness (Section 15/19): if a
  `package.json` change isn't accompanied by an image rebuild, the
  running container's `node_modules` volume can silently drift from what
  `package-lock.json` now specifies — mitigated by the startup workflow
  explicitly calling for a rebuild after dependency changes (Section 18),
  not by any automatic detection this design adds.
- **Two separate `.env.example` files vs. one, still open** (Section 17)
  — a small, low-stakes decision left to Section 22 rather than assumed.
- **This design intentionally leaves WAHA/PostgreSQL fully external**
  (Sections 10/11) — a benefit for scope discipline (matches the task's
  own constraints #4/#5) but means a developer's very first `docker
  compose up` still requires *something* real and reachable for both,
  exactly as the bare-host workflow already requires today — **not a new
  burden Docker introduces**, simply not eliminated by it either.

---

## 22. USER DECISIONS REQUIRED

1. **`office.yml`/`tencent.yml`-shared vs. per-location `.env.example`**
   (Section 17). **Options**: one combined `infrastructure/development/.env.example`
   (simpler, one file to fill in) vs. two, mirroring production's own
   per-location split exactly (`office.env.example`/`tencent.env.example`).
   **Consequence**: one combined file means `tencent.yml`'s services
   would read some variables they don't use (harmless, just noise); two
   files means slightly more setup steps but a closer mirror of
   production's own convention. **No strong pull either way from
   existing architecture** — genuinely open.
2. **Cross-boundary networking: `host.docker.internal` (this report's
   recommendation, Section 14) vs. a shared external Docker network.**
   **Consequence**: the recommendation needs no extra setup command and
   preserves this project's "always an explicit URL, never an assumed
   shared network" principle even in development; the external-network
   alternative is more "native-Docker-feeling" (bare service names) at
   the cost of one extra setup step and a real, if small, departure from
   that principle.
3. **BFF/frontend dev image: separate `Dockerfile.dev` vs. `--target
   build` against the existing multi-stage Dockerfile** (Section 2/12/13
   — restated from the prior audit, still genuinely undecided, no new
   evidence this task tips it either way).
4. **Whether to build `tencent.yml` (frontend/BFF dev containers) in the
   same implementation pass as `office.yml`, or defer it** — Section 8
   already establishes that `office.yml` alone fully satisfies the
   task's stated top priority (real Celery/Redis execution); `tencent.yml`
   is valuable but independently justified, not a blocking dependency.
5. **`develop.watch` for Celery worker/beat** (Section 16) — explicitly
   not proposed as required, but worth a deliberate yes/no rather than
   silent omission, once the operator's Compose CLI version is known.
6. **Carried forward, unaffected by this audit**: the prior report's
   still-open staging-topology and Redis-persistence questions (Sections
   12/8 of `DOCKER-ENVIRONMENT-ARCHITECTURE-AUDIT-REPORT.md`) — this
   Phase B design does not resolve either, since neither is in scope for
   a development-only environment.

---

## 23. Dependency-Ordered Implementation Plan for Phase B

**Not implemented by this audit — sequencing only, for whenever Phase B
is approved:**

1. **`frontend/vite.config.ts`: add `server: { host: true }`** (Section
   12) — the one unavoidable application-source change, and a
   prerequisite for step 4 below regardless of which other decisions are
   made. Independent of every other step; could be done standalone even
   before the rest of Phase B is approved.
2. **`infrastructure/development/office.yml` + `.env.example`** — backend,
   celery-worker, celery-beat, redis (Sections 6-9, 15, 17). Delivers the
   task's stated top priority on its own (Section 8). No dependency on
   steps 3-4.
3. **`infrastructure/development/tencent.yml`** — frontend, BFF (Sections
   12-14), depending on step 1 for frontend to actually work, and on
   Section 22 item 3's Dockerfile-vs-`--target` decision. Independent of
   step 2 in principle, though most naturally built after it given step
   2 delivers the task's core goal first.
4. **Documentation**: a startup/shutdown workflow write-up (Sections
   18-19) alongside whichever files land, plus an implementation report
   mirroring `PHASE-A-RECONCILIATION-EXECUTOR-IMPLEMENTATION-REPORT.md`'s
   own format (problem found, files changed, verification, files
   intentionally not touched).

---

## Summary

Re-verified directly against current source (not assumed from the prior
audit): `vite.config.ts` still lacks `server.host`; all three Dockerfiles
and both production Compose files are unchanged except for Phase A's one
already-completed `.env.example` line; no development Docker environment
exists yet. **The backend's existing Dockerfile is fully reusable for
Django, Celery worker, and Celery beat with no `Dockerfile.dev` needed** —
only a `command:` override and a source bind mount, both zero-new-dependency.
**The task's central goal — real `RECONCILIATION_EXECUTOR=celery` in
development — is fully achievable with backend + celery-worker +
celery-beat + redis alone**, requiring no frontend or BFF involvement at
all for the periodic reconciliation path. Recommended structure:
`infrastructure/development/office.yml` + `tencent.yml`, mirroring the
repository's own existing location-based ownership convention rather than
either a single combined file or a per-component fragmentation this
audit explicitly evaluated and rejected on the same grounds the prior
audit already established for staging/production. The one real
cross-boundary networking question (BFF → Django) is resolved via
`host.docker.internal` rather than a shared Compose network, which — a
genuine refinement over the prior audit's own earlier assumption —
preserves this project's consistent "always an explicit URL, never an
assumed shared network" principle in every environment, not just
production. Celery worker/beat hot-reload has **no automatic solution
proposed**, per explicit instruction not to introduce `watchdog`/`watchmedo`
— the documented, safe workflow is a manual `docker compose restart`
after task-affecting source changes. **No source code, Dockerfile,
Compose file, `.env`, database, or deployment configuration was modified
producing this report, and no container was started.** Six items are
listed under Section 22 as requiring your decision before implementation.
