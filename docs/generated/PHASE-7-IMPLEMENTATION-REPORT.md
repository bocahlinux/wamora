# Phase 7 — WAMORA Frontend Implementation Report

Implements the WAMORA frontend foundation per
`wamora-design-assets/docs/WAMORA-FRONTEND-DESIGN-SPEC.md` (visual source
of truth) and the Phase 6 BFF/Django contract
(`docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md`). No Django
model, migration, WAHA configuration, or BFF/Django source file was
touched this round — confirmed by file-modification-time check against
the most recent Phase 6 report; only `frontend/` and `frontend/.env*`
were modified. Phase 8 was not started.

## 1. Phase 7 scope implemented

**IMPLEMENTED**: application shell (sidebar + top bar + content area),
theme system (light/dark/system, semantic tokens, no color inversion),
routing, WAMORA branding, a lean set of reusable UI primitives, real
authentication against the actual Phase 6 login endpoint, a functional
Dashboard wired to the three real health endpoints that exist, read-only
session status presentation wired to the real Phase 6 BFF endpoint, and
honest placeholder pages for everything with no backing API yet.

**NOT IMPLEMENTED** (deliberately, per phase boundaries — see Section
13): session *control* (start/stop/restart/logout/QR), inbox/chat,
reports data, settings, blast, security hardening beyond what's
described here.

## 2. Pages/routes implemented

| Route | Page | Status |
|---|---|---|
| `/login` | Login | **IMPLEMENTED** — real `POST /api/auth/login/` call |
| `/` | Dashboard | **IMPLEMENTED** — real health checks (WAHA/Backend/Database) |
| `/sessions` | Sessions | **IMPLEMENTED (read-only)** — real `GET /api/sessions/:session/status`; no control actions |
| `/whatsapp` | WhatsApp | **DOCUMENTED / CONTRACT ONLY** — placeholder, scope undefined by any spec (Section 14) |
| `/inbox` | Inbox | **NOT IMPLEMENTED** — placeholder, Phase 8 dependency |
| `/reports` | Reports | **NOT IMPLEMENTED** — placeholder, no phase has defined this API yet |
| `/settings` | Settings | **NOT IMPLEMENTED** — placeholder, no phase has defined this API yet |
| `*` | Not Found | **IMPLEMENTED** |

All six sidebar destinations from the design spec exist as real routes
behind a shell (task Section 10: routes may exist as UI shell even where
backend functionality doesn't, as long as they don't fake it) — the four
placeholder pages render an honest `EmptyState` naming the dependency,
never mocked data.

## 3. Components created

**UI primitives** (`src/components/ui/`): `Button`, `IconButton`,
`Input`, `Badge`, `StatusBadge`, `Card`, `EmptyState`, `LoadingState`,
`ErrorState`, `PageHeader` — 10 of the design spec's ~19-item Section 8
list.

**Deliberately not built yet** (task Section 16: "avoid premature
abstraction," "only create components that are actually useful") —
`SearchInput`, `Select`, `Tabs`, `Modal/Dialog`, `Drawer`, `Dropdown`,
`Tooltip`, `Toast/Notification`, `DataTable`, `ConfirmDialog`,
`Pagination`: none of Phase 7's actual pages need any of these (no
search backend, no tabular data, no destructive action requiring
confirmation, no multi-step dialog flow exists yet). Building them now
would be exactly the "massive design system abstraction before it is
needed" the spec warns against. Icon-only buttons currently rely on the
native `title` attribute for a tooltip rather than a dedicated `Tooltip`
component — acceptable per the same reasoning, revisit once a second use
case justifies the abstraction.

**Layout** (`src/components/layout/`): `AppShell`, `Sidebar`, `TopBar`.

**Brand** (`src/components/brand/`): `Logo` (horizontal/mark ×
light/dark, theme-aware).

## 4. Design system/theme implementation

- `src/styles/tokens.css` — every color/typography/spacing value is
  copied verbatim from `WAMORA-FRONTEND-DESIGN-SPEC.md` Sections 4/5
  (exact hex codes, exact type scale). Radius/shadow/icon-size/motion
  values are **not** given exact pixel values by the spec — chosen to
  match the reference boards' visibly calm, low-shadow, moderately
  rounded style rather than invented per-component; documented as such
  in the file's own comments.
