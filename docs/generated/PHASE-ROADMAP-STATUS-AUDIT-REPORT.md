# Phase Roadmap Status Audit Report

**Read-only audit.** No source, config, migration, Docker, Compose, or
dependency file was modified. No container was started, stopped, or
restarted. No migration, Celery task, reconciliation run, or WAHA write
endpoint was triggered. The only file created by this task is this
report.

**Relationship to prior reports**: `docs/generated/NEXT-PHASE-ROADMAP-AUDIT-REPORT.md`
exists and covers similar ground but predates all Phase 11 (Blast) and
Phase "13.A"/"13.B" work — at the time it was written it correctly found
Blast had **zero** implementation. It was read for context (Step 1/2 of
this task) but every claim below was independently re-verified against
current source, not carried over from it or any other report. This
report does not overwrite it; it is a new, separate, more rigorous
document per this task's explicit instruction.

Status classification used throughout: **VERIFIED FROM SOURCE** (I read
the actual code/config/test and cite file:line), **INFERRED** (reasoned
from verified facts but not a direct citation), **NOT VERIFIED** (could
not be confirmed either way from available evidence).

---

## 1. Official Roadmap Sequence (verbatim, `docs/15-CODING-PHASES.md`)

```
0. Repository skeleton
1. Backend foundation
2. Database models + migrations
3. Webhook ingestion
4. Reconciliation
5. Celery/Redis
6. BFF
7. Frontend foundation
8. Inbox/chat
9. Offline/degraded mode
10. Session management
11. Blast
12. Security hardening
13. Failure/security testing
14. Production deployment

Each phase must pass relevant tests before the next phase.
```
**VERIFIED FROM SOURCE** — re-read in full this task; unchanged from
prior audits.

No other doc under `docs/` redefines this list. `docs/00-MASTER-SPEC.md`,
`docs/10-CLAUDE-CODING-GUIDE.md`, `docs/CLAUDE.md` reference it but add
no phase detail. `docs/02-REQUIREMENTS.md`, `docs/06-SECURITY.md`,
`docs/09-TEST-PLAN.md`, `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`,
`docs/04-DATA-MODEL.md` elaborate individual phases' required scope (used
in Sections 5–6 below). `docs/02-REQUIREMENTS.md` and
`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` both carry a
"(2026-09-26, not yet phased)" section listing five new candidate
requirements (auto-reply bot, esamsat integration, blast templates, user
manager/handoff) that are **explicitly not part of any numbered phase
yet** — VERIFIED FROM SOURCE, both docs state this in their own text.

---

## 2. Evidence Inventory (`docs/generated/*.md`, 108 files)

Full listing obtained via `ls docs/generated/`. Grouped by what each
claims to cover (title-level only — not trusted as proof of completion,
per Step 3):

