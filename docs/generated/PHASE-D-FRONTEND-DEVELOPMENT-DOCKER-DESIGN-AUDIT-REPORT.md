# Phase D — Frontend Development Docker — Design Audit (Read-Only)

**Scope.** Design/read-only audit only, following Phase A (production
`RECONCILIATION_EXECUTOR`), Phase B (`infrastructure/development/office.yml`),
and Phase C (`infrastructure/development/tencent.yml`, BFF-only), all
complete and unmodified. No Dockerfile, Compose file, `.env`, source
code, dependency, database, or runtime state was created or modified.
No container was started. Every claim below was verified directly
against current source this task — including one claim (Section 8)
confirmed by directly inspecting `frontend/node_modules/vite`'s actual
installed, compiled code, not merely assumed from documentation or
carried over from Phase C's structurally similar finding.

---

## 1. Current Frontend Docker Architecture

**CONFIRMED FROM CURRENT CODE, re-read in full this task:**

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

Two stages: `build` (full `npm install` — dependencies **and**
devDependencies, including `vite` itself, `@vitejs/plugin-react`,
`typescript` — then `tsc -b && vite build`), then a final `nginx:1.27-alpine`
stage that copies only the static `dist/` output. **The final stage has
no Node.js runtime at all** — it cannot run `vite`, `npm`, or anything
JavaScript-based, in any form. This is the **same structural shape**
Phase C already found and resolved for `bff/Dockerfile` (production
stage lacking dev tooling, `build` stage already having everything
needed) — re-confirmed here for `frontend/Dockerfile` by direct read,
not assumed to repeat by analogy alone.

No `infrastructure/development/frontend.yml` or any frontend-scoped
development Compose file exists yet — confirmed by directory listing
(`infrastructure/development/` contains `office.yml`, `.env.example`,
`tencent.yml`, `tencent.env.example` only, all Phase B/C, re-read in
full this task, byte-identical to their completed/verified state —
Section 6).

---

## 2. Relevant Source/Config Findings

**CONFIRMED FROM CURRENT CODE:**

- **`frontend/package.json`**: `"dev": "vite"` (no flags — unlike BFF's
  `dev` script, there is no `--env-file-if-exists` or similar wrapper to
  reason about bypassing). `"vite": "^8.3.0"`, `"@vitejs/plugin-react": "^6.1.1"`.
  No `nodemon`, no `chokidar` as a direct dependency (Section 8 covers
  what this actually means).
- **`frontend/vite.config.ts`**: `defineConfig({ plugins: [react()] })` —
  **no `server` block at all**. Confirmed, re-verified this task: no
  `server.host`, no `server.proxy`, no `server.watch`, no `server.hmr`
  configuration exists. The "`vite.config.ts` lacks `server.host`"
  finding from every prior Docker audit in this session **is still
  true, unchanged**.
- **`frontend/src/lib/config.ts`**: reads exactly three
  `VITE_`-prefixed variables — `VITE_BFF_BASE_URL`, `VITE_DJANGO_BASE_URL`,
  `VITE_WAHA_SESSION_NAME` — via `import.meta.env`, Vite's own
  build/dev-time static-replacement mechanism (browser-bundle-baked, not
  a server-side proxy or runtime lookup).
- **Every API call traced to a full, absolute URL** (grepped
  `frontend/src/lib/*.ts` this task): `bffApi.ts` (`${config.bffBaseUrl}/health`,
  `/api/sessions/...`), `djangoApi.ts` (`${config.djangoBaseUrl}/api/...`),
  `auth.ts` (`${config.djangoBaseUrl}/api/auth/login/`) — **no relative
  paths, no Vite dev-server proxy usage anywhere**. Confirmed by the
  complete absence of a `server.proxy` block in `vite.config.ts` (above)
  — if a proxy were in use, these would be relative paths (`/api/...`)
  routed through Vite's own dev server; they are not.
- **`frontend/.env.example`**: `VITE_BFF_BASE_URL=http://localhost:8080`,
  `VITE_DJANGO_BASE_URL=http://localhost:8000` — **already the exact
  values Phase B (`8000:8000`) and Phase C (`8080:8080`) publish to the
  host**. No change needed to these two values for Docker development —
  they were already correct for a Docker-based backend/BFF before this
  audit began.

