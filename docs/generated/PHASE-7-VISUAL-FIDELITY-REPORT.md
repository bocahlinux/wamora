# Phase 7 — Visual Fidelity Pass

Frontend-only. No backend, BFF, API, or authentication file was touched
— confirmed by scope (only files under `frontend/src/` were edited).
Design source of truth used:
`wamora-design-assets/docs/WAMORA-FRONTEND-DESIGN-SPEC.md` and the five
reference boards under `wamora-design-assets/assets/reference/`,
re-inspected directly (image viewing) this round rather than relied on
from memory.

## 1. Sidebar collapsed-state bug — root cause and fix

**Root cause found directly in source**:
`frontend/src/components/layout/Sidebar.css` had

```css
.wa-sidebar--collapsed .wa-sidebar__collapse-toggle {
  display: none;
}
```

— a leftover rule that unconditionally hid the toggle button whenever
the sidebar was collapsed, with nothing replacing it. The button was
never conditionally rendered wrong in the JSX (`Sidebar.tsx` always
renders it, swapping `PanelLeftOpen`/`PanelLeftClose` correctly by
state) — this was a pure CSS bug.

**Fix**: removed that rule. Collapsed mode now stacks the compact logo
mark and the toggle button vertically (`.wa-sidebar__brand` becomes
`flex-direction: column` when collapsed) instead of trying to fit both
side-by-side in a 72px-wide column, which the original horizontal
layout didn't have room for. Both elements remain visible and
functional in both states, matching your explicit requirement:

```
Expanded:  [logo]                    [collapse]
Collapsed: [compact logo]
           [expand]
```

(Stacked rather than side-by-side in the collapsed case specifically —
the horizontal layout you sketched doesn't fit in 72px once both a
~31px logo mark and a 36px icon button are accounted for; stacking was
the smallest change that keeps both permanently visible without
widening the collapsed sidebar or shrinking either element awkwardly.)

## 2. Structured mismatch list (current → design reference)

Produced by re-viewing `wamora-frontend-reference.png` and
`wamora-visual-design-system.png` directly and comparing against the
actual current component code (not from memory of building it):

