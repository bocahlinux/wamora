# WAMORA MASTER ROADMAP — CANONICAL 22 PHASES

**This document is the canonical, current-authority product roadmap for
WAMORA.** It supersedes the informal 15-phase mapping this document
previously contained (preserved below as Section 9, Historical Mapping —
not deleted) and supersedes any phase-status claim in
`docs/15-CODING-PHASES.md` or any `docs/generated/*.md` report where they
now disagree with the evidence below.

`docs/15-CODING-PHASES.md` remains in the repository as the **historical,
original engineering roadmap** (Phase 0–14, a different and now-superseded
numbering) — it is not deleted, not rewritten, and not renumbered. It is
simply no longer the current authority; this document is.

**Last audit date**: 2026-09-28 (this session). **Audit type**: full
repository re-verification (source, migrations, tests, git history,
Docker/Compose, generated reports) — not a re-statement of prior report
titles. Every status below cites its evidence.

**This audit made no code change.** No migration was created or run. No
commit was made. Files changed by this task are listed in Section 10.

---

## 1. Canonical Roadmap (as provided by the project owner)

```
Phase 0  — Foundation / Architecture
Phase 1  — Authentication & Authorization
Phase 2  — WAHA Session Management
Phase 3  — Webhook / Message Ingestion
Phase 4  — Reconciliation
Phase 5  — Inbox
Phase 6  — Frontend
Phase 7  — Multi-Tenant
Phase 8  — Audit / Security
Phase 9  — Session → Office Mapping
Phase 10 — Office Inbox Configuration
Phase 11 — WhatsApp User / WP Office Selection
Phase 12 — WhatsApp Office Selection
Phase 13 — Inbox Lifecycle
Phase 14 — Dynamic RBAC
Phase 15 — Operator Workflow
Phase 16 — Waiting / Offline Automation
Phase 17 — Realtime Inbox
Phase 18 — Blast
Phase 19 — Reports / Analytics
Phase 20 — Audit / Observability
Phase 21 — Production Hardening
Phase 22 — Production Deployment
```

No phase was added, removed, renamed, reordered, merged, or split from
this list. No Phase 23 was created.

---

## 2. Canonical Phase 0–22 Status

Status values used: **COMPLETE**, **PARTIAL**, **NOT STARTED**,
**DEFERRED**, **BLOCKED**, **NEEDS VERIFICATION**.

