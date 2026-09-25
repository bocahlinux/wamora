# Phase 9 — Next-Step Design Audit (Read-Only)

**Scope.** Design/read-only audit only. No source, `.env`, configuration,
database, migration, or WAHA state was modified. No write-capable endpoint
was called. No WhatsApp message was sent. `git status`/`git diff` were
checked first and confirmed the working tree contains exactly: Phase
9.0/9.1D/9.1E's frontend diff (`InboxPage.tsx`/`.css`,
`StatusBadge.tsx`, `djangoApi.ts`) and Phase 9.1A's backend diff
(`apps/sync/views.py`, `apps/sync/api_urls.py`, `config/urls.py`,
`apps/sync/tests/test_views.py`) — nothing else. Every claim below reflects
this actual, current, uncommitted-but-real state, re-verified this task
where noted, not assumed from memory of prior sessions.

---

## 1. Executive Summary

Four Phase 9 slices are now code-complete and verified at the build/test
level: **9.0** (ambiguous send-outcome UX), **9.1D** (frontend
connectivity indicator), **9.1A** (backend sync-status endpoint), **9.1E**
(frontend sync-status badge). Together they give an Inbox user three
independent, non-overlapping signals — "did my send work," "can this page
reach the server," "is reconciliation itself healthy" — built entirely on
already-existing patterns (`ApiError.kind`, `StatusBadge`,
`SyncCheckpoint`), with no new architecture, no new dependency, and no
schema change anywhere in the stack.

**What remains genuinely uncovered**, confirmed by direct source
inspection this task, not assumption: webhook-channel health (no signal
exists, anywhere, for "has a webhook arrived recently"); Redis/Celery
health (no check exists, anywhere); a stuck-`running` `SyncCheckpoint` has
no timeout/recovery mechanism; the connectivity-indicator pattern
(`reportPollOutcome`) exists only on `InboxPage.tsx` — `SessionsPage.tsx`
has its own, separate, differently-shaped status poller that was never
brought into this pattern; and no page other than Inbox shows sync status
at all (Dashboard, which is the more natural "system health" home per its
own existing `HealthCard` precedent, still shows nothing about
reconciliation).

**Nothing found in this audit blocks any next step from being scoped** —
every remaining gap has a small, independently-testable candidate slice
(Section 11), none requiring a broad architectural change. Several are
genuinely independent of each other and could be sequenced in more than one
valid order; this report states dependencies, not a preference.

---

## 2. Current Phase 9 Completion Matrix

| Item | Status | Evidence |
|---|---|---|
| 9.0 — Ambiguous send-outcome UX | **Done** | `InboxPage.tsx`'s `SendFeedback` union, verified this task via `git diff` — unchanged since its own implementation report |
| 9.1D — Frontend connectivity indicator | **Done** | `connectivityIssue`/`reportPollOutcome()`, unchanged |
| 9.1A — Backend sync-status endpoint | **Done** | `GET /api/sync/status/<session>/`, unchanged, 287/287 backend tests passed at implementation time (not re-run this task — no backend code changed since, so no reason to expect drift; Section 9 covers what re-running would add) |
| 9.1E — Frontend sync-status badge | **Done** | `StatusBadge` + `mapSyncStatus()` + Inbox poll loop, unchanged |
| 9.1B — Webhook-timestamp signal | **Not started** | No `last_webhook_received_at` (or equivalent) field exists anywhere in `apps/sync/views.py`'s response or any other endpoint |
| 9.1C — Redis health endpoint | **Not started** | No `RedisHealthView`/equivalent exists anywhere in `apps/core` (re-confirmed this task) |
| 9.1F — Dashboard Redis card | **Not started** | Depends on 9.1C; `DashboardPage.tsx` unchanged since the prior Phase 9 audits |
| 9.1G — Live verification of 9.1A/9.1E | **Not started** | No report on file documents a live browser/production check of either |
| Canonical Phase 9 ("Offline/degraded mode") as a whole | **Partially addressed** | Inbox now has three of the five zones `docs/03-UI-UX-SPEC.md`'s global-status example names (WAHA/BFF via 9.1D's connectivity signal in spirit, though not literally re-labeled; sync via 9.1A/9.1E) — Sessions and Dashboard still show none of this; webhook and Redis/Celery health remain fully unaddressed |

