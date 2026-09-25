# Phase C — BFF Development Docker — Design Audit (Read-Only)

**Scope.** Design/read-only audit only. No Dockerfile, Compose file,
source code, `package.json`/`package-lock.json`, `.env`/`.env.example`,
or database configuration was created or modified. No container was
built or started, no HTTP request was made, no WhatsApp message was
sent. Phase A and Phase B are unmodified and not re-implemented here —
Phase B's own files (`infrastructure/development/office.yml`,
`.env.example`) were re-read this task only to check integration points,
never edited. Every claim below was verified directly against current
source this task; where a prior report's finding is reused, it was
independently re-confirmed first (Section 2's networking claim in
particular was re-derived from `bff/src/djangoClient.ts` itself, not
assumed from the Phase B report).

---

## 1. Executive Summary

The BFF's existing `Dockerfile` has the **exact same** structural gap
the earlier Docker audits already found in the backend/frontend
Dockerfiles, now re-confirmed directly against current source: its
production final stage runs `npm install --omit=dev`, which excludes
`tsx` — the package the BFF's own already-existing `npm run dev` script
(`tsx watch --env-file-if-exists=.env src/index.ts`) requires. The
**`build` stage**, however, already runs a full `npm install` including
`tsx`, so `docker build --target build` against the **unmodified**
existing Dockerfile is a real, workable option, alongside a
`Dockerfile.dev` alternative — this audit does not choose between them
(Section 12).

**One new, concrete finding this task**, verified directly against
`bff/src/djangoClient.ts:38-51` (`postJson()`): the BFF's calls to
Django are built via `new URL(path, options.baseUrl)` and a plain
`fetch()` — `options.baseUrl` is `config.djangoInternalBaseUrl`, read
verbatim from `process.env.DJANGO_INTERNAL_BASE_URL`. **There is no code
path anywhere in the BFF that assumes a Docker network, a bare service
name, or any transport other than "whatever full URL string this
variable holds."** This means the "BFF reaches Django via an explicit
URL, never an assumed shared network" principle the Phase B design audit
recommended is not just an operational choice this project could make —
it is **already how the code is written**, for every environment,
today. Development following that same pattern (`http://host.docker.internal:8000`,
matching Phase B's own published `8000:8000`) requires zero code change.

**A second new finding**: Phase B named its environment file
`infrastructure/development/.env.example` (bare, not
`office.env.example`) — reasonable on its own, since Phase B only ever
populated one file. But a future BFF/frontend development file living in
the **same** `infrastructure/development/` directory cannot also be
named `.env.example` without colliding with Phase B's file. This is a
real naming-scope question this audit surfaces (Section 5/15) — **not**
a correctness defect in Phase B itself (nothing about Phase B is wrong
in isolation), so this audit does not propose changing Phase B's file;
it flags the question for a decision before Phase C's own files (not
created by this audit) are ever written.

---

## 2. Current BFF Docker/Runtime Architecture

**CONFIRMED FROM CURRENT CODE, re-read in full this task:**

```
bff/Dockerfile                              — 2-stage (build, then production)
bff/package.json                            — dev/build/start/typecheck/test scripts
bff/.env.example                            — bare-host + component-level dev template
infrastructure/tencent/docker-compose.yml   — production: frontend, bff, waha
infrastructure/tencent/.env.example         — location-level production template
infrastructure/development/office.yml       — Phase B, Office-side only, no BFF service
infrastructure/development/.env.example     — Phase B, Office-side only
```

`infrastructure/tencent/docker-compose.yml`'s `bff` service (re-read in
full this task, byte-identical to every prior audit's finding):
`build: context: ../../bff`, `env_file: .env`, `ports: "8080:8080"`,
`depends_on: waha`, `restart: unless-stopped` — **no `networks:`,
`develop:`, `profiles:`, or `healthcheck:` block**, same as every other
production Compose file in this repository.

