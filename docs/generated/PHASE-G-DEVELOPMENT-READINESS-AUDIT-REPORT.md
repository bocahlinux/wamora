# Phase G — Development Environment Readiness & Next-Step Audit (Read-Only)

**Scope.** Read-only audit only. No file was modified, no container was
restarted, no configuration was changed, no database write was
performed by this audit, no WhatsApp message was sent, no write
endpoint was called. The development Docker environment was **already
running** (started by the user, and by this session in an earlier turn
while diagnosing an unrelated PostgreSQL connectivity question) — this
audit only *observed* its live state via read-only commands (`ps`,
`logs`, `exec redis-cli ping`, `curl GET`).

---

## 1. Objective

Establish a factual baseline after Phase A–F: is the current
implementation actually ready to be the normal development workflow, is
anything concretely broken, does Phase G need to be an implementation
phase at all, and what should happen next — based only on the current
repository and live state, not on assumption or preference.

---

## 2. Current Repository State

**VERIFIED DIRECTLY** (`git status`/`git diff --stat`, re-run this
task): identical in shape to the state Phase F left — the same nine
tracked files modified (`.gitignore`, `README.md`, `backend/config/urls.py`,
three frontend files, `frontend/vite.config.ts`,
`infrastructure/office/.env.example`), the same set of untracked
`docs/generated/*.md` reports, and `infrastructure/development/` still
entirely untracked. **No unexpected tracked-file change exists.** Every
prior phase's report is present; none is missing.

**A concrete, newly-discovered change exists, but outside `git`'s own
visibility**: `infrastructure/development/office.yml` and `tencent.yml`
(untracked, so invisible to `git diff`) have been **manually extended by
the user**, independently of any Phase A–F work in this session, with a
new bind mount on every service:
```yaml
- ${JWT_KEYS_HOST_PATH}:/run/secrets/wamora:ro
```
and a corresponding `JWT_KEYS_HOST_PATH=E:/keys/wamora` in both real
`.env`/`tencent.env` files, with `JWT_PRIVATE_KEY_PATH`/`JWT_PUBLIC_KEY_PATH`
pointing at `/run/secrets/wamora/jwt_*.pem` inside the containers. This
is a legitimate, working extension (confirmed live — Section 5) that
**this session did not author** and that **no Phase A–F report
documents**. Flagged in Section 9 as a real, minor gap: the two
`.env.example` templates were not updated to reflect it (Section 6).

---

## 3. Phase A–F Verification

**VERIFIED DIRECTLY, re-checked against current source, not merely
cited from the reports themselves:**

- **Phase A**: `infrastructure/office/.env.example` line 43 —
  `RECONCILIATION_EXECUTOR=celery` — present, unchanged.
- **Phase B**: `infrastructure/development/office.yml` — four services
  (`backend`, `celery-worker`, `celery-beat`, `redis`), same
  `backend/Dockerfile`, `redis` healthcheck present, `condition: service_healthy`
  gating the other three — matches the report exactly, plus the user's
  own JWT-mount addition (Section 2).
- **Phase C**: `infrastructure/development/tencent.yml`'s `bff` service —
  `build.target: build`, explicit `name: wamora-dev-tencent`,
  `CHOKIDAR_USEPOLLING: "true"`, healthcheck via the existing `/health` —
  all present, unchanged.
- **Phase D**: same file's `frontend` service — `build.target: build`,
  `command: npx vite`, `CHOKIDAR_USEPOLLING: "true"`, port `5173:5173` —
  present, unchanged. `frontend/vite.config.ts`'s `server: { host: true }`
  confirmed present (`git diff` shows the +8 lines untouched since Phase D).
- **Phase E**: its own claims (BFF→Django via `host.docker.internal`,
  independent Compose projects, hot reload for all three components) —
  **re-verified live this task**, not merely re-read (Section 5).
- **Phase F**: `infrastructure/development/.env.example`'s
  `DJANGO_SECRET_KEY=django-insecure-dev-only-placeholder` pre-fill
  confirmed present; README's Tencent Development stack section and the
  two added env-file table rows confirmed present (`git diff --stat`
  shows `README.md` still at `164` insertions, unchanged since Phase F).

**No regression found in any Phase A–F deliverable.**

---

## 4. Current Docker Topology

**VERIFIED DIRECTLY** — confirms the intended, unchanged shape:

```
Office (project "development", infrastructure/development/office.yml)
  backend, celery-worker, celery-beat, redis

Tencent (project "wamora-dev-tencent", infrastructure/development/tencent.yml)
  bff, frontend

External: PostgreSQL (real, 192.168.168.171), WAHA (real, session "no_epahari")
```