| # | Area | CURRENT (before this pass) | EXPECTED (reference) | Action |
|---|---|---|---|---|
| 1 | Sidebar collapse toggle | Disappears when collapsed | Always visible | **Fixed** (Section 1) |
| 2 | Status badges | Plain 6px color dot + text | Small semantic icon (check/warning-triangle/x-circle/info/etc.) + text, inside the pill | **Fixed** — `StatusBadge` now renders a Lucide icon per status (reusing the spec's own Section 6 icon mapping where one is named: success→`CircleCheck`, warning→`TriangleAlert`, error→`CircleX`, info→`Info`, QR→`QrCode`) |
| 3 | Dashboard/Session health-card icon badge | One flat neutral-gray square for every card | A distinct color tint per service, drawn from the approved primary/blue palette | **Fixed** — WAHA uses `--color-primary` (green), Backend uses `--color-blue-500`, PostgreSQL uses `--color-blue-600`; no new color invented, all three already existed in `tokens.css` |
| 4 | Card title / status relationship | Small muted-gray title, status badge stacked below it | Bold, primary-colored title with the status badge inline to its right on the same row | **Fixed** — both `DashboardPage` and `SessionsPage` cards restructured to a title row (`justify-content: space-between`) with the detail text below |
| 5 | Sidebar active-nav highlight | Light-tint background pill, primary-colored text | Same treatment | **No change needed** — already matches |
| 6 | Typography scale (H1–H4, body, caption) | Exact spec values in `tokens.css` | Same | **No change needed** — verified byte-for-byte against the spec's Section 5 table, already correct |
| 7 | Button hierarchy (Primary/Secondary/Danger) | Green primary, outlined secondary, solid red danger | Reference board shows a *blue* primary example, but the written spec (Section 8) explicitly allows "WAMORA green/blue depending on semantic context" | **No change** — reusing the same `--color-primary` token for both buttons and the active-nav highlight keeps the app internally consistent, which the reference board's single example doesn't override |
| 8 | Dashboard Row 2 (sessions summary / messages-today+chart / activity feed) | Not built | Reference shows three additional cards here with real-looking numbers and a bar chart | **Deliberately not built** — no backend data source exists for any of it; building it would mean fabricating numbers, which this task explicitly forbids. Documented as a standing dependency, not silently skipped. |
| 9 | Topbar (search bar, notification bell, avatar) | Menu toggle + theme toggle only | Reference shows a search input, notification bell, and avatar circle | **Deliberately not added** — no search backend exists (a non-functional search box would be an invented, dishonest UI element); the notification bell in the reference implies unread-count data that doesn't exist yet either. Sidebar already carries a real account/sign-out area, so identity/session context isn't entirely absent from the shell. Flagged as a remaining, data-dependent gap, not silently ignored. |
| 10 | Card radius/shadow/border/padding | `--radius-lg` (14px), `--shadow-sm`, 1px border, 20px padding | Visually rounded (~12–14px), flat/near-shadowless, subtle border | **No change needed** — already matches closely |
| 11 | Icon family/sizing consistency | Lucide throughout, 20px nav/card icons, 16px small icons | Lucide throughout | **No change needed** |

## 3. Files changed

- `frontend/src/components/layout/Sidebar.css` — removed the bug (Section 1).
- `frontend/src/components/ui/StatusBadge.tsx` — icon-per-status instead of a dot (mismatch 2).
- `frontend/src/components/ui/StatusBadge.css` — updated for the icon (was dot-specific sizing).
- `frontend/src/pages/DashboardPage.tsx` — health-card restructure (mismatches 3, 4).
- `frontend/src/pages/DashboardPage.css` — colored icon-badge tints, title-row layout.
- `frontend/src/pages/SessionsPage.tsx` — same title-row restructure for consistency (mismatch 4).
- `frontend/src/pages/SessionsPage.css` — matching colored icon badge.

No other file was touched. No dependency was added (all icons come from the already-installed `lucide-react`).

## 4. Checks performed

- **TypeScript type-check** (`npx tsc -b --noEmit`): clean, 0 errors.
- **Lint** (`npm run lint`, oxlint): same 4 pre-existing style warnings as before this pass (component/hook co-location suggestions, unrelated to this change), 0 errors, 0 new findings.
- **Production build** (`npm run build`): clean, no warnings.
- **Module-transform check**: started a scratch Vite dev instance (landed on port `5175`, since `5173`/`5174` were both already occupied by your own running instances, which were never touched or restarted) and confirmed every edited file (`Sidebar.tsx`/`.css`, `DashboardPage.tsx`/`.css`, `StatusBadge.tsx`, `SessionsPage.tsx`) transforms successfully (`200` from Vite's dev transform pipeline) — proves no syntax/import error, not a visual confirmation.
- **CSS source check**: confirmed the `display: none` rule responsible for the sidebar bug no longer exists anywhere in `Sidebar.css`.

## 5. What was NOT verified — stated explicitly, not claimed

**No browser was used and no screenshot was received — no visual/browser verification was performed**, per your own instruction not to claim it otherwise. Specifically not confirmed by actually looking at a rendered page:

- Sidebar expanded → collapsed → expanded actually looks and behaves correctly on screen (only confirmed via source: the CSS rule that broke it is gone, and the JSX/state logic that drives the icon swap was already correct and untouched).
- Page navigation continuing to work (unchanged code path, not touched this round, so low risk — but not re-clicked-through in a browser).
- Dark mode and light mode rendering of the updated card layout (the new CSS uses only existing semantic tokens that already have both light/dark values, so it should carry over correctly, but this is an inference from the token system, not an observed screenshot).
- Real backend status data still loads and displays correctly in the restructured cards (the data-fetching code — `useApiQuery`, `getBffHealth`, etc. — was not modified at all this round, only the JSX/CSS around how the result is displayed, so this is low-risk but, again, not watched happen on screen).

**Recommend a manual look in your browser** (you already have a running instance) to confirm these before considering the visual pass fully closed.

## 6. Remaining visual mismatches not addressed

- Dashboard Row 2 and the Topbar's search/notification/avatar elements (mismatches 8–9 above) — both are data-dependent gaps, not styling gaps, and building either now would mean inventing data or a non-functional control. Left as explicitly-documented dependencies rather than closed.
- No pixel-level (exact px/color) comparison was performed against the reference PNGs — the comparison was structural/visual (layout, hierarchy, treatment), consistent with the design package's own README, which describes the reference boards as "visual references, not pixel-perfect implementation screenshots."
