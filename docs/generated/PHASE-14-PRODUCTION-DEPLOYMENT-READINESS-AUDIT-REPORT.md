# Phase 14 (Production Deployment) — Readiness Audit Report

**Read-only audit.** No code, Docker Compose file, environment file,
database, or deployment target was touched, started, stopped, or
modified. Nothing was pushed. This report is source-code and
documentation reading only, cross-checked against Phase 9/11/12/13's
own reports where relevant.

**Explicit reminder — do NOT do these during this or any future Phase
14 audit/implementation step, unless the user says so explicitly:**
- Do not create a PostgreSQL Docker service (hard rule 1).
- Do not expose PostgreSQL to the public internet, or change any
  firewall/network rule for the real PostgreSQL host (`192.168.168.171`
  in the dev `.env` — whether production reuses this exact host is
  itself an open question, Section 3).
- Do not run any command against the real WAHA instance
  (`100.124.162.223:3000`) or its real session (`no_epahari`) — no
  session start/stop/logout, no message send, no webhook reconfigure.
- Do not run `docker compose up`/`down`/`stop` against any real
  Tencent/Office deployment target.
- Do not run `manage.py migrate` against the real PostgreSQL database.
- Do not generate, rotate, or commit any real secret (JWT keys,
  `DJANGO_SECRET_KEY`, `WAHA_API_KEY`, `INTERNAL_SERVICE_KEY`,
  `OFFICE_DISPATCH_SERVICE_KEY`, `WAHA_WEBHOOK_HMAC_SECRET`, DB
  password) — none should ever appear in a `docs/generated/*.md` file.
- Do not commit or push anything from this audit without being asked.

---

## 1. Sources read for this audit

`docs/15-CODING-PHASES.md`, `docs/01-ARCHITECTURE.md`,
`docs/08-DEPLOYMENT.md`, `docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`,
`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`, `docs/06-SECURITY.md`;
`infrastructure/{tencent,office}/docker-compose.yml` and their
`.env.example` files; `backend/.env.example`, `bff/.env.example`,
`frontend/.env.example`; `backend/Dockerfile`, `bff/Dockerfile`,
`frontend/Dockerfile`, `frontend/.dockerignore`; `backend/config/settings.py`
(security-headers/logging/Blast-dispatch sections); Phase 9/11/12/13
completion and fix reports already in `docs/generated/`.

---

## 2. What's already READY for production

| Area | Status | Evidence |
|---|---|---|
| Fail-closed `DJANGO_SECRET_KEY` when `DEBUG=False` | **READY** | Phase 12 MUST-FIX; re-confirmed present in `settings.py`. |
| CORS: empty-by-default, no wildcard | **READY** | `backend/.env.example`/`infrastructure/office/.env.example` both document this; Phase 12 implementation report. |
| Rate limiting (Django + BFF) | **READY** | Phase 12 login/general throttles; Phase 13 Track B Finding 1 fix makes them fail-open on a Redis outage without weakening normal-case protection (verified: 472/472 backend tests, including the new fail-open tests). |
| Auth/authz negative coverage | **READY** | Phase 13 Track A's systematic endpoint sweep (401/403), permanent regression test. |
| Secrets-not-in-logs coverage | **READY** | Phase 13 Track A (`test_secrets_not_in_logs.py`, `secretsNotInLogs.test.ts`), both passing. |
| BFF WAHA-endpoint allowlist (no generic proxy) | **READY** | `bff/src/wahaAllowlist.ts`, structurally enforced, repeatedly audited. |
| Frontend never holds the WAHA key | **READY** | Structural — key lives only in `bff/`/`waha` env, never in `frontend/`. |
| WAHA session/media persistence | **READY** | `infrastructure/tencent/docker-compose.yml` — named volumes `waha_sessions`/`waha_media` on the `waha` service. |
| `.gitignore` secret coverage | **READY** | Root `.gitignore` excludes `.env`/`*.env`/`.env.*` project-wide, with an explicit `.env.example` carve-out; confirmed no real secret in any of the three Phase 13 reports just committed. |
| PostgreSQL — no Docker service defined | **READY** | Both compose files confirmed to never define a `postgres`/`db` service; backend connects via env vars to existing infra, per hard rule 1. |
| Django/BFF-side idempotency (webhooks, outbound ops) | **READY** | Pre-existing `UniqueConstraint`s, confirmed live under Phase 13 Track A's concurrency test. |
| Reconciliation stuck-checkpoint fix | **READY** | Phase 4/9 fix (`2f18c0d`), confirmed working under a real periodic run during the Track B drill. |
| Redis/PostgreSQL outage resilience (dev-verified) | **READY** (dev-scoped) | Phase 13 Track B Findings 1/2, fixed and tested this session — but see Section 4, this was not re-verified with a live drill after the fix, and Finding 2's fix is dev-`runserver`-specific (production uses gunicorn, which never had this crash to begin with — see Section 5). |

