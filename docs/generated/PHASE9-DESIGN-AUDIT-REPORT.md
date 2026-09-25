# Phase 9 Design Audit — Offline / Degraded-State Handling (Read-Only)

**Scope.** Read-only design audit. No source, `.env`, migration, Dockerfile,
WAHA configuration, or deployment configuration was modified. No write
endpoint was called. No WhatsApp message was sent. No service was
started/stopped. This report designs Phase 9 against the architecture and
code that actually exist today (confirmed by direct reading this round, and
by `git status` showing zero drift since the two prior audits earlier this
session) — it does not implement anything, and per instruction it stops at
the "USER DECISIONS REQUIRED" section rather than proceeding.

Every finding below is labeled **CONFIRMED** (read directly from source),
**INFERRED** (a reasonable conclusion not explicitly stated anywhere),
**PROPOSED** (a design option this report suggests, not a decision), or
**USER DECISION REQUIRED** (this report cannot resolve it and does not
guess).

---

## 1. Executive Summary

Phase 9's canonical purpose — degrade gracefully when Django/PostgreSQL is
unreachable while WAHA/Tencent stays live, and label data
live/cached/stale/unavailable rather than presenting a false "everything is
fine" or a false "everything is down" — is **well-supported by architecture
that already exists**, more so than a from-scratch reading of
`docs/03-UI-UX-SPEC.md` alone would suggest. Three pieces of existing,
reusable infrastructure make this Phase cheaper than it might look:

1. **A complete error taxonomy already exists** in
   `frontend/src/lib/api.ts` (`ApiError.kind`: `network_error`, `timeout`,
   `server_error`, `unauthorized`, `forbidden`, `not_found`, `validation`,
   `unknown`) and is already threaded through every API call in the
   frontend. Phase 9 does not need a new error-classification system — it
   needs the polling loops (which currently discard this classification on
   every failed tick) to start using it.
2. **A reusable, already-proven `HealthCard` UI pattern** exists on the
   Dashboard (`frontend/src/pages/DashboardPage.tsx`), and a matching
   `LivenessView`/`DatabaseHealthView` backend pattern
   (`backend/apps/core/views.py`) — both trivially extensible to a Redis
   health card without inventing new architecture.
3. **The BFF already reports WAHA reachability distinctly from BFF-process
   health**, and says so in its own code comment: `bff/src/routes/health.ts:1-3`
   explicitly states this is "the 'which upstream failed' signal Phase 9's
   degraded-mode UI will consume" — this was already built with Phase 9 in
   mind and needs no change.

**What genuinely does not exist yet and blocks part of Phase 9's scope**:
`SyncCheckpoint` has zero HTTP read surface (confirmed, unchanged from the
prior two audits); Redis has zero health check anywhere; and two concrete,
previously-undocumented gaps were found this round during a full read of
`InboxPage.tsx`:
- A poll failure during an **already-open** session is completely invisible
  (no state, no indicator) — this was known qualitatively from the prior
  audit; this round confirms it precisely: the code does not even inspect
  `ApiError.kind` on a failed poll tick, so a `401` (expired session) and a
  transient network blip are handled identically (silently skipped forever)
  even though only one of them can ever self-recover by retrying.