- **Phase 0**: `PHASE-0-ARCHITECTURE-VALIDATION.md`, `PHASE-0-DOCUMENTATION-AUDIT.md`.
- **Phase 2.5 / 3**: `PHASE-2.5-LID-JID-VERIFICATION.md`, `PHASE-3-WEBHOOK-INGESTION.md`, `PHASE-3-LIVE-VERIFICATION.md`.
- **Phase 4**: `PHASE-4-RECONCILIATION.md`.
- **Phase 5**: `PHASE-5-CELERY-REDIS.md`, `PHASE-5-LIVE-VERIFICATION.md`.
- **Phase 6 (BFF)**: 11 files (`PHASE-6-ARCHITECTURE-CONTRACT.md` … `PHASE-6-WAHA-LIFECYCLE-VERIFICATION.md`) — architecture decisions, spec review/resolution, implementation, post-audit fix, blocker resolution.
- **Phase 7 (frontend foundation)**: `PHASE-7-IMPLEMENTATION-REPORT.md`, `PHASE-7-CORS-FIX-REPORT.md`, `PHASE-7-ENV-LOADING-FIX-REPORT.md`, `PHASE-7-VISUAL-FIDELITY-REPORT.md`.
- **Phase 8 (Inbox/chat + Dashboard)**: `PHASE-8-DASHBOARD-*` (3 files), `PHASE-8C-*` (4 files), plus 13 `INBOX-*` files (audit, findings, implementation, identity display, outbound reconciliation trigger debugging across 4 iterations, webhook fix).
- **Phase 9 (offline/degraded mode) lineage**: `PHASE9-*` (13 files: design audits 9-1/9-1A/9-1C/9-1E/9-1F, implementations for 9.0, 9.1A, 9.1C, 9.1D, 9.1E, 9.1F), `PHASE-9-1B-*` (2 files), `PHASE-9-ROADMAP-AUDIT-REPORT.md`, `NEXT-SESSIONS-CONNECTIVITY-*` (2 files), `NEXT-PHASE-POSSIBLY-STUCK-DETECTION-*` (2 files), `NEXT-PHASE-CELERY-WORKER-LIVENESS-DESIGN-AUDIT-REPORT.md`, `NEXT-PHASE-CELERY-TASK-CORRELATION-*` (2 files), `NEXT-PHASE-RECONCILIATION-OBSERVABILITY-*` (2 files), `NEXT-PHASE-RECONCILIATION-RECOVERY-DESIGN-AUDIT-REPORT.md`, `PHASE-A-RECONCILIATION-EXECUTOR-IMPLEMENTATION-REPORT.md`, `CURRENT-STATE-AND-PHASE9-READINESS-AUDIT-REPORT.md`.
- **Phase 10 (session management)**: `SESSION-MANAGEMENT-*` (5 files).
- **Phase 11 (Blast)**: `PHASE-11-BLAST-DESIGN-AUDIT-REPORT.md`, `-BACKEND-IMPLEMENTATION-REPORT.md`, `-FRONTEND-IMPLEMENTATION-REPORT.md`, `-END-TO-END-AUDIT-REPORT.md`, `-STUCK-RECOVERY-IMPLEMENTATION-REPORT.md`.
- **"Phase 13.A"/"13.B"** (reconciliation-recovery lineage, see Section 7 — **not** the official Phase 13): `PHASE-13A-MANUAL-RECONCILIATION-RECOVERY-IMPLEMENTATION-REPORT.md`, `PHASE-13B-RECONCILIATION-DIAGNOSTICS-UI-DESIGN-AUDIT-REPORT.md`, `PHASE-13B-RECONCILIATION-DIAGNOSTICS-UI-IMPLEMENTATION-REPORT.md`.
- **Dev environment (informal "Phases A–G")**: `PHASE-B/C/D/E/F/G-*` (10 files), `DOCKER-ENVIRONMENT-ARCHITECTURE-AUDIT-REPORT.md`.
- **Security/infra audits (not a dedicated Phase 12 pass)**: `GITHUB-SECURITY-AUDIT.md`, `GITHUB-PUBLICATION-REMEDIATION.md`, `INTERNAL-SERVICE-AUTH-AUDIT-REPORT.md`, `INTERNAL-SERVICE-KEY-FINGERPRINT-AUDIT-REPORT.md`.
- **General roadmap surveys**: `NEXT-DEVELOPMENT-AUDIT-REPORT.md`, `NEXT-PHASE-ROADMAP-AUDIT-REPORT.md` (superseded by this report, per task instructions).

No file anywhere is titled or scoped as "Phase 12" or (in the official
sense) "Phase 14." No file performs failure-injection testing (killing a
container and observing behavior against `docs/09-TEST-PLAN.md`'s
Failure section) — all "audits" in this repo are static/read-only source
audits, not the dynamic failure-injection testing the roadmap's Phase 13
name implies (see Section 8).

---

## 3. Phase 0–14 Status Table