**Conclusion, stated plainly**: the browser resolves the BFF/Django URLs
**itself**, from values Vite baked into the served JavaScript at
dev-server-start time, and **fetches them directly** — never through a
proxy, never through Docker's internal DNS. `Browser → localhost:8080 →
BFF` (the task's own framing) is confirmed to be **exactly** what
happens today, and is unaffected by whether the frontend process itself
runs on bare host or inside a container — only *where the frontend's own
dev server is reachable from* changes, not how the browser reaches BFF/Django.

---

## 3. Current Production Topology Relationship

**CONFIRMED FROM CURRENT CODE**, re-read `infrastructure/tencent/docker-compose.yml`
in full this task:

```yaml
services:
  frontend:
    build: { context: ../../frontend }
    ports: ["80:80"]
    depends_on: [bff]
    restart: unless-stopped
  bff:
    build: { context: ../../bff }
    env_file: [.env]
    ports: ["8080:8080"]
    depends_on: [waha]
    restart: unless-stopped
  waha:
    image: devlikeapro/waha:gows
    ...
```

**Production already groups `frontend` + `bff` + `waha` in one file** —
this is the existing, real precedent for Tencent-location ownership,
unchanged since every prior audit in this session. `depends_on: [bff]`
here governs container **start order** only (Compose's default,
no `condition:`) — it has no bearing on the browser's own
direct-fetch behavior (Section 2), since the browser is not a container
and never consults Docker's `depends_on` graph.

---

## 4. Proposed Phase D Architecture

**PROPOSED DESIGN.** Add a `frontend` service to the **existing**
`infrastructure/development/tencent.yml` (Phase C), rather than creating
a new file — Section 6 gives the full reasoning. High-level shape:

```yaml
services:
  bff:
    # unchanged from Phase C
  frontend:
    build:
      context: ../../frontend
      target: build
    command: npx vite --host
    env_file:
      - tencent.env
    volumes:
      - ../../frontend:/app
      - /app/node_modules
    ports:
      - "5173:5173"