| # | Name | Status | Evidence | Remaining work |
|---|---|---|---|---|
| 0 | Foundation / Architecture | **COMPLETE** | `frontend/`, `bff/`, `backend/`, `infrastructure/`, `docs/` skeleton; `backend/manage.py`, `config/settings.py`, `config/celery.py`; base `Office`/core models (`apps/offices/migrations/0001_initial.py`). | None identified. |
| 1 | Authentication & Authorization | **COMPLETE** (base mechanism) | JWT issuance/verification (`apps/authn/jwt_utils.py`, `authentication.py`), `LoginView`, `MeView`; scope-checking permission classes (`apps/authn/permissions.py`: `HasReadingScope`, `HasBlastScope`, `HasSystemAdministrationScope`, `HasUserAdministrationScope`); BFF `requireAuth`/`requireScope` (`bff/src/middleware/auth.ts`). | Base auth is done; **Dynamic** (Superadmin-editable) authorization is separately tracked as canonical Phase 14, not here — see that row for why they're split. |
| 2 | WAHA Session Management | **COMPLETE** | `frontend/src/pages/SessionsPage.tsx`, `bff/src/routes/session.ts` + `sessionGuard.ts`; 5 `SESSION-MANAGEMENT-*` reports (status-sync, button-guard fixes). | None identified. |
| 3 | Webhook / Message Ingestion | **COMPLETE** | `apps/webhooks/models.py` `unique_webhook_event_per_session` constraint; `services.py` idempotent `get_or_create`; HMAC-SHA512 verification (`authentication.py`). | None identified. |
| 4 | Reconciliation | **COMPLETE** | `apps/sync/reconciliation.py` `reconcile_session()`; the previously-open "stuck at RUNNING forever" bug is closed (`is_final_attempt` threading, `apps/sync/executors.py`/`tasks.py`, commit `2f18c0d`). | None identified. |
| 5 | Inbox | **COMPLETE** (polling-based; realtime is Phase 17, separately tracked) | `frontend/src/pages/InboxPage.tsx` (700+ lines); `apps/chats` models/views; 13 `INBOX-*` reports. | None for the polling-based scope as built. |
| 6 | Frontend | **COMPLETE** (foundation) | React 19 + Vite + TS project-references build (`tsconfig.json`/`.app.json`/`.node.json` — note: `npx tsc -b --noEmit`, not `tsc --noEmit -p .`, is the command that actually type-checks this project; confirmed the hard way this session), `src/routes/`, `src/lib/`, `src/theme/`. | Ongoing feature pages continue to be added; foundation itself is not in question. |
| 7 | Multi-Tenant | **COMPLETE** | `Office`/`OfficeMembership` models (`apps/offices/models.py`), Office-boundary authorization (`apps/offices/authorization.py`), Office↔Blast integration (`apps/blast/authorization.py`, `BlastCampaign.office`), Office↔Inbox integration (`apps/chats/authorization.py`, `Chat.office`), Office & User management CRUD (`apps/offices/views.py`/`serializers.py`, Settings UI). Internally labeled "Step 1/3/4/5/6" in source comments — a different numbering from this roadmap, see Section 9. | The User-management CRUD UI built here (Step 6) is also reused by canonical Phase 14 (Dynamic RBAC) for Role assignment — one repository feature serving two canonical phases, noted explicitly rather than double-counted. |
| 8 | Audit / Security | **COMPLETE** | `apps/audit` `AuditLog` model; Phase-12-lineage MUST-FIXes: scope-gated Dashboard/Sync views, fail-closed `DJANGO_SECRET_KEY`, login audit logging (success+failure), bounded `LoginSerializer`, Django+BFF rate limiting (`docs/generated/PHASE-12-SECURITY-HARDENING-IMPLEMENTATION-REPORT.md`, 6/6 MUST-FIX closed, full suite re-run 439→447/447). | Monitoring/alerting on top of this audit trail is Phase 20 (Audit/Observability), not this phase. |
| 9 | Session → Office Mapping | **COMPLETE** | `apps/waha_sessions/models.py` `WahaSession.office`, migration `0002_wahasession_office`, `apps/waha_sessions/tests.py`. Internally "Step 9." | None identified. |
| 10 | Office Inbox Configuration | **COMPLETE** (foundation) | `apps/offices/models.py` `OfficeInboxConfig` (`enabled`, `welcome_message`, `waiting_message`, `offline_message`), migration `0003_officeinboxconfig`, Settings UI panel. Internally "Step 10." | Storing/editing the config is complete; **consuming** `welcome_message` is Phase 13 (done), consuming `waiting_message`/`offline_message` is Phase 16 (not started) — a deliberate 3-way split this canonical roadmap's own phase boundaries happen to match cleanly. |
| 11 | WhatsApp User / WP Office Selection | **COMPLETE** (foundation) | `apps/chats/operator_chat.py` `select_office_for_chat()` — "which Offices may be offered, is a chosen Office ID still valid." Internally "Step 11." Deliberately not a WhatsApp interactive-menu/button engine — this codebase has never parsed anything but plain-text messages (`apps.webhooks.parsing.SUPPORTED_EVENT_TYPES == {'message'}`), by explicit prior decision. | If a real WhatsApp interactive-list/button UI is ever wanted, that is new scope beyond what this phase built. |
| 12 | WhatsApp Office Selection | **COMPLETE** | Plain-text numeric-reply flow in `apps/chats/operator_chat.py` (the WP's reply is the Office's own DB id, not a re-numbered position — stateless, race-safe by construction). Internally "Step 12." `apps/chats/test_operator_chat.py`. | None identified. |
| 13 | Inbox Lifecycle | **PARTIAL** | Welcome-message lifecycle: `apps/chats/inbox_lifecycle.py` `handle_inbox_lifecycle_message()`, atomic compare-and-set claim on `Chat.welcome_sent_at` (migration `0004_chat_welcome_sent_at`), `apps/chats/test_inbox_lifecycle.py`. Internally "Step 13." | No broader chat-status state machine (open/closed/reopened) exists — only `welcome_sent_at` + `assigned_to` (Phase 15). This module's own docstring explicitly states `waiting_message`/`offline_message` are out of its scope (Phase 16). |
| 14 | Dynamic RBAC | **PARTIAL — functionally complete, verified against the dev database, but UNCOMMITTED** | Committed foundation: original fixed 3-value role enum + `office_matches_role` constraint (Step 2, migration `0002_officemembership_role`), Office/role authorization core (Step 3, `apps/offices/authorization.py`), Role×Scope permission classes (Step 8, `HasOfficeAccess`/`HasOfficeAdminAccess`). **Uncommitted, in the current working tree**: a full `Role` model — Superadmin-managed, carrying both JWT scopes (`reading`/`sending`/`session control`/`blast`/`user administration`/`system administration`) AND organizational standing (`grants_global_access`/`is_office_admin`/`is_operator`, replacing the old fixed enum entirely) — `apps/offices/models.py`, migrations `0005`–`0010`, `/api/roles/` CRUD, Sidebar/Sessions-page menu gating by JWT scope. Verified: `manage.py check`/`makemigrations --check` clean, all touched test modules import-load, migrations applied and manually verified against the dev/staging DB (a real pre-existing data-integrity gap was found and fixed mid-verification), `npx tsc -b --force --noEmit` and `oxlint` clean. | **Commit the working tree** (or make further changes first) — this is the single largest gap between "done" and "shipped" anywhere in this audit. Per the task's own instruction, this was not committed during this audit either. |
| 15 | Operator Workflow | **PARTIAL** | Manual assignment: `apps/chats/assignment.py` (`valid_assignment_candidates`/`assign_chat_to_operator`), `OfficeMembership.is_available`, `OperatorAvailabilityView`, Inbox UI assign/unassign controls. Internally "Step 14." | No queue, no auto-assignment, no multi-operator concurrency handling, no bot→human handoff (that last one is the explicitly-deferred "user manager" feature, Section 8). Assignment today is entirely manual, one Chat at a time. |
| 16 | Waiting / Offline Automation | **NOT STARTED** | `OfficeInboxConfig.waiting_message`/`.offline_message` are stored, editable fields with **zero** code path reading them anywhere in the backend — confirmed by `apps/chats/inbox_lifecycle.py`'s own docstring, which explicitly says so. | Needs its own design: what triggers "waiting" vs "offline" state, and what automation (if any) sends these. |
| 17 | Realtime Inbox | **NOT STARTED** | `InboxPage.tsx` uses plain polling (`CHAT_LIST_POLL_MS`/`MESSAGES_POLL_MS` `setInterval`s), confirmed no WebSocket/SSE anywhere in `frontend/` or `backend/`. `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`'s "Open" list still carries "WebSocket vs SSE" as an undecided question. | Needs a technology decision (the still-open WebSocket-vs-SSE question) before any implementation. |
| 18 | Blast | **COMPLETE** (core v1); template/esamsat extension **NEEDS REVIEW** | `apps/blast/` full stack; `docs/generated/PHASE-11-BLAST-END-TO-END-AUDIT-REPORT.md` traced every hop and re-ran 63/63 Django + 120/120 BFF tests itself; recipient caps, throttling, admin-approval, idempotent dispatch, stuck-recipient recovery all confirmed working. | Blast **templates** and **esamsat integration** are explicitly listed as "not yet phased" candidate requirements in `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` — whether they belong inside this canonical Phase 18 or are a future roadmap revision's own phase is a project-owner call, not inferred here (see Section 8). |
| 19 | Reports / Analytics | **NOT STARTED** | `frontend/src/pages/ReportsPage.tsx` is a `PlaceholderPage` with no backing API — confirmed by direct read this session. | Needs its own scope/design; no backend metrics endpoint exists to build a frontend against yet. |
| 20 | Audit / Observability | **PARTIAL** | Health endpoints exist and are individually good: `LivenessView`/`DatabaseHealthView`/`RedisHealthView` (`apps/core/views.py`), BFF `/health`; Dashboard health cards + (uncommitted) sync-status card. Audit trail itself is Phase 8's `AuditLog`. | No monitoring/alerting system (Prometheus/Grafana/Sentry or equivalent) found anywhere in the repository — nothing polls or alerts on the health endpoints that exist. No dedicated audit-log browsing/reporting UI. |
| 21 | Production Hardening | **PARTIAL** | Failure/security testing: Track A (`PHASE-13-TRACK-A-IMPLEMENTATION-REPORT.md`) — 4 permanent security test files, 456/456 backend + 127/127 BFF passing. Track B (`PHASE-13-TRACK-B-FAILURE-DRILL-REPORT.md`) — 5 of 8 `docs/09-TEST-PLAN.md` failure scenarios **live-drilled** against real running containers, all PASS; 2 findings (Redis-outage 500s, dev-Postgres-outage crash) fixed and committed (`8708004`). Network/TLS hardening: Blocker B1 (frontend `VITE_*` build args) and B3 (TLS/reverse-proxy — `DJANGO_BEHIND_TLS_PROXY` + `test_tls_proxy_settings.py`) are **closed**, found by direct source inspection this session (no dedicated report exists for either closure — see Section 7, discrepancy). Blocker B2 (network isolation) is **config-level mitigated** — `PROXY_BIND_ADDRESS`/`BFF_BIND_ADDRESS` are now required, fail-closed, private-address-only — but whether a real NetBird/VPN network is actually provisioned is infrastructure outside this repository and cannot be verified from source. | Scenarios 6–8 of the Test Plan's failure list (duplicate webhook, recovery reconciliation, ambiguous outbound result) have only unit-level coverage, not a live drill. 2 LOW-severity Track B findings (no auto-recovery, no dev healthcheck) were explicitly deferred, not fixed. B2's real-world network setup needs your confirmation. |
| 22 | Production Deployment | **PARTIAL** | M5 (SPA-fallback nginx config) and M6 (rollback/image-versioning: `IMAGE_TAG`, 3-slot alias chain, `infrastructure/scripts/*.sh`) are **closed** — M6 has its own dedicated report pair, M5 does not (found by direct inspection of `frontend/nginx.conf`, whose own header comment names itself "Phase 14 MISSING item M5"). | M1 (infra `.env.example` still missing Blast vars — re-checked this session, still absent), M2 (no migration-execution step/entrypoint), M3 (no Docker healthchecks, any of 7 services), M4 (no log rotation), M7 (Django admin static assets unstyled), M8 (no BFF security-headers middleware), M9 (no health-gated `depends_on`), M10 (no backup/restore procedure) all remain open. **No evidence anywhere in the repository of an actual live production deployment** — no runbook execution log, no DNS/TLS-issuance record, no `docker compose up` history against a real server. |

