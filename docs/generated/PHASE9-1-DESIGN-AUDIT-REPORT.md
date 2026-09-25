# Phase 9.1 — Sync Status / Degraded-Mode Design Audit (Read-Only)

**Scope.** Design/read-only audit only. No source, `.env`, config, migration,
WAHA session, or database was modified. No write-capable/internal endpoint
was called. No WhatsApp message was sent. Phase 9.0 (ambiguous send-outcome
UX, `InboxPage.tsx`/`InboxPage.css`) is treated as done and is **not**
revisited, changed, or re-litigated anywhere below — confirmed via
`git status`/`git diff --stat` at the start of this task: the working tree
contains exactly the Phase 9.0 diff (two files) plus the untracked reports
from prior audit tasks; nothing else has changed in the repository since
Phase 9.0 finished.

Every source-code claim below was read directly this task (file paths and,
where meaningful, line numbers are cited) — nothing is taken on the word of
`docs/generated/PHASE9-DESIGN-AUDIT-REPORT.md` or any earlier report without
being re-confirmed against the current tree. Where this task's own findings
sharpen or add detail beyond that earlier report, it's called out explicitly
as new.

---

## 1. Current State

- **Backend**: 9 Django apps, unchanged (`core, authn, waha_sessions, chats,
  webhooks, sync, operations, audit, dashboard`). `apps.sync` still has
  exactly one URL (`reconciliation/trigger/`, write-only, internal-key
  gated) — zero read surface for `SyncCheckpoint` exists anywhere.
- **Reconciliation**: `reconcile_session()` (`backend/apps/sync/reconciliation.py`)
  is unchanged, still the single entry point reached by all four trigger
  paths (HTTP internal-trigger, Celery periodic, Celery targeted, management
  command). `RECONCILIATION_EXECUTOR` (`backend/config/settings.py:222-229`)
  still defaults to `'sync'` and still fails fast (`ImproperlyConfigured`)
  on any value other than `'sync'`/`'celery'`.
