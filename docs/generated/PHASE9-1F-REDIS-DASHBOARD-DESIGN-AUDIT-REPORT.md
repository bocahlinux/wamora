# Phase 9.1F — Dashboard Redis Health Card — Design Audit (Read-Only)

**Scope.** Design/read-only audit only. No source, Docker, Compose,
`.env`, database, or Redis/WAHA state was modified. No endpoint was
called by this audit beyond what Phase 9.1C's own implementation report
already verified. No dependency was added. Every claim below was
verified directly against current source this task — `frontend/src/pages/DashboardPage.tsx`
and its CSS, `frontend/src/lib/djangoApi.ts`, `frontend/src/lib/useApiQuery.ts`,
`frontend/src/lib/bffApi.ts`, and `backend/apps/core/{views,urls,tests}.py`
were all re-read in full this task, not assumed from any prior report.

---

## 1. Objective

Determine exactly how the existing frontend Dashboard should consume
and display the `GET /api/health/redis/` signal Phase 9.1C already
implemented — data path, UI reuse, polling, error handling, security,
and file scope — without implementing anything.

---

## 2. Current Architecture

**VERIFIED FROM SOURCE:**

- **`backend/apps/core/views.py`/`urls.py`** (re-read this task, matches
  Phase 9.1C's implementation report exactly): `GET /api/health/redis/`,
  unauthenticated, `{status: 'ok'|'error', component: 'redis'}`, `200`/`503`,
  single broad `except Exception`, no secret ever in the body.
- **`frontend/src/lib/djangoApi.ts`**: already exports
  `export interface ComponentHealth { status: string; component: string; }`
  and `getBackendHealth()`/`getDatabaseHealth()`, both calling
  `request<ComponentHealth>(`${config.djangoBaseUrl}/api/health/...`)`
  with **no auth header** — Frontend → Django direct, no BFF hop.
- **`frontend/src/lib/bffApi.ts`**: `getBffHealth()` calls
  `${config.bffBaseUrl}/health` — the **only** health call that goes
  through the BFF, and only because WAHA reachability is what it
  reports, and WAHA lives on the Tencent side (same side as the BFF).
- **`frontend/src/lib/useApiQuery.ts`**: a generic `loading`/`success`/`error`
  state machine around one `fetcher()` call, re-run only when its `deps`
  array changes (plus a manual `refetch()`). **No built-in polling/interval
  of any kind** — any polling in this codebase is implemented by the
  *caller*, not by this hook itself.

---

## 3. Existing Dashboard Precedent

**VERIFIED FROM SOURCE**, `frontend/src/pages/DashboardPage.tsx` re-read
in full this task:

- **`HealthCard`** (lines 40-63) is already a **generic**, reusable
  component: `query: ReturnType<typeof useApiQuery<{ ok: boolean; detail: string }>>`.
  It already handles all three states with no per-service branching:
  `loading` → `LoadingState`; `error` → `StatusBadge status="error" label="Unreachable"` +
  "Could not reach this service."; success → `StatusBadge status={data.ok ? 'healthy' : 'error'} label={data.ok ? 'Healthy' : 'Degraded'}` + `data.detail`.
- **Three existing instances** (`wahaQuery`, `backendQuery`, `databaseQuery`,
  lines 164-180) all follow the **identical shape**: call the raw API,
  then transform its real response into `{ok, detail}` inline inside the
  `useApiQuery` callback. `backendQuery`/`databaseQuery` — the two
  directly analogous to Redis — do exactly:
  ```ts
  const result = await getDatabaseHealth();
  if (!result.ok) return result;
  return { ok: true, data: { ok: result.data.status === 'ok', detail: 'Connected' } };
  ```
- **All three use `useApiQuery(fn, [])`** — empty deps array — **fetch-once-on-mount,
  no polling**, confirmed for every existing Dashboard health card, no
  exception.
- **Row 1's own layout** (`section.wa-dashboard__health-row`, lines
  189-193) already renders exactly three `<HealthCard>` elements in a
  row; its CSS (`frontend/src/pages/DashboardPage.css:1-5`) uses
  `grid-template-columns: repeat(auto-fill, minmax(220px, 1fr))` —
  **responsive, not hardcoded to 3 columns** — confirmed by direct read.
