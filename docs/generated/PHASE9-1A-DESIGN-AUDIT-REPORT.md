# Phase 9.1A — Backend Sync Status Endpoint — Design Audit (Read-Only)

**Scope.** Design/read-only audit only. No source, `.env`, migration, or
database was modified. No write-capable/internal endpoint was called. No
WhatsApp message was sent, no WAHA session touched. Everything cited below
was read directly from the current source tree this task (file paths and
line numbers given where meaningful) — `git status` was checked first and
confirmed zero drift beyond the already-completed, already-reported Phase
9.0/9.1D frontend changes: no backend file has changed since the last
backend-touching audit in this conversation, so every backend claim here is
current, not stale.

---

## 1. Executive Summary

`apps.sync` today has **zero** frontend-readable HTTP surface — its one URL
(`reconciliation/trigger/`) is a write-triggering, `HasInternalServiceKey`-gated
endpoint meant only for the BFF, mounted under `/internal/`. Phase 9.1A adds
exactly one new, read-only, `GET`-only endpoint that lets an authenticated
operator's browser learn `SyncCheckpoint`'s current state without touching
reconciliation itself in any way.

Two things distinguish this design from a naive read of the earlier Phase 9
design reports, both found by reading the current code directly rather than
trusting prior summaries:

1. **The codebase already has two different, real precedents for a
   frontend-facing authenticated read endpoint**, not one — `apps.chats`'s
   views require `IsAuthenticated` **and** `HasReadingScope`; `apps.dashboard`'s
   views require only `IsAuthenticated`, no scope check at all. Sync status
   is operational/system state, not conversation content, so it sits
   squarely in the Dashboard precedent's category — this sharpens the
   authentication recommendation in Section 5 considerably compared to
   treating it as an open toss-up.