---

## 3. Roadmap Drift — Old Repository Roadmap vs. Canonical 22 Phases

Explicit differences found between the repository's own historical
numbering and this canonical roadmap, per the task's own requirement not
to silently reconcile them:

- **The canonical roadmap splits several features the repository's
  history treated as one undifferentiated blob.** Most notably: Office
  Inbox Configuration (10) / Inbox Lifecycle (13) / Waiting-Offline
  Automation (16) were all touched by a single internal "Step 10" and
  "Step 13" in the repository's own source comments, but the canonical
  roadmap's three-way split turns out to match the actual code boundary
  exactly (config storage vs. welcome-message consumption vs.
  waiting/offline consumption) — confirmed by source, not assumed.
- **"Dynamic RBAC" moved numbers.** The repository's own prior audit
  (this document's previous version) called it "Phase 15." The canonical
  roadmap calls it **Phase 14**. The implementation itself needed no
  change for this — only the number attached to it in documentation.
- **"Production Deployment" is not one canonical phase's work.** The
  repository's old Phase 14 (`docs/15-CODING-PHASES.md`) bundled
  security/failure-testing concerns together with deployment-tooling
  concerns. The canonical roadmap splits these into **Phase 21
  (Production Hardening)** and **Phase 22 (Production Deployment)** —
  this document assigns the old Phase 14's M-items and the old Phase 13's
  Track A/B work across both, per each item's actual nature (security/
  failure-testing vs. deployment-tooling/execution), stated explicitly
  per-item in Section 2 rather than guessed at.
