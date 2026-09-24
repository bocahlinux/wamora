# Phase 8C — Acceptance Report

Read-only verification. No code, config, `.env`, dependency, or
infrastructure file was modified while producing this report.

## Important limitation, stated up front

**No browser automation tool (Playwright/Puppeteer/screenshot capability)
is available in this environment.** Everything below marked PASS was
verified either by direct HTTP requests (`curl`, including real
`Authorization`/`Origin` headers matching what the browser would send)
against your actually-running dev servers, or by static inspection of the
shipped frontend source/build output. Nothing about actual rendered
pixels, real DevTools Console/Network entries, or live clicking through
routes was observed — those items are marked **NOT VERIFIED**, not PASS,
per your own standing instruction never to claim browser verification
that wasn't performed.

**Correction to the task's stated origin**: the task said the frontend
origin is currently `http://localhost:5174`. At the time of this check,
port 5174 was not listening at all — the active dev server was on
**`http://localhost:5173`** (Vite's default port; `bff/.env`'s
`CORS_ALLOWED_ORIGIN` and `backend/.env`'s `CORS_ALLOWED_ORIGINS` are both
currently set to `5173`, matching). All checks below use 5173, the
origin that's actually running.

## 1. Authentication — PASS

- `GET /api/auth/me/` against the real running Django server (`:8000`),
  with a real JWT for your only dev user (`udin`, id 1) and
  `Origin: http://localhost:5173`:
  ```
  200 {"id":1,"username":"udin","display_name":"udin"}
  ```
- Static check: `frontend/src/components/layout/Sidebar.tsx` calls
  `useApiQuery(() => getMe(), [])` and renders
  `meQuery.data.display_name` in `.wa-sidebar__account-name`, falling back
  to the literal string `"Signed in"` only while loading/on error — never
  a fabricated name. `getMe()` (`frontend/src/lib/djangoApi.ts:32`) hits
  `GET {VITE_DJANGO_BASE_URL}/api/auth/me/` with `authHeader()`.
- Confirmed the previous static "Signed in" text is gone as the default
  authenticated-state render — it's now the loading/error fallback only.

**Not verified**: that the sidebar visually shows "udin" in your actual
browser tab right now (would need a screenshot/DOM read).

## 2. Dashboard messages — PASS

- `GET /api/dashboard/messages/` against `:8000` with the same real
  token/origin:
  ```
  200 {"messages_today":0,"trend":[24 hourly buckets, all count:0]}
  ```
  This is a genuine empty result — your dev database currently has zero
  `Message` rows — not a simulated/hardcoded response.
- Static check: `DashboardPage.tsx` calls
  `useApiQuery(() => getDashboardMessages(), [])` and `MessagesCard`
  renders `query.data.messages_today` and maps all 24 `trend` entries into
  bars (`.wa-metric-card__bar`, `height: (count/max(1,...counts)) * 100%`,
  `min-height: 2px` as a purely cosmetic floor). With `max(1, ...)`
  guarding the divisor, an all-zero trend produces 24 bars each at the
  2px CSS floor — it renders, it does not divide by zero or crash.
- The `messages_today: 0` / all-zero-trend response above is exactly this
  all-zero case, confirmed against real data, not just reasoned about
  statically.

**Not verified**: what the chart looks like rendered (only confirmed it
computes valid, non-NaN, non-crashing values for this exact response).

## 3. Recent activity — PASS

- `GET /api/dashboard/activity/?limit=8` against `:8000`:
  ```
  200 {"results":[]}
  ```
  Real empty result — zero `AuditLog`/`WebhookEvent` rows in your dev
  database right now, not a frontend placeholder standing in for a failed
  call.
- Static check: `ActivityCard` in `DashboardPage.tsx` renders
  `<EmptyState icon={Activity} title="No recent activity"
  description="Nothing has happened yet." />` **only** when
  `query.data.results.length === 0` — i.e., only when the API itself
  returned an empty array. There is no separate hardcoded "no activity"
  UI path that could show regardless of the API response; the empty
  state you're seeing is the API-driven one having nothing to render, by
  construction of the conditional (`query.status === 'success' &&
  results.length === 0`).

