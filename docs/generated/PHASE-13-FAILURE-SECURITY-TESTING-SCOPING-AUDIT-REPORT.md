# Phase 13 (Failure/Security Testing) — Scoping Audit Report

**Read-only audit.** No source, config, migration, Docker, Compose, or
dependency file was modified. No container was started, stopped, or
restarted. No migration, Celery task, reconciliation run, or WAHA write
endpoint was triggered. The only file created by this task is this report.

---

## 1. Step 1 — Confirmed next official phase

**`docs/15-CODING-PHASES.md` re-read in full, unchanged** (verbatim
0–14 list, "Each phase must pass relevant tests before the next phase").

**`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` re-read in full.** Relevant
findings:

- The new dated entry, **"Final — 2026-09-26, phase-labeling
  correction"** (item 13), confirms — consistent with
  `docs/generated/PHASE-ROADMAP-STATUS-AUDIT-REPORT.md` Section 7 — that
  the ~10 `PHASE-13A-*`/`PHASE-13B-*` reports are **not** official
  sub-phases of roadmap Phase 13. They are relabeled, in substance, as
  Phase 4 (Reconciliation) / Phase 9 (Offline/degraded mode) lineage. The
  roadmap's 0–14 sequence is explicitly stated as unchanged. This does
  **not** shift what "Phase 13" means going forward: it remains
  `docs/15-CODING-PHASES.md` item 13, "Failure/security testing," with no
  work done under that correct meaning yet.
- The "Open" list (exact auth implementation, frontend versions,
  WebSocket vs SSE, backup retention, exact PostgreSQL host/IP/db,
  TLS/domain, NetBird/firewall rules) are all Phase 14
  (production-deployment)-shaped infrastructure/ops decisions, not
  earlier-phase functional gaps — none of them blocks starting Phase 13.
- The "Open — new candidate requirements" section (auto-reply bot,
  esamsat integration, blast templates, user-manager/handoff) is
  explicitly marked "not yet phased" and is excluded from this task per
  the user's own instructions — not discussed further here.

**Cross-checked against `docs/generated/*.md` (110 files, globbed
fresh).** Three reports confirm the three closures the task's context
summary described, each independently re-verified here by reading the
report body (not just its title):

1. **Phase 9 (Offline/degraded mode) — now COMPLETE.**
   `docs/generated/PHASE-9-OFFLINE-DEGRADED-MODE-COMPLETION-REPORT.md`
   closes both gaps `PHASE-ROADMAP-STATUS-AUDIT-REPORT.md` had left open
   (`SessionsPage.tsx` connectivity handling, `DashboardPage.tsx`
   reconciliation sync-status card), reusing the existing
   `InboxPage.tsx` pattern verbatim. `npm run lint`/`npm run build` both
   clean; git diff confined to `DashboardPage.tsx/.css`,
   `SessionsPage.tsx/.css`.
2. **Phase 12 (Security hardening) — 6/6 MUST-FIX items CLOSED.**
   `docs/generated/PHASE-12-SECURITY-HARDENING-IMPLEMENTATION-REPORT.md`:
   scope-gated Dashboard/SyncStatus views behind `HasReadingScope`,
   fail-closed `DJANGO_SECRET_KEY` when `DEBUG=False`, login audit
   logging (success+failure, password never logged), bounded
   `LoginSerializer` field lengths, rate limiting on both Django
   (`DRF` throttles, Redis cache backend, 5/min IP-keyed login throttle)
   and BFF (`express-rate-limit`, 300/min on `/api`), and a documentation
   fix stating the BFF network-exposure reality project-wide. Full
   backend suite 439/439 (later 447/447, see below), BFF 125/125, both
   confirmed re-run in that report. **OBSERVATION items were explicitly
   out of scope and confirmed untouched**: JWT key-rotation, SSL/HSTS
   (correctly deferred behind the still-open TLS/domain decision),
   BFF message-length bound, `.gitignore`/committed-`.env`
   re-verification, dependency-CVE audit. Re-checked the original
   `PHASE-12-SECURITY-HARDENING-DESIGN-AUDIT-REPORT.md`'s own
   "Consolidated OBSERVATION list" (Section 6): none of its five items is
   framed as blocking further progression — each is either explicitly
   "acceptable for this project's scale," "correctly sequenced" pending
   a different open decision, or "fold in only if [X] isn't already
   closed." **The OBSERVATION/non-blocking classification holds; nothing
   was silently expected to gate Phase 13.**