- **A pre-existing, independent, in-source acknowledgment of this exact
  gap**: `DashboardPage.tsx`'s own comment (lines 151-156, written before
  any Phase 9 Docker/Redis work this session did) —
  *"The spec's Row 1 reference board also shows a Redis card — omitted
  because no Redis health endpoint exists anywhere in the backend...
  showing 'Healthy' for a check that was never made would be exactly the
  'fake successful API behavior' this project's phases forbid."* This
  independently corroborates that 9.1F closes an already-named,
  already-anticipated gap — not a newly invented one.

---

## 4. Redis Endpoint Integration Path

**Frontend → Django, direct — not through the BFF.**

Determined strictly from existing architecture, not generic best
practice:

- **Precedent is unambiguous**: `backendQuery`/`databaseQuery` (the two
  most directly analogous existing cards) both call Django directly,
  unauthenticated, exactly matching `GET /api/health/redis/`'s own shape
  (`ComponentHealth`, Section 2).
- **The BFF has no path to Redis and needs none** — re-confirmed this
  task by grep: no `redis`/`REDIS` string anywhere under `bff/`, and
  Redis is Office-side infrastructure the BFF (Tencent-side) has never
  had network access to, at any point in this project's history (Phase
  9.1C design audit Section 1, re-verified unchanged). Routing Redis
  health through the BFF would add a cross-boundary proxy hop for a
  check Django already answers directly — exactly the "don't add a
  proxy layer just because you can" anti-pattern this project's own
  prior audits have repeatedly rejected for this same reasoning.
- **No BFF change of any kind is required.**

---

## 5. UI/State Design

**No new UI pattern needed — `HealthCard` is reused exactly as-is,
unmodified.**

Proposed `redisQuery` (mirroring `databaseQuery` line-for-line):
```ts
const redisQuery = useApiQuery(async () => {
  const result = await getRedisHealth();
  if (!result.ok) return result;
  return { ok: true, data: { ok: result.data.status === 'ok', detail: result.data.status === 'ok' ? 'Connected' : 'Unreachable' } };
}, []);
```
and one additional `<HealthCard icon={... } tint={...} title="Redis" query={redisQuery} />`
inside the existing `wa-dashboard__health-row` section — no new
component, no new CSS class, no layout restructuring (Section 3's grid
finding).

**No new frontend TypeScript type is needed** — `ComponentHealth`
(`frontend/src/lib/djangoApi.ts`) already matches `/api/health/redis/`'s
response shape exactly (`{status: string, component: string}`); a
`getRedisHealth()` function would simply be:
```ts
export function getRedisHealth() {
  return request<ComponentHealth>(`${config.djangoBaseUrl}/api/health/redis/`);
}
```

---

## 6. Polling/Refresh Design

**No existing Dashboard health card polls.** All three current cards use
`useApiQuery(fn, [])` (Section 2/3) — fetch once, on mount, full stop; a
manual `refetch()` exists on the hook but nothing in `DashboardPage.tsx`
calls it automatically for any health card today.

**Redis should follow the identical pattern: fetch-once-on-mount, no
polling.** Not a new proposal — the *only* pattern this codebase's
Dashboard has ever used for this exact category of card. Introducing
polling for Redis alone, when its three siblings don't poll, would be an
unrequested, unprecedented inconsistency — not proposed here.

---

## 7. Error Handling

**Fully covered by the existing, unmodified `HealthCard` component — no
new logic needed:**

| Backend response | `redisQuery` state | `HealthCard` rendering |
|---|---|---|
| `200 {"status":"ok","component":"redis"}` | `success`, `data.ok = true` | `StatusBadge status="healthy" label="Healthy"` |
| `503 {"status":"error","component":"redis"}` | `success`, `data.ok = false` (the transform still returns `ok: true` at the `ApiResult` level — a 503 with a valid JSON body is not a network failure, `request()` still resolves successfully; only `result.data.status` distinguishes it) | `StatusBadge status="error" label="Degraded"` |
| Network failure / timeout / unreachable Django | `error` (`ApiResult.ok === false`) | `StatusBadge status="error" label="Unreachable"` + "Could not reach this service." |
| Authentication failure | **Not applicable** — the endpoint is unauthenticated (Section 2); no auth-failure branch exists or is needed |

