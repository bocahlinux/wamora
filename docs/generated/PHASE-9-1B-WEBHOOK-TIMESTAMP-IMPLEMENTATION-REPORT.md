# Phase 9.1B — Webhook Timestamp — Implementation Report

**Conclusion: Complete.** `GET /api/sync/status/<session_name>/` now
returns a `last_webhook_received_at` field, computed from
`WebhookEvent.received_at` via `Max()`, scoped per session, `null` when
the session has no webhook events. No migration, no BFF change, no
frontend change, no new dependency. All 298 backend tests pass,
`manage.py check` is clean. Implements exactly the plan from
`docs/generated/PHASE-9-1B-WEBHOOK-TIMESTAMP-DESIGN-AUDIT-REPORT.md`
Section 12, per the user's explicit approval of that design.

---

## 1. Objective

Add a `last_webhook_received_at` field to the existing sync-status
endpoint, reporting the most recent time the backend actually received
any WAHA webhook for a session — a server-received-time connectivity
signal, independent of reconciliation/`SyncCheckpoint` state.

---

## 2. Initial State (before this task)

`GET /api/sync/status/<session_name>/` (`apps/sync/views.py`,
`SyncStatusView`) returned exactly:

```json
{
  "session": "no_epahari",
  "sync_status": "healthy",
  "checkpoint_status": "ok",
  "last_run_at": "2026-09-25T10:00:00Z",
  "seconds_since_last_run": 320,
  "checkpoint_updated_at": "2026-09-25T10:00:05Z"
}
```

No `last_webhook_received_at` field existed — confirmed by the design
audit immediately preceding this task, re-confirmed by reading the file
again before editing.

---

## 3. Implementation

**`backend/apps/sync/views.py`** — two changes, both scoped exactly to
the design audit's plan (Section 12 there):

1. Added imports: `Max` from `django.db.models`, `WebhookEvent` from
   `apps.webhooks.models`.
2. Inside `SyncStatusView.get()`, after the existing `checkpoint`
   lookup, added:
   ```python
   last_webhook_received_at = WebhookEvent.objects.filter(session=session).aggregate(
       Max('received_at')
   )['received_at__max']
   ```
   and added `'last_webhook_received_at': _isoformat(last_webhook_received_at)`
   to the response dict — reusing the view's own existing `_isoformat()`
   helper (already used by `last_run_at`/`checkpoint_updated_at`), so
   formatting is byte-identical across all three timestamp fields in
   this response.