```

(Sketch only — this audit does not create or modify any file.)

**No shared Docker network requirement between `frontend` and `bff`**
(Section 9) — they may end up in the same Compose project for
**ownership/grouping reasons** (Section 6), but nothing about their
runtime communication depends on it, since the browser — not the
`frontend` container — is what talks to `bff`.

---

## 5. Exact Files That Would Need to Change During Implementation

- **New**: nothing — no new Compose file is proposed (Section 6).
- **Modified**: `infrastructure/development/tencent.yml` (add the
  `frontend` service — an anticipated extension, not a correction; Phase
  C's own implementation report explicitly named "frontend added later,
  per a separate, not-yet-audited slice" as deferred, not rejected).
- **Modified**: `infrastructure/development/tencent.env.example` (add
  `VITE_BFF_BASE_URL`, `VITE_DJANGO_BASE_URL`, `VITE_WAHA_SESSION_NAME`
  — Section 10's reasoning).
- **Modified, the one unavoidable application-source change**:
  `frontend/vite.config.ts` — add `server: { host: true }` (Section 8/13).
  Confirmed necessary, not optional: without it, Vite's dev server binds
  to `localhost` inside the container, unreachable via any published
  port. This audit does **not** make this change — it is named here,
  per the task's own instruction, as a concrete, identified,
  not-yet-implemented prerequisite.
- **Not modified**: `bff/Dockerfile`, `frontend/Dockerfile`, any
  production Compose file, `infrastructure/development/office.yml`,
  `infrastructure/development/.env.example`, Phase A/B/C's own
  deliverables in any other respect.

---

## 6. Should Frontend Be Added to `tencent.yml`, or Use a Separate Compose File?

**Recommendation: add to the existing `tencent.yml`.** The task's own
caution — "do not automatically put frontend and BFF into the same
Compose project just because they communicate with each other" — is
correct and is **not the reasoning used here**. Section 2 already
establishes that frontend↔BFF communication happens entirely
browser-side, with **zero dependency on shared Compose-project
membership** — so "they communicate" is explicitly **not** why this
audit recommends combining them.

**The actual reasoning is ownership/location, mirroring an existing,
real precedent**: production's own `infrastructure/tencent/docker-compose.yml`
already groups `frontend` + `bff` + `waha` together, as one location
(Tencent), for the same reason `infrastructure/office/docker-compose.yml`
groups `backend` + `celery-worker` + `celery-beat` + `redis` together as
Office. Phase B/C's own `infrastructure/development/office.yml` and
`tencent.yml` already mirror that exact location split. Frontend is
Tencent-located in every existing definition of "location" this
repository uses — adding it to `tencent.yml` **extends an established
grouping**, it does not invent a new one, and does not blur the
Office/Tencent boundary the way folding BFF into `office.yml` would have
(a combination this session's earlier Phase C design audit explicitly
rejected, for the opposite reason: because BFF's location is Tencent,
not Office).

**A separate `frontend.yml`** would be a legitimate, working
alternative — nothing about it would be *wrong* — but it would
re-introduce exactly the fragmentation-by-component pattern this whole
Docker migration has consistently rejected at every prior phase
(Phase A/B/C's general Docker audit's Section 15, re-affirmed by Phase
C's own Section 11), without a concrete, new justification this audit
could find. **Not chosen.**

**This is presented as a confident recommendation, not a
`USER DECISIONS REQUIRED` item** — the precedent (production's own file
shape) is unambiguous and Phase C's own report already anticipated this
exact continuation.

---

## 7. Dockerfile Strategy

**CONFIRMED FROM CURRENT CODE (Section 1)**: the production final stage
has no Node.js runtime — a command override alone cannot make it run
`vite`. Two real options, same shape as Phase C's BFF decision:

1. **`build.target: build`** against the existing, **unmodified**
   `frontend/Dockerfile` — the `build` stage already runs a full `npm
   install` (including `vite`, `@vitejs/plugin-react`, `typescript`)
   before its own `RUN npm run build` step. That build step's `dist/`
   output would simply go unused in dev (the dev server serves from
   `src/`, not `dist/`) — the same small, harmless inefficiency Phase C
   already accepted for BFF.
2. **`frontend/Dockerfile.dev`** — a new file, avoiding the wasted
   build step, at the cost of a second file to keep in sync.

**Recommendation, for consistency with the just-verified, working Phase
C pattern**: **option 1, `build.target: build`**, unless implementation
reveals a concrete reason it doesn't work for frontend specifically (none
found by this audit — the two Dockerfiles have structurally identical
two-stage shapes). **Not escalated to `USER DECISIONS REQUIRED`** — same
low-stakes, either-way-valid character as Phase C's equivalent decision,
where this audit defers to the already-established pattern rather than
re-opening a settled style question.

---

## 8. Hot-Reload Strategy

**CONFIRMED FROM CURRENT CODE, including one claim verified by direct
inspection of the installed package's actual compiled code (not
assumed):**

- **Vite's dev server already provides hot module replacement (HMR)
  natively** — `npm run dev` (`vite`) is already the project's own dev
  workflow; no new tool or dependency is needed for reload itself.
- **Bind mount is safe**: same reasoning as Section 15 of the earlier
  general Docker audit and Phase C's own finding — the image's installed
  `node_modules` lives at `/app/node_modules`, outside the source tree a
  bind mount would otherwise shadow; an anonymous volume at
  `/app/node_modules` (layered over the `../../frontend:/app` bind
  mount) protects it, identical to the pattern already proven working
  for BFF in Phase C.
- **Does Vite need polling on Docker Desktop/Windows, the way `tsx`
  did?** `frontend/package-lock.json` lists **no top-level `chokidar`
  dependency** — a real difference from `bff`'s dependency tree, which
  does list `tsx` (and transitively depends on a file-watching
  mechanism). This could have meant Vite uses a different,
  non-chokidar-based watcher unaffected by Phase C's finding. **Checked
  directly rather than assumed**: `frontend/node_modules/vite/dist/node/chunks/node.js`
  (the actual installed package's compiled code, read this task) **does
  contain literal `CHOKIDAR_USEPOLLING` and `usePolling` references** —
  confirming Vite **vendors/bundles a chokidar-compatible watcher
  internally**, rather than listing it as a separate top-level
  `package.json` dependency (which is why the lockfile search alone was
  inconclusive, and why this audit went one level deeper to check the
  actual installed code instead of stopping at a plausible-looking
  negative result).
- **Conclusion**: Vite's dev-server watcher **does** respect the same
  `CHOKIDAR_USEPOLLING` environment variable Phase C already proved
  fixes this exact class of Docker-Desktop-on-Windows bind-mount
  file-change-detection gap for `tsx`. **This audit recommends the same
  fix, at the same layer (a Compose `environment:` entry, zero new
  dependency, zero source change)** — not a `vite.config.ts`
  `server.watch.usePolling` addition, specifically to keep the one
  unavoidable source change (Section 13) as small as possible, matching
  Phase C's own minimal-source-footprint precedent.
- **Caveat, stated honestly**: this audit did **not** start a container
  to confirm Vite's HMR actually restarts/updates correctly with this
  variable set (the task's explicit read-only constraint forbids it) —
  the `CHOKIDAR_USEPOLLING` support is confirmed to exist in the
  installed code; whether it fully resolves HMR specifically (as opposed
  to just the underlying file-watch primitive) should be the **first**
  thing verified live during Phase D implementation, exactly as Phase
  C's own report documented discovering and fixing this live rather than
  assuming it upfront.

**No new dependency (`watchdog`, `nodemon`, or otherwise) is proposed or
needed** — satisfies the task's explicit constraint directly.

---

## 9. Browser → BFF Networking Strategy

**CONFIRMED FROM CURRENT CODE (Section 2)** — restated once here since
the task lists it as its own required section:

The browser reaches BFF via `VITE_BFF_BASE_URL` (a full,
absolute, browser-visible URL, baked in by Vite at dev-server-start
time), and reaches Django via `VITE_DJANGO_BASE_URL` the same way.
**Neither depends on Docker networking, Compose-project membership, or a
shared network between `frontend` and `bff`/`backend` containers** —
the browser is not a Docker entity and only ever sees **published host
ports**. This is a direct re-confirmation, from frontend's own source
this time, of the same principle Phase B/C's design audits already
established for the Django/BFF side.

**Consequence for this design**: `frontend`'s only Docker-networking
requirement is its **own** published port (`5173:5173`, Section 11) —
it needs no `depends_on`, no shared network, and no explicit
`host.docker.internal`-style URL of its own, unlike `bff`'s
`DJANGO_INTERNAL_BASE_URL` (a **server-side**, container-to-container
call, fundamentally different in kind from the browser's own direct
fetches).

---

## 10. Environment-File Strategy

**PROPOSED DESIGN, directly following from Section 6's recommendation**:
since `frontend` would join the **existing** `tencent.yml`, its
variables belong in the **existing** `infrastructure/development/tencent.env.example`
(Phase C) — **not** a new `frontend.env.example` file. Concretely, three
new lines would be added to that file: `VITE_BFF_BASE_URL`,
`VITE_DJANGO_BASE_URL`, `VITE_WAHA_SESSION_NAME` — the exact same three
variables `frontend/.env.example` already documents, no others invented.

**Values, not guessed**: `VITE_BFF_BASE_URL=http://localhost:8080` and
`VITE_DJANGO_BASE_URL=http://localhost:8000` are safe to pre-fill in the
template (matching `frontend/.env.example`'s own existing defaults
exactly) — these are the browser-visible ports Phase B/C already publish,
not secrets, not guesses. `VITE_WAHA_SESSION_NAME` stays empty, matching
`frontend/.env.example`'s own convention (developer-specific, not a
secret, but not a value this audit should invent either).

