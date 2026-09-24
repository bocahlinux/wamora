# Phase 8 — Dashboard Backend Foundation

Backend-only. This is **not** the Phase 8 Inbox/chat implementation — it is
a small, scoped pass adding exactly three read endpoints so the
already-built Dashboard/Topbar can later consume real data, per the task's
explicit boundary. No notifications, global search, Redis health, or BFF
multi-session support was implemented. No frontend file was changed.

## 1. Scope

Implemented exactly the three endpoints requested, and nothing else:

1. `GET /api/auth/me/` — identifies the caller of a Django-issued JWT.
2. `GET /api/dashboard/messages/` — today's message count + hourly trend.
3. `GET /api/dashboard/activity/` — a bounded, merged recent-activity feed.

Everything else named in the task's scope boundary (Inbox/chat,
notifications, global search, Redis health, BFF multi-session support) was
deliberately left untouched.

## 2. Files changed

New files:

- `backend/apps/authn/authentication.py` — new `JWTAuthentication` DRF
  authentication class (see Section 5).
- `backend/apps/authn/tests/test_authentication.py`
- `backend/apps/authn/tests/test_me_view.py`
- `backend/apps/dashboard/__init__.py`
- `backend/apps/dashboard/apps.py`
- `backend/apps/dashboard/views.py` — `MessagesStatsView`, `ActivityFeedView`
- `backend/apps/dashboard/urls.py`
- `backend/apps/dashboard/tests/__init__.py`
- `backend/apps/dashboard/tests/test_views.py`
- `docs/generated/PHASE-8-DASHBOARD-BACKEND-FOUNDATION-REPORT.md` (this file)

Edited files:

- `backend/apps/authn/views.py` — added `MeView`.
- `backend/apps/authn/urls.py` — wired `path('me/', MeView.as_view())`.
- `backend/apps/authn/jwt_utils.py` — docstring only: the module previously
  stated verification "happens independently on the BFF side" as if that
  were the only verifier; added one sentence noting Django now also
  verifies (via the new `authentication.py`) for endpoints the frontend
  calls directly. No functional change — issuance logic, keys, algorithm,
  claims, and the `JwtNotConfigured` behavior are byte-for-byte unchanged.