`docker network ls` (re-run this task): `development_default` and
`wamora-dev-tencent_default` — two distinct networks, confirmed still
independent. Neither Compose file references the other's service names
or networks. **No evidence anywhere in the repository suggests this
architecture is broken** — per the task's own instruction, no merge is
proposed.

---

## 5. Live Container Verification (Read-Only, Already-Running Stack)

**VERIFIED DIRECTLY**, all commands read-only (`ps`, `logs`, `exec
redis-cli ping`, `curl GET`) — no container was restarted for this audit:

| Check | Result |
|---|---|
| `backend` | `Up`, `GET /api/health/` → `200 {"status":"ok","component":"backend"}` |
| `celery-worker` | `Up`, log shows `Connected to redis://redis:6379/0`, `celery@... ready.`, all 3 tasks registered |
| `celery-beat` | `Up`, log shows `broker -> redis://redis:6379/0`, **and a real periodic firing already occurred** (Section 5.1) |
| `redis` | `Up (healthy)`, `redis-cli ping` → `PONG` |
| `bff` | `Up (healthy)`, `GET /health` → `200 {"status":"ok","service":"bff","waha":{"reachable":true}}` |
| `frontend` | `Up`, `GET /` → `200` |
| Networks | `development_default`, `wamora-dev-tencent_default` — confirmed distinct |
| Ports | `8000` (Django), `8080` (BFF), `5173` (frontend) all published and responding; Redis has no published port (by design, unchanged) |

### 5.1 A significant, unplanned live observation