**This does not "silently rename" anything** (the task's explicit
concern) — `.env.example` (Office, Phase B) and `tencent.env.example`
(Tencent, Phase C) both keep their existing names; only `tencent.env.example`'s
**contents** would grow, consistent with `frontend` joining `tencent.yml`
rather than a new file being introduced.

---

## 11. Port Strategy

**CONFIRMED FROM CURRENT CODE**: no `--port` flag in `frontend/package.json`'s
`dev` script — Vite's own default dev port, `5173`, applies. This is
**already** the value referenced throughout the existing stack: `bff/.env.example`'s
`CORS_ALLOWED_ORIGIN=http://localhost:5173`,
`infrastructure/tencent/.env.example`'s equivalent, and
`infrastructure/development/tencent.env.example`'s
`CORS_ALLOWED_ORIGIN=http://localhost:5173` (Phase C, re-read this task,
unchanged) — all already assume port `5173`. **Recommendation: publish
`5173:5173`, unchanged from Vite's own default** — changing it would
require updating BFF's CORS configuration too, an unnecessary ripple
with no stated benefit. Production's own frontend port (`80:80`,
Nginx) is irrelevant here — that's a different process (Nginx serving a
static build) with a different, already-documented port; development's
`5173` and production's `80` are not the same "slot" and should not be
conflated.