- Semantic tokens (`--color-primary`, `--surface-default`,
  `--text-primary`, etc.) sit on top of the raw palette, matching spec
  Section 4's "important consistency rule" — no component references a
  raw hex value.
- Theme (`src/theme/ThemeContext.tsx`): `light`/`dark`/`system`
  preference, persisted to `localStorage`, resolved via
  `prefers-color-scheme` when `system`. Dark mode redefines only the
  neutral tokens (background/surface/border/text) — semantic
  brand/status colors (success/warning/error/info/primary) are the
  **same hex value in both themes**, per spec Section 13's explicit
  rule ("Only luminance/contrast should change").

## 5. WAMORA assets used

Source: `wamora-design-assets/assets/brand/` and
`wamora-design-assets/assets/reference/wamora-frontend-reference.png`
(the design package's own README/ASSET-INTEGRATION-GUIDE.md confirm
these are reference-quality crops, not yet approved SVG masters — see
Section 12 of both). Four production PNGs were cropped from the supplied
reference images using Pillow (pixel crop only — no recoloring,
redrawing, or distortion) and placed at `frontend/src/assets/brand/`:

| File | Source crop | Use |
|---|---|---|
| `wamora-logo-horizontal-light.png` | Already-isolated `assets/brand/wamora-logo-reference.png`, used as-is | Sidebar (expanded), login panel |
| `wamora-logo-horizontal-dark.png` | Cropped from the "Logo (Dark Background)" swatch in `wamora-frontend-reference.png` | Reserved for dark-surface placements (not currently used — sidebar dark mode still uses the light-background logo assets against the dark sidebar surface, since the sidebar surface color in dark mode is `#1E293B`, not near-black; flagged for design review) |
| `wamora-mark-primary.png` | Cropped from `assets/brand/wamora-favicon-reference.png`'s 128×128 icon | Collapsed sidebar, favicon |
| `wamora-mark-dark.png` | Cropped from `assets/brand/wamora-app-icon-reference.png`'s "Dark Background" variant | Reserved, same caveat as above |

**NEEDS DESIGN REVIEW, not silently resolved**: the design spec's logo
rules (Section 3) name a "dark-background logo" variant but don't
specify exactly which surfaces count as "dark" for this purpose (the
sidebar's own dark-mode surface color, `#1E293B`, is a lighter dark than
the near-black swatch the reference logo was designed against). The
`Logo` component currently switches purely on the app's light/dark theme
preference, which may not be the visually-correct trigger. Flagged
rather than guessed at further.

Favicon: a 64×64 PNG derived from the primary mark (`frontend/public/favicon.png`), `index.html` updated accordingly. Browser tab title changed from the scaffold's "frontend" to "WAMORA" (design spec Section 2: "Avoid reverting to the old generic product name").

Old Vite scaffold assets (`react.svg`, `vite.svg`, `hero.png`, `favicon.svg`, `icons.svg`) removed — none were referenced by anything after `App.tsx` was replaced.

## 6. API integrations

| Call | Endpoint | Auth | Status |
|---|---|---|---|
| Login | `POST {VITE_DJANGO_BASE_URL}/api/auth/login/` | none (credential check itself) | **IMPLEMENTED**, real |
| WAHA reachability | `GET {VITE_BFF_BASE_URL}/health` | none | **IMPLEMENTED**, real |
| Backend liveness | `GET {VITE_DJANGO_BASE_URL}/api/health/` | none | **IMPLEMENTED**, real |
| Database health | `GET {VITE_DJANGO_BASE_URL}/api/health/database/` | none | **IMPLEMENTED**, real |
| Session status | `GET {VITE_BFF_BASE_URL}/api/sessions/{session}/status` | Bearer JWT, `reading` scope | **IMPLEMENTED**, real |

