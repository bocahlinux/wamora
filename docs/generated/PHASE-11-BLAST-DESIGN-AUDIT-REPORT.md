# Phase 11 — Blast (Controlled Bulk Send) — Design Audit Report

**This is a read-only design audit. No source, migration, Docker,
Compose, or configuration file was modified. No container was started,
stopped, or restarted. No write/mutating endpoint was called. The only
file created by this task is this report.**

**Conclusion up front:** Blast has **zero implementation** anywhere in
this codebase today — the only trace is a placeholder `'blast'` string
in Django's JWT scope vocabulary (never checked by any permission
class) and a bare `- Blast` bullet in the UI-UX spec's nav list. The
user has now finalized the hard limits and approval requirement
(docs/11-DECISIONS-AND-OPEN-QUESTIONS.md, item 12): max 100
recipients/campaign, max 500 recipients/day/session, 60s inter-message
delay, queued/throttled dispatch, admin ("system administration"
scope) approval before dispatch. This audit proposes a minimal data
model, an approval state machine, a dispatch design that **must not**
use `time.sleep`-style blocking (Celery's own
`CELERY_TASK_TIME_LIMIT=600` hard-kills a task after 10 minutes — a
100-recipient campaign at 60s/message needs ~100 minutes, so a single
long-running task is a correctness bug, not a style choice — Section
5), extends the existing `OutboundOperation` idempotency pattern rather
than inventing a parallel one, and reuses the already-declared `'blast'`
and `'system administration'` JWT scopes rather than proposing new
ones. A new cross-service call direction (Office/Celery → Tencent/BFF)
is required and does not exist today in either direction the codebase
currently uses — flagged in Section 8 as the single biggest open
architecture question.

---

## 1. Objective

Determine a minimal, sequenced implementation scope for Phase 11
(Blast) consistent with: the finalized limits/approval decision
(docs/11-DECISIONS-AND-OPEN-QUESTIONS.md item 12), the existing
outbound-message idempotency pattern (`OutboundOperation`), the
existing JWT scope vocabulary, the BFF-only-touches-WAHA hard rule, and
the project's own data-model change discipline ("All schema changes
require migrations" — docs/04-DATA-MODEL.md). This is a design audit
only — no code, schema, or config is produced here, only a proposal for
sign-off.

---

## 2. Current State

**VERIFIED FROM SOURCE.**

- `grep -rin "blast|broadcast|bulk" backend/ bff/ frontend/` returns
  exactly two hits, both in `backend/`:
  `backend/config/settings.py:293` — `'blast'` as one entry in the
  `JWT_SCOPES` list (docs/06-SECURITY.md's category names verbatim,
  "Separate permissions for session control, reading, sending, blast,
  user administration and system administration") — and
  `backend/apps/authn/tests/test_jwt_utils.py:17`, a test asserting the
  full six-scope list for a superuser. **No `bff/` or `frontend/`
  match of any kind.** This matches the prior audit's finding and adds
  no discrepancy.
- No `HasBlastScope` (or equivalent) permission class exists —
  `backend/apps/authn/permissions.py` defines only `HasReadingScope`
  and `HasSystemAdministrationScope`. The `'blast'` scope has never
  been checked by any endpoint.
- No `BlastCampaign`/`BlastRecipient` model, app, migration, view,
  serializer, URL, Celery task, BFF route, or frontend page/component
  exists anywhere in the repository.
- `docs/04-DATA-MODEL.md` names `BlastCampaign` and `BlastRecipient` in
  its entity list (lines 18-19) with **no field-level schema** — this
  audit proposes one (Section 3), flagged as requiring sign-off before
  any migration is written, per that same document's closing line
  ("All schema changes require migrations").
- `docs/03-UI-UX-SPEC.md` lists `Blast` as one of four top-level nav
  areas (Inbox, Session management, Monitoring, Blast) with no further
  detail — no wireframe, field list, or flow.
- `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` item 12 (as of 2026-09-26,
  read this task): **max 100 recipients/campaign; max 500
  recipients/day/session; 60s delay between messages; dispatch must be
  queued/throttled; admin ("system administration" scope) approval
  required before dispatch.** This is treated as a firm constraint for
  this audit, not re-litigated.
- The same file's "Open — new candidate requirements (2026-09-26, not
  yet phased)" section separately raises a blast-template +
  esamsat-integration variant. **Out of scope for this audit** per this
  task's own instructions — noted only as a dependency in Section 13,
  not designed for here. Generic Phase 11 Blast (this audit) and that
  esamsat-integrated variant are explicitly two different things until
  the user decides otherwise.

