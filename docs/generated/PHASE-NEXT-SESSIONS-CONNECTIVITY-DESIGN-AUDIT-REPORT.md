# Sessions Connectivity Indicator Extension — Design Audit (Read-Only)

**Scope.** Read-only design audit only. No file was modified, no
container was started/stopped/restarted, no Compose/`.env`/Dockerfile
was touched, no dependency was added. The currently-running development
stack was not disturbed. Every claim below is tagged **VERIFIED
DIRECTLY** (read from current source this task), **INFERRED FROM
SOURCE** (a conclusion drawn from verified facts, not itself a literal
quote), or **NOT VERIFIED** (could not be confirmed from source alone).

---

## 0. A Scope Ambiguity Found and Resolved by Direct Investigation

**This section exists because the task's own title and its investigation
steps point in two different directions, and this audit found enough
evidence to resolve which one the source actually supports.**

The prior roadmap audit's recommendation (`NEXT-PHASE-ROADMAP-AUDIT-REPORT.md`
Section 8) named this slice "Sessions Connectivity Indicator Extension,"
meaning: extend Inbox's `reportPollOutcome`/`ConnectivityIssue` pattern
(Signal A — "is my own request to the backend succeeding") to
`SessionsPage.tsx`, which currently has no such indicator.

**This task's own investigation steps point somewhere else**: Section 3
explicitly says "Locate DashboardPage and determine exactly where the
connectivity indicator should appear," and Section 6 asks for
`connected`/`disconnected` states — vocabulary that describes a WAHA
**session's** state (is WhatsApp itself connected), not API
reachability (Inbox's indicator has no "connected" state at all — only
`unreachable`/`unauthorized`, because it was never about WhatsApp
connection status in the first place).

**VERIFIED DIRECTLY, this task**: these are two materially different
features, not two names for the same one:

| | Inbox's existing indicator (Signal A) | What this task's Section 3/6 describes |
|---|---|---|
| Question it answers | "Is my browser's connection to BFF/Django working right now?" | "Is the configured WhatsApp session connected?" |
| Data source | Any existing poll's own `ApiResult.ok` | `GET /api/sessions/:session/status` (WAHA's own reported session state) |
| States | `unreachable`, `unauthorized` | `WORKING`/`SCAN_QR_CODE`/`STARTING`/`STOPPED`/`FAILED`/unknown (already enumerated by `mapWahaStatus`, Section 2) |
| Existing precedent | `InboxPage.tsx`'s `reportPollOutcome` | `SessionsPage.tsx`'s own `StatusBadge`+`mapWahaStatus` display, **not** its (missing) connectivity handling |

**This audit proceeds on the interpretation the task's own investigation
steps actually support**: exposing the **WAHA session's connectivity/status**
(not API reachability) on the **Dashboard** — while still fully
auditing Inbox's connectivity pattern (Section 2, as explicitly
requested) and explicitly stating where it does and doesn't apply
(Section 5). If this resolution is wrong, no harm was done — nothing
was implemented either way, and Section 11 restates both readings.

---

## 1. Existing Session/Connectivity Implementation

**VERIFIED DIRECTLY**, `frontend/src/pages/SessionsPage.tsx` re-read in
full this task:

- **API/client/helper**: `getSessionStatus(sessionName)` from
  `frontend/src/lib/bffApi.ts` — calls
  `GET /api/sessions/:session/status` through the **BFF** (Frontend →
  BFF → WAHA), not Django. Confirmed by import: `SessionsPage.tsx`
  imports `getSessionStatus` from `'../lib/bffApi'`, not `djangoApi`.
- **Response shape**: `SessionStatus` (from `bffApi.ts`) — includes at
  least `session: string` and `status?: string`, confirmed by
  `SessionsPage.tsx`'s own usage (`displayedStatus.session`,
  `displayedStatus.status`).
- **Already available through**: BFF, already live, already the single
  source of truth `SessionsPage.tsx` itself uses today — **no new
  endpoint, no Django change, no WAHA change needed** to read the same
  data again elsewhere in the frontend.