**No new terminology is invented** — "Healthy"/"Degraded"/"Unreachable"
are the exact three labels `HealthCard` already uses for every existing
card (Section 3); Redis reuses them verbatim, not a fourth vocabulary.

---

## 8. Security Analysis

**VERIFIED FROM SOURCE**: the endpoint is intentionally unauthenticated
(Phase 9.1C, re-confirmed by direct read of `apps/core/views.py` this
task) — `authentication_classes = []`, matching `LivenessView`/`DatabaseHealthView`
exactly. **Exposing it through the Dashboard introduces no new
information-disclosure risk**: the response is always exactly one of two
fixed, two-field bodies (`{status, component}`), already proven (Phase
9.1C's own dedicated test) to never leak the broker URL, credentials, or
raw exception text, even when the caller is unauthenticated. This is the
same exposure profile `backendQuery`/`databaseQuery` already have —
Redis health is not more sensitive than "is PostgreSQL reachable,"
already shipped and already unauthenticated. **No security weakening of
any kind is required or proposed** to make this work.

---

## 9. Performance Analysis

Fetch-once-on-mount (Section 6) means the Dashboard's Redis card issues
**exactly one** `GET /api/health/redis/` request per page load — the
same load profile as the three existing cards, not a new polling burden
on Django or Redis. The endpoint itself is already bounded to
`REDIS_HEALTH_TIMEOUT_SECONDS = 2` (Phase 9.1C), so even a slow/unreachable
Redis cannot make a single Dashboard page load hang for more than 2
seconds on this one card. **No caching or infrastructure change is
necessary** — the existing architecture's own "fetch once, no interval"
convention already bounds the impact to the minimum possible for this
category of check.

---

## 10. Testing Strategy

**VERIFIED FROM SOURCE**: `frontend/package.json`'s `scripts` are
`dev`/`build`/`lint`/`preview` only — **no test script, no test
framework** (`devDependencies` lists only `@vitejs/plugin-react`,
`oxlint`, `typescript`, `vite` — no `vitest`, `jest`, or
`@testing-library/*`). This has been the frontend's consistent state
throughout every prior phase in this session.

**Consequence**: no frontend unit test (healthy state / unavailable
state / network failure / loading state) can be added without
introducing a new dependency — explicitly forbidden by this task's own
strict scope ("add dependencies" is listed under what must NOT be done).
**This audit does not propose adding a frontend test framework** — it
notes the gap and defers the decision (Section 13).

**No BFF changes are proposed** (Section 4), so no BFF test is needed.

**Backend**: Phase 9.1C's own 5 `RedisHealthViewTests` already cover the
endpoint itself completely (reachable, connection error, timeout, no
leak, timeout wiring) — **re-confirmed this audit found no missing
case** a Dashboard-consumption slice would newly require; the backend
contract doesn't change at all for 9.1F, so no new backend test is
proposed.

---

## 11. Expected Files to Change

**IMPLEMENTATION REQUIRED** (if/when 9.1F is approved):
- `frontend/src/lib/djangoApi.ts` — add `getRedisHealth()` (Section 5),
  reusing the existing `ComponentHealth` interface, no new type.
- `frontend/src/pages/DashboardPage.tsx` — add `redisQuery` +
  one `<HealthCard>` element in the existing Row 1 section (Section 5).

**NO CHANGE REQUIRED**:
- `frontend/src/pages/DashboardPage.css` — grid is already responsive
  (Section 3).
- `frontend/src/components/ui/StatusBadge.tsx` — `HealthCard` uses
  `StatusBadge` with the same `'healthy'`/`'error'` `StatusKind` values
  every other card already uses; no new mapper function needed (this is
  a plain boolean, not `SyncStatus`'s 5-value enum — the
  `mapSyncStatus()`-style concern from the earlier Dashboard-integration
  audit does not apply here).
- `bff/src/*` — no involvement (Section 4).
- `backend/apps/core/*` — Phase 9.1C already complete, untouched.
- Any Docker/Compose/`.env` file.
- Any test file — no frontend test framework exists to add tests to
  (Section 10); no backend test gap found.

---

## 12. Files Intentionally Not Changed

Restated per the task's own emphasis — none of the following require
any change for 9.1F: `backend/apps/core/views.py`, `urls.py`, `tests.py`
(Phase 9.1C, complete); `bff/src/*` (Section 4); any Dockerfile or
Compose file (Phase A–G's development environment, untouched by
Phase 9.1C and not implicated by this audit either); `frontend/src/components/ui/HealthCard`-equivalent
— there is no separate file for it; it's defined inline in
`DashboardPage.tsx` and is already generic enough to reuse verbatim.

---

## 13. USER DECISIONS REQUIRED

Given how directly this audit's questions were resolvable from existing,
unambiguous precedent (three prior health cards following one identical
pattern), only one item rises to the level the task's own instructions
reserve for escalation:

1. **Whether to add a frontend test framework at all**, given none
   exists today (Section 10) — **not** a decision this audit makes or
   recommends a direction on, since it would be a new dependency
   (explicitly out of this task's scope to decide) and affects every
   future frontend feature, not just this one card. If declined (the
   status quo), 9.1F would ship with the same "no automated frontend
   test" coverage every other Dashboard card already has today — not a
   regression, simply unchanged.

**Not escalated** (per the task's own examples of what doesn't need a
decision): card icon/tint choice, exact wording beyond the
already-established "Healthy"/"Degraded"/"Unreachable" vocabulary,
polling interval (none exists to choose — Section 6 already settles
this from precedent), and the data path (Section 4 — settled
unambiguously from source, not a judgment call).

---

## 14. Implementation Plan (Not Performed by This Audit)

1. Add `getRedisHealth()` to `frontend/src/lib/djangoApi.ts`, reusing
   `ComponentHealth` (Section 5) — no dependency on any other step.
2. Add `redisQuery` + one `<HealthCard>` to `DashboardPage.tsx`'s
   existing Row 1 section (Section 5) — depends only on step 1.
3. Manual verification (matching this project's own established
   "frontend has no test framework, verify via `npm run build`/`npm run
   lint` plus a manual browser check" pattern, used consistently in
   every prior frontend-touching phase this session): confirm the new
   card renders, shows "Healthy" against the live Phase 9.1C endpoint,
   and shows "Unreachable"/"Degraded" appropriately if Redis or Django
   is down (achievable via the same mocking discipline already
   established, or by observing real state, without ever needing to
   stop the currently-running development stack deliberately).
4. `npm run lint` + `npm run build` — the same regression check every
   prior frontend change in this session has used.

No step above was performed by this audit — sequencing only.

---

## 15. Risks and Limitations

- **No frontend automated test coverage** — consistent with every
  existing Dashboard card, not a new gap introduced by this slice
  specifically (Section 10).
- **No risk to Celery-liveness semantics** — the proposed card's label
  vocabulary (`"Healthy"`/`"Degraded"`/`"Unreachable"`) says nothing
  about Celery workers, tasks, or Beat; it reuses the exact same
  generic vocabulary the WAHA/Backend/PostgreSQL cards already use for
  their own, unrelated checks — no wording anywhere claims or implies
  worker liveness. This boundary (Redis health ≠ Celery worker health)
  is preserved by construction, not by an added disclaimer.
- **No risk to Docker development environment (Phase A–G)** — nothing
  in this design touches any Compose file, Dockerfile, or `.env`.
- **Very low regression risk overall** — two small, additive changes to
  already-proven, already-generic code paths; no existing card's
  behavior changes.

---

## 16. Final Recommendation

**9.1F is a small, low-risk, fully-precedented slice** — every design
question resolves directly from the three already-existing Dashboard
health cards, which already establish an identical, reusable pattern
for exactly this kind of binary reachability signal. No BFF change, no
new frontend type, no new CSS, no new polling mechanism, and no new
backend work is required — `HealthCard` and `ComponentHealth` were
already generic enough to absorb this exact addition before this audit
began. The one item requiring your input (Section 13) is a
project-wide question (frontend test framework) that exists independently
of this specific card and is not a blocker to implementing 9.1F itself.

**No file was modified in producing this report. No endpoint was called
beyond what Phase 9.1C's own report already verified. No dependency was
added.**

**STOP.** Phase 9.1F is not implemented. Not proceeding to staging,
production, Phase G/H, Celery liveness, worker monitoring, or any other
feature.