---

## 3. What's MISSING (should be added, doesn't require re-architecture)

| # | Gap | Where | Why it matters |
|---|---|---|---|
| M1 | **Production `.env.example` templates are stale — missing all Phase 11 (Blast) variables** | `infrastructure/office/.env.example` and `infrastructure/tencent/.env.example` (the two files actually referenced by the production Compose `env_file:` directives) have no `OFFICE_DISPATCH_SERVICE_KEY`, `BFF_INTERNAL_BASE_URL`, `BFF_INTERNAL_TIMEOUT_MS`, `BLAST_MAX_RECIPIENTS_PER_CAMPAIGN`, `BLAST_MAX_RECIPIENTS_PER_SESSION_PER_DAY`, `BLAST_INTER_MESSAGE_DELAY_SECONDS`. These DO exist in the per-service `backend/.env.example`/`bff/.env.example`, so the drift is specifically in the infra-level templates, apparently never updated after Phase 11 shipped. | An operator following only the infra-level template would deploy Blast half-configured. **Not silent**, though: `apps/blast/bff_client.py` explicitly raises `BffDispatchError` if either var is empty — every dispatch attempt would fail loudly, not corrupt data. |
| M2 | **No migration-execution step anywhere** | `backend/Dockerfile`'s `CMD` is `gunicorn` only; no entrypoint script, no `migrate` step, no documented manual procedure. | Migrations must currently be run by an undocumented manual `docker compose exec backend python manage.py migrate` — easy to forget on first deploy or a later release. |
| M3 | **No Docker healthcheck anywhere in production Compose** (`backend`, `celery-worker`, `celery-beat`, `redis`, `bff`, `frontend`, `waha` — all 7 services) | Both `infrastructure/{office,tencent}/docker-compose.yml` | Same class of gap as Phase 13 Track B Finding 4, but broader — that finding was scoped to the dev stack's Office side; the **production** compose files have zero healthchecks on any of the 7 services. `docker ps`/`docker compose ps` would show "Up" even for a hung/crashed process (exactly Track B's Postgres-outage finding, but with no dev-only caveat this time). |
| M4 | **No log rotation configured** | Neither compose file sets a `logging:` driver/options block | Docker's default `json-file` driver has no size cap unless set — long-running production containers can fill disk over time. (This is a Compose-level fix, not a Django/BFF one — the app-level choice to log to stdout/console only is itself correct 12-factor practice, not the gap.) |
| M5 | **Frontend has no reverse-proxy/SPA-fallback config** | `frontend/Dockerfile` copies the Vite build into stock `nginx:1.27-alpine` with no custom `nginx.conf` | `frontend/src/App.tsx` uses `BrowserRouter` (history-API routing). Without an nginx `try_files $uri /index.html;` fallback, a page refresh or deep link to any non-root route (e.g. `/sessions`, a specific chat) will 404 against nginx's stock config. |
| M6 | **No rollback/image-versioning strategy** | Both compose files use `build: context: ...` with no image tag; no registry push step anywhere | A rollback today means checking out a previous git commit and rebuilding — undocumented, and there's no way to quickly redeploy "the previous known-good build" without doing that rebuild. |
| M7 | **Django admin static assets will render unstyled** | No `STATIC_ROOT`, no WhiteNoise, no `collectstatic` step; `DEBUG=False` disables Django's own static serving | Low severity — cosmetic only, and only affects `/admin/` if it's actually used in production. Confirms `django.contrib.admin` is still in `INSTALLED_APPS` with no static-serving plan for it. |
| M8 | **No security-headers middleware on the BFF** (`helmet` or equivalent) | `bff/src/app.ts` — no such middleware found | `docs/06-SECURITY.md`'s "security headers" line item is unimplemented on the BFF side (Django already sets `X_FRAME_OPTIONS`/`SECURE_CONTENT_TYPE_NOSNIFF`). Lower risk since BFF mostly returns JSON, not HTML, but still an open checklist item from the same doc. |
| M9 | **`depends_on` has no health-based ordering** | Both compose files — every `depends_on` is a plain list, no `condition: service_healthy` | Combined with M3 (no healthchecks to depend on anyway) — `backend` can start before `redis` is actually accepting connections, `bff` before `waha` has initialized. In practice Redis/WAHA start fast enough that this is usually harmless, but it is not guaranteed. |
| M10 | **No documented backup/restore procedure or schedule** | `docs/06-SECURITY.md` itself lists "backups and restore testing" under Database, still unaddressed; `docs/11`'s "Open" list has "backup retention" | Applies to both the real PostgreSQL data and the `waha_sessions`/`waha_media` Docker volumes (losing the WAHA session volume means re-scanning a QR code and a full session re-link). |

