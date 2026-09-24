# Phase 8C — Dashboard Frontend Data Integration

Connects the already-built Dashboard/Topbar UI to the three real Phase 8
backend endpoints
(`docs/generated/PHASE-8-DASHBOARD-BACKEND-FOUNDATION-REPORT.md`). No new
data-fetching architecture, no mock/fabricated data, no Inbox/chat,
notifications, search, Redis health, or BFF multi-session work.

## 1. Exact files changed

Frontend:

- `frontend/src/lib/djangoApi.ts` — added `getMe()`, `getDashboardMessages()`,
  `getDashboardActivity(limit)` and their response types (`Me`,
  `DashboardMessages`, `MessageTrendBucket`, `DashboardActivity`,
  `ActivityItem`, `ActivityItemType`), following the existing
  `getBackendHealth`/`getDatabaseHealth` pattern in the same file
  (`request<T>()` + `authHeader()`, no new HTTP client).
- `frontend/src/components/ui/StatusBadge.tsx` — added `mapActivityResult()`,
  a second raw-string → `StatusKind` mapper alongside the existing
  `mapWahaStatus()`, same file, same pattern.
- `frontend/src/components/layout/Sidebar.tsx` /
  `frontend/src/components/layout/Sidebar.css` — the account-area
  placeholder ("Signed in") now shows the real `display_name` from
  `GET /api/auth/me/`; added text-overflow handling for the now-variable-
  length name.
- `frontend/src/pages/DashboardPage.tsx` /
  `frontend/src/pages/DashboardPage.css` — added `MessagesCard`,
  `ActivityCard`, and a sessions-summary placeholder card, wired into a
  new Row 2 section below the existing health-check row.

Backend (see Section 8 — one line, with your explicit approval, not part
of implementing the frontend):

- `backend/.env` — `JWT_PUBLIC_KEY_PATH` was empty; set to the same
  `jwt_public.pem` path already configured in `bff/.env`, so Django (which
  now verifies its own tokens as of the Phase 8 backend foundation task)
  actually has a public key to verify against in this dev environment.

Nothing else was touched. No new npm dependency was added
(`frontend/package.json` is unchanged — no chart library, no `axios`).

## 2. API endpoints integrated

| Endpoint | Called from | Auth |
|---|---|---|
| `GET /api/auth/me/` | `Sidebar.tsx` | Bearer JWT (`authHeader()`) |
| `GET /api/dashboard/messages/` | `DashboardPage.tsx` | Bearer JWT |
| `GET /api/dashboard/activity/?limit=8` | `DashboardPage.tsx` | Bearer JWT |

All three go **Frontend → Django directly** (`config.djangoBaseUrl`),
exactly like the existing `getBackendHealth`/`getDatabaseHealth` calls —
not through the BFF, matching `docs/07-API-CONTRACT.md`'s "Frontend ->
Django" path and this task's explicit instruction not to move this data
through the BFF.

## 3. API response contracts consumed

```ts
// GET /api/auth/me/
interface Me { id: number; username: string; display_name: string }

// GET /api/dashboard/messages/
interface DashboardMessages {
  messages_today: number;
  trend: { hour: string; count: number }[]; // always 24 entries, UTC
}

// GET /api/dashboard/activity/?limit=N
interface DashboardActivity {
  results: {
    id: string; type: 'audit' | 'webhook'; action: string;
    target: string; result: string; occurred_at: string;
  }[];
}
```

These match the backend contract exactly as documented in the Phase 8
backend foundation report — no field was renamed, added, or assumed
beyond what that report specifies.

## 4. UI components connected

- **Identity** (`Sidebar.tsx`): the existing account-footer area (icon +
  name + sign-out) now renders `display_name` from `/me/` instead of the
  static "Signed in" placeholder. Still the same generic `User` icon —
  the API returns no avatar, so none is fabricated.
- **Messages** (`DashboardPage.tsx`, new `MessagesCard`): reuses `Card`,
  `LoadingState`, `ErrorState`; the big number is `messages_today`; the
  chart is a small dependency-free CSS bar chart (flex row of 24 divs,
  height = `count / max(count)`, `title` attribute showing the exact
  hour+count on hover) — no charting library was added, consistent with
  "do not add axios or another HTTP library" and the project's existing
  zero-extra-dependency posture for UI primitives (`Card`/`Badge`/
  `StatusBadge` are all hand-built the same way).
- **Activity** (`DashboardPage.tsx`, new `ActivityCard`): reuses `Card`,
  `LoadingState`, `ErrorState`, `EmptyState`, `StatusBadge`. Each row
  shows a type icon (`ShieldCheck` for `audit`, `Webhook` for `webhook`),
  the raw `action`/`target` strings, and a `StatusBadge` colored via the
  new `mapActivityResult()`.
