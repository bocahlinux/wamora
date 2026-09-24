# Phase 6 — Architecture Decision Resolution

Research and decision-making only. No application code, models,
migrations, frontend, BFF implementation, or production configuration
was modified. `docker-compose.yml` untouched. Phase 7 not started.

## Terminology flags — read before the rest of this document

Two phrasing inconsistencies appeared across this task's own instructions
and need to be surfaced rather than silently resolved one way or another:

1. **"Django BFF"** (previous round) / **"BFF → WAHA → Django" as a
   linear chain** (this round, Section 9's diagram: *"Frontend ↓ BFF ↓
   WAHA ↓ Django"*). Every standing project document
   (`00-MASTER-SPEC.md`, `01-ARCHITECTURE.md`,
   `11-DECISIONS-AND-OPEN-QUESTIONS.md` Final #11,
   `13-FINAL-DEPLOYMENT-TOPOLOGY.md`, `CLAUDE.md`) describes the BFF as a
   separate Node.js/Express process (Tencent) from Django (Office) — a
   "Final," not "Open," decision. It also describes **two parallel
   frontend paths**, not one chain: `docs/07-API-CONTRACT.md` has
   separate "Frontend → BFF" and "Frontend → Django" sections. Django
   does not sit downstream of WAHA in any documented request flow — WAHA
   calls Django directly for webhooks (Phase 3), and Django calls WAHA
   directly for reconciliation (Phase 4/5); neither goes through the BFF.
   **This document uses the standing, documented topology as
   authoritative**: Frontend talks to BFF and Django as two independent
   paths; BFF talks to WAHA; Django talks to WAHA independently; WAHA
   talks to Django independently (webhooks). If a literal linear chain
   or a merged BFF/Django component was actually intended, that is a
   real architecture change and needs to be said explicitly, not
   inferred from a diagram.

This flag is not repeated as a blocker in the readiness table (Section
10) — it's treated as almost certainly informal phrasing, consistent
with the previous round's finding — but it is listed in "decisions still
requiring confirmation" for completeness.

---

## 1. Authentication decision

### Options analyzed (per this round's explicit list)

| | Where credentials/tokens live | Frontend auth flow | BFF validation | Needs Django online per request? | Django down: WAHA/Tencent still usable? | Logout/revocation | Security notes |
|---|---|---|---|---|---|---|---|
| **Django session/cookie** | Server-side session store (Django, already installed: `django.contrib.sessions`) | Cookie set by Django on login, sent automatically by browser | Would have to call Django (or share its session store) to check validity — **no independent verification possible** | **Yes, every request** | **No** — session validity can't be confirmed without Office | Immediate (server-side invalidation) | Needs CSRF defense (cookie-based); strong revocation |
| **JWT (Bearer)** | Signed token, held client-side (memory/`sessionStorage`) | `Authorization: Bearer` header, obtained from Django at login | **Independent signature check, no DB/session lookup needed** | **No, once issued** | **Yes**, for already-authenticated users | Requires short expiry + refresh, or a revocation list (reintroduces a live check if used) | Not CSRF-vulnerable if never cookie-stored; needs a securely shared verification key |
| **DRF `TokenAuthentication`** | Opaque token, DB row (Django) | `Authorization: Token` header | DB lookup required to validate | **Yes, every request** | **No** | Instant (delete DB row) | Same CSRF profile as JWT; same Office-dependency problem as sessions |
| **BFF-local auth** (BFF issues/validates its own credentials, no Django involvement) | Wherever the BFF stores it — **no persistence layer currently exists for the BFF, and none is authorized by any spec** | BFF-only login | Local, no Django dependency at all — **best availability of all four** | **No, ever** | **Yes, fully**, including brand-new logins during an outage | Depends entirely on an unbuilt mechanism | **Cannot satisfy `06-SECURITY.md`'s "separate permissions for session control, reading, sending, blast, user administration and system administration"** without inventing a whole parallel user/role/permission system the BFF has no database to hold — directly conflicts with the documented "no new persistence layer" and "BFF has no DB access" findings from the prior review |

### Decision

**Selected: a signed, independently-verifiable token (JWT or equivalent),
issued by Django, verified by the BFF without a per-request round-trip to
Django.**

This is not chosen because it's common — it's the only option, among the
four actually analyzed, that satisfies **two explicit, already-documented
requirements simultaneously**:
1. `docs/00-MASTER-SPEC.md`, "Availability": *"WAHA/Tencent tetap dapat
   bekerja ketika server kantor mati"* — disqualifies Django sessions and
   DRF TokenAuthentication outright, since both require Django to be
   reachable on every single request.
2. `docs/06-SECURITY.md`: *"Separate permissions for session control,
   reading, sending, blast, user administration and system
   administration"* — disqualifies BFF-local auth, since the BFF has no
   database and no documented user/role model of its own; only Django
   (with its already-installed `auth.User`/`Group`/`Permission` system,
   used elsewhere since Phase 2) has a place to define this.

Issuing from Django and verifying independently at the BFF is the only
option satisfying both at once. Django sessions and DRF TokenAuthentication
are ruled out by requirement #1, not by preference; BFF-local auth is
ruled out by requirement #2, not by preference.

### What remains genuinely open (implementation-level, not architecture-level)

- Exact token lifetime and refresh strategy.
- Exact claim shape (how permission scopes are encoded).
- How the JWT verification key is securely distributed to the Tencent-side
  BFF (an operational concern of the same *kind* this project already
  manages for the WAHA API key and webhook HMAC secret, not a new class
  of problem).
- Revocation strategy (accept "can't revoke before expiry" as a tradeoff,
  or add a best-effort revocation check that degrades gracefully when
  Office is unreachable).

These do not block declaring the *architecture* decision made — they are
Phase 6 implementation details to work out while building it, not
prerequisites to starting.

---

## 2. BFF Responsibility Boundary

### BFF → WAHA (proxied, live-only)
- Session status / session list.
- Chat list, message history (see Section 3/4 for the identity nuance).
- Send message.
- Session lifecycle (start/stop/restart) — **once the underlying WAHA
  endpoints are actually confirmed to exist; see Section 5.**
- QR/pairing — same caveat.

### Frontend → Django (direct, not through the BFF — per `07-API-CONTRACT.md`'s separate section)
- Durable conversation views, audit, monitoring, reports, blast, sync
  status — i.e. anything backed by PostgreSQL rather than live WAHA
  state.
- Contact information, if/when exposed as its own concept distinct from
  WAHA's live chat listing (per the prior review's Section 12 finding:
  `Contact` is Django-owned durable data, not a WAHA-live concept).

