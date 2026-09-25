# Phase 9.1A — Sync Status Read Endpoint — Implementation Report

**Scope of this task.** Backend implementation only, exactly the slice
scoped as "Phase 9.1A" in `docs/generated/PHASE9-1A-DESIGN-AUDIT-REPORT.md`.
`reconcile_session()`, the Celery/Redis setup, webhook ingestion,
`WahaSession` lifecycle, Inbox polling, and Phase 9.0/9.1D's own frontend
changes were all read where relevant but **not modified**. No migration was
created. No live write, WAHA call, or WhatsApp message occurred at any
point. Phase 9.1B/C/E/F/G were not started.

---

## 1. Pre-implementation verification (re-confirmed directly, not assumed from the design report)

Before writing any code, the design report's four load-bearing claims were
re-checked against the current source:

1. **`WahaSession` is the source-of-truth list of sessions** — confirmed:
   `apps/webhooks/services.py:40` and `apps/operations/views.py:61` are the
   only two `WahaSession.objects.get_or_create(...)` call sites in the
   codebase; reconciliation never creates one.
2. **`reconcile_session()` uses `WahaSession.objects.get()`, not
   `get_or_create()`** — confirmed, `apps/sync/reconciliation.py:171`
   (unchanged, re-read, not edited).
3. **`SyncCheckpoint.session` is a reverse `OneToOneField`, whose accessor
   raises `DoesNotExist` rather than returning `None`** — confirmed by
   reading `apps/sync/models.py:25` (`related_name='sync_checkpoint'`) and
   Django's own reverse-descriptor semantics; the new view therefore never
   uses `session.sync_checkpoint` — see Section 6.
4. **This is operational state, not conversation content** — confirmed by
   re-reading both `apps/chats/views.py` (JWT + `IsAuthenticated` +
   `HasReadingScope`) and `apps/dashboard/views.py` (JWT +
   `IsAuthenticated` only) side by side; the endpoint follows the
   Dashboard precedent (Section 3).