- **Sessions summary placeholder** (`DashboardPage.tsx`): a third Row-2
  card using the existing `EmptyState` component, explicitly labeled "Not
  available yet" with a description pointing at the Phase 8 audit — see
  Section 13.

## 5. Loading/error/empty behavior

All three follow the existing `useApiQuery` state machine
(`{status: 'loading' | 'success' | 'error'}` + `refetch`), the same one
every other page already uses — no new fetching pattern was introduced.

- **Loading**: existing `LoadingState` component, per-card.
- **Error**: existing `ErrorState` component (`describeError()` — never a
  raw server response), with its built-in "Try again" retry button wired
  to `query.refetch`.
- **Empty, as real data**:
  - `messages_today: 0` renders as `0`, not hidden or replaced with a
    placeholder — verified directly against the real dev database, which
    currently has zero `Message` rows (see Section 12).
  - A trend where every bucket is `0` still renders all 24 bars (each at
    minimum a 2px CSS baseline for visibility — a purely cosmetic
    floor, not a change to the underlying data).
  - `results: []` for activity renders the existing `EmptyState`
    ("No recent activity") rather than an empty list with no explanation.

## 6. Timezone decision and evidence

**Decision: keep "today" as the UTC calendar day — no backend change.**

Evidence gathered before writing any code:
- `docs/generated/PHASE-5-CELERY-REDIS.md`: `CELERY_TIMEZONE` was
  explicitly set to match Django's `TIME_ZONE` ('UTC') "to avoid a second
  source of truth" — this is the project's own established reasoning for
  treating UTC as the single time authority, not something assumed for
  this task.
- A project-wide search of `docs/*.md` and `docs/generated/*.md` for
  "Jakarta", "WIB", or any other named timezone found **zero matches** —
  no specification document establishes a different user-facing
  timezone for the Dashboard or anywhere else.
- `backend/config/settings.py` has `TIME_ZONE = 'UTC'` / `USE_TZ = True`,
  confirmed directly (again) before this task.

Since no document defines a different intended timezone and the project's
own stated principle is to avoid a second time source, UTC is not an
unexamined assumption here — it's the only timezone this project has ever
defined, so there was no genuine ambiguity to resolve and no reason to
touch backend code (`messages_today`/`trend` are unchanged from the
Phase 8 backend foundation report).

The one frontend concession made for clarity: the trend chart's caption
and hover tooltips explicitly say "UTC" (`"Hourly trend (UTC)"`,
`aria-label="Messages per hour today, UTC"`, and each bar's `title`
attribute shows e.g. `"14:00 UTC — 3 messages"`) so an operator viewing
this outside UTC is never left to assume it's their local day. This is a
labeling choice, not a data or contract change.

## 7. Authentication behavior

No change to login, JWT issuance, JWT structure, or where authentication
happens. All three new calls use the existing `authHeader()` helper
(`frontend/src/lib/auth.ts`, unchanged) to attach the same
`sessionStorage`-held Bearer token every other authenticated call already
uses. A 401 from any of the three renders through the existing
`ErrorState`/`describeError()` path, which already maps `unauthorized` to
"Your session has expired. Please sign in again." — the same behavior
`SessionsPage`'s existing BFF call already has for its own 401s. No new
reactive "log the user out on any 401" mechanism was added, because none
existed before this task and inventing one now would be exactly the
second mechanism the task said not to build; the existing proactive
mechanism (`AuthContext` clearing the token when the JWT's own `exp`
claim passes) is untouched.

## 8. Whether any backend code was changed

**One line of `backend/.env`, with your explicit approval, and nothing
else.** While verifying the three endpoints against your real running dev
server (not the automated test suite, which already passed independently
— see Section 9), every call returned `401 authentication_failed /
"Authentication is not available"`. Investigation (detailed mid-task)
found `JWT_PUBLIC_KEY_PATH` was empty in `backend/.env` — Django never
needed its own copy of the public key before the Phase 8 backend
foundation task added `JWTAuthentication`, since only the BFF verified
tokens until then. I stopped and asked before touching anything; you chose
to have me copy the same `jwt_public.pem` path already configured in
`bff/.env` into `backend/.env`. No key material was generated, guessed, or
invented — it's the exact file the BFF already trusts, now referenced by
Django too. No other backend file, endpoint, model, or migration was
touched in this task; the three endpoints themselves are exactly what the
prior Phase 8 backend foundation task built.

**Action needed from you**: the fix was applied to `backend/.env` but your
actual `runserver` process on port 8000 loaded that file at its own
earlier startup and won't see the change until it restarts (Django's
`.env` auto-load only runs once, at process start). I verified the fix
using a separate, temporary `runserver` instance on port 8001 (using the
same updated `.env`) rather than touching your existing port-8000 process,
whose process tree looked unusual (four nested `manage.py runserver`
processes rather than the normal two) and which I didn't want to
disturb without asking first. That temporary instance was stopped again
once verification was done. **Restart your own port-8000 server** to pick
up the fix before using the live app.

