# Phase 14 — M6: Rollback / Image Versioning — Implementation Report

Implements the decisions approved against
`docs/generated/PHASE-14-M6-ROLLBACK-IMAGE-VERSIONING-AUDIT-REPORT.md`.
**Local image tagging only** — no container registry, no CI/CD, no
production deployment, no migration file change, no production `.env`
touched. Blast/WAHA session logic/reconciliation were not touched.

---

## 1. Files changed

| File | Change |
|---|---|
| `infrastructure/office/docker-compose.yml` | `backend` keeps `build:`, gains `image: wamora-backend:${IMAGE_TAG:-local}`. `celery-worker`/`celery-beat` **lose their own `build:` section** and reference the same `image:` — they can no longer be built independently at all. |
| `infrastructure/tencent/docker-compose.yml` | `frontend` gains `image: wamora-frontend:${IMAGE_TAG:-local}`; `bff` gains `image: wamora-bff:${IMAGE_TAG:-local}`. Both keep their existing `build:` unchanged. `reverse-proxy`/`waha` untouched (third-party base images, out of scope per your decisions). |
| `infrastructure/office/.env.example`, `infrastructure/tencent/.env.example` | Document `IMAGE_TAG` (optional, defaults to `local`). |
| `docs/08-DEPLOYMENT.md` | New "Image versioning and rollback" section — the full procedure (Section 4 below). |
| `infrastructure/scripts/compute-image-tag.sh` (new) | Prints the git short SHA, or `local` if unavailable. |
| `infrastructure/scripts/rotate-image-tags.sh` (new) | Shifts the current/previous/previous-previous alias chain and points `current` at a freshly-built tag. |
| `infrastructure/scripts/rollback-image.sh` (new) | Rolls `current` back to `previous` (and `previous-previous` forward into `previous`), no rebuild. |

No Dockerfile changed. No Blast/WAHA/reconciliation/migration file
touched. B1–M5's own changes (TLS/reverse-proxy, log rotation, SPA
fallback, security hardening) are untouched — confirmed by diff (the
`x-logging` anchors, `reverse-proxy` service, `nginx.conf`,
`test_tls_proxy_settings.py`, `trustProxy.test.ts` etc. all still
present exactly as before).

---

## 2. Tagging design

- **`backend`/`celery-worker`/`celery-beat` share one image** (`wamora-backend`).
  Only `backend` has a `build:` section now — confirmed directly (Section
  5) that `docker compose build celery-worker` alone now does **nothing**
  ("No services to build"), so it is structurally impossible for these
  three to run different versions of each other. This is stronger than
  "same `image:` name with 3 separate `build:` blocks" (which would still
  let someone build just one of them) — closes audit Finding #2 more
  completely than the audit's own Section 7 proposal.
- **`frontend`/`bff` remain two separate images** (`wamora-frontend`,
  `wamora-bff`) — they're genuinely different applications.