---

## 3. Current Architecture / Data Flow Relevant to Phase 9

```
Browser (InboxPage.tsx)
  │
  ├── GET /api/chats/, /api/chats/:id/messages/   (poll, 8s/5s)  ─┐
  ├── GET /api/sync/status/<session>/              (poll, ~32s)  ─┼─→ reportPollOutcome()
  │                                                                │    → connectivityIssue banner
  │  (send: POST via BFF, unrelated to polling — Phase 9.0's own,  │      (Signal A)
  │   independent SendFeedback state)                              ┘
  │
  └── StatusBadge (Signal B: sync_status, from the endpoint's own successful response only)

Django
  ├── apps.sync.views.SyncStatusView  ← reads SyncCheckpoint (session, status, last_run_at, updated_at)
  ├── apps.webhooks  ← writes WebhookEvent + Chat/Message (via persist_message, shared with reconciliation)
  └── apps.sync.reconciliation.reconcile_session()  ← the only writer of SyncCheckpoint
        ▲ ▲ ▲ ▲
        │ │ │ └── manage.py reconcile (manual)
        │ │ └──── Celery periodic (reconcile_all_sessions_task, every RECONCILIATION_INTERVAL_SECONDS)
        │ └────── Celery targeted (reconcile_chat_task, RECONCILIATION_EXECUTOR='celery')
        └──────── in-process sync (RECONCILIATION_EXECUTOR='sync', dev default)
              ▲
              └── BFF's POST /internal/reconciliation/trigger/, fired only after a confirmed 'sent' outbound send

BFF
  └── GET /health  ← WAHA reachability + BFF-process liveness, unrelated to anything above,
                      never consumed by any Phase 9 frontend code (Section 8's own question)
```

**No new edge was added to this diagram by 9.0/9.1D/9.1A/9.1E** — every
box and arrow already existed before this session's work; what changed is
purely that two previously-invisible facts (connectivity, sync status) are
now surfaced to the browser.

---

## 4. What 9.0 + 9.1D + 9.1A + 9.1E Now Provide

Directly answering investigation item 3: **sufficient for what each is
individually scoped to answer, not sufficient as a complete "is my data
flowing correctly" picture** — and this is by design, not an oversight
this audit is newly discovering.

- **9.0** answers: "did my one send attempt succeed, fail, or go
  ambiguous?" — scoped to a single message, never implies anything about
  the page as a whole.
- **9.1D** answers: "can this page currently talk to Django?" — derived
  from `ApiError.kind` on chat-list/messages/sync-status polls, says
  nothing about data freshness or WhatsApp.
- **9.1A/9.1E together** answer: "has reconciliation completed
  successfully recently?" — derived from `SyncCheckpoint.status` +
  `last_run_at`, says nothing about webhook health or Redis/Celery health,
  and (Section 6) can be `healthy` even while the webhook channel is
  silently broken, because periodic reconciliation is designed to
  compensate for exactly that.

What none of the four currently answer, confirmed absent from the
codebase: "is a webhook actually arriving," "is Redis/Celery actually up,"
"is WhatsApp itself online" (this project has never had a direct signal
for WhatsApp's own connection state distinct from WAHA's own reported
session status, which is a separate, pre-existing concern in
`SessionsPage.tsx`, untouched by any Phase 9 work).

---

## 5. Remaining Gaps

Confirmed by direct source inspection this task:

