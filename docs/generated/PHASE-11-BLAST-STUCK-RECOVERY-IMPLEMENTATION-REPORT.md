# Phase 11 — Blast — Stuck-Recipient Recovery — Implementation Report

> **Phase labeling note (added 2026-09-26):** this report's references
> below to "Phase 13.A" (including a quoted source-code string literal)
> and "Phase 13.B work" use informal labels. Those labels are not part of
> the canonical roadmap's Phase 13 ("Failure/security testing",
> `docs/15-CODING-PHASES.md`) — they refer to earlier
> reconciliation-recovery/diagnostics-UI work that is properly a
> continuation of Phase 4/Phase 9. The quoted `last_error` string is left
> verbatim since it reflects actual source code text. See
> `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` for the recorded decision.

## 1. Objective

Close the single FAIL from
`docs/generated/PHASE-11-BLAST-END-TO-END-AUDIT-REPORT.md` Section 4/6/
Summary — quoted verbatim from that report:

> **FAIL** — 1 — the "worker dies after WAHA send succeeds but before
> status is persisted" scenario (Section 4), specifically its
> **undocumented-by-the-prior-reports compounding consequence**: a
> recipient stuck in `sending` permanently blocks its campaign from ever
> reaching a terminal status, and there is **no operator-facing recovery
> path anywhere in this system** (not the API, not the Django admin,
> which marks `status` read-only).