**BFF source layout** (`bff/src/`, listed and the relevant files read in
full this task): `index.ts` (entrypoint — creates the Express app,
`app.listen(config.port, ...)`), `app.ts` (mounts `healthRouter`,
`sessionRouter`, `messagesRouter`, CORS middleware), `config.ts`
(reads every environment variable, Section 5), `djangoClient.ts`
(BFF→Django internal calls, Section 6), `middleware/auth.ts` (JWT
verification via `requireAuth`/`requireScope`), `routes/health.ts`
(`GET /health`, Section 8), plus `routes/session.ts`, `routes/messages.ts`,
`wahaClient.ts`, `wahaAllowlist.ts`, `operationLock.ts`, `auditHelper.ts`,
`corsOptions.ts`, `errors.ts`, `jwt.ts` — none of which change how the
BFF is started, configured, or networked, so none required deeper
reading for this audit's Docker-specific scope.

---

## 3. Existing Dockerfile Analysis

**CONFIRMED FROM CURRENT CODE, re-read in full this task — unchanged
from the general Docker environment audit's earlier finding:**

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY package*.json ./
RUN npm install --omit=dev
COPY --from=build /app/dist ./dist

EXPOSE 8080
CMD ["node", "dist/index.js"]
```

- **Final (production) stage**: `npm install --omit=dev` explicitly
  excludes `devDependencies` — `tsx` (`bff/package.json:26`,
  `devDependencies`) is **not present** in this stage's `node_modules`.
  Confirmed by direct read of the Dockerfile and `package.json` together,
  not assumed: `npm run dev` (`tsx watch ...`) **cannot run** in a
  container built from this stage alone.
- **`build` stage**: runs a full, unqualified `npm install` (both
  dependencies and devDependencies) **before** `RUN npm run build` — at
  the point that install finishes, `tsx` (and `vitest`, `typescript`,
  every other devDependency) is present. `docker build --target build`
  against this **exact, unmodified** Dockerfile produces a usable dev
  image, at the cost of that stage's own `RUN npm run build` step still
  executing (its `dist/` output is simply unused in dev, since `tsx
  watch` runs directly from `src/`) — a small, harmless inefficiency, not
  a functional problem.
- **Conclusion, matching the earlier general audit's finding, now
  re-verified specifically for this task**: the existing Dockerfile is
  reusable via `--target build`, **or** a `Dockerfile.dev` could be
  written to skip the wasted build step — both are real, valid options;
  this audit does not choose between them (Section 15, carried forward
  from the earlier audit since no new evidence in this task tips the
  balance).

---

## 4. Development Command / Hot-Reload Analysis

**CONFIRMED FROM CURRENT CODE:**

- **Production command**: `CMD ["node", "dist/index.js"]` — runs the
  compiled, frozen build.
- **Development command — already exists, no change needed**:
  `bff/package.json:8`, `"dev": "tsx watch --env-file-if-exists=.env src/index.ts"`.
  `tsx watch` is `tsx`'s own built-in file-watching mode (esbuild-backed
  — re-transpiles and restarts the process on every source change) —
  **this already fully provides hot reload**, with **no additional
  package needed** (satisfies the task's instruction not to add a new
  dependency "just to obtain hot reload").
- **Is source bind-mounting safe?** Yes — identical reasoning to the
  Phase B backend design: the container's installed `node_modules` lives
  under `/app/node_modules`, and `tsx watch` reads TypeScript source
  directly from `/app/src`; bind-mounting `bff/:/app` from the host makes
  edits visible immediately, the same mechanism `tsx watch` already uses
  when run on bare host today.
- **Should `node_modules` remain inside the container?** Yes — bind
  mounting the **host's** `bff/` directory would shadow the image's
  already-`npm install`-ed `node_modules` with whatever the host
  currently has (possibly absent, or containing host-OS/architecture-
  mismatched native binaries, e.g. from `cffi`/`bcrypt`-style native
  addons if any existed here — this project's actual dependency list has
  none, but the general risk is still real for any future dependency).
  **PROPOSED**: an anonymous Docker volume mounted at `/app/node_modules`
  on top of the source bind mount (`volumes: ["../../bff:/app",
  "/app/node_modules"]`) — the same standard, well-documented Compose
  idiom already proposed for this exact purpose in the earlier general
  Docker audit, re-affirmed here after re-reading the Dockerfile
  directly.
- **Install at build time or container startup?** **At build time**
  (the existing `build` stage's own `npm install`) — **not** at
  container startup. Re-running `npm install` on every `docker compose
  up` would be slow and would fight with the anonymous-volume strategy
  above (the volume should be seeded once, by the image's own build-time
  install, and only re-seeded via an image rebuild after a genuine
  `package.json` change — an explicit, deliberate trigger, not an
  automatic one).

---

## 5. Environment-Variable Inventory

**CONFIRMED FROM CURRENT CODE** — every variable below is read directly
by `bff/src/config.ts` (re-read in full this task); none invented.

**BFF-only** (no Django-side counterpart at all): `PORT`, `WAHA_BASE_URL`,
`WAHA_API_KEY`, `CORS_ALLOWED_ORIGIN`, `WAHA_SESSION_NAME`,
`DJANGO_INTERNAL_TIMEOUT_MS`, `WAHA_TIMEOUT_MS`.

**Shared/duplicated** (value must agree with a Django-side variable, but
read from the BFF's own separate `.env` — no shared-file mechanism
exists anywhere in this project, confirmed by every `.env.example`
requiring the same value to be pasted into two different files already):
- `JWT_PUBLIC_KEY`/`JWT_PUBLIC_KEY_PATH` — must be the **public half**
  of Django's `JWT_PRIVATE_KEY` (a derived relationship, not an identical
  string).
- `JWT_ISSUER`, `JWT_AUDIENCE` — must be textually identical to Django's
  own `JWT_ISSUER`/`JWT_AUDIENCE` (`config/settings.py`) for token
  verification to succeed at all.
- `INTERNAL_SERVICE_KEY` — must be **literally identical** on both
  sides (a static shared secret, Section 6).
- `DJANGO_INTERNAL_BASE_URL` — conceptually "shared" in the sense that
  it must resolve to wherever Django's `backend` container/process
  actually is, but it is a BFF-only variable in the sense that Django
  itself never reads it (Django has no corresponding "BFF base URL"
  setting of its own — confirmed absent from `config/settings.py`).

**Development-only / production-only values** (not variable names —
the same variables exist in every environment; only their *values*
differ): `WAHA_BASE_URL` (Docker-network `http://waha:3000` in
production per `bff/.env.example`'s own default; a real, external,
already-running WAHA URL in development, per Phase B's own precedent for
`WAHA_BASE_URL`/Section 11 of the Phase B design report — WAHA is not
part of this development topology, Section 9's own constraint list
re-confirms this); `DJANGO_INTERNAL_BASE_URL` (a NetBird/LAN address in
production; `http://host.docker.internal:8000` in development, Section 6
below); `CORS_ALLOWED_ORIGIN` (the real frontend origin in production;
`http://localhost:5173` in development, already the exact default
`bff/.env.example` ships today).