1. **Webhook-channel health** — no field, endpoint, or frontend signal
   exists anywhere for "time since last webhook received" or "how many
   webhooks have recently failed ingestion." `WebhookEvent.attempts` is
   live-written (re-confirmed, `apps/webhooks/services.py`) but never
   aggregated or exposed.
2. **Redis/Celery health** — no check exists anywhere in `apps/core` or
   elsewhere (re-confirmed this task via grep).
3. **Stuck-`running` recovery** — `reconcile_session()` sets
   `status='running'` before any WAHA call and only the two
   `try`/`except`-guarded branches at its end ever move it to
   `'ok'`/`'error'`; an uncaught exception or killed process leaves it
   stuck indefinitely, with no code anywhere that times it out. `9.1A`'s
   endpoint exposes `checkpoint_updated_at` precisely so a *consumer* can
   judge this, but no *automatic* recovery exists (deliberately, per
   9.1A's own design report — not a new finding, restated here because
   this audit was explicitly asked to re-check it).
4. **`SessionsPage.tsx` has no equivalent connectivity indicator** — it
   has its own, separate `runTick()`/`isSyncing` status-settle poller
   (unchanged by anything in Phase 9), which silently swallows a failed
   check (`setIsSyncing(false)`, no error surfaced) rather than
   contributing to any shared signal. The `reportPollOutcome()` pattern
   `InboxPage.tsx` now has was never extended there — a real,
   now-more-visible inconsistency since one page has the pattern and the
   other doesn't.
5. **No page other than Inbox shows sync status** — `DashboardPage.tsx`
   (which already has the closest existing precedent, `HealthCard`, for
   an always-visible system-health element) shows nothing about
   reconciliation. An operator who never opens Inbox has zero visibility
   into sync health today.
6. **`RECONCILIATION_EXECUTOR`'s real production value remains
   unverified** — same finding as every prior Phase 9 audit this session;
   nothing new was found to resolve it (no `.env` access from this
   environment, Section 9).
7. **`README.md` has not been updated** to reflect any of 9.0/9.1D/9.1A/9.1E
   (Section 10) — expected, since nothing has been committed yet, not a
   defect, but worth tracking before this work is considered "shipped."

---

## 6. Edge Cases and Misleading-State Analysis

Investigation items 3/4/9, answered concretely:

- **`healthy` sync + broken webhook is not misleading, but is easy to
  misread** — if the webhook channel silently stops delivering while
  periodic reconciliation keeps succeeding every cycle, `sync_status`
  correctly stays `healthy` (reconciliation genuinely *is* working — it's
  compensating for the broken webhook, which is exactly its documented
  purpose). The risk is purely in how an operator *reads* "Synced": it is
  accurate as "reconciliation completed recently," not as "every channel
  that could deliver data is working." The 9.1E implementation's label
  choice ("Synced," not "All systems operational") already mitigates this
  by wording alone (Section 4 of the 9.1E design report), but the
  *underlying inability to detect this specific failure mode at all* is a
  real, unresolved gap (Section 5, item 1), not merely a wording risk.
- **Stuck `running`** — the badge would show "Syncing" indefinitely for a
  session whose last reconciliation attempt crashed mid-run. This is
  visually indistinguishable from a genuinely-in-progress run of unusual
  length. `checkpoint_updated_at` is available in the raw API response for
  a future consumer to reason about staleness-of-running, but **nothing in
  the current frontend implementation surfaces or uses it** — 9.1E's
  `SyncStatus` interface includes the field, but `InboxPage.tsx` never
  reads `syncStatus.checkpoint_updated_at` anywhere in its render logic
  (confirmed by re-reading the current file this task: only
  `syncStatus.sync_status` drives the badge). This is not a bug relative
  to either design report (neither mandated using it), but it is a
  concrete, currently-unexploited gap between what the API already
  provides and what the UI currently shows.
- **404 vs. `never_synced`** — already deliberately conflated to the same
  label ("Not synced") per 9.1E's own documented design choice; not a new
  finding, re-confirmed still true and still intentional.
