# Phase 11 — Blast Backend/API — Implementation Report

> **Phase labeling note (added 2026-09-26):** this report's passing
> reference below to "the prior 13.B task" uses an informal label. That
> label is not part of the canonical roadmap's Phase 13
> ("Failure/security testing", `docs/15-CODING-PHASES.md`) — it refers to
> earlier reconciliation-recovery/diagnostics-UI work that is properly a
> continuation of Phase 4/Phase 9. See
> `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` for the recorded decision.

## 1. Objective

Implement the backend/API slice of Phase 11 (Blast — controlled bulk
WhatsApp send): a new Django app (`backend/apps/blast/`) with campaign
CRUD, admin approval workflow, throttled Celery dispatch, and a new
internal BFF endpoint for Office/Celery → Tencent/BFF message dispatch —
per `docs/generated/PHASE-11-BLAST-DESIGN-AUDIT-REPORT.md` as the base
design, overridden/finalized by this task's own prompt wherever the two
differ. `frontend/` and reconciliation/`possibly_stuck`/`SyncCheckpoint`
code were explicitly out of scope and were not touched (confirmed in
Section 9). No live blast, WAHA call, or BFF call was ever exercised.

## 2. Readiness Check (performed before writing any code)

**No blocker found.** Every field/status/endpoint/permission/task implied
by the finalized decisions was traceable to an existing pattern already in
this codebase:

- Idempotency: `apps.operations.OutboundOperation`'s existing
  `unique(session, idempotency_key)` constraint and register/resolve
  discipline (`apps/operations/models.py`, `views.py`) — reused directly
  by `BlastRecipient.outbound_operation`, `operation_type='blastSend'`.
- Compare-and-set concurrency: `apps.sync.views.SyncCheckpointRecoveryView`'s
  `.filter(pk=..., status=<value just read>).update(...)` pattern — reused
  verbatim for every `BlastCampaign`/`BlastRecipient` status write.
- Scope-checking permission shape: `apps.authn.permissions.HasReadingScope`/
  `HasSystemAdministrationScope` — `HasBlastScope` added in the same shape,
  checking the already-declared `'blast'` `JWT_SCOPES` entry.
- Internal shared-secret auth shape:
  `apps.core.internal_auth.HasInternalServiceKey` (Django-side,
  BFF→Django) mirrored on the BFF side, in the new direction
  (Office→BFF), by `bff/src/middleware/officeAuth.ts`.
- `zoneinfo` (Python 3.9+ stdlib; `backend/Dockerfile` is
  `python:3.12-slim`) covers the Asia/Jakarta calendar-day requirement —
  no new dependency needed.
- No conflict was found between any two finalized decisions.

Implementation proceeded directly; no "USER DECISIONS REQUIRED" stop was
needed.

## 3. Files Created / Changed

### Backend — new app (`backend/apps/blast/`)
- `models.py` — `BlastCampaign`, `BlastRecipient`, `OPERATION_TYPE_BLAST_SEND`.
- `limits.py` — Asia/Jakarta calendar-day budget accounting
  (`jakarta_day_bounds_utc`, `blast_sends_today`, `remaining_daily_budget`).
