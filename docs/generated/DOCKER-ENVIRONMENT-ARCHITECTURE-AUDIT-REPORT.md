# Docker Environment Architecture Audit & Migration Plan (Read-Only)

**Scope.** Audit + design/plan only. No source code, Dockerfile, compose
file, `.env`, database, or WAHA state was modified. No deployment was run
and no live test that changes state was performed. Every claim below is
tagged **CONFIRMED FROM CURRENT CODE**, **INFERRED FROM CURRENT
ARCHITECTURE**, or **PROPOSED DESIGN** — nothing is stated as fact unless
directly read from source this task. A separate `.kilo/worktrees/pinnate-bag/`
directory exists in the repo root, mirroring `backend/`, `bff/`,
`frontend/`, and `infrastructure/` — this is a tool-managed git worktree,
not a second deployment target; it was not audited and is not referenced
further below (see Section 11 for its one relevant implication).

---

## 1. Executive Summary

Wamora's Docker footprint today is **exactly two production-shaped
Compose files, one per physical deployment location** (`infrastructure/tencent/`,
`infrastructure/office/`), each building the same single-stage/production
Dockerfile every component already has. **There is no development Docker
environment anywhere in this repository today** — confirmed directly from
`README.md`'s own "Local development" section, which runs Django, the
BFF, and the frontend as bare host processes (`manage.py runserver`,
`npm run dev`, `npm run dev`) and states outright that `RECONCILIATION_EXECUTOR=celery`
"is unit-tested with Celery's eager mode — no real Celery worker/Redis
runs in this project's current manual dev environment." The two existing
Compose files are only ever used in their documented "Full Tencent/Office
stack (Docker)" sections, both of which build the production image and
run it as-is — there is no staging concept, no dev-oriented Dockerfile,
and no hot-reload mechanism configured anywhere.

**One concrete, previously-latent discrepancy surfaced by this audit**:
`backend/.env.example` sets `RECONCILIATION_EXECUTOR=sync` with a comment
explicitly framing that as the local-dev value, while
`infrastructure/office/.env.example` — the template an operator actually
copies for the **Office/production** Docker deployment, which *does*
provision a real `celery-worker`/`celery-beat`/`redis` — **does not set
`RECONCILIATION_EXECUTOR` at all**. Since Django's own default (`settings.py:225`)
is `'sync'`, an operator who follows `infrastructure/office/.env.example`
literally and never adds this one line ends up running the production
Office deployment's targeted-reconciliation trigger path in-process
(`sync`), never touching the Celery/Redis infrastructure that same
deployment stands up right beside it. This is a source-confirmed gap, not
a speculation, and it directly explains why every prior Phase 9 report in
this project has carried "confirm `RECONCILIATION_EXECUTOR`'s real
production value" as an unresolved open item — the template itself never
asks for it.