- **The 32-second poll interval** — during a fast state transition (e.g.
  a targeted reconciliation completing within a couple of seconds of a
  send), the badge can lag the true state by up to ~32s. Not misleading
  (it will catch up and was never claimed to be real-time), but worth
  naming as a latency characteristic, not a defect.
- **Asymmetric page coverage (Section 5, items 4/5)** — an operator on
  `SessionsPage` or `DashboardPage` sees no connectivity or sync signal at
  all, while one on `InboxPage` sees both. This isn't "misleading" in the
  sense of showing a wrong value, but it does mean the *absence* of a
  degraded-state indicator on those other pages could be misread as "all
  clear" when in fact those pages simply never check.
- **No interference found between the new signals and existing frontend
  behavior** (investigation item 9) — re-confirmed this task by reading
  the current `InboxPage.tsx` end to end: `syncStatus`, `connectivityIssue`,
  and `sendFeedback` are three independent `useState` calls, never
  cross-read or cross-written, rendered in three separate, non-overlapping
  JSX locations (`PageHeader`'s `actions` slot, a banner under it, and the
  composer area respectively).

---

## 7. Redis/Celery Analysis

Investigation item 6, re-confirmed this task (`config/celery.py`,
`config/settings.py` read fresh):

- Redis's only role remains Celery broker + result backend
  (`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND`) — no `CACHES` setting, no
  session store, confirmed unchanged.
- The only periodic task is `reconcile_all_sessions_task`, registered via
  `sender.add_periodic_task(settings.RECONCILIATION_INTERVAL_SECONDS, ...)`
  inside `config/celery.py`'s `_setup_periodic_tasks` signal handler — no
  other periodic job exists.
- **No Docker `HEALTHCHECK` directive exists in any Dockerfile**
  (re-confirmed this task via direct grep across `backend/Dockerfile`,
  `bff/Dockerfile`, `frontend/Dockerfile`) and **no Celery-native liveness
  check** (e.g. `celery_app.control.ping()`) is implemented anywhere —
  meaning nothing in this repository, today, can distinguish "Redis is
  down" from "Redis is up but no worker is consuming the queue," a
  distinction named as a real limitation in the 9.1A design report and
  still unresolved.
- **Whether Redis/Celery health should become a separate signal, or stay
  outside Phase 9 sync status, is a scoping question this audit does not
  resolve** — both are architecturally valid: a dedicated `9.1C` endpoint
  (already scoped in the 9.1-series design reports) keeps `SyncCheckpoint`-derived
  data and infrastructure-reachability data as two distinct concerns,
  matching this project's existing `LivenessView`/`DatabaseHealthView`
  precedent of "one dependency, one check"; folding a Redis ping into the
  *existing* sync-status response would couple two different failure
  domains into one payload, which none of this project's other health
  endpoints do. This report notes the trade-off, not a recommendation
  (Section 11).
- **No assumption is made that Redis/Celery is currently healthy in any
  environment** — this audit did not check, and nothing in the repository
  itself proves it either way; the only true statement derivable from
  source is "reconciliation's `stale`/`healthy` classification would
  correctly, eventually reflect a Redis/Celery outage as `stale`, but
  cannot distinguish *why*" (Section 6/8 of the 9.1-series design report,
  unchanged, re-confirmed this task).

---

## 8. Webhook-Health Analysis

Investigation item 7:

- **Confirmed, re-read this task**: `WebhookEvent.attempts` is
  genuinely live-written on every re-delivery of an already-seen event
  (`apps/webhooks/services.py`); `received_at`/`processed_at` are both
  real, queryable timestamps. This data exists and is durable — it is
  simply never aggregated or exposed anywhere.