- **Frontend Inbox**: `InboxPage.tsx` now has correct three-way send-outcome
  feedback (Phase 9.0) on the **write** path. The **read** path (chat-list
  poll every 8000ms, messages poll every 5000ms,
  `InboxPage.tsx:67-76`/`104-111`) is **unchanged and still silent on
  failure** — confirmed again this task by reading the current file: neither
  loop inspects the failure at all (`if (result.ok) setChats(...)`, no
  `else`), so this specific gap (Phase 9's core remaining target) still
  exists exactly as before Phase 9.0, which never touched it.
- **No health/sync-status infrastructure has been added anywhere** since the
  last design audit — no `SyncCheckpoint` endpoint, no Redis health check,
  no webhook heartbeat. This task confirms that state, it does not assume
  it from memory.

---

## 2. Evidence from Source Code

### `SyncCheckpoint` — read/write sites (CONFIRMED, grepped and read fresh this task)

- **Model** (`backend/apps/sync/models.py:7-33`, unchanged): `session`
  (`OneToOneField` → `WahaSession`), `checkpoint_value` (`CharField`,
  ISO-8601 string), `last_run_at` (`DateTimeField`, nullable), `status`
  (`idle`/`running`/`ok`/`error`, default `idle`), `lag_seconds`
  (`PositiveIntegerField`, nullable), `last_error` (`TextField`).
- **The only writer, anywhere in the codebase**: `reconcile_session()`
  (`backend/apps/sync/reconciliation.py:155-247`). Exact write sequence,
  re-read this task:
  1. `SyncCheckpoint.objects.get_or_create(session=session)`
     (`reconciliation.py:172`) — **a checkpoint row does not exist for a
     session until reconciliation has run for it at least once.** This is a
     distinct, real state ("never synced") that any read endpoint must
     represent explicitly, not just as `null` fields on a row that doesn't
     exist.
  2. `checkpoint.status = STATUS_RUNNING; checkpoint.save(update_fields=['status','updated_at'])`
     (`reconciliation.py:183-184`) — set **eagerly, before any WAHA call**.
  3. At the end: `status → OK` (with `checkpoint_value` advanced) only if
     the run had zero errors, else `status → ERROR` with `last_error`
     populated and `checkpoint_value` **not** advanced
     (`reconciliation.py:233-246`). `last_run_at` and `updated_at` are
     always written in this final save, success or failure.
  4. `lag_seconds` is written **nowhere** — re-grepped this task,
     repository-wide: the only two matches for `lag_seconds` are the model
     field itself and its migration. **This task does not propose
     populating it** — see Section 5's explicit reasoning, directly
     answering the instruction not to "activate" it just because the field
     exists.
- **The only reader, anywhere in the codebase**: nothing. Re-grepped this
  task for `SyncCheckpoint` outside `apps/sync` itself and its own tests —
  zero results in any view, serializer, or frontend file.
- **A CONFIRMED gap not previously written up this precisely**: because
  `status → RUNNING` is saved *before* any WAHA call, and the only paths
  that ever move it back to `OK`/`ERROR` are the two `try`/`except`-guarded
  branches at the end of `reconcile_session()`, **an uncaught exception
  during a run (anything not a `WahaClientError` from the WAHA-fetch step,
  or a `MessageParsingError`/`DuplicateMessage` from the persist step —
  e.g. a genuine bug, an unexpected exception type, a process kill) would
  leave `status` stuck at `RUNNING` indefinitely**, with no code anywhere
  that times it out or resets it. `updated_at` (from `TimeStampedModel`) is
  the only signal that would let a reader infer "this has claimed to be
  running for an implausibly long time" — there is no explicit
  stuck-run-detection mechanism in the codebase today. Relevant to Section
  6's schema design.

### Reconciliation executor / trigger points (CONFIRMED, re-read this task)

- `trigger_reconciliation()` (`backend/apps/sync/executors.py:65-85`)
  dispatches on `settings.RECONCILIATION_EXECUTOR` — `'sync'` runs
  `run_targeted_reconciliation_with_retry()` in-process (3 attempts, 1.5s
  delay, `executors.py:39-62`); `'celery'` enqueues
  `reconcile_chat_task.delay()`. Unchanged from the prior audit, re-confirmed
  by direct read this task.
- Periodic dispatch: `config/celery.py`'s `_setup_periodic_tasks` registers
  `reconcile_all_sessions_task` via `sender.add_periodic_task(settings.RECONCILIATION_INTERVAL_SECONDS, ...)`
  — a programmatic registration, not a `CELERY_BEAT_SCHEDULE` dict (confirmed
  unchanged from the prior audit's finding; not re-read line-by-line this
  task since `git status` shows zero backend drift, only re-verified that no
  backend file appears in the diff at all).
- **All four trigger paths converge on the exact same `reconcile_session()`
  and therefore the exact same `SyncCheckpoint` row** — this is the
  property that makes a single sync-status read surface meaningful
  regardless of which trigger caused the most recent update.

### Webhook ingestion — read/write sites (CONFIRMED, read fresh this task —
this is new detail beyond the prior design audit, directly relevant to
Section 5's webhook-health question)

- `WebhookEvent` model (`backend/apps/webhooks/models.py`, read in full this
  task): `status` (`pending`/`processed`/`failed`/`unsupported`), `attempts`
  (`PositiveIntegerField`, default 0), `error_message`, `received_at`
  (`auto_now_add`), `processed_at` (nullable), `updated_at`.
- `ingest_webhook()` (`backend/apps/webhooks/services.py:28-79`, read in
  full this task): **`attempts` is genuinely live-written**, not a dead
  field like `SyncCheckpoint.lag_seconds` — `webhook_event.attempts += 1`
  fires on every delivery for an already-existing event
  (`services.py:48-50`), which happens on WAHA's own retry of a delivery
  whose processing previously failed or is still pending. A webhook event
  sitting at `status='failed'` with a non-trivial `error_message` and
  `attempts` incrementing is a genuine, already-recorded signal of
  **"webhook arrived, ingestion failed"** — distinct from either "nothing
  arrived" or "arrived and worked." This existing data was not previously
  identified as a candidate signal in the prior design audit; it is a
  confirmed, reusable piece of evidence for Section 5/6 below.
- **What still cannot be derived from any existing data**: whether the
  *absence* of new `WebhookEvent` rows for a stretch of time means "WhatsApp
  is quiet" or "webhooks stopped arriving" — nothing in the system observes
  WhatsApp/WAHA activity independently of the webhook channel itself, so a
  webhook silence and a real silence are structurally indistinguishable from
  inside Django. This is the same conclusion the prior design audit reached,
  re-confirmed rather than assumed.

### Frontend polling / error-handling primitives (CONFIRMED, re-read this task, full file)

- `ApiError.kind` taxonomy (`frontend/src/lib/api.ts`, not re-read
  line-by-line this task since `git status` shows it unchanged, but its
  shape was exercised directly in Phase 9.0's own edit and is confirmed
  current): `network_error`, `timeout`, `server_error`, `unauthorized`,
  `forbidden`, `not_found`, `validation`, `unknown`.
- `InboxPage.tsx`'s two poll loops (`67-76`, `104-111`, quoted in Section 1)
  still discard this classification entirely on every failed tick — this is
  the exact, still-open gap Section 7 designs against.
- `SessionsPage.tsx`'s `ActionFeedback`/settle-poller pattern (used as the
  precedent for Phase 9.0) is unchanged and untouched by this task, per the
  instruction not to touch Session Management unless strictly required —
  it is not required here, since Section 7's proposal only *reuses the
  pattern's shape*, the same way Phase 9.0 did, without editing the file.