3. **Phase 4/9 follow-up — `reconcile_session()` stuck-`RUNNING` bug
   CLOSED.** `docs/generated/PHASE-4-9-CELERY-WORKER-LIVENESS-IMPLEMENTATION-REPORT.md`
   adds an `is_final_attempt` parameter threaded from
   `self.request.retries >= self.max_retries` (computed at the Celery
   task level) down through `reconcile_session()`/
   `run_targeted_reconciliation_with_retry()`, so any unhandled exception
   on the genuinely-final attempt now reaches `STATUS_ERROR` with a safe
   message instead of leaving the checkpoint stuck at `RUNNING` forever.
   `apps.sync` suite 171/171, full suite 447/447. **Verified this task
   that the working tree matches the report**: `git diff --stat` on
   `backend/apps/sync/{executors.py,reconciliation.py,tasks.py,tests/test_reconciliation.py,tests/test_tasks.py}`
   shows exactly the file set the report claims (264 insertions / 41
   deletions across 5 files) — the fix is real and present in the
   working tree, currently uncommitted per `git status`.

**No other earlier-phase gap was found.** Blast (Phase 11) is explicitly
excluded from re-scoping per this task's instructions and was not
re-examined beyond citing its existing, closed status.

**Conclusion: the next official phase is confirmed as 13 — "Failure/security
testing."** No new phase number was invented; no earlier gap remains that
would block starting it.

---

## 2. Step 2 — Phase 13's scope, synthesized from project docs

`docs/15-CODING-PHASES.md` itself gives zero elaboration beyond the name
(confirmed, re-read). The elaborating sources:

**`docs/09-TEST-PLAN.md`** (the only doc with a dedicated, itemized list
for this phase's subject matter) — read in full:

- **Failure** (8 named scenarios): (1) office server off — WAHA remains
  working, live ops remain possible, office shows offline; (2) PostgreSQL
  off — DB health fails, persistence/retry behavior is safe; (3) Redis
  off — background jobs fail visibly, WAHA remains independent; (4)
  BFF/WAHA off — live features unavailable with exact failure domain; (5)
  network partition in both directions; (6) duplicate webhook produces no
  duplicate durable message; (7) recovery reconciles missing data; (8)
  ambiguous outbound result does not cause duplicate send.
- **Security**: frontend cannot obtain the WAHA key; unauthorized actions
  return 401/403; BFF rejects arbitrary URLs; DB is not public; secrets
  are absent from logs.

**`docs/06-SECURITY.md`** (re-read in full this task) — **has no
testing-specific section distinct from the hardening requirements Phase
12 already addressed.** It is entirely architectural/requirement-shaped
(Zones, Secrets, WAHA flow, Authorization, Network — including the
Phase-12-added "Current BFF network-exposure reality" note, SSRF, Rate
limits, Audit, Database), never itself prescribing *how* to test any of
it. `docs/09-TEST-PLAN.md`'s "Security" list is the closest thing to a
testing-specific elaboration, and it maps one-to-one onto
`docs/06-SECURITY.md`'s own requirement bullets (WAHA-flow/Secrets →
"frontend cannot obtain WAHA key"; Authorization → "401/403"; SSRF →
"BFF rejects arbitrary URLs"; Database → "DB not public"; Secrets →
"absent from logs"). No independent testing scope exists beyond
verifying those same requirements are actually true.

**`docs/01-ARCHITECTURE.md`**'s "Failure isolation" section states the
governing principle directly: "Office outage tidak boleh otomatis
mematikan Tencent/WAHA. PostgreSQL outage tidak boleh dianggap sebagai
WAHA outage" — this is Test Plan Failure scenarios 1 and 2, stated as an
architectural invariant Phase 13 must verify holds in practice, not just
in design intent.

**`docs/05-WEBHOOK-SYNC-DESIGN.md`** names three specific scenarios
Phase 13 should verify: office outage (WAHA keeps operating, webhook
delivery may fail, live messages stay accessible via WAHA — Failure
scenario 1); recovery (reconciliation job must be repeatable, paginated,
transaction-aware, duplicate-safe — Failure scenario 7); outbound during
outage (idempotency key required, never blindly resend an operation of
uncertain success — Failure scenario 8).

