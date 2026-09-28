# Phase 14 — M6: Rollback / Image Versioning — Audit Report

**Read-only audit.** No file was changed, no image was built/pushed, no
container was started for anything other than transient, isolated
`docker compose config`/`--images` checks against throwaway scratch
copies (never the real repo state, nothing left running). Blast, WAHA
session logic, and reconciliation were not examined or touched — out of
this item's scope. Nothing committed, nothing pushed, no production
touched.

---

## 1. CURRENT STATE

**Dockerfiles** (`backend/Dockerfile`, `bff/Dockerfile`, `frontend/Dockerfile`):
- All three `FROM` a **tag**, never a digest: `python:3.12-slim`,
  `node:22-alpine` (×2, build+bff runtime stages), `nginx:1.27-alpine`.
  These are floating tags — the same tag name can (and does, upstream)
  point at a different underlying image over time as base images get
  security-patched.
- `backend`: `pip install -r requirements.txt` — every dependency is
  pinned to an exact version (`Django==4.2.23`, etc., confirmed all 11
  lines), but there is no hash-pinning (`--hash=`), so this is
  version-reproducible but not byte-for-byte cryptographically verified.
- `bff`/`frontend`: `npm install` (not `npm ci`) against a committed
  `package-lock.json`. `npm install` *can* still touch/update the
  lockfile if `package.json` and the lockfile disagree; `npm ci` would
  refuse and fail instead — a minor reproducibility gap, not part of
  M6's own scope but adjacent to "consistent versioning."
- None of the three application Dockerfiles declare a version label of
  any kind (no `LABEL version=`, no build-arg-derived tag baked into the
  image itself).

**`infrastructure/tencent/docker-compose.yml` / `infrastructure/office/docker-compose.yml`**:
- `frontend`, `bff` (tencent) and `backend`, `celery-worker`,
  `celery-beat` (office) all use `build: context: ...` with **no
  `image:` field at all**. Confirmed directly via `docker compose config
  --images` on a throwaway copy of `office`'s file: Compose auto-names
  these `office-backend`, `office-celery-worker`, `office-celery-beat`
  (implicit `:latest`) — one separate local image tag per **service**,
  not per build context.
- **`backend`, `celery-worker`, and `celery-beat` build from the
  identical `../../backend` context/Dockerfile**, yet get three
  separate image names. `docker compose build` (no service argument)
  rebuilds all three consistently today, but nothing prevents someone
  running `docker compose build backend` alone — the other two would
  then silently keep running an older image while `backend` runs a
  newer one.
- Every `docker compose build`/`up --build` **overwrites the same
  local tag in place**. The previous image becomes untagged
  (`<none>:<none>`) — still on disk until something removes it
  (`docker image prune`, `docker system prune`, or simply running out of
  disk), but no longer *addressable by name*. There is no `docker tag`
  step anywhere that would preserve a reachable "previous version."
