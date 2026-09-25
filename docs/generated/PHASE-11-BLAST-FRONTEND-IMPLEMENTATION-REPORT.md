# Phase 11 — Blast Frontend Implementation Report

## 1. Objective

Build the frontend for Phase 11 "Blast" (controlled bulk WhatsApp send) on
top of the already-complete, already-tested backend
(`backend/apps/blast/`) and the BFF's internal dispatch endpoint
(`bff/src/routes/internalBlast.ts`), both from a prior task in this
session. This task is frontend-only: `backend/`, `bff/`, and
reconciliation/`possibly_stuck`/`SyncCheckpoint`/Celery-liveness/recovery
code were not touched.

## 2. Step 0 — verified API contract (source-of-truth, not the reports)

Read directly from source, not paraphrased from
`docs/generated/PHASE-11-BLAST-*-REPORT.md` (both skimmed for narrative
only):

- `backend/apps/blast/models.py`
- `backend/apps/blast/serializers.py`
- `backend/apps/blast/views.py`
- `backend/apps/blast/urls.py`
- `backend/config/urls.py`
- `backend/apps/blast/limits.py`
- `backend/apps/authn/permissions.py`
- `backend/config/settings.py` (BLAST_* env vars)

**Endpoints** (mounted at `/api/blast/` — `backend/config/urls.py:28`,
`backend/apps/blast/urls.py:11-17`), all `JWTAuthentication`:

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/api/blast/campaigns/` | `HasBlastScope \| HasSystemAdministrationScope` | `views.py:60-69` |
| POST | `/api/blast/campaigns/` | `HasBlastScope` | `views.py:61-83` |
| GET | `/api/blast/campaigns/:pk/` | `HasBlastScope \| HasSystemAdministrationScope` | `views.py:86-100` |
| POST | `/api/blast/campaigns/:pk/submit/` | `HasBlastScope`, creator-only (403 otherwise) | `views.py:103-135` |
| POST | `/api/blast/campaigns/:pk/approve/` | `HasSystemAdministrationScope`, not-creator (403), daily-budget check (409) | `views.py:138-198` |
| POST | `/api/blast/campaigns/:pk/reject/` | `HasSystemAdministrationScope`, **no** creator restriction | `views.py:201-235` |

**Request/response shapes** (VERIFIED against `serializers.py`):
- `BlastRecipientSerializer` (`:9-13`): `id, destination, status,
  scheduled_for, sent_at, failure_reason` — all read-only.
- `BlastCampaignListSerializer` (`:70-84`): `id, session` (name string,
  not FK id), `name, status, recipient_count` (a `SerializerMethodField`
  — **not** a stored column), `created_by, approved_by` (usernames),
  `approved_at, created_at, updated_at`.
- `BlastCampaignDetailSerializer` (`:87-91`): list fields +
  `message_template, rejected_reason, recipients[]`.
- `BlastCampaignCreateSerializer` (`:16-67`): request body
  `{session (name string), name, message_template, recipients (string[])}`,
  cap `settings.BLAST_MAX_RECIPIENTS_PER_CAMPAIGN` enforced in
  `validate_recipients` (`:45-58`), response is the *detail* shape
  (`views.py:83`).
- `BlastCampaignRejectSerializer` (`:94-95`): `reason` is
  `required=False, allow_blank=True, default=''` — **optional**.

**Resolved before designing UI, per Step 0's checklist:**
- **No file-upload endpoint** anywhere in `apps/blast/urls.py` —
  `recipients` is JSON array of strings only. `frontend/package.json` has
  no CSV/Excel library, so none was added; the create page lets the
  operator pick a local `.csv`/`.txt` file, reads it client-side
  (`file.text()`), and hand-parses it (newline- and comma-separated) into
  the same string array the JSON API already expects. **Binary `.xlsx`
  import was NOT implemented** — no parsing library is a dependency and
  none was added, per the task's explicit constraint.
- **Reject reason is optional**, not required — the UI's reject dialog
  has an optional "Reason" textarea, never a mandatory field.
- **Per-recipient fields actually returned**: `destination, status,
  scheduled_for, sent_at, failure_reason` — exactly what
  `BlastDetailPage.tsx`'s recipient table renders, nothing invented.
- **Campaign timestamps actually returned**: `created_at, approved_at,
  updated_at`. **There is no submitted/sending/completed/failed
  timestamp column** on `BlastCampaign` (`models.py:71-86` — only
  `TimeStampedModel`'s `created_at`/`updated_at` plus `approved_at`).
  `BlastDetailPage.tsx` shows `created_at`, `approved_at`, and
  `updated_at` (labeled "Last updated") — it does **not** fabricate a
  submitted/sending/completed/failed timestamp. This is a gap between the
  task's requested field list and the real contract.
- **No idempotency_key field is ever serialized** — it's a derived
  `@property` on `BlastRecipient` (`models.py:158-164`), confirmed not a
  stored/returned column. Nothing in the frontend references it.
- **No limits/OPTIONS endpoint** exposes `BLAST_MAX_RECIPIENTS_PER_CAMPAIGN`
  (100) / `BLAST_MAX_RECIPIENTS_PER_SESSION_PER_DAY` (500) /
  `BLAST_INTER_MESSAGE_DELAY_SECONDS` (60s) dynamically
  (`backend/config/settings.py:317-319`). These are shown as **static,
  hardcoded UI copy** (sourced from `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`
  item 12, which matches the settings.py defaults), explicitly labeled in
  the banner text as "not fetched dynamically" so it can't be mistaken for
  a live value if a deployment overrides the env vars.
- **No session-listing endpoint exists anywhere in this project**
  (`backend/apps/waha_sessions/` has no `urls.py`/`views.py` at all — not
  Blast-specific, this is a project-wide single-session assumption already
  relied on by `InboxPage.tsx`/`SessionsPage.tsx`/`DashboardPage.tsx` via
  `config.wahaSessionName`). The "session picker" in scope item 2 is
  therefore the single configured session shown as read-only context
  (matching every other page's existing convention), not a dropdown over
  multiple sessions — there is nothing to pick from.

No genuine blocker was found — every scope item was buildable against the
real contract; the items above are gaps, not blockers, and are handled per
the task's own guidance (build to what's real, note the gap).

## 3. Files created

- `frontend/src/pages/BlastListPage.tsx` — campaign list.
- `frontend/src/pages/BlastCreatePage.tsx` — draft creation form.
- `frontend/src/pages/BlastDetailPage.tsx` — detail + workflow actions +
  recipient table.
- `frontend/src/pages/BlastPage.css` — shared styles for the three pages
  above (one file, not three, since all three are the same feature and
  share the same list-row/field/banner vocabulary — no new CSS framework,
  reuses the existing design tokens verbatim).

## 4. Files changed

- `frontend/src/lib/djangoApi.ts` — added `BlastCampaignStatus`,
  `BlastRecipientStatus`, `BlastRecipient`, `BlastCampaignListItem`,
  `BlastCampaignDetail` types and `getBlastCampaigns`,
  `getBlastCampaign`, `createBlastCampaign`, `submitBlastCampaign`,
  `approveBlastCampaign`, `rejectBlastCampaign` functions — same
  `request()`/`ApiResult`/`authHeader()` conventions as every existing
  function in the file.
- `frontend/src/components/ui/StatusBadge.tsx` — added
  `mapBlastCampaignStatus` and `mapBlastRecipientStatus`, following the
  exact pattern of the existing `mapWahaStatus`/`mapSyncStatus`/
  `mapActivityResult` (never invents a status the backend didn't report;
  unrecognized falls back to `'unknown'`).
- `frontend/src/routes/AppRoutes.tsx` — added `/blast`, `/blast/new`,
  `/blast/:id` routes, each wrapped in the existing `ProtectedRoute`.
- `frontend/src/components/layout/Sidebar.tsx` — added a "Blast" nav
  entry (Megaphone icon) between Sessions and Reports, unconditional for
  every authenticated user (matching every other nav item — scope gating
  happens inline within the pages, same as Inbox's recovery button).

No other file was touched. `backend/`, `bff/`, Docker/Compose, and
`package.json`/`package-lock.json` are untouched by this task (verified
via `git diff --stat` below — the backend/bff/docs changes present in
`git status` predate this task, from the prior session's backend/BFF
work).

## 5. What was built, per scope item

1. **Blast list page** (`BlastListPage.tsx`) — fetch-on-mount via
   `getBlastCampaigns()`, no polling. Shows name, session, status
   (`StatusBadge` + `mapBlastCampaignStatus`), recipient count, created
   by, created at, as clickable rows into the detail page. "New campaign"
   action shown only when the JWT carries the `'blast'` scope (inline
   `claims?.scopes.includes(...)` check, same idiom as `InboxPage.tsx`).
2. **Create campaign** (`BlastCreatePage.tsx`) — session shown read-only
   (`config.wahaSessionName`, no picker — see Step 0), name field,
   message template textarea, recipient textarea (one per line or
   comma-separated) with an "Import .csv/.txt" file picker that appends
   parsed lines into the same textarea (single source of truth for what's
   submitted), a live parsed/deduped recipient count and preview list,
   client-side validation mirroring the 100-recipient cap (disables
   submit, shows an inline error) — explicitly a UX courtesy, the server
   remains authoritative (documented in both the code comment and
   `createBlastCampaign`'s docstring). A static limits banner states the
   100/campaign, 500/day/session, and 60-second throttle, labeled as
   non-dynamic copy.
3. **Workflow UI** — draft → submit → pending_approval → approve/reject →
   approved → sending/completed/failed is fully represented via
   `BlastCampaignStatus` badges and the detail page's conditional action
   buttons. Approve/Reject are visible only for
   `'system administration'`-scoped users (same inline idiom). Self-approval
   is hidden client-side (`isCreator` computed by comparing
   `GET /api/auth/me/`'s `username` against `campaign.created_by`, the
   only usernames the API actually exposes) as a UX courtesy on top of the
   server's own 403 check (`views.py:161-162`).
4. **Reject flow** — a reason field is included because Step 0 confirmed
   the API accepts (optional) `reason`. `ConfirmDialog` itself has no
   slot for extra form content, so the reject dialog is built directly
   from `Modal` + `Button` — the same idiom `SessionsPage.tsx`'s
   `PairingModal` already uses for a dialog that needs input fields beyond
   a plain confirm/cancel. Approve uses `ConfirmDialog` verbatim (as the
   sync-recovery flow does), with `variant="primary"` since approving
   isn't destructive.
5. **Campaign detail page** (`BlastDetailPage.tsx`) — campaign info,
   message template, recipient table (destination, status, scheduled_for,
   sent_at, failure_reason — exactly the real serializer fields, nothing
   fabricated), and a "Dispatch progress" row of counts
   (sent/failed/sending/pending/skipped) computed client-side from the
   real `recipients[]` array — not a progress bar.
6. **UX constraints** — reused `StatusBadge`, `Card`, `PageHeader`,
   `ConfirmDialog`, `ErrorState`, `LoadingState`, `EmptyState`, `Button`,
   `Input`, `Modal` verbatim; no new base component was created. No new
   polling was added (fetch-on-mount + manual refetch only, matching the
   task's explicit preference and this codebase's established reluctance
   to add polling without justification).

## 6. Explicit list of requested items NOT implemented (API/contract gaps)

- **Binary `.xlsx` import** — not implemented. No parsing library is a
  frontend dependency; one was not added per the task's constraint. CSV/
  plain-text (newline- or comma-separated) import is implemented instead.
- **Submitted/sending/completed/failed timestamps** — not shown, because
  they don't exist on `BlastCampaign`. Only `created_at`, `approved_at`,
  and `updated_at` are real and shown.
- **Multi-session picker** — not implemented as a dropdown; there is no
  session-listing endpoint anywhere in the backend (not blast-specific).
  The single configured session is shown as fixed context instead, same
  as every other page in this app.
- **Dynamic limits (100/500/60s) from the API** — not available from any
  endpoint; shown as static, explicitly-labeled UI copy instead.

## 7. Lint / build / tests

- `npm run lint` (`oxlint`): passes, **no errors**. Two additional
  warnings of the pre-existing `react(only-export-components)` class
  appear in `StatusBadge.tsx` (for the two new exported mapper functions)
  — the same warning type this file already had 3 of before this change,
  not a new class of issue.
- `npm run build` (`tsc -b && vite build`): passes, zero TypeScript/build
  errors.
- No frontend test runner exists in this project (`frontend/package.json`
  has no `test` script and no `jest`/`vitest`/`@testing-library`
  dependency) — re-verified directly; none was added.

## 8. Git diff summary

Frontend files only:

```
 frontend/src/components/layout/Sidebar.tsx |   3 +-
 frontend/src/components/ui/StatusBadge.tsx |  65 ++++++++-
 frontend/src/lib/djangoApi.ts              | 176 ++++++++++++++
 frontend/src/routes/AppRoutes.tsx          |  27 +++
 (new) frontend/src/pages/BlastListPage.tsx
 (new) frontend/src/pages/BlastCreatePage.tsx
 (new) frontend/src/pages/BlastDetailPage.tsx
 (new) frontend/src/pages/BlastPage.css
