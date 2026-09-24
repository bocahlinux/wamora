# Phase 6 — Final Implementation Contract

This document closes the remaining Phase 6 architecture/product
decisions and produces the final implementation contract. It builds
directly on `docs/generated/PHASE-6-ARCHITECTURE-CONTRACT.md` (the prior
round's decision record) rather than re-deriving everything from
scratch — where this document finalizes something the prior one left
OPEN, that's called out explicitly as **NEW THIS ROUND**. No code,
models, migrations, or live WAHA configuration were touched. No
destructive WAHA call was made. Phase 7 is not started.

Per this task's explicit instruction, decisions 1–10 in the task prompt
are treated as **APPROVED**. Repository evidence was checked against
each one specifically for a *direct contradiction* (not merely an
omission) before accepting it — where evidence only under-specifies
something (e.g. `docs/00-MASTER-SPEC.md`'s feature list not naming
`logout`) rather than contradicting it, the approval stands, and the
gap is noted rather than treated as a blocker.

**Labels used throughout**: **FINAL** (settled, do not revisit without a
new decision round), **IMPLEMENTATION DETAIL** (a concrete default is
given so coding can start; adjustable later without an architecture
change), **DEPENDENCY** (needed for full production behavior, but does
not block Phase 6 code from being written), **BLOCKED** (cannot proceed
without a decision this document is not authorized to make alone).

---

## 1. Final Phase 6 scope

**FINAL.** Phase 6 implements:

- The BFF's authentication/authorization layer (JWT verification, no
  live Django round-trip per request).
- The BFF's WAHA-facing routes: session status, start, stop, restart,
  logout, QR, pairing-code, send-message.
- The BFF's WAHA allowlist enforcement (`bff/src/wahaAllowlist.ts`).
- The narrow Django-side endpoints the BFF depends on to function
  safely: outbound-idempotency registration/resolution, and the audit
  event write. These are Django code, not BFF code, but they exist
  *because* Phase 6 needs them — see [Section 8](#8-django--bff-interaction-contract).
- The BFF's degraded-mode signal (`/health` reporting WAHA reachability
  distinctly from BFF-process health).