**Not verified**: the rendered empty-state card visually, or a
non-empty-result render (your dev DB has no rows to exercise that path
with right now).

## 4. Sessions — PASS (confirmed intentional placeholder)

`DashboardPage.tsx`'s third Row 2 card is a static `EmptyState` with title
"Not available yet" — it makes **no API call at all** (no query, no
`useApiQuery`, no fetch). It cannot be "driven by data" because it isn't
wired to any data source, by design, per this task's own Step 5. Nothing
was implemented for multi-session support in this check, as instructed.

## 5. Existing health cards — PASS (unchanged)

- `HealthCard`, `wahaQuery`, `backendQuery`, `databaseQuery` in
  `DashboardPage.tsx` are byte-for-byte the same logic as before Phase 8C
  — calling `getBffHealth()`, `getBackendHealth()`, `getDatabaseHealth()`
  respectively. No line in this block was touched by Phase 8C; only new
  code was added after it.
- Live check against the real running servers:
  - `GET http://localhost:8000/api/health/` → `200 {"status":"ok","component":"backend"}`
  - `GET http://localhost:8080/health` → `200 {"status":"ok","service":"bff","waha":{"reachable":false}}`
    — WAHA itself is genuinely not reachable right now (real value, not
    fabricated); this is expected in a local dev setup without a live
    WAHA instance and is not something Phase 8C changed.

## 6. CORS/authentication — PASS for the new endpoints, one unrelated finding

- Preflight (`OPTIONS`) for `/api/dashboard/messages/` from
  `Origin: http://localhost:5173` against the real `:8000` server:
  ```
  HTTP/1.1 200 OK
  access-control-allow-origin: http://localhost:5173
  access-control-allow-headers: accept, authorization, content-type, ...
  access-control-allow-methods: DELETE, GET, OPTIONS, PATCH, POST, PUT
  ```
  `authorization` is present in the allowed headers, so the real
  `Authorization: Bearer <token>` header the frontend sends is not
  blocked.
- The same preflight from `Origin: http://localhost:5174` (the port the
  task text expected) returned `200` with **no** CORS headers — correctly
  rejected, since 5174 isn't the currently configured/running origin.
  This is expected, not a bug.
- **Unrelated finding, not a Phase 8C regression**: a plain `GET
  http://localhost:8080/health` with `Origin: http://localhost:5173`
  returned **no** `Access-Control-Allow-Origin` header at all, even
  though `bff/.env`'s `CORS_ALLOWED_ORIGIN` is already set to `5173` and
  `bff/src/app.ts` mounts CORS middleware globally before all routes
  (code looks correct). This looks like the same class of issue found
  earlier in this session on the Django side: the BFF process currently
  listening on 8080 most likely loaded its `.env` at an **earlier**
  startup, before `CORS_ALLOWED_ORIGIN` was set to its current value, and
  hasn't been restarted since — not a code defect, and not something
  Phase 8C touched (Phase 8C never modified any BFF file, its `.env`, or
  its running process). If your browser's Network tab shows a CORS error
  specifically on the **WAHA health card's** request (not the three new
  Phase 8C endpoints, which all go straight to Django on 8000), this is
  almost certainly why. Per this task's read-only scope, **not fixed
  here** — flagging only, with a note that restarting the BFF process is
  the likely fix if you choose to do it (same class of fix as the Django
  restart from the previous task).

## 7. Navigation/regression smoke test — PARTIALLY VERIFIED

- Confirmed statically: all six routes (`/`, `/whatsapp`, `/inbox`,
  `/sessions`, `/reports`, `/settings`) still resolve to existing page
  components (`DashboardPage`, `WhatsAppPage`, `InboxPage`,
  `SessionsPage`, `ReportsPage`, `SettingsPage` — all present in
  `frontend/src/pages/`), and `AppRoutes.tsx` was not touched by Phase
  8C.