```

`InboxPage.tsx`/`InboxPage.css` and the `backend/`/`bff/`/`docs/` changes
visible in `git status` are unmodified by this task — they were already
present (uncommitted) from the prior session's Phase 13.B and Blast
backend/BFF work. `package.json`/`package-lock.json` in any workspace were
not touched.

## 9. Known limitations

- The "New campaign" nav action and list-page button are hidden for
  non-`'blast'`-scoped users, but the `/blast/new` route itself has no
  route-level scope guard (only `ProtectedRoute`'s `isAuthenticated`
  check) — consistent with every other route in this app (none are
  scope-guarded at the route level; the server's 403 is the real
  boundary, surfaced via the existing `ErrorState`/`ApiError` taxonomy).
- `isCreator`/self-approval hiding depends on `GET /api/auth/me/`
  resolving before the detail page's action buttons render correctly;
  until it resolves, Submit/Approve buttons are conservatively hidden
  (brief flash), matching the same trade-off `Sidebar.tsx` already makes
  for the display name.
- The recipient table has no pagination; campaigns are capped at 100
  recipients server-side, so this was not needed.

## 10. Backend/BFF/reconciliation code confirmation

Not touched. `git diff --stat` (full repo) shows only the files listed in
Section 4/8 above under `frontend/`; no file under `backend/`, `bff/`,
`infrastructure/`, or any reconciliation/`possibly_stuck`/
`SyncCheckpoint`/Celery-liveness/recovery path was modified by this task.

## 11. Claim classification

- **VERIFIED** (read directly from source this session): all endpoint
  paths/methods/permissions, all serializer fields, the reject reason's
  optionality, the absence of a file-upload endpoint, the absence of a
  session-listing endpoint, the absence of submitted/sending/completed/
  failed timestamp columns, the absence of a stored `idempotency_key`,
  the BLAST_* settings defaults and their non-exposure via any endpoint,
  lint/build results (both run this session).
- **INFERRED**: that `GET /api/auth/me/`'s `username` is the correct and
  only available signal for "is this the campaign's creator" (the JWT's
  own `sub` claim is the user's numeric PK, not comparable to
  `created_by`, which the serializer exposes only as a username string —
  this inference follows directly from those two verified facts, but was
  not confirmed against a live approval performed by two different real
  accounts in this session).
- **NOT VERIFIED**: no real WhatsApp message was sent and no live
  approve/reject/submit action was exercised against a running
  backend/BFF/WAHA stack in this session (explicitly out of scope — "do
  not send any real WhatsApp message during testing"); correctness rests
  on `tsc`/`oxlint` passing and on reading the backend's own (separately
  tested) source, not on an end-to-end run.