- **Historical context, re-verified this task**: `docs/generated/PHASE-8-DASHBOARD-DATA-UI-AUDIT-REPORT.md`
  (re-read this task, lines 91-98, 131) already documented that
  real-time session status "genuinely exists, but only live, per-session,
  via the BFF's already-built `GET /api/sessions/:session/status`" — and
  explicitly distinguished this from a **true multi-session summary**,
  which does need BFF work (the BFF is "single-session-scoped today").
  **This project's actual configuration is single-session** — `frontend/src/lib/config.ts:9`,
  `wahaSessionName: import.meta.env.VITE_WAHA_SESSION_NAME`, a single
  string, not a list — consistent with `docs/00-MASTER-SPEC.md`'s own
  "Initial session: 1; expected max 2-3" scale note. **For the single
  configured session, the data already exists and needs no new backend
  work** — the Phase 8 audit's "needs BFF work" conclusion applies only
  to a *true multi-session* summary, not to showing the one session this
  project is actually configured for today.

---

## 2. Existing Inbox Precedent (Fully Audited, Per the Task's Own Request)

**VERIFIED DIRECTLY**, `frontend/src/pages/InboxPage.tsx` re-read this
task:

- **Data source**: any existing poll's `ApiResult<T>` (chat list,
  messages, sync status) — not a dedicated endpoint of its own.