### Existing Django ↔ WAHA operations that do not involve the BFF at all
- Reconciliation (`apps/sync/waha_client.py`, Phase 4/5) — Django calls
  WAHA directly, separately credentialed, unchanged by anything in this
  document.
- Webhook ingestion (`apps/webhooks/views.py`, Phase 3) — WAHA calls
  Django directly.

### Resolved: how BFF-initiated actions reach Django's durable record, without a new BFF→Django integration

This was an open gap in the prior review (audit/logging flow
unspecified). Combining several already-documented and already-verified
facts resolves it architecturally:

- `docs/05-WEBHOOK-SYNC-DESIGN.md`, "Outbound during outage": *"Use an
  idempotency key. Send through BFF/WAHA. **When office returns,
  record/reconcile provider message ID.**"* — this explicitly describes
  recording happening **after** the send, via reconciliation, not via a
  synchronous BFF→Django call at send time.
- Phase 3's webhook ingestion already correctly handles `fromMe: true`
  messages (direction=outbound, no fabricated Contact) — a message sent
  via the BFF, once WAHA emits its own `message` webhook for it
  (`fromMe: true`), would **already** flow into durable `Message` storage
  through the existing webhook pipeline, with zero new integration work.
- This round's live verification found the real session's webhook
  config includes **both** `message` and `session.status` event types —
  meaning session-lifecycle changes (start/stop/restart) triggered via
  the BFF would similarly reach Django as `session.status` webhook
  events, **once Django's webhook handler is extended to process that
  event type** (currently only `message` is handled; everything else,
  `session.status` included, is recorded but marked `unsupported` —
  `apps/webhooks/parsing.py`, Phase 3).