**Secrets** (never printed by this report, never invented a value for):
`WAHA_API_KEY`, `JWT_PUBLIC_KEY`(`_PATH`) (a public key — not strictly
secret, but treated with the same file-based discipline as the truly
secret ones), `INTERNAL_SERVICE_KEY`.

**Should `infrastructure/development/.env.example` eventually contain
BFF variables, or should BFF get its own development env file?**
**Its own file — by direct precedent, not preference.** The existing,
already-established pattern (re-confirmed this task) is: `backend/.env.example`
(component-level, bare-host) + `infrastructure/office/.env.example`
(location-level, production) are **two separate files for the same
variable set**; identically, `bff/.env.example` (component-level,
bare-host) + `infrastructure/tencent/.env.example` (location-level,
production) are **two separate files** too. Phase B already followed
this exact pattern for the Office side. A BFF development file should
therefore be a **third, Tencent-scoped** file, not merged into Office's —
mixing Office-only variables (`DB_HOST`, `CELERY_BROKER_URL`, etc.) with
Tencent-only variables (`WAHA_API_KEY`, `CORS_ALLOWED_ORIGIN`) in one
file would blur exactly the location-based separation `docs/14-REPOSITORY-STRUCTURE.md`
establishes and every existing `.env.example` pair already preserves.