| # | Phase | Status | Evidence (VERIFIED FROM SOURCE unless noted) |
|---|---|---|---|
| 0 | Repository skeleton | **COMPLETE** | Top-level `frontend/`, `bff/`, `backend/`, `infrastructure/`, `docs/` all exist (`ls` this task), matching `docs/00-MASTER-SPEC.md`/`docs/CLAUDE.md` scope list and `docs/14-REPOSITORY-STRUCTURE.md`. |
| 1 | Backend foundation | **COMPLETE** | `backend/manage.py`, `backend/config/settings.py` (`INSTALLED_APPS` lists 9 first-party apps + DRF + corsheaders, `settings.py:59-78`), `backend/config/celery.py`, `backend/Dockerfile` all present and non-trivial. |
| 2 | Database models + migrations | **COMPLETE** | Every `docs/04-DATA-MODEL.md` suggested entity except `Role`/`Permission`/`MediaReference`/`SystemHealthSnapshot` has a matching model class, confirmed by grep for `class X(` across `backend/apps/*/models.py`: `WahaSession`, `Chat`, `Message` (`apps/chats`), `WebhookEvent` (`apps/webhooks`), `SyncCheckpoint` (`apps/sync`), `OutboundOperation` (`apps/operations`), `AuditLog` (`apps/audit`), `BlastCampaign`/`BlastRecipient` (`apps/blast`). Every app with a model has a non-empty `migrations/` directory (`0001_initial.py` at minimum; `chats`, `sync`, `webhooks` have follow-up migrations). `Role`/`Permission`/`MediaReference`/`SystemHealthSnapshot` were never implemented as separate models — INFERRED this is an intentional simplification (JWT scopes substitute for Role/Permission; media/health are out of current scope), not verified as a documented decision anywhere. |
| 3 | Webhook ingestion | **COMPLETE** | `backend/apps/webhooks/models.py:47-48` — `UniqueConstraint(fields=['session','provider_event_id'], name='unique_webhook_event_per_session')`; `services.py:31,44` — ingestion uses `get_or_create` on that same pair, docstring states "Idempotency: WebhookEvent.get_or_create on (session, provider_event_id)". HMAC verification present: `apps/webhooks/authentication.py` — `verify_waha_webhook_signature()`, HMAC-SHA512, `hmac.compare_digest`, fails closed if secret/header missing. Satisfies hard rule 6 (idempotent webhooks). |
| 4 | Reconciliation | **COMPLETE, with one open correctness gap carried forward** | `backend/apps/sync/reconciliation.py:155` `reconcile_session()` exists, writes `SyncCheckpoint.STATUS_RUNNING` then does fetch/parse/persist then a terminal `STATUS_OK`/`STATUS_ERROR` write. Re-confirmed this task: the block between the RUNNING write (line 198) and the terminal write is **not** wrapped in `try/finally` — a hard worker kill or exhausted Celery retries leaves a checkpoint stuck at `RUNNING` forever with no self-healing. This gap is independently mitigated (not fixed) by the "possibly_stuck"/Phase-13.A-labeled manual-recovery work (Section 7) — a human can now un-stick it, but nothing auto-resets it. Core reconciliation logic itself is functional and tested. |
| 5 | Celery/Redis | **COMPLETE** | `backend/config/celery.py` defines the Celery app; `apps/sync/tasks.py`/`apps/blast/tasks.py` use `@shared_task`; `infrastructure/development/office.yml` defines `celery-worker`, `celery-beat`, `redis:7-alpine` services with healthchecks, alongside `backend`. `apps/core/views.py` has `RedisHealthView`. Confirmed wired; NOT VERIFIED whether the dev or production stack is actually running right now (out of scope — read-only audit, no `docker ps` state change permitted, and this task did not check current container state). |
| 6 | BFF | **COMPLETE** | `bff/src/app.ts:20-27` mounts `healthRouter`, `sessionRouter` (`/api`), `messagesRouter` (`/api`), `internalBlastRouter` (`/internal`). `bff/src/wahaAllowlist.ts` — explicit `WAHA_ALLOWED_ENDPOINTS` record (8 named endpoints only), structurally enforced (only `callWaha()` can dispatch, and it only accepts a key from this map) — satisfies hard rule 5 (explicit allowlist, not a generic proxy). |
| 7 | Frontend foundation | **COMPLETE** | `frontend/package.json` (React 19), `vite.config.ts`, `tsconfig.json`/`tsconfig.app.json`/`tsconfig.node.json`, `src/App.tsx`, `src/routes/`, `src/lib/`, `src/theme/` all present. |
| 8 | Inbox/chat | **COMPLETE** | `frontend/src/pages/InboxPage.tsx` (575 lines) — send/reply, polling, `SendFeedback` with an `'unknown'` outcome kind. Backed by `apps/chats` (models + `api_urls.py`) per the prior session's own webhook/outbound-reconciliation debugging trail (13 `INBOX-*` reports document a real, iteratively-fixed feature, not a stub). |
| 9 | Offline/degraded mode | **PARTIAL** | Substantial, genuinely-wired signal surface exists and is source-confirmed this task: `InboxPage.tsx` — `ConnectivityIssue` type (`'unreachable'\|'unauthorized'`), `reportPollOutcome()`, `syncStatus` state wired to `GET /api/sync/status/<session>/`, a `<StatusBadge>` next to the page title, and (newly confirmed this task, not in the prior audit) `syncStatus.possibly_stuck` is now read and rendered (`InboxPage.tsx:377-384`). `DashboardPage.tsx` has a Redis health card and a WAHA `SessionsCard`. **However**, `SessionsPage.tsx` has **zero** matches for `ConnectivityIssue`/`reportPollOutcome` (grepped this task) — the Inbox's degraded-mode pattern was never extended there, and `DashboardPage.tsx` has zero matches for `getSyncStatus`/`SyncStatus` — no reconciliation-health card on the Dashboard (both gaps independently confirmed by the superseded prior audit and re-confirmed unchanged this task). Phase 9 is functionally substantial but not fully and consistently applied across all three frontend surfaces that show connectivity/sync state. |
| 10 | Session management | **COMPLETE** | `frontend/src/pages/SessionsPage.tsx` (376 lines) exists; `bff/src/routes/session.ts` + `sessionGuard.ts` back it directly against WAHA (by design — `waha_sessions` Django app deliberately has no `urls.py`, confirmed via directory listing, matching the architecture where live session control goes through the BFF, not Django). 5 dedicated `SESSION-MANAGEMENT-*` reports document status-sync and button-guard fixes. |
| 11 | Blast | **COMPLETE for the officially-scoped v1** (see Section 6 for the exact boundary) | `backend/apps/blast/` (models, tasks, views, serializers, limits, bff_client — 164-line `models.py`, non-trivial `tasks.py`), `bff/src/routes/internalBlast.ts`, `frontend/src/pages/{BlastListPage,BlastCreatePage,BlastDetailPage}.tsx`. End-to-end audit (`PHASE-11-BLAST-END-TO-END-AUDIT-REPORT.md`) traced every hop Frontend→Django→Celery→BFF→WAHA with file:line citations and re-ran the test suites itself (63/63 Django, 120/120 BFF, stated as re-run "this task" in that report, not merely cited). The one FAIL that audit found (a recipient stuck in `sending` forever if a worker dies mid-send, with no recovery path) was subsequently closed by `PHASE-11-BLAST-STUCK-RECOVERY-IMPLEMENTATION-REPORT.md`. |
| 12 | Security hardening | **PENDING** | No dedicated hardening-pass report exists anywhere in `docs/generated/`. Grep for `RateLimit\|throttle\|SECURE_\|CSRF\|Content-Security-Policy\|helmet` across `backend/` and `bff/` finds only Blast's own domain-specific rate limiting (`apps/blast/tasks.py`, `apps/blast/tests/test_tasks.py`) and CORS config (unrelated to hardening) — no generic Django `SECURE_*` settings, no DRF throttle classes, no `helmet`/`express-rate-limit` in `bff/`. Every one of 6 separate reports (`CURRENT-STATE-AND-PHASE9-READINESS-AUDIT-REPORT.md`, `NEXT-DEVELOPMENT-AUDIT-REPORT.md`, `NEXT-PHASE-ROADMAP-AUDIT-REPORT.md`, `PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md`, `PHASE-6-IMPLEMENTATION-REPORT.md`, `PHASE-6-POST-AUDIT-FIX-REPORT.md`, `PHASE-6-POST-IMPLEMENTATION-AUDIT.md`, `PHASE-7-IMPLEMENTATION-REPORT.md`) that mentions "Security Hardening" refers to it explicitly as **Phase 12, not yet done, deferred**. See Section 5 for the detailed requirement-by-requirement breakdown. |
| 13 | Failure/security testing | **PENDING (as officially scoped)** | No dynamic failure-injection testing (killing PostgreSQL/Redis/BFF/WAHA containers and observing behavior, per `docs/09-TEST-PLAN.md`'s Failure section items 1–8) exists anywhere — every audit in this repo is a static source-read, not a live chaos/failure test. The "13.A"/"13.B" labeled work that does exist is reconciliation-recovery and diagnostics-UI work, not failure-injection or security testing — see Section 7 for why this is NOT the same thing as official Phase 13, despite the name collision. |
| 14 | Production deployment | **PENDING (tooling exists, deployment does not)** | `infrastructure/tencent/` contains only `docker-compose.yml` (923 bytes) + `.env.example`; `infrastructure/office/` the same (`docker-compose.yml` 944 bytes + `.env.example`). No deployment runbook execution log, no DNS/TLS setup evidence, no record of an actual production `docker compose up` having been run against real servers. `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`'s "Open" list still includes "TLS/domain" and "NetBird/firewall rules" as unresolved. This is deployment *tooling*, not a completed deployment. |

---

## 4. Phase 11 (Blast) — Status Detail

**Core roadmap requirement** (per `docs/02-REQUIREMENTS.md` "controlled
blast" + `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` decision 12) —
verified this task:

| Requirement | Status | Evidence |
|---|---|---|
| Max 100 recipients/campaign | **DONE** | `backend/apps/blast/serializers.py` `validate_recipients` (cited by the E2E audit, `serializers.py:53-57`), enforced at creation, unaddable afterward by construction (no endpoint mutates an existing campaign's recipient list). |
| Max 500 recipients/day/session | **DONE** | `BlastCampaignApproveView.post` (`views.py:169-179`), Jakarta-calendar-day-aware (`limits.py`), tested against a UTC/Jakarta divergence case. |
| 60s delay between messages | **DONE** | `tasks.py:109` `start + timedelta(seconds=index * delay_seconds)`, tested exact (not approximate). Cross-campaign, same-session throttling also enforced (`tasks.py:97-105`). |
| Dispatch queued/throttled (not synchronous loop) | **DONE** | One Celery task per recipient (`apply_async(..., countdown=...)`), not a loop with `sleep` — confirmed by test `test_enqueues_one_dispatch_task_per_recipient_with_matching_countdown`. |
| Admin ("system administration" scope) approval before dispatch | **DONE** | `BlastCampaignApproveView` gated by scope; dispatch only begins after `.delay()` is called from the approve view, not from creation. |
| `blast` JWT scope check live | **DONE** | `backend/apps/authn/permissions.py:48` — `'blast' in claims.get('scopes', [])`, a dedicated permission class distinct from the `system administration` scope used for approval. |
| Idempotent outbound send (hard rule 7) | **DONE** | Deterministic key `blast:{campaign_id}:{recipient_id}` (`models.py:164`), enforced via `OutboundOperation`'s DB-level unique constraint, reused (not a parallel mechanism) from the same infrastructure Phase 3/4 already use. |

**Named gaps / caveats found** (present but explicitly low-severity per
the audit reports themselves, not hidden):
- `BlastRecipient.STATUS_SKIPPED` is declared but never set by any code
  path — dead but harmless (E2E audit Section 2).
- The stuck-`sending` recovery fix is **manual, human-triggered**, not
  automatic — an intentional, explicitly-decided scope boundary, not an
  oversight (`PHASE-11-BLAST-STUCK-RECOVERY-IMPLEMENTATION-REPORT.md`
  Section 1, "finalized decision 6 still stands").
- The E2E audit's own "BFF network-exposure finding" (Section 7, finding
  #3) was explicitly **not** addressed by the stuck-recovery follow-up
  task — still open, not evaluated further by this audit since it falls
  under Phase 12 (Security hardening) scope, not Phase 11.

**Out of official Phase 11 scope** (confirmed, not a gap): the esamsat
API integration, blast message templates, and the 1-minute
esamsat-specific delay are listed in
`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` under "Open — new candidate
requirements (2026-09-26, not yet phased)" — explicitly **not yet
scoped into any numbered phase**, so their absence is not a Phase 11
deficiency.

**Conclusion**: Phase 11 is complete for what the roadmap + decisions
doc actually specify. It is not complete for the newer, informally
captured esamsat/template requirements — but those were never part of
Phase 11's official scope to begin with.

---

## 5. Phase 12 (Security Hardening) — Scope + Status

**Official scope**, assembled from `docs/06-SECURITY.md` (the only doc
that elaborates this phase in any detail — `docs/15-CODING-PHASES.md`
itself gives zero detail beyond the phase name) and
`docs/02-REQUIREMENTS.md`'s "Security" list:

| Requirement (`docs/06-SECURITY.md`) | Status | Evidence |
|---|---|---|
| Authentication | **DONE (incidental, via Phase 6/8)** | JWT-based auth exists across BFF/Django (`apps/authn`, `jwt.ts`). |
| Authorization (session control/reading/sending/blast/user admin/system admin scopes) | **DONE (incidental, via Phase 6/11)** | `JWT_SCOPES` in `settings.py:290-296`; `HasBlastScope`, `HasSystemAdministrationScope`, etc. in `apps/authn/permissions.py`. |
| LAN/NetBird restriction | **NOT VERIFIED / likely PENDING** | This is a network/infra-layer control, not application code — no evidence in `infrastructure/tencent/docker-compose.yml` or `.env.example` of NetBird/firewall config; `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` still lists "NetBird/firewall rules" as Open. |
| Server-side secrets | **DONE (incidental)** | WAHA key, DB creds, HMAC secret, dispatch service key all read from env server-side only; no grep hit for any such secret in `frontend/`. |
| Rate limiting | **PARTIAL** | Only Blast's own domain-specific throttling (recipient caps, 60s spacing) exists. No generic login/send/session-control/sync rate limiting as `docs/06-SECURITY.md`'s "Rate limits" section requires ("Login, send, session control, blast and expensive sync") — grep for DRF throttle classes / `express-rate-limit` returns nothing. |
| Audit (actor/time/action/target/result) | **DONE (incidental, via Phase 3/8/11)** | `apps/audit` app + `AuditLog` model exist and are referenced by Blast/recovery work. |
| Validation | **PARTIAL/INFERRED** | DRF serializers validate Blast input; not audited for coverage across all endpoints in this task (out of scope — would require reading every view). |
| CSRF/XSS protection | **NOT VERIFIED** | No grep hit for `CSRF`/security headers in `backend/` beyond Django's own defaults (not customized); not evaluated for `frontend/` output escaping in this task. |
| SSRF protection | **DONE (incidental, via Phase 6)** | `wahaAllowlist.ts`'s structural allowlist is exactly this control, already built as part of Phase 6. |
| Least-privilege DB user | **NOT VERIFIED** | Cannot be verified from source alone — this is a DB-server-side configuration outside the repo. |

**Conclusion**: every "DONE" above is security-by-construction that
happened to land as a side effect of building Phases 3/6/8/11 — none of
it was the product of a dedicated Phase 12 pass. Rate limiting outside
Blast, LAN/NetBird restriction, CSRF/XSS, and least-privilege DB user
are genuinely unaddressed or unverifiable. **Status: PENDING**, matching
every prior report's own characterization of Phase 12 as "not yet done."

---

## 6. Phase 13 (Failure/Security Testing) — Scope + Status

**Official scope**, from `docs/09-TEST-PLAN.md`'s "Failure" section (8
named scenarios: office server off, PostgreSQL off, Redis off, BFF/WAHA
off, network partition, duplicate webhook, recovery reconciliation,
ambiguous outbound result) and its "Security" section (frontend cannot
obtain WAHA key, unauthorized actions 401/403, BFF rejects arbitrary
URLs, DB not public, secrets absent from logs).

**Status: PENDING**, as a dedicated phase. None of the 8 failure
scenarios has a report documenting an actual live test (stopping a real
container and observing behavior) — every "audit" report in
`docs/generated/` is a static source-code read, explicitly disclaiming
container starts/stops in its own header (e.g. "No container was
started, stopped, or restarted" appears verbatim in dozens of these
reports, including this one). Some individual scenarios have partial,
incidental coverage as a side effect of other phases' unit tests (e.g.
duplicate-webhook idempotency is unit-tested per-app, satisfying
Failure scenario 6 in isolation) but there is no dedicated Phase 13 body
of work that systematically worked through the Test Plan's list.

---

## 7. The "Phase 13.A" / "Phase 13.B" Origin — Traced

**Finding: these labels are NOT official sub-phases of roadmap Phase 13.
They originated as internal subsection numbers inside a single design
report, and were then informally promoted to "Phase" status by
subsequent report titles — without ever being tied back to
`docs/15-CODING-PHASES.md` item 13.**

Traced precisely, this task:

1. `docs/generated/NEXT-PHASE-RECONCILIATION-RECOVERY-DESIGN-AUDIT-REPORT.md`
   is a design audit about **reconciliation recovery** (what to do about
   a `SyncCheckpoint` stuck at `RUNNING` — continuation of Phase 4/9
   lineage, see the earlier `possibly_stuck` detection work). Its
   **Section 13** is titled "Proposed State Machine" and offers two
   competing framings, labeled **"### 13.A — Derived-only..."** and
   **"### 13.B — Attempt-tracked..."** — i.e., `13` here is that report's
   own internal section number, and `.A`/`.B` are sub-options within
   it, not phase numbers.
2. The very next report, `PHASE-13A-MANUAL-RECONCILIATION-RECOVERY-IMPLEMENTATION-REPORT.md`,
   titles itself "Phase 13.A — Manual Reconciliation Recovery" and
   states it "Implements exactly 13.A from
   `NEXT-PHASE-RECONCILIATION-RECOVERY-DESIGN-AUDIT-REPORT.md`" — this
   is where "Section 13.A" silently became "**Phase** 13.A." No decision
   document, no roadmap edit, and no explicit statement anywhere
   declares "this is roadmap Phase 13's sub-item A."
3. `PHASE-13B-RECONCILIATION-DIAGNOSTICS-UI-DESIGN-AUDIT-REPORT.md` and
   its implementation report continue the pattern for a reconciliation
   **diagnostics UI** — again, not failure-injection testing or security
   testing in the `docs/09-TEST-PLAN.md` sense; it is a frontend feature
   surfacing `possibly_stuck` and a recovery button.
4. Later reports (`NEXT-PHASE-CELERY-WORKER-LIVENESS-DESIGN-AUDIT-REPORT.md`,
   `NEXT-PHASE-CELERY-TASK-CORRELATION-*`,
   `NEXT-PHASE-RECONCILIATION-OBSERVABILITY-*`) all refer back to "Phase
   13.A"/"Phase 13.B" by that name, by now treating it as an established
   fact — but every one of these citations traces back to the same
   single origin in step 1/2 above. No independent decision document
   establishing "13.A"/"13.B" as roadmap sub-phases was found anywhere
   in `docs/`.

**Consequence**: "Phase 13.A"/"Phase 13.B" work is real, substantial,
and well-executed (manual recovery endpoint with compare-and-set
guarding, a diagnostics UI) — but it is **reconciliation
recovery/observability work**, i.e., in substance a continuation of
**Phase 4 (Reconciliation)** and **Phase 9 (Offline/degraded mode)**,
mislabeled with a "13" prefix that collided with — but was never
actually mapped to — the canonical roadmap's item 13
("Failure/security testing"). Roadmap Phase 13 itself, in the sense
`docs/09-TEST-PLAN.md` defines it (dynamic failure injection + security
verification), remains untouched by any of this work.

The same pattern applies to the earlier informal labels the task
mentioned (9.1A–9.1F): those explicitly nest under "9.1" in their own
titles and consistently trace to Phase 9 lineage — a more honest
sub-numbering than 13.A/13.B, which accidentally collides with a
different, unrelated canonical phase number.

---

## 8. Next Official Phase

Per `docs/15-CODING-PHASES.md`'s own closing rule — "Each phase must
pass relevant tests before the next phase" — the honest answer is **not**
simply "12, since 0–11 are done."

**Phase 9 (Offline/degraded mode) is PARTIAL, not COMPLETE** (Section 3):
`SessionsPage.tsx` has no connectivity-issue handling, and
`DashboardPage.tsx` has no reconciliation sync-status card, even though
the pattern is proven and already exists on `InboxPage.tsx`. This is a
real, source-confirmed gap sitting numerically before Phase 11
(Blast, itself complete) and well before Phase 12.

Strictly reading the roadmap's own sequencing rule, the honest next step
is **finishing Phase 9** (extending the existing, already-proven
connectivity/sync-status pattern to `SessionsPage.tsx` and
`DashboardPage.tsx`) before starting Phase 12. This is not a new
finding — the prior (superseded) `NEXT-PHASE-ROADMAP-AUDIT-REPORT.md`
identified the same two gaps independently.

If the project chooses to treat Phase 9's *core* offline/degraded-mode
requirement (clear stale/live state signaling, satisfied on the Inbox
and Dashboard-WAHA-status surfaces) as sufficiently met and the two
missing extensions as optional polish rather than blocking gaps, then
**Phase 12 (Security hardening)** is the next unstarted numbered phase.
**This is a judgment call this report does not make unilaterally** — see
Section 10.

---

## 9. Discrepancies Found

1. **Phase 9 claimed "complete, in substance" by the superseded prior
   report is more accurately PARTIAL.** The prior
   `NEXT-PHASE-ROADMAP-AUDIT-REPORT.md` (Section 3.A) states "Phases
   0–10 are, in substance, complete" for Phase 9, while its own Section
   3.B in the same document lists the Dashboard sync-status card and
   Sessions connectivity extension as "still pending" — an internal
   tension in that report between its summary line and its own detailed
   findings. This audit resolves it explicitly as PARTIAL, not COMPLETE.
2. **"Phase 13.A"/"Phase 13.B" naming implies roadmap-sanctioned status
   it never received.** Traced in Section 7 — a coincidental section-
   number collision, promoted informally across ~10 subsequent reports
   without any decision document ever confirming the mapping to
   canonical Phase 13. The work itself is good, but it is Phase 4/9
   lineage, not Phase 13 lineage.
3. **Phase 4 (Reconciliation)'s stuck-`RUNNING` root cause is still
   unfixed, only mitigated.** `reconcile_session()` still lacks a
   `try/finally` around its fetch/parse/persist block (re-confirmed
   this task, `reconciliation.py:198` onward) — the manual-recovery
   endpoint (mislabeled "13.A") lets an operator clean up after the
   fact, but the underlying gap that causes checkpoints to get stuck in
   the first place remains open.
4. **Phase 12 has been "next" in name across at least 8 separate reports
   spanning Phases 6 through 11, and has still never been started as a
   dedicated pass.** Not a contradiction, just worth naming plainly:
   this is a long-deferred phase, not a recent gap.

---

## 10. USER DECISIONS REQUIRED

1. **Whether to treat Phase 9 as sufficiently complete to proceed
   straight to Phase 12, or to first close the two named gaps**
   (`SessionsPage.tsx` connectivity handling, `DashboardPage.tsx`
   sync-status card) as a formal completion of Phase 9. The roadmap's
   own "each phase must pass relevant tests before the next phase" rule
   supports finishing Phase 9 first; this report does not have the
   authority to decide whether those two items are "relevant" enough to
   block progression, or are optional polish — that is a project
   priority call, not a technical one.
2. **Whether "Phase 13.A"/"Phase 13.B" should be formally retitled**
   (e.g. renamed under a Phase 4/9 sub-numbering, since that is what
   they actually are) **to avoid future confusion with the still-unstarted
   official Phase 13**, or left as-is now that the naming is already
   embedded across ~10 existing report titles. This is a documentation-
   hygiene decision, not a technical blocker, but was explicitly asked
   about by this task and is named here rather than silently resolved.

No decision is required to determine *whether* Phase 12 and Phase 13 (in
the canonical sense) are pending — that is unambiguous from source
(Sections 5–6). The only genuine open call is the sequencing question in
item 1.

---

## 11. Explicit STOP

This was an audit only. Nothing was implemented, no Phase 14 plan was
drafted, and no file other than this report was created or modified.