- **Whether webhook health should be addressed separately from
  reconciliation health**: the two are architecturally distinct failure
  domains (webhook delivery vs. periodic catch-up), and this project's own
  existing precedent (one dependency, one health check —
  `LivenessView`/`DatabaseHealthView`) would suggest keeping them
  separate rather than merging "last webhook received" into the sync-status
  payload. The 9.1-series design reports already proposed this as
  optional "9.1B," additive to the same response object rather than a new
  endpoint — both remain structurally possible; this audit does not choose
  between them.
- **The deeper limitation, unchanged from every prior Phase 9 report this
  session**: even with a "last webhook received at" timestamp exposed,
  the system still cannot distinguish "webhook is broken" from "WhatsApp
  is genuinely quiet" — both look identical (silence) from inside Django.
  Surfacing the timestamp would only ever narrow the window of uncertainty
  (bounded by the periodic reconciliation interval), never eliminate it,
  since nothing in this architecture observes WhatsApp/WAHA independently
  of the webhook channel itself.

---

## 9. Production Implications

Investigation item 13 — documented, not changed:

- **Django**: `backend/Dockerfile`'s `CMD` uses `gunicorn`, never
  `manage.py runserver` (re-confirmed this task) — the duplicate-stale-process
  failure mode documented earlier this session for local dev cannot recur
  in the Docker/production path, unchanged conclusion.
- **BFF**: `bff/Dockerfile` runs the compiled `dist/index.js` under plain
  `node`, one process, `restart: unless-stopped` only — unchanged.
- **Celery/Redis**: `infrastructure/office/docker-compose.yml` provisions
  `celery-worker`, `celery-beat`, `redis` services — their *presence* in
  the compose file says nothing about whether `RECONCILIATION_EXECUTOR`
  is actually set to `'celery'` in the real office `.env` (the Django
  default, if unset, is `'sync'`, which would silently run reconciliation
  in-request inside `gunicorn` workers instead). This audit could not
  check the real value (no `.env` access from this environment) and does
  not assume either value — same unresolved item as every prior Phase 9
  report.
- **No Docker-level health checks exist for any service** — `restart:
  unless-stopped` will restart a crashed container but cannot detect a
  hung-but-still-running one (e.g. a Celery worker connected to Redis but
  deadlocked) without a `HEALTHCHECK` directive, which none of the three
  Dockerfiles define.
- **Sync-status endpoint itself is production-safe by construction** — it
  performs only two `SELECT`s against Django's own database, no WAHA call,
  no Celery/Redis dependency at request time (Section 3) — its behavior in
  production is identical to dev except for whichever real
  `RECONCILIATION_INTERVAL_SECONDS`/data the office environment actually
  has, which this audit cannot inspect.

---

## 10. Documentation Consistency Audit

Investigation items 11/12 — historical reports are **not** deleted or
edited by this audit, per instruction; classified only.

- **`README.md`** (re-confirmed this task, line 141): still states
  `| 9 | Offline/degraded mode | Not started — intentionally deferred... |`
  and its opening summary (line 21) still lists "Offline/degraded mode
  (Phase 9)... have not been started." **This is now stale** relative to
  the four uncommitted, code-complete slices this session produced —
  expected, since nothing has been committed yet, and therefore not a
  defect in any of the four implementation reports themselves, but a real
  gap that should be closed before this work is considered finished
  (Section 13).