- `npx tsc -b --noEmit` and `npm run build` both ran clean (0 errors) on
  the current source tree — this is strong evidence there's no
  import/type error that would crash any route at runtime, though it
  cannot prove a runtime-only crash (e.g. a bad conditional that
  typechecks but throws for a specific data shape).
- `Sidebar.tsx`'s collapse/expand logic (`collapsed` state, icon swap,
  `onToggleCollapsed`) is unchanged from the Phase 7 visual-fidelity fix —
  Phase 8C only added the `getMe()` query and changed what text renders
  inside `.wa-sidebar__account-name`; the toggle button itself, its
  handler, and its CSS were not touched.

**Not verified** (needs an actual browser): actually clicking through all
six nav items, watching for a blank screen/unexpected redirect/console
error, and physically toggling the sidebar collapse/expand twice.

## 8. Responsive/basic visual sanity — NOT VERIFIED

No screenshot or rendered-DOM inspection was possible. Static review of
`DashboardPage.css`'s new rules
(`.wa-dashboard__row2 { grid-template-columns: repeat(auto-fit,
minmax(260px, 1fr)) }`) follows the same responsive pattern already used
by the existing `.wa-dashboard__health-row`, which the Phase 7 visual
pass already covered — but this is a code-pattern inference, not an
observed measurement at any viewport width. Not claimed as verified.

## Exact endpoints tested (with status codes, this session)

| Request | Status |
|---|---|
| `GET /api/auth/me/` (valid token, Origin 5173) | 200 |
| `GET /api/dashboard/messages/` (valid token, Origin 5173) | 200 |
| `GET /api/dashboard/activity/?limit=8` (valid token, Origin 5173) | 200 |
| `OPTIONS /api/dashboard/messages/` (Origin 5173) | 200, CORS headers present |
| `OPTIONS /api/dashboard/messages/` (Origin 5174) | 200, no CORS headers (correctly rejected) |
| `GET /api/health/` (Django, :8000) | 200 |
| `GET /health` (BFF, :8080) | 200, `waha.reachable:false` |
| `GET /health` (BFF, :8080, Origin 5173) | 200, **no CORS header** (see Section 6) |

## Browser console/network findings

None observed — no browser was available to observe them in. The one
network-level anomaly found (BFF `/health` missing a CORS header for a
real cross-origin GET) was found via `curl`, not a browser Network tab,
and is documented in Section 6.

## Regression findings

**None found that trace to Phase 8C.** The one anomaly (Section 6, BFF
CORS) predates this task, is unrelated to any file Phase 8C touched, and
most likely needs only a BFF process restart, not a code change.

## Explicitly NOT verified in this check

- Actual rendered appearance of any card, chart, or the sidebar name in a
  real browser.
- Real DevTools Console output (any warnings/errors) or Network tab
  entries as the browser itself constructs them.
- Live click-through of all six nav routes.
- Live sidebar collapse → expand → collapse interaction.
- Horizontal overflow or layout behavior at any specific viewport width.
- Dark/light theme rendering of the new Row 2 cards.
- Whether the BFF CORS finding (Section 6) actually manifests as a
  visible error in your browser — only confirmed it would, based on the
  missing header on a real cross-origin request.

## Recommendation

**Phase 8C can be considered functionally closed at the API/data-wiring
level** — all three new endpoints are real, authenticated, CORS-correct
for the actual running frontend origin, return genuine (not fabricated)
data including real empty states, and no code-level regression traces to
this task. Before calling it *fully* closed, a short manual look in an
actual browser (the items listed as "NOT VERIFIED" above) is still
recommended, since none of this session's tools could observe rendering,
console output, or click-through behavior directly.

---

Do not proceed to Phase 9 automatically.