## 9. Typecheck result

```
npx tsc -b --noEmit
→ clean, 0 errors
```

## 10. Lint result

```
npm run lint (oxlint)
→ 5 warnings, 0 errors
```

Same 4 pre-existing `only-export-components`/`set-state-in-effect`
warnings documented in the Phase 7 visual fidelity report, plus one new
instance of the *same* `only-export-components` warning
(`StatusBadge.tsx`) — caused by `mapActivityResult` being a second
non-component export from that file, exactly mirroring the pre-existing
`mapWahaStatus` export the linter already accepted there. Not a new
category of finding, and splitting one small helper function into its own
file for this would be exactly the kind of unnecessary abstraction this
task's instructions ask to avoid.

## 11. Build result

```
npm run build  (tsc -b && vite build)
→ built in 153ms, no warnings
dist/assets/index-*.js   291.68 kB │ gzip: 92.67 kB
dist/assets/index-*.css   15.61 kB │ gzip:  3.25 kB
```

## 12. Browser verification result

**No browser tool was available in this environment (no Playwright/
Puppeteer/screenshot capability), so no actual browser or visual
verification was performed — not claimed here.** What was verified
instead, at the HTTP level, against your real running dev database (user
`udin`, id 1 — the only user in it):

- Issued a real JWT for that user via the existing signing mechanism
  (read-only — no data was created or modified).
- `GET /api/auth/me/` → `200 {"id":1,"username":"udin","display_name":"udin"}`
  (correct fallback to username — this dev user has no first/last name
  set).
- `GET /api/dashboard/messages/` → `200 {"messages_today":0,"trend":[...24
  zero-count hourly buckets...]}` — a real empty-state response, not
  simulated (this dev database currently has zero `Message` rows).
- `GET /api/dashboard/activity/?limit=5` → `200 {"results":[]}` — same,
  a real empty result (zero `AuditLog`/`WebhookEvent` rows).
- No `Authorization` header → `401 not_authenticated`.
- A garbage token → `401 authentication_failed`.
- CORS preflight (`OPTIONS` with `Origin: http://localhost:5174`,
  matching your configured `CORS_ALLOWED_ORIGINS`) on
  `/api/dashboard/messages/` → `200` with
  `Access-Control-Allow-Origin: http://localhost:5174` and `authorization`
  in `Access-Control-Allow-Headers` — confirms a real browser on 5174 can
  actually complete these requests, not just curl.
- Noted, not changed: `CORS_ALLOWED_ORIGINS` in your `backend/.env` is
  currently `http://localhost:5174` only — a preflight from
  `http://localhost:5173` (also running locally) got no CORS headers at
  all. This is pre-existing configuration from the earlier CORS fix task,
  not something introduced or altered here; it just means the frontend
  needs to be opened via **5174**, not 5173, for these calls (and every
  other Django-direct call) to work in-browser.

Because the empty-dataset responses reflect this dev database's genuinely
empty `Message`/`AuditLog`/`WebhookEvent` tables, this confirms the
empty-state code paths (Section 5) are exercised by real data, not just
unit tests — but it does **not** confirm what the cards visually look
like rendered in a browser, dark/light theme rendering, or that the
sidebar collapse/expand still works — those remain unverified and are not
claimed as tested.

## 13. Remaining Dashboard gaps

- **WhatsApp sessions summary** (Row 2's third design element) —
  deliberately left as an `EmptyState` placeholder, per this task's
  explicit instruction. The Phase 8 data/UI audit already established
  that `WahaSession.status` isn't a reliable live source and a true
  multi-session summary needs BFF work the BFF doesn't have yet.
- **Topbar notifications/search** — not implemented; no backend data
  source exists for either, per this task's explicit instruction not to
  build non-functional controls.
- **No live browser verification** (Section 12) — HTTP-level only.
- **Your port-8000 dev server needs a manual restart** (Section 8) before
  the live app reflects the `.env` fix.
- The activity feed's `action`/`target` are shown as raw backend strings
  (e.g. `session.start`, `primary`) rather than a prettified sentence —
  deliberate, to avoid inventing semantics the backend didn't provide.

## 14. No fabricated or mock data was introduced

Every number, label, and status shown by the new UI comes directly from
one of the three real API responses. No hardcoded message count, no fake
activity rows, no invented percentages/growth rates/comparisons, no
placeholder avatar image, and no non-functional decorative control (no
search box, no notification bell) was added. Where real data doesn't
exist yet (sessions summary), the UI says so explicitly via `EmptyState`
rather than inventing a number.

---

Do not start another phase after this report.