- `backend/config/settings.py` — added `'apps.dashboard'` to
  `INSTALLED_APPS`. No other setting changed; no new setting was needed
  (`JWT_PUBLIC_KEY`/`JWT_ALGORITHM`/`JWT_ISSUER`/`JWT_AUDIENCE` already
  existed for the BFF's own verification and are simply reused).
- `backend/config/urls.py` — added
  `path('api/dashboard/', include('apps.dashboard.urls'))`.

No `.env` file, no dependency (`requirements.txt`), no migration, and no
frontend file was touched.

## 3. Endpoints added

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/auth/me/` | Bearer JWT | Identify the current user |
| GET | `/api/dashboard/messages/` | Bearer JWT | Today's message count + hourly trend |
| GET | `/api/dashboard/activity/` | Bearer JWT | Bounded recent-activity feed |

## 4. Exact request/response contracts

### `GET /api/auth/me/`

No request body/params. Requires `Authorization: Bearer <token>`.

200 response:
```json
{
  "id": 4,
  "username": "operator",
  "display_name": "Op Erator"
}
```
`display_name` is `user.get_full_name() or user.username` — a Django
built-in, no new field. 401 (see Section 5) if the token is missing,
malformed, expired, wrong signature/issuer/audience, or names a user that
no longer exists/is inactive.

### `GET /api/dashboard/messages/`

No request params. Requires `Authorization: Bearer <token>`.

200 response:
```json
{
  "messages_today": 42,
  "trend": [
    {"hour": "2026-09-24T00:00:00+00:00", "count": 3},
    {"hour": "2026-09-24T01:00:00+00:00", "count": 0},
    ...
    {"hour": "2026-09-24T23:00:00+00:00", "count": 1}
  ]
}
```
`trend` always has exactly 24 entries (zero-filled for hours with no
messages), covering the current UTC calendar day, ascending order.

This intentionally does **not** reuse the example shape given in the task
(`{"today": {"count": ...}, "trend": [{"bucket": ..., "count": ...}]}`):
flattened `today.count` to `messages_today` and renamed `bucket` to `hour`
(the field literally is an hour-truncated timestamp) to match this
project's existing flat, unwrapped response convention (`LoginView`'s
`{access_token, token_type, expires_in}`, the health views'
`{status, component}` — no nested envelope exists anywhere else in the
API).

### `GET /api/dashboard/activity/`

Query param: `limit` (optional, integer, default 20, clamped to
`[1, 100]`; a missing/invalid/out-of-range value silently falls back to
the default rather than returning 400 — this is a display convenience
knob, not a validated input boundary). Requires
`Authorization: Bearer <token>`.

200 response:
```json
{
  "results": [
    {
      "id": "webhook-118",
      "type": "webhook",
      "action": "message",
      "target": "primary",
      "result": "processed",
      "occurred_at": "2026-09-24T09:58:00+00:00"
    },
    {
      "id": "audit-42",
      "type": "audit",
      "action": "session.start",
      "target": "primary",
      "result": "success",
      "occurred_at": "2026-09-24T09:55:00+00:00"
    }
  ]
}
```
`results` is ordered most-recent-first, deterministically (see Section 7),
truncated to `limit`. `id` is a namespaced string (`"<type>-<pk>"`) meant
as a stable frontend list key, not a real cross-table identifier. Empty
array when there is no data.

## 5. Authentication behavior

Until this task, Django only ever *issued* JWTs
(`apps/authn/jwt_utils.py::issue_access_token`) — verification existed
only on the BFF (`bff/src/jwt.ts`), per the Phase 6 contract framing
("Django is the sole issuer; verification happens independently on the
BFF side"). The three new endpoints are called by the frontend directly
(not through the BFF), so Django itself needed a way to check the Bearer
token — that gap is what `apps/authn/authentication.py::JWTAuthentication`
closes.

It is a second, independent **consumer** of the exact same values the BFF
already uses for its own verification — nothing about signing was
changed:
- Algorithm: `settings.JWT_ALGORITHM` (`RS256`, unchanged).
- Key: `settings.JWT_PUBLIC_KEY` (already loaded via the existing
  `_read_key` helper, previously unused; now used for the first time).
- Issuer/audience: `settings.JWT_ISSUER` / `settings.JWT_AUDIENCE`
  (unchanged, same values the token is signed with).
- `sub` claim resolves to a real, active `django.contrib.auth.User` via
  `User.objects.get(pk=..., is_active=True)`.

Behavior:
- No `Authorization` header → `authenticate()` returns `None` → DRF's
  `IsAuthenticated` permission produces **401 Unauthorized** (a
  `WWW-Authenticate: Bearer` challenge header is emitted via
  `authenticate_header()`, so DRF returns 401 rather than the default 403
  for an authenticator with no challenge).
- Malformed / expired / wrong-signature / wrong-issuer / wrong-audience /
  unknown-or-inactive-user token → raises DRF's `AuthenticationFailed` →
  **401 Unauthorized**, with a single generic message
  (`"Invalid or expired token"`) in every case — the underlying PyJWT
  exception text is never echoed back to the client (matches
  `docs/06-SECURITY.md`'s log-redaction posture; also matches
  `LoginView`'s existing pattern of a deliberately generic auth error).
- `JWT_PUBLIC_KEY` unconfigured → fails closed with `AuthenticationFailed`
  (401), same "fail closed when unconfigured" posture as
  `HasInternalServiceKey` (`apps/core/internal_auth.py`).

All three views set `authentication_classes = [JWTAuthentication]` and
`permission_classes = [IsAuthenticated]` explicitly — the project has no
`DEFAULT_AUTHENTICATION_CLASSES`/`DEFAULT_PERMISSION_CLASSES` in
`REST_FRAMEWORK` settings, so every existing view already sets these
per-view; the new views follow that same established pattern rather than
introducing a global default.

## 6. Data sources used

- `apps.chats.models.Message` (existing model, untouched) — `timestamp`,
  `direction` fields for the messages endpoint. No new field, no new
  model.
- `apps.audit.models.AuditLog` (existing model, untouched) — `action`,
  `target`, `result`, `created_at` for the activity feed's audit side.
- `apps.webhooks.models.WebhookEvent` (existing model, untouched) —
  `event_type`, `status`, `received_at`, `session` for the activity
  feed's webhook side.
- `django.contrib.auth.User` — `id`, `username`, `get_full_name()` for
  `/me/`.

No new model or migration was introduced for any of the three endpoints.

Why both `AuditLog` and `WebhookEvent` feed the activity endpoint, not
just one: they are the only two "something happened" record types that
currently exist in the system, and they're not redundant — `AuditLog`
covers sensitive/administrative actions, `WebhookEvent` covers inbound
WAHA traffic. Picking only one would silently drop real events the
Dashboard's design reference implies should appear together (e.g. a
session-lifecycle audit entry alongside an inbound-message webhook
entry). No new "activity" model was created to unify them — the two
existing tables are queried directly and merged in the view.

## 7. Query/performance considerations

Verified directly via `django.test.utils.CaptureQueriesContext` against
each endpoint (temporary inspection test, run and removed — not part of
the permanent suite):

- **`GET /api/dashboard/messages/`: 3 queries total** — 1 user lookup (the
  authentication class resolving `sub`, unavoidable per-request), 1
  `SELECT COUNT(*) ... WHERE timestamp >= day_start AND timestamp <
  day_end` for `messages_today`, 1 single `GROUP BY` query
  (`django_datetime_trunc('hour', timestamp, 'UTC', 'UTC')`) for the
  24-hour trend. No row-by-row Python iteration over `Message` — both
  aggregates are computed DB-side. The 24-entry zero-fill loop operates
  only on the small aggregated result (at most 24 rows), never on raw
  messages.
- **`GET /api/dashboard/activity/`: 3 queries total** — 1 user lookup, 1
  bounded `AuditLog` query (`ORDER BY created_at DESC, id DESC LIMIT
  <limit>`), 1 bounded `WebhookEvent` query with `select_related('session')`
  (`ORDER BY received_at DESC, id DESC LIMIT <limit>`) — confirmed to be a
  single joined query, not `1 + N` per-row session lookups. The merge/sort
  of the two bounded result sets happens in Python but only ever touches
  at most `2 × limit` rows (default 40, max 200), never a full table.
- **"Today" boundary**: computed from `django.utils.timezone.now()`
  truncated to midnight, which is the **UTC** calendar day — this project
  has `TIME_ZONE = 'UTC'` / `USE_TZ = True` (`config/settings.py`,
  confirmed by direct read before writing this code), so UTC is this
  project's actual configured "today," not an unexamined assumption.

**Missing-index findings — reported, not silently fixed, per explicit
instruction:**

- `apps.chats.models.Message` is indexed only on `(chat, timestamp)`
  (`Index(fields=['chat', 'timestamp'])`). The messages endpoint's query
  filters on `timestamp` alone, chat-agnostic — no existing index
  supports it, so both the count and trend queries are a sequential scan
  bounded by the `WHERE` clause. At this project's expected scale (a
  handful of WAHA sessions, an internal ops tool) this is very likely
  fine. **If message volume grows enough to matter, the candidate index
  is `Index(fields=['timestamp'])`** — not added here.
- `apps.webhooks.models.WebhookEvent` is indexed only on `status`
  (`Index(fields=['status'])`). The activity feed's query orders by
  `received_at`, unindexed — bounded by `LIMIT`, so the practical cost is
  low even without an index, but it is still an unindexed sort. **The
  candidate index, if this becomes a hot path, is
  `Index(fields=['received_at'])`** — not added here.
- `apps.audit.models.AuditLog` is already indexed on `created_at` — no
  gap there.

No index was added speculatively. Both gaps above are reported as
findings for a future decision, per the task's explicit instruction not
to add one without being asked.

## 8. Tests added

- `apps/authn/tests/test_authentication.py` (12 tests) — `JWTAuthentication`
  unit tests: no header, non-Bearer scheme, valid token resolves the
  correct user, expired token, wrong signing key, wrong issuer, wrong
  audience, malformed token, unknown subject, non-numeric subject,
  inactive user, unconfigured public key.
- `apps/authn/tests/test_me_view.py` (5 tests) — unauthenticated → 401,
  invalid token → 401, valid token returns correct id/username/
  display_name, display_name falls back to username when no full name is
  set, response never contains anything beyond `{id, username,
  display_name}` (explicit sensitive-field-exclusion check).
- `apps/dashboard/tests/test_views.py` (11 tests):
  - Messages: unauthenticated → 401; empty dataset → `messages_today: 0`
    and a fully zero-filled 24-entry trend; only today's messages are
    counted (controlled fixtures at yesterday/today/tomorrow boundaries);
    trend buckets messages into the correct hour and leaves other hours
    at 0; trend is ordered and always covers all 24 hours.
  - Activity: unauthenticated → 401; empty dataset → `results: []`;
    audit and webhook events are correctly merged and sorted by recency
    (with a controlled, out-of-DB-insertion-order fixture proving the
    sort, not just insertion order); webhook `payload` is never present
    in a result row; `limit` bounds the result count; an invalid `limit`
    value falls back to the default instead of erroring.

All fixtures use explicit, timezone-aware `timestamp`/`created_at`/
`received_at` values (the latter two backdated via `.update()` since both
fields are `auto_now_add=True` and can't be set directly at creation) —
no reliance on "now" happening to fall into the right bucket by luck.

## 9. Test results

```
DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test apps.authn apps.dashboard
→ Ran 48 tests in 7.4s — OK

DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test
→ Ran 206 tests in 7.7s — OK   (full existing suite, unaffected)

DJANGO_SETTINGS_MODULE=config.settings_test python manage.py check
→ System check identified no issues (0 silenced)

DJANGO_SETTINGS_MODULE=config.settings_test python manage.py makemigrations --check --dry-run
→ No changes detected
```

No production database was used or touched; no live WAHA call was made
(none of this task's code calls WAHA at all).

## 10. Migration status

**No migration was created or is required.** `apps.dashboard` has no
`models.py` — both endpoints read existing models (`Message`, `AuditLog`,
`WebhookEvent`) directly. `makemigrations --check --dry-run` confirms no
pending model changes anywhere in the project. The two missing-index
findings in Section 7 are explicitly *not* implemented as migrations here,
per instruction.

## 11. Security considerations

- All three endpoints require authentication (`IsAuthenticated`); none
  uses `AllowAny`. No existing fine-grained per-user data-isolation model
  exists in this project (every `AuditLog`/`Message`/`WebhookEvent` row is
  visible to any authenticated user, same as every other authenticated
  read endpoint already in the codebase) — this task did not invent a new
  authorization model, and this is stated here explicitly rather than
  silently assumed.
- `/me/` returns only `id`, `username`, `display_name` — no password
  hash, email, scopes, or group membership.
- The activity feed returns only `{id, type, action, target, result,
  occurred_at}` per item — `WebhookEvent.payload` (raw webhook body) and
  `AuditLog.actor` (a full user object) are never serialized, only the
  plain `target` string field.
- Invalid/expired/malformed tokens all produce the same generic 401
  message — no information about *why* a token was rejected leaks to the
  client.
- No secret, credential, or `.env` file was read, modified, or logged
  during this task.

## 12. What was NOT implemented

- Inbox/chat (the actual Phase 8 scope) — not started, per explicit
  instruction.
- Notifications, global search, Redis health, BFF multi-session support —
  not started, per explicit instruction.
- No frontend change of any kind — the three endpoints exist but nothing
  in `frontend/` consumes them yet. **No browser or frontend verification
  was performed or is claimed** — this task is backend-only.
- The two missing-index findings (Section 7) were not implemented —
  reported only, per instruction not to add an index speculatively.
- No rate limiting was added to any of the three endpoints (consistent
  with the rest of the API — rate limiting is explicitly out of scope
  until the Phase 12 security-hardening pass, same posture already
  documented for `LoginView`).
- No caching of any kind was added to the dashboard aggregates — each
  request recomputes both queries directly.

---

Do not start another phase automatically after this task.
