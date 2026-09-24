# Phase 6 — WAHA Lifecycle API Contract

Documentation/specification reconciliation only. No application code,
models, migrations, frontend, BFF implementation, or `docker-compose.yml`
was modified. No destructive or state-changing operation was invoked
against `test_session` or any other WAHA session in this round. Phase 6 is
not implemented by this document. Phase 7 is not started.

## 1. Official WAHA source

- Sessions/lifecycle: <https://waha.devlike.pro/docs/how-to/sessions/>
  (fetched twice this round: once for the general lifecycle/QR/status
  overview, once specifically for request/response body detail on
  start/stop/restart/logout/delete).
- Security/authentication: <https://waha.devlike.pro/docs/how-to/security/>

These are the public docs site's **current** content as of this task's
fetch (2026-09-23). The docs site is not version-pinned in the fetched
pages themselves — see Section 2's caveat.

## 2. WAHA version relevant to this project

- **Deployed**: `2026.9.1`, image `devlikeapro/waha:gows` — confirmed
  live in every prior verification round, unchanged.
- **Caveat, stated plainly rather than assumed away**: the fetched
  documentation pages do not display a version selector or per-version
  changelog in what was retrieved, so this report cannot independently
  confirm the fetched lifecycle/security docs describe exactly
  `2026.9.1`'s behavior versus a newer or older version. This is treated
  as **DOCUMENTED** (per Section 3's category definitions) rather than
  **LIVE VERIFIED**, precisely because of this gap. If the deployed
  version ever diverges from current docs, that would only be caught by
  actual live testing (Section 11/12) or an explicit version-changelog
  check — neither performed here.

## 3. Engine

**GOWS** — the fetched documentation states all listed session-management
and authentication endpoints support **WEBJS, WPP, NOWEB, and GOWS**
alike (the only documented exception is `/api/screenshot`, which supports
only WEBJS/WPP — not relevant to this project's GOWS deployment). This
directly resolves the open question from
`docs/generated/PHASE-6-WAHA-LIFECYCLE-VERIFICATION.md` about whether
lifecycle endpoints are GOWS-supported at all: **yes, per documentation**.

## 4. Category definitions (used throughout this document)

- **DOCUMENTED / IMPLEMENTATION-READY** — path, method, and semantics are
  explicitly stated by official WAHA documentation, with documented GOWS
  support. Sufficient to design against; not yet exercised against this
  deployment.
- **LIVE VERIFIED** — this project has actual deployment evidence (a real
  request/response against `<TENCENT_WAHA_HOST>:3000`, session `test_session`).
- **NOT LIVE TESTED** — documented (per above) but deliberately not
  invoked against `test_session`, because invocation would be disruptive to
  a real, in-use session. This is a distinct category from "unknown
  endpoint" — the contract is known; only live confirmation is missing.

## 5. Lifecycle endpoint table

| Operation | Method | Path | GOWS support | Request body | Response | Category |
|---|---|---|---|---|---|---|
| List sessions | GET | `/api/sessions` | Documented | none | array of session objects | LIVE VERIFIED |
| Get session | GET | `/api/sessions/{session}` | Documented | none | session object (`name`, `status`, `engine`, `me`, `config`) | LIVE VERIFIED |
| Get "me" | GET | `/api/sessions/{session}/me` | Documented | none | account info object | LIVE VERIFIED |
| Create session | POST | `/api/sessions` | Documented | session config (`name`, `start`, `config`, ...) | session object, e.g. `{"name": "...", "status": "STARTING", "engine": {...}}` | DOCUMENTED / IMPLEMENTATION-READY (not used by this project — `test_session` already exists) |
| Update session | POST | `/api/sessions/{session}/` | Documented | partial session config | session object | DOCUMENTED / IMPLEMENTATION-READY — not proposed for BFF exposure (see Section 8) |
| **Start session** | POST | `/api/sessions/{session}/start` | Documented | **none** (curl example shows an empty body) | not shown by docs; expected to mirror the session object shape | DOCUMENTED / IMPLEMENTATION-READY, **NOT LIVE TESTED** |
| **Stop session** | POST | `/api/sessions/{session}/stop` | Documented | **none** | not shown by docs | DOCUMENTED / IMPLEMENTATION-READY, **NOT LIVE TESTED** |
| **Restart session** | POST | `/api/sessions/{session}/restart` | Documented | **none** | not shown by docs | DOCUMENTED / IMPLEMENTATION-READY, **NOT LIVE TESTED** |
| **Logout session** | POST | `/api/sessions/{session}/logout` | Documented | **none** | not shown by docs | DOCUMENTED / IMPLEMENTATION-READY, **NOT LIVE TESTED** |
| Delete session | DELETE | `/api/sessions/{session}` | Documented | **none** | not shown by docs | DOCUMENTED / IMPLEMENTATION-READY, **NOT LIVE TESTED** — and **not proposed for BFF exposure at all** (see Section 8) |

**Documented behavioral semantics** (quoted/paraphrased from the fetched
page, not independently re-derived):

- **Start**: idempotent — calling it repeatedly starts the session only
  if it isn't already running.
- **Stop**: idempotent — stops the session only if running. **Does not
  log out or delete** the session (WhatsApp pairing is preserved).
- **Restart**: if the session is already running (status not `STOPPED`),
  it is stopped, then started.
- **Logout**: if the session is running, it is logged out **and then
  started again from scratch** — i.e. logout does not leave the session
  in a stopped state; it transitions toward a fresh `SCAN_QR_CODE`
  pairing flow. Removes authentication/pairing data; preserves session
  *configuration* (webhooks, engine settings, etc.).
- **Delete**: also logs out (if paired) and stops (if running) before
  removing the session's configuration and data entirely — the most
  destructive of the five, and irreversible from WAHA's side (session
  would need to be recreated).

**Response body gap, stated honestly**: the fetched documentation shows a
response example only for **Create**
(`{"name": ..., "status": ..., "engine": {...}}`); it does not show
explicit response JSON for start/stop/restart/logout/delete. The
project's existing live evidence for `GET /api/sessions/{session}`
(session object with `status`, `engine.gows.connected`, `me`) is the best
available basis for what these likely return, but this is an
**inference, not a confirmed response schema** for the five
state-changing operations themselves. Flagged as a remaining gap in
Section 14, not papered over.

## 6. QR / pairing endpoint contract

| Operation | Method | Path | Request | Response | Category |
|---|---|---|---|---|---|
| Get QR code | GET | `/api/{session}/auth/qr` | none (format via query/header — image, base64, or raw, per docs) | QR code, in the requested format | DOCUMENTED / IMPLEMENTATION-READY, **NOT LIVE TESTED** (a prior round's probe timed out rather than 404'd against the already-paired `test_session` — see Section 12) |
| Request pairing code | POST | `/api/{session}/auth/request-code` | phone number (for phone-linking, as an alternative to scanning a QR) | pairing code | DOCUMENTED / IMPLEMENTATION-READY, NOT LIVE TESTED |
| Passkey challenge / confirm | GET/POST `/api/{session}/auth/passkey*` | — | — | — | DOCUMENTED, **not relevant to this project** — no evidence WAHA passkey auth applies to GOWS/WhatsApp pairing as used here; not proposed for the BFF |

**Confirmed from documentation**:

- QR codes expire: the first after **60 seconds**, each subsequent one
  after **20 seconds**, **up to 6 total** — meaning a client polling for
  a fresh QR needs to re-request roughly every 20–60s during an active
  pairing flow, and the flow has a hard ceiling (~160 seconds across 6
  codes) before WAHA gives up.
- QR retrieval is only meaningful while the session is in (or being
  driven toward) `SCAN_QR_CODE` status — **consistent with this
  project's prior live finding** that probing `/api/{session}/auth/qr`
  against the already-`WORKING`/paired `test_session` session produced an
  inconclusive timeout rather than a clean response. This is not proof
  of a bug; it is consistent with the endpoint's documented purpose not
  applying to an already-authenticated session. **Not re-tested this
  round**, per this task's explicit instruction not to call the QR
  endpoint unnecessarily.
- **Relationship to `SCAN_QR_CODE`**: the QR endpoint is the mechanism by
  which a session that has entered (or been driven into, e.g. via
  `start` on a fresh/logged-out session) `SCAN_QR_CODE` status can be
  paired. There is no documented evidence this project has captured that
  QR can be meaningfully requested outside that status.
- **After successful authentication**: status transitions away from
  `SCAN_QR_CODE` toward `WORKING` (via `STARTING`, per the status table
  in Section 7) — this project has direct live evidence of the resting
  `WORKING` state, but no live evidence of the transition itself (would
  require watching a real pairing event, which this task does not
  authorize).
- **Should the BFF proxy raw QR data or transform it?** Proposed:
  **proxy the image/base64 form as-is**, without server-side
  interpretation — the BFF has no legitimate reason to decode or inspect
  QR contents (doing so would mean handling raw pairing/auth material
  outside the intended scan-with-phone flow, which this task's own
  constraints and `CLAUDE.md`'s general "don't touch auth material you
  don't need to" spirit both argue against). This is a proposal, not a
  decision — see Section 14.

## 7. Session status table

| Status | Meaning (per documentation) | Existing project representation |
|---|---|---|
| `STOPPED` | Inactive session | Free-text `WahaSession.status` (Phase 2) — stores whatever WAHA reports verbatim |
| `STARTING` | Initialization in progress | same |
| `SCAN_QR_CODE` | Awaiting QR authentication | same |
| `PASSKEY_REQUIRED` | Pending WebAuthn signature | same — not expected to occur for this project's WhatsApp-QR pairing flow, but no schema change needed if it did |
| `PASSKEY_CONFIRMATION_REQUIRED` | User must verify a confirmation code | same |
| `WORKING` | Active and operational | same — **matches this project's live-confirmed current state for `test_session`** |
| `FAILED` | Error requiring restart/re-authentication | same |

**No schema change is required or proposed.** `WahaSession.status`
(`backend/apps/waha_sessions/models.py`, Phase 2) was deliberately built
as an unconstrained `CharField` rather than a `choices` enum, specifically
because the exact status vocabulary wasn't confirmed at the time — its
docstring says so explicitly. This documentation now supplies that
vocabulary, but per the standing "do not invent states unless the project
explicitly requires them" instruction, and because the free-text field
already handles any of these values correctly today, **adding a
`choices` constraint is a possible future hardening, not a requirement**
— proposed only as an optional Phase 6+ nicety (e.g. for frontend status
badges/copy), not a blocker.

## 8. WAHA authentication strategy

### Documented mechanism (from Section 1's security-doc fetch)

- **`WAHA_API_KEY`** (global) — a single admin-equivalent key, either
  plaintext or `sha512:`-hashed in the environment. This is what every
  prior verification round in this project has used, and what
  `backend/.env`'s `WAHA_API_KEY` is today (already rotated once, per
  the incident in
  `docs/generated/PHASE-6-WAHA-LIFECYCLE-VERIFICATION.md` Section 3).
- **Keys API** (`POST/GET/PUT/DELETE /api/keys*`) — lets an admin key
  mint additional keys, either `isAdmin: true` (full access, all
  sessions) or session-scoped (`isAdmin: false`, `session: "<name>"`,
  with an optional `actions` object).
- **Documented `actions` scopes** (session-scoped keys only): `read`,
  `send`, `control` ("session lifecycle: start, stop, restart, logout,
  authenticate" — matches this document's Sections 5–6 almost exactly),
  `setting`, `app` (all default `true` if `actions` is omitted), and
  `delete` (default `false`).

### Recommendation: **B — a session-scoped WAHA API key for the BFF**

Evaluated against the requested criteria:

- **Least privilege**: a session-scoped key with `actions: {read: true,
  send: true, control: true, setting: false, app: false, delete: false}`
  grants the BFF exactly what Sections 5–8 of this document propose it
  needs (status, chats/messages, send, lifecycle) and nothing more. It
  cannot call the Keys API, cannot create/delete sessions, and — this is
  a direct, concrete benefit given this project's own history — a
  session-scoped key is documented to be scoped to a single session's
  data, which is a reasonable basis to expect it **cannot** reach
  admin/global endpoints like `/api/server/environment` (the exact
  endpoint responsible for the credential-exposure incident in the prior
  verification report). **This is stated as a reasonable inference from
  the documented admin/session-scoped distinction, not as something this
  round independently confirmed by testing** — confirming it would
  require minting a real scoped key and testing it, which this
  documentation-only task does not do. Recommended as a concrete
  follow-up verification once a scoped key exists.
- **Number of WAHA sessions**: exactly one (`test_session`) today, and no
  project document (`docs/00-MASTER-SPEC.md` and the rest of `docs/`)
  states a multi-session requirement — grep across `docs/` for
  "multi-session"/"multiple session" returns nothing. This slightly
  reduces the *practical* isolation benefit of session-scoping today
  (there's only one session to scope to), but doesn't weaken the
  privilege-reduction benefit (no Keys API, no admin endpoints, no
  `delete`).
- **Future multi-session support**: not documented as a requirement
  anywhere in this project. If it were added later, a session-scoped
  BFF key model would need to become "one key per session, provisioned
  per session" — a real but bounded operational cost, not a redesign, and
  arguably the *more* correct shape for a multi-session future (an admin
  key shared across all sessions would concentrate risk as sessions
  grow, exactly the opposite of least privilege at scale).
- **BFF responsibilities** (Section 2 of
  `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md`): status, chats,
  messages, send, lifecycle (start/stop/restart/logout), QR/pairing —
  all covered by `read` + `send` + `control`. **Delete is deliberately
  excluded** — no BFF responsibility in any standing document calls for
  session deletion, and `06-SECURITY.md`'s "system administration" is a
  separate, more privileged category than "session control," which this
  document reads as excluding destructive session-configuration removal
  from the BFF's remit.
- **Security boundary**: directly reinforces
  `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` Section 9's existing
  diagram (BFF and Django already use **separate** WAHA credentials) —
  scoping the BFF's specific key further is a strict improvement with no
  architectural cost, since nothing currently depends on the BFF holding
  admin-level WAHA access.
- **Operational complexity**: one additional one-time step (mint the
  scoped key via the Keys API, using the existing admin key, then store
  it as the BFF's `WAHA_API_KEY`-equivalent config value) — comparable in
  kind to credential provisioning this project already does (e.g. the
  webhook HMAC secret). Not a recurring cost unless sessions multiply.

**This is a recommendation for confirmation, not a decision made
unilaterally by this document** — consistent with this task's framing
("provide a concrete recommendation... do not choose based on
preference"). If accepted, minting the actual key and updating BFF
config is a Phase 6 implementation step, not something this document
performs.

## 9. Proposed BFF endpoint contract

Paths below mirror WAHA's own `/api/sessions/{session}/...` and
`/api/{session}/auth/...` naming for minimal cognitive translation
overhead — **a naming proposal, not a decided contract**; no existing
project document specifies concrete BFF paths (`docs/07-API-CONTRACT.md`
lists only categories: "session status," "session lifecycle,"
"QR/pairing"). Authentication is the Section 1 JWT decision from
`docs/generated/PHASE-6-ARCHITECTURE-DECISION.md`, applied uniformly.
Authorization scope names reuse `docs/06-SECURITY.md`'s own categories
verbatim (`session control`, `reading`, `sending`) rather than inventing
new ones.

| Operation | BFF method + path | Request body | Auth | Authorization scope | Downstream WAHA call | Success response | Failure responses | Sync? | Audited? |
|---|---|---|---|---|---|---|---|---|---|
| Session status | `GET /api/sessions/:session/status` | none | JWT required | `reading` | `GET /api/sessions/{session}` | `200` — subset of the WAHA session object (`status`, `engine`, `me`) | `401` no/invalid JWT; `403` lacking `reading`; `404` unknown session; `502`/upstream-error shape if WAHA unreachable (per Section 6 of `PHASE-6-ARCHITECTURE-DECISION.md`'s error-handling table) | Sync | No (read-only) |
| Start session | `POST /api/sessions/:session/start` | none | JWT required | `session control` | `POST /api/sessions/{session}/start` | `200`/`202` — proposed; exact code TBD since WAHA's own response shape here is undocumented (Section 5) | `401`/`403`/`404` as above; `409` if already running — **proposed default, not WAHA-confirmed**, since `start` is documented idempotent and may just return `200` again instead | Sync | **Yes** — `AuditLog(action='session.start', target=session, result=...)` |
| Stop session | `POST /api/sessions/:session/stop` | none | JWT required | `session control` | `POST /api/sessions/{session}/stop` | `200` proposed | same pattern | Sync | **Yes** — `action='session.stop'` |
| Restart session | `POST /api/sessions/:session/restart` | none | JWT required | `session control` | `POST /api/sessions/{session}/restart` | `200` proposed | same pattern | Sync | **Yes** — `action='session.restart'` |
| Logout session | `POST /api/sessions/:session/logout` | none | JWT required | `session control` | `POST /api/sessions/{session}/logout` | `200` proposed | same pattern | Sync | **Yes** — `action='session.logout'`, and per Section 5's documented behavior (logout re-starts from scratch into pairing), the BFF response should make clear the session is now mid-re-pairing, not simply "off" |
| Get QR code | `GET /api/sessions/:session/qr` | none | JWT required | `session control` (pairing material, not plain `reading`) | `GET /api/{session}/auth/qr` | `200` — QR payload proxied as-is (Section 6); **never logged, never persisted** | `401`/`403`/`404`; `409`/`425`-style "not awaiting pairing" if session isn't in `SCAN_QR_CODE` — proposed, not WAHA-confirmed | Sync | **Yes for the request event itself** (who asked for a QR, when) — **never** the QR payload |
| Request pairing code | `POST /api/sessions/:session/pairing-code` | `{"phoneNumber": "..."}` | JWT required | `session control` | `POST /api/{session}/auth/request-code` | `200` — pairing code proxied; **never logged** | same pattern | Sync | **Yes for the request event**, never the code value |

**Deliberately not exposed by the BFF** (proposed, for confirmation):

- `DELETE /api/sessions/{session}` — irreversible, no documented product
  requirement, reads as "system administration" rather than "session
  control" per `06-SECURITY.md`'s own category split.
- `POST /api/sessions` (create) / `POST /api/sessions/{session}/` (update)
  — session provisioning/reconfiguration is not a documented end-user
  BFF capability anywhere in `docs/`; this project has exactly one
  pre-existing session, managed operationally, not through the app.

## 10. Authorization model

- **JWT claims carry permission scopes**, per the existing decision in
  `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` Section 1 — Django
  remains the system of record for what a user's scopes are
  (`auth.User`/`Group`/`Permission`, already in use since Phase 2); the
  BFF makes a local, offline-capable allow/deny decision from the
  token's claims, satisfying the Availability requirement even if Office
  is unreachable for an already-issued token.
- **Exact scope names proposed**: `reading`, `sending`, `session control`
  — taken directly from `docs/06-SECURITY.md`'s own required
  differentiation ("separate permissions for session control, reading,
  sending, blast, user administration and system administration"),
  rather than inventing a parallel naming scheme. `blast`, `user
  administration`, and `system administration` are out of this
  document's scope (not lifecycle-related) but should reuse the same
  naming convention when their own phases define them.
- **This is layered on top of, not a substitute for, Section 8's WAHA-side
  scoping.** JWT authorization controls which *frontend users* may
  trigger a lifecycle action through the BFF; the WAHA-side scoped key
  (Section 8) controls what the *BFF process itself* is capable of doing
  to WAHA even if its own authorization check were somehow bypassed —
  defense in depth, not redundant.

## 11. Audit requirements

- **Model**: `apps.audit.models.AuditLog` (Phase 1) — already shaped
  exactly for this (`actor`, `action`, `target`, `result`,
  `created_at`), and its own test suite already uses
  `action='session.start'` as a worked example, suggesting this exact
  use case was anticipated even if never wired up.
- **A real, previously-unflagged gap, surfaced by this document**: unlike
  `message`/`session.status` webhook events (which `docs/generated
  /PHASE-6-ARCHITECTURE-DECISION.md` Section 2 already resolved as
  flowing into Django durably without a new BFF→Django call), a WAHA
  webhook carries **no actor identity** — WAHA has no concept of "which
  frontend user, authenticated via this project's JWT, triggered this."
  A webhook-only design can tell Django *that* `test_session` restarted,
  but never *who* asked for it through the BFF. Since `docs/06-SECURITY.md`
  requires an actor-attributed audit trail for sensitive operations,
  **webhook-based durability alone does not satisfy the audit
  requirement for BFF-initiated lifecycle actions.**
- **Proposed resolution, consistent with the precedent already accepted
  for outbound-idempotency registration**
  (`docs/generated/PHASE-6-BLOCKER-RESOLUTION.md`): a narrow,
  audit-specific BFF→Django call — fire-and-forget, not blocking the
  WAHA call itself — carrying `{actor, action, target}` for Django to
  write as an `AuditLog` row. This is the same *class* of exception
  already accepted once (a synchronous/best-effort BFF→Django call for a
  specific, narrow purpose, not a general-purpose integration), not a new
  kind of architecture deviation. **Proposed, not decided** — see
  Section 14.
- **What must never be included in an audit entry**: QR payloads,
  pairing codes, API keys, or any credential value — consistent with
  this task's own security constraints and `CLAUDE.md` rule 3's spirit.

## 12. Live-verified operations

Unchanged from
`docs/generated/PHASE-6-WAHA-LIFECYCLE-VERIFICATION.md` Section 13.3,
restated here for this document's completeness:

| Operation | Evidence |
|---|---|
| `GET /api/sessions` | LIVE VERIFIED (prior rounds) |
| `GET /api/sessions/{session}` | LIVE VERIFIED, re-confirmed with the rotated API key this cycle |
| `GET /api/sessions/{session}/me` | LIVE VERIFIED (prior round) |
| Session status (embedded field) | LIVE VERIFIED — currently `WORKING` |
| `GET /api/{session}/chats` | LIVE VERIFIED (prior round) |
| `GET /api/{session}/chats/{chatId}/messages` | LIVE VERIFIED, including pagination behavior (prior round) |
| `POST /api/sendText` | LIVE VERIFIED — schema/validation behavior only, via deliberately invalid bodies (prior round); never sent a real message |

## 13. Documented-but-not-live-tested operations

| Operation | Category | Why not live-tested |
|---|---|---|
| `POST /api/sessions/{session}/start` | DOCUMENTED / IMPLEMENTATION-READY | `test_session` already running; starting a running session isn't a meaningful test and this task forbids forcing state changes to test |
| `POST /api/sessions/{session}/stop` | DOCUMENTED / IMPLEMENTATION-READY | Would disconnect the real, in-use business session — explicitly forbidden this round |
| `POST /api/sessions/{session}/restart` | DOCUMENTED / IMPLEMENTATION-READY | Same reason |
| `POST /api/sessions/{session}/logout` | DOCUMENTED / IMPLEMENTATION-READY | Explicitly forbidden outright by this task's instructions, independent of confirmation |
| `DELETE /api/sessions/{session}` | DOCUMENTED / IMPLEMENTATION-READY | Irreversible; explicitly forbidden this round; also not proposed for BFF exposure at all (Section 9) |
| `GET /api/{session}/auth/qr` | DOCUMENTED / IMPLEMENTATION-READY | `test_session` is already paired; a prior round's probe against the live paired session produced an inconclusive timeout; not retried, per this task's explicit instruction not to call it unnecessarily |
| `POST /api/{session}/auth/request-code` | DOCUMENTED / IMPLEMENTATION-READY | Same reasoning — meaningful only during an active pairing flow, not tested against the paired session |

**Important distinction upheld throughout this document**: none of the
rows above are "unknown" endpoints anymore. Their path, method, and
documented semantics are established (Section 5/6). What remains open is
strictly *live confirmation against this specific deployment* — a
narrower gap than the prior report's blanket "UNVERIFIED" implied.

## 14. Known limitations

1. **Response body shapes for start/stop/restart/logout/delete are not
   shown by the fetched documentation** (Section 5) — only inferred by
   analogy to the `GET /api/sessions/{session}` shape this project has
   directly confirmed live. Real confirmation requires either a live
   call (deferred, per this task's scope) or deeper documentation/Swagger
   inspection this round did not perform.
2. **The session-scoped-key recommendation (Section 8) is not itself
   live-verified** — specifically, whether a session-scoped key is
   actually blocked from reaching `/api/server/environment` (the
   endpoint responsible for the prior credential-exposure incident) is a
   reasonable inference from the documented admin/session-key
   distinction, not a tested fact.
3. **Audit-actor attribution for BFF-initiated lifecycle actions
   (Section 11) has no existing mechanism** — this is a newly-surfaced
   gap, not previously named in
   `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md`, which resolved
   webhook-based *durability* but not actor attribution specifically.
4. **QR/pairing-code response formats** ("image, base64, or raw" per the
   docs) are named but not shown field-by-field — which format the BFF
   should request/proxy by default is not decided here.
5. **This project's own version-pinning caveat (Section 2)** — the
   fetched docs are not confirmed to describe `2026.9.1` specifically,
   only presumed current/compatible.
6. **`test_session`'s webhook target misconfiguration** (already documented
   in `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` Section 5 —
   currently points at `webhook-test:8000`, not this project's Django
   endpoint) remains unfixed and would need correcting before
   `session.status` webhook events (referenced in Section 11) could
   reach Django at all, independent of the audit-actor gap.

## 15. Remaining blockers

Cross-referencing `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md`
Section 10's readiness table, updated by this document's findings:

1. **Outbound idempotency mechanism** (send-message) — unchanged,
   outside this document's scope.
2. **Live WAHA chat-list entry ↔ existing Django `Chat.id` matching** —
   unchanged, outside this document's scope.
3. **Chat list/message-history source of truth** — unchanged, outside
   this document's scope.
4. **Session lifecycle and QR — reclassified, not fully closed.** No
   longer "unknown endpoints" (Section 4's category distinction). What
   remains: (a) live confirmation of response shapes, (b) the
   audit-actor-attribution mechanism (Section 11), (c) confirming the
   session-scoped-key recommendation (Section 8), (d) a small number of
   explicit decisions listed in Section 16 below. **None of these require
   destructive testing against `test_session`** — they are documentation,
   architecture, and (if pursued) disposable-session testing.
5. **WAHA's webhook target correction** — unchanged, a deployment fix,
   not code.

## 16. Phase 6 readiness

**1. Is the WAHA lifecycle API sufficiently specified to implement?**

**Mostly yes, for path/method/semantics** (Section 5/6) — this closes
the specific gap that blocked lifecycle/QR work in
`docs/generated/PHASE-6-WAHA-LIFECYCLE-VERIFICATION.md`. **Not fully**,
for exact response-body field shapes on the five state-changing
operations (Section 14, item 1) and QR/pairing-code response format
(item 4) — these are smaller, well-scoped gaps rather than "endpoint
existence unknown."

**2. Is Phase 6 blocked by missing WAHA lifecycle documentation anymore?**

**No, not by missing documentation.** The lifecycle/QR blocker as
originally framed ("we don't know if these endpoints exist or what they
do") is resolved by official documentation. What remains is narrower:
live confirmation of exact response shapes, and this project's own
architectural decisions (audit-actor attribution, WAHA key scoping,
BFF route/response contract finalization) — none of which are
"documentation" gaps anymore.

**3. What blockers remain for Phase 6?**

Per Section 15: outbound idempotency (#1), chat-identity matching (#2),
chat/message source of truth (#3) — all pre-existing and untouched by
this document — plus the newly-narrowed lifecycle/QR items (#4: response
shapes, audit-actor attribution, key-scoping confirmation) and the
webhook-target misconfiguration (#5).

**4. What exact decisions are still required before implementation?**

- Confirm or reject the session-scoped WAHA API key recommendation
  (Section 8).
- Confirm or reject the proposed BFF route contract (Section 9),
  including the choice to exclude `delete`/create/update from the BFF.
- Decide the audit-actor-attribution mechanism (Section 11) — accept the
  proposed narrow BFF→Django call, or an alternative.
- Decide default QR/pairing-code response format (Section 14, item 4).
- Resolve `test_session`'s webhook target (Section 14, item 6) —
  operational, not a document decision, but a prerequisite for
  `session.status` webhook events to be usable at all.
- The three still-open items from
  `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` (idempotency, chat
  matching, chat/message source of truth) — unaffected by this document,
  still required.

**5. What should the next implementation task be?**

Not proposed as a decision by this document (out of scope — "Do NOT
implement Phase 6"), but factually: the items in Question 4 are
architecture/decision tasks, not coding tasks — a reasonable next step
would be a follow-up decision round covering exactly that list, before
any Phase 6 code is written. Live response-shape confirmation for
start/stop/restart/logout (Section 14, item 1) would still need either a
disposable WAHA session or explicit, deliberate authorization to test
against `test_session` — a choice for the user to make, not this document.

---

**PHASE 6 NOT READY** — unchanged verdict, but the specific reason has
narrowed materially: lifecycle/QR is no longer an "unknown API" blocker,
only a "finalize a small number of architecture decisions, then
optionally live-confirm" blocker, alongside the three pre-existing,
unrelated blockers this document did not touch.