**`docs/02-REQUIREMENTS.md`**'s Reliability section (duplicate-safe
webhooks, recovery after backend outage, idempotent outbound operations,
clear stale/live state) and Security section restate the same items as
top-level requirements — confirms Phase 13's job is to *verify* these
already-stated requirements hold under real failure/attack conditions,
not to invent new requirements.

**Net: Phase 13's scope is exactly `docs/09-TEST-PLAN.md`'s Failure (8
items) and Security (5 items) sections — no broader or narrower scope is
implied anywhere else in the docs.**

---

## 3. Step 3 — Already covered vs. genuinely new

### Already covered, with real evidence (cite, don't re-do)

| Test Plan item | Status | Evidence |
|---|---|---|
| Failure #6 — duplicate webhook, no duplicate durable message | **Covered (unit-level).** | `backend/apps/webhooks/models.py` `UniqueConstraint(session, provider_event_id)` + `services.py` `get_or_create` on that pair; exercised in `backend/apps/webhooks/tests/{test_ingestion.py,test_views.py,test_models.py}` (confirmed present via grep this task). This is sequential/unit-level idempotency, not true concurrent-request idempotency — see "genuinely new" below. |
| Failure #7 — recovery reconciles missing data | **Covered (unit-level, plus the stuck-checkpoint fix).** | `docs/generated/PHASE-4-RECONCILIATION.md` (original design/build) + this session's own `PHASE-4-9-CELERY-WORKER-LIVENESS-IMPLEMENTATION-REPORT.md` (closes the one correctness gap: `reconcile_session()` now always reaches a terminal status). `apps.sync` suite: 171/171. Never exercised as a live "kill office, bring it back, watch reconciliation actually backfill against a real WAHA/Postgres" drill. |
| Failure #8 — ambiguous outbound result, no duplicate send | **Covered (backend logic + frontend surfacing).** | `docs/generated/PHASE-11-BLAST-END-TO-END-AUDIT-REPORT.md` Section 5 traces the `OutboundOperation` idempotency-key defense-in-depth (DB `UniqueConstraint` on `(session, idempotency_key)`) end-to-end with passing tests; `docs/generated/PHASE9-0-UNKNOWN-SEND-OUTCOME-IMPLEMENTATION-REPORT.md` closes the frontend gap where an `'unknown'` WAHA/BFF outcome was silently treated as "no send attempted." Blast-specific worker-death/BFF-timeout/WAHA-error/race scenarios are fully tabulated in that same E2E audit (PASS for BFF timeout, WAHA error response, approve-race, duplicate-in-list; one FAIL — a `sending`-forever recipient if a worker dies mid-send — subsequently closed by `PHASE-11-BLAST-STUCK-RECOVERY-IMPLEMENTATION-REPORT.md`). This is Blast-specific evidence (out of scope to re-open per this task's exclusions), cited here only as a precedent for the *general* idempotency mechanism Phase 13 would otherwise need to re-verify from scratch. |
| Security — unauthorized actions return 401/403 | **Covered (unit-level).** | Phase 12's scope-gate tests (`HasReadingScope` 403 tests on Dashboard/SyncStatus views) and pre-existing `apps.chats`/`apps.blast` scope tests. |
| Security — rate limiting triggers correctly | **Covered (unit-level).** | Phase 12's `test_login_burst_beyond_the_configured_rate_returns_429`, `test_rate_limit_applies_per_ip_regardless_of_credentials_tried` (Django) and `bff/test/rateLimit.test.ts` (5 tests, BFF). |
| Security — frontend cannot obtain the WAHA key | **Covered (structural + repeatedly audited).** | WAHA key is server-side only (`bff/src/config.ts`), never referenced in `frontend/`; confirmed by multiple prior source audits (`GITHUB-SECURITY-AUDIT.md`, Phase 6 reports, this task's own re-check of `docs/06-SECURITY.md`). |
| Security — BFF rejects arbitrary URLs | **Covered (structural).** | `bff/src/wahaAllowlist.ts`'s explicit `WAHA_ALLOWED_ENDPOINTS` map, structurally enforced (only `callWaha()` dispatches, only from this map) — satisfies hard rule 5, confirmed by multiple prior audits. |

### Genuinely new / unexercised — Phase 13's real, distinct work

1. **Failure scenarios 1–5 (office off, PostgreSQL off, Redis off,
   BFF/WAHA off, network partition)** — **zero live evidence exists
   anywhere in this repo.** `docs/generated/PHASE-ROADMAP-STATUS-AUDIT-REPORT.md`
   Section 6/8 states this plainly and it remains true today: every
   "audit" in `docs/generated/` is a static source read, and dozens
   explicitly disclaim "no container was started, stopped, or
   restarted" in their own header (this report does too). These 5
   scenarios are structurally *designed for* (Section 2's architecture
   citations) but never dynamically verified. This is the core of
   Phase 13's distinct, unaddressed scope.
2. **Duplicate webhook under real concurrent load** — the existing
   evidence (`get_or_create` + `UniqueConstraint`) is correct by
   construction and unit-tested sequentially, but no test has ever fired
   genuinely concurrent identical webhook deliveries at a live endpoint
   to confirm the DB constraint (not just Django's single-threaded test
   client) is what actually prevents the duplicate under real race
   timing.
3. **Auth/authz negative-testing as a living exercise, not only unit
   tests** — actually sending requests with invalid/expired/wrong-scope
   tokens against a running dev BFF/Django instance over real HTTP (as
   opposed to Django's `APITestCase` client or BFF's in-process
   `supertest`/mocked-fetch harness), and actually triggering the
   Phase 12 rate limiter over real network calls.
4. **Secrets absent from logs** — **no evidence found anywhere** that
   this has ever been checked, live or statically. Not mentioned as
   verified or even attempted in any prior report.
5. **DB not public / least-privilege DB user** — repeatedly marked "NOT
   VERIFIED" across every prior audit that touched it (it is
   infrastructure/ops state outside the repo, per `docs/CLAUDE.md`'s own
   framing of PostgreSQL as "existing infrastructure").

