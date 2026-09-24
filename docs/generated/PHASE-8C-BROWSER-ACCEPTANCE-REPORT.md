# Phase 8C — Browser Acceptance (Manual)

Documentation only. No source, configuration, `.env`, dependency, or
infrastructure file was touched to produce this report.

This report records the results of **manual browser testing performed by
you** against the currently running application, following up on the
gaps the earlier automated/API-level checks explicitly could not close
(no browser automation tool was available in this environment — see
`docs/generated/PHASE-8C-ACCEPTANCE-REPORT.md`, "Important limitation,
stated up front"). These results are **relayed and recorded here as your
own reported observations**, not independently re-verified by me in a
browser — I have no way to open one in this environment. Where a claim
overlaps with something I *did* independently verify earlier (via
`curl`/real running servers/static code inspection), that's called out
explicitly in Section 3 so the two kinds of evidence aren't conflated.

## 1. Manually verified in the browser (your report)

| # | Item | Result |
|---|---|---|
| 1 | Sidebar collapse | PASS |
| 2 | Sidebar expand/restore | PASS |
| 3 | All sidebar navigation items | PASS |
| 4 | Dashboard rendering | PASS |
| 5 | Dashboard API requests observed in Network tab: `/api/auth/me/`, `/api/health/database/`, `/health` (BFF), `/api/dashboard/messages/`, `/api/dashboard/activity/?limit=8` | all successful |
| 6 | Logout | PASS |
| 7 | Dark/light theme switching | PASS |
| 8 | Username (`udin`) persists after a browser refresh | PASS |
| 9 | Browser Console | no errors observed |
| 10 | Login/authentication flow | PASS |
| 11 | CORS | no browser CORS error observed |

These items — actual rendered layout, real DevTools Console/Network
output, live click-through, and the refresh-persistence check — were
explicitly listed as **not verifiable by me** in the prior acceptance
report and the Phase 8C frontend integration report, since this session
has no browser/screenshot tool. They are recorded here as PASS strictly
on your report, not on independent re-verification.

## 2. Known open issues, intentionally outside Phase 8 scope

| # | Item | Status | Why it's not a Phase 8 failure |
|---|---|---|---|
| 1 | WAHA health card | Degraded / Not reachable | Pre-existing infrastructure connectivity gap — no live WAHA instance is running in this local dev environment. Phase 8 never touched WAHA connectivity, and the BFF env-loading fix (`docs/generated/PHASE-8C-BFF-ENV-LOADING-FIX-REPORT.md`) explicitly distinguished "WAHA config loaded" (yes) from "WAHA reachable" (no) and did not attempt to fix reachability, by design. |
| 2 | WhatsApp Sessions dashboard card | Intentional `EmptyState` | Multi-session BFF support was explicitly out of scope for Phase 8 (`docs/generated/PHASE-8-DASHBOARD-DATA-UI-AUDIT-REPORT.md` and the Phase 8C frontend integration report both document this as a deliberate placeholder, not a bug). |

## 3. Cross-reference: items also independently verified earlier via API/runtime checks (not browser)

These overlap with Section 1's items but were separately confirmed by me
against the real running dev servers, outside a browser, using `curl`
with the actual `Authorization`/`Origin` headers a browser would send,
plus static source inspection. Listed here so it's clear which claims
rest on two independent kinds of evidence versus your browser report
alone:

- `GET /api/auth/me/` → `200 {"id":1,"username":"udin","display_name":"udin"}`
  (`docs/generated/PHASE-8C-ACCEPTANCE-REPORT.md` Section 1) — consistent
  with your browser-observed "username remains udin" result (Section 1,
  item 8).
- `GET /api/dashboard/messages/` and `GET /api/dashboard/activity/?limit=8`
  → both `200`, real (non-fabricated) data from the live dev database
  (same report, Sections 2–3).
- CORS preflight and actual response headers for `Origin:
  http://localhost:5173` on `/api/dashboard/messages/` → 
  `Access-Control-Allow-Origin: http://localhost:5173` present; the same
  origin's request to `http://evil.example.com` correctly receives no
  CORS header (same report, Section 6; further reconfirmed for the BFF's
  own `/health` specifically in
  `docs/generated/PHASE-8C-BFF-ENV-LOADING-FIX-REPORT.md` Section 11,
  after the BFF env-loading fix) — consistent with your browser-observed
  "no CORS error" result (Section 1, item 11).
- The BFF's `/health` CORS gap found during the first acceptance pass was
  root-caused and fixed in the same BFF env-loading fix report; that fix
  is what makes the BFF's own dashboard-adjacent request path (not the
  three Django dashboard endpoints, which were never affected) CORS-clean
  now.

## 4. Overall Phase 8 status

With this manual pass added to the earlier API-level verification, every
item originally listed as "not verified — needs an actual browser" in
`docs/generated/PHASE-8C-ACCEPTANCE-REPORT.md` Section "Explicitly NOT
verified in this check" now has a result on record (Section 1 above), and
both previously open technical findings (Django `JWT_PUBLIC_KEY_PATH`,
BFF `.env` loading) were root-caused and fixed in their own dedicated
reports. The two remaining items (Section 2) are documented, intentional
scope boundaries, not defects.

**No implementation change was made in this task.**

---

Do not start Phase 9 automatically.