**Decision: no direct BFF→Django call is architecturally required for
audit/durability of BFF-initiated WAHA actions.** The existing webhook
path is the documented mechanism for this, once two things are true: (a)
WAHA's webhook target actually points at this project's Django endpoint
(currently it does not — see Section 5's live-verification note below),
and (b) `session.status` event handling is added to the webhook parser
(a small, contained extension of already-built Phase 3 code, not a new
subsystem).

**A real, separate gap this surfaces**: outbound *idempotency* (not
audit) — preventing the frontend from double-submitting the same send —
needs a check *somewhere*. The BFF has no database to check against.
Given the outage-mode design explicitly tolerates sending without a
prior Django round-trip, the most consistent reading of
`05-WEBHOOK-SYNC-DESIGN.md`'s own language: the idempotency key is
generated client-side, the BFF forwards the send to WAHA regardless of
Django's reachability, and **real-time duplicate prevention during an
active outage is a client/UX discipline (don't resubmit while a send is
in flight), not a server-side guarantee** — Django's role is to
*reconcile* using the idempotency key once it's back online, matching
"never blindly resend an operation whose success is uncertain" (about
not *retrying*, not about real-time locking). During normal operation
(Office reachable), the BFF *may* still register the idempotency key
with Django first as a best-effort, fast-timeout call, proceeding to
WAHA either way. This is a design direction, not a fully resolved
contract — exact request shape is a Phase 6 implementation detail.

---

## 3. WAHA Identity Fragmentation — Phase 6 API design constraint

Documenting this explicitly, as required:

- **Confirmed** (`docs/generated/PHASE-6-SPEC-RESOLUTION.md` Section 5):
  the chat-list endpoint does not necessarily expose the LID-primary
  identifier for a conversation; message-history can be queried by
  either the LID or the `@c.us`/JID form and returns the same merged
  result.
- **The Phase 2.5 identity rule is preserved, unmodified, by this
  document**: primary WAHA identifier stored verbatim; `Alt` is optional
  metadata only; `Alt` is never the primary identity. Nothing here
  proposes changing that.
- **Does the existing Django `Chat` model already provide a stable
  application-level identifier?** — **Yes, structurally.** `Chat.id`
  (the Django primary key, `BigAutoField`, Phase 2) is already a stable,
  session-independent, WAHA-format-independent identifier that exists
  the moment a `Chat` row is created — it does not depend on which of
  WAHA's identifier forms was used to create it. **This means the BFF
  API does not need to invent a new identifier scheme**: if the frontend
  addresses chats by Django's `Chat.id` rather than by a raw WAHA
  identifier, the LID/`@c.us` inconsistency becomes an implementation
  detail the BFF/Django resolve internally, not something the frontend
  or BFF API contract needs to expose or reason about.
- **What this does NOT resolve, and must not be silently decided here**:
  whether a *given* WAHA chat identifier (LID or `@c.us`) that arrives
  fresh (e.g. from `GET /api/{session}/chats`, which the BFF might call
  live) can be reliably mapped to an *existing* Django `Chat` row when
  the two don't share a literal string match — this is exactly the
  fragmentation problem, now reframed as: **"does a live WAHA chat-list
  entry reliably correspond to an already-known Django `Chat` row?"**
  There is no evidence this round that answers that, and inventing a
  matching rule (e.g. "match by conversation timestamp proximity") would
  be exactly the kind of undocumented normalization this project has
  repeatedly refused to invent. **This is flagged as a missing decision,
  not resolved by this document** — see Section 10.

---

## 4. Chat List vs Message History — API contract direction (not final endpoint spec)

- **Chat identifiers**: per Section 3, the frontend should address chats
  using **Django's `Chat.id`**, not raw WAHA identifiers, once a chat is
  known to Django. A live WAHA chat-list entry not yet known to Django
  has no `Chat.id` yet — see the open question below.
- **How the BFF resolves a selected chat into a message-history
  request**: if the frontend passes a `Chat.id`, the BFF (or Django,
  depending on Section 6's still-open source-of-truth question) would
  need to look up that `Chat` row's `provider_chat_id` and use *that*
  verbatim value in the upstream `GET /api/{session}/chats/{chatId}/messages`
  call — this requires the BFF (or whichever component performs this
  step) to read `Chat.provider_chat_id`, which is Django/PostgreSQL data.
  **This is a concrete case where a BFF-only, database-free design is
  insufficient** — either the BFF needs a narrow, read-only lookup
  capability against Django (via an API call, not direct DB access,
  preserving the "no BFF database access" rule), or Django itself serves
  the message-history endpoint directly instead of the BFF. **Not
  resolved here — flagged for Section 10.**
- **Pagination**: WAHA's own confirmed `limit`+`offset` mechanism
  (newest-first, `page` non-functional — `docs/12-WAHA-REFERENCE.md`,
  confirmed live in Phase 4/5) is the only concrete pagination mechanism
  that exists anywhere in this system. Whichever component serves
  message history live from WAHA should reuse it as-is rather than
  inventing a different scheme.
- **Duplicate prevention**: already fully solved at the persistence
  layer — the `(session, provider_message_id)` constraint (Phase 2) and
  `persist_message`'s reuse across webhook ingestion and reconciliation
  (Phase 3/4) already guarantee this for anything that reaches Django.
  A BFF response that reads *live* from WAHA (not from Django) has
  nothing to deduplicate against in the first place, since it isn't
  persisting anything.
- **Interaction with reconciliation**: unaffected. Reconciliation
  (Phase 4/5) continues to operate on Django's own known `Chat` rows,
  independent of whatever the BFF does live. If the BFF's chat list ever
  surfaces a WAHA chat not yet known to Django, that chat would not be
  reconciled until a corresponding `Chat` row exists — consistent with
  Phase 4's already-documented, deliberate scope ("reconciliation only
  covers chats already known locally").

---

## 5. Session Lifecycle and QR — confirmed vs. unverified

Re-stated precisely from `docs/generated/PHASE-6-SPEC-RESOLUTION.md`
Section 4, with nothing new invented:

| Operation | Status |
|---|---|
| List sessions | **CONFIRMED** (`GET /api/sessions`, live 200) |
| Get session | **CONFIRMED** (`GET /api/sessions/{session}`, live 200) |
| Get "me" | **CONFIRMED** (`GET /api/sessions/{session}/me`, live 200) |
| Session status | **CONFIRMED** — embedded in the session object, no separate endpoint |
| Start session | **UNVERIFIED** — not safely testable against the live, active session |
| Stop session | **UNVERIFIED** — same reason |
| Restart session | **UNVERIFIED** — same reason |
| Logout/unpair | **UNVERIFIED** — same reason, and explicitly forbidden to test |
| QR/pairing | **UNVERIFIED (inconclusive)** — a candidate path timed out rather than 404'd, suggestive but not confirmed; not retried, deliberately |

**Essential-for-Phase-6 assessment**: session status display, chat list,
and message history are all confirmed and sufficient to implement a
useful, real Phase 6 slice. **Start/stop/restart/logout/QR are product
features this project has committed to (`00-MASTER-SPEC.md`), and their
BFF endpoints cannot be finalized without confirming the underlying WAHA
contract** — this is flagged as a blocker for *that specific slice* of
Phase 6, not for Phase 6 as a whole (see Section 10 — the readiness
table separates these).

**Additional live-verification note directly relevant to Section 2's
audit-flow design**: the real session's currently configured webhook
target is `http://webhook-test:8000/webhook` — **not this project's
Django endpoint** (already found in Phase 3 Live Verification, unchanged
this round). Section 2's "no new BFF→Django call needed" architecture
depends on this being corrected. This is a deployment/configuration fix,
not a code change, and is out of this document's scope to perform.

---

## 6. Error Handling

| Case | Expected behavior | Reasoning |
|---|---|---|
| WAHA unavailable | BFF returns a distinct, clearly-labeled error status (not conflated with auth or Django errors) | `docs/03-UI-UX-SPEC.md`/`CLAUDE.md`'s offline rule requires WAHA status to be independently reportable |
| Django unavailable | BFF-proxied (WAHA-only) endpoints continue to function; Django-backed endpoints (durable views) fail independently, reported as their own status | Directly required by the Availability decision in Section 1 and `00-MASTER-SPEC.md`'s Availability section |
| Invalid WAHA response | Not documented anywhere; reasonable default: treat as an upstream error, log server-side detail, return a generic error to the client (matching the existing `apps.core.exceptions.api_exception_handler` pattern, Phase 1) — **proposed by analogy to existing code, not confirmed by any spec** |
| Invalid frontend request | `400`-class response — standard, not specific to this project, no doc contradicts it |
| Unauthorized frontend request | `401` — matches `docs/09-TEST-PLAN.md`, "Security": *"unauthorized actions return 401/403"* |
| Forbidden operation (authenticated but lacking permission) | `403` — same source |
| Unknown chat | Not documented; reasonable default `404`, unconfirmed |
| Unknown session | Not documented; reasonable default `404`, unconfirmed |
| WAHA timeout | The QR-endpoint probe (Section 5) is live proof WAHA itself can hang; the BFF needs its own bounded timeout — no specific value documented anywhere; **needs an explicit decision**, not invented here |
| WAHA rate/error response | Not documented; WAHA's own error shape was observed as `{"message": "...", "statusCode": ...}` (NestJS default) for a 401 during this and prior rounds — a real, observed data point, not confirmed as its general error contract |

Where a behavior above is marked "reasonable default... not confirmed,"
that is intentional — it is proposed for your confirmation, not adopted
as decided, consistent with the instruction not to invent HTTP semantics
without documenting the reasoning.

---

## 7. Offline / Degraded Mode Compatibility (cross-check against Phase 9)

- **Django temporarily unavailable**: BFF↔WAHA endpoints (session
  status, chat list, message history *if served live by the BFF*,
  sending) must keep working — directly required by the Authentication
  decision (Section 1) and the Availability requirement. Endpoints that
  depend on Django (durable conversation views, anything requiring the
  `Chat.id`→`provider_chat_id` lookup from Section 4) would degrade —
  consistent with `00-MASTER-SPEC.md`'s own framing ("features requiring
  office persistence become degraded," not that the whole system goes
  down).
- **WAHA temporarily unavailable**: Django-backed endpoints (durable
  history, audit, reports) must keep working; BFF↔WAHA endpoints
  degrade — this is the mirror case, already explicit in
  `docs/01-ARCHITECTURE.md`'s "Failure isolation" principle.
  (`GET /api/health/database/`-style independent health signals already
  exist Django-side since Phase 1 for exactly this kind of
  differentiation.)
- **Both unavailable**: the frontend should be able to render *something*
  (cached/last-known state, per `docs/03-UI-UX-SPEC.md`'s "label data as
  live/cached/stale/unavailable") rather than a blank failure — this is
  a frontend (Phase 7) concern more than a Phase 6 one, but Phase 6's
  API responses need to carry enough status information (e.g. a
  distinguishable "WAHA offline" vs. "Django offline" vs. "both offline"
  signal) for Phase 7 to build that UI. **This is the one concrete
  contract Phase 6 must not omit** to avoid making Phase 9 impossible:
  error responses must identify *which* upstream failed, not just that
  "something" failed.

No offline-mode logic is implemented here — this section only defines
the contract Phase 6 must not violate.

---

## 8. WAHA_BASE_URL Configuration — verified

**Confirmed, re-checked directly against the current `backend/.env` this
round**: `WAHA_BASE_URL` now resolves to `<TENCENT_WAHA_HOST>` — the correct,
consistently-confirmed address. The discrepancy flagged in the previous
round's report (`.233`, a one-digit typo) **has been corrected** — not by
any assistant session in this project; the file was not touched here
either round. See the correction note added to
`docs/generated/PHASE-6-SPEC-RESOLUTION.md` for the historical record.
**No further action needed on this item.**

---

## 9. Security Boundary

Using the standing, documented topology (see the terminology flag at the
top of this document — **not** the literal linear diagram in this task's
own Section 9 header, which doesn't match any standing architecture doc):

```
Frontend (browser)
   │                    │
   ▼                    ▼
  BFF                 Django
   │                    │
   ▼                    ▼
 WAHA  ◄─────────────  WAHA
(BFF's own creds)   (Django's own creds, reconciliation)
        WAHA ──────► Django   (webhooks, direct)
```

- **Credentials that may exist only server-side**: WAHA API key (both
  the BFF's and Django's separate copies), the webhook HMAC secret,
  Django's `SECRET_KEY`, the JWT signing/verification key, PostgreSQL
  credentials, Redis connection details — all already treated this way
  by existing code and documentation; nothing here changes that.
- **Credentials that must never reach the browser**: all of the above,
  explicitly and repeatedly required by `CLAUDE.md` rule 3 and multiple
  other documents. The WAHA API key specifically is already only read
  server-side in the existing BFF skeleton (`bff/src/config.ts`) and
  Django settings — confirmed unchanged.
- **Can the WAHA API key ever reach the frontend?** No — never
  documented, never implemented, explicitly forbidden.
- **Can Django credentials (DB password, `SECRET_KEY`) ever reach the
  frontend?** No — same answer, same reasoning; not something a JWT-based
  auth design changes (the JWT *verification* key is shared
  server-to-server, BFF↔Django, never with the browser).
- **What the BFP is trusted to do**: call the fixed, allowlisted set of
  WAHA endpoints on behalf of an authenticated frontend user; nothing
  else — unchanged from every prior document's framing.
- **Authorization responsibilities**: enforced using the JWT's claims
  (Section 1) — the BFF can make a coarse allow/deny decision locally
  from the token without a live Django call, while Django remains the
  system of record for *defining* what those claims mean (via
  `auth.User`/`Group`/`Permission`, Phase 2). No real secret is included
  anywhere in this document or was printed at any point during this
  research.

---

## 10. Phase 6 Implementation Readiness

| Decision | Status | Evidence | Blocking? |
|---|---|---|---|
| Authentication | **DECIDED** — Django-issued, independently-verified signed token (JWT or equivalent) | Section 1; grounded in `00-MASTER-SPEC.md` Availability + `06-SECURITY.md` permission-separation requirements | No (implementation details remain, not architecture) |
| BFF responsibility boundary | **DECIDED** | Section 2 | No |
| BFF-initiated action durability/audit | **DECIDED architecturally** (reuse existing webhook path) — **conditional on** correcting WAHA's webhook target and extending `session.status` handling | Section 2, Section 5 | **Partially** — the architectural direction is set, but the prerequisite webhook-config fix is outstanding |
| Outbound idempotency mechanism | **Direction proposed, not finalized** | Section 2 | **Yes**, for the send-message endpoint specifically |
| Chat identity (LID/`@c.us`) representation | **Partially decided**: use `Chat.id` as the stable frontend-facing identifier | Section 3 | **Yes** — matching a *fresh* live WAHA chat-list entry to an existing `Chat.id` is unresolved |
| Chat list/message-history contract | **Direction set, not finalized** — depends on the identity question above and on where message-history is served from (BFF live vs. Django durable) | Section 4 | **Yes** |
| Session lifecycle (start/stop/restart/logout) | **UNVERIFIED**, cannot be safely tested | Section 5 | **Yes, for this specific slice only** |
| QR/pairing | **UNVERIFIED (inconclusive)** | Section 5 | **Yes, for this specific slice only** |
| Error handling | **Proposed, several items need explicit confirmation** (timeout values, 404 semantics) | Section 6 | No — reasonable defaults proposed, non-blocking |
| Degraded-mode contract | **DECIDED** (error responses must identify which upstream failed) | Section 7 | No |
| WAHA_BASE_URL configuration | **RESOLVED** — confirmed correct now | Section 8 | No |
| Security boundary | **DECIDED**, consistent with existing rules | Section 9 | No |

### Final status

**PHASE 6 NOT READY**

Not because nothing was resolved — this round settled the authentication
architecture, the BFF/Django boundary, the audit-flow design, and
confirmed the configuration issue is fixed. What remains blocking:

1. **Outbound idempotency mechanism** for the send-message endpoint
   (Section 2) — direction proposed, not finalized.
2. **Matching a live WAHA chat-list entry to an existing Django `Chat.id`**
   when they don't share a literal identifier (Section 3) — genuinely
   unresolved, and must not be invented (would risk exactly the kind of
   undocumented normalization this project has repeatedly refused to
   add).
3. **Chat list/message-history source of truth** (BFF-live vs.
   Django-durable) and the resulting contract (Section 4) — depends on
   #2.
4. **Session lifecycle and QR endpoints** — genuinely unverified against
   the real deployment, no safe verification path existed this round
   (Section 5). A narrower Phase 6 (session status + chat + messages
   only, deferring lifecycle/QR to a follow-up slice) could plausibly
   proceed without these — that scoping decision is itself something
   you'd need to make, not something decided here.
5. **WAHA's webhook target correction** — a deployment/configuration
   change (not code), required for the audit-flow design in Section 2 to
   actually function, though it doesn't block writing the Phase 6 code
   itself.

Recommend resolving items 1–3 (and deciding on item 4's scoping) before
implementation begins; item 5 can be fixed in parallel, independently.