- `bff_client.py` — `send_blast_message()` / `BffDispatchError`, the
  Django → BFF HTTP call (mockable, isolated per the "must remain
  unit-testable without a live BFF" requirement).
- `serializers.py` — `BlastCampaignCreateSerializer` (100-recipient cap,
  dedup, unknown-session rejection), `BlastCampaignListSerializer`,
  `BlastCampaignDetailSerializer`, `BlastRecipientSerializer`,
  `BlastCampaignRejectSerializer`.
- `views.py` — `BlastCampaignListCreateView`, `BlastCampaignDetailView`,
  `BlastCampaignSubmitView`, `BlastCampaignApproveView`,
  `BlastCampaignRejectView`.
- `tasks.py` — `schedule_blast_campaign_task`, `dispatch_blast_recipient_task`,
  `_maybe_finalize_campaign`.
- `urls.py`, `apps.py`, `admin.py` (read-only registration; creation
  disabled via `has_add_permission`), `migrations/0001_initial.py`.
- `tests/` — `test_models.py`, `test_limits.py`, `test_views.py`,
  `test_tasks.py` (63 tests).

### Backend — existing files modified
- `backend/apps/authn/permissions.py` — added `HasBlastScope`.
- `backend/config/settings.py` — registered `apps.blast`; added
  `BLAST_MAX_RECIPIENTS_PER_CAMPAIGN` (100), `BLAST_MAX_RECIPIENTS_PER_SESSION_PER_DAY`
  (500), `BLAST_INTER_MESSAGE_DELAY_SECONDS` (60), `OFFICE_DISPATCH_SERVICE_KEY`,
  `BFF_INTERNAL_BASE_URL`, `BFF_INTERNAL_TIMEOUT_MS`.
- `backend/config/urls.py` — mounted `apps.blast.urls` at `/api/blast/`.
- `backend/.env.example` — documented the six new variables above.

### BFF
- `bff/src/routes/internalBlast.ts` (new) — `POST /internal/blast/send`.
- `bff/src/middleware/officeAuth.ts` (new) — `requireOfficeDispatchKey`.
- `bff/src/app.ts` — mounted the new router at `/internal` (not `/api`).
- `bff/src/config.ts` — added `officeDispatchServiceKey`.
- `bff/.env.example` — documented `OFFICE_DISPATCH_SERVICE_KEY`.
- `bff/test/routes.internalBlast.test.ts` (new, 12 tests).

### Docs
- This report.

**Not touched**: `frontend/` (confirmed zero files), any
reconciliation/`SyncCheckpoint`/`possibly_stuck` code, any Docker/Compose
file, any dependency manifest (`requirements.txt`/`package.json`
unchanged — `zoneinfo` is stdlib, `requests` was already a dependency).

## 4. Data Model (as implemented)

`BlastCampaign` (`session` FK → `WahaSession`, `name`, `message_template`,
`status`, `created_by`/`approved_by` FKs → `User`, `approved_at`,
`rejected_reason`, `+TimeStampedModel`'s `created_at`/`updated_at`).

`BlastRecipient` (`campaign` FK, `destination`, `status`, `scheduled_for`,
`sent_at`, `failure_reason`, `outbound_operation` FK →
`OutboundOperation`, `+TimeStampedModel`).

Two deliberate deviations from the design audit's Section 3 proposal,
made as implementation-detail calls (not specified by the finalized
decisions) and documented here per the task's own instruction:

1. **No stored `recipient_count`.** The audit proposed a denormalized
   field; this implementation computes it on read
   (`recipients.count()`/`SerializerMethodField`) instead, to avoid a
   second value that could drift from the real row count. Recipient
   counts here are in the low hundreds at most (100/campaign cap), so
   the extra `COUNT` query has no meaningful cost.
2. **No stored `idempotency_key` field.** It is fully derived
   (`blast:{campaign_id}:{recipient_id}`) via a model `@property`, not
   persisted — both IDs it depends on already exist on the row, so a
   third stored copy would only be a source of potential staleness.
3. **`UniqueConstraint(campaign, destination)`** (not in the audit's
   proposal) — a duplicate destination within one campaign is treated as
   an input mistake; the DB rejects it. The recipient serializer also
   de-duplicates exact-string repeats client-side before this constraint
   would ever fire, so the common "pasted list has a repeat" case gets a
   clean validation error, not an `IntegrityError`.

## 5. State Machine (as implemented)

`draft → pending_approval → approved → sending → completed`, with
`pending_approval → rejected` (terminal) and `sending → failed`
(terminal, reachable only when **every** recipient ends up `failed` —
partial failure still reaches `completed`, per decision 2).

Implemented as `BlastCampaign.ALLOWED_TRANSITIONS` (a dict of
`from_status → {allowed to_statuses}`) plus
`BlastCampaign.is_valid_transition(from, to)`, checked in every
status-changing view/task **before** any write. Every write is a
compare-and-set (`.filter(pk=..., status=<value just read>,
updated_at=<value just read>).update(...)`), never a blind `.save()` —
mirrors `SyncCheckpointRecoveryView` exactly. A transition attempted from
the wrong status, or a write that raced with a concurrent change, returns
`409` with `invalid_transition` or `concurrent_state_change`
respectively, never a silent overwrite.

`BlastRecipient.status`: `pending → sending → {sent | failed}`, plus
`skipped` (declared in the enum for a future cancel/resume feature — no
code path in this implementation sets it; documented as a known,
intentional gap, not a bug).

## 6. Dispatch / Throttling

- **`schedule_blast_campaign_task`** (triggered once, synchronously, by
  `BlastCampaignApproveView` right after approval): claims the campaign
  (`approved → sending`, compare-and-set — a redelivered duplicate call
  becomes a no-op), computes each pending recipient's `scheduled_for` at
  exactly `BLAST_INTER_MESSAGE_DELAY_SECONDS` (60s) apart, in `id` order,
  and calls `dispatch_blast_recipient_task.apply_async(args=[...],
  countdown=...)` once per recipient — **never** `time.sleep`.
- **Same-session throttle across campaigns** (decision 3's explicit
  scope — "on the same session", not per-campaign): before assigning
  times, the scheduler looks up the latest already-`scheduled_for`
  `pending` recipient on the *same session*, across any *other*
  campaign, and starts no earlier than 60s after it. Recipients on a
  *different* session never coordinate with each other (verified by
  `test_different_session_recipients_do_not_throttle_each_other`).
- **`dispatch_blast_recipient_task`** (fires once per recipient at its
  scheduled time): re-checks `campaign.status == 'sending'` → claims the
  recipient (`pending → sending`, compare-and-set) → registers/fetches
  the linked `OutboundOperation` → calls the BFF → resolves both rows.
  Each invocation is short-lived (one HTTP call), so `CELERY_TASK_TIME_LIMIT`
  (600s) is never a concern regardless of campaign size — this was the
  design audit's core correctness argument against a single looping task,
  and it holds by construction here.
- **Daily budget enforcement**: checked synchronously in
  `BlastCampaignApproveView`, **before** the campaign is allowed to reach
  `approved` — `apps.blast.limits.remaining_daily_budget(session)` counts
  only `operation_type='blastSend'` `OutboundOperation` rows
  (decision 3: blast-specific, not shared with 1:1 sends) created within
  the current **Asia/Jakarta calendar day** (decision 3: not UTC — `
  apps.blast.limits.jakarta_day_bounds_utc()` uses `zoneinfo`). A
  campaign that would exceed the remaining budget is rejected with `409
  daily_budget_exceeded` and never leaves `pending_approval` — it is
  never partially dispatched and left to stall mid-campaign.
- **Campaign finalization**: `_maybe_finalize_campaign()`, called after
  every recipient dispatch resolves, transitions `sending → completed`
  (or `→ failed` iff every recipient is `failed`) once all recipients
  reach a terminal status — also a compare-and-set, safe if two
  recipients finish at nearly the same moment.

## 7. Idempotency

`BlastRecipient.idempotency_key` is `blast:{campaign_id}:{recipient_id}`
— deterministic, derived, never random. `dispatch_blast_recipient_task`
uses `OutboundOperation.objects.get_or_create(session=..., idempotency_key=...)`,
reusing the exact same DB-level `unique(session, idempotency_key)`
constraint `apps.operations` already enforces for 1:1 sends — **no
parallel idempotency mechanism was built**. Defense-in-depth is layered
on top, not instead of, that DB constraint: (1) the task re-checks
`campaign.status`, (2) claims the recipient row (`pending → sending`,
compare-and-set) before doing anything else, (3) if the linked
`OutboundOperation` is already `sent` when fetched (e.g. a redelivered
task), the task reflects that status without calling the BFF again.
`test_the_same_recipient_task_firing_twice_results_in_exactly_one_sent_outbound_operation`
and `test_redelivery_after_operation_already_sent_reflects_without_resending`
verify both layers directly.

## 8. The New BFF Endpoint

`POST /internal/blast/send` (`bff/src/routes/internalBlast.ts`), mounted
at `/internal` (not `/api`, the prefix every frontend-reachable route
uses). Authenticated **only** by `requireOfficeDispatchKey`
(`bff/src/middleware/officeAuth.ts`) — a constant-time comparison against
`OFFICE_DISPATCH_SERVICE_KEY`, a **new, distinct** secret from
`INTERNAL_SERVICE_KEY` (which authenticates the opposite direction,
BFF→Django). This route accepts **no** `Authorization: Bearer` JWT of any
kind — `requireAuth`/`requireScope` are never applied to it — so a
frontend/browser session token can never route through it even if the
URL were somehow known. It performs exactly one operation
(`callWaha('sendText', ...)`, the same allowlisted call
`routes/messages.ts` already uses) and takes no arbitrary path/method —
not a generic proxy, satisfying CLAUDE.md rule 5 the same way the
existing `WAHA_ALLOWED_ENDPOINTS` structure already does for every other
route.

It deliberately does **not** call `registerOutboundOperation`/
`resolveOutboundOperation` back to Django: unlike the 1:1 send flow
(where the BFF is the first party to learn of the send), here Django's
own Celery task is the caller and already owns its `OutboundOperation`
row directly via the ORM — a second HTTP hop back to Django would
duplicate state Django already holds. Response contract: always HTTP 200
with `{"status": "sent" | "failed" | "unknown", providerMessageId?}` —
a structured field rather than HTTP status-code semantics, since the
caller is a trusted internal service that needs the three-way
distinction, not a browser needing REST status conventions.

## 9. AuditLog Usage

Three actions, matching `SyncCheckpointRecoveryView`'s
`AuditLog.objects.create(actor=request.user, action=..., target=...,
result=...)` pattern exactly:
- `blast.campaign.create` (creation, `BlastCampaignListCreateView.post`).
- `blast.campaign.approve` (`BlastCampaignApproveView.post`).
- `blast.campaign.reject` (`BlastCampaignRejectView.post`).

Per-recipient dispatch sends do **not** each write a Django `AuditLog`
row (a 100-recipient campaign would otherwise write 100 rows for one
approval) — this matches the task's explicit instruction ("AuditLog
entries for campaign creation/approval/rejection") and is a deliberate,
documented scope boundary, not an oversight. The BFF's own
`logAuditFallback` (a local structured log line, not a Django write) is
still emitted per send, matching this project's existing observability
convention for every WAHA-facing route.

## 10. Test Results

**Targeted (`apps.blast`, `DJANGO_SETTINGS_MODULE=config.settings_test`,
SQLite — this project's own established test-settings convention, per
`docs/generated/PHASE-9-1B-WEBHOOK-TIMESTAMP-IMPLEMENTATION-REPORT.md`
and others):**

```
$ docker exec -e DJANGO_SETTINGS_MODULE=config.settings_test development-backend-1 \
    python manage.py test apps.blast -v 2
...
Ran 63 tests in 6.049s
OK
```

Covers: recipient cap enforcement (≤100, exactly-100 boundary, empty
rejected, duplicates deduplicated); every transition table branch
(valid and invalid) at both the model-method and API level; approval
scope + self-approval rejection (including a user holding *both*
`'blast'` and `'system administration'`); daily-budget enforcement at
approval time, exact-boundary and over-budget cases, using Asia/Jakarta
day math specifically (including a case proving the Jakarta boundary
differs from the UTC boundary); scheduling spacing (exact 60s apart,
correct `countdown` values, same-session cross-campaign throttling,
different-session non-throttling, double-invocation idempotence); the
double-fire idempotency case decision 2/6 of the readiness check called
out explicitly; sanitized failure-reason (raw exception text never
reaches `BlastRecipient.failure_reason`); campaign finalization
(partial-failure → `completed`, all-failed → `failed`); AuditLog writes
for all three actions.

**Full backend suite:**

```
$ docker exec -e DJANGO_SETTINGS_MODULE=config.settings_test development-backend-1 \
    python manage.py test
...
Ran 408 tests in 18.474s
OK
```

408 = 345 pre-existing + 63 new (`apps.blast`). Zero pre-existing test
broke. (The Redis/WAHA connection-error tracebacks in the output are
expected, deliberately-mocked-failure assertions from pre-existing tests
in `apps.core`/`apps.sync`, not new failures.)

**`manage.py check`** (both `config.settings_test` and the real dev
settings): `System check identified no issues (0 silenced).`

**`manage.py makemigrations --check --dry-run`** (both settings
modules): `No changes detected` — the committed migration is complete.

**BFF (`npm test`, vitest):**

```
Test Files  12 passed (12)
     Tests  120 passed (120)
```

108 pre-existing + 12 new (`routes.internalBlast.test.ts`), covering: the
office-dispatch-key gate (missing/wrong key/JWT-instead-of-key all
rejected — no request ever reaches `callWaha` without the correct
secret); unknown-session rejection; missing-field validation; the
sent/failed/unknown outcome mapping; that the WAHA API key never leaks
into any response; that this route never calls Django's
outbound-operations endpoints (confirming Section 8's "no redundant hop"
claim above). `npm run typecheck` (`tsc --noEmit`): clean, zero errors.

## 11. Migration Review / Application

`backend/apps/blast/migrations/0001_initial.py` was generated via
`docker compose -f infrastructure/development/office.yml exec backend
python manage.py makemigrations blast` and reviewed via `sqlmigrate`
before being treated as final. **Confirmed purely additive**: two `CREATE
TABLE` statements (`blast_blastcampaign`, `blast_blastrecipient`), their
own indexes/constraints, and `ADD CONSTRAINT ... FOREIGN KEY` references
from the new tables into three existing ones (`auth_user`,
`waha_sessions_wahasession`, `operations_outboundoperation`). **No
existing table is altered** — no `ALTER TABLE ... ADD/DROP/ALTER COLUMN`
against any pre-existing table appears anywhere in the generated SQL.

Applied to the running dev PostgreSQL database (VERIFIED):
```
$ docker exec development-backend-1 python manage.py migrate blast
Applying blast.0001_initial... OK
$ docker exec development-backend-1 python manage.py showmigrations blast
blast
 [X] 0001_initial
```
The dev database/containers were already running before this task
(confirmed via `docker ps`, matching this session's established
practice from the prior 13.B task) — nothing was started, stopped, or
restarted to do this.

## 12. Git Diff Summary

**New**: `backend/apps/blast/` (17 files: app code + 4 test files + 1
migration), `bff/src/routes/internalBlast.ts`,
`bff/src/middleware/officeAuth.ts`, `bff/test/routes.internalBlast.test.ts`,
this report.

**Modified** (7 files, 75 insertions, 0 deletions — every change is a
pure addition, confirmed via `git diff --stat`):
`backend/apps/authn/permissions.py` (+14), `backend/config/settings.py`
(+24), `backend/config/urls.py` (+1), `backend/.env.example` (+14),
`bff/.env.example` (+7), `bff/src/app.ts` (+6), `bff/src/config.ts` (+9).

**Confirmed untouched by this task** (`git status` at task start already
showed these as modified by prior work — re-confirmed unchanged by
`git diff` scoped to just this task's files above): `frontend/` (zero
files), `docs/02-REQUIREMENTS.md`, `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`,
`infrastructure/development/office.yml`, all reconciliation/
`SyncCheckpoint`/`possibly_stuck` code, all Docker/Compose files, all
dependency manifests (`requirements.txt`, `package.json`).

## 13. Known Limitations (v1, explicitly deferred)

- **No automatic retry** for a failed recipient send (decision 5) —
  `dispatch_blast_recipient_task` records `failed` with a sanitized
  reason and completes normally; no `autoretry_for`, no `self.retry()`.
  A future phase would need a manual re-send/new-campaign flow.
- **No automatic resume** for a campaign interrupted by a worker/broker
  outage (decision 6) — `BlastRecipient.status`/`scheduled_for` alone
  remain fully diagnosable, but nothing re-schedules an unfired
  recipient automatically. No distributed lock, no periodic sweep.
- **`BlastRecipient.STATUS_SKIPPED`** exists in the model's enum for a
  future cancel/resume feature but no code path in this implementation
  ever sets it.
- **No live verification was performed** — no real blast was sent, no
  live call was made to a real WAHA instance, and the BFF↔Django/BFF↔WAHA
  path was never exercised end-to-end against live services, per the
  task's explicit prohibition. All verification above is: automated
  tests (Django + BFF, both with mocked external calls), `check`,
  `makemigrations --check`, and one real (additive-only) migration
  apply against the dev PostgreSQL database.
- **Per-recipient dispatch sends are not individually audit-logged** in
  Django's `AuditLog` (Section 9) — only campaign create/approve/reject
  are, per the task's explicit instruction.

## 14. Claim Classification

- **VERIFIED**: all test-run outputs (Section 10), the migration's
  `sqlmigrate` output and its real application to the dev database
  (Section 11), `git diff --stat` output (Section 12), `manage.py
  check`/`makemigrations --check` results.
- **INFERRED**: that the BFF's `sendText` allowlisted call behaves
  identically when invoked from `routes/internalBlast.ts` as it does from
  `routes/messages.ts` (both call the same `callWaha('sendText', ...)`
  function with the same shape of arguments) — not independently
  re-verified against a live WAHA instance in this task, consistent with
  the "no live blast" constraint.
- **NOT VERIFIED**: end-to-end behavior of a real campaign against a live
  BFF/WAHA stack; real-world WAHA response shapes for the blast path
  specifically (the existing `routes/messages.ts` code this reuses
  already carries its own "not live-verified" caveat for WAHA's exact
  `sendText` success-response field names — see that file's own
  comments — and this implementation inherits the same caveat, unchanged).