- **`IMAGE_TAG`** (env var, optional, defaults to `local`) is the tag
  Compose builds/runs. Recommended convention (decision #3):
  `sh infrastructure/scripts/compute-image-tag.sh` — the current git
  commit's short SHA, falling back to `local` if this checkout isn't a
  git repo with a resolvable `HEAD`. Never guesses a production value —
  the default (`local`) needs none.
- **3-slot alias chain** (`current`/`previous`/`previous-previous`) —
  separate, human-readable tags on the SAME image repository, existing
  alongside (never replacing) the concrete `IMAGE_TAG` tags. Managed
  purely by `rotate-image-tags.sh`/`rollback-image.sh`; Compose itself
  never references `current`/`previous` directly (a deploy always uses
  the concrete `IMAGE_TAG`; the alias chain is bookkeeping + the
  rollback mechanism).

---

## 3. How 3-version retention works

`rotate-image-tags.sh <repo> <new_tag>` (run once per new build, per
image repo):
1. If `<repo>:previous` exists, retag it `<repo>:previous-previous`.
2. If `<repo>:current` exists, retag it `<repo>:previous`.
3. Retag `<repo>:<new_tag>` as `<repo>:current`.

**Never deletes or untags anything.** An image that ages out of the
3-slot window keeps its own original concrete tag (e.g. its git SHA)
on disk, untouched — verified directly (Section 5): after 4 simulated
deploys, the 1st deploy's tag was still fully addressable via
`docker image inspect`, even though it had fallen out of the
current/previous/previous-previous window.

`rollback-image.sh <repo>`:
1. Retag `<repo>:previous` as `<repo>:current`.
2. If `<repo>:previous-previous` exists, retag it as `<repo>:previous`
   (else `previous` is left pointing at the same image as the new
   `current` — never deleted).

No rebuild involved either direction — both scripts only move local
Docker tags.

---

## 4. Rollback procedure (also in `docs/08-DEPLOYMENT.md`)

- **Know what's active**: `docker images wamora-backend` (etc.) lists
  every alias + concrete tag with shared `IMAGE ID`s; for a running
  container, `docker inspect <container> --format '{{.Config.Image}}'`.
- **Deploy**: `IMAGE_TAG=$(compute-image-tag.sh)` → `docker compose build`
  → `rotate-image-tags.sh <repo> "$IMAGE_TAG"` for each app image →
  `docker compose up -d`.
- **Roll back, no rebuild**: `rollback-image.sh <repo>` →
  `IMAGE_TAG=current docker compose up -d --no-build <service(s)>`.
- **Only backend/Celery needs rolling back**: roll back `wamora-backend`
  and restart `backend`+`celery-worker`+`celery-beat` together (they
  share the image by construction) — Tencent's `frontend`/`bff` are
  untouched. Works symmetrically the other way.
- **Service order**: identify which side is broken (health checks
  below) and roll back only that side; Office's 3 services always move
  together (shared image), Tencent's `frontend`/`bff` are independent.
- **Health check after rollback**: reuses existing endpoints — Office
  `GET /api/health/`, `/api/health/database/`, `/api/health/redis/`;
  Tencent BFF `GET /health`.
- **Migration caveat, stated explicitly**: an image rollback does **not**
  by itself mean a database migration is safe to roll back — confirm
  schema compatibility with the older code before relying on this alone.
- **`docker compose down -v` is explicitly forbidden in production** —
  documented prominently: it deletes `waha_sessions`/`waha_media`,
  destroying the live WAHA session. Nothing in this implementation ever
  uses `-v`.

---

## 5. Validation results

- **`docker compose config` — office**: valid (isolated scratch copy,
  placeholder `.env`). `backend` shows `build:` + `image:
  wamora-backend:local`; `celery-worker`/`celery-beat` show `image:
  wamora-backend:local` with **no `build:` key at all**.
- **`docker compose config` — tencent**: valid (isolated scratch copy,
  B2/B3's required vars satisfied with placeholders). `frontend` →
  `wamora-frontend:local`, `bff` → `wamora-bff:local`; `reverse-proxy`
  TLS mounts, ports, `x-logging`, and `waha` all still present and
  correct — B1–M5 unaffected.
- **Structural version-mismatch test**: `docker compose build
  celery-worker` (alone) → `time="..." level=warning msg="No services to
  build"`, exit 0 — confirmed there is no way to build it independently
  of `backend`.
- **IMAGE_TAG produces a reusable tag**: built a throwaway backend image
  3 times with `IMAGE_TAG=sha-aaa111`/`sha-bbb222`/`sha-ccc333`,
  running `rotate-image-tags.sh` after each — `docker images
  wamora-backend` showed exactly `current`/`previous`/`previous-previous`
  correctly pointing at the 3 most recent, each also addressable by its
  own concrete tag.
- **Previous image never becomes unaddressable**: ran a 4th deploy
  (`sha-ddd444`) — `sha-aaa111` (now outside the 3-slot window) was
  confirmed still present and inspectable by name
  (`docker image inspect wamora-backend:sha-aaa111` succeeded).
- **Rollback simulation, local images only**: ran `rollback-image.sh
  wamora-backend`, confirmed the alias shift via `docker images`, then
  actually started a real container with `IMAGE_TAG=current
  docker compose up -d --no-build backend` — `docker inspect` confirmed
  the running container's image ID exactly matched the rolled-back
  `wamora-backend:current` tag. No rebuild occurred (`--no-build`).
- **Shared image identity confirmed for real**: started `backend` +
  `celery-worker` + `celery-beat` together and inspected each
  container's `Config.Image` — all three: `wamora-backend:current`,
  byte-identical value.
- **`git diff --check`**: clean (exit 0) on every modified tracked file.
  New scripts checked too (only the routine LF→CRLF autocrlf notice
  Windows always prints for new files — no actual whitespace error);
  confirmed via `file` that they're still plain LF POSIX shell scripts
  on disk right now.
- **Test/build for application config changes**: **not applicable** —
  no Django/BFF/frontend application source was changed in this task
  (only Compose YAML, `.env.example` docs, one new doc section, and 3
  new standalone shell scripts outside any app's test suite), so no
  `manage.py test`/`npm test`/`npm run build` re-run was needed or
  performed.
- All test containers, images, and networks created during validation
  were removed afterward; confirmed via `docker ps -a`/`docker images`
  that only the pre-existing, unrelated dev stack remains.

---

## 6. Gaps / things not covered by this change

- **`redis`/`nginx`/`waha` base images remain mutable tags** — out of
  scope per your decisions ("application images" only); still flagged
  from the audit, unresolved by design.
- **No hash-pinning for `pip`/`npm` dependencies** — noted in the audit
  as adjacent, not part of M6's own scope; unchanged.
- **Migration rollback policy** — explicitly documented as a caveat
  (Section 4) but not designed or implemented here; tracked separately
  per your own Phase 14 priority list ("migration execution procedure").
- **No automated retention limit enforcement** — by design, per your
  explicit instruction not to auto-delete anything; an operator who
  wants to reclaim disk space from very old, out-of-window tags must do
  so manually (`docker rmi`), which this implementation deliberately
  never does on its own.
- **Registry/CI/CD** — deliberately not added, per decisions #7/#8.

---

## 7. Explicit confirmations

- **No container registry** was added or referenced.
- **No CI/CD** was added or referenced.
- **No production deployment** was performed — only isolated, throwaway
  scratch directories (never the real repo paths) were built/run/torn
  down for validation.
- **No migration file** was changed.
- **No production `.env`** was created or modified — confirmed via
  `git status --ignored`, only the same pre-existing gitignored dev
  `.env` files exist, untouched.
- **No real WAHA/WhatsApp session** was touched — validation used a
  trivial `alpine:3.20` throwaway image standing in for `backend`,
  never the real `waha` service or its volumes.
- Nothing was committed or pushed.

---

## 8. Explicit stop

M6 implementation and validation complete. Not proceeding to M7 or any
other Phase 14 item. Awaiting your review and further instructions.
