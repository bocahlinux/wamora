# Next-Phase Roadmap Audit Report

**This is a read-only audit. No source, config, test, migration,
dependency, or documentation file was modified. No container was
started, stopped, or restarted. No Celery task, reconciliation run, or
WAHA write endpoint was triggered.**

**This report replaces the prior version at the same path** (written
before Phase 9.1B and the Sessions Connectivity dashboard card existed)
— every claim below was re-verified against the current repository
state directly in this task, not carried over from that or any other
prior report.

---

## 1. Current Verified Project State

Every item below was confirmed by reading the actual current source
this task, not inferred from a report's title or a prior summary.

**Docker development environment (Phases A–G, informal numbering)**:
`wamora-dev-tencent-bff-1` and `wamora-dev-tencent-frontend-1` are
running (`docker ps`, checked this task) — the Tencent-side dev stack is
live. The Office-side stack (`backend`/`celery-worker`/`celery-beat`/`redis`)
was **not running** at audit time; this was not changed, per the strict
read-only scope.

**Backend Django apps** (`ls backend/apps/`, checked this task):
`audit`, `authn`, `chats`, `core`, `dashboard`, `operations`, `sync`,
`waha_sessions`, `webhooks` — all nine present. Apps with a wired URL
module: `audit`, `authn`, `chats`, `core`, `dashboard`, `operations`,
`sync` (`api_urls.py` + `urls.py`), `webhooks`. `waha_sessions` has no
`urls.py` of its own — by design, session management is served by the
BFF directly against WAHA (`bff/src/routes/session.ts`), never through
Django (confirmed by this session's own prior audits and unchanged
here).

**Frontend pages** (`ls frontend/src/pages/`): `DashboardPage`,
`InboxPage`, `LoginPage`, `NotFoundPage`, `PlaceholderPage`,
`ReportsPage`, `SessionsPage`, `SettingsPage`, `WhatsAppPage`. Three of
these (`ReportsPage`, `SettingsPage`, `WhatsAppPage`) are honest,
explicitly-commented placeholders — re-read in full this task; each
states in its own source comment exactly why it has no real content
(no backing API exists yet for Reports/Settings; WhatsApp's scope was
never defined by any spec document). These are **not** part of the
canonical numbered-phase roadmap and are not evaluated as "next task"
candidates below.

---

## 2. Completed Phases/Features (Source-Verified This Task)

| Item | Verified how (this task) |
|---|---|
| Docker dev Phases A–G | `docker ps` shows the Tencent stack live and healthy; Office stack config exists (`infrastructure/development/office.yml`, `.env.example`), not started this task. |
| Phase 9.0 (unknown send outcome) | `frontend/src/pages/InboxPage.tsx` — `SendFeedback` type with a `'unknown'` kind, wired to `handleSend()`, re-read this task. |
| Phase 9.1A (sync-status endpoint) | `backend/apps/sync/views.py` — `SyncStatusView`, `GET /api/sync/status/<session_name>/`, re-read this task. |
| Phase 9.1B (webhook timestamp) | `backend/apps/sync/views.py` — `last_webhook_received_at` field present, sourced from `WebhookEvent.received_at` via `Max()`; just implemented and verified in the immediately preceding task this session (298/298 backend tests passing). |
| Phase 9.1C (Redis health endpoint) | `backend/apps/core/views.py:60` — `RedisHealthView` class exists; `backend/apps/core/urls.py:8` — `health/redis/` route wired. Grepped directly this task. |
| Phase 9.1D (Inbox connectivity indicator) | `frontend/src/pages/InboxPage.tsx` — `ConnectivityIssue` type, `reportPollOutcome()`, wired into both poll loops; re-read this task. |
| Phase 9.1E (Inbox sync-status badge) | `frontend/src/pages/InboxPage.tsx` — `syncStatus` state, `getSyncStatus()` call, `<StatusBadge status={mapSyncStatus(...)} />` next to the page title; re-read this task. |
| Phase 9.1F (Dashboard Redis card) | `frontend/src/pages/DashboardPage.tsx` — `redisQuery` + `<HealthCard icon={Zap} title="Redis" query={redisQuery} />`; re-read this task. |
| Dashboard WhatsApp Session Status Card ("Sessions Connectivity," interpretation (a)) | `frontend/src/pages/DashboardPage.tsx` — `SessionsCard` component, `getSessionStatus`/`mapWahaStatus` imports, wired into Row 2; just implemented and verified two tasks ago this session (lint/build clean). |