---

## 12. Healthcheck Decision

**Recommendation: no healthcheck.** Directly following the task's own
instruction not to add one "merely for symmetry": nothing in this
design `depends_on` the frontend container's readiness (Section 9 — the
browser accesses it directly, never through another container's
`depends_on` graph), and Vite's dev server has no established,
documented health-check-shaped endpoint the way BFF's `/health` or
Django's `/api/health/` already do (Section 8 of the Phase C design
audit made the same "don't invent one" judgment for a comparable case).
Adding one here would be pure symmetry with `bff`'s healthcheck (Phase
C), not a response to any real startup-order risk this audit could
identify.

---

## 13. Windows/Docker Desktop Considerations

Consolidating Sections 1/8's findings, as the task's own Section 13
requires:

- **`server.host` is a hard requirement**, not a Windows-specific one —
  Vite's dev server binds to `localhost` by default on *any* platform;
  inside a container, that makes it unreachable via a published port
  regardless of host OS. Confirmed unchanged from every prior audit in
  this session (Section 1).
- **File-change detection likely needs polling on Docker Desktop for
  Windows specifically** — Section 8's confirmed finding
  (`CHOKIDAR_USEPOLLING` support exists in Vite's own bundled code,
  matching the exact mechanism Phase C already proved necessary for
  `tsx` on this same host). This audit could not live-verify Vite's HMR
  specifically without violating the read-only constraint — flagged as
  the first thing to confirm during implementation.
- **`host.docker.internal`** is not relevant to `frontend` the way it
  was to `bff` (Section 9) — `frontend` has no server-side call to
  Django/BFF at all; this consideration is specific to `bff`'s own
  already-implemented `DJANGO_INTERNAL_BASE_URL` (Phase C), unaffected
  by Phase D.

---

## 14. Risks and Trade-Offs

- **`CHOKIDAR_USEPOLLING`'s effect on Vite's HMR specifically is
  unverified** (Section 8) — confirmed to exist as a supported switch in
  Vite's own code, but not confirmed to fully resolve HMR (as opposed to
  just file-watch detection) without live testing, which this read-only
  audit could not perform. The single largest open item for
  implementation to verify first.
- **Polling's usual CPU/battery cost** — same, already-accepted
  trade-off Phase C's implementation report already documented for BFF;
  applies identically here, not a new cost category.