- **Helper/function**: `reportPollOutcome(result)` — a closure-scoped
  function defined inline inside the `InboxPage` component (not
  exported, not in a shared module — re-confirmed unchanged since the
  earlier Phase C design audit's own finding on this exact point).
- **TypeScript types**: `type ConnectivityIssue = 'unreachable' | 'unauthorized'`.
- **State mapping**: `connectivityFailureCountRef` (a `useRef` counter,
  not `useState`, to avoid re-render on every tick) + `CONNECTIVITY_FAILURE_THRESHOLD = 2`
  consecutive non-auth failures before showing anything; `unauthorized`
  shows immediately (no threshold — retrying won't fix a `401`/`403`).
- **UI component**: inline JSX, `<p className="wa-inbox__connectivity" role="status">`
  — not a separate reusable component.
- **CSS/classes**: `wa-inbox__connectivity` in `InboxPage.css` — scoped
  to that page.
- **Error/loading behavior**: silent below threshold (deliberately, to
  avoid flicker on a single blip); resets to `null` on any success.

**Can this be reused directly for the Dashboard's session status?**
**No — it answers a different question** (Section 0's table). It could
be reused if the Dashboard also needed an "is my connection to
BFF/Django working" indicator, but that is not what
`SessionStatus`/`mapWahaStatus` represent, and the task's own Section 6
vocabulary (`connected`/`disconnected`) doesn't match this pattern's own
vocabulary (`unreachable`/`unauthorized`) at all.

**What Inbox's pattern *does* usefully inform**: the general discipline
of "don't show a raw error immediately, wait for a threshold, never
invent a state the backend didn't report" — a design principle, not
literal reusable code, and one `SessionsPage.tsx`'s own
`mapWahaStatus`-based display already follows independently (Section 3).

---

## 3. Target Dashboard

**VERIFIED DIRECTLY**, `frontend/src/pages/DashboardPage.tsx` re-read
in full this task (current state, including this session's own 9.1F
Redis-card addition):

- **Exact location**: Row 2 (`section.wa-dashboard__row2`) currently
  renders `MessagesCard`, `ActivityCard`, and a **placeholder** third
  card:
  ```tsx
  <Card className="wa-metric-card">
    <div className="wa-health-card__icon wa-health-card__icon--blue-deep">
      <Smartphone .../>
    </div>
    <div className="wa-metric-card__body">
      <p className="wa-health-card__title">WhatsApp Sessions</p>
      <EmptyState icon={Smartphone} title="Not available yet"
        description="A multi-session summary needs BFF work beyond this phase's scope — see the Phase 8 dashboard audit." />
    </div>
  </Card>
  ```
  This is **the exact card** Section 3's "where the connectivity
  indicator should appear" question resolves to — it is already
  reserved, already positioned, already has an icon, and its own
  description text is what Section 1 found to be no longer fully
  accurate (it's correct for *multi-session*, not for *this session*).
- **Does Dashboard already have session information available?**
  **Not fetched yet** — no `useApiQuery` call for session status exists
  anywhere in `DashboardPage.tsx` (re-confirmed via grep this task,
  Section 4 of the prior roadmap audit, still true).
- **Is a new API request necessary?** **Yes, one new `useApiQuery` call**
  — but reusing the **existing** `getSessionStatus()` function
  (`bffApi.ts`), not a new endpoint.
- **Can an existing query/helper be reused?** The **function** yes
  (`getSessionStatus`), the **card/rendering shape** no —
  `HealthCard` (Row 1) expects `{ok: boolean, detail: string}`, which
  doesn't fit a multi-value WAHA status cleanly (the same "boolean vs.
  enum" friction the earlier `PHASE9-NEXT-SLICES-DESIGN-AUDIT-REPORT.md`
  Section 8 already identified for `SyncStatus`, applying identically
  here since `SessionStatus.status` is likewise not binary). The
  existing **Row 2 placeholder card's own markup** (not `HealthCard`) is
  the natural container — it already uses `EmptyState`, which would
  simply be replaced by a real `StatusBadge`+`mapWahaStatus` rendering
  when data is present, matching `SessionsPage.tsx`'s own display
  pattern exactly (Section 1).

---

## 4. Architecture — What Requires a Change

**VERIFIED DIRECTLY / INFERRED FROM SOURCE**, explicit per-component
answer:

| Component | Change required? | Basis |
|---|---|---|
| Django backend | **No** | Data already served by BFF, sourced from WAHA directly — Django was never in this path for session status (`SessionsPage.tsx` imports from `bffApi`, not `djangoApi`) |
| BFF | **No** | `GET /api/sessions/:session/status` already exists, already used, already correct for one session |
| Frontend API client (`bffApi.ts`) | **No** | `getSessionStatus()` already exported, already typed (`SessionStatus`) |
| Frontend `DashboardPage.tsx` | **Yes** | New `useApiQuery` call + replace the placeholder card's inner content |
| Shared components | **Possibly, minor** | `StatusBadge`/`mapWahaStatus` already generic and reusable as-is (Section 2's finding that this is a design *principle*, not new code, applies) — no new component class is required, though see Section 5 for the one real open question |
| CSS | **Possibly, minor** | The placeholder card already has `wa-metric-card` styling; a status badge + label likely fits inside the existing `wa-health-card__title-row`-style markup already used elsewhere (`DashboardPage.tsx` itself, `SessionsPage.tsx`) — **no new CSS file or class category is anticipated**, though this is not fully certain without writing the JSX (see Section 8's scope note) |
| Docker/Compose | **No** | Confirmed — nothing in this slice touches any Docker file |
| Environment variables | **No** | `VITE_WAHA_SESSION_NAME` already exists and is already read by `SessionsPage.tsx`; the same value would be reused |
| Dependencies | **No** | No new package of any kind |

---

## 5. Avoid Duplication

**This is an implementation-level decision, not an architecture
decision** — confirmed by this audit's own investigation, matching the
task's own framing.

Because Section 0/2 established that Inbox's `reportPollOutcome` pattern
does **not** apply here (different question, different vocabulary), the
"share vs. duplicate" question that mattered for the *original*
Sessions-extension framing (Section 0) is **moot for this
interpretation** — there is no Inbox code to share or duplicate, because
the actual reusable precedent is `SessionsPage.tsx`'s own
`StatusBadge`+`mapWahaStatus` **rendering pattern**, which is already
just JSX using already-shared, already-generic components
(`StatusBadge`, `mapWahaStatus`) — reusing it means writing similar JSX
in `DashboardPage.tsx`, not extracting a new shared component. A tiny,
genuinely optional refinement (not required, not escalated): if the
exact same three-line JSX snippet (`StatusBadge status={mapWahaStatus(...)} label={...}`)
ends up literally duplicated between `SessionsPage.tsx` and
`DashboardPage.tsx`, it could be pulled into a tiny shared
`<WahaStatusBadge status={...} />` wrapper — a naming/placement detail,
not an architecture question, left for the implementation task itself.

---

## 6. Loading/Error/Degraded States

**Determined by direct reuse of two already-established, already-shipped
conventions — no new vocabulary invented:**

| State | Source pattern | Rendering |
|---|---|---|
| Loading | `useApiQuery`'s own `status === 'loading'` (already used everywhere) | `LoadingState` (already used in the placeholder's sibling cards) |
| Connected | `SessionStatus.status === 'WORKING'` → `mapWahaStatus` → `'working'` | `StatusBadge status="working" label="WORKING"` (or a friendlier label — a wording choice, not escalated) |
| Disconnected | `'STOPPED'` → `mapWahaStatus` → `'offline'` | `StatusBadge status="offline" label="STOPPED"` |
| Other known WAHA states | `SCAN_QR_CODE`/`STARTING`/`FAILED` → already mapped by `mapWahaStatus` (Section 1) | Same `StatusBadge` call, already-existing `StatusKind` values (`scan_qr`/`starting`/`error`) |
| Unknown/unavailable (no session configured) | `!sessionName` (already checked by `SessionsPage.tsx` itself, line 174) | Reuse the same `EmptyState` pattern the placeholder already has, for the "not configured" case specifically |
| API error (BFF unreachable, WAHA down, etc.) | `useApiQuery`'s `status === 'error'` | `ErrorState` (already used by `MessagesCard`/`ActivityCard` in the very same `DashboardPage.tsx` file) or the simpler `StatusBadge status="error" label="Unreachable"` pattern `HealthCard` uses — either already-established; not a new pattern either way |

**No new terminology, no new taxonomy** — every state above already has
an existing, shipped rendering somewhere in this same codebase.

---

## 7. Tests

**VERIFIED FROM SOURCE (re-confirmed, unchanged since every prior
frontend-touching phase this session)**: `frontend/package.json` still
has no test script, no test framework in `devDependencies`. **No test
framework will be proposed or added** — matching this task's own
explicit instruction. Verification would follow the exact same
established pattern used for Phase 9.1F: `npm run lint` + `npm run
build`, plus a live check against the running development stack's
served module (not a browser).

---

## 8. Scope — Smallest File Set

**IMPLEMENTATION REQUIRED** (if/when this proceeds):
- `frontend/src/pages/DashboardPage.tsx` — one new `useApiQuery` call
  (reusing `getSessionStatus`), replacing the placeholder card's inner
  `EmptyState` with a real status rendering when data is available (and
  keeping `EmptyState` for the genuine "no session configured" case).

**POSSIBLY REQUIRED, not certain without writing the JSX**:
- `frontend/src/pages/DashboardPage.css` — only if the existing
  `wa-metric-card`/`wa-health-card__title-row` classes don't already
  produce an acceptable layout for a status badge inside that specific
  card; Section 4 leans "no" but this audit did not write the JSX to
  confirm definitively.

**NOT REQUIRED**:
- Any backend file.
- Any BFF file.
- `frontend/src/lib/bffApi.ts` (function already exists).
- `frontend/src/components/ui/StatusBadge.tsx` (`mapWahaStatus` already
  covers every WAHA status this project reports).
- `frontend/src/pages/SessionsPage.tsx` (not touched — its own
  connectivity/error handling, if ever addressed, per the *original*
  Section 0 reading, would be a **separate, distinct** slice from this
  one).
- Any Docker/Compose/`.env`/dependency file.

---

## 9. Regression Risk

**VERIFIED / INFERRED FROM SOURCE**:

- **Inbox**: zero risk — not touched, and Section 2 confirmed its
  pattern isn't being reused, so no shared-code risk either.
- **Existing Dashboard health cards** (WAHA/Backend/PostgreSQL/Redis,
  Row 1): zero risk — this change is confined to Row 2's third card;
  Row 1 is untouched.
- **WAHA communication**: read-only — `getSessionStatus()` is already a
  GET-only call, already made by `SessionsPage.tsx` today; adding a
  second caller doesn't change WAHA's load profile in any qualitatively
  new way (same endpoint, same method, now called from two pages
  instead of one, both fetch-once-on-mount per Section 4's finding that
  no polling is proposed — consistent with every other Dashboard card,
  Phase 9.1F's own established precedent).
- **Authentication**: unaffected — `getSessionStatus()`'s own auth
  requirements (whatever they already are for `SessionsPage.tsx`) are
  unchanged by calling it from a second page.
- **BFF**: unaffected — no BFF code changes proposed.
- **Backend**: unaffected — no backend code changes proposed.
- **Docker development environment**: unaffected — confirmed no file
  in scope.

---

## 10. USER DECISIONS REQUIRED

**One material item — the scope ambiguity itself (Section 0).**

1. **Confirm which feature "Sessions Connectivity Indicator Extension"
   actually means**, since this audit found direct evidence that the
   task's own title and its own investigation steps point to two
   different features (Section 0's table):
   - **(a) Dashboard WAHA session status card** (what this audit's
     Sections 1-9 designed, following the task's own explicit "Locate
     DashboardPage"/`connected`/`disconnected` instructions) — replacing
     the Row 2 placeholder with real, single-session status data via the
     already-existing `getSessionStatus()`.
   - **(b) SessionsPage.tsx API-connectivity indicator** (the *original*
     roadmap-audit framing — extending Inbox's `reportPollOutcome`
     pattern to `SessionsPage.tsx`'s own silent-on-failure polling,
     Section 2/9 of `PHASE-G-DEVELOPMENT-READINESS-AUDIT-REPORT.md`'s
     antecedent and the prior roadmap audit's own Section 4 finding that
     `SessionsPage.tsx` has zero `reportPollOutcome`/`ConnectivityIssue`
     matches today).
   - **This is escalated because it materially changes which files
     change and what the feature actually shows the user** — not a
     cosmetic/naming/formatting choice. Both are legitimate, small,
     low-risk slices; they are simply **not the same slice**, and
     implementing the wrong one would not satisfy whichever was actually
     intended.
   - **This audit's own recommendation, if a single answer must be
     picked**: **(a)**, because it is what this task's own investigation
     steps explicitly directed the audit to examine (Section 3's "Locate
     DashboardPage," Section 6's `connected`/`disconnected` vocabulary),
     and because it closes a card that has sat as an explicit, named
     placeholder in `DashboardPage.tsx` since the Phase 8 dashboard work
     — a more visible, more complete-feeling gap than Sessions' silent
     polling failure. **(b) remains fully valid and ready for its own
     audit** if that is what was actually intended instead.

No decision regarding architecture, a new dependency, an external
service boundary, or security behavior arose from this audit —
consistent with Section 4's finding that neither reading requires any
of those.

---

## 11. Final Recommendation

**Ready for implementation — for interpretation (a) (Dashboard WAHA
session status card), pending your confirmation per Section 10.**
Interpretation (b) (Sessions page connectivity indicator) is separately
ready too, using the already-existing Inbox pattern as its own direct
precedent, but was not the primary focus this audit's own investigation
steps directed toward.

**Exact files expected to change** (interpretation (a)):
- `frontend/src/pages/DashboardPage.tsx` (required).
- `frontend/src/pages/DashboardPage.css` (possibly, unconfirmed — Section 8).

**Exact files that should NOT change**: any backend file, any BFF file,
`frontend/src/lib/bffApi.ts`, `frontend/src/components/ui/StatusBadge.tsx`,
`frontend/src/pages/SessionsPage.tsx`, `frontend/src/pages/InboxPage.tsx`,
any Docker/Compose/`.env`/dependency file.

**Implementation order** (once Section 10 is resolved in favor of (a)):
1. Add the `useApiQuery(() => getSessionStatus(sessionName), [sessionName])`
   call to `DashboardPage.tsx`.
2. Replace the placeholder card's `EmptyState` branch with a
   `StatusBadge`+`mapWahaStatus` rendering when data is present, keeping
   `EmptyState` for the `!sessionName` case (mirroring
   `SessionsPage.tsx`'s own branching exactly).
3. Update the placeholder's own description text, since "needs BFF work
   beyond this phase's scope" is no longer the accurate reason once
   single-session data is wired in (Section 1) — only a true
   multi-session summary still needs BFF work.

**Verification plan**: `npm run lint` (0 errors expected), `npm run
build` (`tsc -b && vite build`, 0 errors expected), a live
`curl`-against-the-Vite-dev-server check of the modified module
(matching Phase 9.1F's own documented substitute for browser
verification), and a `git diff --stat` scope check confirming only the
files named above changed.

**No file was modified, no container was touched, and nothing was
implemented in producing this report.**

**STOP.** Not proceeding to 9.1B, the Dashboard sync-status card (a
third, still-distinct item from both this slice's readings), stuck-running
recovery, Celery liveness, staging, production, or any other phase.
Awaiting your decision on Section 10 before any implementation begins.