- **"Multi-Tenant" (7) and "Authentication & Authorization" (1) did not
  exist as named phases in the old roadmap at all** — that work was
  scattered across the old roadmap's Phase 6 (BFF, for base auth) and an
  entirely separate, informally-numbered "Step 1–6" sequence (for
  multi-tenant/Office). The canonical roadmap gives both real, named
  slots; this document is the first place that reorganization is made
  explicit.
- **"Blast" (18) absorbed the old roadmap's Phase 11 wholesale** — no
  drift here, a clean 1:1 rename/renumber.
- **"Reports/Analytics" (19) and "Realtime Inbox" (17) have no
  predecessor anywhere in the old roadmap or the Step 1–14 lineage** —
  both are genuinely new canonical slots for work that was never started
  under any numbering, old or new.
- **Two of this task's own initial premises about internal "Step 7"/
  "Step 8" content were incorrect** and were corrected against source
  in this document's prior version (Section 9) rather than carried
  forward uncritically here.

---

## 4. Completed But Previously Undocumented

Found by direct source/git inspection, not claimed by any single existing
report:

- **Phase 21 Blockers B1 and B3, and Phase 22's M5, are closed** — none
  of the three has a dedicated audit/implementation report (unlike M6,
  which does). All three were found bundled into commit `1d705f9`, whose
  message only describes the Step 6–14 Office/RBAC work and says nothing
  about closing three separate Phase-14-lineage items in the same commit.