- **`docs/generated/PHASE9-DESIGN-AUDIT-REPORT.md`,
  `PHASE9-1-DESIGN-AUDIT-REPORT.md`, `PHASE9-1A-DESIGN-AUDIT-REPORT.md`,
  `PHASE9-1E-DESIGN-AUDIT-REPORT.md`** — all four are design proposals
  whose recommendations were **implemented largely as written**; each
  corresponding implementation report (`PHASE9-0-...`,
  `PHASE9-1D-...`, `PHASE9-1A-SYNC-STATUS-...`,
  `PHASE9-1E-SYNC-STATUS-...`) explicitly documents the small number of
  places implementation diverged (e.g. 9.1E's single-effect refinement
  over the design's two-effect suggestion). **No undocumented
  contradiction was found between any design report and its own
  implementation report.**
- **`docs/generated/PHASE-9-ROADMAP-AUDIT-REPORT.md`** and
  **`docs/generated/CURRENT-STATE-AND-PHASE9-READINESS-AUDIT-REPORT.md`**
  — both now further superseded specifically on Inbox/Session-Management/
  sync-status status (they predate 9.1A/9.1E entirely, and the roadmap
  report predates even 9.0/9.1D) — already flagged as historical, not
  current, by the later `NEXT-DEVELOPMENT-AUDIT-REPORT.md` in this same
  set; this audit does not re-litigate that classification, only confirms
  it still holds.
- **No report was found to contradict another report's *factual* claims**
  about what code exists — the only drift found anywhere is the expected,
  known kind (a top-level status doc not yet updated for uncommitted work),
  not a factual disagreement between two reports about the same code.

---

## 11. Candidate Next Implementation Slices

Presented neutrally — purposes, affected files, dependencies, risks, and
testability only, **no ranking**, per instruction.

### A. 9.1B — Webhook-timestamp signal

- **Purpose**: surface "time since last webhook received" alongside sync
  status, narrowing (not eliminating) the "webhook broken vs. WhatsApp
  quiet" ambiguity (Section 8).
- **Files/components likely affected**: `backend/apps/sync/views.py`
  (one additional query + response field), `frontend/src/lib/djangoApi.ts`
  (`SyncStatus` interface addition), `frontend/src/pages/InboxPage.tsx`
  (optional display use).
- **Dependencies**: none — additive to the existing 9.1A response shape.
- **Risks**: low; one extra `WebhookEvent.objects.filter(session=session).aggregate(Max('received_at'))`-style
  query, still well within this project's existing "acceptable at current
  scale" performance posture (Section 10 of the 9.1A implementation
  report).
- **Testability**: straightforward — mirrors the existing
  `test_views.py` pattern with an added `WebhookEvent` fixture per case.
- **Independently implementable**: yes.

### B. 9.1C — Redis health endpoint

- **Purpose**: an independent `GET /api/health/redis/`-style check,
  mirroring `DatabaseHealthView` exactly, per the already-established
  "one dependency, one check" precedent.
- **Files/components likely affected**: a new view in `apps/core`
  (or similar), one new URL entry — no existing file's behavior changes.
- **Dependencies**: none — `redis==5.0.8` is already a direct
  dependency (confirmed in the 9.1A design report, unchanged since).
- **Risks**: low; same class of change as `DatabaseHealthView` already is.
- **Testability**: same pattern as `DatabaseHealthView`'s own existing
  tests (mock a connection failure, assert a non-200 response, assert no
  raw connection string is ever echoed).
- **Independently implementable**: yes — no dependency on 9.1A/9.1E or
  vice versa.

### C. 9.1F — Dashboard Redis card

- **Purpose**: complete the Dashboard's Row 1 health-card set (currently
  WAHA/Backend/PostgreSQL) with Redis, reusing `HealthCard` verbatim.
- **Files/components likely affected**: `frontend/src/pages/DashboardPage.tsx`
  only (one new `HealthCard` call), plus `frontend/src/lib/djangoApi.ts`
  (a `getRedisHealth()` function).
- **Dependencies**: **9.1C must exist first** — there is nothing to poll
  otherwise.
- **Risks**: minimal — smallest-scoped candidate in this list, identical
  in shape to the three existing Dashboard health cards.
- **Testability**: no frontend test infra exists (unchanged); manual
  browser verification only, same as every other Dashboard card.
- **Independently implementable**: no — blocked on B.

### D. Extend the connectivity-indicator pattern to `SessionsPage.tsx`