---

## 3. Existing Reusable Infrastructure

Restated because it still governs every proposal below — nothing here has
changed since the prior design audit, re-confirmed:

- `HealthCard` (`frontend/src/pages/DashboardPage.tsx`) — a working,
  reusable loading/error/detail card component, already used for
  WAHA/Backend/PostgreSQL.
- `LivenessView`/`DatabaseHealthView` (`backend/apps/core/views.py`) — the
  established "one dependency, one unauthenticated view, never echo raw
  error text" pattern.
- `bff/src/routes/health.ts` — already reports WAHA reachability distinctly
  from BFF-process health, by its own design intent
  (`bff/src/routes/health.ts:1-3`'s comment). No BFF change is proposed
  anywhere in this report.
- `StatusBadge` — arbitrary label/tint, no fixed vocabulary imposed.
- The `ApiError.kind` taxonomy (Section 2) — the one and only error
  classification mechanism the frontend needs for the "server unavailable"
  axis (Section 7).
- `redis==5.0.8` — already a **direct** dependency in
  `backend/requirements.txt` (re-confirmed present this task via the same
  grep as the prior audit) — a Redis health check needs no new package.

---

## 4. Confirmed Gaps

1. No HTTP read surface for `SyncCheckpoint` anywhere (Section 2).
2. No Redis health check anywhere.
3. `InboxPage.tsx`'s read-polling (chat list, messages) still cannot
   distinguish "server unreachable" from "nothing new happened" — unchanged
   by Phase 9.0, which only fixed the write/send path.
4. No stuck-`RUNNING`-checkpoint detection or recovery exists (Section 2 —
   new finding this task).
5. No durable record of *how much* a reconciliation run recovered (e.g.
   `messages_inserted` is computed in-memory by `ReconciliationResult` but
   never persisted anywhere) — meaning even a successful, "healthy" sync
   status cannot answer "did the last run actually find and fix anything?",
   only "did it complete without error?" Named here as a gap, **not
   proposed to be fixed in this design** (would touch the checkpoint's
   write path — see Section 13, Non-Goals).
6. No way to distinguish "webhook stopped arriving" from "WhatsApp is quiet"
   — architecturally unsolvable with currently-available data (Section 2),
   not merely unbuilt.
7. Whether production actually runs `RECONCILIATION_EXECUTOR=celery` remains
   unconfirmable from source alone (same finding as the prior two audits —
   `infrastructure/office/docker-compose.yml` provisions Celery/Redis, but
   nothing in code enforces the env var being set) — re-stated, not
   re-investigated, since nothing new is available to resolve it without
   live access this task doesn't have.

---

## 5. Proposed Minimal Architecture

**Two independent signals, not one merged concept** — this directly answers
the task's explicit requirement to distinguish "server unavailable" from
"data not synced" from "WhatsApp is quiet":

**Signal A — Read-connectivity** (does the frontend's *own* network calls to
Django/BFF succeed right now?). Purely derived, client-side, from the
existing `ApiError.kind` on the existing chat-list/messages polling calls —
**needs no new backend endpoint at all**. This is "is the server reachable"
in the most literal sense.

**Signal B — Sync health** (is reconciliation itself healthy, independent of
whether the frontend can currently reach Django?). Requires a new backend
read surface over `SyncCheckpoint`, since nothing durable about
reconciliation's own health is visible from outside Django today. This is
"is the data I'm looking at actually current."

**Derived sync-health states, computed — not stored** (directly answering
"tentukan bagaimana production seharusnya membedakan: healthy / stale /
never synced / running / failed", and directly honoring "jangan menghidupkan
`lag_seconds` hanya karena field tersebut sudah ada" — this design uses only
`status` and `last_run_at`, both already reliably written, and computes
everything else on read rather than adding a new stored field):

| Derived state | Condition (computed from existing fields only) |
|---|---|
| **never_synced** | No `SyncCheckpoint` row exists for the session at all. |
| **running** | `status == 'running'`. (Optionally sub-flagged `possibly_stuck: true` if `updated_at` is older than a generous multiple of the retry loop's own bound — PROPOSED, not required for a first version; see Section 4, gap 4.) |
| **failed** | `status == 'error'` (the most recent attempt errored). |
| **healthy** | `status == 'ok'` AND `(now - last_run_at) <= STALE_THRESHOLD_SECONDS`. |
| **stale** | `status == 'ok'` BUT `(now - last_run_at) > STALE_THRESHOLD_SECONDS` — the last *attempt* succeeded, but no attempt has run recently enough, implying the periodic mechanism itself has stopped (Celery beat/worker down, Redis down, or the office deployment simply not running Celery at all). |

`STALE_THRESHOLD_SECONDS` is **proposed as a multiple of the already-configured
`RECONCILIATION_INTERVAL_SECONDS`** (e.g. 2–3×) rather than a new hardcoded
or newly-configured constant — this means the threshold automatically tracks
whatever interval a given environment is already running, satisfying
Section 9's "no environment-specific branching" requirement without adding
a second env var to keep in sync with the first. The exact multiplier is a
tuning choice, not derivable from the repository — **Section 12, decision
point**.

This derivation can live **either** in the backend (endpoint returns the
already-classified state) **or** the frontend (endpoint returns raw
`status`/`last_run_at`, frontend classifies) — both are equally "minimal";
Section 6 recommends server-side classification for schema stability
(Section 12 still flags it as worth confirming).

---

## 6. API Design Proposal

**Two independent, small additions — same fork as the prior design audit,
now with a concrete schema.** Neither is implemented here.

**A. Sync status.** Two shape options remain genuinely open (Section 12):
a dedicated `apps.sync` endpoint, or a field on the existing Dashboard
aggregate. Proposed response shape, either way:

```json
{
  "sessions": [
    {
      "session": "no_epahari",
      "sync_status": "healthy",
      "last_run_at": "2026-09-25T10:00:00Z",
      "seconds_since_last_run": 320,
      "last_webhook_received_at": "2026-09-25T10:04:12Z"
    }
  ]
}
```

- **A list, not a single object** — proposed even though exactly one
  session is currently operable end-to-end (the BFF's `sessionGuard` is
  single-session by construction, unchanged), because `WahaSession` itself
  already supports multiple rows and `docs/00-MASTER-SPEC.md` names
  "kemungkinan maksimal 2–3" as a stated possibility — a list costs nothing
  extra to return today (it will just have zero or one entries) and avoids
  a breaking shape change later. This is a low-stakes choice, not forced
  either way (Section 12).
- `sync_status`: one of the five derived states from Section 5 —
  **computed server-side** in this proposal, so the frontend never
  re-implements the threshold logic (keeps the "response schema yang
  stabil" property the task asked for — the frontend only ever switches on
  a fixed string enum, never recomputes a derived state from raw
  timestamps).
- `session: "never_synced"` case: `last_run_at`/`seconds_since_last_run`/
  `last_webhook_received_at` all `null`.
- `last_error` is **deliberately excluded** from this shape — same
  reasoning as the prior design audit (Section 17 there): it can contain
  fragments of WAHA response text or exception messages, and this endpoint
  is proposed unauthenticated (below), so raw error text would be
  inconsistent with `apps/core/exceptions.py`'s existing discipline of never
  echoing raw exception text externally. If operators want the error
  detail, that's a separate, authenticated surface — not proposed here.
- `last_webhook_received_at` — one additional query
  (`WebhookEvent.objects.filter(session=session).aggregate(Max('received_at'))`),
  optional but cheap, directly serving Section 4/gap 6's partial mitigation
  (Section 8).
- **Auth**: same open question as before, **not resolved here** — follow
  the `Liveness`/`DatabaseHealth` unauthenticated-infra-probe precedent (this
  report's default recommendation, since the payload above carries no PII
  and no raw error text), or gate behind `HasReadingScope` like the chats
  endpoints. Flagged in Section 12.

**B. Redis health.** Unchanged proposal from the prior design audit:
`GET /api/health/redis/`, mirroring `DatabaseHealthView` exactly (no auth,
never echo raw broker URL/error), using the already-available `redis`
package. No new schema design needed beyond the existing
`{status, component}` shape `LivenessView`/`DatabaseHealthView` already use.

**Neither addition changes any existing endpoint's contract or the BFF.**

---

## 7. Frontend UX Proposal

**Three distinguishable situations, per the task's explicit requirement —
kept as two separate, independently-triggered indicators (not one merged
badge), specifically so they don't get conflated:**

1. **"Server/API tidak tersedia"** — Signal A (Section 5). A small,
   unobtrusive indicator (reusing `StatusBadge`, no new visual language)
   shown only when Inbox's own read-polling has failed enough consecutive
   times to matter (same LIVE→RECONNECTING→STALE ladder proposed in the
   prior design audit's Section 7/8, unchanged here — this report does not
   redesign it, only re-confirms it's still the right mechanism since
   `ApiError.kind` is still discarded exactly as before). Triggers purely
   from existing endpoints' failures — **no dependency on the new backend
   endpoint at all**.
2. **"Data belum sinkron"** — Signal B (Section 6's `sync_status`). A
   separate, **quiet-by-default** badge (only rendered when `sync_status`
   is `stale`/`failed`/`never_synced` — never rendered at all when
   `healthy`, so it adds zero visual noise in the common case, directly
   answering "jangan membuat UX yang terlalu ramai"). Proposed placement:
   near the chat-list header, since sync health is a property of the whole
   Inbox's data, not of any one conversation. Independent of Signal A — a
   perfectly reachable Django with a stale `SyncCheckpoint` should show
   *only* this badge, not a connectivity warning.
3. **"WhatsApp memang sedang sepi"** — the deliberate **absence** of both
   signals above. Not a state to build — a consequence of Signals A and B
   being correctly scoped: if Django is reachable (Signal A: LIVE) and
   reconciliation is healthy (Signal B: `healthy`), an empty or quiet chat
   list is presented exactly as it is today (the existing, correct
   `EmptyState`/`unread`-driven UI, untouched) — no warning of any kind.
   This is what makes the two-signal design important: a single merged
   indicator risks either over-warning on quiet-but-fine days, or
   under-warning when data is stale but the API still technically responds.

**Explicitly not proposed**: any indicator inside individual message
bubbles, any change to the chat-list item rendering, any change to
`chatDisplay()` or identity fallback logic (all untouched, per the task's
scope-protection list).

---

## 8. Redis/Celery Behavior

Same underlying facts as the prior design audit, restated with the two
additional scenarios this task explicitly asked about, traced precisely:

- **Redis down, executor `sync`**: zero effect — the `sync` path never
  touches Redis (`executors.py:78-79`). Confirmed unchanged.
- **Redis down, executor `celery`**: `reconcile_chat_task.delay()`
  publishes to the broker synchronously; unreachable Redis raises inside
  the Django request handling `POST /internal/reconciliation/trigger/`
  (fire-and-forget from the BFF, doesn't block the send response, per
  Phase 8's existing design — unchanged, untouched). The periodic Celery
  Beat dispatch also fails to publish. **From `SyncCheckpoint`'s
  perspective, this produces exactly the `stale` derived state (Section
  5)** — the checkpoint simply stops advancing, `last_run_at` ages past the
  threshold.
- **Celery worker down, Redis up** (the task's new scenario): `.delay()`
  succeeds — the task is durably enqueued in Redis — but nothing ever
  consumes it. `reconcile_session()` is only entered once a worker actually
  executes the task body, so `checkpoint.status` is **never even set to
  `running`**; it simply stays at whatever it last was. **From
  `SyncCheckpoint`'s perspective this is indistinguishable from the
  "Redis down" case above** — both present as `stale` once enough time
  passes, because neither the sync-status endpoint (Section 6) nor
  `SyncCheckpoint` itself has any visibility into Celery queue depth or
  worker liveness. **Distinguishing the two root causes (broker down vs.
  worker dead) would require the separate Redis health check (Section 6.B)
  plus, for worker liveness specifically, a Celery-native check (e.g.
  `celery_app.control.ping()`) that is not proposed in this report** — named
  here as a real limitation of the minimal design, not silently glossed
  over. For an *operator* ("is my data stale, yes/no"), this distinction
  may not matter; for an *engineer debugging it*, it would.
- **Executor `celery`, worker present, Redis present** (the healthy case):
  unchanged, already correct, not discussed further.

---

## 9. Production Compatibility

Every proposal in this report is config-driven, not code-forked, matching
the task's explicit principle:

- The `sync_status` derivation (Section 5) reads only
  `settings.RECONCILIATION_INTERVAL_SECONDS` (already environment-configured,
  same variable in both dev and production) to compute its staleness
  threshold — no new environment variable, no `if DEBUG` / `if
  settings.ENVIRONMENT == 'production'` branch anywhere.
- `RECONCILIATION_EXECUTOR` itself remains untouched, unqueried-for-change —
  this report reads its value to explain behavior (Section 8), never
  proposes altering it or branching on it in new code beyond what
  `executors.py` already does.
- The Redis health check (Section 6.B) reads `settings.CELERY_BROKER_URL`,
  already present and already environment-specific by design (`redis://redis:6379/0`
  in Docker, whatever a developer configures locally) — same code path
  either way.
- **Development-specific expected behavior, not a defect**: in local manual
  dev (no Celery/Redis running, per `README.md`'s own admission, unchanged),
  the proposed Redis health check would correctly show unreachable, and
  `sync_status` would correctly show `stale` or `never_synced` for any
  session whose reconciliation has only ever run via the `sync` executor's
  own targeted triggers (which do advance the checkpoint) or not at all.
  This is accurate, not misleading, and requires no special-casing in code —
  the same derivation logic simply produces an honest answer for whatever
  the real environment's state is.

---

## 10. Dependency Order

Dependency-derived only — no ranking, per instruction.

- **9.1A — Backend: sync-status derivation + endpoint** (Section 5/6.A).
  Depends on nothing else. The single decision this needs first (endpoint
  shape/auth, Section 12) is a product decision, not a code dependency.
- **9.1B — Backend: `last_webhook_received_at` addition** (Section 6.A).
  Naturally extends 9.1A's same response if built together, but is logically
  independent — a separate query, no shared state with the checkpoint logic.
- **9.1C — Backend: Redis health endpoint** (Section 6.B). Fully independent
  of 9.1A/B — different model, different concern.
- **9.1D — Frontend: read-connectivity indicator (Signal A)** (Section 7,
  item 1). Depends on **nothing backend-side** — it classifies failures of
  the chat-list/messages endpoints that already exist today. Could be built
  and shipped before 9.1A–C exist at all.
- **9.1E — Frontend: sync-status badge (Signal B)** (Section 7, item 2).
  Depends on 9.1A.
- **9.1F — Frontend: Dashboard Redis card**. Depends on 9.1C. Reuses
  `HealthCard` verbatim, as established.
- **9.1G — Manual/live verification** of every derived state (`healthy`,
  `stale`, `never_synced`, `running`, `failed`, plus the two indicators'
  actual on-screen behavior) against the real dev environment — depends on
  9.1A–F being built; cannot happen inside a design-only audit.

9.1D has no dependency on any other item in this list and is the cheapest,
most self-contained piece here, the same way Phase 9.0 was — worth naming
explicitly since it could reasonably be sequenced first for the same reason
Phase 9.0 was peeled off early, though this report does not rank it above
the others, only notes its independence.

---

## 11. Risks

- The `stale` threshold (Section 5) is a tunable multiplier with no
  objectively correct value derivable from the repository — same category
  of risk as Phase 9's earlier connectivity-failure-count threshold, and
  handled the same way: presented as an adjustable default, not a hard
  requirement.
- The `celery`-worker-dead vs. `Redis`-down ambiguity (Section 8) is a real,
  named limitation of this minimal design — accepted deliberately rather
  than solved, per the "prefer minimal change" / "no new architecture just
  for a health indicator" principles this project has consistently applied
  across Phase 9.0 and the prior design audit.
- A stuck `RUNNING` checkpoint (Section 2/4, gap 4) has no timeout/recovery
  mechanism — this design's `running` derived state would show that
  situation as "running" indefinitely rather than eventually reclassifying
  it as `failed`, unless the optional `possibly_stuck` sub-flag (Section 5)
  is built. Flagged, not silently accepted, but also not proposed to be
  fixed here since it would mean adding new write-path logic
  (auto-recovery) to `reconcile_session()` itself — out of this report's
  minimal-change scope (Section 13).
- Exposing `sync_status`/`last_run_at` on an unauthenticated endpoint (if
  that auth posture is chosen) is a small information-disclosure surface —
  mitigated by excluding `last_error` (Section 6), but not zero; this is the
  same trade-off already accepted for `LivenessView`/`DatabaseHealthView`.

---

## 12. USER DECISIONS REQUIRED

1. **Sync-status endpoint shape**: dedicated `apps.sync` endpoint, or a
   field on the existing Dashboard aggregate? (Section 6.A — unresolved,
   same fork as the prior design audit, now with a concrete payload either
   way could carry.)
2. **Auth posture** for the new sync-status and Redis-health endpoints:
   unauthenticated (matching Liveness/DatabaseHealth) or gated? (Section
   6/11.)
3. **`STALE_THRESHOLD_SECONDS` multiplier** — this report proposes 2–3× the
   configured `RECONCILIATION_INTERVAL_SECONDS` as a starting default;
   confirm or adjust. (Section 5/11.)
4. **Whether `sync_status` derivation happens server-side (proposed) or
   client-side** — server-side keeps the frontend simpler and the schema
   more stable (Section 6), but is a real design choice worth confirming
   rather than assuming.
5. **Whether to build the optional `possibly_stuck` sub-flag** for a
   long-`running` checkpoint (Section 5/11), or leave that gap named but
   unaddressed for now.
6. **Whether `last_webhook_received_at` (9.1B) is wanted at all** — cheap,
   but adds one more field to the schema and one more query; not assumed.
7. **Confirm `RECONCILIATION_EXECUTOR` in the real production/office
   environment** — same unresolved item carried forward from both prior
   audits (Section 2/4, gap 7); this task found nothing new to resolve it.

---

## 13. Explicit Out-of-Scope Items

Restated and held to, matching the task's own scope-protection list —
nothing below was touched, read-for-editing, or proposed to change:

- `@lid`/JID identity resolution, `chatDisplay()`, any Contact/Chat
  auto-merge — untouched.
- `status@broadcast` — no filter proposed or implied anywhere in this
  report; not mentioned again beyond this line.
- Session Management (`SessionsPage.tsx`/`.css`) — read only, to confirm
  its pattern is unchanged since Phase 9.0 reused it; not edited, and no
  edit is proposed here either.
- Outbound send behavior / `OutboundOperation` idempotency / the BFF's
  `messages.ts` — unchanged, unread-for-editing this task (only cited from
  prior confirmed knowledge).
- Reconciliation's persistence logic (`persist_message()`,
  `reconcile_session()`'s dedup/checkpoint-advance rules) — described, never
  proposed to change. The one new gap named (Section 4, gap 5 —
  `messages_inserted` not persisted) is explicitly **not** proposed to be
  fixed here.
- Already-finished Inbox message rendering (`wa-inbox__bubble*`, media
  handling, mark-as-read) — untouched.
- Phase 9.0's own change — not revisited, not re-verified beyond the
  `git status` check in the preamble.
- Phase 11 (Blast), Phase 13 (Failure/security testing), Phase 14
  (Production deployment) — not started, not scoped further here.
- No migration, no endpoint implementation, no config/`.env` change, no
  write/internal-endpoint call, no live WhatsApp send — all consistent with
  every hard rule this task stated.

---

## 14. Recommended Next Implementation Prompt

Per the dependency order in Section 10, if/when you're ready to move from
design to implementation, the smallest, most independent next slice is
**9.1D — the read-connectivity indicator (Signal A)** — it requires no
backend work, no new endpoint, and no decision from Section 12 to be
resolved first, since it only consumes the `ApiError.kind` taxonomy that
already exists on `InboxPage.tsx`'s two existing polling calls. It is to the
*read* path what Phase 9.0 was to the *write* path — the same shape of
small, additive, precedent-reusing change.

If instead you want to start with the backend (9.1A), Section 12's items 1–4
would need to be settled first, since they directly determine the
endpoint's shape and response contract before any code is written against
it.

This report does not choose between these two starting points — it only
notes which one has decisions still pending versus which one doesn't.

---

This was a design/read-only audit. No implementation was performed. Per
your instruction, stopping here and awaiting your decisions on Section 12
before any further Phase 9 work begins.