Nothing else from that audit was touched: not the Celery
`acks_late`/redelivery documentation mismatch (Section 3, finding #2),
not the BFF network-exposure finding (Section 7, finding #3), not
reconciliation/`possibly_stuck`/`SyncCheckpoint`/Celery-worker-liveness
code, and no automatic resume/retry was added (finalized decision 6
still stands — this is a manual, human-triggered recovery action only).

## 2. Step 1 — Design Audit Findings

Re-read in full before writing any code: `backend/apps/blast/models.py`,
`tasks.py`, `views.py`, `admin.py`, `serializers.py`, the whole
`tests/` directory, and `backend/apps/sync/views.py`'s
`SyncCheckpointRecoveryView` (+ its tests in
`apps/sync/tests/test_views.py`) as the closest existing precedent for
"a human manually resolves a stuck automated process."

Confirmed facts (matching the audit's own citations, re-verified
against current line numbers):

- `dispatch_blast_recipient_task` (`tasks.py`) claims a recipient
  `pending -> sending` (compare-and-set) *before* calling the BFF, and
  only writes the terminal `sent`/`failed` status *after* the BFF call
  returns. If the process dies in that window, the recipient is stuck
  in `sending` forever.
- Re-invoking `dispatch_blast_recipient_task` for that recipient is
  provably a no-op (`claimed == 0` since status is no longer `pending`)
  — safe, but not self-healing.
- `BlastRecipientInline.readonly_fields` (`admin.py`) includes `status`
  — the Django admin cannot move it either.
- No API endpoint existed anywhere that could write `BlastRecipient.status`.
- `_maybe_finalize_campaign` (`tasks.py`) only finalizes a campaign once
  every recipient's status is in `TERMINAL_STATUSES = {sent, failed,
  skipped}` — `sending` is not terminal — so one stuck recipient
  permanently blocks that campaign's own finalization, even though it
  is a **free function**, not a method only reachable from inside
  `dispatch_blast_recipient_task`'s own call path. This meant a
  recovery action could safely call it directly (not re-implement it),
  closing both the recipient-level and campaign-level halves of the
  gap in one action, which Step 1's task instructions specifically
  called out as the part to get right.
- `BlastRecipient.status` already has `failed` (and `sent`) as valid,
  reachable terminal values — no new status value or migration is
  needed to express "this recipient's outcome is now known."

**Chosen minimal design**: a new admin-gated (`HasSystemAdministrationScope`,
the same scope `SyncCheckpointRecoveryView` uses for this exact "human
resolves a stuck automated thing" shape) API endpoint,
`POST /api/blast/campaigns/<pk>/recipients/<recipient_id>/resolve/`,
that lets the admin transition a `sending` recipient to `sent` or
`failed` — **their own choice**, not a system guess. Reasoning: the
system genuinely cannot know whether the WhatsApp message was actually
delivered in that ambiguous window (querying WAHA/reconciliation to
find out is explicitly out of scope for this task), so the honest
design records the outcome the operator determined externally (e.g.
they checked the actual WhatsApp chat). Recording `sent` here is safe
because it is a pure status write — the endpoint never imports or
calls `send_blast_message`/the BFF client, so no new message can ever
be sent by this action, only a status corrected. Recording `failed`
when unsure is always safe, just possibly inaccurate in the rare case
the message actually went through — an acceptable, disclosed trade-off
identical in spirit to `SyncCheckpointRecoveryView`'s own "mark as
failed, an operator can investigate further if needed" shape.

Implementation-detail choices made without escalating (per the task's
own instruction to make these calls rather than ask):
- Exact path/name: `campaigns/<pk>/recipients/<recipient_id>/resolve/`,
  mirroring `sync/recover/<session_name>/`'s "resolve/recover a stuck
  thing" verb choice.
- No creator restriction (unlike `BlastCampaignApproveView`) — resolving
  a stuck send is not a self-approval concern; mirrors
  `BlastCampaignRejectView`'s own precedent of no creator check under
  the same `HasSystemAdministrationScope` gate.
- Response shape: returns the full updated `BlastCampaignDetailSerializer`
  payload (same shape submit/approve/reject already return), so any
  frontend caller can `setCampaign(result.data)` identically — no new
  response contract invented.
- Rejection when the recipient is not currently `sending` (already
  resolved, still `pending`, etc.) returns `409 not_sending`, distinct
  from the compare-and-set race response `409 concurrent_state_change`
  — mirrors `SyncCheckpointRecoveryView`'s own two-stage
  `not_running`/`concurrent_state_change` split.
- `failure_reason` on manual `failed` resolution is a distinct,
  clearly-labeled string ("Marked as failed by manual recovery (stuck
  in sending).") — mirrors `SyncCheckpoint`'s own
  `last_error = 'Marked as failed by manual recovery (possibly_stuck) —
  Phase 13.A.'` idiom, so this is visibly a manual correction, not an
  automated `SAFE_FAILURE_MESSAGE` outcome.
- `OutboundOperation` is deliberately **not** touched by this endpoint
  at all (no import, no write) — at the moment a recipient is claimed
  `sending`, no `OutboundOperation` row is necessarily linked to it yet
  (that FK is only ever set together with the recipient's own terminal
  write inside `dispatch_blast_recipient_task`), and the task's hard
  scope boundary forbids changing the `OutboundOperation`
  idempotency mechanism — leaving it alone entirely is the safest
  reading of that constraint.
- No Django-admin action was added (the "expected shape" offered either
  an admin action or an API endpoint) — the API endpoint is the
  primary, testable path, and it is also directly reusable from the
  frontend, which an admin-site custom action would not be.

No genuine architectural ambiguity requiring escalation was found —
Step 1 completed without a blocker.

## 3. Migration

**No migration was added or needed.** The fix reuses
`BlastRecipient.status`'s existing `sent`/`failed` choices,
`sent_at`, and `failure_reason` fields verbatim — no new column, no
new enum value. Confirmed via
`python manage.py makemigrations --check --dry-run` → `No changes
detected`.

## 4. Files Changed

**Backend (`backend/apps/blast/`)**
- `serializers.py` — added `BlastRecipientResolveSerializer` (`status`
  choice field, restricted to `sent`/`failed`).
- `views.py` — added `BlastRecipientResolveView`; imported
  `BlastRecipient` and `_maybe_finalize_campaign` (reused verbatim from
  `tasks.py`, not re-implemented).
- `urls.py` — added the `recipients/<int:recipient_id>/resolve/` route.
- `tests/test_views.py` — added `BlastRecipientResolveTests` (18 new
  test cases).
- `admin.py`, `models.py`, `tasks.py`, `bff_client.py`, `limits.py` —
  **unchanged**.

**Frontend**
- `frontend/src/lib/djangoApi.ts` — added `resolveBlastRecipient(campaignId,
  recipientId, status)`, following the existing
  `submitBlastCampaign`/`approveBlastCampaign`/`rejectBlastCampaign`
  request-function shape verbatim.
- `frontend/src/pages/BlastDetailPage.tsx` — added a minimal,
  admin-only ("system administration" scope, same inline
  `claims?.scopes.includes(...)` idiom already used on this page),
  confirm-gated ("Mark sent" / "Mark failed" buttons, reusing the
  existing `ConfirmDialog` component as-is) recovery control per
  `sending`-status recipient row. No new page, no new component, no
  new polling.
- `frontend/src/pages/BlastPage.css` — added one small rule
  (`.wa-blast-recipients__recovery-actions`) for the new button row's
  layout.

**Not touched**: `bff/` (the fix is entirely Django-side status/lifecycle
logic; the BFF dispatch mechanism itself was never buggy per the
audit), reconciliation/`possibly_stuck`/`SyncCheckpoint`/Celery-worker-
liveness code, `OutboundOperation`, the 60s throttle/cadence, any
dependency manifest.

## 5. Tests Added

All added to `backend/apps/blast/tests/test_views.py`,
`BlastRecipientResolveTests` (18 tests):

| Test | Step 3 requirement satisfied |
|---|---|
| `test_unauthenticated_request_is_rejected` | auth gating |
| `test_blast_scoped_user_without_admin_scope_is_forbidden` | admin-only gating |
| `test_unknown_campaign_returns_404` | error path |
| `test_unknown_recipient_returns_404` | error path |
| `test_recipient_belonging_to_a_different_campaign_returns_404` | error path / scoping |
| `test_invalid_status_value_is_rejected` | body validation (`pending`/`sending`/`skipped` rejected) |
| `test_admin_can_resolve_a_stuck_recipient_to_sent` | "recovered to `sent`" |
| `test_admin_can_resolve_a_stuck_recipient_to_failed` | "recovered to `failed`" (both paths) |
| `test_resolve_writes_an_audit_log_entry` | AuditLog requirement |
| `test_resolve_never_calls_the_bff_client` | "no duplicate send — BFF client never called during recovery" |
| `test_pending_recipient_cannot_be_resolved` | terminal/non-`sending` cannot be overwritten |
| `test_already_sent_recipient_cannot_be_overwritten_to_failed` | terminal cannot be overwritten |
| `test_already_failed_recipient_cannot_be_overwritten_to_sent` | terminal cannot be overwritten |
| `test_skipped_recipient_cannot_be_overwritten` | terminal cannot be overwritten |
| `test_concurrent_state_change_is_rejected_without_overwriting` | race/concurrent recovery — compare-and-set, mirrors `SyncCheckpointRecoveryViewTests`'s own concurrency test pattern |
| `test_resolving_the_last_stuck_recipient_completes_the_campaign` | campaign reaches `completed` once unwedged |
| `test_resolving_the_last_stuck_recipient_to_failed_when_all_others_failed_reaches_campaign_failed` | campaign reaches `failed` per existing all-failed rule |
| `test_resolving_a_stuck_recipient_when_others_still_pending_does_not_finalize` | finalization still respects other in-flight recipients |

Normal dispatch/claim/finalize flow: unaffected, confirmed by the
pre-existing 63 tests in `test_tasks.py`/`test_models.py`/`test_limits.py`
still passing unchanged.

## 6. Test-Suite Results

- **Targeted** — `docker compose -f infrastructure/development/office.yml
  exec backend python manage.py test apps.blast -v 1`
  (run via `docker exec development-backend-1 ...`) → **81/81 passed**
  (63 pre-existing + 18 new). Zero failures.
- **Full backend** — `docker exec development-backend-1 python manage.py
  test -v 1` → **426/426 passed**. Zero failures. (426 = 408 the prior
  audit's "known-good" full-suite count + 18 new tests added here; the
  408 baseline already included unrelated uncommitted Phase 13.B work
  present in the working tree before this task started.)
- **Frontend** — `npm run lint` (oxlint): 0 errors (pre-existing
  warnings only, in files this task did not touch:
  `StatusBadge.tsx`, `AuthContext.tsx`, `ThemeContext.tsx`).
  `npm run build` (`tsc -b && vite build`): succeeded, 0 TypeScript
  errors, build artifacts produced normally.
- **BFF** — not touched, `npm test` not re-run (no BFF-side change was
  made or needed; the audit already re-confirmed 120/120 passing BFF
  tests independent of this fix).

## 7. `manage.py check` / `makemigrations --check`

- `python manage.py check` → `System check identified no issues (0
  silenced).`
- `python manage.py makemigrations --check --dry-run` → `No changes
  detected`.

## 8. Git Diff Scope Confirmation

Only files genuinely needed for this narrow fix changed:
`backend/apps/blast/{serializers,views,urls}.py`,
`backend/apps/blast/tests/test_views.py`,
`frontend/src/lib/djangoApi.ts`,
`frontend/src/pages/BlastDetailPage.tsx`,
`frontend/src/pages/BlastPage.css`, plus this report. No file under
`apps/sync/`, `apps/operations/`, `bff/`, or any dependency manifest
(`package.json`/`requirements*.txt`) was touched. `backend/apps/blast/
models.py`, `tasks.py`, `admin.py`, `bff_client.py`, and `limits.py`
are unchanged.

## 9. FAIL Verdict

**The FAIL is CLOSED.**

Reasoning: the audit's finding had two parts — (a) an individual
recipient stuck in `sending` forever with no recovery path, and (b) the
compounding consequence that this permanently blocks the campaign from
reaching any terminal status. Both are now addressed:

- (a) An admin can now call
  `POST /api/blast/campaigns/<pk>/recipients/<recipient_id>/resolve/`
  (or use the new "Mark sent"/"Mark failed" buttons on
  `BlastDetailPage.tsx`) to move a `sending` recipient to a terminal
  status, with compare-and-set protection against overwriting a
  concurrent legitimate completion or a second recovery attempt, and an
  `AuditLog` entry recording who did it and when.
- (b) That same action calls `_maybe_finalize_campaign` (reused
  verbatim), so a campaign wedged solely by one stuck recipient can now
  reach `completed`/`failed` immediately after recovery — verified
  directly by
  `test_resolving_the_last_stuck_recipient_completes_the_campaign` and
  its `failed`-path counterpart.

What remains true/unresolved after this fix (explicitly out of scope,
not claimed as fixed):
- The recipient's **true delivery status in that ambiguous window
  remains fundamentally unknowable through this system** — this fix
  gives an operator a way to *record* an outcome they determined
  externally, it does not and cannot determine the outcome itself
  (querying WAHA/reconciliation was explicitly out of scope).
- No automatic retry of failed/stuck sends was added (decision 5/6
  unchanged).
- No automatic resume/periodic sweep was added — recovery is 100%
  manual, human-triggered (decision 6 unchanged).
- The Celery `acks_late`/redelivery threat-model documentation mismatch
  (audit Section 3, finding #2) is **untouched** — still present,
  still not this task's scope.
- The BFF network-exposure finding (audit Section 7, finding #3,
  `OFFICE_DISPATCH_SERVICE_KEY` as the sole verifiable defense for
  `/internal/blast/send`) is **untouched** — still present, still not
  this task's scope.
- `BlastRecipient.STATUS_SKIPPED` remains unreachable by any code path
  (unrelated pre-existing gap, unchanged by this task).

## 10. Safety Confirmations

- **No real WhatsApp message was sent** and **no live dispatch was
  exercised** at any point during design, implementation, or
  verification. All test coverage uses Django's `APITestCase`/`TestCase`
  against the test database, with `send_blast_message`
  mocked/asserted-not-called where relevant
  (`test_resolve_never_calls_the_bff_client`). No `curl`/live HTTP call
  was made against the BFF or any WAHA instance.
- **Reconciliation, `possibly_stuck`, `SyncCheckpoint`, and
  Celery-worker-liveness code were not touched** — confirmed by the
  git diff scope in Section 8 (no file under `apps/sync/` changed).
- **The 60-second inter-message throttle/cadence was not changed** —
  `BLAST_INTER_MESSAGE_DELAY_SECONDS`, `schedule_blast_campaign_task`,
  and its throttling logic in `tasks.py` are byte-for-byte unchanged.
- **The `OutboundOperation` idempotency mechanism was not changed** —
  `operations/models.py` is untouched; the new endpoint never imports
  or references `OutboundOperation` at all.