- **Purpose**: close the asymmetry named in Section 5/6 — give Sessions
  the same "can this page reach the server" visibility Inbox now has,
  instead of its current silent-swallow behavior on a failed status check.
- **Files/components likely affected**: `frontend/src/pages/SessionsPage.tsx`
  only — would need its own `reportPollOutcome`-equivalent (the existing
  one is a closure-scoped function inside `InboxPage.tsx`, not currently
  an exported/shared utility, so this would either duplicate the logic or
  require extracting it into a shared hook — a small, explicit design
  choice, not resolved here).
- **Dependencies**: none technical; a design decision (share vs.
  duplicate the connectivity logic) would need to be made first if this
  is picked up.
- **Risks**: touches an existing, working page (`SessionsPage.tsx`) —
  higher care needed than a purely additive change, though still
  small in absolute scope.
- **Testability**: no frontend test infra; manual verification only.
- **Independently implementable**: yes, fully independent of A/B/C.

### E. Surface sync status on `DashboardPage.tsx`

- **Purpose**: close the "only Inbox shows this" gap (Section 5, item 5)
  by adding a sync-status `HealthCard` to Dashboard, the page that already
  has the closest existing precedent for always-visible system health.
- **Files/components likely affected**: `frontend/src/pages/DashboardPage.tsx`,
  reusing `getSyncStatus()`/`mapSyncStatus()` from 9.1A/9.1E as-is.
- **Dependencies**: 9.1A only (already done) — does not depend on 9.1B/C/D.
- **Risks**: low — purely additive, reuses existing, already-tested client
  functions.
- **Testability**: manual only, same constraint as every frontend page.
- **Independently implementable**: yes.

### F. Documentation sync pass (`README.md` update)

- **Purpose**: close the staleness named in Section 10 — update
  `README.md`'s Phase 9 status line and "what's verified" section to
  reflect 9.0/9.1D/9.1A/9.1E's actual current state.
- **Files/components likely affected**: `README.md` only.
- **Dependencies**: none.
- **Risks**: essentially zero (documentation-only) — the only care needed
  is accuracy, matching this project's own established discipline of
  precise, evidence-based status claims rather than optimistic rounding.
- **Testability**: not applicable (no code).
- **Independently implementable**: yes, and could be done regardless of
  which other candidate is picked next.

### G. Stuck-`running` timeout/recovery

- **Purpose**: address the gap named in Section 5/6, item 3 — give a
  crashed-mid-run `SyncCheckpoint` a way back to a non-`running` state
  automatically.
- **Files/components likely affected**: `apps/sync/reconciliation.py`
  and/or `apps/sync/tasks.py` — this is the **only** candidate in this
  list that would touch `reconcile_session()`'s own write path, which
  every prior Phase 9 report (including this one) has treated as
  deliberately off-limits for a "minimal change" slice.
- **Dependencies**: a genuine design decision first — what counts as
  "stuck" (a timeout duration derived from what?), and whether recovery
  means auto-reclassifying to `'error'`, force-unlocking for a retry, or
  something else. None of this is derivable from the repository alone.
- **Risks**: materially higher than any other candidate here — touches
  the one piece of Phase 9-adjacent code every other slice this session
  deliberately left untouched, with real duplicate-write/race-condition
  considerations if done carelessly (e.g. two processes both deciding a
  checkpoint is "stuck" and racing to reclaim it).
- **Testability**: possible but non-trivial — would need to simulate a
  crashed run (e.g. directly constructing a `SyncCheckpoint` row with a
  stale `'running'` status and an old `updated_at`) and verify the
  recovery path doesn't corrupt or duplicate data.
- **Independently implementable**: yes, but with the caveat above — this
  is the one candidate this audit flags as needing a dedicated design
  audit of its own before implementation, not a direct "small slice."

### H. Celery worker liveness check (design only, not yet scoped anywhere)