**Phase 6 does NOT implement** (see [Section 15](#15-phase-6--phase-7-handoff)
for the full boundary): the frontend, Django's chat/message read API,
offline/degraded-mode UI, the session-management screen, blast, or
security hardening beyond what's specified here.

---

## 2. Explicitly included routes

**FINAL.**

| Method | BFF route | Downstream |
|---|---|---|
| GET | `/api/sessions/:session/status` | `GET /api/sessions/{session}` |
| POST | `/api/sessions/:session/start` | `POST /api/sessions/{session}/start` |
| POST | `/api/sessions/:session/stop` | `POST /api/sessions/{session}/stop` |
| POST | `/api/sessions/:session/restart` | `POST /api/sessions/{session}/restart` |
| POST | `/api/sessions/:session/logout` | `POST /api/sessions/{session}/logout` — **NEW THIS ROUND**, see [Section 11](#11-session-lifecycle-contract) |
| GET | `/api/sessions/:session/qr` | `GET /api/{session}/auth/qr` |
| POST | `/api/sessions/:session/pairing-code` | `POST /api/{session}/auth/request-code` |
| POST | `/api/sessions/:session/messages` | `POST /api/sendText` |
| GET | `/health` | (reachability probe only) |

## 3. Explicitly excluded routes

**FINAL.**

| Route | Why excluded |
|---|---|
| `DELETE /api/sessions/{session}` (WAHA delete) | No product requirement names it (`docs/00-MASTER-SPEC.md` "Fitur" never mentions deleting a session); irreversible; reads as `docs/06-SECURITY.md`'s "system administration" category, not "session control" — the category this contract scopes the BFF to. This task's own instruction requires an explicit project requirement to expose it; none exists. |
| `POST /api/sessions` (create), `POST /api/sessions/{session}/` (update) | Not a documented end-user capability; this project's 2–3 sessions are operationally provisioned, not created through the app. |
| `GET` chats / chat detail / message history | **Not BFF endpoints at all** — Django-owned, durable data. See [Section 6](#6-bff--waha-contract) and [Section 9](#9-chat-identity-and-source-of-truth). |
| WAHA Keys API (`/api/keys*`) | Never proxied by the BFF under any route — it's the mechanism used to *provision* the BFF's own credential (Section 5), not something the BFF exposes to the frontend. |

---

## 4. Authentication contract

**FINAL** (architecture, per task decision 1) / **IMPLEMENTATION DETAIL**
(the concrete numbers below).

- **Mechanism**: Django-issued, asymmetrically-signed JWT. BFF verifies
  locally against a distributed public key — no live Django call per
  request. Unchanged from `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md`
  §1 and `PHASE-6-ARCHITECTURE-CONTRACT.md` §10.
- **Signing algorithm: RS256.** — **NEW THIS ROUND**, resolving the
  prior round's open RS256-vs-ES256 choice. Picked over ES256 for wider
  library/tooling maturity on both the Python (Django) and Node
  (BFF) sides for a first implementation; ES256's smaller signature size
  isn't a meaningful benefit at this project's request volume (2–3
  sessions, a small internal user base). **IMPLEMENTATION DETAIL** — not
  a security-load-bearing choice, changeable later without an
  architecture change.
- **Token lifetime: a single access token, 8 hours, no separate refresh
  token in v1.** — **NEW THIS ROUND**, resolving the prior round's open
  lifetime tradeoff. Reasoning:
  - 8 hours covers a full working day, so an already-authenticated user
    survives a typical Office outage without needing to re-authenticate
    mid-shift — directly serving the Availability requirement.
  - A **stateless refresh token** was considered and rejected for v1:
    without a new DB-backed token/denylist table (a schema change this
    task forbids), a refresh token can only be verified by
    signature+expiry, meaning it **cannot be revoked before its own
    expiry** — pushing the leak-exposure problem from the access token
    onto a token that would need to be *longer*-lived to be useful. A
    single, moderately-short-lived access token has a smaller, easier
    to reason about exposure window and requires no new mechanism.
  - **Consequence, stated plainly**: a session longer than 8 hours, or
    an Office outage longer than 8 hours, requires re-login once Office
    is reachable again. This is a real, accepted UX tradeoff — **IMPLEMENTATION
    DETAIL**, the 8-hour figure specifically (not the "no stateless
    refresh" reasoning, which is closer to FINAL given the schema
    constraint).
  - **DEPENDENCY, not designed here**: a real refresh mechanism with
    proper revocation would need a token/session table — flagged as a
    candidate for Phase 12 (Security hardening) or a dedicated future
    migration, not invented now.
- **Claims**: `sub` (Django user ID), `iss` (`waha-monitoring-django`),
  `aud` (`waha-monitoring-bff`), `iat`, `exp`, `kid` (key ID, for
  rotation — see below), `scopes` (array, using `docs/06-SECURITY.md`'s
  own category names verbatim: `reading`, `sending`, `session control`,
  `blast`, `user administration`, `system administration`).
  **IMPLEMENTATION DETAIL** — exact claim names are conventional, not
  security-load-bearing.
- **Key distribution**: Django holds the RS256 private key
  (environment/secret-managed, never committed, same pattern as
  `WAHA_API_KEY`/the webhook HMAC secret). The BFF holds only the public
  key, provisioned the same way. No JWKS endpoint — a static key,
  manually provisioned, is sufficient at this project's scale. **FINAL**
  (mechanism); **IMPLEMENTATION DETAIL** (exact env var names, file vs.
  inline).
- **Rotation — corrected after the post-implementation audit
  (`docs/generated/PHASE-6-POST-IMPLEMENTATION-AUDIT.md`); this bullet
  previously overstated what was built.** **v1 implements single-key
  verification only**: the BFF checks every token against exactly one
  statically-configured public key. Issued tokens do carry a `kid`
  header (`apps/authn/jwt_utils.py`), but the BFF's verifier
  (`bff/src/jwt.ts`) does not read it and performs no key lookup — `kid`
  exists purely for forward compatibility, in case a multi-key rotation
  mechanism is built later, and is otherwise inert. **A real rotation
  (distributing a new public key, retaining the old one briefly so
  already-issued tokens keep verifying, using `kid` to select between
  them) is NOT implemented and is a DEPENDENCY on future work, not a
  built mechanism** — this was previously mislabeled "FINAL (mechanism)"
  in this section, which is corrected here. Today, rotating the key pair
  means every outstanding token becomes unverifiable the moment the BFF's
  configured public key changes — acceptable at this project's current
  scale (rotation has not yet happened), but a real, current limitation,
  not a hypothetical one.
- **Revocation**: best-effort only, bounded by the 8-hour expiry. An
  urgent revocation (e.g. a compromised account) is handled by
  disabling the Django user (`auth.User.is_active = False`, blocks
  *new* token issuance immediately) or, in the extreme, rotating the
  signing key (invalidates *all* outstanding tokens project-wide). **A
  compromised, not-yet-expired token cannot be individually invalidated
  without a schema change.** **FINAL** (as a stated, accepted
  limitation) — stronger revocation is a **DEPENDENCY** on future schema
  work, not solved here.
- **Behavior when Django is unreachable**: unchanged from the prior
  round — already-issued, unexpired tokens keep verifying locally; new
  logins fail closed. **FINAL.**

---

## 5. Authorization / RBAC contract

**FINAL** (mechanism) / **IMPLEMENTATION DETAIL** (exact scope-to-route
mapping, restated from the prior round for completeness):

| BFF route | Required scope |
|---|---|
| `GET status` | `reading` |
| `POST start` / `stop` / `restart` / `logout` | `session control` |
| `GET qr`, `POST pairing-code` | `session control` |
| `POST messages` | `sending` |

Scopes are carried in the JWT's `scopes` claim (Section 4), checked
locally by BFF middleware — no live Django call. Django remains the
system of record for *what* a user's scopes are (`auth.User`/`Group`/`Permission`,
unchanged since Phase 2); how that maps to the `scopes` claim's exact
strings at token-issuance time is an **IMPLEMENTATION DETAIL**, not an
architecture question. `blast`, `user administration`, `system
administration` scopes are named for forward compatibility but have no
Phase 6 routes that check them yet — **DEPENDENCY** on Phases 10/11/12.

---

## 6. BFF → WAHA contract

**FINAL** (credential strategy, per task decision 2).

- **Credential**: one **session-scoped WAHA API key per session**
  (2–3 total, per the project's Final "max 2–3 sessions" decision),
  minted via WAHA's documented Keys API with `isAdmin: false`, `session:
  "<name>"`, `actions: {read: true, send: true, control: true, setting:
  false, app: false, delete: false}`. No admin/delete privilege, per
  task decision 2's explicit requirement. Never sent to the frontend —
  it's read only by the BFF process, server-side, from its own
  environment.
- **Fallback, if the Keys API turns out unreachable on this deployment**:
  a dedicated (non-scoped) key for the BFF, separate from Django's own
  WAHA key — strictly better than reusing one key across both
  components, though it fails the "no admin capability" requirement.
  **DEPENDENCY**: which of the two is actually used depends on a live
  check against the real deployment (not performed this round, per this
  task's instruction not to call destructive/administrative WAHA
  endpoints) — **not blocking**, since the code path is identical either
  way (an API key in a header); only the *provisioning step* differs.
- **Allowlist**: `bff/src/wahaAllowlist.ts` holds exactly the eight
  downstream paths in Section 2's table — nothing else. This is the
  concrete enforcement of `CLAUDE.md` rule 5 ("BFF is not a generic
  proxy"). **FINAL.**
- **What the BFF is explicitly NOT responsible for serving from WAHA**:
  chats, chat detail, message history. Restated from
  `docs/generated/PHASE-6-BLOCKER-RESOLUTION.md`'s "Blocker 2"
  resolution and `docs/00-MASTER-SPEC.md`'s "Ownership" section (*"WAHA:
  live WhatsApp/session state. PostgreSQL: durable ... chats/messages
  ..."*) — direct repository evidence, not a preference. **FINAL.**

---

## 7. Frontend → BFF contract

**FINAL** (shape) / **DEPENDENCY** (the frontend itself — Phase 7, not
built yet).

- All frontend WAHA-operation traffic goes through the BFF's eight
  routes (Section 2) — never directly to WAHA (`CLAUDE.md` rule 4).
- Every request (except `/health`) carries `Authorization: Bearer
  <jwt>`.
- `POST messages` additionally requires an `Idempotency-Key` header,
  generated client-side once per logical send attempt and reused
  verbatim on any retry of that same logical attempt (Section 10).
- Response envelopes are BFF-owned, not raw WAHA passthroughs, for the
  five state-changing lifecycle operations (Section 11) — this is
  deliberate (Section 13), so the frontend never has to parse an
  unconfirmed WAHA response shape.
- This contract does not itself require any frontend code to exist —
  it's the interface Phase 7 will consume. **Building the frontend is
  explicitly out of Phase 6's scope** (Section 15).

---

## 8. Django → BFF interaction contract

**FINAL** (that this interaction is required and narrow) /
**IMPLEMENTATION DETAIL** (the exact credential mechanism, decided
concretely this round).

Two narrow, BFF-initiated, server-to-server Django endpoints are
required for Phase 6 to function safely — **NEW THIS ROUND: a concrete
authentication mechanism for these calls is specified**, closing a gap
the prior round left implicit ("a separate BFF↔Django service
credential," unspecified):

- **Mechanism: a static shared secret**, e.g. `INTERNAL_SERVICE_KEY`,
  configured as an environment variable on both the BFF and Django,
  sent as a header (e.g. `X-Internal-Service-Key`) and checked with a
  constant-time comparison on the Django side. This is the same *kind*
  of mechanism this project already uses for the WAHA API key and the
  webhook HMAC secret — no new infrastructure class introduced. **Not**
  the end user's JWT — this authenticates the BFF *process* to Django,
  independent of which frontend user triggered the call.
- **Endpoint 1 — outbound-operation registration/resolution** (Section
  10): a single endpoint handling both the pre-send `get_or_create` and
  the post-send resolve, distinguished by request body/method (exact
  route shape is an **IMPLEMENTATION DETAIL**, e.g. `POST
  /internal/outbound-operations` to register, `PATCH
  /internal/outbound-operations/{id}` to resolve — or one endpoint that
  does both idempotently; not prescribed further here).
- **Endpoint 2 — audit event write** (Section 12): `POST
  /internal/audit-events`, body `{actor_id, action, target, result}`.
- **Both calls are synchronous from the BFF's perspective, bounded by a
  short timeout** (proposed **2 seconds** — **IMPLEMENTATION DETAIL**,
  not specified by any doc, chosen to be comfortably shorter than a
  typical WAHA round-trip so a slow Django doesn't dominate response
  latency), **and best-effort**: a failure never blocks the BFF from
  proceeding to WAHA (idempotency registration) or from returning the
  WAHA result to the frontend (audit write) — see Sections 10/12 for the
  precise degraded behavior in each case.

---

## 9. Outbound idempotency state machine

**FINAL** (per task decision 4 — this section directly answers the
exact transitions the task asked for).

### States (existing `OutboundOperation.status` — no schema change)

`PENDING` → registered, outcome not yet known.
`SENT` → WAHA confirmed success; `provider_message_id` populated.
`FAILED` → WAHA returned a clean error.
`UNKNOWN` → the BFF's own call to WAHA was inconclusive (timeout/reset).

### Transitions

| Event | Precondition | Action |
|---|---|---|
| **First request** | No `OutboundOperation` row for `(session, idempotency_key)` | `get_or_create` inserts a new `PENDING` row → BFF calls WAHA → resolves to `SENT`/`FAILED`/`UNKNOWN` (below) |
| **Duplicate request, same idempotency key** | Row exists, status `PENDING` or `SENT` | **BFF does not call WAHA.** Returns the row's current state as-is. |
| **Duplicate request, same idempotency key** | Row exists, status `FAILED` or `UNKNOWN`, **and is younger than the staleness threshold** (Section below) | **BFF does not call WAHA.** Returns the row's current state; a genuinely new attempt requires a *new* idempotency key — a deliberate frontend action, not an automatic retry. |
| **WAHA success** | BFF received a clean WAHA response with a message identifier | `PENDING → SENT`, `provider_message_id` set. Django write is the same call that also writes the audit row (Section 12). |
| **WAHA failure** | BFF received a clean WAHA error response (e.g. `400`/`500` with a body) | `PENDING → FAILED`. |
| **Timeout / unknown outcome** | The BFF's own request to WAHA times out or the connection resets — no confirmed response either way | `PENDING → UNKNOWN`. This is the safe default: never assume success or failure when genuinely unknown (`docs/09-TEST-PLAN.md`'s Failure test #8). |
| **Retry (of a stale `PENDING`/`UNKNOWN` row)** | Row exists, status `PENDING` or `UNKNOWN`, **and is older than the staleness threshold** | **NEW THIS ROUND** — see below. The BFF is now permitted to retry, using the *same* row (not a new one). |
| **Django unreachable at registration time** | Step 3 call to Django times out | BFF proceeds to WAHA anyway (accepted, documented degradation — Section 14). No local record exists to prevent a concurrent duplicate in this specific window. |

### Staleness/retry policy — **NEW THIS ROUND, resolving the prior round's open item**

`OutboundOperation` inherits `TimeStampedModel`'s `updated_at` field
(already in schema, confirmed via `apps/webhooks/services.py`'s existing
use of `update_fields=[..., 'updated_at']` on sibling models — **no
schema change needed**, satisfying this task's "if the schema cannot
represent a required state safely, STOP and report" instruction: it
can). Policy: a `PENDING` or `UNKNOWN` row is eligible for a retry
attempt (same idempotency key, same row, not a new one) once
`updated_at` is older than a **30-second threshold** (**IMPLEMENTATION
DETAIL** — chosen to comfortably exceed any expected BFF↔WAHA round
trip; tunable).

**This is a staleness/retry-eligibility gate, not the message-body/timestamp
correlation heuristic the task explicitly forbids.** It never tries to
guess *which* WAHA message corresponds to a stuck operation — it only
decides *whether a fresh WAHA call may be attempted at all* for an
operation whose outcome was never confirmed. The distinction matters:
correlation (matching an unconfirmed operation to a specific
already-sent message) remains unsolved and is **not** attempted here,
for the same reason as before (no client-correlatable ID exists on the
WAHA side).

**Residual risk, stated plainly, not hidden**: if the BFF crashes
*after* WAHA actually processed the send but *before* resolving the
`OutboundOperation` (leaving it `PENDING`), and a retry happens after
the 30-second window, the retry **could** cause a real second WhatsApp
message. This is a deliberate, bounded tradeoff — progress on stuck
operations vs. a narrow, rare double-send window — not an oversight.
**FINAL as a policy** (the task asked for retry behavior to be defined,
not left open); the 30-second number and the tradeoff itself are
recorded for your visibility, not silently assumed.

---

## 10. Audit contract

**FINAL** (per task decision 5 — unchanged from `PHASE-6-ARCHITECTURE-CONTRACT.md`
§5, restated here as the deliverable requires):

- Sequence: **WAHA call resolves first, then one `AuditLog` row is
  written** with the now-known final `result` (`success`/`failure`) —
  never before, since `AuditLog.result` has no "pending" choice and this
  task forbids adding one.
- For `POST messages`: the same Django call that resolves the
  `OutboundOperation` (Section 9) also writes the `AuditLog` row, in one
  Django-side transaction — no extra BFF→Django round trip.
- For lifecycle actions (start/stop/restart/logout/qr/pairing-code): the
  dedicated `POST /internal/audit-events` endpoint (Section 8).
- **Actor identity**: `AuditLog.actor` (nullable FK to
  `AUTH_USER_MODEL`) is populated from the JWT's `sub` claim wherever
  the action was frontend-initiated — satisfying the task's "authenticated
  actor identity where the existing schema permits it" requirement. The
  schema already supports `actor=None` for system-initiated actions
  (unused by Phase 6, but noted as already-correct for a future
  scheduled/automated action).
- **Consistency model — no transactional guarantee across WAHA and
  Django, stated explicitly**: WAHA's own execution is the sole source
  of truth for whether an action happened. A missing `AuditLog` row
  (Django unreachable at write time) does not mean the action didn't
  happen — it means the record degraded, an accepted category under
  `docs/00-MASTER-SPEC.md`'s Availability section. **Mitigation**: the
  BFF also emits a structured local log line (actor, action, target,
  result, timestamp) for every sensitive action, independent of Django's
  reachability, as a fallback trail — not a substitute for the durable
  `AuditLog` row, but bounds the gap to "Office was unreachable at that
  exact moment."

---

## 11. Session lifecycle contract

**FINAL** — includes **logout**, per this task's explicit approval.
**Flagged transparently**: `docs/generated/PHASE-6-ARCHITECTURE-CONTRACT.md`
§8 previously recommended *excluding* logout, reasoning from
`docs/00-MASTER-SPEC.md`'s Fitur list naming only "start/stop/restart"
and not "logout." That list's silence on logout is an omission, not a
stated prohibition, and this task explicitly directs logout to be
covered — treated as approved per this round's instruction, not silently
reversed. `delete` remains excluded (Section 3) since nothing approves
it and it remains explicitly out of scope.

| Operation | BFF route | Method | Authz | WAHA method/path | Request body | Response mapping | Error mapping | Audit | Idempotency | Retry-safe? |
|---|---|---|---|---|---|---|---|---|---|---|
| Status | `/api/sessions/:s/status` | GET | `reading` | `GET /api/sessions/{s}` | — | `200 {session, status, engine, me}` (subset) | `401`/`403`/`404`/upstream-error | No (read-only) | N/A | Yes, always |
| Start | `/api/sessions/:s/start` | POST | `session control` | `POST /api/sessions/{s}/start` | — | `200 {success, session, requestedAction:"start"}` — no `status` claimed (Section 13) | `401`/`403`/`404`/upstream-error | Yes, after resolution | N/A (no `OutboundOperation`) | **Yes** — WAHA documents `start` as idempotent |
| Stop | `/api/sessions/:s/stop` | POST | `session control` | `POST /api/sessions/{s}/stop` | — | `200 {success, session, requestedAction:"stop"}` | same | Yes | N/A | **Yes** — documented idempotent |
| Restart | `/api/sessions/:s/restart` | POST | `session control` | `POST /api/sessions/{s}/restart` | — | `200 {success, session, requestedAction:"restart"}` | same | Yes | N/A | **No** — always has an effect if not already `STOPPED`; repeated calls are not no-ops |
| Logout | `/api/sessions/:s/logout` | POST | `session control` | `POST /api/sessions/{s}/logout` | — | `200 {success, session, requestedAction:"logout"}` | same | Yes | N/A | **No** — per official WAHA docs, logout re-starts the session from scratch into pairing; a second call has a real effect, not a no-op. **Frontend should confirm before calling this** — a UX requirement, not a Phase 6 API requirement. |
| QR | `/api/sessions/:s/qr` | GET | `session control` | `GET /api/{s}/auth/qr` | — | Section 12 | `401`/`403`/`404`/`409` (proposed) | Yes, request event only — never the payload | N/A | Yes, but time-boxed (60s/20s expiry per WAHA docs) |
| Pairing code | `/api/sessions/:s/pairing-code` | POST | `session control` | `POST /api/{s}/auth/request-code` | `{phoneNumber}` | `200 {session, code}` | `400`/`401`/`403`/`404` | Yes, request event only — never the code | N/A | Not established by documentation |
| Send | `/api/sessions/:s/messages` | POST | `sending` | `POST /api/sendText` | `Idempotency-Key` header + `{chatId, text}` | Section 9's state machine | Section 13 | Yes, via same call as Section 9's resolve | **Yes** — the entire point of Section 9 | Governed by Section 9, not a simple yes/no |

**Do not claim live verification where only documentation verification
exists** — restated as a hard rule for this table: every "Response
mapping"/"Error mapping" cell above is the *documented* WAHA contract
(`docs/generated/PHASE-6-WAHA-LIFECYCLE-API-CONTRACT.md`) or this
project's own BFF-owned envelope — none of the five state-changing
operations have been live-invoked against `test_session` or any other
real session. This is unchanged and not revisited by this document.

---

## 12. QR/pairing contract

**FINAL** (envelope strategy — **clarified this round** per the task's
"adapter contract" framing, reconciling with the prior round's "proxy
as-is" language):

- **The QR/pairing *payload itself*** (the actual image/base64 data, or
  the pairing code string) **is forwarded to the frontend essentially
  as-is** — there is no meaningful way to "clean up" or transform actual
  pairing material; the frontend needs the literal bytes WAHA produced
  to render a scannable code or a phone-linkable code.
- **The response *envelope* around it is BFF-owned and minimized** —
  this is the "adapter contract" the task asks for: the BFF's JSON shape
  is `{session, format, data, expiresInSeconds?}` for QR and `{session,
  code}` for pairing, **dropping every other field WAHA's raw response
  might include** (no internal server metadata, no unrelated WAHA
  response fields, no credentials). The BFF is the single place this
  mapping lives — the frontend never sees WAHA's raw response shape
  directly.
- **Isolation**: this mapping is implemented as one narrow adapter
  function inside the BFF (not spread across multiple call sites), so
  if WAHA's actual field names differ from what's assumed once this is
  live-tested, exactly one place needs to change.
- `expiresInSeconds` is included only if derivable from WAHA's own
  response; otherwise omitted rather than guessed — restated from the
  prior round, unchanged.
- **DEPENDENCY**: WAHA's exact QR/pairing response field names remain
  undocumented at the field level (`docs/generated/PHASE-6-WAHA-LIFECYCLE-API-CONTRACT.md`
  Section 6) — the adapter's *internal* mapping will need adjustment
  once this is live-tested, but the *external* BFF↔frontend contract
  above does not change as a result, which is the entire point of
  isolating the mapping.

---

## 13. Error/status mapping

**FINAL** (consolidating and finalizing
`docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` §6's proposed table):

| Case | BFF response | Source |
|---|---|---|
| No/invalid JWT | `401` | Standard |
| Valid JWT, missing required scope | `403` | `docs/09-TEST-PLAN.md` "unauthorized actions return 401/403" |
| Unknown session name | `404` | Reasonable default, not WAHA-confirmed |
| WAHA unreachable | Distinct, clearly-labeled upstream-error status (not conflated with auth/Django errors) — e.g. `502` with `{error: "waha_unavailable"}` | `docs/03-UI-UX-SPEC.md`/`CLAUDE.md` offline-status requirement |
| WAHA request times out | Same as above, plus (for `POST messages` only) the `UNKNOWN` `OutboundOperation` state (Section 9) | New this round — ties the generic timeout case to the specific idempotency state machine |
| Django unreachable (idempotency registration) | BFF proceeds to WAHA anyway — degraded, not failed (Section 9) | `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` §2 |
| Django unreachable (audit write) | BFF still returns the WAHA result to the frontend; audit degrades to local log only (Section 10) | This document, restated |
| Invalid frontend request body | `400` | Standard |
| Lifecycle op on a session in an incompatible state (e.g. QR while `WORKING`) | `409` (proposed, WAHA-unconfirmed) | Section 11 |
| Any other WAHA error response | Logged with full detail server-side; a generic, non-credential-bearing error returned to the client | Mirrors `apps.core.exceptions.api_exception_handler`'s existing pattern (Phase 1) |

**Every error response must identify *which* upstream failed** (WAHA vs.
Django vs. the BFF's own auth check) — restated as a hard requirement,
unchanged from the prior round, since Phase 9 (offline/degraded UI)
depends on this distinction existing in Phase 6's responses even though
Phase 9 itself is not built yet.

---

## 14. Security boundaries

**FINAL** (unchanged from `docs/generated/PHASE-6-ARCHITECTURE-CONTRACT.md`
§9/§14, restated as this deliverable requires):

- WAHA API key (session-scoped, BFF-held), Django's own separate WAHA
  key, the `INTERNAL_SERVICE_KEY` (Section 8), the JWT signing private
  key, and PostgreSQL/Redis credentials all exist **server-side only** —
  never reach the browser, confirmed by construction (frontend has zero
  WAHA/Django-credential references anywhere in its source, per the
  GitHub security audit performed this project cycle).
- The BFF is trusted to call exactly the eight allowlisted WAHA
  endpoints (Section 2) on behalf of an authenticated, authorized
  frontend user — nothing else, enforced by `wahaAllowlist.ts` and the
  JWT scope checks (Section 5).
- A session-scoped WAHA key structurally cannot reach admin/global WAHA
  endpoints (e.g. `/api/server/environment`, the endpoint responsible
  for this project's earlier credential-exposure incident) — a direct,
  structural mitigation, not just a policy promise. **DEPENDENCY**: not
  independently live-verified this round (would require minting a real
  key).
- Office↔Tencent traffic (BFF→Django's two internal endpoints) is
  authenticated by a shared static secret, distinct from end-user JWTs —
  a compromised frontend session cannot forge these calls.

---

## 15. Phase 6 → Phase 7 handoff

**FINAL** (resolving `docs/generated/PHASE-6-ARCHITECTURE-CONTRACT.md`
§0.2's previously-open scoping question, per this task's item 10):

| Capability | Owning phase | Depends on Phase 6 for |
|---|---|---|
| BFF auth/allowlist/WAHA routes (this document) | **6** | — |
| Django `OutboundOperation`/audit internal endpoints (Section 8) | **6** (built alongside the BFF, since Phase 6's own flows require them) | — |
| Frontend application (any UI at all) | **7** | The BFF contract in this document, to build against |
| Django chat/message read API (DRF endpoints backing "GET chats"/"message history") | **8** — not Phase 6; these are Django-owned, not BFF-owned (Section 6), and no BFF route exists for them | Nothing from Phase 6 directly — independent Django/DRF work |
| Inbox/chat UI | **8** | The (not-yet-built) Phase 8 Django endpoints, and Phase 7's frontend shell |
| Offline/degraded-mode UI | **9** | This document's Section 13 error/status-mapping contract (the "which upstream failed" signal) — the contract exists now; the UI consuming it does not |
| Session-management *screen* (as opposed to the underlying API) | **10** | This document's Section 11 lifecycle contract |
| Blast | **11** | Nothing from Phase 6 directly |
| Rate limiting, security headers, CSRF/XSS hardening beyond what's specified here, dependency scanning | **12** | The auth/authz architecture this document locks (rate-limiting specific routes like login/send/session-control, per `docs/06-SECURITY.md`'s "Rate limits" line, is Phase 12's job to implement against Phase 6's routes) |
| Live verification of start/stop/restart/logout/QR response bodies against `test_session` (or a disposable session) | **13** (Failure/security testing) or an explicit, separately-authorized live round — not this document | Phase 6's routes existing to test against |
| Production webhook re-pointing (WAHA's webhook target still points at `webhook-test:8000`, not this project's endpoint) | **14** (Production deployment) — an operational/config action, not code | Nothing from Phase 6 directly; independent of BFF work |
| Webhook parser extension to handle `session.status` events (currently parsed but marked `unsupported`, `apps/webhooks/parsing.py`) | Not cleanly any single numbered phase — it's `apps/webhooks` (Phase 3) code, needed for full audit *durability* via the webhook path, but Phase 6's own audit design (Section 10) does not depend on it (the direct `/internal/audit-events` call is the primary path). **DEPENDENCY**, recommend scheduling alongside Phase 6 implementation even though it's technically backend/webhooks work, not BFF work. | — |

---

## 16. Remaining unresolved decisions

Everything in Sections 1–15 above is now either **FINAL**, a concrete
**IMPLEMENTATION DETAIL** with a stated default, or a **DEPENDENCY**
that does not block writing Phase 6 code. Nothing is **BLOCKED**. What
remains is confirmation, not open specification:

1. **Confirm the concrete defaults this document picked**: RS256 over
   ES256, 8-hour single access token with no v1 refresh mechanism, the
   30-second `OutboundOperation` staleness/retry threshold, and the
   `INTERNAL_SERVICE_KEY` shared-secret mechanism for Django↔BFF calls.
   None of these are architecture-level — all are changeable later
   without redesigning anything — but none were specified by any
   existing document, so they're this document's own reasoned proposals,
   not extracted facts.
2. **The residual double-send risk window** named in Section 9 (a retry
   after the 30-second staleness threshold, in the rare case the BFF
   crashed after a successful WAHA dispatch but before resolving the
   operation) — accepted as a deliberate, bounded tradeoff by this
   document; flagged for your explicit awareness since it's a genuine,
   non-zero risk, not a hypothetical one.
3. **Whether the Keys API is actually reachable on this specific
   deployment** for minting the session-scoped WAHA key (Section 6) —
   not live-tested this round; Option B (dedicated non-scoped key) is
   the ready fallback either way, so this doesn't block starting
   implementation.

---

## PHASE 6 IMPLEMENTATION READY

Every decision this task asked to close now has a concrete answer:
architecture-level items are **FINAL**, implementation-level numbers
have stated, reasoned defaults, and every remaining gap is a
**DEPENDENCY** that Phase 6 code can be written against without waiting
for it to close. Nothing in this document requires further live testing
against a real WAHA session, a schema change, or a decision this
document isn't authorized to make. The three items in
[Section 16](#16-remaining-unresolved-decisions) are asking for your
sign-off on this document's own reasoned defaults, not for missing
specification.