- `waha`: `image: devlikeapro/waha:gows` — `gows` is the WAHA *engine*
  variant name (decision #1, `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`),
  not a version — a mutable tag; `docker compose pull` can silently
  fetch a newer WAHA release under the same tag name.
- `reverse-proxy`: `image: nginx:1.27-alpine` — a minor-version tag,
  more stable than `latest` but still not a digest; alpine patch
  releases roll forward under the same tag.
- `redis`: `image: redis:7-alpine` — same class of tag as above.
- **`docker compose pull` currently does nothing for this project's own
  code** — `frontend`/`bff`/`backend`/`celery-worker`/`celery-beat` have
  no registry image to pull from; the only thing `pull` would affect is
  `waha`/`nginx`/`redis`'s upstream base images. The only way this
  project's own code gets into a running container today is
  `docker compose build` (from whatever source is checked out on the
  host at that moment).
- Named volumes (`waha_sessions`, `waha_media`) are **not** deleted by a
  normal `docker compose down`/`up` cycle — only `docker compose down -v`
  removes them. Relevant to rollback safety: a rollback must never pass
  `-v`.

**Docs**: `docs/08-DEPLOYMENT.md`, `docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`
describe *what* runs where, not *how* a release/rollback is performed —
neither mentions tagging, versioning, or a rollback procedure at all.
`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`'s "Open" list has no entry for
this either.

**No CI/CD anywhere**: confirmed no `.github/workflows/`, no
`.gitlab-ci.yml`, no `Jenkinsfile`, nothing under any other common CI
path. **No container registry is referenced anywhere in this
repository** — grepped for Docker Hub/GHCR/ECR/Tencent Container
Registry patterns project-wide (excluding the unrelated `.kilo/`
worktree); zero hits. **No git tags exist** (`git tag -l` — empty).

---

## 2. FINDINGS

1. `frontend`/`bff`/`backend`/`celery-worker`/`celery-beat` are always
   built fresh from source on the deployment host, always land in the
   same mutable local tag, with no registry and no CI/CD anywhere in
   this repository today.
2. `backend`, `celery-worker`, `celery-beat` share one Dockerfile/context
   but get three independent image names — a latent version-mismatch
   risk if ever built selectively rather than all together.
3. Every application image is untagged beyond an implicit `:latest`-like
   local name; the previous build is only retained as an unnamed,
   easy-to-lose dangling image.
4. `waha` (`:gows`) and, to a lesser degree, `nginx`/`redis` (minor
   version tags) are mutable — re-pulling can silently change what runs
   without any change in this repository.
5. No base image is pinned by digest; a rebuild months apart, from an
   unchanged Dockerfile, is not guaranteed to reproduce the exact same
   image.
6. No versioning/rollback procedure is documented anywhere.

---

## 3. RISKS

| Risk | Currently mitigated? |
|---|---|
| Backward-incompatible DB migration deployed alongside new app code | **No** — Django migrations run independent of any image-tag concept; M6 doesn't fix this by itself (see Section 7) — rolling back the *app image* without also considering migration state can leave code expecting a schema the DB doesn't have. |
| Frontend build requiring a BFF/Django API that doesn't exist yet on the deployed backend | **No** — frontend, BFF, and backend are three independently-built images with no shared version identifier tying a specific frontend build to the BFF/Django build it was tested against. |
| BFF/backend version mismatch (Office and Tencent are two separate hosts/Compose projects — confirmed `docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`) | **No** — nothing enforces that the BFF and backend deployed together actually correspond to the same source commit. |
| Docker image tag changing meaning after deployment (`latest` semantics) | **Yes, this is the current default behavior** — not a hypothetical, it's exactly what happens today on every rebuild. |
| Losing the old image after a rebuild/prune | **Partially** — Docker doesn't delete a superseded image immediately (it just untags it), but nothing prevents `docker image prune`/disk pressure from reclaiming it, and it can no longer be referenced by name once untagged. |

---

## 4. WHAT IS ALREADY SAFE

- Application dependency versions are exactly pinned
  (`requirements.txt`, `package-lock.json` ×2) — the *content* going
  into a build is reproducible even though the *resulting image tag* is
  not persistently addressable.
- `waha_sessions`/`waha_media` are named volumes, untouched by a normal
  `up`/`down` cycle — a rollback that avoids `-v` does not risk the live
  WAHA session.
- `restart: unless-stopped` on every service — a rollback that replaces
  a running container doesn't need to also fix up restart policy.
- Git itself is a complete, ready-made source-level rollback mechanism
  for *code* (not images) — `git checkout <previous commit>` +
  `docker compose build` reproduces the previous application
  source exactly, modulo the floating-base-image caveat above.
- Migrations are Django's own forward-only, ordered mechanism —
  well-understood, no custom rollback tooling needed to reason about
  *what* ran; the gap is process/discipline around when to run them
  relative to an app rollback, not the migration mechanism itself.

---

## 5. WHAT IS MISSING

- No image tag that survives a rebuild long enough to roll back to.
- No place recording "which source commit is the currently-deployed
  one" independent of `git log` on the deployment host itself.
- No documented rollback procedure (which order to roll back
  services/config/migrations in).
- No shared image identity between `backend`/`celery-worker`/`celery-beat`.
- No decision, anywhere, on whether a registry will ever be used (not a
  gap to fix unilaterally — see Section 8).

---

## 6. PROPOSED MINIMAL STRATEGY

The minimal, repo-only, registry-agnostic piece of this that can be done
**without deciding on a registry/CI provider** is: **give every build a
stable, content-derived tag instead of relying on the implicit mutable
one**, and **keep the previous tag around explicitly** instead of
letting Compose silently overwrite it. Concretely:

1. Introduce an `IMAGE_TAG` (or similar) environment variable, used as
   the tag Compose builds/runs (`image: wamora-backend:${IMAGE_TAG:-local}`,
   one shared `image:` name across `backend`/`celery-worker`/`celery-beat`
   so all three are guaranteed to be the same build). Defaulting to a
   safe, non-production value (e.g. `local`) if unset — no registry,
   no CI, and no real production value required for this to work; an
   operator can set it to a git short-SHA, a date, or anything else
   they choose.
2. Before overwriting the running deployment, `docker tag` (or an
   equivalent `IMAGE_TAG=<previous>` build kept around) the currently-
   running image under a `-previous` (or explicit prior `IMAGE_TAG`)
   name, so "the thing that was running before" stays addressable by
   name for at least one rollback step, without needing a registry at
   all — this is purely local `docker` tag bookkeeping.
3. Document the rollback procedure itself (order of operations: which
   service to roll back first, when to also consider migration state,
   how to verify health afterward) — this is process documentation, a
   Compose-file-adjacent change, not a code change.

This gets meaningfully safer *without* requiring a registry, CI/CD, or
any production value this repository shouldn't guess — it only requires
picking a tagging *scheme*, which is a decision this repo can express as
a convention, not an operator-specific fact.

---

## 7. IMPLEMENTATION OPTIONS

Presented as options, not a decision — Section 9 lists exactly what
still needs your input before picking one.

### Option A — Local tag discipline only (no registry)
- What: the `IMAGE_TAG` + `docker tag`-the-previous-build approach from
  Section 6, entirely on the deployment host, no registry involved.
- Rollback = re-run `docker compose up -d` with `IMAGE_TAG` pointed at
  the previous tag (no rebuild needed, since that image is still on
  disk under its own name).
- Trade-off: **works with zero new infrastructure and no decision about
  a registry**, but only protects you as far back as however many
  previous tags you keep on that one host's disk — if the host's disk
  is lost/rebuilt, so is every rollback target. Doesn't help if you ever
  need to redeploy to a *different* host.

### Option B — Push to a container registry (deferred: which one)
- What: after building, `docker push` each image to a registry under an
  immutable tag (e.g. a git SHA); rollback = `docker compose pull` a
  specific prior tag, no local build/history dependency at all.
- Trade-off: **the only option that survives losing the deployment
  host entirely**, and is the natural fit if CI/CD is ever added. But it
  requires deciding on a registry (Docker Hub, GHCR, a Tencent Cloud
  registry, a self-hosted one, or something else) and provisioning
  credentials for it — explicitly **not** decided by this repo today
  (Section 8), and this report does not choose one on your behalf.
- Can be layered *on top of* Option A later without redoing A's work —
  they are not mutually exclusive.

### Option C — Git-commit-as-version-of-record, rebuild-to-rollback
- What: no image tagging scheme at all; rollback = `git checkout` the
  previous known-good commit on the deployment host, then
  `docker compose build && up -d`.
- Trade-off: **needs no new tagging convention, no registry decision**,
  literally works today with the files as they already are. But it's
  the *slowest* rollback (a full rebuild, not just swapping a tag) and
  is the one most exposed to the floating-base-image caveat (Section
  1) — a rebuild of an old commit today may not perfectly reproduce
  what actually ran back then, since `python:3.12-slim`/`node:22-alpine`
  etc. may have moved under those same tags since.
- Cheapest to adopt as an *interim* documented procedure while A/B are
  still being decided — costs nothing to write down now.

### Cross-cutting, any option: shared `image:` name for backend/celery-*
Regardless of A/B/C, giving `backend`/`celery-worker`/`celery-beat` one
shared `image:` name (built once, referenced three times) closes the
version-mismatch risk from Section 3 and is a small, self-contained
change compatible with every option above.

---

## 8. NEEDS VERIFICATION / OPERATOR DECISIONS

Nothing below is guessed or assumed in this report:

1. **Is a container registry wanted at all**, and if so, which one
   (Docker Hub, GHCR, a Tencent Cloud registry, self-hosted, or none)?
   This repo does not assume Docker Hub/GHCR/Tencent Container Registry
   or any other — genuinely undecided.
2. **Is CI/CD planned** (which would naturally want to own tagging/push),
   or will builds continue to happen by hand on the deployment host for
   now? Confirmed nothing exists today either way.
3. **How many previous versions need to stay rollback-able** — one step
   back, or a longer history? Shapes whether Option A's local-tag
   bookkeeping is sufficient or a registry (Option B) is needed sooner.
4. **Who/what triggers a rollback decision** — this report only covers
   the mechanism, not an on-call/ops process.
5. **Migration rollback policy** — out of M6's own scope per your
   instruction not to touch migration execution here (that's tracked
   separately, "migration execution procedure" in your Phase 14
   priority list) but the two are coupled: an app-image rollback that
   ignores migration state can be unsafe, and this report flags that
   coupling without resolving it.

---

## 9. RECOMMENDED IMPLEMENTATION ORDER

No registry/cloud-provider decision is assumed here — each step below
is useful regardless of how Section 8's questions are eventually
answered, and is ordered so nothing later depends on a decision not yet
made:

1. **Shared `image:` name for `backend`/`celery-worker`/`celery-beat`**
   (Section 7, cross-cutting) — zero new decisions needed, closes a
   real version-mismatch gap immediately.
2. **Document the rollback procedure** (Option C, at minimum, as the
   documented fallback) — costs nothing, needs no registry decision,
   and is useful even after A/B are eventually adopted.
3. **Introduce `IMAGE_TAG` + local previous-tag retention** (Option A)
   — still no registry needed, meaningfully faster/safer than C alone.
4. **Decide registry/CI (Section 8, items 1–2)** — genuinely your call;
   this report does not recommend one.
5. **Adopt Option B** once (and only once) #4 is answered.

---

## 10. Explicit stop

This was an audit and report only. No Dockerfile, Compose file, or any
other file was changed. No image was built or pushed. No deployment was
performed. Nothing was committed. Awaiting your decision before any
implementation.
