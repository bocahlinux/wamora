# Deployment

## Tencent Docker
Services:
- frontend
- bff
- waha

Preferred internal flow:
frontend -> bff -> waha

## Office Docker
Services:
- backend
- celery-worker
- celery-beat
- redis

## PostgreSQL
Use existing PostgreSQL. Configure host/IP, port, database, username and password manually.

DO NOT:
- create PostgreSQL service in Compose;
- expose PostgreSQL publicly;
- alter unrelated databases.

WAHA persistence uses configured `/app/.sessions` and `/app/.media`.

Secrets must be environment/secret-managed and never committed.

## Image versioning and rollback

(Phase 14 MISSING item M6 —
`docs/generated/PHASE-14-M6-ROLLBACK-IMAGE-VERSIONING-AUDIT-REPORT.md`/
`PHASE-14-M6-ROLLBACK-IMAGE-VERSIONING-IMPLEMENTATION-REPORT.md`.) Local
image tagging only — **no container registry, no CI/CD** are used or
assumed by anything below.

**Image identity.** `backend`, `celery-worker`, and `celery-beat`
(Office) all run the **same** `wamora-backend` image — only `backend`
has a `build:` section; the other two just reference the same
`image:`, so it is structurally impossible for them to drift apart.
`frontend` and `bff` (Tencent) are two separate images,
`wamora-frontend` and `wamora-bff`. Every one of these is tagged
`${IMAGE_TAG:-local}` in both `infrastructure/office/docker-compose.yml`
and `infrastructure/tencent/docker-compose.yml`. `IMAGE_TAG` is
OPTIONAL everywhere — unset defaults to `local`, which needs no
production value.

**Recommended tag convention**: the current git commit's short SHA.
`sh infrastructure/scripts/compute-image-tag.sh` prints exactly that
(falling back to `local` itself if this checkout isn't a git repo with
a resolvable `HEAD`).

**Knowing what's currently deployed**: `docker images wamora-backend`
(or `wamora-frontend`/`wamora-bff`) lists every locally-retained tag —
`current`, `previous`, `previous-previous`, and each concrete
`IMAGE_TAG` (e.g. a git short SHA) they point at, sharing the same
`IMAGE ID` where they're aliases of each other. For a **running**
container specifically: `docker inspect <container> --format '{{.Config.Image}}'`.

**Deploying a new build**:
```sh
export IMAGE_TAG="$(sh infrastructure/scripts/compute-image-tag.sh)"
docker compose build
sh infrastructure/scripts/rotate-image-tags.sh wamora-backend "$IMAGE_TAG"   # Office
sh infrastructure/scripts/rotate-image-tags.sh wamora-frontend "$IMAGE_TAG" # Tencent
sh infrastructure/scripts/rotate-image-tags.sh wamora-bff "$IMAGE_TAG"      # Tencent
docker compose up -d
```
`rotate-image-tags.sh` is what **retains the previous image** — it
shifts the current/previous/previous-previous alias chain (at least 3
versions stay addressable by name at all times) before pointing
`current` at the new build. It never deletes or untags anything; an
image that ages out of the 3-slot chain simply keeps its own original
tag on disk, untouched.

**Rolling back, without a rebuild** (both images are already on disk):
```sh
sh infrastructure/scripts/rollback-image.sh wamora-backend   # or wamora-frontend / wamora-bff
IMAGE_TAG=current docker compose up -d --no-build backend celery-worker celery-beat
```
`rollback-image.sh` only moves image-tag aliases; it does not restart
anything itself.

**If only backend/Celery needs to be rolled back** (not frontend/BFF):
since `backend`/`celery-worker`/`celery-beat` share one image, rolling
back `wamora-backend` and restarting just those three Office services
is enough — Tencent's `frontend`/`bff` are unaffected and don't need
touching. The reverse (only Tencent needs rolling back) works the same
way, independently.

**Service order for a rollback**: identify which side is actually
broken first (see health checks below) and roll back only that side.
If Office (`backend`+`celery-worker`+`celery-beat`, one shared image)
is the problem, roll it back and restart those three together — they
must never run different versions of each other by design. If Tencent
(`frontend`/`bff`) is the problem, roll back whichever of the two is
affected (they are independent images) and restart it; `reverse-proxy`
and `waha` don't need restarting unless they were also changed.

**Health check after rollback** — reuse the endpoints already built
into this project, no new tooling needed:
- Office: `GET /api/health/` (liveness), `/api/health/database/`,
  `/api/health/redis/`.
- Tencent: BFF's `GET /health` (via the reverse-proxy or directly).

**Database migrations are NOT covered by an image rollback.** Rolling
back `wamora-backend` only changes which application code is running —
it does **not** undo any database migration that new code may have
already applied. Before rolling back a backend version that ran a
migration, confirm the **older** code is actually compatible with the
**current** database schema; if it isn't, an image rollback alone is
unsafe. (Migration execution/rollback procedure itself is tracked
separately — not decided here.)

**Never run `docker compose down -v` in production.** The `-v` flag
deletes named volumes, including `waha_sessions`/`waha_media` — that
would destroy the live WAHA session (a real WhatsApp session), not
just roll back an image. A normal `docker compose down`/`up` (no `-v`)
never touches these volumes; rollback procedures above never use `-v`.