**The concrete naming question this surfaces (Section 1)**: Phase B's
file is named plainly `infrastructure/development/.env.example`, not
`office.env.example` — so a new Tencent-scoped file in the same
directory needs a **distinct name** (e.g. `tencent.env.example`) to
avoid colliding with it. **Not resolved by this audit** — Section 15.

---

## 6. BFF → Django Networking Analysis

**CONFIRMED FROM CURRENT CODE, the central finding of this audit
(Section 1):**

`bff/src/djangoClient.ts`'s `postJson()` (lines 38-51, re-read in full
this task) constructs every Django-bound request as:
```ts
const url = new URL(path, options.baseUrl);
...
const response = await fetch(url, { method, headers: {...}, body, signal });
```
where `options.baseUrl` traces back to `config.djangoInternalBaseUrl =
process.env.DJANGO_INTERNAL_BASE_URL ?? ''` (`bff/src/config.ts:51`).
**This is a plain HTTP client hitting a URL string from configuration —
there is no `dns.lookup`, no hardcoded service name, no
Docker-network-specific code anywhere in this path.** The architectural
principle documented in `bff/.env.example`'s own comment ("reaches
Django over NetBird/LAN, not the Tencent Docker network") is not merely
a deployment convention layered on top of flexible code — **it is the
only mode this code has ever supported**, for every environment,
confirmed by direct read rather than inferred from documentation alone.

**Comparing the four options the task asks about, against this
confirmed code shape**:

1. **`host.docker.internal`** — `DJANGO_INTERNAL_BASE_URL=http://host.docker.internal:8000`.
   Works with **zero code change**, since the code already just treats
   this as an opaque URL string. Reaches Phase B's `backend` service via
   its already-published `8000:8000` port (`infrastructure/development/office.yml`,
   re-read this task, unchanged) — the exact same mechanism a bare-host
   BFF process already uses today when talking to a bare-host `manage.py
   runserver`. **This is the same option the earlier general Docker
   audit recommended for this exact hop**, now confirmed correct at the
   code level, not just the architecture-diagram level.