**Redis health — DEPENDENCY, not implemented**: the design spec's
dashboard reference shows a Redis card; no Redis health endpoint exists
anywhere in `backend/apps/core/` (confirmed by direct inspection). The
Dashboard omits this card entirely rather than fabricating a "Healthy"
status for a check that was never made (task Section 14: "Do not fake
successful API behavior").

**New, non-secret config surfaced**: `VITE_WAHA_SESSION_NAME` was added
(frontend/.env, frontend/.env.example) because the BFF's own status
endpoint requires the caller to already know the session name — there is
no "list sessions" endpoint to discover it from, since the BFF is
scoped to exactly one configured session (Phase 6 contract Section 6).
Not a secret — mirrors the BFF's own `WAHA_SESSION_NAME`.

All frontend→WAHA traffic goes through the BFF only; the frontend never
holds a WAHA API key, `INTERNAL_SERVICE_KEY`, or any Django credential —
verified directly (Section 10 below).

## 7. Authentication integration

Implements exactly the Phase 6 v1 contract, nothing invented:

- `POST /api/auth/login/` → `{access_token, token_type, expires_in}` —
  matches `apps/authn/views.py`/`serializers.py` field-for-field (read
  directly, not assumed).
- Token stored in `sessionStorage` (not `localStorage`) — a documented
  choice, not specified by Phase 6 (which governs server-side
  signing/verification, not frontend storage), reasoned by analogy to
  `docs/generated/PHASE-6-ARCHITECTURE-CONTRACT.md` Section 10's own
  "avoid localStorage for anything long-lived" guidance. **No refresh
  logic was implemented** — Phase 6 v1 has none (contract Section 4,
  confirmed in the post-audit-fix round); the 8-hour token's `exp` claim
  is used to auto-sign-out client-side when it lapses, matching the
  contract's own stated behavior ("re-login required once expired").
  `AuthContext` decodes the JWT payload **for UI purposes only**
  (showing sign-in state, timing the auto-logout) — this is explicitly
  documented in code as not a verification step; the BFF/Django remain
  the only components that verify a token's signature.
- `Authorization: Bearer <token>` attached to the one authenticated call
  Phase 7 makes (session status).

## 8. Responsive behavior

Implemented per spec Section 14's three conceptual ranges (mobile
<640px, tablet 640–1023px, desktop ≥1024px — breakpoints documented in
`tokens.css`, applied as literal `@media` queries since CSS custom
properties cannot be used inside a media-query condition):

- Sidebar becomes an off-canvas drawer with a backdrop below 1024px,
  toggled from the `TopBar`'s hamburger button — matches spec Section
  14's "sidebar becomes navigation drawer... where appropriate."
- Dashboard health-row uses `grid-template-columns:
  repeat(auto-fill, minmax(220px, 1fr))`, so cards reflow rather than
  overflow horizontally at any width.
- No component sets a `min-width` wider than the mobile viewport.

**NOT independently visually verified** — see Section 9.

## 9. Light/dark mode verification

**Implemented, NOT visually verified.** No browser or screenshot tool
was available in this environment (checked — none of the available
tools can render or screenshot a running web app). What *was* done
instead:

- Every token file value was cross-checked against
  `WAMORA-FRONTEND-DESIGN-SPEC.md`'s explicit hex table, not eyeballed
  from an image.
- The five supplied reference boards were inspected directly (via image
  viewing) during planning to confirm the token/component choices match
  the approved visual language before writing any code.
- The dev server was started and every route's module was confirmed to
  compile and serve successfully (`curl` against each page's Vite-transformed
  module returned `200` for all 8 routes) — this proves the app boots
  without a build/runtime-import error, but is **not** the same as
  confirming it *looks* correct in a browser.

**This task's own instruction — "Do not claim pixel-perfect matching
unless it was actually visually verified" — is honored by not claiming
it.** Recommend a manual visual pass (or providing browser/screenshot
tooling) before treating this as design-approved.

## 10. Testing results

- **TypeScript type-check** (`npx tsc -b --noEmit`): clean, 0 errors.
- **Production build** (`npm run build`): succeeds; no warnings (fixed
  one `INEFFECTIVE_DYNAMIC_IMPORT` warning found during the build by
  switching `auth.ts` to a static import). Bundle: ~285 KB JS (91 KB
  gzip), ~14 KB CSS (3 KB gzip), four brand PNGs (~180 KB combined).
- **Lint** (`npm run lint`, oxlint): 0 errors, 4 warnings — all
  `react(only-export-components)`/`react(set-state-in-effect)` style
  suggestions about co-locating a context's Provider and hook in one
  file (a common, accepted React pattern); none indicate a correctness
  bug.
- **Frontend tests**: none exist in this repository (no test runner was
  configured in this phase or any prior one) — task Section 19 says
  "frontend tests where configured"; none are, so none were run or
  added. **DEPENDENCY**: a test runner (e.g. Vitest, matching the BFF's
  choice) is not yet set up for `frontend/` — flagged, not silently
  skipped.