- **Purpose**: distinguish "Redis down" from "Redis up, no worker" (Section
  7's named limitation), via something like `celery_app.control.ping()`.
- **Files/components likely affected**: unknown until designed — this is
  **not** currently described in any existing Phase 9 report at any level
  of detail; it would need its own design audit before a "files affected"
  list could even be stated with confidence.
- **Dependencies**: conceptually related to 9.1C (Redis health) but
  answers a different question (broker reachable vs. worker consuming) —
  whether it extends 9.1C or is a wholly separate check is itself an open
  design question.
- **Risks**: unknown/unscoped — `control.ping()`-style calls have their
  own timeout/failure-mode characteristics not yet investigated anywhere
  in this project's history.
- **Testability**: unknown until designed.
- **Independently implementable**: unclear — flagged here only to name
  that it exists as a real gap (Section 7), not to propose it as ready to
  build.

---

## 12. Dependency Order for the Next Work

Stated as dependency facts only, per instruction — not a priority ranking.

- **Fully independent of every other candidate and of each other**: A
  (9.1B), B (9.1C), D (Sessions connectivity), E (Dashboard sync card), F
  (README update). Any of these could be started next without waiting on
  anything else in this list.
- **C (9.1F) depends on B (9.1C)** — cannot be built before B exists.
- **G (stuck-`running` recovery) depends on a dedicated design decision
  first** (not listed as a dependency on any other candidate here, but on
  a product/architecture decision this audit does not make).
- **H (Celery worker liveness) depends on being designed at all** — not
  yet at the "implementation candidate" maturity level any other item in
  this list is at; its relationship to B is itself an open question, not
  a settled dependency.
- **F (README update) has no code dependency on anything**, but is most
  naturally done *after* whichever other candidates are chosen, so it
  only needs to be written once rather than updated repeatedly — a
  sequencing convenience, not a hard technical dependency.

---

## 13. USER DECISIONS REQUIRED

1. **Which candidate slice (if any) to pick up next** — Section 11
   deliberately does not rank A/B/D/E/F against each other; all five are
   independently viable.
2. **Whether G (stuck-`running` recovery) should get its own dedicated
   design audit now, or remain a known, documented, unaddressed gap for
   longer** — this is the one candidate this report explicitly does not
   treat as "ready to implement directly."
3. **Whether H (Celery worker liveness) is wanted at all**, and if so,
   whether it should extend 9.1C or be a separate mechanism — currently
   not designed anywhere, this report only names it as a real gap.
4. **Whether/when to do F (the `README.md` update)** — no technical
   blocker, purely a sequencing/timing choice (e.g. batch it with the next
   code slice vs. do it now to keep documentation current).
5. **Whether 9.1B (webhook timestamp) should extend the existing 9.1A
   response object, or become a separate endpoint** — both remain
   structurally valid (Section 8); this report does not choose.
6. **Whether Redis/Celery health (9.1C) should stay a separate endpoint
   from sync status, or ever be merged into it** — Section 7 states the
   trade-off (this project's "one dependency, one check" precedent favors
   separate) without deciding it for you.
7. **Confirm `RECONCILIATION_EXECUTOR`'s real production value** — same
   unresolved item carried forward from every prior Phase 9 report this
   session; still not independently verifiable from this environment.

---

## Summary

Phase 9.0, 9.1D, 9.1A, and 9.1E are confirmed code-complete, mutually
non-interfering, and built without any new architecture, dependency, or
schema change. The remaining Phase 9 surface — webhook health,
Redis/Celery health, stuck-`running` recovery, and consistent coverage
across Sessions/Dashboard, not just Inbox — is fully mapped in this report
with concrete, independently-assessed candidate slices and their real
dependencies, but no next step has been chosen or started here.

**No source code, `.env`/configuration, database schema or data, or WAHA
state was modified in the course of producing this report.** No write
endpoint was called and no WhatsApp message was sent. This was a read-only
audit; per instruction, nothing further is implemented — awaiting your
decisions in Section 13.