2. **A Docker service name (e.g. `backend`)** — would require both
   containers to share a Docker network. **Would also work with zero
   code change** (still just a URL string, only the hostname differs) —
   but would require either merging BFF into the same Compose project as
   `office.yml` (contradicted by Section 9/11's own constraint list:
   "do not fragment... but also do not assume BFF/frontend belong in the
   same Compose project"), or an explicit shared external Docker network
   (an extra setup step, and — more importantly — the *one* environment
   where this hop would stop being "an explicit URL," diverging from
   every other environment's own architecture).
3. **A shared Docker network** — same tradeoff as option 2, just
   explicit rather than implicit; still a real, valid Compose pattern,
   just not the one this audit recommends, for the reason above.
4. **An explicit host URL** — this is what `host.docker.internal`
   *is*, from the code's perspective (Section 6, option 1) — not a
   fourth, different mechanism, but the same one, named separately in
   the task's own question. Confirmed as the correct characterization:
   `DJANGO_INTERNAL_BASE_URL` is always "an explicit host URL," and
   `host.docker.internal` is simply the specific hostname value that
   makes it resolve correctly from inside a development container.

**Recommendation, unchanged from the earlier general audit, now
re-derived from source rather than re-stated from that report**:
**`http://host.docker.internal:8000`**, preserving the "always an
explicit URL, never an assumed shared network" property that — this
task's own re-verification shows — is not just this project's
convention but its actual, only-supported code path.

---

## 7. Internal-Service Authentication Analysis

**CONFIRMED FROM CURRENT CODE, both sides re-read this task:**

- **BFF side**: `config.ts:52`, `internalServiceKey: process.env.INTERNAL_SERVICE_KEY ?? ''` —
  attached as the `X-Internal-Service-Key` header on every internal call
  (`djangoClient.ts:59`). If either `baseUrl` or `serviceKey` is empty,
  the call is **skipped entirely** (`postJson()`'s own guard, line 44) —
  fails closed, matching the Django-side posture.
- **Django side**: `backend/apps/core/internal_auth.py`
  (`HasInternalServiceKey`, re-confirmed this task) reads
  `settings.INTERNAL_SERVICE_KEY` and compares it against the incoming
  `HTTP_X_INTERNAL_SERVICE_KEY` header — **"Fails closed: if
  INTERNAL_SERVICE_KEY is unconfigured, no request is [authorized]"**
  (the class's own docstring, read directly).
- **Must the same secret exist on both sides?** Yes — a static shared
  secret, compared for exact equality; there is no derivation,
  signing, or asymmetric mechanism here (unlike the JWT keypair).
- **Can development safely use a separate local secret?** **Yes** —
  the value only needs to match *between the two development
  containers*, never needs to relate to production's real secret at all
  (exactly analogous to how development would already use its own
  `DJANGO_SECRET_KEY`/JWT keypair, unrelated to production's). This is
  not a new judgment call invented by this audit — `README.md` already
  documents this exact "must match between BFF and Django, not tied to
  any other environment" property for the *existing* bare-host
  workflow, and Phase B's own `.env.example`
  (`infrastructure/development/.env.example:97-103`) already anticipated
  this, leaving `INTERNAL_SERVICE_KEY` present but empty specifically
  for "if you also run a BFF against this backend."
- **Should development Compose inject it into both containers?** Yes,
  in the sense that both the BFF's own `.env` (Section 5's still-open
  naming question) and Office's `infrastructure/development/.env` would
  each need the **same literal value** written into them separately —
  there is no mechanism in this project (Docker secrets, a shared
  `.env`, or otherwise) that lets one value populate two different
  Compose projects' environments automatically. This duplication is not
  new risk Phase C introduces — it is the same manual-duplication
  requirement the existing bare-host `bff/.env` + `backend/.env` pair
  already has, carried into Docker unchanged.

---

## 8. Port / Health Analysis

**CONFIRMED FROM CURRENT CODE:**

- **BFF internal port**: `8080` — `EXPOSE 8080` (Dockerfile),
  `PORT=8080` default (`config.ts:30`, `bff/.env.example:5`).
- **Published in production?** Yes — `"8080:8080"`,
  `infrastructure/tencent/docker-compose.yml`, re-confirmed this task.
- **Should development publish it too?** Yes, for the same reason
  Phase B publishes Django's `8000:8000`: the browser (Section 9) and
  any direct `curl`-based manual testing both need a host-reachable
  port; nothing about running in Docker changes that requirement.
- **Existing health endpoint**: `GET /health`
  (`bff/src/routes/health.ts`, re-read this task) — unauthenticated,
  returns `{status: 'ok', service: 'bff', waha: {reachable: boolean}}`,
  **always with HTTP 200**, regardless of whether WAHA itself is
  reachable (confirmed: `res.status(200).json(...)` unconditionally,
  Section 1 of the earlier general Docker audit's own finding, re-verified
  by direct read this task). This is a deliberate, existing design
  choice (WAHA-reachability is reported *in the body*, not via HTTP
  status) — **not a defect this audit is flagging**, but a real nuance
  for anyone using this endpoint as a Compose `healthcheck:` `test:`
  command: a plain `curl -f http://localhost:8080/health` would report
  "healthy" even when the body says `waha.reachable: false`, since curl's
  `-f` flag only reacts to the HTTP status, not the JSON body. A
  Docker-level healthcheck against this endpoint can therefore only ever
  answer **"is the Express process up and accepting connections,"** not
  **"is the BFF's WAHA link healthy"** — which is arguably the *correct*
  scope for a container-startup-order healthcheck anyway (the same
  narrow scope Phase B's own Redis healthcheck has), not a reason to
  invent a new endpoint.
- **Is a Docker healthcheck appropriate here?** **Not clearly needed**
  in this design specifically, unlike Phase B's Redis healthcheck (which
  exists because three *other* services `depends_on` it) — in this
  BFF-only slice, nothing yet declared in this audit `depends_on` the
  BFF being ready (WAHA is external, Section 9's frontend hop is
  browser-side, not container-to-container). **Not invented or mandated
  by this audit** — left as an implementation-time judgment call
  (Section 15), using the existing `/health` endpoint if one is ever
  added, never a new one.

---

## 9. Future Frontend Interaction

**CONFIRMED FROM CURRENT CODE**, re-read `frontend/src/lib/config.ts`
this task: `bffBaseUrl: import.meta.env.VITE_BFF_BASE_URL ?? ''` — a
Vite build-time-injected, `VITE_`-prefixed variable, consumed by
**browser-side** code (Vite's own documented behavior for this prefix,
and consistent with every other `VITE_`-prefixed variable already
audited in this project, e.g. `VITE_DJANGO_BASE_URL`).

**Contract for the future frontend container**: the browser talks
directly to the BFF's **published host port** (`8080`), exactly as it
already does in the current bare-host workflow — **not** through Vite's
own dev server as a proxy, and **not** via any Docker-network hop,
since the request never leaves the browser's own network stack until it
hits `localhost:8080` (or whatever published address `VITE_BFF_BASE_URL`
names). This directly mirrors the same "browser reachability is
independent of Compose-project membership" finding the Phase B design
report already established for Django — re-confirmed here for BFF by
reading the actual frontend source rather than assuming the pattern
repeats. **Consequence**: a future frontend development container does
**not** need to share a Compose project with the BFF development
container for this reason alone — the same two-file,
location-scoped structure (Section 11) remains fully sufficient.

---

## 10. Production vs. Development Comparison

| | Production (`infrastructure/tencent/docker-compose.yml`) | Development (proposed, not yet created) |
|---|---|---|
| Process | `node dist/index.js` (compiled) | `tsx watch src/index.ts` (source, hot-reload) |
| Image | Final stage (no devDependencies) | `build`-stage target, or `Dockerfile.dev` (Section 3, undecided) |
| Source | Baked into image at build time | Bind-mounted, live-editable |
| `DJANGO_INTERNAL_BASE_URL` | Real NetBird/LAN address | `http://host.docker.internal:8000` (Section 6) — **same shape**, an explicit URL either way |
| `WAHA_BASE_URL` | `http://waha:3000` (Docker-network, same Compose project) | A real, external, already-running WAHA instance's URL (Section 5) |
| `INTERNAL_SERVICE_KEY` | Production's real shared secret | A separate, dev-only shared value (Section 7) — intentionally different, not a leak |
| Port | Published `8080:8080` | Published `8080:8080` (recommended, Section 8) — same |
| Healthcheck | None | None mandated by this audit (Section 8) — same, unless a later implementation adds one |

**Intentional differences**: process/image (dev needs source, not a
frozen build), `WAHA_BASE_URL`/`INTERNAL_SERVICE_KEY` values (different
environments, different real dependencies/secrets — expected).
**Unavoidable differences**: none identified beyond the intentional
ones above. **Accidental/risky differences**: **none found** — the one
difference that *could* have been accidental (BFF→Django transport
shape) is, per Section 6, not actually different in kind between
environments at all, only in the specific hostname value — this is a
genuinely clean result, not a gap glossed over.

---

## 11. Recommended Development Architecture

**PROPOSED DESIGN, answering Section 8's A/B/C comparison directly:**

**Option B — a separate `infrastructure/development/tencent.yml`,
alongside the existing, unmodified `office.yml`.** Not Option A (folding
BFF into `office.yml`).

**Reasoning, grounded in re-verified repository structure, not
convenience**:
- `docs/14-REPOSITORY-STRUCTURE.md`'s ownership statement
  ("infrastructure = deployment... A task scoped to one component
  should not modify another") applies to *development* exactly as it
  already applies to production — this audit finds no basis to treat
  development as exempt from it, and the Phase B design report already
  established this reasoning once (re-affirmed here, not re-derived from
  scratch).
- **Production itself already groups BFF with frontend** (and WAHA), not
  with backend/Celery/Redis — `infrastructure/tencent/docker-compose.yml`
  is the existing, real precedent for "BFF's location is Tencent, not
  Office." Folding BFF into `office.yml` would contradict that
  established grouping for no offsetting benefit this audit could find.
- **Phase B's own file is literally named `office.yml`** — a name that
  is only accurate if it stays Office-scoped. Adding BFF to it would
  make the file's own name misleading, a concrete (if soft) signal that
  Option A is the wrong direction.
- **Section 9 confirms no networking requirement forces the fusion**:
  the browser reaches BFF via a published port regardless of Compose
  project, and BFF reaches Django via an explicit URL regardless of
  Compose project (Section 6) — there is no *technical* dependency
  linking BFF's container lifecycle to backend's.

**"The current Phase B structure should be treated as established
unless there is a concrete reason to change it"**: this audit finds
**no such reason** — `office.yml` remains correct, unmodified, exactly
as Phase B left it; the recommended path is **additive** (a new
`tencent.yml`), not a revision of Phase B.

**`infrastructure/development/` would eventually contain**:
```
infrastructure/development/
├── office.yml            # Phase B — unchanged
├── .env.example            # Phase B — unchanged (Office-scoped)
├── tencent.yml            # NOT YET CREATED — this audit's subject
└── <tencent env file>      # NOT YET CREATED — naming undecided, Section 5/15
```

---

## 12. Files That Would Eventually Change

**Not created or modified by this audit** — listed for planning only:

- New: `infrastructure/development/tencent.yml` (BFF service; frontend
  added later, per a separate, not-yet-audited slice).
- New: a Tencent-scoped development env template (exact filename
  undecided, Section 5/15) — **not** merged into Phase B's existing
  `infrastructure/development/.env.example`.
- Possibly new: `bff/Dockerfile.dev` — **only if** Section 3's
  Dockerfile-vs-`--target build` decision goes that way; otherwise no
  new Dockerfile-related file at all.
- **No existing file requires modification**: `bff/Dockerfile`,
  `bff/package.json`, `bff/.env.example`,
  `infrastructure/tencent/docker-compose.yml`,
  `infrastructure/tencent/.env.example`,
  `infrastructure/development/office.yml`,
  `infrastructure/development/.env.example` — none of these need to
  change for this design to be implemented.

---

## 13. Dependency-Ordered Implementation Plan (Not Implemented)

- **C1 — Dockerfile decision**: `--target build` against the existing,
  unmodified `bff/Dockerfile`, or a new `bff/Dockerfile.dev` (Section 3).
  Independent of every other step; blocks C3's `build:` configuration
  specifically.
- **C2 — Environment design**: resolve the naming question (Section 5),
  then write the new Tencent-scoped development env template (variables
  per Section 5's inventory, values per Section 10's comparison table).
  Independent of C1.
- **C3 — Compose integration**: create `infrastructure/development/tencent.yml`
  (`bff` service only, per Section 11 — frontend is out of this slice's
  scope entirely), using C1's chosen build approach and C2's env file.
  Depends on C1 and C2.
- **C4 — Networking**: set `DJANGO_INTERNAL_BASE_URL=http://host.docker.internal:8000`
  in the new env file (Section 6) — folded into C2/C3, not a separate
  file change, listed here only because the task's own category list
  names it separately.
- **C5 — Hot reload**: `command: npm run dev` (or the equivalent `tsx
  watch` invocation directly) + bind mount + anonymous `node_modules`
  volume (Section 4) — folded into C3's service definition.
- **C6 — Verification**: `docker compose config`, build, `up`, `curl
  http://localhost:8080/health`, confirm a BFF→Django internal call
  succeeds against Phase B's already-running `office.yml` stack (both
  `.env` files populated with the same `INTERNAL_SERVICE_KEY`, Section 7)
  — **not performed by this audit**, design/read-only per the task's
  explicit constraint.

---

## 14. Risks and Mitigations

- **`INTERNAL_SERVICE_KEY` duplication across two separate dev `.env`
  files** (Section 7) — the same manual-sync risk the existing bare-host
  workflow already has (a typo or left-empty value fails closed with a
  `403`, per `README.md`'s own documented diagnostic). Not worsened by
  Dockerizing, not eliminated by it either — an inherent property of
  this project's static-shared-secret design, out of this audit's scope
  to change.
- **`host.docker.internal` Linux portability** (Section 6) — same
  caveat already documented for Phase B's PostgreSQL connectivity;
  applies identically here for the BFF→Django hop. Named, not silently
  assumed universal.
- **Env-file naming collision risk** (Section 1/5) — concrete, would
  cause real confusion or an accidental overwrite if not resolved before
  C2/C3 are implemented. The one genuinely new risk this audit surfaces.
- **`/health`'s always-200 shape limits its usefulness as a Compose
  healthcheck** (Section 8) — not a defect, but worth knowing before
  anyone reaches for it as a `depends_on: condition: service_healthy`
  gate expecting it to reflect WAHA's own reachability.
- **No risk found in the BFF→Django networking design itself** (Section
  6/10) — the code-level re-verification this task performed found the
  recommended approach requires no code change and introduces no new
  transport assumption relative to every other environment.

---

## 15. USER DECISIONS REQUIRED

1. **`Dockerfile.dev` vs. `--target build`** for the BFF (Section 3) —
   carried forward from the earlier general Docker audit, still
   genuinely open, no new evidence in this task tips it either way.
2. **Tencent-scoped development env file naming** (Section 5/1) — e.g.
   `infrastructure/development/tencent.env.example`, or some other
   scheme — must be decided before C2/C3 (Section 13) are implemented,
   to avoid colliding with Phase B's existing
   `infrastructure/development/.env.example`. **This audit does not
   propose renaming Phase B's own file** — that would be a Phase B
   change, out of this task's scope per its own instruction not to touch
   Phase B without a concrete correctness issue (this is a
   forward-compatibility naming question, not a defect in Phase B
   itself).
3. **Whether a BFF Docker healthcheck is worth adding at all** (Section
   8), given nothing in this design currently `depends_on` BFF's
   readiness — a genuinely optional, low-stakes call, not required for
   this slice to work.
4. **Confirm the dev-local `INTERNAL_SERVICE_KEY` value is acceptable as
   a separate secret from production's** (Section 7) — this audit
   recommends yes (matches existing project convention for every other
   secret/keypair), but flags it for explicit confirmation since it's a
   security-adjacent decision, not a purely technical one.

---

## Explicit Stop Condition

**No Dockerfile, Compose file, source file, `package.json`/`package-lock.json`,
`.env`/`.env.example`, or database configuration was created or modified
producing this report.** No image was built, no container was started,
no HTTP request was made, no WhatsApp message was sent. Phase A and
Phase B remain exactly as they were, unmodified and unrevisited beyond
read-only integration checks.

**STOP.** Phase C is not implemented. No Dockerfile or Compose file was
created. No source or configuration was modified. Not proceeding to
Phase D (frontend development Docker) or any Phase 9 work. Awaiting your
decisions in Section 15.