---

## 3. Recommended Data Model (Proposal — Requires Sign-Off)

**This is a proposal, not a final schema.** Per docs/04-DATA-MODEL.md,
any real version of this requires a migration and, per this audit's own
instructions, a new architectural addition of this size should not be
treated as unilaterally decided by an audit.

### 3.1 `BlastCampaign`

| Field | Type | Notes |
|---|---|---|
| `id` | PK | |
| `session` | FK → `WahaSession` | Which WAHA session sends this campaign — needed to enforce the 500/day/**session** limit (the limit is scoped per session, not global, per decision 12's exact wording). |
| `name` | CharField | Operator-facing label. |
| `message_template` | TextField | Plain text for this generic phase — no esamsat/template-variable engine (out of scope, Section 13). |
| `status` | CharField + choices | See Section 4 state machine. |
| `created_by` | FK → `User` | Campaign creator (needs `'blast'` scope, Section 7). |
| `approved_by` | FK → `User`, null | Set on approval (needs `'system administration'` scope). |
| `approved_at` | DateTimeField, null | |
| `rejected_reason` | TextField, blank | Free-text, set on rejection. |
| `recipient_count` | IntegerField | Denormalized count, enforced ≤ 100 at creation/edit time (decision 12). |
| `created_at`/`updated_at` | from `TimeStampedModel` | Matches every other model's existing base class (`apps.core.models.TimeStampedModel`, used by `OutboundOperation` and others). |

### 3.2 `BlastRecipient`

| Field | Type | Notes |
|---|---|---|
| `id` | PK | |
| `campaign` | FK → `BlastCampaign`, `related_name='recipients'` | |
| `destination` | CharField | Chat/phone identifier — same shape as `OutboundOperation.destination`. |
| `status` | CharField + choices | `pending`, `sending`, `sent`, `failed`, `skipped` — mirrors `OutboundOperation`'s status vocabulary (`pending`/`sent`/`failed`/`unknown`) but adds `sending` (a recipient is claimed by the dispatch task, preventing a double-pick under Celery's at-least-once delivery) and `skipped` (campaign was rejected/cancelled before this recipient's turn). |
| `scheduled_for` | DateTimeField, null | The computed dispatch time (`campaign.approved_at + index * 60s`), Section 5. |
| `sent_at` | DateTimeField, null | |
| `outbound_operation` | FK → `OutboundOperation`, null, `on_delete=PROTECT` | **The idempotency link** — see Section 6. Each recipient send reuses the existing `OutboundOperation` row/state-machine rather than duplicating status tracking. |
| `idempotency_key` | CharField | Deterministic, derived (Section 6), not random — required so a re-dispatched/retried campaign task can't double-send. |

### 3.3 Why extend rather than replace `OutboundOperation`

`OutboundOperation` (docs/04-DATA-MODEL.md, `backend/apps/operations/models.py`)
already models exactly what a single blast recipient-send needs:
idempotency key (unique per `(session, idempotency_key)`), destination,
operation type, status (`pending|sent|failed|unknown`), provider
message ID, audit relation. Recommendation: **reuse it as-is**,
`operation_type='blastSend'`, linked from `BlastRecipient` via FK — not
a parallel status/idempotency mechanism. This directly satisfies hard
rule 7 ("Outbound WhatsApp side effects must use idempotency keys") by
construction rather than by a second implementation that could drift
from the first.

---

## 4. Approval Workflow

**Creator vs approver**: campaign creation requires the `'blast'` scope
(existing, unchecked scope — Section 7); approval requires
`'system administration'` (decision 12, explicit). These should be
different people in the common case but this audit does **not**
recommend technically forbidding the same user holding both scopes from
approving their own campaign — no such self-approval restriction is
stated in the decision, and inventing one would be scope creep; flagged
in Section 13 as a cheap follow-up confirmation, not blocking.

**Proposed state machine**:

```
draft -> pending_approval -> approved -> sending -> completed
                |                           |
                v                           v
            rejected                     failed
                                            |
                                     (partial: some sent, see below)
```

- `draft`: creator is still editing recipients/message; not yet
  submitted.
- `pending_approval`: creator submitted; visible to `'system
  administration'`-scoped users for approval.
- `approved`: admin approved; dispatch has not yet started (a queued
  task, Section 5, picks it up).
- `sending`: at least one recipient has moved past `pending`; the
  campaign is actively being throttled through.
- `completed`: every recipient reached a terminal status
  (`sent`/`failed`/`skipped`).
- `rejected`: admin declined; **terminal** — this audit recommends
  rejection be terminal (no resubmission of the same campaign row) so
  the audit trail of "this exact campaign was rejected" stays intact;
  the creator makes a new campaign (effectively a copy) if they want to
  try again. Flagged as a default, not a mandate (Section 13).
- `failed`: reserved for a campaign-level failure (e.g. the session
  disappeared mid-dispatch) distinct from individual recipient
  failures, which are tracked per-`BlastRecipient` and do not by
  themselves fail the campaign — a campaign with some `sent` and some
  `failed` recipients should still reach `completed`, not `failed`.
  "Partial failure is not campaign failure" is this audit's
  recommended default (Section 11).

**Is approval per-campaign?** Yes — decision 12 says "admin approval
required before dispatch," and a campaign is the natural unit matching
the 100-recipient/campaign limit already decided. No per-recipient
approval is implied or recommended.

---

## 5. Dispatch/Throttling Design

**Critical constraint found this audit**: `CELERY_TASK_TIME_LIMIT = 600`
(10 minutes, hard kill) and `CELERY_TASK_SOFT_TIME_LIMIT = 540`
(`backend/config/settings.py:192-193`). A 100-recipient campaign at a
mandatory 60s delay between messages needs **up to ~100 minutes** to
finish. A single Celery task that loops over recipients and
`time.sleep(60)`s between sends would be **hard-killed at 10 minutes**,
mid-campaign, with no automatic resumption — this is not a style
preference, it is a correctness bug against decision 12's own "60s
delay between messages" requirement. Any implementation **must not**
use a sleep-in-a-loop design.

**Recommended pattern** (consistent with this codebase's existing
Celery idioms — `reconcile_all_sessions_task`'s fan-out-one-task-per-unit
pattern, `backend/apps/sync/tasks.py:108-117`):

- On approval, schedule **one Celery task per recipient**, each with an
  explicit `countdown` (or `eta`) equal to `index * 60` seconds from
  campaign approval — using `apply_async(countdown=...)`, never
  `sleep`. Each task is short-lived (one WAHA send), so it can never
  approach the 600s hard limit regardless of campaign size.
- Each per-recipient task: (1) re-checks the campaign is still
  `approved`/`sending` (not rejected/cancelled after scheduling — a
  scheduled-but-not-yet-fired task must be a no-op if the campaign was
  cancelled in the interim), (2) claims the recipient
  (`pending → sending`, guarding against Celery's at-least-once
  redelivery double-firing the same task), (3) dispatches through BFF
  (Section 8), (4) resolves the linked `OutboundOperation` and
  `BlastRecipient.status` exactly like the existing single-send flow
  does (`bff/src/routes/messages.ts` Steps 1/3, mirrored server-side).
- **500/day/session counter**: recommend counting **`sent` +
  `sending`-committed `OutboundOperation` rows of `operation_type in
  ('sendText','blastSend')`** (i.e. all outbound sends on that session,
  not just blast — decision 12 doesn't say whether the daily cap is
  blast-only or all outbound traffic on the session; this audit
  recommends **all outbound sends on the session**, since the safety
  rationale — WhatsApp ban risk from sustained volume — doesn't care
  whether a send was a 1:1 reply or a blast recipient. **Flagged for
  confirmation, not decided here** — Section 13) evaluated against a
  rolling or calendar-day window. Recommend **calendar day in the
  server's configured timezone** (matches `CELERY_TIMEZONE =
  TIME_ZONE`, already UTC-per-settings) for unambiguous reset semantics
  — a rolling 24h window is harder to reason about operationally and
  isn't asked for. **This reset-semantics choice is explicitly flagged
  as needing confirmation** (the task prompt itself calls this out as a
  risk in Section 11).
- A campaign whose scheduled dispatch would push a session over its
  500/day/session budget should be **rejected at approval time** (a
  clear, actionable error) rather than partially dispatched and then
  silently stalled mid-campaign — recommended default, flagged for
  confirmation.
- No new Celery queue is required for a first slice — reuse the
  existing single worker/queue (`celery-worker`, Office Docker,
  docs/08-DEPLOYMENT.md). If blast volume later contends with
  reconciliation tasks for worker capacity, a dedicated queue is an
  optional future optimization, not required for correctness.

---

## 6. Idempotency

Each `BlastRecipient` gets a **deterministic** idempotency key (e.g.
`blast:{campaign_id}:{recipient_id}`), not a random one — this is what
makes a retried/duplicate dispatch safe: if the per-recipient Celery
task is redelivered (Celery's at-least-once semantics under worker
restart/redelivery) or a campaign's dispatch is somehow re-triggered,
`OutboundOperation`'s existing `unique(session, idempotency_key)`
constraint (`backend/apps/operations/models.py:45-48`) and its existing
register/resolve state machine
(`backend/apps/operations/views.py` — `get_or_create`, never a second
row for the same key) already prevent a double-send **without any new
idempotency logic** — this is the direct payoff of Section 3.3's reuse
decision. The per-recipient Celery task itself should also be written
idempotently at the task level (check `BlastRecipient.status` before
acting, per Section 5) as defense-in-depth, matching this codebase's
existing "safe to re-run" philosophy (`reconcile_session_task`'s own
docstring: "a task retry is safe purely because re-running ... is
already safe to re-run").

---

## 7. Authorization

- **Campaign creation** (draft/submit): the existing, already-declared
  `'blast'` JWT scope (`backend/config/settings.py:293`,
  docs/06-SECURITY.md) is the natural fit and has never been checked by
  any endpoint — enforcing it for the first time here is the same kind
  of "first use of an existing declared scope" step Phase 13.A already
  took for `'system administration'`
  (`backend/apps/authn/permissions.py:22-28`'s own comment: "the first
  administrative/state-changing... endpoint, so this is the first use
  of this scope name"). A new `HasBlastScope` permission class,
  identical in shape to `HasReadingScope`/`HasSystemAdministrationScope`,
  is all that's needed — **no new scope name is proposed**, consistent
  with the hard-rule spirit of not inventing scopes without reason.
- **Campaign approval**: `'system administration'` (decision 12,
  explicit — "admin ... approval"), reusing
  `HasSystemAdministrationScope` verbatim, no new class needed beyond
  applying it to the new approval endpoint.
- This audit does **not** find a case for a third, blast-specific
  approval scope distinct from `'system administration'` — decision 12
  names that scope explicitly, and introducing a narrower one (e.g.
  `'blast approval'`) would be adding scope surface the user did not
  ask for. If the user later wants approval separated from other
  system-administration powers, that would be a deliberate follow-up
  decision, not something this audit unilaterally proposes.

---

## 8. BFF Involvement — Open Architecture Question

**This is the single largest open design question in this audit.**

Actual WAHA sends must go through the BFF (hard rules 4/5). Today,
`bff/src/routes/messages.ts`'s `POST /sessions/:session/messages` is
**end-user-JWT-gated** (`requireAuth` verifies a Bearer JWT issued by
Django for a logged-in human, then `requireScope('sending')`) — it has
no notion of a service-to-service caller. Blast dispatch, however, is
**Celery-driven from the Office side**, which has no human JWT to
present in the moment a scheduled task fires.

Two options, neither of which is a "generic proxy" (hard rule 5 is
satisfied by both — each is a narrow, explicit, allowlisted send
operation):

1. **New BFF-internal endpoint**, mirroring the existing internal
   pattern but in the **reverse** direction: today `INTERNAL_SERVICE_KEY`
   authenticates BFF → Django calls
   (`backend/config/settings.py:298-305`); this option adds a distinct
   shared secret authenticating Office/Celery → Tencent/BFF calls to a
   new, narrow endpoint (e.g. `POST /internal/blast/send`), doing
   exactly one thing (call WAHA `sendText`, allowlisted, same as the
   existing route's `callWaha('sendText', ...)`), never taking an
   arbitrary path/target. This is architecturally consistent with the
   existing NetBird/LAN link between Tencent and Office already used
   for BFF → Django traffic (docs/01-ARCHITECTURE.md's diagram shows
   the same link connecting both directions) but is a **new call
   direction that has never been built or exercised in this codebase**.
2. **Service JWT minted by Django for its own worker**: since Django is
   already the sole JWT issuer (`JWT_PRIVATE_KEY`,
   `backend/config/settings.py:272`), it could mint a short-lived,
   system-actor JWT with `['sending','blast']` scopes for the Celery
   task to present to the *existing* `/sessions/:session/messages`
   route unmodified. This reuses the existing route/verification path
   with zero BFF changes, at the cost of a "fake user" identity concept
   that doesn't exist anywhere in this system today (every current JWT
   represents a logged-in human; audit/actor fields elsewhere assume
   that).

This audit's mild preference is **option 1** (new narrow internal BFF
endpoint) — it keeps the existing user-facing send route's semantics
(real human actor, real audit trail) unchanged and matches the
project's existing pattern of a dedicated static secret for
service-to-service calls rather than stretching the human-JWT concept
to cover a system actor. **This is flagged for explicit user
confirmation before implementation (Section 13/14)**, not decided
unilaterally — it is a genuine new architecture surface, exactly the
class of decision this audit's own instructions say not to guess on.

---

## 9. Frontend (High-Level Only)

Per docs/03-UI-UX-SPEC.md, `Blast` is one of the four top-level nav
areas (alongside Inbox, Session management, Monitoring) — no existing
component or page exists for it (confirmed, Section 2). A first-slice
surface needs, at minimum:

- A campaign list (status-badge per campaign, reusing the existing
  `StatusBadge`/`Card`/`PageHeader` UI kit already used across
  Sessions/Dashboard/Inbox).
- A create/draft form (name, session picker, message text, recipient
  list — client-side enforcement of the 100-recipient cap as a UX
  courtesy only; the real enforcement is server-side, matching this
  codebase's existing "hiding a button/rejecting client-side is a
  courtesy, not the security boundary" discipline, per the 13.B audit's
  own Section 6.2 framing).
- An approval view, visible only to `'system administration'`-scoped
  viewers (reusing the existing `claims?.scopes.includes(...)` inline
  pattern from `InboxPage.tsx:216`, not a new scope-hiding framework),
  behind a `ConfirmDialog` (matching the existing destructive-action
  confirmation convention).
- A campaign detail/progress view (recipient statuses, sent/failed
  counts) — likely fetch-on-mount or manual-refresh only, **not**
  polling by default, consistent with this codebase's general
  reluctance to add new polling loops without a stated live-monitoring
  need (13.B audit Section 5.6's reasoning applies equally here: a
  60s-per-message campaign has no benefit from sub-minute polling).

Component-level detail is deliberately not designed here — out of this
audit's mandate (high-level only, per the task's own instruction).

---

## 10. Files That Would Need to Change/Be Created

### Backend — REQUIRED
- `backend/apps/blast/` (new app): `models.py` (`BlastCampaign`,
  `BlastRecipient`, Section 3), `migrations/000X_...py`, `serializers.py`,
  `views.py` (create/list/detail/approve/reject endpoints), `urls.py`,
  `tasks.py` (per-recipient dispatch task, Section 5).
- `backend/apps/authn/permissions.py` — add `HasBlastScope` (Section 7).
- `backend/config/settings.py` — register the new app; add any new
  limit constants (`BLAST_MAX_RECIPIENTS_PER_CAMPAIGN=100`,
  `BLAST_MAX_RECIPIENTS_PER_SESSION_PER_DAY=500`,
  `BLAST_INTER_MESSAGE_DELAY_SECONDS=60`) as environment-overridable
  defaults, matching the existing `OUTBOUND_OPERATION_STALE_SECONDS`
  idiom (settings.py:309).
- `backend/apps/core/urls.py` (or project root urls) — mount the new
  app's URLs.

### Backend — OPTIONAL (first slice can defer)
- A dedicated `backend/apps/blast/services.py` splitting business logic
  from views/tasks (matching `apps.sync.reconciliation`'s existing
  thin-task/service-layer separation) — good practice, not blocking.
- Admin-side Django admin registration for `BlastCampaign` (operational
  convenience only).

### BFF — REQUIRED (if Section 8 Option 1 is chosen)
- `bff/src/routes/blast.ts` (or extend `messages.ts`) — new internal,
  allowlisted, single-purpose send endpoint.
- `bff/src/config.ts` — new shared-secret env var (name TBD on Section
  8 sign-off) and its Office→Tencent counterpart.
- `bff/src/middleware/` — a new internal-auth check for this direction
  (mirrors `apps.core.internal_auth.HasInternalServiceKey`'s pattern
  but on the BFF/Express side).

### BFF — OPTIONAL (if Section 8 Option 2 is chosen instead)
- No new route; only `backend/apps/authn` gains a
  "mint a system-actor JWT for Celery" helper — smaller BFF footprint,
  larger new-concept footprint on the Django side (Section 8).

### Frontend — REQUIRED
- `frontend/src/pages/BlastPage.tsx` + `.css` (new page, nav entry).
- `frontend/src/lib/djangoApi.ts` — campaign CRUD/approve/reject
  functions + types.
- `frontend/src/components/` — campaign list/detail/create-form pieces,
  reusing existing `Card`/`StatusBadge`/`ConfirmDialog`/`EmptyState`/
  `ErrorState`/`LoadingState` primitives (no new base components
  expected to be required).

### Frontend — OPTIONAL
- A dedicated recipient-CSV/paste-list import UX (v1 can be a plain
  textarea, one destination per line).

---

## 11. Risks

- **Spam/ban risk**: this is the entire reason decision 12's limits
  exist; the dispatch design (Section 5) must not silently exceed
  60s/message even under retry — a naive retry-on-failure could
  otherwise burst multiple sends close together. Recommend: a failed
  recipient send is marked `failed` and **not automatically retried**
  in the first slice (manual re-send/new campaign only) — auto-retry
  interacting with the fixed 60s cadence is exactly the kind of
  subtlety this audit does not want to silently decide (flagged,
  Section 13).
- **Abuse risk**: a `'blast'`-scoped user could create many
  100-recipient campaigns to route around the per-campaign cap; the
  500/day/session cap (Section 5) is what actually bounds total daily
  volume — this makes the daily-cap enforcement point (Section 5) not
  merely a nice-to-have but the real backstop, and it must be checked
  at **approval** time (when the campaign actually commits to
  consuming the budget), not just at creation.
- **Partial-failure/resume risk**: if the Celery worker or Redis is
  down for part of a campaign's scheduled window, some per-recipient
  tasks may never fire (Celery does not guarantee execution across a
  broker outage without redelivery configuration this audit did not
  verify exists). A `completed` campaign with recipients stuck in
  `pending`/`scheduled_for` in the past needs a defined recovery story
  (a manual "resume"/re-schedule action, admin-gated) — **not designed
  in this first-slice minimal scope**, flagged as a known gap (Section
  14), not silently ignored.
- **WAHA rate-limit interaction**: this audit found no documented WAHA
  rate limit in this repo (docs/06-SECURITY.md only says "Rate limits:
  Login, send, session control, blast and expensive sync" as a
  category, no numeric values) — the 60s/message delay is this
  project's own self-imposed pacing, not confirmed to match any actual
  WAHA/WhatsApp-imposed limit; if WAHA itself throttles independently,
  a blast send could still fail for reasons outside this design's
  control, and `BlastRecipient.status='failed'` must not be presented
  to the operator as necessarily "this codebase's fault."
- **500/day/session reset-semantics ambiguity**: explicitly named in
  the task prompt as a risk needing to be unambiguous — Section 5's
  calendar-day/session-scoped/all-outbound-traffic proposal is a
  **default recommendation, not yet confirmed** (Section 13).

---

## 12. Verification Plan (For a Future Implementation Phase)

1. **Backend unit tests**: campaign creation enforces ≤100 recipients;
   approval enforces `'system administration'` scope and the
   day/session budget; per-recipient task claims a recipient exactly
   once even if invoked twice (idempotency, Section 6); a rejected
   campaign never dispatches.
2. **Idempotency test**: simulate the same `BlastRecipient` task firing
   twice (e.g. Celery redelivery) — assert exactly one `sent`
   `OutboundOperation` and no duplicate WAHA call (mirroring
   docs/09-TEST-PLAN.md's existing outbound-idempotency test style).
3. **Timing test**: assert scheduled `countdown`/`eta` values are
   exactly `index * 60s` apart and that no task can fire before its
   scheduled time even under worker restart.
4. **BFF integration test** (once Section 8 is resolved): the new
   internal endpoint rejects any request without the correct
   service-auth, and only performs the one allowlisted `sendText`
   operation — no arbitrary-path capability, per hard rule 5.
5. **Frontend**: approval control only renders for
   `'system administration'`-scoped viewers (client-side courtesy);
   direct API call from a non-admin session still receives `403`
   server-side (defense-in-depth check, same discipline as the 13.B
   audit's own Section 13.3).
6. **Manual end-to-end** (dev stack): create → approve → observe
   throttled dispatch timing → verify daily counter increments and
   blocks a second campaign that would exceed it.

---

## 13. Dependencies and Flagged-for-Confirmation Sub-Decisions

This audit finds **no blocking external dependency** — decision 12
already resolved the one previously-blocking open item. The following
are genuinely open sub-decisions this audit recommends defaults for,
**flagged for a quick follow-up confirmation, not blocking this
report**:

1. **BFF call direction/mechanism** (Section 8) — new internal BFF
   endpoint + new shared secret (this audit's preference) vs. a Django-
   minted service JWT reusing the existing send route. Biggest open
   item.
2. **Exact state-machine names** (Section 4) — `draft` /
   `pending_approval` / `approved` / `sending` / `completed` /
   `rejected` / `failed` are this audit's proposal, not confirmed
   final names.
3. **500/day/session counter scope** (Section 5) — all outbound sends
   on the session vs. blast-only sends; calendar-day-UTC reset vs.
   rolling 24h.
4. **Self-approval**: should a user holding both `'blast'` and `'system
   administration'` scopes be allowed to approve their own campaign?
   (Section 4) — this audit does not recommend forbidding it, but flags
   it as undecided.
5. **Auto-retry policy for a failed individual recipient send**
   (Section 11) — this audit recommends none in the first slice
   (manual re-send only).
6. **Resume story for a partially-dispatched campaign after a worker
   outage** (Section 11) — not designed in this first slice; a known
   gap, not silently dropped.
7. **Out of scope, explicitly not folded in here**: the esamsat-
   integrated blast-template variant
   (docs/11-DECISIONS-AND-OPEN-QUESTIONS.md, "Open — new candidate
   requirements") — a separate, unscoped, undecided candidate feature;
   this audit's `message_template` field (Section 3.1) is plain text
   only and assumes no dependency on that candidate feature's outcome.

None of items 1-6 block writing this audit or block a future
implementation from starting on the parts that don't depend on the
answer (e.g. the data model and state machine can be built while
Section 8's mechanism is still being decided, since it only affects
the dispatch task's final "call BFF" step).

---

## 14. Final Recommendation

**Minimal first-slice scope**: campaign CRUD (draft/submit) + manual
admin approval/rejection + throttled per-recipient dispatch via
scheduled Celery tasks (Section 5) + reuse of the existing
`OutboundOperation` idempotency pattern (Section 3.3/6) + enforcement
of all four numeric limits from decision 12 at the appropriate stage
(100/campaign at creation, 500/day/session at approval, 60s spacing at
schedule-time, queued dispatch by construction). Defer: auto-retry of
failed sends, a resume/recovery flow for interrupted campaigns,
recipient CSV import tooling, and any esamsat/template-variable
functionality (explicitly out of this audit's scope, Section 2/13).

**Before implementation starts**, this audit recommends the user
confirm Section 13 item 1 (BFF call mechanism) specifically, since it
is the one item that changes which files get created in `bff/` and
introduces a genuinely new cross-service architecture surface — every
other flagged item (2-6) has a safe, reversible default this audit
already proposes and implementation can proceed with those defaults
if the user has no objection.

**STOP.** This was a design audit only. No source, migration, Docker,
or configuration file was modified. No container was started or
restarted. No write/mutating endpoint was called. The only artifact
produced by this task is this report. Awaiting the user's decision on
Section 13 item 1 (and any objection to items 2-6's proposed defaults)
before any implementation task proceeds.