**App-placement decision, made and documented before coding (per the
task's instruction), not left ambiguous**: a new `apps/sync/views.py` +
a new URL mount (`api/sync/`), not folded into `apps.dashboard`. Reasoning:
every other domain-owned model in this project exposes its own HTTP surface
from within its own app (`apps.chats` → `Chat`/`Message`, `apps.operations`
→ `OutboundOperation`, `apps.audit` → `AuditLog`) — `apps.dashboard` is the
one deliberate exception, and its own module docstring explains why: *"the
activity feed reads from two unrelated apps' models, so it doesn't belong to
either one specifically."* That reasoning does not apply here —
`SyncCheckpoint` belongs entirely to `apps.sync`, with no cross-app
aggregation needed, so keeping its read endpoint inside `apps.sync` (the
same app that already owns `reconciliation.py`, `executors.py`,
`tasks.py`, `models.py` for this exact data) is the more consistent choice,
not a personal preference. No ambiguity was found that materially affected
the API contract itself (method, path shape, response fields), so
implementation proceeded without stopping to ask, per the task's own
instruction.

---

## 2. Endpoint created

**`GET /api/sync/status/<session_name>/`**

- **Method**: `GET` only.
- **Shape**: per-session detail (not a collection) — `<session_name>` is a
  path parameter, matching the task's own concrete test requirement
  ("session yang tidak ada -> response error yang konsisten"), which
  implies a per-session identifier in the URL. This is a deliberate,
  documented deviation from the design report's earlier "collection-only"
  suggestion — the design report itself flagged that as an open question
  (Section 9), and this task's own more concrete API-contract description
  (via its exact test-case list) resolved it in favor of a detail route.
  Not treated as a material ambiguity requiring a stop, since the task's
  own text supplied enough signal to derive the intended shape.
- **Never touches WAHA, Redis, or Celery, and never triggers
  reconciliation** — the view performs exactly two `SELECT`s against
  Django's own database and nothing else (Section 6).

---

## 3. Implementation location

| File | Status | Purpose |
|---|---|---|
| `backend/apps/sync/views.py` | **New** | `SyncStatusView` + the derivation helpers. Deliberately named `views.py`, distinct from the existing `internal_views.py` (BFF-only, `HasInternalServiceKey`-gated) — the naming itself now documents the auth-boundary split this app has. |
| `backend/apps/sync/api_urls.py` | **New** | The URL list for this frontend-facing surface, kept separate from `apps/sync/urls.py` (which remains exactly as it was — mounted at `/internal/`, internal-key semantics only, untouched). |
| `backend/config/urls.py` | **Modified, 1 line added** | `path('api/sync/', include('apps.sync.api_urls'))`, inserted alongside the other `api/<domain>/` mounts, immediately after `api/chats/` and before the `internal/` block — placement mirrors the existing grouping (public `api/` routes first, `internal/` routes last). |

No existing file's behavior was changed — `apps/sync/urls.py`,
`apps/sync/reconciliation.py`, `apps/sync/executors.py`,
`apps/sync/tasks.py`, `apps/sync/models.py` are all byte-for-byte unchanged
(confirmed by `git diff --stat`, Section 10).

---

## 4. Authentication / permission used, and why

```python
authentication_classes = [JWTAuthentication]
permission_classes = [IsAuthenticated]
```

Matches `apps/dashboard/views.py`'s `MessagesStatsView`/`ActivityFeedView`
exactly — **no** `HasReadingScope` gate. Reasoning, per the pre-verification
in Section 1: `HasReadingScope` (`apps/authn/permissions.py`) exists
specifically to gate **conversation content** (its own docstring: "the
chat/message read and mark-as-read endpoints require the JWT's `reading`
scope"). Sync status is operational/system state, the same *kind* of data
`MessagesStatsView`/`ActivityFeedView` already expose without any scope
check — extending `reading` to cover it would stretch that scope's
documented meaning without a basis found anywhere in `docs/06-SECURITY.md`'s
named authorization concerns. `HasInternalServiceKey` was never a candidate
— it authenticates the BFF *process*, not an end user's browser (its own
docstring, `apps/core/internal_auth.py:1-8`), and this endpoint's entire
purpose is to be called directly by an authenticated browser, matching the
`/api/chats/`/`/api/dashboard/...` Frontend→Django-direct precedent.

No `HasReadingScope`-strength justification was found in the current
security model, so per the task's explicit instruction ("Jangan menambahkan
HasReadingScope kecuali ditemukan alasan kuat"), it was not added.

---

## 5. Response schema

```json
{
  "session": "no_epahari",
  "sync_status": "healthy",
  "checkpoint_status": "ok",
  "last_run_at": "2026-09-25T10:00:00Z",
  "seconds_since_last_run": 320,
  "checkpoint_updated_at": "2026-09-25T10:00:00Z"
}
```

- `session` — `WahaSession.name`, verbatim.
- `sync_status` — the derived five-state value (Section 6).
- `checkpoint_status` — the **raw** stored `SyncCheckpoint.status` value
  (`idle`/`running`/`ok`/`error`), `null` when no checkpoint row exists.
  Included for transparency, matching this project's own established
  preference for exposing raw system values alongside interpreted ones
  (the same reasoning `WahaSession.status`'s own docstring gives).
- `last_run_at` / `checkpoint_updated_at` — timezone-aware, UTC,
  ISO-8601-with-`Z`, manually formatted via a small `_isoformat()` helper
  that **matches the exact existing convention** already used twice in this
  codebase (`apps/dashboard/views.py`'s `MessagesStatsView`/`ActivityFeedView`
  both manually call `.isoformat()` + replace `+00:00` with `Z` rather than
  relying on implicit datetime-to-JSON encoding) — this endpoint follows
  that precedent rather than introducing a different one.
- `seconds_since_last_run` — server-computed
  `int((timezone.now() - last_run_at).total_seconds())`, `null` when
  `last_run_at` is `null`.
- **Deliberately excluded**: `lag_seconds` (never written anywhere in this
  codebase — re-confirmed by grep immediately before coding — would always
  be `null`, excluded per the task's explicit instruction); `last_error`
  (raw error text — excluded per `apps/core/exceptions.py`'s established,
  project-wide discipline of never surfacing raw internal error text
  through a standard API response, applied consistently here); any
  webhook-derived or Redis/Celery-derived field (both explicitly out of
  scope per the task's instruction — nothing in the current source proves
  either is available to this endpoint, so neither was assumed).

**HTTP status codes**:
- `200` — for every `sync_status` value, including `never_synced`/`stale`/
  `failed` — this endpoint only ever performs a successful *read* of
  already-stored Django state; a "bad" status value is data, not a request
  failure (deliberately different from `DatabaseHealthView`'s `503`-on-failure
  pattern, which checks a *live* dependency).
- `404` — an unknown `session_name` (via `get_object_or_404(WahaSession,
  name=session_name)`, the exact same pattern `ChatMessagesView`/
  `ChatMarkReadView` already use for an unknown chat `pk`), automatically
  wrapped in the project's standard `{"error": {"code", "message",
  "request_id"}}` envelope by the global `apps.core.exceptions.api_exception_handler`
  — no custom error-handling code was written.
- `401` — no/invalid JWT, automatic (same global handler).

---

## 6. State definitions

Implemented in `_derive_sync_status()` (`apps/sync/views.py`), computed
**entirely** from `SyncCheckpoint.status` + `last_run_at` — `lag_seconds`
is never read, and no `possibly_stuck` (or any other invented) state was
added, per the task's explicit instruction.

| `sync_status` | Condition |
|---|---|
| `never_synced` | No `SyncCheckpoint` row exists for the session at all (`SyncCheckpoint.objects.filter(session=session).first()` returns `None`). |
| `running` | `checkpoint.status == 'running'` **or** `checkpoint.status == 'idle'`. |
| `failed` | `checkpoint.status == 'error'` — takes priority over any staleness calculation, regardless of how old the failed attempt is (verified by `test_old_error_checkpoint_still_reports_failed_not_stale`). |
| `healthy` | `checkpoint.status == 'ok'` and `seconds_since_last_run <= threshold` (Section 7). |
| `stale` | `checkpoint.status == 'ok'` and `seconds_since_last_run > threshold`. |

**A deliberate, documented choice not explicitly spelled out in the design
report**: `STATUS_IDLE` (the model's default) is grouped with `running`,
**not** with `never_synced`, even though no code path in this project
leaves a checkpoint observably in that state in practice
(`reconcile_session()` advances a freshly `get_or_create()`'d checkpoint
straight to `STATUS_RUNNING` within the same call, before any other reader
could see `'idle'`). The reasoning, made explicit in the code's own
docstring: the task's own definition ties `never_synced` specifically to
*no row existing* — an `idle` checkpoint row genuinely exists, so labeling
it `never_synced` would contradict that definition; "a reconciliation
attempt has been initiated but not yet observed to progress" is the closer
description, hence grouped with `running`. Covered by its own test
(`test_idle_checkpoint_is_grouped_with_running_not_never_synced`).

**No `possibly_stuck` boolean was added** for a long-`running` checkpoint,
per the task's explicit instruction — the raw `checkpoint_updated_at` field
is exposed instead (Section 5), letting a future consumer judge for
themselves without this endpoint asserting an unprovable fact.

---

## 7. Staleness threshold, and why

```python
STALE_THRESHOLD_MULTIPLIER = 2
threshold_seconds = settings.RECONCILIATION_INTERVAL_SECONDS * STALE_THRESHOLD_MULTIPLIER
```

**Derivation, not an arbitrary number**: `RECONCILIATION_INTERVAL_SECONDS`
(`backend/config/settings.py`, default `900` = 15 minutes) is the
project's own already-configured periodic-reconciliation cadence — the
threshold is defined as a **multiple of this existing setting**, not an
independent value, so it automatically tracks whatever interval a given
environment actually runs, in both dev and production, with no second knob
to keep in sync.

**Why 2×, not a new environment variable**: missing exactly one periodic
cycle can be ordinary scheduling jitter (Celery beat/worker timing, a
momentarily busy worker); missing two consecutive cycles is a materially
stronger signal that periodic reconciliation has actually stopped
advancing. This mirrors the same "wait for repeated misses before
declaring degraded" philosophy already implemented and reported for the
frontend's own connectivity indicator
(`frontend/src/pages/InboxPage.tsx`'s `CONNECTIVITY_FAILURE_THRESHOLD = 2`,
Phase 9.1D) — a deliberately consistent choice across both signals, not a
coincidence. Hardcoded as a Python constant in the view module rather than
a new setting, matching this project's own precedent for this *kind* of
value (`apps/sync/executors.py`'s `MAX_ATTEMPTS`/`RETRY_DELAY_SECONDS` are
hardcoded constants for the same reason — a display/behavior judgment call,
not a genuine per-environment infrastructure choice like
`RECONCILIATION_INTERVAL_SECONDS`/`RECONCILIATION_EXECUTOR` themselves are).

This was judged derivable from the existing system (an explicit interval
already exists; a small integer multiplier for hysteresis is a standard,
justifiable engineering default, not a business/operational policy like a
budget or SLA figure) — so, per the task's own conditional instruction,
implementation proceeded without stopping to ask. The exact multiplier
remains a one-line constant, trivially adjustable if `2` turns out not to
match your operational expectations.

---

## 8. Handling a session with no checkpoint

`SyncCheckpoint.objects.filter(session=session).first()` — a plain filter,
**never** the reverse-OneToOne accessor `session.sync_checkpoint`, which
(per Section 1's pre-verification) raises `SyncCheckpoint.DoesNotExist`
instead of returning `None`. `.first()` returns `None` cleanly for a
session that has never been reconciled, and every field in the response is
computed to gracefully handle that `None` (`checkpoint_status`,
`last_run_at`, `seconds_since_last_run`, `checkpoint_updated_at` all become
`null`; `sync_status` becomes `'never_synced'`) — no exception, no special
control flow needed. Verified by
`test_session_with_no_checkpoint_is_never_synced`.

---

## 9. Query / performance

- **Exactly 2 database queries per request**, regardless of whether a
  checkpoint exists: one `WahaSession` lookup (`get_object_or_404`), one
  `SyncCheckpoint` lookup (`.filter().first()`). No
  `select_related`/`prefetch_related` needed — there is no related-object
  serialization here (unlike `ChatListView`'s `Contact` join). Verified
  directly by `test_query_count_is_bounded_no_n_plus_one`, using the exact
  same `CaptureQueriesContext` tool `ChatListViewTests` already uses.
- **No query to WAHA** — confirmed by construction: the view imports only
  `apps.sync.models` and `apps.waha_sessions.models`, never
  `apps.sync.waha_client` or `apps.sync.reconciliation`.
- **No index was added to `SyncCheckpoint`** — none was needed; the model
  has no index beyond the implicit `OneToOneField` uniqueness, and at this
  project's expected scale (1, "kemungkinan maksimal 2–3" sessions per
  `docs/00-MASTER-SPEC.md`) a full table scan touches at most a handful of
  rows, matching the same "acceptable at current scale" reasoning already
  documented for `MessagesStatsView`/`ActivityFeedView`'s own unindexed
  queries.

---

## 10. Tests added

`backend/apps/sync/tests/test_views.py` — new file, 15 tests, following the
exact `APITestCase` + `@override_settings(JWT_PRIVATE_KEY=..., JWT_PUBLIC_KEY=...)`
pattern already established in `apps/chats/test_views.py` (same
`generate_test_key_pair()`/`issue_access_token()` helpers). Additionally
overrides `RECONCILIATION_INTERVAL_SECONDS=900` for deterministic threshold
math, independent of whatever value the real environment happens to have
configured.

| Test | Covers |
|---|---|
| `test_unauthenticated_request_is_rejected` | 401 with no token |
| `test_authenticated_request_succeeds_with_no_scope_required` | a plain user with no Group/scope succeeds (confirms `IsAuthenticated`-only, not `HasReadingScope`) |
| `test_session_with_no_checkpoint_is_never_synced` | Section 8, all fields `null` |
| `test_running_checkpoint_reports_running` | `status='running'`, `last_run_at=None` (first-run-in-progress edge case) |
| `test_running_checkpoint_after_a_prior_completed_run_still_reports_running` | `status='running'` with a non-null `last_run_at` from a prior completed run |
| `test_idle_checkpoint_is_grouped_with_running_not_never_synced` | Section 6's explicit grouping decision |
| `test_error_checkpoint_reports_failed` | plus asserts `last_error` is never present in the response |
| `test_old_error_checkpoint_still_reports_failed_not_stale` | `failed` takes priority over staleness, regardless of age |
| `test_recent_ok_checkpoint_within_threshold_is_healthy` | |
| `test_ok_checkpoint_at_exactly_the_threshold_is_healthy` | boundary-inclusive (`<=`) |
| `test_old_ok_checkpoint_beyond_threshold_is_stale` | |
| `test_checkpoint_updated_at_is_returned` | value + exact `Z`-suffixed ISO-8601 format match |
| `test_last_run_at_is_timezone_aware_utc_iso8601` | |
| `test_unknown_session_returns_404_with_standard_error_envelope` | 404 + the project's standard `{"error": {...}}` shape |
| `test_query_count_is_bounded_no_n_plus_one` | Section 9 |

All 10 of the task's explicitly requested checklist items are covered
(items 1–8 map 1:1 to the table above; item 9 is
`test_unknown_session_returns_404...`; item 10 is
`test_query_count_is_bounded_no_n_plus_one`).

---

## 11. Verification results

All run against `DJANGO_SETTINGS_MODULE=config.settings_test` — this
project's own pre-existing, documented SQLite-in-memory test-settings
module (`backend/config/settings_test.py`, not created or modified by this
task), used because the real configured PostgreSQL user lacks `CREATEDB`
privilege in this environment (confirmed directly: `manage.py test` against
the default settings failed with `permission denied to create database`,
a pre-existing environment limitation this task did not cause and is not
responsible for fixing — the settings module's own docstring names exactly
this scenario as its reason to exist: *"when no PostgreSQL instance is
reachable... Invoke explicitly and only for this purpose"*).

- **`manage.py test apps.sync.tests.test_views`**: **15/15 passed.**
- **`manage.py test` (full suite)**: **287/287 passed, 0 failures.** This
  is the strongest available evidence that nothing outside this task's
  three new/changed files regressed — including every existing
  reconciliation, webhook, session-management, identity, and internal-auth
  test.
- **`manage.py check`**: `System check identified no issues (0 silenced).`
- **`manage.py makemigrations --check --dry-run`**: `No changes detected.`
  — confirms this implementation introduces **no** model/schema change,
  consistent with the design (no new model, no field added to
  `SyncCheckpoint`).

---

## 12. Files changed — final scope

```
$ git status --short
 M backend/config/urls.py
 M frontend/src/pages/InboxPage.css
 M frontend/src/pages/InboxPage.tsx
?? backend/apps/sync/api_urls.py
?? backend/apps/sync/tests/test_views.py
?? backend/apps/sync/views.py
?? docs/generated/... (this report and prior Phase 9 audit reports)

$ git diff --stat
 backend/config/urls.py           |   1 +
 frontend/src/pages/InboxPage.css |  31 ++++++++++
 frontend/src/pages/InboxPage.tsx | 125 +++++++++++++++++++++++++++++++++------
 3 files changed, 140 insertions(+), 17 deletions(-)
```

The `InboxPage.tsx`/`.css` lines are **entirely Phase 9.0/9.1D's own,
already-completed, already-reported changes** — untouched by this task
(re-confirmed: this task never opened either file). This task's own diff is
exactly: `backend/config/urls.py` (+1 line) plus three new files
(`backend/apps/sync/views.py`, `backend/apps/sync/api_urls.py`,
`backend/apps/sync/tests/test_views.py`). No migration file was created
(consistent with `makemigrations --check` finding no changes). No `.env`
file was edited (the real `backend/.env` present in this environment was
only read implicitly by `manage.py`/Django at runtime, as every command
already does — never opened or written by this task).

---

## 13. What was deliberately NOT touched

- `reconcile_session()`, `_discover_chats()`, `_iter_chat_history_pages()`
  (`apps/sync/reconciliation.py`) — unread-for-editing this task, cited
  only from prior confirmed knowledge and this task's own Section 1
  re-verification reads.
- `executors.py`, `tasks.py` — read to confirm behavior, not modified.
- Celery/Redis configuration (`config/celery.py`, `CELERY_BROKER_URL`,
  `RECONCILIATION_EXECUTOR`) — not touched.
- Webhook ingestion (`apps/webhooks/`) — not touched.
- `WahaSession` model/lifecycle — not touched (only read via `.objects.get()`
  in the new view, the exact same read-only access pattern
  `reconcile_session()` itself already uses).
- Inbox polling, the connectivity indicator, and the send-outcome feedback
  (`frontend/src/pages/InboxPage.tsx`, Phase 9.0/9.1D) — not opened, not
  edited, confirmed unchanged by this task's own `git diff`.
- Session Management, identity/`@lid`/JID resolution, `status@broadcast` —
  not referenced anywhere in this task's changes.
- No new dependency was added (`requirements.txt` unchanged).
- 9.1B (webhook-timestamp signal), 9.1C (Redis health endpoint), 9.1E
  (frontend consumption of this endpoint), 9.1F (Dashboard Redis card),
  9.1G (live verification against a real running environment) — none
  started, per the task's explicit stop instruction.

---

This implementation is complete: backend endpoint + tests + verification +
this report. Stopping here, per instruction — not proceeding to frontend
integration (9.1E) or any other Phase 9 slice without further direction.