2. **`reconcile_session()` looks up its `WahaSession` with a plain `.get()`,
   not `get_or_create()`** (`backend/apps/sync/reconciliation.py:171`) —
   meaning a session must already be known to Django (created by webhook
   ingestion or outbound-operation registration) before reconciliation can
   ever run for it. This makes `WahaSession.objects.all()` the correct,
   complete, and only-necessary source for "which sessions exist," with no
   risk of a checkpoint existing for an unknown session (enforced by the
   DB's `on_delete=PROTECT` foreign key).

This report recommends a single collection endpoint (`GET` returning every
known session's status in one response — not a per-session detail route),
a derived five-state taxonomy computed entirely from `SyncCheckpoint.status`
+ `last_run_at` (never `lag_seconds`), and explicitly excludes both webhook
health and Redis/Celery health from this endpoint's response, per the
task's own instruction — those remain 9.1B/9.1C's separate concern.

Two genuine architecture forks remain open and are escalated in Section 16,
not resolved unilaterally: the endpoint's exact URL/app placement, and the
staleness threshold's concrete value.

---

## 2. Current Implementation Evidence

Read directly this task:

- **`apps.sync` file inventory** (confirmed via directory listing):
  `models.py`, `reconciliation.py`, `executors.py`, `tasks.py`,
  `internal_views.py`, `urls.py`, `waha_client.py`, `tests/`. **No
  `views.py`, no `serializers.py`.** The existing file is named
  `internal_views.py`, not `views.py` — the only file in this app with
  that naming, precisely because its one view
  (`ReconciliationTriggerView`) is internal-service-key-gated. This is a
  real, existing naming convention this design can extend rather than
  invent (Section 4).
- **Root URL mounting** (`backend/config/urls.py`, re-confirmed unchanged):
  `internal/` → `apps.sync.urls` (alongside `apps.operations.urls`,
  `apps.audit.urls` at the same prefix). **No app in this project currently
  has two separate URL mount points** — every app's `urls.py` is mounted
  exactly once. This is a real constraint on Section 4's design fork.
- **`SyncCheckpoint` model** (`backend/apps/sync/models.py:7-33`, migration
  `backend/apps/sync/migrations/0001_initial.py` read in full this task):
  fields `session` (`OneToOneField` → `WahaSession`, `on_delete=PROTECT`),
  `checkpoint_value`, `last_run_at` (nullable), `status`
  (`idle`/`running`/`ok`/`error`, default `idle`), `lag_seconds` (nullable,
  **never written anywhere**, confirmed again this task by grep), `last_error`.
  **No database index exists on this model beyond the implicit unique index
  Django creates for the `OneToOneField`** — confirmed by reading the
  migration file directly (no `indexes = [...]` in `Meta`, no
  `Index(fields=[...])` anywhere for this model).
- **The only writer**: `reconcile_session()`
  (`backend/apps/sync/reconciliation.py:155-247`, re-read in full this
  task). Exact sequence: `session = WahaSession.objects.get(name=session_name)`
  (line 171 — **a plain `.get()`, will raise `WahaSession.DoesNotExist` if
  the session is unknown to Django — reconciliation cannot run for a
  session Django has never heard of**); `checkpoint, _ =
  SyncCheckpoint.objects.get_or_create(session=session)` (line 172);
  `status → 'running'`, saved eagerly with `update_fields=['status',
  'updated_at']` (lines 183-184, **before** `last_run_at` is touched); at
  the end, `status → 'ok'` (checkpoint_value advanced) or `status → 'error'`
  (checkpoint_value **not** advanced, `last_error` populated), both
  branches saving `update_fields=['status', 'last_run_at', 'last_error',
  'checkpoint_value', 'updated_at']` (lines 233-246). **No code anywhere
  times out or resets a `status='running'` row that never reaches its
  final save** (e.g. an uncaught exception, a killed process) — confirmed
  again by reading the full function; this remains a real, unaddressed gap
  (Section 7/15).
- **All four trigger paths** (HTTP internal-trigger via
  `ReconciliationTriggerView`, Celery periodic via
  `reconcile_all_sessions_task`, Celery targeted via `reconcile_chat_task`,
  the `manage.py reconcile` management command) **converge on this exact
  same function and therefore the exact same `SyncCheckpoint` row per
  session** — re-confirmed by reading `executors.py` and `tasks.py` in
  full this task.
- **`reconcile_all_sessions_task`**
  (`backend/apps/sync/tasks.py:104-113`, read in full this task):
  `session_names = list(WahaSession.objects.values_list('name', flat=True))`
  — this is the **exact, existing query pattern** for "enumerate all known
  sessions," directly reusable for this endpoint's collection query
  (Section 4/9).
- **`WahaSession` creation sites** (confirmed via grep, re-verified this
  task): `apps/webhooks/services.py:40` (`get_or_create`, on first inbound
  webhook) and `apps/operations/views.py:61` (`get_or_create`, on first
  outbound-operation registration). **Never** created by reconciliation
  itself. Combined with the `on_delete=PROTECT` foreign key on
  `SyncCheckpoint.session`, this means `WahaSession.objects.all()` is
  guaranteed to be a superset of every session that has a `SyncCheckpoint`
  — safe and correct as the sole enumeration source (Section 9).
- **`HasInternalServiceKey`** (`backend/apps/core/internal_auth.py:18-30`,
  unchanged): a static shared secret, `X-Internal-Service-Key` header,
  `hmac.compare_digest()`, fails closed. Used exclusively for
  BFF-process-to-Django calls (`/internal/...`), never for anything a
  browser calls directly — confirmed by reading every one of its four
  current call sites (`apps.operations`, `apps.audit`, `apps.sync.internal_views`).
- **`JWTAuthentication` + `IsAuthenticated` + `HasReadingScope`**
  (`apps/chats/views.py`, all three views, re-read in full this task) — the
  precedent for **conversation content** specifically.
- **`JWTAuthentication` + `IsAuthenticated`, no scope check**
  (`apps/dashboard/views.py`, both views, read in full this task) — the
  precedent for **operational/aggregate system state** — `MessagesStatsView`
  and `ActivityFeedView` are both this shape, and both are, in kind, the
  closest existing analog to a sync-status endpoint (they report on
  system-derived facts, not on message content a specific scope was
  designed to gate).
- **`HasReadingScope`** (`apps/authn/permissions.py:14-19`, read in full):
  `'reading' in claims.get('scopes', [])` — a single, simple scope check,
  no complexity to reuse if chosen.
- **REST_FRAMEWORK settings** (`backend/config/settings.py:315-332`, read in
  full this task): `EXCEPTION_HANDLER: 'apps.core.exceptions.api_exception_handler'`
  (global — **every** view, including any new one, automatically gets the
  redacted `{"error": {...}}` envelope for auth failures and unhandled
  exceptions, with zero custom error-handling code needed);
  `DEFAULT_PAGINATION_CLASS: PageNumberPagination`, `PAGE_SIZE: 20` — but
  the settings comment itself states plainly: *"Existing endpoints are all
  plain APIView responses (never call `.paginate_queryset()`), so this has
  no effect on them"* — pagination is opt-in per view, not automatic.
  **No `DEFAULT_AUTHENTICATION_CLASSES`/`DEFAULT_PERMISSION_CLASSES` is
  set anywhere** — every view in this project explicitly declares both, and
  a new view must do the same or fall back to DRF's own (insecure-for-this-project)
  defaults.
- **`ActivityFeedView`** (`apps/dashboard/views.py:80-148`, read in full):
  the concrete precedent for a small, bounded, **non-paginated** collection
  response (`Response({'results': [...]})`, built from plain Python dicts,
  no serializer class) — the closest existing shape-match for this
  endpoint's expected response (Section 6).
- **`TIME_ZONE = 'UTC'`, `USE_TZ = True`** (`settings.py:160-164`,
  re-confirmed this task) — every stored `DateTimeField` is UTC-aware;
  DRF serializes these as ISO-8601 with an explicit offset automatically.
  No special timezone handling is needed in this design (Section 8).
- **Test-authoring pattern** (`backend/apps/chats/test_views.py`, read in
  full this task): `APITestCase` + `@override_settings(JWT_PRIVATE_KEY=...,
  JWT_PUBLIC_KEY=...)` using `apps.authn.tests.keys.generate_test_key_pair()`;
  `apps.authn.jwt_utils.issue_access_token(user)` to mint a token;
  scope granted via `Group.objects.get_or_create(name='reading');
  user.groups.add(group)` (mirroring `compute_scopes()`'s real mechanism);
  `CaptureQueriesContext` used to assert exact query counts. This is the
  exact, reusable pattern for Section 13's test plan.

---

## 3. `SyncCheckpoint` Data Flow

```
reconcile_session()  ← the ONLY writer, all 4 trigger paths converge here
        │
        ├─ get_or_create(session=session)   [row created on FIRST run ever]
        ├─ status='running'  (eager, before any WAHA call)
        └─ status='ok'+checkpoint_value advanced   OR   status='error'+last_error
                (last_run_at always written in this final save, either branch)

SyncCheckpoint  ← currently read by NOTHING (re-confirmed: grepped this
                  task for SyncCheckpoint outside apps.sync itself and its
                  own tests — zero results in any view/serializer/frontend)
```

**A subtlety worth flagging precisely for whoever implements this**:
`SyncCheckpoint.session` is a reverse `OneToOneField` from `WahaSession`
(`related_name='sync_checkpoint'`). Django's reverse-OneToOne descriptor
**raises `SyncCheckpoint.DoesNotExist`** on attribute access when no related
row exists — it does not return `None`. A naive
`WahaSession.objects.select_related('sync_checkpoint').all()` loop that then
does `session.sync_checkpoint` directly would crash for any
never-synced session. The correct, exception-free implementation pattern is
to query `SyncCheckpoint` separately and build a `{session_id: checkpoint}`
lookup dict in Python, then `.get(session.id)` per `WahaSession` row (→
`None` if absent, cleanly representing "never_synced"). This is a concrete,
non-obvious correctness point this audit found by reading the ORM behavior,
not something either prior Phase 9 report called out this precisely.

---

## 4. Recommended Endpoint Design

**App placement — a genuine fork, escalated (Section 16, item 1), not
picked unilaterally — but sharpened with new evidence this task found:**

- **Option A1 — new `apps/sync/views.py` + a new URL mount.** Matches the
  existing `internal_views.py`/(new)`views.py` naming symmetry cleanly
  (Section 2) and keeps all of reconciliation's HTTP surface inside
  `apps.sync`. **Cost, found this task**: requires a **new** mount point in
  `backend/config/urls.py` (e.g. `path('api/sync/', include('apps.sync.api_urls'))`)
  since `apps.sync.urls` is already fully committed to the `/internal/`
  prefix's semantics (internal-key auth) — this project has no existing
  precedent for one app owning two separate URL mounts, so this would be a
  first, small, structural addition to the routing layer, not just a new
  file.
- **Option A2 — a new view inside the existing `apps.dashboard` app**, e.g.
  `SyncStatusView` in `apps/dashboard/views.py`, mounted at
  `apps/dashboard/urls.py` (e.g. `sync-status/`, under the already-mounted
  `api/dashboard/` prefix). **Zero new URL-module/mount work** — literally
  one new view class and one new `path()` line in already-existing files,
  reusing the exact already-proven `IsAuthenticated`-only auth precedent
  those two sibling views already use. **Cost**: `apps.dashboard`'s own
  module docstring frames itself as "business metrics" aggregation
  (messages/activity) drawn from `apps.chats`/`apps.audit`/`apps.webhooks` —
  folding in reconciliation-internal state slightly stretches that stated
  scope, though nothing in the docstring forbids it, and the app boundary
  reasoning given there ("doesn't belong to either [chats or audit]
  specifically... this is that same pattern applied to `/api/dashboard/`")
  arguably already accepts cross-cutting operational data as this app's
  domain.

This report does **not** pick between A1/A2 — both are minimal, both reuse
real precedent, and the trade-off (routing-layer cleanliness vs. zero new
files) is a genuine judgment call, not a technical correctness question.

**HTTP method**: `GET` only — this is a pure read, nothing here should ever
be a `POST`.

**Collection, not detail** (Section 9 has the full reasoning): one endpoint
returning **every** known session's status in a single response — no
separate per-session detail route is proposed for 9.1A. Given the expected
session count (1, "kemungkinan maksimal 2–3" per `docs/00-MASTER-SPEC.md`),
a collection response already serves the single-session case trivially (a
one-element list) and avoids N separate polling requests if/when a second
session exists.

---

## 5. Authentication / Authorization Design

**Recommendation: `authentication_classes = [JWTAuthentication]`,
`permission_classes = [IsAuthenticated]` — matching `apps.dashboard`'s
existing precedent exactly, not `apps.chats`'s `HasReadingScope` addition.**

Reasoning, grounded in what the codebase already distinguishes (Section 2):

- `HasInternalServiceKey` is categorically wrong for this endpoint — that
  mechanism authenticates the **BFF process** to Django, not an end user's
  browser (confirmed by its own docstring:
  `apps/core/internal_auth.py:1-8`, "authenticates the BFF *process*, not
  the frontend user"). This endpoint's entire purpose (per 9.1D/9.1E) is to
  be called **directly by the authenticated browser**, exactly like
  `/api/chats/` and `/api/dashboard/...` already are — the same
  Frontend→Django-direct pattern the Inbox/Chat decision report
  established, not a new Frontend→BFF→Django hop.
- Between the two existing frontend-facing precedents, `HasReadingScope`
  gates **conversation content** specifically (its own docstring:
  "the chat/message read and mark-as-read endpoints require the JWT's
  `reading` scope" — Section 5 of the Inbox/Chat decision report, cited
  there). Sync status is not conversation content — it is operational
  system state, the same *kind* of thing `MessagesStatsView`/`ActivityFeedView`
  already expose without any scope check. Requiring `reading` scope for
  sync status would be extending that scope's meaning beyond what it was
  designed for, without a clear justification found anywhere in the
  documented scope design (`docs/06-SECURITY.md`'s "Authorization" section
  names "session control, reading, sending, blast, user administration,
  system administration" as separate concerns — sync/reconciliation
  visibility isn't explicitly named under any of them, so extending
  `reading` to cover it would be an interpretive choice, not a
  documented one).
- **No new auth mechanism is proposed** — this recommendation reuses an
  existing, already-implemented, already-tested pattern verbatim
  (`JWTAuthentication` class, `IsAuthenticated` permission class, both
  already imported and used identically in `apps/dashboard/views.py`).

**This is presented as a strong recommendation, not an unresolved fork** —
unlike the app-placement question (Section 4), the evidence here points
clearly one way. It is still listed in Section 16 for your explicit
confirmation, since it is a security-relevant choice the task's own rules
say should not be guessed past without being surfaced.

---

## 6. Response Schema

Following `ActivityFeedView`'s precedent (Section 2): a plain dict response,
**no DRF pagination**, **no new serializer class** (matches the Dashboard
app's existing style — `apps.chats`'s serializer-class approach exists for
richer, per-model-field serialization needs this endpoint doesn't have).

```json
{
  "sessions": [
    {
      "session": "no_epahari",
      "sync_status": "healthy",
      "checkpoint_status": "ok",
      "last_run_at": "2026-09-25T10:00:00Z",
      "seconds_since_last_run": 320,
      "checkpoint_updated_at": "2026-09-25T10:00:00Z"
    }
  ]
}
```

- **`session`**: `WahaSession.name`, verbatim. Not a new sensitivity
  concern — see Section 11.
- **`sync_status`**: the derived five-state value (Section 7) —
  `never_synced` / `running` / `healthy` / `stale` / `failed`.
- **`checkpoint_status`**: the **raw** stored `SyncCheckpoint.status`
  value (`idle`/`running`/`ok`/`error`), included alongside the derived
  field for transparency — matches this project's own established
  philosophy of exposing raw provider/system values rather than only an
  interpreted layer (the same reasoning `WahaSession.status`'s own
  docstring gives for storing WAHA's raw status string instead of guessing
  an enum). **Flagged as optional** — costs nothing to include, but is not
  strictly required if a smaller payload is preferred (Section 16, item 3).
  `null` when no checkpoint row exists (`never_synced`).
- **`last_run_at`**: `null` until the *first* run ever completes (see the
  first-run-in-progress edge case below) — otherwise the checkpoint's raw,
  UTC, ISO-8601-serialized value.
- **`seconds_since_last_run`**: server-computed
  `int((timezone.now() - last_run_at).total_seconds())`, `null` when
  `last_run_at` is `null`.
- **`checkpoint_updated_at`**: the raw `SyncCheckpoint.updated_at` —
  included specifically because, for the `running` state, this timestamp
  reliably represents "since when has this claimed to be running" (it is
  the exact moment `status` was last set to `'running'`, since nothing else
  touches `updated_at` while status stays `'running'`) — this is **raw
  data, not an invented signal**: it lets a consumer (human or 9.1E) judge
  for themselves whether a long-running status looks stuck, without this
  endpoint asserting an unprovable `possibly_stuck` boolean of its own.
  Flagged as optional (Section 16, item 4) — the same transparency
  trade-off as `checkpoint_status`.
- **Deliberately excluded**: `last_error` (raw text — see Section 11 for
  the reasoning, flagged as a decision in Section 16, item 5);
  `lag_seconds` (never written, would always be `null`, explicitly excluded
  per this task's own instruction); any webhook-derived field (per this
  task's own instruction not to mix webhook health into this endpoint —
  that is 9.1B's separate concern); any Redis/Celery-derived field (9.1C's
  separate concern — nothing in the current source proves this data is
  available to this endpoint at all, so none is assumed).

**A real edge case the schema must represent correctly**: a session whose
reconciliation is running for the very first time ever has a
`SyncCheckpoint` row (`status='running'`) but `last_run_at` is still `null`
(only set on the *final* save — Section 3). The derived `sync_status` for
this case is `'running'` (status takes priority), with `last_run_at: null`
and `seconds_since_last_run: null` in the response — not `'never_synced'`,
since a checkpoint row genuinely exists and a run is genuinely in progress.

**HTTP status codes**:
- `200 OK` — always, for every derived `sync_status` value, including
  `stale`/`failed`/`never_synced`. This is a deliberate, important
  distinction from `DatabaseHealthView`'s `503`-on-failure pattern: that
  view performs a **live** dependency check where the check itself can
  fail; this endpoint only ever performs a plain, successful **read** of
  already-stored Django state — the "badness" being reported is *data*,
  not a *request failure*. A malformed/degraded sync status is not an HTTP
  error.
- `401` / `403` / `500` — all automatic, via the global `EXCEPTION_HANDLER`
  (Section 2) and the standard `JWTAuthentication`/`IsAuthenticated`
  classes — **zero custom error-handling code is needed** in the new view.

---

## 7. State Taxonomy

Per the task's explicit instruction: stated honestly against what the data
can actually prove, no invented signals.

| State | Reliably derivable? | Condition |
|---|---|---|
| `never_synced` | **Yes, unambiguously** | No `SyncCheckpoint` row exists for the `WahaSession` at all. |
| `running` | **Yes, at face value** — but see the caveat below | `checkpoint.status == 'running'`. |
| `healthy` | **Yes, but only once a staleness threshold is chosen (Section 8)** | `checkpoint.status == 'ok'` AND `(now - last_run_at) <= threshold`. |
| `stale` | **Yes, same caveat as `healthy`** | `checkpoint.status == 'ok'` BUT `(now - last_run_at) > threshold`. |
| `failed` | **Yes, unambiguously** | `checkpoint.status == 'error'`. |

**The `running` caveat, stated plainly per the task's instruction not to
paper over this**: the raw value `status == 'running'` is 100% reliably
read from the database — it always accurately reflects the last state
transition `reconcile_session()` actually performed. What is **not**
reliably provable from currently-available data is whether a `running`
row is *actually* still running right now, versus stuck forever because a
prior run crashed after setting `status='running'` but before its final
save (Section 3). **This design does not invent a `possibly_stuck` boolean
to paper over that gap** — instead it exposes the raw `checkpoint_updated_at`
(Section 6) so a consumer can judge for themselves, which is honest about
the limitation rather than asserting a derived fact this endpoint cannot
actually prove.

`healthy`/`stale` are correctly derivable **only as a function of a chosen
threshold** — the underlying data (`status`, `last_run_at`) is completely
reliable; the *boundary* between "healthy" and "stale" is a policy decision
this report does not make unilaterally (Section 8/16).

---

## 8. Staleness Rules

- **Definition proposed**: `stale` = the last **completed** reconciliation
  attempt succeeded (`status == 'ok'`), but it completed longer ago than a
  threshold — implying the periodic mechanism itself (Celery beat/worker,
  or the `sync`-executor's own targeted triggers) has stopped running
  recently enough, not that the data is known-wrong.
- **Threshold source — recommend a multiple of the already-configured
  `RECONCILIATION_INTERVAL_SECONDS`** (`settings.py`, unchanged), not a
  new, independent constant — this means the threshold automatically
  tracks whatever interval a given environment already runs, with no
  second value to keep in sync. **The exact multiplier (2×? 3×?) is not
  derivable from the repository** — Section 16, item 2.
- **Hardcoded constant vs. new setting**: recommend a **hardcoded Python
  constant in the view module** (e.g. `STALE_MULTIPLIER = 2`), matching
  this project's own precedent for this *kind* of value —
  `executors.py`'s `MAX_ATTEMPTS`/`RETRY_DELAY_SECONDS` are hardcoded
  constants, not settings, because they represent a display/behavior
  judgment call rather than a genuine per-environment infrastructure
  choice (unlike `RECONCILIATION_INTERVAL_SECONDS`/`RECONCILIATION_EXECUTOR`,
  which **are** settings because different environments genuinely need
  different values). A new environment variable is the alternative, more
  flexible but adds a config surface with its own default to decide and
  document — presented as the less-preferred option, not ruled out
  (Section 16, item 2).
- **Timezone/UTC handling**: a non-issue by construction — `TIME_ZONE='UTC'`,
  `USE_TZ=True` (Section 2, re-confirmed), so every `DateTimeField` read
  from the database is already UTC-aware, `timezone.now()` (already used
  throughout `reconciliation.py`) returns a UTC-aware value directly
  comparable to it, and DRF's default `DateTimeField` serialization emits
  ISO-8601 with an explicit UTC offset automatically — no custom timezone
  code is needed anywhere in this design, mirroring `MessagesStatsView`'s
  own "not an unexamined assumption" UTC-day-boundary precedent.
- **`last_run_at` NULL handling**: two distinct real cases, both already
  covered by the taxonomy above — no checkpoint row at all (`never_synced`,
  `last_run_at: null`) and a checkpoint row mid-first-run
  (`running`, `last_run_at: null` — Section 6's edge case). In neither case
  does the staleness calculation ever run (`healthy`/`stale` are only
  evaluated when `status == 'ok'`, which requires `last_run_at` to be
  non-null by construction, since both are written in the same final save).
  No `None`-comparison bug is possible if implemented as described.

---

## 9. Multi-Session Design

**Recommendation: a single collection endpoint, `WahaSession.objects.all()`
as the enumeration source (Section 2's `reconcile_all_sessions_task`
precedent), no separate per-session detail route for 9.1A.**

- `WahaSession.objects.all()` is proven complete and safe as the "which
  sessions exist" source (Section 2/3 — no session can have a
  `SyncCheckpoint` without first existing as a `WahaSession`, enforced by
  the DB foreign key).
- Query shape: fetch all `WahaSession` rows, fetch all `SyncCheckpoint`
  rows in one separate query, join them in Python via a dict keyed by
  `session_id` (Section 3's reverse-OneToOne caveat) — two queries total,
  regardless of session count.
- A `?session=<name>` filter query parameter is **not proposed for 9.1A** —
  nothing in 9.1D or the planned 9.1E consumption pattern needs
  per-session filtering yet (the frontend's own `config.wahaSessionName` is
  the only session it currently operates on at all — the BFF's
  `sessionGuard` remains single-session by construction, unchanged by
  anything in this report). Trivially addable later
  (`WahaSession.objects.filter(name=...)`) without any schema or
  architecture change if a real multi-session consumer ever needs it — not
  built speculatively now.

---

## 10. Performance Considerations

- **Query count**: exactly 2 (one `WahaSession.objects.all()`, one
  `SyncCheckpoint.objects.all()`) regardless of session count, per Section
  9's join-in-Python design — no N+1 risk, no `select_related`/`prefetch_related`
  needed (there is no nested/related-object serialization happening here,
  unlike `ChatListView`'s `Contact` join).
- **Index situation**: `SyncCheckpoint` has **no** index beyond the implicit
  `OneToOneField` uniqueness (Section 2/3) — but this is a complete
  non-issue at this project's scale: `docs/00-MASTER-SPEC.md` names "1,
  kemungkinan maksimal 2–3" sessions, meaning a full, unindexed table scan
  of `SyncCheckpoint` will touch at most a handful of rows, ever. This
  matches the exact "acceptable at current scale, not added speculatively"
  reasoning `MessagesStatsView`/`ActivityFeedView`'s own docstrings already
  use for their own unindexed-but-bounded queries.
- **Safe to poll**: yes, comfortably — two trivial-cardinality queries, no
  pagination overhead, no live external I/O (unlike, e.g., the BFF's
  `/health`, which makes a real WAHA call — this endpoint touches only
  Django's own database). If 9.1E eventually polls this on the same
  cadence as Inbox's existing 5–8s loops (Phase 9.1D, unchanged by this
  report), the load is negligible.

---

## 11. Security Considerations

- **Endpoint accessible to any authenticated user (no scope gate,
  Section 5)** — consistent with, not a new departure from, this project's
  own already-documented v1 posture: *"every authenticated user with the
  `reading` scope currently sees all chats/messages/dashboard/audit
  data — a documented, deliberate v1 posture, not an oversight"*
  (`README.md`, re-confirmed unchanged this task). Recommending
  `IsAuthenticated`-only (no scope at all) for sync status is, if
  anything, a narrower exposure than what chats/dashboard data already
  gets, not a wider one.
- **Session enumeration / name exposure**: not a new risk. The frontend
  already knows its own configured session name
  (`VITE_WAHA_SESSION_NAME`); this project has no multi-tenant concept
  where one authenticated operator's dashboard should be hidden from
  another's — every authenticated user is already trusted with full,
  identical read access to all session-scoped data project-wide (same
  citation as above). Exposing `WahaSession.name` in this new endpoint's
  response introduces no risk class that doesn't already exist for the
  chats/dashboard/audit endpoints.
- **`last_error` exclusion (Section 6)**: recommended, matching
  `apps/core/exceptions.py`'s own established, project-wide discipline of
  never surfacing raw exception/error text through a standard API
  response — this discipline is applied there regardless of whether the
  caller is authenticated, so it is applied here the same way, not loosened
  just because this endpoint requires a login. Genuinely a judgment call
  though (an authenticated operator debugging a stale session might want
  *some* hint) — escalated, not silently decided (Section 16, item 5).
- **Response size**: small and bounded by construction (at most a handful
  of session objects, each with ~6 scalar fields) — not a concern.
- **Rate limiting**: explicitly **not** addressed by this design, per the
  task's own instruction — remains Phase 12 scope, unchanged, same as
  every other endpoint in this project today.

---

## 12. Production Compatibility

- The staleness threshold (Section 8) reads only the already-environment-configured
  `RECONCILIATION_INTERVAL_SECONDS` — same code path in dev and production,
  no `if DEBUG`/`if ENVIRONMENT == 'production'` branch anywhere, matching
  the task's explicit requirement.
- The endpoint's queries (`WahaSession.objects.all()`,
  `SyncCheckpoint.objects.all()`) behave identically against SQLite
  (this project's test settings) and the real PostgreSQL production
  database — no PostgreSQL-specific query construct is used (unlike, e.g.,
  `ChatListView`'s explicit `nulls_last=True` handling for a genuine
  cross-database ordering difference — this endpoint's queries have no such
  concern since there's no `ORDER BY` on a nullable column here).
- **Multiple WAHA sessions**: the collection design (Section 9) already
  scales to 2–3 sessions with zero code change — the same query, the same
  response shape, just a longer `sessions` array. No environment-specific
  branching is needed to support this.
- **Celery/Redis production**: this endpoint reads only `SyncCheckpoint`,
  which is updated identically regardless of which `RECONCILIATION_EXECUTOR`
  wrote it (Section 2) — the endpoint itself has zero awareness of, and
  zero dependency on, Celery or Redis being reachable at request time. It
  will correctly report whatever `SyncCheckpoint` last recorded even if
  Redis/Celery are down right now — consistent with Signal A/Signal B's
  intended independence (Section 14).

---

## 13. Testing Plan

Following the exact pattern established in `backend/apps/chats/test_views.py`
(Section 2) — a new `backend/apps/sync/tests/test_views.py` (matching the
project's `test_views.py` naming convention for a new `views.py`), using
`APITestCase` + `@override_settings(JWT_PRIVATE_KEY=..., JWT_PUBLIC_KEY=...)`
via `apps.authn.tests.keys.generate_test_key_pair()`, and
`apps.authn.jwt_utils.issue_access_token()` to mint tokens. Since this
report recommends `IsAuthenticated`-only (Section 5), no scope-granting
`Group` setup is needed for the "authorized" cases — only a plain
`User.objects.create_user(...)`.

Concrete cases, mapped to the task's own checklist:

- `test_unauthenticated_request_is_rejected` — no `Authorization` header
  → `401`.
- `test_authenticated_request_succeeds` — any logged-in user (no scope
  needed, per Section 5) → `200`. *(No "unauthorized access" 403 case
  applies under the `IsAuthenticated`-only recommendation — if Section 16's
  auth decision instead chooses `HasReadingScope`, this case becomes a
  403-for-no-scope test, mirroring `ChatListViewTests.test_authenticated_without_reading_scope_is_forbidden`
  exactly.)*
- `test_no_sessions_returns_empty_list` — no `WahaSession` rows at all →
  `{"sessions": []}`.
- `test_session_with_no_checkpoint_is_never_synced` — a `WahaSession` row
  exists, no `SyncCheckpoint` → `sync_status: 'never_synced'`.
- `test_running_checkpoint_before_first_completion` — a `SyncCheckpoint`
  with `status='running'`, `last_run_at=None` (the Section 6 edge case) →
  `sync_status: 'running'`, `last_run_at: null`.
- `test_running_checkpoint_after_a_prior_completed_run` — `status='running'`,
  `last_run_at` non-null (a *subsequent* run in progress) →
  `sync_status: 'running'`, `last_run_at` still reflects the *prior*
  completed run.
- `test_recent_ok_checkpoint_is_healthy` — `status='ok'`, `last_run_at`
  within the threshold → `sync_status: 'healthy'`.
- `test_old_ok_checkpoint_is_stale` — `status='ok'`, `last_run_at` beyond
  the threshold (constructed via `timezone.now() - timedelta(...)`,
  mirroring the existing `timedelta` usage pattern in
  `ChatsApiTestCase`) → `sync_status: 'stale'`.
- `test_error_checkpoint_is_failed` — `status='error'` → `sync_status:
  'failed'`, regardless of `last_run_at` age.
- `test_multiple_sessions_each_reported_independently` — two
  `WahaSession` rows with different checkpoint states → both appear in
  `sessions`, each correctly classified, not conflated.
- `test_query_count_is_bounded` — `CaptureQueriesContext` (same tool
  `ChatListViewTests` already uses), asserting exactly 2 queries regardless
  of session count (Section 10) — a direct regression guard against an
  accidental N+1 reintroduction.
- **"malformed/nonexistent session"**: not directly applicable in the
  collection-only design (Section 9) — there is no session-identifying URL
  parameter to be malformed. If Section 16 ultimately adds a `?session=`
  filter, the corresponding test would be
  `test_unknown_session_filter_returns_empty_list` (not a 404 — an unknown
  filter value on a collection endpoint conventionally returns an empty
  result, not an error, consistent with how DRF filtering generally
  behaves elsewhere in Django, though this is a minor convention choice
  only relevant if that optional filter is ever built).
- **Timezone edge case**: `test_response_timestamps_are_utc_iso8601` —
  construct a checkpoint with an explicit UTC `last_run_at`, assert the
  serialized response string carries an explicit UTC offset (`Z` or
  `+00:00`), confirming DRF's default behavior under this project's
  `USE_TZ=True` setting is what's actually relied on, not merely assumed.

**No frontend test is proposed** — this project has no frontend test
infrastructure (re-confirmed across every prior Phase 9 task this session),
and 9.1E (the frontend consumer) is explicitly out of scope for this task
regardless.

---

## 14. Dependencies on 9.1B/9.1C/9.1E/9.1F

- **9.1B (webhook-timestamp signal)**: **not** folded into this design, per
  the task's explicit instruction not to mix webhook health with sync
  health. If 9.1B is built later, the natural integration point is an
  *additional* field on the same response object (e.g.
  `last_webhook_received_at`) — additive, no breaking change to the schema
  proposed here, but a separate decision/task, not assumed into 9.1A.
- **9.1C (Redis health)**: **not** part of this endpoint at all — nothing
  in the current source proves `SyncCheckpoint`-derived data has any
  awareness of Redis/Celery reachability (Section 2/12), and the task's
  own instruction is explicit not to assume otherwise. 9.1C remains its
  own, fully independent endpoint (`GET /api/health/redis/` per the earlier
  design report), with no schema overlap with this one.
- **9.1E (frontend sync-status badge)**: this design's response schema
  (Section 6) is what 9.1E would consume — `sync_status` as a fixed string
  enum is deliberately chosen so 9.1E never needs to re-derive
  `healthy`/`stale` logic client-side, mirroring how 9.1D's connectivity
  indicator already keeps its own logic entirely client-side and
  independent (see Section 14 below on the two-signal independence). **Not
  built or touched by this task.**
- **9.1F (Dashboard Redis card)**: depends on 9.1C only, unrelated to this
  endpoint.
- **9.1G (live verification)**: depends on 9.1A actually being implemented
  and deployed somewhere reachable — out of scope for a design audit.

**Signal A (Phase 9.1D, already implemented) vs. Signal B (this endpoint) —
explicitly verified independent, not contradicted by anything in this
design**: Signal A (`InboxPage.tsx`'s `connectivityIssue`) answers "can the
frontend currently reach Django at all," derived purely from `ApiError.kind`
on the *existing* chat-list/messages polling calls — it has no dependency on
this new endpoint and would work identically whether or not 9.1A is ever
built. Signal B (this endpoint) answers "is reconciliation itself healthy,"
and is meaningful only once Django *is* reachable (if Django is down,
9.1D's Signal A already correctly reports that, and a call to this new
endpoint would simply fail the same way any other Django call does under
that condition — no special-casing needed, no overlap in what each signal
claims to know).

---

## 15. Risks and Limitations

- **The stuck-`running`-checkpoint gap (Section 3/7) is not fixed by this
  design, by design** — this report only makes the underlying raw data
  (`checkpoint_updated_at`) visible; it does not add any timeout/recovery
  logic to `reconcile_session()` itself, which would be a write-path
  change outside a design-only, read-endpoint task's scope.
- **The `healthy`/`stale` boundary is inherently a judgment call** — no
  value is "provably correct" from the repository (Section 8); whatever
  multiplier is chosen, a session that misses exactly one cycle due to
  ordinary jitter (not a real outage) could transiently read as `stale`
  depending on where the threshold lands — an accepted trade-off of any
  fixed-threshold design, not unique to this proposal.
- **App-placement choice (Section 4) has a real, if small, structural
  cost either way** — A1 adds a new URL mount (a first for this project);
  A2 stretches `apps.dashboard`'s stated scope slightly. Neither is free.
- **This audit could not run any test or verify any behavior live** — every
  claim in Sections 6-13 is a design proposal validated by reading existing,
  analogous, already-tested code, not by executing anything. Per the hard
  rules, no migration, view, or test file was created.
- **No serializer class is proposed** (Section 6) — if the response ever
  needs to grow significantly more complex than the ~6 scalar fields
  proposed here, a plain-dict response becomes harder to maintain than a
  proper `Serializer` class; acceptable for the schema's current size, but
  worth revisiting if 9.1B's addition (or others) grows the shape
  substantially later.

---

## 16. USER DECISIONS REQUIRED

1. **App placement / URL mount** (Section 4): a new `apps/sync/views.py` +
   a new root URL mount (Option A1), or a new view inside the existing
   `apps.dashboard` app reusing its current mount (Option A2)? Both are
   minimal-change, evidence-backed options with different, real trade-offs
   — this report does not pick.
2. **Staleness threshold multiplier** (Section 8): this report proposes
   computing it as a multiple of the existing `RECONCILIATION_INTERVAL_SECONDS`
   (2× or 3×, hardcoded as a Python constant, not a new setting) — confirm
   the exact multiplier, or decide a new dedicated environment variable is
   wanted instead.
3. **Include raw `checkpoint_status` in the response?** (Section 6) —
   recommended (cheap, matches the project's "expose raw values" philosophy)
   but genuinely optional; confirm or drop it for a smaller payload.
4. **Include `checkpoint_updated_at` in the response?** (Section 6/7) —
   recommended as the honest, non-invented signal for judging a long-`running`
   state, but also genuinely optional.
5. **Exclude `last_error` entirely, or include a truncated/redacted
   excerpt for authenticated operators?** (Section 6/11) — this report
   recommends full exclusion, matching `apps/core/exceptions.py`'s
   project-wide discipline, but acknowledges a legitimate operator-debugging
   argument for at least a short excerpt.
6. **Confirm the `IsAuthenticated`-only auth recommendation** (Section 5) —
   presented with strong supporting evidence from existing precedent, not
   as an open toss-up, but still a security-relevant choice this report
   surfaces for your explicit sign-off rather than assuming.
7. **Is a `?session=` filter wanted even though nothing currently consumes
   it?** (Section 9) — this report recommends not building it speculatively;
   confirm that's acceptable.

---

## 17. Recommended Implementation Order

Not a ranking — dependency-derived only, and **not started by this task**:

1. Resolve Section 16, items 1 and 6 (app placement, auth) first — every
   other implementation detail (which files, which test module path,
   which URL) depends on these two being settled.
2. Resolve items 2–5 (threshold value, optional fields) — these affect the
   exact response schema and the view's internal constants, but not the
   overall file/routing structure, so they can be settled in parallel with
   or shortly after item 1.
3. Implement the view + URL wiring (per items 1) and the derivation logic
   (per items 2–5), reusing `WahaSession.objects.all()` +
   `SyncCheckpoint.objects.all()` joined in Python (Section 3/9) — no
   migration required (no schema change anywhere in this design).
4. Implement the test suite (Section 13) — can begin as soon as the view's
   shape is fixed, ideally alongside the view itself, matching this
   project's existing test-alongside-implementation discipline.
5. **9.1E (frontend consumption) and 9.1G (live verification) remain
   explicitly out of this task's scope**, per your instruction not to
   auto-continue — to be taken up only on your further direction.

---

This was a design-only audit. No source code, migration, endpoint, or test
file was created. Stopping here, per instruction, awaiting your decisions on
Section 16.