- **Phase 9 (Offline/degraded mode, old numbering) is complete**, closed
  by a report (`PHASE-9-OFFLINE-DEGRADED-MODE-COMPLETION-REPORT.md`) that
  postdates the still-frequently-cited
  `PHASE-ROADMAP-STATUS-AUDIT-REPORT.md`, which called it "PARTIAL."
- **Phase 12 (Security hardening, old numbering) is complete** — 6/6
  MUST-FIX items closed, contradicting README.md's own "In progress"
  status line (fixed as part of this task, Section 10).

---

## 5. Deferred Features — Mapped Against the Canonical Roadmap

| Feature | Canonical placement | Status |
|---|---|---|
| Session-based auto-reply menu bot (esamsat lookup, typing-delay simulation, per-session JSON log) | No canonical phase covers this | **FOUNDATION BUILT (2026-09-28 session), STILL OUTSIDE CURRENT CANONICAL ROADMAP** — a Conversation/Bot Engine now exists: `apps.bot` (`BotConfig`/`BotMenu`/`BotMenuItem`/`BotTrigger` — fully Superadmin/Office-Admin-configurable via `/api/bot/...` and the Settings → "Bot Configuration" UI, no hardcoded menu/trigger content), `apps.chats.conversation_engine` (the resolver: global-trigger reset, session state machine `NEW→ACTIVE→COMPLETED`/`WAITING_OPERATOR`, fallback behavior, dynamic Office-selector reusing the existing Phase 11/12 `operator_chat` functions verbatim), wired into `ingest_webhook()` in place of the old Phase 12/13 handlers (which remain in the codebase, unwired, not deleted). Verified: mocked unit tests, a rolled-back real-DB walkthrough, and — critically — a real, unmocked BFF→WAHA→WhatsApp delivery test against the live dev WAHA session (`no_epahari`), all destined only to the bot's own self-chat (`ack:2` confirmed for every scenario). **Not yet verified**: a genuine device-originated inbound message (no second controllable WhatsApp number was available for that half of the loop — see `docs/generated/` for the live-verification report once filed). Still explicitly NOT built, per the original deferred description: esamsat API lookup, typing-delay simulation, and a per-session JSON interaction log (this implementation uses relational `ConversationSession`/`Message` rows instead of a JSON blob — a deliberate design choice, not an oversight). `HANDOFF_TO_OPERATOR` exists only as an extension point (state transition + ack message), with no queue/assignment logic — that remains Phase 15's (Operator Workflow) job. No canonical phase number has been assigned to this feature by the project owner yet. |
| Blast template + esamsat integration | Arguably within Phase 18 (Blast)'s existing scope, but not confirmed | **NEEDS REVIEW** — see Phase 18's row in Section 2. Not silently placed inside Phase 18 as "remaining work" nor silently excluded; flagged for a project-owner decision. |
| User manager / operator-admin handoff | Its role/permission question is now largely answered by Phase 14 (Dynamic RBAC); the handoff/takeover mechanism itself is not covered by any canonical phase | **PARTIALLY ADDRESSED (permissions) / DEFERRED (mechanism) — the mechanism half is OUTSIDE CURRENT CANONICAL ROADMAP** unless the project owner places it under Phase 15 (Operator Workflow), which is the closest existing fit. |
| Reports page | Canonical **Phase 19 (Reports/Analytics)** | Not deferred outside the roadmap — it has a real canonical home, just **NOT STARTED** (Section 2). |
| `waiting_message` | Canonical **Phase 16 (Waiting/Offline Automation)** | Has a real canonical home, **NOT STARTED** (data field exists, unread). |
| `offline_message` | Canonical **Phase 16 (Waiting/Offline Automation)** | Same as above. |