The user's proposed per-component `docker/` + `compose/` structure is
**partially a good fit and partially in tension with an existing,
explicit repository decision** (`docs/14-REPOSITORY-STRUCTURE.md`:
"infrastructure = deployment... A task scoped to one component should not
modify another"). Section 15 works through this in detail; the summary
recommendation is: per-component `Dockerfile`/`Dockerfile.dev` (or a
multi-stage `target:` inside the existing Dockerfile) is a good fit, but
per-component `compose/{base,staging,production}.yml` directories fragment
a location-based deployment-ownership model this repository has already
settled on. A location-scoped (`infrastructure/office/`, `infrastructure/tencent/`,
plus a new `infrastructure/development/`) base+override structure fits
the existing repository better.

---

## 2. Current Docker Architecture

**CONFIRMED FROM CURRENT CODE.** Three Dockerfiles, two Compose files,
zero dev-oriented Docker artifacts:

```
backend/Dockerfile              — single-stage, python:3.12-slim, gunicorn CMD
bff/Dockerfile                  — two-stage (build, then production), tsx/vite NOT in final stage
frontend/Dockerfile             — two-stage (build, then nginx), no dev-server capability at all

infrastructure/office/docker-compose.yml    — backend, celery-worker, celery-beat, redis
infrastructure/tencent/docker-compose.yml   — frontend, bff, waha
```

No `docker-compose.override.yml`, no `docker-compose.dev.yml`, no
`Dockerfile.dev`, no `.dockerignore`-excluded dev config, and no
`develop:`/`profiles:` blocks in either existing Compose file — confirmed
by direct read of both files in full (Section 5).

---

## 3. Current Deployment Topology

**CONFIRMED FROM CURRENT CODE + `docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`**
(the two agree; no discrepancy found here):

```
Tencent VPS (Docker, infrastructure/tencent/)
  frontend (nginx, static build) → bff (Node/Express) → waha (devlikeapro/waha:gows)
                                        │
                                        │ NetBird / LAN (cross-host, NOT Docker network)
                                        ▼
Office Server (Docker, infrastructure/office/)
  backend (Django/gunicorn) → celery-worker / celery-beat → redis
                                        │
                                        │ TCP 5432
                                        ▼
                          Existing PostgreSQL (not a Docker service, ever)
```

`README.md`'s own architecture diagram and the two `.env.example`
comments (`bff/.env.example:23-26`: "reaches Django over NetBird/LAN, not
the Tencent Docker network") independently confirm this — **BFF → Django
is cross-host, cross-Compose-project, never a Docker-network hop today.**
This is architecturally significant for Section 11/17: any development
topology that puts BFF and Django in the *same* Compose project changes
that specific hop's transport from NetBird/LAN to a Docker bridge network
— a real, nameable production-parity difference, not a defect (Section 14).

---

## 4. Existing Dockerfiles

**CONFIRMED FROM CURRENT CODE.**

**`backend/Dockerfile`**: single stage, `python:3.12-slim`, installs
`libpq-dev`/`gcc` (for `psycopg2-binary`'s build), `pip install -r
requirements.txt`, `COPY . .`, `CMD gunicorn config.wsgi:application
--bind 0.0.0.0:8000`. **Not multi-stage** — build tooling (`gcc`) remains
in the final image (a minor image-bloat/attack-surface point, not flagged
as broken — this project's own hard rules don't require multi-stage for
Python images, and `psycopg2-binary` is specifically chosen over
`psycopg2` precisely to avoid needing a C toolchain at all at runtime, per
its package name — the `gcc`/`libpq-dev` install here is arguably
unnecessary if the binary wheel is used, but that's a pre-existing,
out-of-scope observation, not part of this audit's requested scope).
There is **no `manage.py collectstatic` step** and **no non-root
`USER`** — both pre-existing characteristics, neither part of Docker
*environment strategy* and not modified or further audited here.

**`bff/Dockerfile`**: two stages. Stage 1 (`build`) does a full `npm
install` (dependencies **and** devDependencies — `tsx`, `typescript`,
`vitest` all present here) then `npm run build` (→ `dist/`). Stage 2
(final) sets `NODE_ENV=production`, runs `npm install --omit=dev`
(devDependencies, including `tsx`, deliberately excluded), copies only
`dist/` from stage 1, `CMD node dist/index.js`. **The final production
image cannot run `npm run dev` (`tsx watch`) — `tsx` is not installed in
it.** The `build` stage, however, already has every dev dependency
installed and could be targeted directly (`docker build --target build`)
for a dev use case without needing a whole separate Dockerfile — noted
here as a real option, decided in Section 11.

**`frontend/Dockerfile`**: two stages. Stage 1 (`build`) does a full `npm
install` + `npm run build` (→ static `dist/`). Stage 2 is `nginx:1.27-alpine`
serving that static output — **no Node.js runtime at all in the final
image**, so it structurally cannot run `vite` (dev server or otherwise).
Same "the build stage already has everything a dev target would need"
observation as BFF applies here too.

**Is production Dockerfile "correct"?** For its stated purpose (build a
deployable image, run it standalone) — **yes**, all three are functional,
minimal, and multi-stage where multi-stage genuinely reduces final image
size (bff, frontend). **Is a `Dockerfile.dev` needed?** Backend: **not
strictly** — the existing single-stage image already contains Django,
gunicorn is just an unused-if-overridden entrypoint; a dev use only needs
a different `command:` plus a source bind mount (Section 11). BFF and
frontend: **effectively yes**, because their production final stage
genuinely lacks the dev tooling — either a `Dockerfile.dev` or a
multi-stage `target:` pointed at their existing `build` stage is required;
a bare `command:` override against the current final stage cannot work
for either (Section 11 decides between these two forms).

**Can staging reuse the production Dockerfile/image?** **Yes, and
should** — Section 12/14 elaborates; nothing about the three existing
Dockerfiles is dev-specific or environment-specific in a way that would
need a *third* Dockerfile variant for staging.

---

## 5. Existing Compose Files

**CONFIRMED FROM CURRENT CODE — full contents already reproduced in
Section 2's evidence; ownership mapped below:**

| Service | File | Image/Build | Ports published | `depends_on` | Notes |
|---|---|---|---|---|---|
| `backend` | `infrastructure/office/docker-compose.yml` | build: `../../backend` | `8000:8000` | `redis` | `env_file: .env` |
| `celery-worker` | same | build: `../../backend` | none | `redis` | `command: celery -A config worker -l info` |
| `celery-beat` | same | build: `../../backend` | none | `redis` | `command: celery -A config beat -l info` |
| `redis` | same | `redis:7-alpine` | none | — | no volume, no persistence flag, no healthcheck |
| `frontend` | `infrastructure/tencent/docker-compose.yml` | build: `../../frontend` | `80:80` | `bff` | nginx-served static build |
| `bff` | same | build: `../../bff` | `8080:8080` | `waha` | `env_file: .env` |
| `waha` | same | `devlikeapro/waha:gows` | **none published** | — | `env_file: .env`, two named volumes (`waha_sessions`, `waha_media`) |

**No `PostgreSQL` service exists in either file** (correctly — hard rule
#1). **No reverse proxy service exists in either file** — `frontend`'s
own Nginx stage is the only Nginx present, serving static files only, not
acting as a reverse proxy in front of `bff`. **No `networks:` block is
defined in either file** — both rely on Compose's implicit default bridge
network per project, meaning cross-service DNS (`redis`, `waha`, etc.)
already works today via Compose's built-in per-project network, with no
custom segmentation. **No `healthcheck:` block exists on any service in
either file**, including `redis` and `waha` — `depends_on` therefore only
waits for container *start*, not for the dependency to be *ready*
(Compose's default `depends_on` behavior without a `condition:`), a
pre-existing characteristic, not something this audit was asked to fix.

---

## 6. Network Analysis

**CONFIRMED FROM CURRENT CODE + docs, answering each sub-question
directly:**

- **Frontend requests: from the browser**, not server-side — the
  frontend is a static SPA served by Nginx; all its own API calls
  (`VITE_BFF_BASE_URL`, `VITE_DJANGO_BASE_URL`) happen from the user's
  browser, confirmed by `frontend/.env.example`'s `VITE_`-prefix
  convention (browser-bundle-exposed by Vite's own build-time
  substitution) and `docs/06-SECURITY.md`'s statement that these are "not
  a secret" precisely because they're client-visible URLs.
- **BFF → Django**: **NetBird/LAN, not Docker network**, confirmed
  Section 3 — `DJANGO_INTERNAL_BASE_URL` is a full URL (host/IP + port),
  not a bare Compose service name, in both `bff/.env.example` and
  `infrastructure/tencent/.env.example`.
- **Django → Redis**: **Docker network, same Compose project** —
  `CELERY_BROKER_URL=redis://redis:6379/0` uses the bare service name
  `redis`, which only resolves inside `infrastructure/office/docker-compose.yml`'s
  own project network. Confirmed working today for the real Office
  deployment per `README.md`'s Phase 5 status ("live-verified against
  real Redis + worker + beat containers").
- **PostgreSQL, external, reachable from the `backend`/`celery-worker`
  containers**: via `DB_HOST`/`DB_PORT` (a real host/IP, not a Compose
  service name) — **INFERRED**, not directly testable read-only, but
  structurally required by `backend/.env.example`'s plain host/port
  fields and the hard rule that no PostgreSQL container exists in this
  project at all.
- **WAHA**: lives in `infrastructure/tencent/docker-compose.yml`, **no
  published port** (comment: "reaches WAHA over the internal Docker
  network only") — reachable from `bff` via the bare service name `waha`
  (`bff/.env.example: WAHA_BASE_URL=http://waha:3000`), confirmed.

---

## 7. Environment Variable Analysis

**CONFIRMED FROM CURRENT CODE.** Full inventory across all five
`.env.example` files, grouped by the variables the task specifically
named:

| Variable | `backend/.env.example` | `infrastructure/office/.env.example` | `bff/.env.example` | `infrastructure/tencent/.env.example` |
|---|---|---|---|---|
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | `redis://redis:6379/0` | — | — |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/0` | `redis://redis:6379/0` | — | — |
| `RECONCILIATION_EXECUTOR` | `sync` (commented as dev default) | **absent** ⚠ | — | — |
| `DJANGO_INTERNAL_BASE_URL` | — | — | empty (must be filled) | empty (must be filled) |
| `INTERNAL_SERVICE_KEY` | empty | empty | empty | empty |
| `WAHA_BASE_URL` | empty | empty | `http://waha:3000` (Docker-network default) | — |
| `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` | all empty | all empty | — | — |
| `JWT_PRIVATE_KEY`(`_PATH`) | empty | empty | — | — |
| `JWT_PUBLIC_KEY`(`_PATH`) | empty | empty | empty | empty |
| `CORS_ALLOWED_ORIGINS` | empty (fails closed) | empty (fails closed) | — | — |

**⚠ Discrepancy already flagged in Section 1**: `RECONCILIATION_EXECUTOR`
is present with an explicit dev-oriented default in `backend/.env.example`,
but **absent** from `infrastructure/office/.env.example` — the one an
operator actually uses for the real Office Docker deployment that
provisions Celery/Redis. This is the single most concrete, actionable
finding in this section.

**Development-hostname-into-production risk (task's explicit concern)**:
today's `redis://redis:6379/0` and `http://waha:3000` defaults are
**Docker-service-name-shaped values that only resolve inside their own
Compose project's network** — they are not "dev-only" values that leak
into production by mistake; they're the *actual* production values too,
since Office/Tencent production **is** the Docker Compose deployment
(there's no separate bare-metal production host name to preserve). The
real risk this task is pointing at would only materialize if a
**third**, differently-shaped development Compose project reused the same
`redis`/`backend`/`waha` service names for *different* containers with
different data — Section 11/13 addresses this directly: a development
Compose project must not share a Docker network, volume namespace, or
`.env` file with the office/tencent production ones, precisely so a
literal `redis://redis:6379/0` always means "whichever `redis` container
is in *this* Compose project," never a cross-project leak.

---

## 8. Redis Analysis

**CONFIRMED FROM CURRENT CODE**, cross-referencing the already-completed
Phase 9.1C design audit (`docs/generated/PHASE9-1C-DESIGN-AUDIT-REPORT.md`
Section 2, re-confirmed here rather than assumed):

- **Who needs Redis**: only `celery-worker`/`celery-beat`/`backend`
  (as Celery client for `.delay()` when `RECONCILIATION_EXECUTOR=celery`) —
  confirmed no `CACHES` setting, no session backend, no other Redis role
  anywhere in `backend/`.
- **Broker only, or result backend too?** **Both** —
  `CELERY_RESULT_BACKEND` is set to the same Redis URL as the broker
  (`settings.py:180`); Celery task results are stored in the same Redis
  instance, not a separate one.
- **Persistence**: `redis:7-alpine` is used with **no volume mount and no
  `--appendonly`/RDB-tuning flags** in `infrastructure/office/docker-compose.yml` —
  confirmed by direct read (Section 5). Today, a Redis container restart
  loses all queued/in-flight task state and any stored task results. This
  is acceptable *by default* for this project's actual usage (a
  periodic-reconciliation trigger and a handful of short-lived targeted
  tasks — nothing here is durable business data; `SyncCheckpoint`, the
  durable record of reconciliation progress, lives in PostgreSQL, not
  Redis), but it is a **PROPOSED DESIGN** open question, not a confirmed
  decision, whether staging/production should add persistence — Section 21.
- **Healthcheck**: **none configured today** (Section 5) — a
  `depends_on: redis` without a `condition: service_healthy` only waits
  for the container process to start, not for Redis to actually accept
  connections; in practice this has apparently not caused problems
  (`README.md`: "live-verified against real Redis + worker + beat
  containers"), likely because Redis starts near-instantly relative to
  Django/Celery's own startup time — not a change this audit proposes
  making now, but relevant if migration Phase E/F (Section 18) touches
  this file at all.
- **Exposed port**: **not exposed today**, in either direction — no
  `ports:` entry on the `redis` service. **PROPOSED DESIGN
  recommendation** (not a current fact): keep it that way in every
  environment, including development — Redis needs no host-machine access
  for this project's usage (no developer tooling in this repo connects to
  Redis directly outside a Django/Celery process; Section 2 of the 9.1C
  audit already confirmed no direct `redis-py` usage exists anywhere in
  application code today, and the proposed 9.1C health check runs
  *inside* the Django container, so it never needs a published port
  either). If a developer ever wants `redis-cli` access for debugging,
  `docker compose exec redis redis-cli` needs no published port at all.
- **Internal-network-only**: **PROPOSED DESIGN, strongly recommended,
  consistent with existing precedent** — `docs/06-SECURITY.md`'s stated
  principle for WAHA ("should not be unnecessarily public... over Docker
  network") applies with equal or greater force to Redis, which has **no
  authentication configured at all** today (`redis://redis:6379/0`, no
  password) — confirmed by the URL's own shape across every `.env.example`
  file. This audit does not propose adding Redis auth (out of scope,
  no task instruction requested it), only flags that its complete absence
  makes "never publish the port" a harder requirement, not an optional
  one, for any environment.

---

## 9. Celery Analysis

**CONFIRMED FROM CURRENT CODE:**

- **Worker command** (`infrastructure/office/docker-compose.yml`):
  `celery -A config worker -l info` — no concurrency flag (Celery's own
  default: one process per CPU core detected inside the container), no
  `--autoreload` (removed from Celery entirely since Celery 5 — **not
  available to add back as a flag**, confirmed absence of any such option
  in `celery==5.4.0`'s command surface by the project's own pinned
  version).
- **Beat command**: `celery -A config beat -l info` — uses Celery's
  default `PersistentScheduler`, which persists its own last-run
  bookkeeping to a local `celerybeat-schedule` file inside the container
  filesystem (not mounted to a volume in the current compose file) —
  ephemeral across container recreation, though this only affects beat's
  own internal "did I already fire this tick" bookkeeping, not
  `SyncCheckpoint` (a separate, PostgreSQL-backed model, unaffected).
- **App/broker/result backend/task discovery**: `config/celery.py` —
  `app.autodiscover_tasks()` (standard Django app-registry-based
  discovery, finds `apps/sync/tasks.py`'s `@shared_task`-decorated
  functions automatically; no manual task list to keep in sync).
  Periodic schedule (`reconcile-all-sessions`) is registered in Python
  code via `sender.add_periodic_task(...)`, reading
  `settings.RECONCILIATION_INTERVAL_SECONDS` — **no `django-celery-beat`
  dependency** (confirmed absent from `requirements.txt`), so there is no
  database-backed/dynamically-editable schedule; changing the interval
  requires an env var change + beat restart, not a runtime API call.
- **Reconciliation executor**: `RECONCILIATION_EXECUTOR` (`sync`/`celery`)
  — already fully covered in Section 7/1.

**Development hot-reload for the worker — the task's specific ask.**
**No built-in Celery mechanism exists** (autoreload removed). Two real
options, **neither implemented, both requiring a decision**:

1. **PROPOSED DESIGN — Docker Compose `develop.watch`** (Compose Spec,
   Docker Compose CLI v2.22+): a `sync+restart` action on the
   `celery-worker`/`celery-beat` services' own source paths, restarting
   just those containers when their bind-mounted source changes. **Adds
   no new Python dependency** — this is infrastructure/tooling-level, not
   a package installed into the image. **Requires a Docker Compose CLI
   version this audit cannot confirm from the repository alone** (no
   `.tool-versions`/CI pin found specifying a minimum Compose version) —
   flagged as an assumption to verify, not a fact.
2. **PROPOSED DESIGN — `watchdog` + `watchmedo auto-restart`**: wrap the
   worker/beat command (`watchmedo auto-restart --directory=./ --pattern=*.py
   --recursive -- celery -A config worker -l info`). **Requires adding
   `watchdog` as a new pip dependency** — per the task's own instruction,
   this is flagged as **USER DECISION REQUIRED** (Section 21), not
   silently added to any proposed `requirements-dev.txt`.

Neither option is chosen by this audit. Option 1 is the lower-friction
default recommendation (no new dependency, no image change at all —
purely a Compose-file addition) **if** the operator's Docker Compose CLI
version supports it; Option 2 is the fallback if it doesn't or if
finer-grained control is wanted.

**Beat**: same two options apply equally (its command is likewise a
long-running Python process with no autoreload of its own) — restarting
beat on a source change is safe (it holds no in-flight state that
restarting would corrupt; its own schedule-file is opportunistically
rewritable). **Config changes** (e.g. editing `RECONCILIATION_INTERVAL_SECONDS`
in `.env`) require a full container restart either way, regardless of
which reload mechanism is chosen — env vars are read once at process
start (`settings.py` module-level `os.environ.get(...)` calls), not
re-read live.

---

## 10. Hot Reload Analysis

**CONFIRMED FROM CURRENT CODE for the "does the tool already support
this" part; PROPOSED DESIGN for what wiring it into Docker requires.**

| Component | Reload mechanism | Already works today? | What Docker-specific wiring is needed |
|---|---|---|---|
| Django | Built-in `runserver` autoreload (`StatReloader`, polls file mtimes — `watchdog` is not installed, confirmed absent from `requirements.txt`, so Django falls back to its own stat-polling reloader, not the faster watchdog-based one) | Yes, on the host, today (`README.md`'s documented `manage.py runserver` flow) | A source **bind mount** into the container (image's `COPY . .` is a one-time snapshot; without a bind mount, edits on the host never reach the running container) + running `runserver` instead of `gunicorn` (a `command:` override, Section 4) |
| BFF | `tsx watch` (already the project's own `npm run dev` script, confirmed `bff/package.json:8`) | Yes, on the host, today | A bind mount + a container that actually has `tsx` installed (the production final stage does not — Section 4); either target the existing `build` stage or add a `Dockerfile.dev` |
| Frontend | Vite HMR (`npm run dev`, confirmed `frontend/package.json:7`) | Yes, on the host, today | A bind mount + a container with Vite installed (same constraint as BFF) + **`vite.config.ts` currently has no `server.host` set** (confirmed by direct read — plugins-only config), meaning Vite's dev server binds to `localhost` inside the container by default and would **not** be reachable from the host browser via a published port without adding `server: { host: true }` (or an equivalent `--host` CLI flag) — a genuine, concrete gap this audit identifies but does not fix (out of scope: "jangan mengubah source code") |
| Celery worker | No built-in mechanism (Section 9) | No — not exercised at all today per `README.md`'s own admission | `develop.watch` or `watchdog`+`watchmedo` (Section 9), neither chosen yet |
| Celery beat | Same as worker | No | Same as worker |

**Limitations, stated plainly**: Django's `StatReloader` (no `watchdog`
installed) polls the filesystem roughly once per second rather than
reacting to OS-level file events — functionally fine for a single
developer's edit-save-reload loop, just marginally slower than the
watchdog-accelerated path Django also supports if `watchdog` were
installed (the same dependency Section 9's Option 2 would add for
Celery — if `watchdog` is approved for Celery's sake, Django's reload
could opportunistically benefit too, at zero extra cost, since it's the
same package).

---

## 11. Development Architecture Proposal

**PROPOSED DESIGN**, built directly from Sections 4/6/9/10's confirmed
constraints — not yet implemented, requires approval (Section 21/22).

**Topology**: one new Compose project, distinct from both
`infrastructure/office/` and `infrastructure/tencent/`, since local
development runs everything on one machine and has no Tencent/Office
physical split to preserve. Services: `backend`, `celery-worker`,
`celery-beat`, `redis`, `bff`, `frontend` — **not** `postgres` (hard rule
#1 applies identically in development; a developer points `DB_*` at
either a real reachable PostgreSQL or a self-managed local instance
outside this repository's Compose files, exactly as `README.md` already
documents) and **not** `waha` unless a developer specifically needs a
disposable WAHA instance for integration work (the existing
`infrastructure/tencent/docker-compose.yml` already provisions one; a
development compose file could optionally reuse/extend that rather than
redefining it — a genuine open question, Section 21).

**Per-service reload approach** (derived from Section 10, decided where
the evidence is unambiguous):

- **`backend`**: reuse the *existing* `backend/Dockerfile` image as-is —
  **no `Dockerfile.dev` needed** (Section 4's finding: the production
  image already contains everything `runserver` needs). Development
  compose overrides only `command: python manage.py runserver 0.0.0.0:8000`
  and adds a bind mount (`./backend:/app`).
- **`celery-worker`/`celery-beat`**: same image, same bind mount, `command:`
  unchanged from production (`celery -A config worker -l info` /
  `celery -A config beat -l info`) — reload is handled by
  `develop.watch` (or `watchmedo`, Section 9's undecided choice) acting
  on the same bind-mounted source, not by a different image or command.
- **`bff`**: **needs either a `Dockerfile.dev` or a `--target build`
  build** against the existing multi-stage Dockerfile (Section 4) — a
  genuine, real decision point (Section 21), since both are valid and
  neither is obviously better from source alone: `--target build` reuses
  the existing file with zero new files, but silently depends on that
  stage's `RUN npm run build` step still succeeding even though its
  output is irrelevant for dev (`tsx watch` runs from source, not
  `dist/`) — mildly wasteful but not broken. A `Dockerfile.dev` avoids
  that wasted build step at the cost of a second file to keep in sync
  (e.g. if the Node base image version ever changes).
- **`frontend`**: same two-option tradeoff as `bff`, plus the
  `vite.config.ts` `server.host` gap already named in Section 10 — that
  one file change is a real prerequisite for this to work at all in
  Docker, regardless of which Dockerfile approach is chosen.
- **`redis`**: unchanged from the existing `infrastructure/office/docker-compose.yml`
  definition (`redis:7-alpine`, no persistence, no published port,
  Section 8) — nothing about development needs Redis to behave
  differently from production here.

**`RECONCILIATION_EXECUTOR=celery` in development** — the task's stated
priority. **Directly achievable** with the topology above: since
`celery-worker`/`celery-beat`/`redis` are now real, running containers in
the same Compose project as `backend`, setting `RECONCILIATION_EXECUTOR=celery`
in the development `.env` makes `apps.sync.executors.trigger_reconciliation()`
enqueue onto the *real* broker, consumed by the *real* worker — the exact
same code path production uses (Section 9's "no second code path" design,
already true today, confirmed by `apps/sync/executors.py`'s own
docstring: "Both executors call the exact same, already-tested
`reconcile_session()`"). **No code change is required to make this work**
— only the Compose/topology work described above; the executor
abstraction was already built for exactly this.

**BFF → Django in this topology**: same Compose project as `backend`
now, so `DJANGO_INTERNAL_BASE_URL` would point at the bare service name
(`http://backend:8000`) rather than a NetBird/LAN address — a
**topology difference from production** (Section 3), not a defect, but
worth naming explicitly in Section 14's parity table so it's never
mistaken for "the same as prod."

---

## 12. Staging Architecture Proposal

**PROPOSED DESIGN.** Staging's own stated goal ("sedekat mungkin dengan
production") maps directly onto reusing the *exact* existing production
Dockerfiles/images unchanged — Section 4 already confirmed nothing about
them is dev-specific, so **no new Dockerfile variant is needed for
staging at all**, only a new Compose file (or override) that:

- Builds/pulls the same three images `infrastructure/office/` and
  `infrastructure/tencent/` already build today, with the same `CMD`s
  (`gunicorn`, compiled `dist/index.js`, `nginx`) — **no
  `runserver`/`tsx watch`/Vite dev server anywhere in staging**, directly
  satisfying the task's explicit Section 10 safety requirement.
- Differs from production **only** via environment/configuration/secrets
  — a different `.env` file (different `DJANGO_ALLOWED_HOSTS`,
  `CORS_ALLOWED_ORIGINS`, a staging PostgreSQL, staging WAHA credentials)
  and, if staging is co-located on shared infrastructure rather than
  mirroring the Tencent/Office physical split 1:1, different exposed
  ports — **not** different images, different `command:`s, or different
  source-mount behavior.
- **No source bind mount in staging** — every image is built fresh from
  a commit, exactly like production, satisfying Section 10's
  "tidak menggunakan... source bind mount untuk runtime production-style"
  requirement directly.

**Does staging need its own Tencent/Office split, or can it be one
combined stack?** **INFERRED, not confirmed** — nothing in current docs
specifies a staging topology at all (Section 3/13's finding: staging is
not mentioned anywhere in `docs/00-MASTER-SPEC.md` through
`docs/15-CODING-PHASES.md`, nor in any `docs/generated/` report found).
If staging is meant to validate the *same* cross-host NetBird/LAN
BFF↔Django path production uses, it would need the same two-location
split as production; if staging is meant only to validate
"production-built images work correctly," a single combined staging host
would suffice but would **not** be testing the real network topology —
this is a genuine open question for Section 21, not decidable from
source alone.

---

## 13. Production Architecture Proposal

**Existing topology is not to be disturbed — confirmed unchanged in this
audit.** `infrastructure/office/docker-compose.yml` and
`infrastructure/tencent/docker-compose.yml` remain the authoritative
production definition; **this audit proposes zero structural changes to
either file's service list, images, or topology.** The only
production-facing recommendation from this audit is the Section 1/7
discrepancy fix (adding `RECONCILIATION_EXECUTOR=celery` to
`infrastructure/office/.env.example`, with a comment explaining why,
mirroring `backend/.env.example`'s existing explanatory comment style) —
an `.env.example` documentation fix, not a compose/topology change, and
still **not implemented by this audit** (out of scope per the task's own
rules; named here as the clear, low-risk next step, Section 22).

If a base+override Compose strategy (Section 15) is adopted, production's
own file would become `infrastructure/office/docker-compose.yml`
(unchanged, kept as today) or a `production.yml` override sitting beside
an extracted `base.yml` — a **pure file-organization refactor with
byte-identical resulting configuration**, not a topology change, and
**not performed by this audit**.

---

## 14. Development / Staging / Production Comparison

**PROPOSED DESIGN for Development and Staging columns (not yet built);
CONFIRMED FROM CURRENT CODE for Production.**

| Component | Development (proposed) | Staging (proposed) | Production (confirmed, unchanged) |
|---|---|---|---|
| Django | `runserver`, same image as prod, source bind-mounted | `gunicorn`, prod image, no mount | `gunicorn`, prod image, no mount |
| Gunicorn | Not used (runserver instead) | Used, `config.wsgi:application` | Used, `config.wsgi:application` |
| BFF | `tsx watch`, `build`-stage or `Dockerfile.dev`, bind-mounted | Compiled `dist/index.js`, prod image | Compiled `dist/index.js`, prod image |
| Frontend | Vite dev server + HMR, needs `server.host` fix, bind-mounted | Static build + Nginx, prod image | Static build + Nginx, prod image |
| Celery Worker | Real worker, real Redis, reload via `develop.watch`/`watchdog` (undecided) | Real worker, no reload | Real worker, no reload (today, confirmed) |
| Celery Beat | Real beat, same reload question as worker | Real beat, no reload | Real beat, no reload (today, confirmed) |
| Redis | `redis:7-alpine`, unpublished, no persistence — same as prod | Same as prod | `redis:7-alpine`, unpublished, no persistence (confirmed) |
| PostgreSQL | External, developer-provided — never a container (hard rule) | External, staging instance — never a container | External, existing instance — never a container (confirmed) |
| WAHA | Optional, reuse Tencent's definition or omit | Real WAHA instance, staging session | `devlikeapro/waha:gows`, unpublished port (confirmed) |
| `RECONCILIATION_EXECUTOR` | `celery` (the task's explicit goal) | `celery` (matches prod) | **Undetermined today** — Section 1/7's discrepancy |
| BFF→Django transport | Docker bridge network (same Compose project) | Depends on staging topology decision (Section 12) | NetBird/LAN (confirmed) |

**"Works on development but fails on production" risks this table
surfaces**: (1) the BFF→Django transport row — a development-only
same-network path could mask a NetBird/LAN-specific failure mode (DNS,
firewall, latency) that only manifests in staging/production; (2) the
`RECONCILIATION_EXECUTOR` row — if development is fixed to `celery`
(this task's own goal) while production's real value remains
unconfirmed (Section 1), development would newly become the
**more**-production-like environment on this one axis, inverting the
usual risk direction — worth resolving the production `.env` alongside
this migration, not after it, precisely so development doesn't leave
production looking comparatively untested.

---

## 15. Compose Strategy Comparison

**PROPOSED DESIGN — a decision, not a fact, explained against this
repository's own existing conventions rather than general preference.**

**A. The user's proposed structure** — per-component
`{backend,bff,frontend}/compose/{base,development,staging,production}.yml`.
**Tension with existing architecture**: `docs/14-REPOSITORY-STRUCTURE.md`'s
own "Ownership" section states plainly: `infrastructure` = deployment,
and a task scoped to one component should not modify another. Splitting
compose ownership into three component directories means **no single
file answers "what runs together in production"** — that knowledge
becomes implicit, reconstructed by combining three separate
`production.yml` files across three directories, none of which
individually shows the Tencent/Office physical split this project's
`docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md` treats as a first-class
architectural fact. This also risks exactly the "mixing Tencent and
Office deployment concerns" the project's own hard rule #9 forbids, if a
single top-level `docker compose up` were ever built to span all three
component directories at once without preserving that split explicitly.

**B. Location/environment-scoped base+override** (this audit's
recommendation) — extend the *existing* `infrastructure/` pattern rather
than replacing it:
```
infrastructure/
├── office/
│   ├── base.yml            # backend, celery-worker, celery-beat, redis — shared shape
│   ├── production.yml      # today's docker-compose.yml, renamed/extracted
│   └── staging.yml         # staging overrides (Section 12)
├── tencent/
│   ├── base.yml
│   ├── production.yml
│   └── staging.yml
└── development/
    └── docker-compose.yml  # single file — dev has no location split to preserve
```
Run as `docker compose -f infrastructure/office/base.yml -f infrastructure/office/production.yml up`
— a standard, well-documented Compose pattern (`-f` file layering), **not
a novel one invented for this proposal**. This keeps `infrastructure/`
as the single place "what runs together, where" is answered, matching
`docs/14-REPOSITORY-STRUCTURE.md` exactly, and keeps Tencent/Office
physically separate in staging exactly as production already is —
directly avoiding hard rule #9's concern. **Dockerfiles still live at
each component's own root** (`backend/Dockerfile`, plus a proposed
`backend/Dockerfile.dev` or multi-stage target, Section 11) — this part
of the user's proposed structure fits well and is not in tension with
anything; only the **compose**-ownership half of the proposal is
redirected here.

**C. One giant compose file for everything**: rejected — directly
conflicts with hard rule #9 and with the existing, deliberate
Tencent/Office split; explicitly warned against in the task's own
instructions ("Jangan mengasumsikan bahwa production harus dipindahkan
ke satu Compose besar").

**D. Compose `profiles:` inside the two existing files**: technically
possible (e.g. a `dev` profile toggling `runserver` vs `gunicorn`
services within the same file) but **conflates two independent axes**
(which physical location, which environment) into one file's profile
list, making it harder to answer "what does staging actually run" at a
glance than the base+override split above. Not recommended, but not
unworkable — a legitimate alternative if the operator strongly prefers
fewer files over clearer separation.

**E. Keep the two existing files completely untouched, add only a third,
independent `infrastructure/development/docker-compose.yml`**: the
**lowest-disruption option** — no refactor of the existing,
already-working production files at all, only a net-new file. This
satisfies "production topology existing TIDAK BOLEH dirusak" most
literally, at the cost of not yet getting staging's own base+override
benefit (staging would instead need its own from-scratch file,
duplicating rather than reusing production's service definitions). A
reasonable **first phase** even if option B is the eventual target
(Section 18's migration plan sequences it this way).

**Recommendation, derived from repository evidence (Section 14's own
instruction: choose by existing structure, not personal preference)**:
**Option E first, Option B as the eventual shape** — start with a
new, isolated `infrastructure/development/` file that touches nothing
existing (satisfies the hard "don't disturb production" constraint
maximally), and only extract `base.yml`/`production.yml` out of the two
existing files later, once staging is actually being built and the
duplication option E would otherwise require becomes a real, felt cost
rather than a hypothetical one.

---

## 16. Security Considerations

**CONFIRMED FROM CURRENT CODE where stated as fact; PROPOSED DESIGN
where stated as a recommendation for the new development/staging work:**

- **`.env` into Git**: already structurally prevented — root `.gitignore`
  has `.env`, `*/.env`, `**/.env`, `.env.*`, with an explicit
  `!**/.env.example` re-inclusion (confirmed, Section-7-adjacent read).
  Any new `infrastructure/development/.env.example` should follow this
  exact existing pattern — no new `.gitignore` rule needed, the wildcard
  patterns already cover any new directory.
- **Secrets in Dockerfile/image layers**: none found in any of the three
  existing Dockerfiles (all secrets arrive via `env_file:`/environment at
  *run* time, never `ARG`/`ENV`-baked at *build* time) — a proposed
  `Dockerfile.dev` should preserve this same discipline.
- **Source bind mount in production**: not present today, and Section
  12/13's proposal explicitly keeps it that way for both staging and
  production — bind mounts are a development-only proposal (Section 11).
- **Redis/PostgreSQL exposure**: covered in depth, Section 8 — Redis has
  no published port today and this audit recommends keeping it that way
  in every environment including development; PostgreSQL was never a
  container in the first place (hard rule #1).
- **Development hostnames into production**: covered in Section 7 —
  the real risk is a *shared* Docker network/volume/`.env` between a new
  development Compose project and the existing production ones, not the
  service-name strings themselves; Section 11's proposal already
  specifies development as its own, fully separate Compose project.
- **`runserver`/`tsx watch`/Vite dev server in production**: explicitly
  ruled out in Section 12/13 — staging and production both reuse the
  unmodified production Dockerfiles/commands.

---

## 17. Production Parity Risks

Consolidating what Sections 11/12/14 already surfaced, stated once here
as the task's Section 17 explicitly requests:

1. **BFF↔Django transport differs by environment** (Docker bridge in dev,
   NetBird/LAN in staging/production, Section 3/14) — a real, unavoidable
   difference given development runs on one machine; mitigated only by
   treating staging (not development) as the environment that validates
   the NetBird/LAN path specifically, per Section 12's open question.
2. **`RECONCILIATION_EXECUTOR` production value is currently
   undetermined** (Section 1/7) — fixing development to `celery` (this
   task's own explicit goal) without also fixing
   `infrastructure/office/.env.example` risks development becoming
   *more* thoroughly exercised on this exact axis than production ever
   has been, inverting the usual "prod is the least-tested environment"
   risk direction into "prod might still silently be running `sync`."
3. **Redis has no persistence or healthcheck anywhere today** (Section
   8/5) — a risk equally present in current production, not introduced
   by this proposal, but worth deciding on explicitly rather than
   silently carrying forward into a newly-formalized staging environment
   that's specifically meant to catch this class of gap before
   production does.
4. **Celery worker/beat reload mechanism is entirely undecided**
   (Section 9) — until Section 21's decision is made, "development uses
   real Celery" (this task's goal) is achievable but without live-reload
   on the worker specifically, meaning a developer would need to
   manually restart `celery-worker`/`celery-beat` after each Python
   change unless/until `develop.watch` or `watchdog` is chosen and wired
   in — not a parity risk exactly, but a real gap between "the goal
   stated in this task" and "what's fully specified by the end of this
   audit."

---

## 18. Migration Plan

**PROPOSED DESIGN — dependency-ordered, not forced into the task's
example lettering.** Each phase is independently shippable and testable
before the next begins, consistent with this project's own established
"one slice at a time, verify, stop" discipline used throughout every
other Phase 9 task in this session.

**Phase A — Fix the `RECONCILIATION_EXECUTOR` production `.env.example`
gap** (Section 1/7/13). Smallest possible change, zero Docker/compose
work, directly resolves a discrepancy already flagged across multiple
prior Phase 9 reports. No dependency on anything else in this plan.

**Phase B — `infrastructure/development/docker-compose.yml`, backend
only** (`backend`, `celery-worker`, `celery-beat`, `redis`, reusing the
existing `backend/Dockerfile` with a `command:` override + bind mount,
per Section 11). Directly delivers the task's stated top priority
(`RECONCILIATION_EXECUTOR=celery` in development) without touching BFF or
frontend at all. Depends on Phase A only in the sense that Phase A's fix
should exist before development's own `.env` is written, so both
environments' `.env.example` files stay consistent with each other from
the start (not a hard technical dependency, just avoids re-doing the same
fix twice).

**Phase C — Celery worker/beat reload mechanism** (Section 9/21's
decision). Depends on Phase B existing (needs the containers to attach
the reload mechanism to). Can be deferred past Phase D/E if the operator
is fine with manual worker restarts during initial development-Docker
adoption — explicitly not a hard blocker for Phase B's own value.

**Phase D — BFF development container** (`Dockerfile.dev` or `--target
build`, per Section 11's undecided choice; added to the same
`infrastructure/development/docker-compose.yml`). Independent of
Phase C; depends only on Phase B's file existing to extend.

**Phase E — Frontend development container** (same undecided
Dockerfile-vs-target choice, **plus** the `vite.config.ts` `server.host`
fix named in Section 10 — the one actual source-code change this entire
plan requires, and only this one). Independent of Phase C/D; depends only
on Phase B's file existing.

**Phase F — Staging Compose** (Section 12). Depends on Phase A (needs a
resolved `RECONCILIATION_EXECUTOR` story to mirror) and benefits from,
but does not strictly require, Phases B–E being done first (staging
reuses production Dockerfiles, not the development ones). Requires
Section 12/21's open topology question (combined vs. Tencent/Office-split
staging) resolved first.

**Phase G — Production Compose cleanup** (Section 15's Option B
base/override extraction). Lowest priority — Section 15 already
recommends deferring this until staging (Phase F) makes the duplication
cost concrete; **must not** be done before Phase F if Option E→B
sequencing (Section 15) is accepted, since extracting `base.yml` out of
production prematurely, before a second consumer (staging) exists to
justify it, is pure speculative refactoring of an already-working,
must-not-be-disturbed file.

**Explicit non-forcing note**: Phases D and E have no dependency on each
other or on Phase C, and could be done in either order or in parallel by
different people; Phase C could equally be done last if manual worker
restarts are an acceptable interim state. Only A→B, A/B→F, and F→G carry
real dependencies.

---

## 19. Files That Would Change (Once Implementation Is Approved)

Listed for planning only — **nothing below has been created or modified
by this audit**:

- `infrastructure/office/.env.example` — add `RECONCILIATION_EXECUTOR=celery`
  with an explanatory comment (Phase A).
- New: `infrastructure/development/docker-compose.yml` (Phase B),
  `infrastructure/development/.env.example` (Phase B).
- Possibly new: `backend/Dockerfile.dev` (only if Section 21 decides
  against reusing the existing image via `command:` override — Section 11
  found this likely unnecessary for backend specifically).
- Possibly new: `bff/Dockerfile.dev`, `frontend/Dockerfile.dev` (Phases D/E
  — only if Section 21 decides against `--target build` reuse).
- `frontend/vite.config.ts` — add `server: { host: true }` (Phase E,
  Section 10) — the one genuine application-source change this whole plan
  implies, and a small, additive one.
- Possibly, much later (Phase F): new `infrastructure/office/staging.yml`,
  `infrastructure/tencent/staging.yml`, staging `.env.example` files.
- Possibly, much later (Phase G, deferred per Section 15/18): `infrastructure/office/base.yml`
  + `production.yml` extracted from today's single file (content-identical
  reorganization); same for `infrastructure/tencent/`.

---

## 20. Files That Must NOT Change

Restated explicitly, per the task's own emphasis:

- `infrastructure/office/docker-compose.yml`, `infrastructure/tencent/docker-compose.yml`
  — production topology, service list, images, and behavior must remain
  exactly as they are today throughout every phase of Section 18 except
  the deferred, optional Phase G reorganization (which, even then, must
  be byte-behavior-identical, not a topology change).
- `backend/Dockerfile`, `bff/Dockerfile`, `frontend/Dockerfile` — every
  proposal in this report adds new files or, at most, a new named build
  stage; none proposes editing these three files' existing behavior.
- Any `.env` file (only `.env.example` templates are ever proposed for
  change).
- The database, any migration, and WAHA session state — untouched by
  every phase in Section 18, none of which involves Django models, WAHA
  API calls, or WhatsApp interaction of any kind.

---

## 21. Open Questions / User Decisions Required

1. **Celery worker/beat dev-reload mechanism** (Section 9/17). **Options**:
   (a) Compose `develop.watch` — no new dependency, but needs a
   Compose-CLI-version check this audit cannot perform from source; (b)
   `watchdog` + `watchmedo` — a new pip dependency, works regardless of
   Compose CLI version, and would incidentally also let Django's own
   `runserver` reloader use the faster watchdog backend (Section 10) at
   no extra cost. **Consequence**: choosing (a) risks silently not
   working if the operator's Compose CLI is older than v2.22; choosing
   (b) adds a dependency that must be approved per the task's own
   instruction. **Recommendation based on existing architecture**: try
   (a) first (zero code/dependency footprint, consistent with this
   project's general preference for configuration over new libraries —
   e.g. `RECONCILIATION_EXECUTOR` itself is a pure-config toggle, no new
   package), falling back to (b) only if the Compose CLI version check
   fails.

2. **BFF/frontend dev image: separate `Dockerfile.dev` vs. `--target
   build` against the existing multi-stage Dockerfile** (Section 11).
   **Consequence**: `--target build` means zero new files but a wasted
   `npm run build` step on every dev image rebuild; a separate
   `Dockerfile.dev` avoids that at the cost of a second file per
   component to keep loosely in sync (base image version, `apt`/`apk`
   packages if any are ever added). **No strong architectural pull either
   way** — genuinely a maintenance-preference call.

3. **Should `infrastructure/development/` optionally include `waha`**
   (reusing/extending `infrastructure/tencent/docker-compose.yml`'s
   definition), or should development always point at a developer-managed
   external WAHA instance, exactly as it does for PostgreSQL today?
   (Section 11.) **Consequence**: including it makes development fully
   self-contained but duplicates a service definition across two Compose
   projects (development and Tencent); excluding it keeps a single
   source of truth for the WAHA service shape but means development
   depends on external WAHA access, same as it already does for
   PostgreSQL.

4. **Staging topology: combined single host, or the same Tencent/Office
   physical split as production?** (Section 12.) **Consequence**:
   combined is cheaper to run and still validates "do the production
   images work," but does not exercise the real NetBird/LAN BFF↔Django
   path (Section 3/17's parity risk #1) — only a split staging topology
   would. Not decidable from source; no staging concept exists anywhere
   in current docs to infer an answer from.

5. **Redis persistence for staging/production** (Section 8). Today's
   answer is "none, anywhere" — this audit surfaces it as a live question
   rather than assuming either "add it" or "leave it" is obviously
   correct, since nothing in the current architecture states a durability
   requirement for Redis's contents one way or the other.

6. **Compose strategy for staging/production**: Option B (location-scoped
   base+override, this audit's stated recommendation) vs. Option D
   (profiles in the existing two files) vs. staying with Option E
   indefinitely (never extracting `base.yml` at all, just maintaining
   parallel staging/production files per location) (Section 15/18).

7. **Whether to proceed with Phase A (the `RECONCILIATION_EXECUTOR`
   `.env.example` fix) independently and immediately**, given it's a
   one-line documentation fix with no dependency on any other part of
   this plan, versus bundling it into the same approval as the larger
   development-Docker work.

8. **Carried forward, still unresolved from every prior Phase 9 report**:
   confirming `RECONCILIATION_EXECUTOR`'s *actual currently-deployed*
   production value (not just the `.env.example` template default) — this
   audit can name the template gap (Section 1) but cannot observe the
   real running Office deployment's actual configured value from the
   repository alone.

---

## 22. Recommended Next Implementation Task

Dependency-ordered, per the task's own request, **not a preference
ranking**:

**Phase A** (Section 18) — fixing `infrastructure/office/.env.example`'s
missing `RECONCILIATION_EXECUTOR` line — is the smallest, lowest-risk,
zero-Docker-file-touching next step, has no dependency on any open
question in Section 21 except item 7 (bundle-vs-standalone), and directly
resolves a discrepancy this session's own prior Phase 9 reports have
carried as unresolved since the very first audit in this conversation.
**Phase B** (a `backend`-only `infrastructure/development/docker-compose.yml`,
reusing the existing `backend/Dockerfile` unchanged) is the next
dependency-ordered step after that, and is the most direct route to this
task's own explicitly stated top priority — real Celery/Redis in
development — without yet requiring any of Section 21's harder,
genuinely-open BFF/frontend/staging decisions to be resolved first.

---

## Summary

**No source code, Dockerfile, compose file, `.env`, database, or WAHA
state was modified in producing this report.** No deployment was run. The
audit found: (1) no development or staging Docker environment exists
today — only two production-shaped Compose files, one per physical
location, exactly matching documented topology; (2) a concrete,
previously-unlocated discrepancy — `infrastructure/office/.env.example`
never sets `RECONCILIATION_EXECUTOR`, so the real Office production
deployment may be silently running reconciliation in-process (`sync`)
despite provisioning real Celery/Redis infrastructure beside it; (3) the
user's proposed per-component `compose/` structure fragments an existing,
explicit repository decision that `infrastructure/` owns deployment
topology by physical location — a location-scoped base+override structure
fits better, while per-component `Dockerfile`/`Dockerfile.dev` fits fine
as proposed; (4) achieving real `RECONCILIATION_EXECUTOR=celery` in
development requires no code change at all — only Compose/topology work,
since `apps/sync/executors.py`'s dual-executor design already exists for
exactly this; (5) Celery worker/beat hot-reload has no precedent in this
codebase and needs one of two new mechanisms, one of which requires a new
dependency and is flagged for approval, not silently chosen. A
dependency-ordered migration plan (Section 18) and two independent next
steps (Section 22) are provided. **Awaiting your decisions in Section 21
— nothing was implemented.**