- **A genuine instance of the exact risk the task brief warned about**: when
  a send resolves to the ambiguous `'unknown'` outcome (BFF/WAHA timeout —
  genuinely unknown whether WhatsApp received it), `InboxPage.tsx` clears
  the compose box and shows **no explicit message at all** — contrast with
  `SessionsPage.tsx`, which has a proven, already-correct pattern for this
  exact case ("The ... request timed out ... may or may not have been
  affected"). This is flagged prominently in Section 10 and Section 12 as a
  direct, concrete, low-risk fix in the spirit of the task's explicit
  warning — proposed, not implemented here.

Phase 9, as designed in this report, is a set of **small, additive, mostly
independent pieces** built entirely on existing patterns: two new read-only
backend endpoints (or fields on an existing endpoint), one new frontend
connectivity-state utility reusing the existing error taxonomy, and UI
wiring that reuses existing components (`HealthCard`, `StatusBadge`,
`ErrorState`). No new architecture, no new dependency (Redis's Python client
is already a direct dependency — `redis==5.0.8` in `backend/requirements.txt`,
confirmed this round), no BFF contract change is required by the default
design in this report.

---

## 2. Current Architecture Relevant to Phase 9

**CONFIRMED**, read directly this round unless noted:

- Frontend talks to two origins directly: Django (`djangoApi.ts` — health,
  auth, dashboard, chats) and the BFF (`bffApi.ts` — sessions, send). There
  is no unified "backend" concept in the frontend's networking layer; every
  page already has to reason about which origin it's calling.
- Every network call in the frontend goes through one shared function,
  `request()` in `frontend/src/lib/api.ts`, which already classifies every
  outcome into the 8-way `ApiError.kind` taxonomy described in Section 1.
- Every page's *first* load goes through `useApiQuery()`
  (`frontend/src/lib/useApiQuery.ts`), a shared loading/success/error state
  machine — but this hook has **no polling/interval concept at all**; every
  page that polls (`InboxPage.tsx`, `SessionsPage.tsx`) implements its own
  separate `setInterval`/`setTimeout` loop by hand, outside this hook, and
  each one currently discards the `ApiError.kind` on failure.
- Health/availability signals that already exist, independently checked,
  matching `docs/01-ARCHITECTURE.md`'s "failure isolation" principle:
  - `GET /api/health/` (Django process liveness — `LivenessView`, no DB
    touch, no auth).
  - `GET /api/health/database/` (PostgreSQL reachability — `DatabaseHealthView`,
    no auth, never echoes raw driver error text).
  - `GET /health` (BFF process + WAHA reachability, via a live
    `getSessionStatus` call — `bff/src/routes/health.ts`, no auth).
  - None of these three exist for Redis, or for sync/reconciliation
    freshness — confirmed absent this round (repeated from the prior audit,
    re-verified).
- `SyncCheckpoint` (Section 4) is written by exactly one code path
  (`reconcile_session()`) and read by **nothing** — no view, no serializer,
  no frontend reference anywhere (re-confirmed by fresh grep this round:
  zero matches for `SyncCheckpoint|sync_status|syncStatus|lag_seconds` in
  `frontend/src`).
- Redis (Section 5) is used for exactly one purpose: Celery broker +
  result backend. No Django `CACHES` setting references Redis (confirmed
  this round — no `CACHES` key exists in `backend/config/settings.py` at
  all); no session store, no rate-limit store, nothing else touches Redis.
- `WahaSession.status`/`last_status_at` (the DB fields, distinct from the
  live BFF status query) are **defined but never written anywhere in
  application code** — confirmed this round via a repository-wide grep for
  any assignment to `WahaSession.status`. The Sessions page's live status
  display comes entirely from a real-time BFF→WAHA call, with **no durable
  fallback value stored anywhere** if that live call fails. This is a
  CONFIRMED, pre-existing fact relevant to Section 7/12 — not a bug, but a
  design constraint: there is nothing in the database to show as "last known
  session status" if WAHA is genuinely unreachable; the honest degraded
  state is "unknown," not a stale cached value.

---

## 3. Current Failure Handling

**CONFIRMED**, this round:

| Surface | On first-load failure | On ongoing-poll failure |
|---|---|---|
| Dashboard health cards | `ErrorState`/`StatusBadge status="error" label="Unreachable"` (immediate, via `useApiQuery`) | N/A — Dashboard cards don't poll on an interval, only fetch once per mount |
| Sessions status | `StatusBadge status="error" label="Unreachable"` (via `useApiQuery`) | **Silent** — `runTick()`'s failure branch just calls `setIsSyncing(false)` and keeps the last known `liveStatus`, no error surfaced |
| Inbox chat list | `ErrorState` with retry button (via `useApiQuery`, only while `chats === null`) | **Silent** — failed tick is skipped entirely, `ApiError.kind` never inspected |
| Inbox messages | Same pattern as chat list | Same silent-skip pattern |
| Inbox send (write) | N/A | `ErrorState` shown for a confirmed failure; **no explicit UI for the `'unknown'` (ambiguous) outcome** — see Section 1/10/12 |
| Session lifecycle actions (write) | N/A | Explicit three-way feedback already exists: success / `'unknown'` (with an honest "may or may not have been affected" message) / error — this is the **proven pattern** Section 10/12 proposes reusing for Inbox's send |

**What this table shows, stated plainly**: the codebase already has two
different, inconsistent postures for "the same kind of failure" — Sessions'
one-shot status query and Inbox's chat/message loads both show a clear error
on *first* load, but go completely silent once they've succeeded once and
start polling. Phase 9's core frontend job is closing that gap consistently,
not inventing a new failure-reporting concept.

---

## 4. SyncCheckpoint Audit

**CONFIRMED**, `backend/apps/sync/models.py` (full file) and
`backend/apps/sync/reconciliation.py` (full file), both re-read this round:

- **Fields**: `session` (`OneToOneField` to `WahaSession`, `on_delete=PROTECT`),
  `checkpoint_value` (`CharField`, holds an ISO-8601 timestamp string, blank
  by default), `last_run_at` (`DateTimeField`, nullable), `status`
  (`idle`/`running`/`ok`/`error`, default `idle`), `lag_seconds`
  (`PositiveIntegerField`, nullable), `last_error` (`TextField`, blank).
- **One checkpoint per session**: confirmed by the `OneToOneField` and by
  `reconcile_session()`'s own `SyncCheckpoint.objects.get_or_create(session=session)`.
- **Who updates it, and when**: exactly one function,
  `reconcile_session()` (`backend/apps/sync/reconciliation.py:155-247`).
  Lifecycle: `status → RUNNING` immediately (saved eagerly, before any WAHA
  call — line 183-184); at the end, `status → OK` with `checkpoint_value`
  advanced (only if the run had zero errors) or `status → ERROR` with
  `last_error` populated and `checkpoint_value` **deliberately not
  advanced** (lines 233-246). `last_run_at` is always updated, success or
  failure. This is reached identically by **every** trigger path (HTTP
  internal-trigger, Celery periodic, Celery targeted, management command) —
  they all funnel through this one function, so the checkpoint reflects the
  true state of the *last* attempt regardless of which mechanism ran it.
- **CONFIRMED, previously undocumented finding**: `lag_seconds` is defined
  on the model and in its migration, but is **never assigned anywhere in
  application code** — grepped this round across the entire `backend/`
  tree; the only two matches are the model definition itself and the
  migration. It is a structurally dead field today. This is an **OUT OF
  SCOPE FINDING** (pre-existing, not something this audit was asked to fix)
  but directly relevant to Section 4's own question about freshness — see
  below.
- **Can it be used for freshness today?** Partially, and only via
  `last_run_at` + `status`, not `lag_seconds` (which is always `null`).
  "Freshness" as currently derivable means: *when did reconciliation last
  run, and did that run complete without error* — not *how far behind is
  the actual data* (which is what "lag" implies and what `lag_seconds`'
  name suggests it should hold). This distinction matters for Section 7's
  state model: a `last_run_at` 20 minutes ago with `status='ok'` tells you
  reconciliation is *working*, not that data is *current* — the periodic
  interval (`RECONCILIATION_INTERVAL_SECONDS`, default 900s) is itself the
  bound on how current "current" can ever be for inbound messages that rely
  solely on periodic reconciliation as a webhook backstop (Section 9).
- **Does a read endpoint exist?** No — `backend/apps/sync/urls.py` exposes
  only `reconciliation/trigger/` (internal-key-gated, write-triggering).
  Confirmed absent again this round.
- **Is a new endpoint needed?** **Yes, in this report's assessment** — there
  is currently no way for the frontend to know reconciliation health at all,
  and `docs/03-UI-UX-SPEC.md`'s explicit "Sync: STALE/OK" example line has
  nothing to read from. This is a recommendation, not something implemented
  here; see Section 11 for the concrete shape options.
- **Minimum data to return, if built** (PROPOSED): per session — `status`,
  `last_run_at`, and a server- or client-computed "seconds since last run."
  **Recommend NOT returning `lag_seconds` as-is** (it would always be
  `null` today and would be misleading to expose); **recommend NOT
  returning raw `last_error` text on an unauthenticated endpoint** (see
  Section 17) — if error detail is wanted, gate the endpoint behind
  authentication, consistent with how `apps/core/exceptions.py` already
  treats raw error text as sensitive.

---

## 5. Redis/Celery Audit

**CONFIRMED** this round:

- Redis's **only** application-level role: Celery broker (`CELERY_BROKER_URL`)
  and result backend (`CELERY_RESULT_BACKEND`), both defaulting to
  `redis://redis:6379/0` (`backend/config/settings.py:179-180`). No Django
  `CACHES` setting exists anywhere — confirmed by grep this round, zero
  matches for `CACHES` in `settings.py`. No session backend, no rate-limit
  store (rate limiting doesn't exist yet at all — Phase 12).
- Celery's only application is background reconciliation
  (`reconcile_all_sessions_task` — periodic, `reconcile_session_task`,
  `reconcile_chat_task` — targeted). No other Celery task exists anywhere
  in the codebase (re-confirmed this round: `backend/apps/sync/tasks.py` is
  the only file defining a `@shared_task`/`@app.task`).
- **Impact of Redis being down, traced through the actual code, `sync` vs
  `celery` executor**:
  - `RECONCILIATION_EXECUTOR='sync'` (dev default): reconciliation runs
    in-process, inside the Django request/worker thread. **Redis is not
    touched at all on this path** — a Redis outage has zero effect on
    reconciliation when this executor is selected.
  - `RECONCILIATION_EXECUTOR='celery'`: `trigger_reconciliation()` calls
    `reconcile_chat_task.delay(...)` (`backend/apps/sync/executors.py:81-83`).
    Celery's `.delay()` publishes to the broker **synchronously** at call
    time — if Redis is unreachable, this raises a connection exception
    inside the Django request that's handling
    `POST /internal/reconciliation/trigger/`. That request is itself only
    ever called by the BFF's fire-and-forget `triggerReconciliation()` call
    (`bff/src/routes/messages.ts:135-139`), which is never awaited before
    the send's own HTTP response — **so a Redis outage in `celery` mode
    does not block or fail an outbound send response**, it only means the
    post-send reconciliation trigger silently fails (the BFF's own
    `.then()` diagnostic logs a warning, nothing more).
  - The **periodic** Celery Beat task (`reconcile_all_sessions_task`) would
    also fail to dispatch during a Redis outage — this is the *general*
    inbound-message safety net (Section 9), and it is unavailable for the
    duration of the outage.
  - **CONFIRMED, concrete consequence worth naming explicitly**: in
    `celery` executor mode, a Redis outage disables **both** reconciliation
    paths simultaneously (targeted post-send *and* periodic). An outbound
    message sent during a Redis-and-webhook-blind window would not appear
    in Inbox until Redis recovers **and** a subsequent periodic run
    succeeds — nothing in the current architecture re-triggers
    reconciliation just because a user reopens the Inbox page. This is a
    real, narrow gap directly relevant to Phase 9's purpose (Section 9,
    Section 10).
- **Whether production actually runs `celery` executor**: **INFERRED, not
  CONFIRMED** — `infrastructure/office/docker-compose.yml` provisions
  `celery-worker`/`celery-beat`/`redis` services, which only makes sense if
  `RECONCILIATION_EXECUTOR=celery` is set in the office `.env`, but nothing
  in code *enforces* this — the Django default, if the office `.env` ever
  omits this var, is `'sync'`, which would silently run reconciliation
  in-request inside `gunicorn` workers instead of via the provisioned Celery
  infrastructure. This is a **USER DECISION / confirmation item**, not
  something this audit can resolve from source code alone — see Section 22.
- **Does Phase 9 need a Redis health endpoint?** **Yes, as a diagnostic
  signal, not a live-request blocker** — given Redis's only role is
  background reconciliation, a Redis health check's value is entirely in
  *explaining* why sync/reconciliation might be behind (the "Sync" status
  line), not in gating any live user-facing feature (nothing live touches
  Redis). **Recommend**: a `RedisHealthView` mirroring `DatabaseHealthView`'s
  exact shape/pattern (independent of `LivenessView`, matching the
  project's own established "check each dependency independently" precedent
  — `docs/01-ARCHITECTURE.md`), no new dependency needed (`redis==5.0.8` is
  already a **direct** dependency in `backend/requirements.txt`, confirmed
  this round — not merely transitive via `celery[redis]`).
- **Readiness vs. liveness distinction**: the project already implicitly
  has this (Liveness = process up; DatabaseHealth/future RedisHealth =
  dependency reachable) — recommend following the exact same shape, not
  inventing a new readiness/liveness vocabulary.

---

## 6. Inbox Polling Audit

**CONFIRMED**, `frontend/src/pages/InboxPage.tsx` read in full this round:

- **Chat list polling** (`InboxPage.tsx:67-76`): `setInterval`, fixed
  `CHAT_LIST_POLL_MS = 8000`. On failure: `if (result.ok) setChats(...)` —
  no `else` branch at all. The error is discarded, not even logged. State
  is simply left as whatever it was before the failed tick.
- **Messages polling** (`InboxPage.tsx:104-111`): same pattern,
  `MESSAGES_POLL_MS = 5000`, discards `ApiError.kind` identically.
- **No consecutive-failure tracking exists anywhere** — every tick is
  independent; there is no counter, no backoff, no distinction between "just
  failed once" and "has been failing for the last ten minutes."
- **No distinction by `ApiError.kind`** — confirmed this round by reading
  every branch: `network_error`, `timeout`, `server_error`, `unauthorized`,
  `forbidden`, `not_found`, `validation`, and `unknown` are **all** treated
  identically on a poll failure (silently skipped). This has one specific,
  concrete consequence worth naming: **a `401 unauthorized` (e.g. the JWT
  genuinely expired server-side, or was revoked) during ongoing polling is
  indistinguishable, in the UI, from a transient network blip** — except
  that a `401` will *never* self-resolve by retrying on the same interval,
  unlike a transient blip might. A user could be looking at an increasingly
  stale, frozen Inbox indefinitely with zero indication they need to log in
  again. (Separately, CONFIRMED: `AuthContext.tsx`'s own expiry handling is
  driven by decoding the JWT's `exp` claim client-side on a `setTimeout`,
  not by observing a live `401` response — so this specific gap is not
  caught by that mechanism either.)
- **Initial load vs. ongoing poll — the exact boundary**: `chatsQuery.status
  === 'error' && chats === null` is the only condition under which an error
  is shown (`InboxPage.tsx:180`) — the moment `chats` has ever been
  successfully populated once, this branch can never fire again, no matter
  how many subsequent polls fail. Same structure for messages
  (`InboxPage.tsx:239`).
- **Empty states are correctly distinct from failure states** — `chats &&
  chats.length === 0` (a genuine, successfully-confirmed zero) is a
  separate branch from the loading/error branches, so there is no risk of
  an empty inbox being confused with a failed poll *today*. Phase 9 should
  preserve this distinction exactly (Section 20).
- **Write path (send) already distinguishes success from ambiguity
  partially** — `sendConfirmed` is explicitly set to `false` when
  `result.data.status === 'unknown'` (`InboxPage.tsx:160`), so the "Message
  sent" confirmation banner correctly does **not** appear for an ambiguous
  outcome. **But nothing else appears either** — no `'unknown'`-specific
  message exists in `InboxPage.tsx`, unlike `SessionsPage.tsx`'s proven
  `feedback.kind === 'unknown'` branch, which shows an explicit sentence.
  This is the concrete instance of the risk named in the task brief
  (Section 1, Section 10, Section 12).

---

## 7. Proposed Degraded-State Model

**PROPOSED.** Built entirely on the existing `ApiError.kind` taxonomy
(Section 2/6) — no new error classification is introduced.

**Two categorically different failure classes already exist in the data,
just unused**:
1. **Connectivity/availability** (`network_error`, `timeout`,
   `server_error`, `unknown`) — self-recovering in principle; retrying on
   the existing poll interval is the correct response, already happening,
   just invisible.
2. **Authorization** (`unauthorized`, `forbidden`) — **not**
   self-recovering by retrying; the correct response is prompting
   re-authentication, not implying "data is just a bit old."

**Proposed states** (names below are illustrative, not final — see the note
on terminology at the end of this section):

- **LIVE** — the most recent poll (of whichever loop is relevant to the
  current view) succeeded.
- **RECONNECTING** — 1 to N consecutive connectivity-class failures
  (N is a tunable threshold, PROPOSED default 2–3 consecutive failures,
  i.e. roughly 10–25 seconds at Inbox's existing poll cadence — chosen only
  to avoid flickering into a visible state on one single transient blip;
  this is a tuning choice, not derived from any document, and should be
  treated as adjustable). Last-known-good data stays displayed, unchanged.
  Polling continues on its existing interval — no change to retry cadence.
- **STALE** — connectivity-class failures have exceeded the threshold. Same
  last-known-good data still displayed (never blanked, never replaced with
  an error screen), but a persistent, visible indicator appears. Recovery
  is automatic the moment a poll succeeds again — no manual "reconnect"
  action is structurally required, since polling already retries
  indefinitely on its own.
- **NEEDS_REAUTH** — an authorization-class failure (`unauthorized`/`forbidden`)
  during polling. Categorically different from STALE: retrying will never
  fix this. Should prompt the user to sign in again, not imply staleness.

**Scope of tracking — combined vs. per-loop (USER DECISION, with a
recommendation)**: Inbox has two independent poll loops (chat list,
messages-of-open-chat). **Recommended default: track one combined
"Inbox connectivity" state**, not two separate indicators — in practice
both loops hit the same Django origin and fail together (a Django/network
outage affects both simultaneously; they essentially never fail
independently), and one indicator is simpler UI than two competing badges.
The per-loop alternative is architecturally possible (each loop already has
its own `setInterval`) but adds UI complexity for a failure mode this
report found no evidence actually occurs independently in practice.

**Manual retry**: not structurally required (automatic retry via the
existing poll interval already exists), but an optional "Retry now" action
that simply fires one out-of-cycle poll is a low-cost UX nicety — PROPOSED,
optional, not required for the model to work correctly.

**On terminology**: the task brief's example (🟢 Live / 🟡 Reconnecting /
🔴 Offline-stale) is a reasonable three-state shape and is *not*
contradicted by anything in `docs/03-UI-UX-SPEC.md` (which itself uses
"live/cached/stale/unavailable" as its own vocabulary, not a fixed
three-word set) — this report does not find an existing, more-specific
terminology already established anywhere in the codebase for *this specific
kind* of indicator (the closest precedent, `StatusBadge`, already supports
arbitrary `label` text with a `status` tint, so it imposes no fixed
vocabulary either). **Recommend reusing `docs/03-UI-UX-SPEC.md`'s own
words** (Live / Stale / Unavailable, plus a transitional "Reconnecting")
for consistency with the canonical spec, rather than inventing new terms —
but this is a naming choice, not an architectural one, and is listed under
Section 22 as something to confirm rather than something this report
decides unilaterally.