---

## 6. Gaps — Canonical Roadmap Work Not Yet Implemented

Direct list, no phase invented for any of these beyond the 22 given:

- Phase 13: chat-status lifecycle beyond welcome-message + assignment.
- Phase 14: commit the already-built Dynamic RBAC work.
- Phase 15: assignment queue, auto-assignment, multi-operator concurrency,
  bot→human handoff.
- Phase 16: entirely not started.
- Phase 17: entirely not started (technology decision needed first).
- Phase 18: template/esamsat extension (pending scope decision).
- Phase 19: entirely not started.
- Phase 20: monitoring/alerting stack; audit-log browsing UI.
- Phase 21: 3 of 8 failure scenarios never live-drilled; 2 deferred LOW
  findings; B2's real network setup needs confirmation.
- Phase 22: 8 of 10 M-items open; no live deployment has occurred.

---

## 7. Current Project Position

```text
Highest canonical phase fully COMPLETE (with no PARTIAL predecessor):
Phase 12 — WhatsApp Office Selection
(Phases 0–12 are all COMPLETE except Phase 13, which is PARTIAL — see below
for why "highest complete" and "current focus" are different questions.)

Phases currently IN PROGRESS (PARTIAL):
- Phase 13 — Inbox Lifecycle (welcome-message done; broader lifecycle not)
- Phase 14 — Dynamic RBAC (functionally done, UNCOMMITTED — the most
  immediately actionable item in this entire roadmap)
- Phase 15 — Operator Workflow (manual assignment done; queue/handoff not)
- Phase 18 — Blast (core complete; template/esamsat extension pending a
  scope decision)
- Phase 20 — Audit/Observability (health endpoints exist; no monitoring
  stack)
- Phase 21 — Production Hardening (blockers closed/mitigated; failure
  drill coverage partial)
- Phase 22 — Production Deployment (2/10 items closed; no live deploy)

Phases NOT STARTED:
- Phase 16 — Waiting/Offline Automation
- Phase 17 — Realtime Inbox
- Phase 19 — Reports/Analytics

Next actionable work (no new phase invented; ordered by what unblocks the
most other work, not by phase number):
1. Phase 14 (Dynamic RBAC) is now committed (`f83824b`, prior session) —
   this item is closed; Section 2's Phase 14 row still says "UNCOMMITTED"
   and needs its own status refresh (README.md's own summary was already
   corrected for this in commit `b8979ad`; this document's per-phase table
   was not — noted here rather than silently fixed, since re-verifying
   the full Phase 14 evidence chain is outside this session's scope).
2. Close Phase 22's remaining M-items (M1–M4, M7–M10) before attempting a
   real production deployment.
3. Scope decision on Phase 18's template/esamsat extension, and on
   Phase 16/17/19's designs, whenever the project owner wants to open
   them — none is blocking anything else.
4. The new Conversation/Bot Engine (Section 5) needs a project-owner
   decision on whether it gets its own canonical phase number or folds
   into Phase 15 (Operator Workflow) once `HANDOFF_TO_OPERATOR` grows real
   assignment logic. It also still needs one real, device-originated
   WhatsApp inbound test to close the one gap its live-verification left
   open (see Section 5's entry).
```