- **Extending `tencent.yml`/`tencent.env.example` (Phase C's own files)
  rather than leaving them untouched** — a deliberate, anticipated
  continuation per Phase C's own report language, not treated by this
  audit as "modifying Phase C" in the sense the task's constraints
  caution against (which is about *unplanned*, *unjustified* changes,
  not an explicitly-deferred, already-scoped next step).
- **`node_modules` anonymous-volume staleness after a `package.json`
  change** — same known, already-documented limitation as both Phase B
  and Phase C; requires an explicit image rebuild, not automatic.
- **No risk found in the browser↔BFF networking design** — Section 9's
  re-confirmation (this time from frontend's own source) found no gap,
  matching Phase B/C's own equivalent, clean findings for their
  respective hops.

---

## 15. Verification Plan for Implementation (Not Performed by This Audit)

1. `docker compose -f infrastructure/development/tencent.yml config` —
   valid syntax after the `frontend` service is added.
2. Build `frontend` (`--target build`, Section 7).
3. Start the stack; confirm the `frontend` container is `Up`.
4. **First priority**: make a safe, non-functional source change (e.g.
   a comment, mirroring Phase C's own verification method) and confirm
   Vite's HMR actually picks it up with `CHOKIDAR_USEPOLLING=true` set —
   directly resolving Section 14's largest open risk.
5. Confirm the dev server is reachable from the host at
   `http://localhost:5173` (requires Section 5's `vite.config.ts`
   change to already be in place).
6. Open the page in a browser and confirm it successfully calls BFF
   (`http://localhost:8080`) and Django (`http://localhost:8000`) —
   both already-running per Phase B/C — end-to-end, completing the full
   `Browser → Frontend → BFF → Django` chain across three independent
   Compose projects for the first time.
7. Run `frontend`'s existing `npm run lint`/`npm run build` (typecheck
   via `tsc -b`) inside the container, mirroring Phase C's verification
   depth for BFF.
8. No WhatsApp send, no production endpoint call, no database
   migration — same boundaries every prior phase in this session has
   already observed.

---

## 16. USER DECISIONS REQUIRED

Given how directly most of this audit's questions were resolvable from
source and established precedent, only one genuine, materially-relevant
open item remains:

1. **Confirm `CHOKIDAR_USEPOLLING` actually resolves Vite's HMR
   end-to-end** (Section 8/14) — this audit confirmed the underlying
   mechanism exists in Vite's own installed code, but could not verify
   it live under this task's read-only constraint. **Not a design
   choice requiring your preference** — a verification step Phase D's
   own implementation should perform first, before anything else, per
   Section 15's plan. Flagged here only so it isn't mistaken for an
   already-confirmed fact.

Everything else in this report — extending `tencent.yml` rather than a
new file (Section 6), `build.target: build` over `Dockerfile.dev`
(Section 7), no healthcheck (Section 12), port `5173` (Section 11), and
the environment-file strategy (Section 10) — was derived with enough
confidence from source and existing precedent to proceed directly, per
the task's own instruction to recommend rather than defer when the
evidence supports it.

---

## Summary

**No Dockerfile, Compose file, `.env`, source code, dependency,
database, or runtime state was created or modified in producing this
report. No container was started.** Phase A, B, and C remain exactly as
verified/implemented, re-confirmed unchanged this task.

Frontend's own source confirms — independently, not merely by analogy —
the same principle already established for BFF/Django: the browser
reaches every backend service via a full, absolute, Vite-baked URL,
never through Docker networking or a dev-server proxy (none exists).
This means `frontend`'s Docker requirements are narrower than `bff`'s:
no `host.docker.internal`-style connectivity concern, no internal
service authentication, only its own published port and a working dev
server. The recommended design extends the **existing**
`infrastructure/development/tencent.yml` and `tencent.env.example`
(Phase C) with a `frontend` service, rather than creating a new file —
grounded in production's own existing Tencent-location grouping, not in
"they talk to each other" (which this audit explicitly does not use as
its reasoning, per the task's own caution). The BFF Dockerfile's
`build`-stage-reuse pattern (Phase C) transfers directly, unmodified.
**The one unavoidable application-source change is `frontend/vite.config.ts`'s
missing `server.host`** — identified, not implemented, per the task's
explicit instruction to stop and report rather than silently make it. A
second, genuinely new finding — confirmed by directly inspecting Vite's
installed compiled code rather than assumed — is that Vite's bundled
watcher **does** support the same `CHOKIDAR_USEPOLLING` mechanism Phase
C already proved fixes Docker-Desktop-on-Windows file-watch propagation
for `tsx`, at zero new dependency cost. **Awaiting nothing but
confirmation of the one flagged verification item (Section 16) — no
implementation was performed, and this audit stops here.**