**Conclusion**: every item the user's task context listed as "complete"
is genuinely complete, confirmed from source, not merely from a report.

---

## 3. Remaining Phases/Features

### 3.A — Canonical roadmap (`docs/15-CODING-PHASES.md`)

Re-read directly this task — the canonical list is unchanged since the
last audit:
```
0. Repository skeleton        8. Inbox/chat
1. Backend foundation         9. Offline/degraded mode
2. Database models+migrations 10. Session management
3. Webhook ingestion          11. Blast
4. Reconciliation             12. Security hardening
5. Celery/Redis               13. Failure/security testing
6. BFF                        14. Production deployment
7. Frontend foundation
```
Phases 0–10 are, in substance, complete (backend foundation, models,
webhook ingestion, reconciliation, Celery/Redis, BFF, frontend shell,
Inbox/chat, offline/degraded-mode signals — the entire 9.0/9.1A–F/
Sessions-card lineage audited in Section 2 — and Session management,
`SessionsPage.tsx`, fully functional). **Phase 11 (Blast) has zero
implementation** — confirmed via a repository-wide search: the only
hits for "blast" anywhere in source are `backend/config/settings.py:293`
(the string `'blast'` inside the static `JWT_SCOPES` vocabulary list,
copied from `docs/06-SECURITY.md`'s scope names) and one JWT test file
referencing that same scope constant — no model, endpoint, route, or UI
exists. **Phase 12/13/14 (security hardening, failure/security testing,
production deployment) have no dedicated implementation surface found**
beyond what individual phases have organically included (e.g. HMAC
webhook signatures, JWT auth, internal-service-key gating) — no
dedicated "hardening pass" or deployment runbook phase has been run.

### 3.B — Phase-9-lineage items still pending (source-verified this task)

- **Dashboard sync-status card** — **still pending.** `grep -n
  "getSyncStatus\|SyncStatus\b" frontend/src/pages/DashboardPage.tsx`
  returned **no matches** (checked this task, after the Sessions card
  work). This is a *different* signal from the Sessions card just
  built: the Sessions card shows WAHA connection status
  (`WORKING`/`SCAN_QR_CODE`/...); this pending item would show
  reconciliation health (`sync_status`: `healthy`/`stale`/`failed`/...)
  — the same signal already shown on `InboxPage.tsx` since 9.1E, just
  not yet duplicated onto the Dashboard.
- **Sessions connectivity indicator extension** (interpretation (b) from
  the earlier design-audit fork — extending `InboxPage.tsx`'s
  `reportPollOutcome`/`ConnectivityIssue` pattern into `SessionsPage.tsx`)
  — **still pending, and was never separately requested**: the user
  explicitly chose interpretation (a) (the Dashboard session card, now
  built) over interpretation (b) when resolving that ambiguity.
  `grep -n "reportPollOutcome\|ConnectivityIssue" frontend/src/pages/SessionsPage.tsx`
  returned **no matches** this task, confirming (b) remains untouched.
- **"Possibly stuck" reconciliation detection** — **still pending, not
  even design-audited.** `grep -n "stuck\|possibly_stuck"
  backend/apps/sync/reconciliation.py backend/apps/sync/views.py`
  returned no matches. Traced directly this task (Section 4) — this is
  a real, currently-unmitigated gap, not a hypothetical one.
- **Celery worker liveness** — **still pending, not even
  design-audited.** No `celery_app.control.ping()` (or equivalent) call
  exists anywhere in `backend/` — the only related text is
  `RedisHealthView`'s own docstring explicitly stating it checks Redis
  reachability only, not worker liveness.
- **Actual "recovery"** for a stuck `RUNNING` checkpoint (as opposed to
  mere detection) — **not proposed anywhere in any report**, including
  this one (Section 6). Naming this explicitly because the user's task
  context uses the phrase "stuck-running reconciliation recovery" —
  Section 6 recommends the narrower, lower-risk *detection* half only.
- **Whether production actually runs `RECONCILIATION_EXECUTOR=celery`**
  — unconfirmable from source alone (repeated finding across this
  session's prior audits, re-stated, not re-investigated, since nothing
  newly available resolves it).

---

## 4. Source-Level Evidence — The Stuck-`RUNNING` Gap, Traced Directly

This task traced `backend/apps/sync/reconciliation.py`'s
`reconcile_session()` directly (not from a report) to establish whether
the gap named in Section 3.B is real:

```python
checkpoint.status = SyncCheckpoint.STATUS_RUNNING
checkpoint.save(update_fields=['status', 'updated_at'])   # <- committed to DB HERE

client = waha_client or WahaClient()
... # the entire fetch/parse/persist loop, no top-level try/except

checkpoint.last_run_at = timezone.now()
if result.had_error:
    checkpoint.status = SyncCheckpoint.STATUS_ERROR
else:
    checkpoint.status = SyncCheckpoint.STATUS_OK
checkpoint.save(update_fields=[...])                       # <- only reached on normal completion
```

**Finding**: the `RUNNING` write is committed to the database
immediately, before any of the actual fetch/parse/persist work runs.
Nothing between that write and the function's final `save()` is wrapped
in a `try/finally` that would reset `status` on an unexpected failure.
For `RECONCILIATION_EXECUTOR=celery`, a raised `Exception` is caught by
`@shared_task(autoretry_for=(Exception,), max_retries=3, ...)`
(`apps/sync/tasks.py`) and retried — but a hard worker kill (OOM, `kill
-9`, container restart) or a 4th consecutive failure exhausting all
retries leaves the checkpoint at `RUNNING` **permanently**, with no
self-healing anywhere in the codebase. For `RECONCILIATION_EXECUTOR=sync`,
there is no retry safety net at all — any unhandled exception during a
synchronous, in-request call leaves the checkpoint stuck immediately.
`SyncStatusView._derive_sync_status()` (`apps/sync/views.py`) would then
report `sync_status: 'running'` forever, indistinguishable from a
healthy, currently-in-progress run — this is a genuine, currently-live
observability/correctness gap, not a hypothetical one, independently
confirmed by this audit rather than assumed from a prior report's
framing.

**Independent finding that revises a prior report's framing**: an
earlier draft of this same audit report (now superseded, Section 7
there) classified stuck-running recovery as "blocked... tightly coupled
[to Celery worker liveness]... implementing one without the other would
be incomplete." Re-examined directly this task: **this coupling claim
does not hold for detection alone.** The original design proposal
(`docs/generated/PHASE9-1-DESIGN-AUDIT-REPORT.md`, Section 5) describes
a purely time-based heuristic — flag `possibly_stuck: true` when
`checkpoint.status == 'running'` and `checkpoint.updated_at` is older
than a generous multiple of the retry loop's own bound. This needs
**no** knowledge of Celery/worker state at all; it is self-contained,
using only `SyncCheckpoint` fields that already exist. Worker-liveness
information would let an operator additionally distinguish *why* a
checkpoint is stuck (broker down vs. worker dead vs. a genuinely huge
backlog) but is not required for the narrower, honest claim "this has
been running suspiciously long." **Genuine coupling exists only for
RECOVERY** (automatically resetting/killing a stuck job) — there,
acting without knowing whether a worker is actually still processing it
risks corrupting an in-progress run, which is exactly why this report
(Section 6) recommends detection only, not recovery, as the next task.

---

## 5. Dependency Graph for Remaining Work

```
Dashboard sync-status card ── fully independent, zero backend change
   (getSyncStatus/SyncStatus/mapSyncStatus already exist and are
   already proven in production use via InboxPage.tsx since 9.1E)      [UNBLOCKED]

Sessions connectivity indicator extension (interpretation b) ·· pattern
   precedent only from 9.1D (not a hard code dependency)                [UNBLOCKED, not requested]

"Possibly stuck" detection flag ── fully independent of Celery worker
   liveness for a MINIMAL (timestamp-only) version (Section 4's revised
   finding) ── reads only SyncCheckpoint.status/updated_at, both already
   in the schema, from the same file 9.1A/9.1B already established      [UNBLOCKED]
        │
        └──(optional future enhancement, NOT required)──→ combine with
           Celery worker liveness for root-cause distinction            [separate, heavier item]

Celery worker liveness (celery_app.control.ping()) ── independent
   backend infra check, needs its own design audit (timeout policy,
   response shape, whether/how to surface "zero workers responded")     [UNBLOCKED but heavier — no existing proposal shape at all]

Stuck-checkpoint RECOVERY (auto-reset/kill) ── depends on detection
   existing first (can't recover from a state you don't detect), AND
   is a write-path change to reconcile_session() ── genuinely higher-
   risk, needs an explicit user decision on recovery policy before any
   design audit even starts                                             [BLOCKED — needs Section 10 decision]

Phase 11 (Blast) / 12 (Security hardening) / 13 (Failure/security
testing) / 14 (Production deployment) ── each a large, separate,
un-scoped body of work with no design audit or precedent anywhere in
this session ── sequencing-only dependency on "Phase 9 lineage settling
first," not a hard code blocker                                         [PENDING, not recommended next]
```

---

## 6. Recommended Next Task

**"Possibly Stuck" Reconciliation Detection — a design audit first,
then (in a separate, later task) a minimal, additive, read-only
`possibly_stuck` signal on the existing sync-status response.**

Explicitly: **detection only, not recovery.** This report does not
recommend implementing recovery (auto-resetting or killing a stuck
job) as part of this next task — that remains a separate, higher-risk
item gated by a user decision (Section 10).

---

## 7. Why This Is The Next Task

Evaluated against the same four criteria the task asked for:

- **Documented project roadmap**: this is the last unaddressed item
  from `docs/generated/PHASE9-1-DESIGN-AUDIT-REPORT.md`'s own "Confirmed
  Gaps" list (gap 4) that has a genuine, already-sketched design
  direction (Section 5 there) and real operational stakes — unlike gap
  5 (durable record of recovery amount), which that same report
  explicitly declined to propose fixing at all.
- **Actual source state**: Section 4 independently confirms the gap is
  real (not just documented) — a crashed/killed worker or an exhausted
  retry genuinely leaves no way to tell "stuck" from "healthy and
  running" today.
- **Dependencies**: Section 5 shows this item is fully unblocked for a
  minimal version — no dependency on Celery worker liveness (a claim
  this audit explicitly revised from an earlier draft, Section 4),
  no dependency on any other pending item.
- **Existing implementation precedents**: extremely strong — the exact
  same file (`apps/sync/views.py`), the exact same threshold-comparison
  shape already used for `STALE_THRESHOLD_MULTIPLIER`/`_derive_sync_status()`,
  and the exact same "additive, `null`-safe, non-breaking JSON field"
  discipline just re-proven twice (9.1A, 9.1B) on this identical
  endpoint.
- **Lowest unnecessary risk**: no migration, no BFF, no frontend, no
  Docker, no new dependency, no write-path change, no live-infra
  dependency to verify correctness (pure unit-testable, exactly like
  9.1B) — strictly lower-risk than Celery worker liveness (which has no
  existing proposal shape, needs a live-broker-aware design, and is
  materially harder to unit test) and than the Dashboard sync-status
  card is *not* strictly lower-risk than, but is lower-*value*: that
  card would only duplicate a signal already visible on `InboxPage.tsx`
  since 9.1E, whereas this item closes a genuinely unaddressed
  correctness gap. Named as the runner-up, not dismissed — see Section
  8.

**Runner-up, explicitly not recommended first**: the Dashboard
sync-status card is lower-effort and equally low-risk, but lower-value
(redundant with an existing Inbox signal) — a reasonable *second* task,
not competing directly with this one's priority.

---

## 8. Risks

- **Threshold miscalibration**: setting the "generous multiple" too
  low would falsely flag a legitimately large/slow reconciliation run
  as stuck (alarm fatigue); too high would delay real detection. This
  is a genuine, if modest, design decision — recommended to be settled
  in the design-audit step, using the same reasoning already applied to
  `STALE_THRESHOLD_MULTIPLIER` (a multiple of the already-configured
  `RECONCILIATION_INTERVAL_SECONDS`, not an independent constant).
- **Scope creep into recovery**: the clearest risk is conflating
  "detect" with "fix" — implementing an automatic reset/kill of a
  `RUNNING` checkpoint without knowing whether it is *actually* still
  legitimately running risks corrupting a genuinely in-progress run.
  This report deliberately recommends detection only for this reason.
- **False confidence**: a `possibly_stuck` flag could be mistaken by an
  operator for a confirmed diagnosis ("the worker is dead") when it is
  only a time-based heuristic — the design audit should specify honest
  field naming/documentation to avoid this (mirroring 9.1B's own
  care around not overclaiming what `last_webhook_received_at` proves).
- **Test-count coupling**: as with 9.1B, adding a field to
  `SyncStatusView`'s response does not by itself add a new query (this
  can be computed from data already fetched in the same request, unlike
  9.1B's necessary new `WebhookEvent` aggregate) — but the existing
  `test_query_count_is_bounded_no_n_plus_one` test should still be
  re-verified at implementation time, not assumed unaffected.

---

## 9. Files Likely to Change

**For the design audit** (next task): no files change — read-only,
per this session's established practice for every phase so far.

**For the eventual minimal implementation** (a later, separate task,
not this one):
- `backend/apps/sync/views.py` — the only file expected to need a
  production change: a `possibly_stuck` boolean computed from
  `checkpoint.status == SyncCheckpoint.STATUS_RUNNING` and
  `checkpoint.updated_at` age, added to the existing response dict.
- `backend/apps/sync/tests/test_views.py` — new test cases (stuck vs.
  not-yet-stuck vs. not-running-at-all), mirroring 9.1A/9.1B's testing
  style in the same file.

**Not expected to change**: `backend/apps/sync/reconciliation.py`
(write path untouched — detection only), `backend/apps/sync/tasks.py`,
`backend/apps/sync/executors.py`, any BFF file, any frontend file (no
UI consumption proposed as part of the minimal version — matching
9.1B's own "Backend:"-only precedent), any Docker/Compose/`.env` file,
any migration.

---

## 10. USER DECISIONS REQUIRED

1. **Whether to proceed with a design audit for "possibly stuck"
   detection next**, per this report's recommendation — or instead
   prioritize one of the runner-up items named in Section 7/3.B
   (Dashboard sync-status card, Celery worker liveness, or Sessions
   connectivity extension interpretation (b)). This is a genuine
   priority call the user should confirm, not assumed by this audit.
2. **Whether "recovery" (auto-resetting or killing a stuck checkpoint)
   is wanted at all, ever** — and if so, under what policy (e.g. only
   after N missed cycles? does it also need to confirm via Celery
   worker liveness first, to avoid interrupting a genuinely-running
   job?). This materially affects architecture and data-integrity
   semantics (a wrong reset could corrupt an in-flight run) — correctly
   escalated, not a naming/formatting decision.
3. **The specific "generous multiple" threshold value** for
   `possibly_stuck`, if the design audit proceeds — a genuine, if minor,
   product judgment call (same category as the already-precedented
   `STALE_THRESHOLD_MULTIPLIER = 2`), not escalated as a hard blocker
   but flagged as something the design audit should propose and the
   user should have visibility into, not something this audit invents
   unilaterally.

**Not escalated** (per the task's own threshold — architecture/security/
data-semantics/scope only): exact field name, whether to add a database
index anywhere, JSON key casing — none of these arose as open questions
in this audit.

---

## 11. Explicit STOP Recommendation

**This was an audit only. Nothing was implemented, and nothing should
be implemented as a direct continuation of this report.**

Recommended immediate next step, **only if the user confirms Section
10, item 1**: a dedicated, read-only design audit titled something like
"Possibly-Stuck Reconciliation Detection — Design Audit," scoped
exactly as Section 6/9 describe (detection only, `apps/sync/views.py`
only, no recovery, no Celery worker liveness dependency) — mirroring
the exact audit-then-implement rhythm this entire session has used for
every other Phase 9 slice.

**STOP.** No implementation was performed by this task. Awaiting the
user's decision on Section 10 before any further action.