No filtering by `WebhookEvent.status` was applied — a `pending`,
`failed`, or `unsupported` delivery still updates `received_at` on
creation and still counts, per the design audit's Section 11 reasoning
(this is a "did WAHA reach us" signal, not a "did we successfully
process it" signal) — verified by `test_non_processed_webhook_event_still_counts`
(Section 9).

**Not touched**: `SyncCheckpoint`, `_derive_sync_status()`, the
`checkpoint`/`sync_status`/`seconds_since_last_run` computation, the
URL routing (`apps/sync/api_urls.py`), authentication/permission classes,
and every other field already in the response — all byte-identical to
before.

---

## 4. Files Changed

- **`backend/apps/sync/views.py`** — `+13` lines (2 imports, 1 aggregate
  query, 1 response field, 1 explanatory comment). The only production
  file changed.
- **`backend/apps/sync/tests/test_views.py`** — added a
  `_make_webhook_event()` helper (mirrors
  `apps/dashboard/tests/test_views.py`'s identical helper, since
  `WebhookEvent.received_at` is `auto_now_add=True` and can only be
  backdated via a post-create `.update()`), six new test methods
  (Section 9), and updated the existing
  `test_query_count_is_bounded_no_n_plus_one` (2 → 3 expected domain
  queries, `webhooks_webhookevent` added to the matched-table list).

No other file was created, modified, or deleted by this task.

---

## 5. Files Intentionally Not Changed

- `backend/apps/webhooks/models.py` — `WebhookEvent.received_at`
  already existed exactly as needed; not touched.
- `backend/apps/sync/models.py` (`SyncCheckpoint`) — untouched, per
  scope ("Jangan mengubah model/database schema").
- `backend/apps/sync/api_urls.py` / `urls.py` — route unchanged.
- Any migration file — none created, per scope; `received_at` already
  existed as a migrated column.
- Any file under `bff/` — per scope ("Jangan mengubah BFF"); also
  confirmed zero involvement in the design audit.
- Any file under `frontend/` — per scope ("Jangan mengubah frontend").
- Any file under `infrastructure/` / Docker / Compose / `.env` — per
  scope.
- `backend/apps/sync/reconciliation.py`, `executors.py`, `tasks.py` —
  reconciliation logic untouched, per scope.
- `backend/apps/webhooks/services.py`, `views.py`, `parsing.py` —
  webhook ingestion behavior untouched, per scope.
- `backend/requirements*.txt` / any dependency file — no new dependency;
  `django.db.models.Max` and `apps.webhooks.models.WebhookEvent` are
  both already-present, already-imported-elsewhere symbols.

---

## 6. API Response — Before / After

**Before:**
```json
{
  "session": "no_epahari",
  "sync_status": "healthy",
  "checkpoint_status": "ok",
  "last_run_at": "2026-09-25T10:00:00Z",
  "seconds_since_last_run": 320,
  "checkpoint_updated_at": "2026-09-25T10:00:05Z"
}
```

**After** (session with at least one webhook event received):
```json
{
  "session": "no_epahari",
  "sync_status": "healthy",
  "checkpoint_status": "ok",
  "last_run_at": "2026-09-25T10:00:00Z",
  "seconds_since_last_run": 320,
  "checkpoint_updated_at": "2026-09-25T10:00:05Z",
  "last_webhook_received_at": "2026-09-25T10:04:12Z"
}
```

**After** (session with zero webhook events, e.g. `never_synced`):
```json
{
  "session": "no_epahari",
  "sync_status": "never_synced",
  "checkpoint_status": null,
  "last_run_at": null,
  "seconds_since_last_run": null,
  "checkpoint_updated_at": null,
  "last_webhook_received_at": null
}
```

**Backward compatibility**: purely additive — every previously-existing
field, its name, type, and meaning is unchanged. **VERIFIED** by the
full pre-existing test suite (Section 8/9) passing unmodified except for
the one query-count assertion that had to change to reflect the new
query (Section 4), not a field/shape change.

---

## 7. Timestamp Semantics

- **Source**: `WebhookEvent.received_at` only — `models.DateTimeField(auto_now_add=True)`,
  the Django/DB clock at the moment the webhook delivery's row was first
  inserted (`apps/webhooks/services.py`'s `get_or_create()` call).
  **Never** `Message.timestamp` (WAHA-reported source event time) and
  **never** a value parsed from the webhook payload itself — neither is
  read anywhere in this change. **VERIFIED** by direct code review: the
  only symbol touched is `WebhookEvent.received_at` via the `Max()`
  aggregate; `Message`/`ParsedMessage`/`parse_timestamp` are not
  imported or referenced in `apps/sync/views.py`.
- **Scope**: aggregated with `.filter(session=session)` before the
  `Max()`, so a webhook event belonging to a different `WahaSession`
  cannot leak into another session's value — **VERIFIED** by
  `test_webhook_event_from_another_session_is_excluded`.
- **Null case**: a session with zero `WebhookEvent` rows yields
  `received_at__max = None` from the aggregate, formatted by the shared
  `_isoformat()` helper (which already returns `None` for a `None`
  input) as JSON `null` — **VERIFIED** by `test_no_webhook_events_returns_null`.
- **Format**: identical to `last_run_at`/`checkpoint_updated_at` — UTC,
  ISO-8601, trailing `Z` (not `+00:00`) — because all three reuse the
  exact same `_isoformat()` function, not a second formatting path.
  **VERIFIED** by `test_last_webhook_received_at_is_timezone_aware_utc_iso8601`.
- **Independence from reconciliation**: this field is populated by the
  webhook-ingestion pipeline (`apps.webhooks`), entirely separate from
  the reconciliation pipeline (`apps.sync`) that drives `sync_status`.
  **VERIFIED** by `test_last_webhook_received_at_present_even_when_never_synced`,
  which creates a `WebhookEvent` but deliberately no `SyncCheckpoint`
  and confirms both `sync_status: 'never_synced'` and a non-null
  `last_webhook_received_at` in the same response.

---

## 8. Query / Performance Verification

- **VERIFIED**: `test_query_count_is_bounded_no_n_plus_one` (updated)
  asserts exactly **3** domain queries per request — `WahaSession`
  lookup, `SyncCheckpoint` lookup, and the new `WebhookEvent` `Max()`
  aggregate — with an explicit table-name assertion, not just a raw
  count, so a future regression (e.g. an accidental per-row loop) would
  be caught by the table match failing to explain a 4th query. Test
  passed (see Section 9).
- **No N+1 introduced**: the new query is a single aggregate
  (`.aggregate(Max(...))`), executed once per request regardless of how
  many `WebhookEvent` rows exist for the session — not a per-row fetch
  followed by Python-side max-finding.
- Consistent with the design audit's Section 11 finding: `received_at`
  itself is unindexed, but the query is pre-filtered by the indexed
  `session` foreign key, bounding the unindexed sort to one session's
  row count — unchanged from the audit's analysis, not re-benchmarked
  here (no live production-scale data available in this environment).

---

## 9. Test Results

**VERIFIED** — `apps.sync` suite, using the project's local `venv`
(`backend/venv/Scripts/python.exe`) and `--settings=config.settings_test`:

```
$ python manage.py test apps.sync --settings=config.settings_test -v 2
...
test_no_webhook_events_returns_null ... ok
test_returns_most_recent_received_at_among_multiple_events ... ok
test_webhook_event_from_another_session_is_excluded ... ok
test_last_webhook_received_at_is_timezone_aware_utc_iso8601 ... ok
test_last_webhook_received_at_present_even_when_never_synced ... ok
test_non_processed_webhook_event_still_counts ... ok
test_query_count_is_bounded_no_n_plus_one ... ok
...
----------------------------------------------------------------------
Ran 115 tests in 5.934s

OK
```

All 6 new tests (Section 3 minimum test cases plus 2 extra covering
independence-from-checkpoint and non-processed-status inclusion) pass,
and every pre-existing `apps.sync` test still passes unmodified except
the one intentionally-updated query-count assertion.

**VERIFIED** — full backend suite:

```
$ python manage.py test --settings=config.settings_test
...
----------------------------------------------------------------------
Ran 298 tests in 24.417s

OK
```

No regression anywhere else in the backend (`apps.webhooks`,
`apps.dashboard`, `apps.chats`, `apps.core`, `apps.authn`,
`apps.waha_sessions` all pass unchanged). The Redis-connection-error
tracebacks visible in the raw test output belong to
`apps.core.tests.RedisHealthViewTests`' own mocked-failure scenarios
(pre-existing, unrelated to this task) — not real failures; the suite's
final result is `OK`.

**VERIFIED** — `manage.py check`:
```
$ python manage.py check --settings=config.settings_test
System check identified no issues (0 silenced).
```

---

## 10. Live Verification

**NOT VERIFIED — honestly disclosed, per instruction not to
start/stop/restart the running stack to obtain this.** `docker ps`
immediately before and after this task showed only
`wamora-dev-tencent-bff-1` and `wamora-dev-tencent-frontend-1` running —
the Office-side stack (`backend`/`celery-worker`/`celery-beat`/`redis`,
which would serve the actual `GET /api/sync/status/...` endpoint) was
**not running**, and this task did not start it (per instruction 9:
"Jangan mematikan atau restart stack yang sedang berjalan hanya untuk
verifikasi" — starting a stopped stack was likewise treated as outside
this task's authorization, not merely "restarting a running one").

**What was verified instead, as the closest honest substitute:**
- The full Django test suite (Section 9) exercises this exact view
  through DRF's real request/response cycle (`self.client.get(...)`),
  including authentication, the actual `Response({...})` serialization,
  and real SQLite-backed `WebhookEvent`/`SyncCheckpoint` queries — this
  confirms the endpoint's behavior at the application layer with the
  same rigor as every other endpoint in this codebase's test suite, but
  **is not the same as an HTTP round-trip against the live dev
  container** and is not claimed to be.
- No WhatsApp message was sent, no reconciliation was triggered, no
  WAHA operation was performed, and no production/WAHA data was
  touched — all satisfied trivially, since no live system was contacted
  at all in this task.

---

## 11. Known Limitations

- **No live HTTP verification against the running dev/production
  backend was performed** (Section 10) — the Office-side stack was not
  running and was not started for this task.
- **No frontend consumes this field yet** — by design (Section 5 of the
  design audit: explicitly out of scope for 9.1B); `frontend/src/lib/djangoApi.ts`'s
  `SyncStatus` interface was not touched and does not yet declare
  `last_webhook_received_at`, consistent with "Jangan mengubah
  frontend."
- **Unindexed `received_at` sort** — unchanged from the design audit's
  own finding (Section 11 there); not addressed here, since adding an
  index was explicitly not requested and was already classified as a
  non-blocking, deferrable performance choice.
- **No automated test covers real production-scale `WebhookEvent`
  volume** — the query's cheapness is structural (session-scoped, not
  full-table), not benchmarked against realistic data.

---

## 12. Security Verification

- **No new authentication/authorization surface**: `SyncStatusView`'s
  existing `JWTAuthentication` + `IsAuthenticated`-only gate is
  completely unchanged — confirmed by `test_unauthenticated_request_is_rejected`
  and `test_authenticated_request_succeeds_with_no_scope_required` both
  still passing unmodified.
- **No sensitive-data exposure**: the new field is a bare UTC datetime —
  no message content, no PII, no raw exception text. `WebhookEvent.error_message`
  and `WebhookEvent.payload` are never read or returned by this change.
- **No cross-session leakage**: explicitly tested (Section 7,
  `test_webhook_event_from_another_session_is_excluded`).
- **No new write path**: `SyncStatusView.get()` remains entirely
  read-only; the new code is a `.filter().aggregate()`, which performs
  a `SELECT`, never an `INSERT`/`UPDATE`/`DELETE`.
- **Idempotency/ordering**: not implicated — a pure read over rows
  already made idempotent by `WebhookEvent`'s pre-existing
  `(session, provider_event_id)` unique constraint, untouched by this
  change.

---

## 13. Git Status

```
$ git status --short backend/apps/sync/
?? backend/apps/sync/api_urls.py
?? backend/apps/sync/tests/test_views.py
?? backend/apps/sync/views.py
```

Both changed files (`views.py`, `tests/test_views.py`) were already
untracked, uncommitted work from Phase 9.1A earlier this session (no
prior commit exists to diff against — `git diff` against these paths
returns nothing precisely because there is no committed baseline, not
because nothing changed; confirmed by direct content inspection in
Sections 3 and 9 above, and by the file sizes/test counts changing
observably before vs. after this task).

```
$ git status --short backend/ bff/ frontend/ infrastructure/
 M backend/apps/core/tests.py
 M backend/apps/core/urls.py
 M backend/apps/core/views.py
 M backend/config/urls.py
 M frontend/src/components/ui/StatusBadge.tsx
 M frontend/src/lib/djangoApi.ts
 M frontend/src/pages/DashboardPage.tsx
 M frontend/src/pages/InboxPage.css
 M frontend/src/pages/InboxPage.tsx
 M frontend/vite.config.ts
 M infrastructure/office/.env.example
?? backend/apps/sync/api_urls.py
?? backend/apps/sync/tests/test_views.py
?? backend/apps/sync/views.py
?? infrastructure/development/
```

No file outside `backend/apps/sync/views.py` and
`backend/apps/sync/tests/test_views.py` was touched by this task — every
other listed entry is pre-existing, uncommitted work from earlier
phases this session.

---

## 14. Final Conclusion

Phase 9.1B is implemented exactly per the approved design: one new,
additive, `null`-safe response field on an existing endpoint, sourced
solely from `WebhookEvent.received_at` (never `Message.timestamp`, never
the WAHA payload), via a single bounded `Max()` aggregate that keeps the
endpoint's query count explicitly tested and enforced (now 3, not 2, not
N+1). No migration, no BFF change, no frontend change, and no new
dependency were introduced, matching every constraint in the approval.
298/298 backend tests pass; `manage.py check` is clean. Live HTTP
verification against a running backend was not possible without
starting the currently-stopped Office-side stack, and was not performed,
per the explicit instruction not to start/stop/restart it for
verification purposes — this is disclosed as NOT VERIFIED rather than
assumed.

**STOP.** Not proceeding to Phase 9.1G/H, stuck-running recovery, Celery
worker liveness, staging, production, or any other feature. No further
audit was performed after this implementation, per instruction.
Awaiting further instructions.