**VERIFIED DIRECTLY from live logs, not triggered by this audit**:
Celery Beat's own periodic schedule (`reconcile-all-sessions`, every
`RECONCILIATION_INTERVAL_SECONDS=900`) fired **on its own**, roughly 13
minutes after the stack was started (by this session, in an earlier
turn, while diagnosing the user's unrelated PostgreSQL question) —
```
[...] Scheduler: Sending due task reconcile-all-sessions
[...] Task apps.sync.tasks.reconcile_all_sessions_task[...] succeeded: {'sessions_dispatched': 1}
[...] reconcile_session_task session=no_epahari chats_processed=8 ... messages_skipped_existing=95 ... had_error=False
```
This is **not** an action this audit (or the prior debugging turn) took
deliberately — it is Celery Beat's own automatic schedule, firing exactly
as designed, because the container happened to already be running with
the user's **real** `WAHA_BASE_URL` and `DB_HOST` credentials. **This is
the strongest evidence available that the entire pipeline — Django →
Celery Beat → Redis → Celery Worker → `reconcile_session()` → real WAHA
→ real PostgreSQL — works correctly in actual use, not merely in a
scripted test.** `waha.reachable: true` (BFF's own health check, Section
5's table) independently confirms the same real WAHA session is
reachable from BFF too. No message was sent, no write endpoint was
called by this audit — this was pre-existing background activity,
observed, not caused.

---

## 6. Development Workflow Verification

Walked through the task's own 12-step list against current files and
live behavior:

1–3. **Clone/copy templates/fill values** — VERIFIED FROM SOURCE
(README's documented steps match the actual file names/locations
exactly), with **one gap**: the user's own `JWT_KEYS_HOST_PATH` addition
(Section 2) is **not** reflected in either `.env.example` template — a
new developer following the templates literally would not know this
variable exists, even though the *committed* Compose files' own
behavior doesn't strictly require it (JWT keys can still be provided
inline via `JWT_PRIVATE_KEY`/`JWT_PUBLIC_KEY`, unchanged). Not a defect
in what's committed, but a real, small documentation gap in a
now-diverged live setup.
4–8. **Start Office/Tencent, access Django/BFF/frontend** — VERIFIED
DIRECTLY, live, this task (Section 5).
9. **Hot reload** — VERIFIED FROM SOURCE (unchanged config: `StatReloader`,
`tsx watch`+polling, Vite HMR+polling) and previously VERIFIED DIRECTLY
in Phase E/F; **not re-tested live this task** (would require a
source-file edit, and Step 4's instructions for this audit explicitly
forbid creating temporary source changes) — carried forward as an
already-proven fact, not re-asserted from nothing.
10–11. **Stop/restart** — VERIFIED FROM SOURCE (`docker compose down`/`up`
commands match documented behavior) and previously VERIFIED DIRECTLY in
Phase E/F; not repeated live this task (the stack is currently in active
use with real data — Section 5.1 — and this audit's own instructions say
not to restart containers unless absolutely necessary for verification,
which it was not).
12. **Rebuild after dependency changes** — VERIFIED FROM SOURCE
(`--build` flag present in every documented command); not exercised live
this task.

**Conclusion: the documented workflow matches the actual Compose files
with no discrepancy**, except the one JWT-mount documentation gap named
above.

---

## 7. External Dependency Boundaries

| Item | Status |
|---|---|
| PostgreSQL remains external to development Docker | **INTENTIONAL ARCHITECTURAL BOUNDARY** — confirmed, no `postgres` service in either file; the live stack reaches a real external instance (`192.168.168.171`) |
| WAHA remains external to development Docker | **INTENTIONAL ARCHITECTURAL BOUNDARY** — confirmed, no `waha` service in either file; the live stack reaches a real external session (`no_epahari`) |
| Celery worker/beat hot reload | **INTENTIONAL ARCHITECTURAL BOUNDARY** — no reload mechanism exists by design (documented limitation, not a defect); manual restart required after task-code changes |
| JWT key path handling inside Docker | **VERIFIED DIRECTLY, working, but undocumented in templates** (Section 2/6) — not a defect in behavior, a documentation gap |
| Django dev DB connectivity from Docker | **VERIFIED DIRECTLY** — real Postgres reachable and functioning (Section 5.1's own reconciliation success is definitive proof beyond the earlier health-endpoint check) |
| BFF → Django connectivity | **VERIFIED DIRECTLY** — `200` via `host.docker.internal`, no shared network |
| Frontend → BFF connectivity | **VERIFIED FROM SOURCE** (embedded `VITE_BFF_BASE_URL` confirmed correct in Phase D/E/F) — browser-level fetch not re-tested this task (no browser automation available, consistent with every prior phase's own disclosed limitation) |
| CORS configuration | **VERIFIED FROM SOURCE** (unchanged since Phase E's live proof); not re-tested live this task |
| `RECONCILIATION_EXECUTOR=celery` | **VERIFIED DIRECTLY, twice over** — both by direct settings inspection in prior phases and, now, by Section 5.1's live, successful periodic execution — the strongest possible confirmation |
| Redis health | **VERIFIED DIRECTLY** — `PONG`, healthy, worker/beat both connected |
| Docker Desktop / Windows file watching | **INTENTIONAL ARCHITECTURAL BOUNDARY, already mitigated** — `CHOKIDAR_USEPOLLING=true` remains in place for both `bff` and `frontend`, confirmed present in the current file (Section 3) |

---

## 8. Known Limitations (Unchanged From Phase F, Re-Confirmed)

- Celery worker/beat require a manual restart after task-code changes —
  by design, not fixed, not proposed to be fixed.
- `backend/.env.example`'s own `DJANGO_SECRET_KEY=` empty-string issue
  (Phase F's "Findings Outside Phase F") remains **unfixed** — still out
  of the Docker-development-environment's own scope; not touched by this
  audit either.
- No browser-automation-based verification of the frontend UI exists in
  this environment — every "browser-facing" check across Phase D/E/F/G
  has used `curl`/direct HTTP, honestly disclosed each time.

---

## 9. Actual Defects, If Any

**None found in the Docker development architecture itself.** The one
concrete, new finding this audit surfaced is **documentation drift, not
a functional defect**:

- **`infrastructure/development/.env.example` and
  `infrastructure/development/tencent.env.example` do not document the
  `JWT_KEYS_HOST_PATH` variable** the user has since added directly to
  both real `.env` files and both Compose files' `volumes:` (Section 2).
  The *committed* templates and Compose files remain fully self-consistent
  and functional on their own (a developer using `JWT_PRIVATE_KEY`/`JWT_PUBLIC_KEY`
  inline, exactly as originally documented, is unaffected) — this is
  only a gap for a *future* developer who tries to replicate the current
  live user's own now-diverged, undocumented local workflow.

**This is not classified as an "actual defect"** in the sense the task's
own taxonomy intends (something broken) — it is a live, working,
user-authored extension whose own template documentation simply hasn't
caught up yet, analogous in kind (though smaller in impact) to the
`DJANGO_SECRET_KEY` gap Phase F itself found and fixed for a
different variable.

---

## 10. Phase 9 Status

**VERIFIED FROM SOURCE** (existing `docs/generated/PHASE9-*.md` reports,
re-confirmed present and unchanged in `git status` — none was modified
during Phase A–G's Docker work):

- **Phase 9.0** (ambiguous send-outcome UX, Inbox) — implemented.
- **Phase 9.1A** (backend sync-status endpoint) — implemented.
- **Phase 9.1D** (connectivity indicator) — implemented.
- **Phase 9.1E** (frontend sync-status consumption) — implemented.
- **Phase 9.1C** (Redis health endpoint) — **design-audited only, not
  implemented**. `docs/generated/PHASE9-1C-DESIGN-AUDIT-REPORT.md` gives
  a complete, decided design (endpoint shape, auth, response contract,
  timeout, test strategy) with exactly one open item (the specific
  timeout constant value) — the most implementation-ready Phase 9 slice
  currently on record.
- **Other Phase 9 slices** (9.1B webhook-timestamp signal, 9.1F Dashboard
  Redis card, Sessions connectivity extension, Dashboard sync-status
  card, stuck-running recovery, Celery worker liveness) — all remain at
  design-audit stage or earlier, per
  `docs/generated/PHASE9-NEXT-SLICES-DESIGN-AUDIT-REPORT.md`'s own
  dependency graph (9.1F depends on 9.1C; the rest are independent but
  each carries its own open sub-question, unlike 9.1C).

**No Phase 9 implementation work was performed by this audit.**

---

## 11. USER DECISIONS REQUIRED

1. **Whether to fix the `JWT_KEYS_HOST_PATH` documentation gap** (Section
   2/6/9) — a small, low-stakes template update (add the variable and its
   `/run/secrets/wamora/...` convention to both `.env.example` files,
   mirroring how the real, live `.env`/`tencent.env` already use it).
   Not a blocker, not urgent, but worth a deliberate yes/no rather than
   silent continuation of the drift.
2. **Whether the currently-running live stack (with real WAHA/PostgreSQL
   credentials) should be left running, or stopped** — this audit did
   not stop it (Section 5's own "no restart unless necessary" instruction),
   and it is actively performing real reconciliation work
   (Section 5.1) — a decision for the user, not this audit, since
   stopping it would interrupt real, in-progress background work.

No other decision requiring your input was found — every other question
this audit could answer, it did.

---

## 12. Recommended Next Phase

**A. Is Phase G actually necessary as a large implementation phase?
No.** The development Docker environment (Phase A–F) is confirmed
stable, functionally correct, and — per Section 5.1 — **already proven
in real, live use** with the user's own real credentials, not merely in
scripted tests. No concrete defect was found that would justify further
Docker-architecture implementation work.

**B. What Phase G should accomplish, if anything**: at most, the single
small documentation fix named in Section 11, item 1 — not a phase-sized
body of work.

**C. Why Phase G (as a Docker-development-implementation phase) should
be skipped**: there is nothing left to build. Phase F already closed the
one real, blocking defect found in this whole initiative
(`DJANGO_SECRET_KEY`); this audit found no comparable blocker — only a
minor, optional documentation touch-up.

**D. What should happen immediately after**: **Phase 9.1C (Redis health
endpoint)**, based strictly on dependency/readiness, not preference:

- It is the only Phase 9 slice with a **complete, fully-decided design**
  on record (`PHASE9-1C-DESIGN-AUDIT-REPORT.md`) — every other candidate
  slice (9.1B, 9.1F, Sessions extension, Dashboard sync card) still
  carries at least one open sub-question per
  `PHASE9-NEXT-SLICES-DESIGN-AUDIT-REPORT.md`'s own comparison.
- It has **zero dependency on the Docker development work** — it's a
  pure Django-side addition (mirrors the existing `DatabaseHealthView`
  pattern exactly), so Phase A–G's completion neither blocks nor is
  required by it.
- It does not depend on any other unresolved Phase 9 item.
- **This audit does not implement it** — named here only as the
  dependency-ordered answer to "what's next," per the task's explicit
  instruction not to rank alternatives by preference; it is simply the
  one candidate with no remaining open question standing in front of it.

---

## 13. Exact Reason for the Recommendation

Every other candidate next-step this audit could identify (staging
preparation, production preparation, another Phase 9 slice, further
Docker work) either has an open, undecided design question attached to
it (per the already-existing `PHASE9-NEXT-SLICES-DESIGN-AUDIT-REPORT.md`'s
own comparison) or has no existing design-audit report to implement
against at all (staging/production). Phase 9.1C uniquely has neither
problem — it is fully specified and ready, and nothing about Phase A–G's
own completion status changes that calculus in either direction.

---

## 14. Explicit Stop Condition

**No file was modified. No container was restarted for this audit's own
purposes (Celery Beat's Section 5.1 activity was pre-existing background
behavior, observed, not triggered). No database write was performed by
this audit. No WhatsApp message was sent. No write endpoint was called.**

**STOP.** This report does not implement Phase 9.1C, the Redis health
endpoint, Celery liveness, or stuck-running recovery. It does not create
staging, modify production, modify application logic, or modify the
Docker architecture. Awaiting your decisions in Section 11, and your
go-ahead before any further implementation work begins.