---

## 4. NEEDS VERIFICATION (cannot be determined from static reading — needs your confirmation)

| # | Item | Why it can't be resolved by reading the repo |
|---|---|---|
| V1 | **Which real PostgreSQL host/instance production will use** | `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`'s own "Open" list still says "exact PostgreSQL host/IP/db" is undecided. The dev stack currently points at a real server (`192.168.168.171`) — whether production reuses this exact instance/credentials, or a separate one, is not stated anywhere in the repo. |
| V2 | **The real PostgreSQL role's actual grants / least-privilege status** | Existing infrastructure outside this repo's control (`docs/CLAUDE.md`); Phase 13's own scoping audit flagged this as something to ask you directly for (`\du`/`GRANT` output), never done. |
| V3 | **Whether NetBird (or an equivalent VPN/firewall) is actually installed and configured on the target VPS/Office server** | Purely an ops/infrastructure fact outside the repo; `docs/06-SECURITY.md` states plainly "No NetBird/firewall configuration exists anywhere in this repository today." |
| V4 | **TLS/domain plan** | Explicitly listed as "Open" in `docs/11`; `backend/config/settings.py`'s own comment confirms `SECURE_SSL_REDIRECT`/HSTS were deliberately left unset pending this decision. |
| V5 | **Whether the real production `.env` files (once created) will actually include `OFFICE_DISPATCH_SERVICE_KEY`/`BFF_INTERNAL_BASE_URL`** despite the stale `.env.example` (M1) | Depends on whoever fills in the real `.env` by hand, not on anything checkable in the repo. |
| V6 | **Acceptable data-loss window for Redis on the Office side** | `redis:7-alpine` in `infrastructure/office/docker-compose.yml` has no persistence volume — a Redis restart during production drops the Celery broker/result backend and the rate-limit cache. Whether this is an accepted tradeoff (matches Phase 13 Track B's own finding that a Redis outage is meant to be "visible but recoverable," not "durable") needs your explicit sign-off, since it hasn't been stated anywhere as a deliberate decision. |
| V7 | **gunicorn worker count** | `backend/Dockerfile`'s `CMD` passes no `--workers`/`--threads`, so gunicorn defaults to a single sync worker. Whether that's sufficient for expected production load is a capacity decision, not something this audit can determine. |
| V8 | **Actual VPS/Office server resource sizing (CPU/RAM/disk)** | Not in the repo at all — infrastructure-provisioning information only you have. |

---

## 5. BLOCKERS — must be resolved before going live

| # | Blocker | Evidence | Why it's a blocker, not just "missing" |
|---|---|---|---|
| B1 | **Frontend's `VITE_*` build-time variables have no way to reach the production image** | `frontend/.dockerignore` excludes `.env`; `frontend/Dockerfile` has no `ARG`/`ENV` for any `VITE_*` variable; `infrastructure/tencent/docker-compose.yml`'s `frontend` service build step passes no `args:` at all (only `bff`/`waha` get `env_file:`, and Vite vars are baked in at **build** time, not read at container **run** time regardless). | As currently written, building the production frontend image bakes in `undefined` for `VITE_BFF_BASE_URL`/`VITE_DJANGO_BASE_URL`/`VITE_WAHA_SESSION_NAME`. Every API call the frontend makes would target an undefined/relative URL — the entire application would be non-functional, not degraded. This must be fixed (e.g. `ARG`+`ENV` in the Dockerfile plus `build.args` in Compose, or an equivalent runtime-config approach) before any production frontend build is usable. |
| B2 | **No network-layer isolation for the Tencent-published ports (80/8080)** | `docs/06-SECURITY.md`'s own "Current BFF network-exposure reality" section, verbatim: "No NetBird/firewall configuration exists anywhere in this repository today... must be resolved... before or during production deployment (Phase 14)." Confirmed still true — no NetBird sidecar/config found anywhere. | The docs themselves name this as a precondition for Phase 14, not an optional hardening step. Until resolved, the only defense on the published frontend/BFF ports is application-layer auth — acceptable as a stated risk only with your explicit, informed sign-off (Decision D2 below), not something to silently accept by proceeding. |
| B3 | **No TLS/reverse-proxy anywhere in either production Compose file** | Both `frontend` (`80:80`) and `bff` (`8080:8080`) are plain HTTP; no Traefik/nginx-proxy/certbot/Caddy service exists in either compose file. | Even fully inside a LAN/NetBird boundary, credentials (login JWT, session cookies) would cross the wire unencrypted. `docs/11`'s "TLS/domain" being still "Open" means this was never actually decided, not that it was decided-and-deferred safely — needs an explicit decision before go-live, per the settings.py comment's own framing ("revisit in the... production-deployment phase" — this is that phase). |

---

## 6. Answers to your specific focus areas

- **Env vars/secrets wajib**: every `.env.example` across `backend/`, `bff/`, `frontend/`, `infrastructure/{office,tencent}/` was read. Full list of required secrets: `DJANGO_SECRET_KEY`, `DB_PASSWORD`, `WAHA_WEBHOOK_HMAC_SECRET`, `WAHA_API_KEY`, `JWT_PRIVATE_KEY`(+public), `INTERNAL_SERVICE_KEY`, `OFFICE_DISPATCH_SERVICE_KEY`. See M1/V5 for the one concrete gap found (stale infra-level templates).
- **Database migration strategy**: **missing** (M2) — no automated step, no documented manual one either.
- **Docker Compose production readiness**: structurally sound (correct service split, correct hard-rule compliance — no Postgres service, WAHA has no published port) but missing healthchecks (M3), health-gated `depends_on` (M9), log rotation (M4), and image versioning (M6).
- **Backend/BFF/frontend/WAHA connectivity**: correct topology and allowlisting; the one functional break is B1 (frontend env baking). BFF→WAHA over the Docker network is correctly configured (`WAHA_BASE_URL=http://waha:3000`, no published WAHA port).
- **Redis/Celery/Celery Beat readiness**: services correctly defined and dev-outage-tested this session (Phase 13 Track B fixes); no persistence volume for Redis (V6), no healthcheck (M3).
- **Network exposure dan firewall**: **BLOCKER B2** — explicitly still open per the project's own security doc.
- **HTTPS/TLS/reverse proxy**: **BLOCKER B3** — not present anywhere, explicitly deferred to this phase by the codebase's own comments.
- **Backup dan recovery**: **missing** (M10) — no procedure for either PostgreSQL or the WAHA session/media volumes.
- **Healthcheck/monitoring**: health endpoints exist and are individually good (`LivenessView`/`DatabaseHealthView`/`RedisHealthView`, BFF `/health`) but nothing polls or alerts on them, and no Compose-level healthcheck exists (M3) — no monitoring/alerting system (Prometheus/Grafana/Sentry/etc.) found anywhere in the repo.
- **Logging dan audit**: app-level logging/audit is solid (Phase 12 login audit trail, log redaction, Phase 13 secrets-not-in-logs tests) — the only gap is Docker-level rotation (M4), an infra concern, not a code one.
- **Rollback strategy**: **missing** (M6) — no versioning/tagging, no documented procedure.
- **Things not to touch during this audit**: see the reminder block at the top of this report — followed throughout; nothing was started, stopped, migrated, or pushed.

---

## 7. Decisions required from you

1. **Frontend build-time config (B1)** — approve fixing this as part of Phase 14 implementation (e.g., Dockerfile `ARG`/`ENV` + Compose `build.args`, or switch to a runtime-injected config approach)? This is functionally required for the frontend to work at all in production, not optional.
2. **Network isolation (B2)** — is NetBird (or an equivalent) already installed/planned for the real VPS and Office server, or does this project need to select/document that mechanism as part of Phase 14? If NetBird won't be ready before initial go-live, do you accept the stated risk (application-layer auth only) for an interim period, and for how long?
3. **TLS/domain (B3)** — is there already a domain and TLS certificate plan (e.g., Let's Encrypt via a reverse proxy), or does this need to be decided now? Blocks safely encrypting login/session traffic.
4. **Production PostgreSQL target (V1/V2)** — confirm whether production reuses the same real instance currently used for dev (`192.168.168.171`) or a different one, and provide (or confirm you'll separately verify) the DB role's actual grants/least-privilege status.
5. **Migration execution (M2)** — should this be a manual documented step, or should Phase 14 add an automated one (e.g. an entrypoint script, or a one-off `migrate` job)?
6. **Redis persistence (V6)** — accept the current no-persistence tradeoff for Office Redis (broker/cache data lost on restart), or should Phase 14 add a volume?
7. **Backup scope (M10)** — who owns PostgreSQL backups (likely outside this repo, per hard rule 1's "existing infrastructure" framing) versus the WAHA session/media Docker volumes (in-repo, this project's responsibility)?
8. **Priority/order** — once these are answered, should Phase 14 implementation tackle the 3 BLOCKERs first (B1–B3), then the MISSING items (M1–M10), or a different order?

---

## 8. Explicit stop

This was an audit and report only. No code, Docker Compose file,
environment file, database, or deployment target was changed. Nothing
was committed or pushed. Not proceeding to Phase 14 implementation —
awaiting your decisions above.