---

## 8. Documentation Updated By This Task

| File | What changed | Why |
|---|---|---|
| `docs/16-MASTER-ROADMAP.md` | Rewritten around the canonical 22-phase roadmap (this document). Previous 15-phase content preserved as Section 9 (historical mapping), not deleted. | This is the task's primary deliverable — the canonical roadmap authority. |
| `README.md` | "Current status" section updated: points to this document as canonical, replaces the stale Phase 12 "In progress"/Phase 13–14 "Pending" table (Phase 12 is actually complete; Phase 13/21/22 are partial, not simply pending). | README was actively misleading — Section 4 above documents exactly this discrepancy. |
| `docs/10-CLAUDE-CODING-GUIDE.md` | The line "Follow `15-CODING-PHASES.md`" updated to also point future work at this canonical roadmap. | This line instructs future contributors/agents on what to follow next; leaving it pointing solely at the superseded roadmap would perpetuate the exact confusion this task was asked to resolve. |
| `docs/15-CODING-PHASES.md` | One header note added at the top, marking it historical/superseded by this document. Its Phase 0–14 body text is otherwise **untouched** — not rewritten, not renumbered. | Satisfies "the old roadmap should not be presented as the current authority" without destroying historical accuracy. |

## Documentation Preserved (intentionally not changed)

- Every file under `docs/generated/` (118 files) — each is a point-in-time
  audit/implementation report; historical by nature. None was edited,
  none was deleted. Several are now known-stale for current-status
  purposes (Section 4 of this document's predecessor content, Section 9
  below) — that staleness is documented here, not fixed by editing the
  original reports (which would falsify their own historical record).