---

## 8. State Machine / State Transition

**PROPOSED.**

```
                  poll succeeds
        ┌─────────────────────────────────┐
        │                                  │
        ▼                                  │
    ┌───────┐   connectivity-class    ┌───────────────┐
    │ LIVE  │ ─── failure (1st) ────► │ RECONNECTING  │
    └───────┘                          └───────────────┘
        ▲                                  │      │
        │                            poll succeeds │ N consecutive
        │                                  │        │ connectivity
        │                                  │        │ failures
        │                                  ▼        ▼
        │                          ┌───────┐    ┌────────┐
        └────── poll succeeds ─────│ (back  │    │ STALE  │
                                    │ to LIVE)    └────────┘
                                                       │
                                              poll succeeds
                                                       │
                                                       ▼
                                                (back to LIVE,
                                                 same as above)

    Any state ─── unauthorized/forbidden on any poll ───► NEEDS_REAUTH
    NEEDS_REAUTH ─── user re-authenticates (new token) ───► LIVE (fresh poll)
```

**Transition rules, explicit**:
- `LIVE → RECONNECTING`: on the *first* connectivity-class failure after a
  success (or on mount, if the very first load fails — though that case is
  already handled by the existing `ErrorState` pattern and does not need
  this state machine at all; the state machine only governs *ongoing*
  polling after at least one success).