- **Security check** (task Section 20): grepped the production
  `dist/assets/*.js` output directly for `WAHA_API_KEY`,
  `INTERNAL_SERVICE_KEY`, `DB_PASSWORD`, `DJANGO_SECRET_KEY`,
  `JWT_PRIVATE_KEY`, and `sha512:` — zero matches. Confirmed only
  non-secret `VITE_`-prefixed values (base URLs, the session name) were
  inlined into the bundle.

## 11. Build results

`npm run build` output (summarized): `tsc -b && vite build` completed in
under 300ms of Vite's own build step, 1945 modules transformed, no
errors, no warnings. Build artifact was removed after verification
(gitignored, not meant to be committed).

## 12. Known limitations

1. **No visual/browser verification was performed** — no such tool was
   available (Section 9).
2. **Login page has no approved design reference** — built from
   already-approved tokens/components only, not copied from a mockup;
   needs design review (flagged in `LoginPage.tsx` itself and here).
3. **The "WhatsApp" nav destination's intended content is undefined** by
   any functional or visual spec — left as a placeholder rather than
   guessed at.
4. **Dark-background logo variant's trigger condition is unclear** — see
   Section 5.
5. **No frontend test runner exists yet.**
6. **`Tooltip`, `Modal`, `Toast`, and other spec-listed primitives are
   not built** — none of Phase 7's own pages need them yet (Section 3).

## 13. Dependencies on later phases

| Capability | Phase | What Phase 7 leaves ready for it |
|---|---|---|
| Inbox/chat data + UI | 8 | Route, shell, placeholder page already exist |
| Session *control* (start/stop/restart/logout/QR) | 10 | Read-only status card and the BFF endpoints (Phase 6) are already in place; only the action UI is deferred |
| Reports data | — (undefined) | Route/placeholder exist |
| Settings/user administration | — (undefined) | Route/placeholder exist |
| Blast | 11 | Not referenced in the design spec's sidebar at all; nothing built or routed |
| Security hardening (rate limiting, etc.) | 12 | Not touched |
| Redis health | — (undefined, no endpoint exists) | Dashboard card intentionally omitted rather than faked |

## 14. Files changed

63 files created/modified, all within `frontend/` (new components, pages,
lib/, styles/, theme/, routes/, brand assets, `index.html`, `.env`,
`.env.example`) plus removal of 5 unused Vite-scaffold files. Full list
available via `find frontend -type f` — omitted here for length; every
path is under `frontend/src/`, `frontend/public/`, or `frontend/.env*`.
**Nothing under `backend/`, `bff/`, or `docs/generated/PHASE-6-*` was
touched** — confirmed by file-modification-time check against the most
recent Phase 6 report, returning zero results.

**Not updated this round, flagged rather than silently left stale**:
root `README.md`'s "Project status" section still describes Phase 6 as
"not yet implemented" and Phase 7 as "not started" — both now inaccurate.
Not fixed here since this task's own documentation deliverable is
specifically this report, not a README sync, and "do not start unrelated
refactoring" argues against expanding scope unprompted; recommend a
short follow-up pass.

## 15. Confirmation: Phase 8 was not started

No chat/message UI, no Django chat/message read-endpoint integration, no
inbox functionality beyond the placeholder page exists. Confirmed.

---

## PHASE 7 IMPLEMENTATION COMPLETE

**Summary of what was actually implemented**: the WAMORA application
shell (sidebar, top bar, responsive collapse/drawer), a semantic
light/dark theme system built exactly from the approved design tokens,
WAMORA branding (logo/favicon/title) sourced from the supplied reference
assets, ten reusable UI primitives, real authentication against the
actual Phase 6 login endpoint, a functional Dashboard wired to the three
real health checks that exist, read-only session status presentation
wired to the real Phase 6 BFF endpoint, and six routed pages (three real,
one contract-undefined placeholder, two later-phase placeholders) — all
using Lucide icons per the spec's mapping, all built on the same token
set, no ad-hoc colors, no mixed icon families.

**Test/build results**: `tsc` clean, production build clean (0
warnings after one fix), lint clean (0 errors, 4 style warnings), no
secret reachable in the built bundle (grepped directly).

**Known limitations**: no visual/browser verification was possible in
this environment; the login page and the "WhatsApp" nav destination both
lack an approved design reference and are flagged, not silently
invented past what the token system already specifies; no frontend test
runner exists yet.

**Later phases were not started** — confirmed directly (Section 15).