- `docs/15-CODING-PHASES.md`'s body — see above, only a header note added.
- `docs/02-REQUIREMENTS.md`, `docs/06-SECURITY.md`, `docs/08-DEPLOYMENT.md` —
  each contains inline "(Phase 12)"/"(Phase 14)" mentions in prose, but
  these are historical attributions ("this control was added during Phase
  12") rather than current-status claims — leaving them intact preserves
  an accurate build history and avoids the blind find/replace this task
  explicitly warned against. If desired, a future pass could add
  parenthetical canonical cross-references (e.g. "Phase 12 (→ canonical
  Phase 8)") — not done here to avoid unrequested scope creep.
- `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` — its "Final — 2026-09-26,
  phase-labeling correction" entry (the "13.A"/"13.B" mislabeling trace)
  remains accurate as a historical decision record and was not touched.

---

## 9. Historical Mapping (this document's previous, now-superseded 15-phase content)

**Everything in this section describes the state of the project as of
this document's *previous* audit, using the repository's own old
internal numbering (`docs/15-CODING-PHASES.md`'s Phase 0–14, plus the
separate "Step 1–14" source-comment lineage, plus a former "Master Phase
15" label this document itself invented before the canonical 22-phase
roadmap existed). It is preserved for historical continuity and because
Section 2 above cites it as evidence in several rows. Do not use this
section to answer "what phase is WAMORA in now" — use Section 2.**

### 9.1 Old Official Engineering Roadmap — Phase 0–14 (`docs/15-CODING-PHASES.md`)

| # | Phase | Status (at previous audit) | → Canonical mapping |
|---|---|---|---|
| 0 | Repository skeleton | COMPLETE | → Phase 0 |
| 1 | Backend foundation | COMPLETE | → Phase 0 |
| 2 | Database models + migrations | COMPLETE | → Phase 0 (base) + Phase 7 (Office/RBAC-specific models) |
| 3 | Webhook ingestion | COMPLETE | → Phase 3 |
| 4 | Reconciliation | COMPLETE | → Phase 4 |
| 5 | Celery/Redis | COMPLETE | → Phase 0 (infra) |
| 6 | BFF | COMPLETE | → Phase 1 (auth) + Phase 0 (BFF infra itself) |
| 7 | Frontend foundation | COMPLETE | → Phase 6 |
| 8 | Inbox/chat | COMPLETE | → Phase 5 |
| 9 | Offline/degraded mode | COMPLETE (closed after the previous audit's own "PARTIAL" call) | → Phase 20 (Audit/Observability, the connectivity-signal half) |
| 10 | Session management | COMPLETE | → Phase 2 |
| 11 | Blast | COMPLETE (v1 scope) | → Phase 18 |
| 12 | Security hardening | COMPLETE | → Phase 8 |
| 13 | Failure/security testing | COMPLETE for scope drilled | → Phase 21 |
| 14 | Production deployment | IN PROGRESS | → Phase 22 (deployment items) + Phase 21 (B1–B3 blockers, which were security/network in nature) |

### 9.2 Old Development Steps 1–14 (Multi-Office & RBAC lineage, source-comment numbering)

| Step | Content | → Canonical mapping |
|---|---|---|
| 1 | Office model foundation | → Phase 7 |
| 2 | Fixed role enum + `office_matches_role` constraint | → Phase 14 (superseded by the Role model) |
| 3 | Office/role authorization foundation | → Phase 7 / Phase 14 (boundary) |
| 4 | Office ↔ Blast integration | → Phase 7 |
| 5 | Office ↔ Inbox integration | → Phase 7 |
| 6 | Office & User management CRUD | → Phase 7 (CRUD) / Phase 14 (Role assignment reuse) |
| 7 | Blast role-vs-scope test coverage | → Phase 8 / Phase 18 (boundary) |
| 8 | Role × Scope alignment (`HasOfficeAccess`/`HasOfficeAdminAccess`) | → Phase 14 |
| 9 | WAHA session → Office mapping | → Phase 9 |
| 10 | Office Inbox Configuration foundation | → Phase 10 |
| 11 | WP destination-Office selection foundation | → Phase 11 |
| 12 | WhatsApp Office selection via plain text | → Phase 12 |
| 13 | Inbox welcome lifecycle | → Phase 13 |
| 14 | Operator assignment & availability foundation | → Phase 15 |

### 9.3 Former "Master Phase 15" (this document's own prior invented label)

Previously labeled "Master Phase 15 — Dynamic Role-Based Access Control"
in this document's prior version, with sub-steps 15.1–15.3 (reading-scope
bug fix, dynamic `Role` model, org-standing merge). **This label is
retired** — the work it described is now **canonical Phase 14**
(Section 2), and the label "Master Phase 15" should not be used going
forward. It is recorded here only so anyone following an old link/note
that says "Phase 15" can find where that work actually lives now.

---

## 10. Git Safety Report

```
Implementation performed: NONE
Code changed:              NONE
Database changed:          NONE
Configuration changed:     NONE
Dependencies changed:      NONE
Documentation changed:
  - docs/16-MASTER-ROADMAP.md   (rewritten)
  - README.md                   (Current status section updated)
  - docs/10-CLAUDE-CODING-GUIDE.md  (one line updated)
  - docs/15-CODING-PHASES.md    (one header note added; body untouched)
Commit created: NO
Push performed: NO
```

All pre-existing working-tree changes (the uncommitted Phase 14/Dynamic
RBAC implementation — `backend/apps/offices/*`, `backend/apps/authn/*`,
`backend/apps/chats/assignment.py`, various test files, the 6 new
migrations, and the frontend Role/Sidebar/Sessions changes) were **not
touched, not committed, not reset, not stashed** by this task. They are
carried over exactly as they were found.