- `RECONNECTING → STALE`: after N consecutive connectivity-class failures
  (PROPOSED default 2–3; see Section 7's caveat that this is tunable).
- `RECONNECTING → LIVE` or `STALE → LIVE`: immediately on the next
  successful poll — no debounce, no minimum "settled" period, since a
  single success is real, current data.
- `Any state → NEEDS_REAUTH`: on any `unauthorized`/`forbidden` response
  during polling, regardless of current state — this pre-empts the
  connectivity ladder entirely, since retrying will not help.
- `NEEDS_REAUTH → LIVE`: only after a fresh, successful authentication
  (out of scope for this state machine itself to implement — it should
  simply surface the need, consistent with `describeError()`'s existing
  "Your session has expired. Please sign in again." message, which already
  exists and is reused, not reinvented).
- **The underlying data (chat list / messages) is never cleared or
  replaced by any state transition** — this is the single most important
  invariant, directly serving the task brief's "operator must not think
  nothing happened" concern, generalized from sends to reads: an operator
  should never see a *blank* Inbox because of a transient failure, only a
  possibly-stale one, clearly labeled as such once it's been stale long
  enough to matter.

---

## 9. Dependency Failure Matrix

**CONFIRMED facts, traced through actual code paths — no invented
dependency.**

| Dependency | Failure | Impact (confirmed from code) | UI today | Recovery |
|---|---|---|---|---|
| **Django** | Unreachable from browser | Inbox reads (chat list/messages/mark-as-read — all Frontend→Django direct) fail. Dashboard health cards already show "Unreachable." **Outbound send is unaffected** — BFF's internal calls to Django (register/resolve `OutboundOperation`, audit log, reconciliation trigger) are all explicitly "best-effort": `messages.ts` proceeds to call WAHA even if Django registration failed (`registration.ok` false → `operationId` stays `undefined`, send still attempted). Session Management is also unaffected (BFF→WAHA direct, doesn't call Django for live status). | Initial load: `ErrorState`. Ongoing poll: silent (Section 6). | Automatic — next successful poll, or `ErrorState`'s manual retry on first load. |
| **BFF** | Unreachable from browser | Session Management **entirely unavailable** (no fallback path exists — every lifecycle action is BFF-only). Outbound send **entirely unavailable** (BFF-only). Inbox reads unaffected (Django-direct). Dashboard's WAHA card shows unreachable (frontend's fetch to the BFF itself fails). | `StatusBadge status="error"` on Sessions' first load; silent on the settle-poller (Section 3). No dedicated Inbox indicator today (Inbox doesn't call the BFF except on send, which already has its own `ErrorState`). | Automatic — next successful poll/action. |
| **WAHA** | Unreachable, but BFF/Django up | Session lifecycle actions fail at the WAHA-call step — **already gracefully handled**: BFF maps WAHA `timeout`/`network_error` to a distinct `'unknown'` outcome, `http_error` to a real failure (no Phase 9 change needed here, this is already correct, principle #4/#5 preserved by design). Outbound send: same existing 3-way outcome handling. Inbound webhooks stop arriving — **indistinguishable, from Django's side, from "WAHA is fine but WhatsApp is just quiet"** (Section 9's most significant confirmed gap). Reconciliation (if triggered) fails at the fetch step, caught (`WahaClientError`), recorded in `SyncCheckpoint.last_error`, checkpoint not advanced — graceful, but invisible to the frontend today (no read endpoint). | Sessions: existing `'unknown'`/error handling (already correct). Inbox: nothing surfaces webhook silence. | For webhook silence specifically: only the periodic reconciliation task, bounded by `RECONCILIATION_INTERVAL_SECONDS` (default 900s = up to 15 minutes of possible inbound lag, silently). |
| **Redis** | Unreachable | Confined entirely to Celery (Section 5) — no live user-facing path touches Redis. In `celery` executor mode: periodic reconciliation doesn't run; the post-send targeted trigger fails silently (does not block or fail the send response, by design). In `sync` executor mode (dev default): **zero impact**, Redis isn't touched on this path at all. | None today (no Redis health check exists). | Automatic once Redis recovers, for the *next* periodic run or the *next* post-send trigger — no retroactive re-trigger of the missed window exists. |
| **Webhook delivery stops** (WAHA misconfigured, or a Tencent↔Office network partition, while WAHA itself keeps receiving WhatsApp traffic) | New messages never reach Django via webhook | This is the **single most significant confirmed gap** relevant to Phase 9's core purpose: there is no heartbeat/liveness signal for the webhook channel itself — Django cannot distinguish "webhook is broken" from "no new WhatsApp activity happened." The only existing safety net is periodic reconciliation (up to 15 minutes of lag, by default config). Outbound messages have an *additional* safety net (the post-send targeted trigger); inbound messages rely solely on webhook-or-periodic-reconciliation. | Nothing today. | Bounded by `RECONCILIATION_INTERVAL_SECONDS` only — this is exactly the kind of staleness `docs/03-UI-UX-SPEC.md`'s "Sync: STALE" line is meant to communicate, and is currently unbuilt (Section 4). |
| **Network** (browser ↔ BFF/Django, general partition, either direction) | Requests time out or fail to reach the server | Already correctly classified by the existing `ApiError.kind` taxonomy (`network_error`/`timeout`) at the transport layer — this is not a new failure mode to detect, only one whose classification is currently discarded by the polling loops (Section 6/7). | Same as "Django unreachable" / "BFF unreachable" rows above, since from the browser's perspective a network partition and a genuinely-down server are indistinguishable. | Automatic on next successful poll. |

---

## 10. Read vs Write Failure Handling

**CONFIRMED analysis, explicit per the task's own emphasis.**

1. **Read failure** (Inbox chat list/messages, Dashboard, Session status
   read): never risks implying something happened that didn't — a failed
   read just means "can't refresh the view right now." Already safe by
   construction; Phase 9's job here is purely about **visibility** of
   staleness (Section 7/8), not correctness (correctness is already fine).

2. **Write failure — Send message**: the underlying mechanism is
   **already correct and is not proposed to change** (principle #4):
   three-way outcome (`sent`/`failed`/`unknown`) from the BFF, backed by the
   `OutboundOperation` idempotency state machine. `InboxPage.tsx`'s existing
   `sendConfirmed` text ("Message sent — it will appear in the history once
   it's confirmed by the server") already correctly avoids conflating "WAHA
   accepted it" with "it's durably visible yet." **The one concrete,
   confirmed gap**: the `'unknown'` outcome shows *nothing* — no banner, no
   text, just a cleared compose box, identical in appearance to a normal
   successful send *minus* the confirmation line. An operator who doesn't
   notice the absence of a confirmation message could easily assume the
   send worked. **This is the exact risk the task brief named explicitly**
   ("Jangan sampai desain degraded-state membuat operator mengira pesan
   berhasil terkirim padahal status send sebenarnya tidak diketahui").
   **PROPOSED fix** (Section 12): reuse `SessionsPage.tsx`'s already-proven
   `'unknown'`-outcome message pattern verbatim in `InboxPage.tsx` — this
   is not a new pattern, just applying an existing, working one to a second
   page. Minimal, low-risk, directly addresses the named concern.

3. **Send succeeded, reconciliation failed** (e.g. Redis down in `celery`
   mode, or the internal-trigger call itself fails for any reason): the
   send **genuinely succeeded** (irreversible — the message reached
   WhatsApp) — `sendConfirmed = true` is **correct** to show, and should
   **not** change. The only gap is that nothing distinguishes "will appear
   shortly" from "will appear once the periodic job catches up (could be
   several minutes)." **Recommend**: do not add a per-message indicator for
   this (would be over-engineering a narrow edge case) — instead, let the
   Section 7 connectivity/sync state (if it also reflects reconciliation
   health, per the optional Section 11 design) implicitly cover this: if
   reconciliation is degraded, the same "Sync: STALE" signal that governs
   inbound-message lag also explains outbound-reappearance lag, without a
   second, message-specific mechanism.

4. **Webhook failure** (inbound messages stop arriving): purely a
   background problem, not directly observable from any single frontend
   interaction — the only honest way to surface it is via the
   `SyncCheckpoint`-derived "Sync" signal (Section 4/9), since inventing a
   webhook-specific heartbeat would be new architecture the codebase has no
   precedent for and principle #8 explicitly discourages ("Jangan membuat
   architecture baru hanya demi health indicator"). **Optional, cheap
   addition** (PROPOSED): also expose the latest `WebhookEvent.received_at`
   (already stored per-event, `apps/webhooks/models.py`) alongside the sync
   checkpoint — "last webhook received at" is a strictly cheaper, more
   direct signal of webhook-channel health than reconciliation status alone
   is, and requires no new field, just one more query in whatever endpoint
   Section 11 builds.

5. **Redis/Celery failure** (background only): as established in Section 5,
   this is purely a diagnostic signal, not a live-blocking concern — the
   Redis health check exists to help explain *why* sync might be behind,
   not to gate any live feature.

---

## 11. Proposed API Changes

**PROPOSED — not implemented.** Two independent additions, no dependency
between them.

**A. Sync/reconciliation status read surface.** Two shape options,
presented without a forced pick (this is a genuine design fork worth your
input, Section 22):

- **Option A1 — dedicated endpoint**: `GET /api/sync/status/` (or similar),
  new `apps.sync` HTTP surface (currently has none — this would be new-app
  Django wiring, not a tweak to an existing view). Returns, per known
  session: `session`, `status`, `last_run_at`, `seconds_since_last_run`
  (server-computed), and optionally `last_webhook_received_at` (Section
  10.4). Auth: **recommend following the `Liveness`/`DatabaseHealth`
  precedent — unauthenticated**, since this is operational/infra state, not
  conversation content — **but see Section 17's caveat about `last_error`**.
- **Option A2 — extend the existing Dashboard aggregate**: add a `sync`
  field to `GET /api/dashboard/...` (which the frontend already polls/fetches
  as the project's established cross-cutting-health aggregation point).
  Slightly less "new surface area" than A1, but couples an operational
  health signal into an endpoint that's otherwise about business metrics
  (messages/activity) — a naming/cohesion trade-off, not a technical one.

  **This report does not pick between A1/A2** — both are consistent with
  existing patterns; A1 mirrors the Liveness/DatabaseHealth precedent more
  closely, A2 mirrors the "Dashboard is where cross-cutting health already
  lives" precedent more closely. Flagged as Section 22, item 1.

**B. Redis health.** `GET /api/health/redis/` (mirroring `DatabaseHealthView`
exactly — same no-auth pattern, same never-echo-raw-error discipline),
implemented via the already-available `redis` package
(`redis.Redis.from_url(settings.CELERY_BROKER_URL).ping()` or equivalent) —
no new dependency, no schema change, purely additive.

**Neither addition changes any existing endpoint's contract** — both are
net-new reads, satisfying principle #6 ("Jangan mengubah BFF contract tanpa
alasan kuat" — neither of these touches the BFF at all) and principle #8/#9
(no new architecture, minimal change).

---

## 12. Proposed Frontend Changes

**PROPOSED — not implemented.**

1. **A shared connectivity-state utility** (a small hook, e.g.
   `useConnectionState`, or inline logic factored out of the existing
   `setInterval` loops) implementing the Section 7/8 state machine, reusing
   `ApiError.kind` — no new error classification. Consumed by `InboxPage.tsx`'s
   two existing poll loops as one combined state (Section 7's recommended
   default), and optionally by `SessionsPage.tsx`'s `runTick()` for the same
   treatment (lower priority — Sessions already has a partial indicator on
   first load, unlike Inbox which has none at all once polling starts).
2. **A small status indicator**, reusing the existing `StatusBadge`
   component (no new visual language) shown in Inbox's header when the
   state is not LIVE, following whatever terminology is confirmed per
   Section 7's note.
3. **The `'unknown'`-outcome send message** (Section 10, item 2) — add an
   explicit message to `InboxPage.tsx`'s composer area for
   `result.data.status === 'unknown'`, reusing `SessionsPage.tsx`'s already-
   proven copy pattern. This is the smallest, most self-contained, most
   directly-motivated single change in this entire report — it requires no
   backend/BFF change, touches only display logic (not the send/idempotency
   mechanism itself, per principle #4), and directly closes the exact gap
   the task brief warned about. **Candidate for being done first/separately
   from the rest of Phase 9**, per Section 21.
4. **Dashboard: a Redis health card** and, if Option A1/A2 (Section 11) is
   chosen, **a Sync status card** — both trivially implemented by reusing
   the existing `HealthCard` component verbatim (confirmed reusable,
   `frontend/src/pages/DashboardPage.tsx`), following the exact pattern
   already used for WAHA/Backend/PostgreSQL.

**Not proposed**: any change to `useApiQuery` itself (it has no polling
concept and none is proposed to be added to it — the per-page interval
pattern already in use is left as-is, satisfying "prefer minimal change").

---

## 13. Proposed Backend Changes

**PROPOSED — not implemented.** Summarized from Section 11:

- New `apps.sync` (or extended `apps.dashboard`) read view(s) for
  `SyncCheckpoint` state — Option A1/A2 per Section 11, USER DECISION
  required on which shape.
- New `RedisHealthView` in `apps.core`, mirroring `DatabaseHealthView`.
- Optional: surface `WebhookEvent.received_at` (latest) alongside sync
  status (Section 10.4) — no new field, just one additional query.
- Optional, lower priority, explicitly not required for Phase 9's core
  scope: start populating `SyncCheckpoint.lag_seconds` at the end of a
  successful `reconcile_session()` run (e.g.
  `(timezone.now() - latest_timestamp).total_seconds()`) so the
  already-existing-but-dead field becomes meaningful, giving a true "lag"
  number distinct from "time since last attempt." This is additive
  (nullable field, no migration needed — the column already exists) and
  entirely optional; Section 4 already establishes that `last_run_at` alone
  is sufficient for the core Phase 9 use case.

**None of these change any existing model, migration, or business-logic
function** — `reconcile_session()`, `persist_message()`, webhook ingestion,
and the outbound-send idempotency machinery are all untouched by every
proposal in this report, per principles #4/#5.

---

## 14. Proposed BFF Changes

**None required, by default.** The BFF's `/health` endpoint already reports
WAHA reachability distinctly from BFF-process health, and its own code
comment (`bff/src/routes/health.ts:1-3`) states this was already built as
"the signal Phase 9's degraded-mode UI will consume" — this is confirmed to
already satisfy that role without modification.

**Rejected-by-default alternative** (PROPOSED only to be explicitly set
aside): the BFF could proxy/aggregate the new Django sync-status endpoint so
the frontend has one fewer origin to poll. **Not recommended as the
default**, per principle #6 (no BFF contract change without strong reason)
and principle #7 (no new dependency/indirection without need) — the
existing Inbox-reads-Django-directly precedent (established in the Phase 8
decision report) already establishes that the frontend calling Django
directly for non-WAHA data is the project's chosen pattern; sync status is
non-WAHA data, so it should follow the same direct-to-Django precedent, not
route through the BFF for no structural reason.

---

## 15. Production Considerations

- **`RECONCILIATION_EXECUTOR` in production is a config choice this report
  cannot confirm from source alone** (Section 5) — the office Docker Compose
  provisions Celery/Redis, strongly suggesting `celery` is intended, but
  nothing enforces it; if the office `.env` omits the var, production would
  silently run `sync` mode inside `gunicorn` workers instead. **Worth an
  explicit confirmation, not an assumption** — Section 22.
- Redis health check and any sync-status endpoint need no new
  infrastructure in production — Celery/Redis are already provisioned
  there (`infrastructure/office/docker-compose.yml`, confirmed unchanged).
- The webhook-silence gap (Section 9) is **more consequential in
  production** than in dev, since production is where real WhatsApp traffic
  flows continuously — a 15-minute default reconciliation interval is a
  reasonable production trade-off already in place, not something this
  report proposes changing (principle #9), but it is the concrete number
  behind "how stale can Inbox get" that any Phase 9 "Sync: STALE" threshold
  should be calibrated against, once built.

## 16. Development Considerations

- Dev currently runs **no real Celery/Redis at all** (confirmed by
  `README.md`'s own admission, re-confirmed by this session's environment
  check finding no `.env`/processes locally) — `RECONCILIATION_EXECUTOR`
  should correctly stay `'sync'` in dev (already the default), and a Redis
  health check in dev would legitimately, correctly show "unreachable"
  unless a developer explicitly runs a local Redis. **This is expected
  behavior, not a defect** — worth documenting alongside the health check
  itself (e.g. in its own code comment) so a future developer doesn't
  mistake it for an application bug, the same way `README.md` already does
  for the `runserver`-duplicate-process gotcha.
- Same source code, config-only difference (principle #10/#11): every
  proposal in this report is env-var/config-driven (which executor, which
  Redis URL) — no environment-conditional branching in application code is
  proposed anywhere, consistent with how `RECONCILIATION_EXECUTOR` itself
  already works.

---

## 17. Security Considerations

- **A genuine design-consistency question, not yet resolved by precedent**:
  the codebase has two existing auth postures for backend endpoints —
  "infra probe, unauthenticated" (`LivenessView`, `DatabaseHealthView`, and
  the BFF's `/health`) vs. "application data, `reading`-scope-gated" (the
  chats endpoints). A new sync-status/Redis-health endpoint sits closer to
  the "infra probe" category in *kind* (no message content, no PII) but
  **`SyncCheckpoint.last_error` could contain fragments of WAHA response
  text or exception messages** — returning that raw on an unauthenticated
  endpoint would be inconsistent with `apps/core/exceptions.py`'s existing,
  deliberate discipline of never echoing raw exception text externally
  (`docs/06-SECURITY.md`'s log-redaction requirement). **Recommendation**:
  if the endpoint is unauthenticated (matching the Liveness/DatabaseHealth
  precedent), **do not include raw `last_error` text** — return only
  `status`/`last_run_at`/derived freshness. If error detail is wanted for
  operators, gate that specific field (or the whole endpoint) behind
  authentication instead. **This is flagged as a decision point**, not
  resolved unilaterally here (Section 22).
- Redis health check must never echo the raw broker URL (which, in a real
  deployment, could contain credentials, even though the current default
  `redis://redis:6379/0` doesn't) — same redaction discipline as
  `DatabaseHealthView` already follows for PostgreSQL.
- No proposal in this report touches JWT, the internal-service-key
  mechanism, webhook HMAC, CORS, or WAHA credential handling in any way —
  all of Section 11–14's proposals are new, additive reads layered on
  existing, unchanged security boundaries.
- No new secret is introduced by anything proposed here.

---

## 18. Testing Strategy

- Any new backend endpoint (Section 11/13) should get unit tests mirroring
  the existing `DatabaseHealthView` test pattern: ok path, error/unreachable
  path, confirmation that no raw error text leaks if unauthenticated —
  consistent with the project's existing test discipline (every other
  backend view in this codebase has a corresponding test file).
- Frontend connectivity-state logic (Section 12, item 1) is pure state-
  transition logic and is unit-testable in principle — **but no frontend
  test runner exists anywhere in this project** (confirmed repeatedly
  across all three audits this session: no `vitest`/`jest` config, zero
  `*.test.tsx` files). Phase 9's frontend work would be in the exact same
  position as all prior frontend work: manual verification only, unless
  introducing a test runner is separately decided — that is a larger,
  distinct decision this report does not fold into Phase 9's scope.
- No BFF changes are proposed by default (Section 14), so no new BFF tests
  are needed under the default design.
- **Live/manual verification this report explicitly cannot perform**: this
  audit cannot observe real state transitions (LIVE→RECONNECTING→STALE,
  the Redis-down Celery behavior, the 15-minute webhook-silence window)
  without deliberately stopping real services — out of scope for a
  read-only audit. This would need to happen during an actual
  implementation-and-verification phase, not this design audit.

---

## 19. Risks / Trade-offs

- A new unauthenticated read endpoint (even a minimal one) is a small
  surface-area increase — mitigated by keeping the payload minimal (Section
  17) and following an existing, already-accepted precedent rather than a
  novel one.
- The state-machine threshold (N consecutive failures before STALE) is an
  arbitrary tuning choice with no objectively "correct" value derivable
  from the codebase — presented as a tunable default, not a hard
  requirement, and easy to change later without any architectural
  consequence.
- Polling-based recovery means state-transition latency is bounded by the
  existing poll interval (5–8s for Inbox) — this is an accepted, pre-
  existing constraint (no WebSocket/SSE is proposed, per principle #7 and
  the standing decision to defer real-time push), not a new limitation
  introduced by this design.
- **Scope-creep risk**: Phase 9 touches Dashboard, Inbox, Sessions,
  Backend, and (optionally) BFF — there is a real temptation to build more
  than the minimum. Section 20 exists specifically to guard against this.
- The `lag_seconds`-population proposal (Section 13, optional) is the one
  item in this report that touches `reconcile_session()`'s write path at
  all (adding one field assignment) — even though it's additive and
  low-risk, it is the closest this report comes to "touching a proven
  mechanism," and is explicitly marked optional/lowest-priority for that
  reason.

---

## 20. Explicit Non-Goals

Restated plainly, matching the task's own principles:

- No WebSocket/SSE or any other real-time push mechanism — already
  deliberately deferred by an earlier decision report; stays deferred.
- No change to `@lid`/JID identity resolution, and no auto-merge of
  contacts/chats — untouched by anything in this report.
- No change to the send-message mechanism or its idempotency contract —
  the only send-related proposal (Section 12, item 3) is a **display-only**
  addition, not a logic change; this distinction is intentional and
  important.
- No change to reconciliation's core algorithm, dedup logic, or checkpoint
  semantics — every backend proposal in this report is a **new read**,
  never a write-path change (except the one optional, explicitly-flagged
  `lag_seconds` addition, Section 13/19).
- No BFF contract change under the default design (Section 14).
- No new external dependency — `redis` is already a direct dependency.
- No rate limiting, no fine-grained per-user authorization change — both
  remain exactly as scoped to Phase 12, untouched here.
- No Docker/deployment-architecture change — every proposal is
  application-code-level; Section 15/16 only *document* existing production
  vs. dev differences, they do not propose changing them.
- **No fix, in this report, for any of the out-of-scope findings
  discovered along the way**: `SyncCheckpoint.lag_seconds` being currently
  dead code, `WahaSession.status`/`last_status_at` being currently unwritten
  anywhere, or the `RECONCILIATION_EXECUTOR` production-config ambiguity
  (Section 5/15) — all are recorded as findings for your awareness, not
  problems this report resolves.
- No implementation of anything in this report — per the task's explicit
  instruction, this stops at design and recommendation.

---

## 21. Implementation Plan

**Dependency-ordered, derived from what this audit actually found — not
the example structure applied automatically.**

- **9.0 — (Independent, smallest, arguably not "Phase 9" at all)**: the
  `'unknown'`-outcome send message in `InboxPage.tsx` (Section 12, item 3).
  Zero dependency on anything else in this plan — pure frontend display
  logic reusing an existing pattern. Could reasonably be done as its own
  tiny fix, separate from the rest of Phase 9, given how directly it
  addresses the task brief's named concern. Flagged here rather than
  numbered into the main sequence because it doesn't actually depend on any
  Phase 9 infrastructure to exist first.
- **9.1 — Backend: sync-status read surface** (Section 11, Option A1 or
  A2 — USER DECISION first, Section 22). No dependency on anything else.
- **9.2 — Backend: Redis health endpoint** (Section 11.B). Independent of
  9.1, can be built in parallel.
- **9.3 — Frontend: shared connectivity-state utility** (Section 12, item
  1). Depends on nothing backend-side — it classifies failures of
  *existing* endpoints, so it can be built and even partially verified
  before 9.1/9.2 exist.
- **9.4 — Frontend: apply the connectivity-state indicator to Inbox**
  (Section 12, item 2). Depends on 9.3.
- **9.5 — Frontend: Dashboard Sync card and Redis card** (Section 12, item
  4). Depends on 9.1 and 9.2 respectively — each card is independently
  buildable once its own backend piece exists.
- **9.6 — (Lower priority, optional) apply the same connectivity-state
  treatment to Sessions' `runTick()`** — depends on 9.3; lower priority
  because Sessions already has a partial indicator on first load, unlike
  Inbox which currently has none once polling starts.
- **9.7 — (Optional, explicitly gated on a decision) populate
  `SyncCheckpoint.lag_seconds`** (Section 13) — depends on nothing else,
  but should only be done if you actually want a true lag metric beyond
  what 9.1's `last_run_at`-based freshness already provides.
- **9.8 — Manual/live verification** of every state transition against the
  real dev/production environment (deliberately stopping Django, BFF, WAHA,
  Redis in turn) — depends on 9.1–9.6 being implemented; cannot happen as
  part of a read-only audit, and per this project's own established
  practice (every prior phase's manual-verification reports), should be
  documented when it happens.

---

## 22. USER DECISIONS REQUIRED

1. **Sync-status endpoint shape** (Section 11): dedicated `apps.sync`
   endpoint (Option A1) or a field added to the existing Dashboard aggregate
   (Option A2)? Both fit existing patterns; this report does not pick.
2. **Auth posture for the new sync/Redis health endpoints** (Section 17):
   follow the unauthenticated Liveness/DatabaseHealth precedent (and if so,
   confirm `last_error` should be excluded from the response), or gate
   behind authentication like the chats endpoints? This affects what detail
   can safely be returned.
3. **Confirm `RECONCILIATION_EXECUTOR` in the actual production/office
   environment** (Section 5/15) — is it explicitly set to `celery` in the
   real `infrastructure/office/.env`, or could it be silently defaulting to
   `sync`? This audit could not check (no `.env` file exists in this
   working tree, consistent with the environment limitation noted in the
   prior audit this session) and does not want to assume either way.
4. **State terminology** (Section 7): reuse `docs/03-UI-UX-SPEC.md`'s own
   words (Live/Stale/Unavailable + a transitional Reconnecting), or a
   different set (e.g. the task brief's 🟢🟡🔴 example)? Not a technical
   decision, but worth confirming before frontend copy is written.
5. **Combined vs. per-loop connectivity state for Inbox** (Section 7) — this
   report recommends one combined state for chat-list + messages polling;
   confirm that's acceptable, or if per-loop granularity is actually wanted
   despite the added UI complexity.
6. **Failure threshold before showing STALE** (Section 7/19) — this report
   proposes 2–3 consecutive failures as a starting default; confirm or
   adjust.
7. **Whether to do 9.0 (the `'unknown'`-send-outcome fix) as an immediate,
   separate small task**, decoupled from the rest of Phase 9, given it has
   no dependency on anything else and directly addresses a concern you
   named explicitly — or bundle it into Phase 9 proper when that begins.
8. **Whether to pursue 9.7** (populating `SyncCheckpoint.lag_seconds`) at
   all, given 9.1's `last_run_at`-based freshness is sufficient for the
   core Phase 9 use case without it — this is genuinely optional, not a
   silently-assumed "yes."
9. **Whether to also expose `WebhookEvent.received_at`** (latest) alongside
   sync status (Section 10.4) — a small, cheap addition this report
   suggests but does not assume you want.

---

This was a read-only design audit. Per your instruction: no implementation
follows, Phase 9 was not started, Phase 11 was not started, and no
out-of-scope finding (Section 4/5's dead-field findings, Section 5's
production-config ambiguity) was fixed — all are recorded for your review
only. Stopping here, awaiting your decisions on Section 22.