---

## 4. Step 4 — Compact design-scoping pass (what would need to be built/run)

Given the volume of prior audit work already cited in Section 3, no
further from-scratch investigation is warranted. Two clearly distinct
tracks of *new* work emerge:

**Track A — non-disruptive, can be scoped as ordinary test-writing work**
(no live container lifecycle changes; only sends additional HTTP
traffic to already-running dev services, or performs static log/config
review):
- A live-HTTP auth/authz negative-test pass against the running dev BFF
  + Django (item 3 above).
- A live rate-limit burst test over real HTTP against the running dev
  BFF/Django (extends Phase 12's unit tests to a real network path).
- A true-concurrency duplicate-webhook test (item 2) — e.g. firing N
  parallel identical webhook payloads at the real dev webhook endpoint.
  This generates real traffic and real DB rows but does not stop or
  restart anything, and is reversible (test data only).
- A log/config review for secret leakage (item 4) — grep container logs
  and config output for the WAHA key, JWT secret/private key, DB
  password. **Caution for whoever executes this**: any report produced
  must redact matches, never paste live secret material into a
  `docs/generated/*.md` file.
- Least-privilege DB user / DB-not-public (item 5) — likely resolvable
  by asking the user directly for the real Postgres role's grants
  (`\du`/`GRANT` output) rather than a live drill, since this project's
  DB is existing infrastructure outside repo control.

**Track B — live/disruptive failure-injection drills** (items 1–5's
office/Postgres/Redis/BFF/WAHA-off and network-partition scenarios):
this requires actually stopping containers in the dev stack
(`infrastructure/development/*.yml` — Postgres/Redis/BFF/WAHA/Django/
Celery services) or simulating a network partition (e.g. `docker network
disconnect`), then observing behavior against the specific claims in
`docs/01-ARCHITECTURE.md`'s failure-isolation section and
`docs/05-WEBHOOK-SYNC-DESIGN.md`. **This is materially more invasive
than anything performed in this session to date** — every prior "audit"
this session has produced, including this one, has been a static
source-only read; no container has been stopped or restarted at any
point in the Phase 9/11/12/4-9-followup work cited above. Track B is
flagged per this task's Step 4 instruction and is **not performed by
this audit task**.

---

## 5. Recommended minimal first-slice scope for starting Phase 13

1. Start with **Track A** in full — it requires no special
   infrastructure risk, closes 4 of the 5 "genuinely new" items from
   Section 3, and follows the same "read source, write/run targeted
   tests, report" pattern every phase so far in this session has used.
2. Defer **Track B** (Failure scenarios 1–5, the actual container-kill
   drills) until the user has made the Section 6 decision below. If
   approved, scope it as its own dedicated task — not folded into Track
   A — given the different risk profile and the need for an explicit
   rollback/recovery plan (confirm the dev stack fully recovers after
   each drill) before starting.
3. Likely files/areas involved:
   - `backend/apps/webhooks/` (duplicate-delivery concurrency test),
     `backend/apps/authn/` (login/rate-limit live tests),
     `bff/src/middleware/rateLimit.ts`, `bff/src/wahaAllowlist.ts`
     (live negative tests against real allowlist enforcement).
   - `infrastructure/development/*.yml` — the dev Compose stack that
     would be the target of any Track B drill (not touched by Track A).
   - `docs/09-TEST-PLAN.md` remains the scope source of truth; no
     change to it is implied by this report.
   - Whichever new test files/scripts get created (a natural home would
     be a new `backend/apps/*/tests/test_live_*.py`-style or
     standalone-script location, or `bff/test/` — exact placement is
     an implementation decision, not resolved here).

---

## 6. Risks

- **Track B (disruptive) risk**: stopping Postgres/Redis/BFF/WAHA/
  backend containers in the shared dev stack could interfere with any
  other work relying on that stack being up (this session's own
  uncommitted `backend/apps/sync/*` changes are file-based and would
  survive a container restart, but any *other* in-progress manual
  verification would not). A drill must have a clear
  restart/rollback plan and should not be attempted without confirming
  no other work depends on the stack's current running state.
- Live failure-injection could produce a stack that doesn't cleanly
  recover (e.g., a Celery worker left in a bad state, a stuck
  `SyncCheckpoint` — ironically the exact scenario this session just
  fixed the root cause of, though the fix only guarantees a *reachable*
  terminal state, not that recovery is instant).
- Secret-leakage log review (Track A) must avoid re-exposing any secret
  it finds — findings should be reported as "leak found in file X,
  redacted" not quoted verbatim.
- True-concurrency webhook test could, if misconfigured, write real
  test rows against the real dev PostgreSQL instance (existing
  infrastructure, not a throwaway container) — should target a
  disposable session/test identifier, not real production-shaped data,
  and should be reviewed against hard rule 1/2 (no new Postgres service,
  no public exposure) even though it only *uses* the existing DB rather
  than provisioning one.

---

## 7. USER DECISIONS REQUIRED

Per the user's own instruction ("tanyakan hanya keputusan yang
benar-benar diperlukan") — only two genuinely undecided items were
found; everything else in this report follows unambiguously from
existing docs/decisions:

1. **Are live/disruptive failure-injection drills (Track B — stopping/
   restarting the dev Postgres/Redis/BFF/WAHA/backend containers,
   simulating a network partition) in scope and approved for Phase 13,
   or should Phase 13 remain a testing-only pass (Track A: live HTTP
   negative-tests, concurrency tests, and log/config review against the
   already-running dev stack, without touching container lifecycle)?**
   This is the one decision this report cannot make unilaterally, per
   its own STOP condition and this task's explicit instruction not to
   perform any such action itself.
2. **Should Phase 13 produce new permanent automated tests** (e.g. a
   live/integration test suite exercising Phase 12's rate limits and the
   Test Plan's failure/security scenarios, checked into the repo
   long-term) **or remain a one-off audit-and-report exercise**, matching
   the pattern most of this session's prior phases have used (write a
   report, optionally close specific findings, no lasting test
   infrastructure added beyond each fix's own unit tests)?

No decision is required on *whether* Phase 13 is next (Section 1,
unambiguous) or on its documented scope (Section 2, unambiguous from
`docs/09-TEST-PLAN.md`).

---

## 8. Explicit stop

This was a scoping audit only. Nothing was implemented, no live or
disruptive action was performed, and no file other than this report was
created or modified.
