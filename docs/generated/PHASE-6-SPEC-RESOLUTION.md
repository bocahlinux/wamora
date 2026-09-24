# Phase 6 — Specification Resolution

Read-only research and live verification. No application code, models,
migrations, `docker-compose.yml`, frontend, or BFF routes were modified.
The real `test_session` session was never started, stopped, restarted, or
logged out, and no WhatsApp message was sent.

## Important finding, unrelated to Phase 6 itself, surfaced during this research

**Original finding (at the time this report was first written):**
`backend/.env`'s stored `WAHA_BASE_URL` resolved to `100.124.162.233` —
a one-digit difference from `<TENCENT_WAHA_HOST>`, the address you have
consistently confirmed reachable throughout this entire project
(Phases 3–5), including restating it again in that task's own
instructions. A direct connection attempt to `.233` timed out; `.223`
worked immediately and authenticated successfully (Section 4). This was
the most likely reason Django's own reconciliation (Phase 4/5) had never
successfully reached WAHA even from contexts where network routing was
otherwise fine — a variable not previously isolated from the separate,
also-real Docker/NetBird routing limitation found in Phase 5's live
verification.

**Update**: re-checked during the follow-up architecture-decision round
— `backend/.env`'s `WAHA_BASE_URL` now correctly resolves to
`<TENCENT_WAHA_HOST>`. The typo has been corrected (not by any assistant
session in this project — this file was never modified here). See
`docs/generated/PHASE-6-ARCHITECTURE-DECISION.md`, Section 8, for the
current confirmation.

*(A previous edit to this section, made outside this session, briefly
left this paragraph internally self-contradictory — stating the same
address "differs" from itself. That has been corrected above; flagging
per the standing instruction to say so rather than silently rewriting
someone else's edit without comment.)*

## 1. Current architecture

Tencent (Docker): React frontend, Node.js/TS/Express BFF, WAHA (GOWS).
Office (Docker): Django/DRF, Celery worker/beat, Redis. Existing
PostgreSQL, external. See the terminology note in
`docs/generated/PHASE-6-AUTH-AND-API-DECISIONS.md` — this report uses the
standing two-component (separate BFF + separate Django) architecture as
authoritative.

## 2. Authentication options

See `docs/generated/PHASE-6-AUTH-AND-API-DECISIONS.md` for the full
comparison (Django session/cookie, JWT/Bearer, DRF TokenAuthentication).
Not repeated in full here.

## 3. Authentication decision status

**UNRESOLVED.** Explicitly marked "Open" in
`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`. Requires your confirmation.

## 4. Actual WAHA session API — VERIFIED LIVE (read-only calls only)

Authenticated against the real deployment using the real `WAHA_API_KEY`
already present in `backend/.env` (value never printed, read via a
script that loaded it directly into `os.environ`, never through a shell
that could echo it).

| Operation | Method | Path | Verified? | Notes |
|---|---|---|---|---|
| List sessions | GET | `/api/sessions` | **VERIFIED LIVE (200)** | Returns full session objects (see below) |
| Get session | GET | `/api/sessions/{session}` | **VERIFIED LIVE (200)** | Adds an `engine` block vs. the list form |
| Get "me" | GET | `/api/sessions/{session}/me` | **VERIFIED LIVE (200)**, discovered this round | Same content as the `me` field embedded in the session object |
| Start session | POST | *not verified* | **NOT EXECUTED (deliberately)** | Would risk disconnecting the real, active session — explicitly avoided per instructions |
| Stop session | POST | *not verified* | **NOT EXECUTED (deliberately)** | Same reasoning |
| Restart session | POST | *not verified* | **NOT EXECUTED (deliberately)** | Same reasoning |
| Logout/unpair | POST | *not verified* | **NOT EXECUTED (deliberately)** | Same reasoning — explicitly forbidden by this task's own instructions |
| QR/pairing | GET | candidate: `/api/{session}/auth/qr` | **INCONCLUSIVE** | See below |
| Session status | — | — | **No separate endpoint found** | Status is embedded in the `GET /api/sessions/{session}` response (`"status": "WORKING"`), not a dedicated sub-resource |

**Why start/stop/restart/logout could not be verified even by inspection**:
Swagger/OpenAPI documentation was probed at every common path
(`/api`, `/api-docs`, `/swagger`, `/docs`, `/openapi.json`, `/swagger.json`,
`/api-json`, `/swagger-ui`) — all returned `401` (auth-gated, and the
real API key didn't unlock them either) or `404`. No machine-readable API
spec was reachable. An `OPTIONS`-based existence probe was attempted next
as a safe alternative, but a control test (`OPTIONS` on a deliberately
nonexistent path) also returned `204` — proving OPTIONS is handled
generically (likely blanket CORS-preflight handling) and is **not a
reliable signal** on this deployment; that approach was abandoned rather
than trusted. A `HEAD`-based probe was then used instead (validated
reliable via the same control-path technique: nonexistent → `404`, known
real path → `200`) — this correctly ruled out several GET-method
candidates (`/api/sessions/{session}/status`, `/qr`, `/presence` at
various guessed paths all `404`'d) and confirmed `/me` exists. `HEAD`
cannot be used for POST-only actions (start/stop/restart/logout) at all,
since HTTP semantics don't guarantee a meaningful HEAD response for a
POST-only route. **No safe method existed to verify these four
endpoints without either finding real documentation (unavailable) or
invoking the action itself (explicitly forbidden).**

**QR endpoint — a genuinely inconclusive result, reported honestly rather
than guessed**: `GET /api/{session}/auth/qr` (top-level session-prefix
convention, matching the already-confirmed `chats`/`messages` endpoints'
URL shape) returned a **read timeout**, not a `404` — unlike every
genuinely nonexistent path tried, which all responded immediately. This
is *suggestive* that the route exists and the server is doing something
in response (plausibly: waiting to generate a QR code, which may hang
indefinitely for a session that's already connected and has nothing to
pair). This was **not retried or investigated further**, out of caution
— a hanging request to an auth/pairing-related endpoint on the live
session is exactly the kind of thing this task said not to risk. Treat
this as **INCONCLUSIVE, not confirmed**.

## 5. Actual WAHA chat/message API — VERIFIED LIVE, with a significant new finding

**`GET /api/{session}/chats`** — VERIFIED LIVE. Real response for
`test_session` (2 entries):
```json
[
  {"id": "62800000001@c.us", "name": "@test_business", "conversationTimestamp": 1790141319},
  {"id": "62800000000@c.us", "name": "Yuk Code Creative", "conversationTimestamp": 1790156457}
]
```
This is a **much smaller shape** than a message object — just `id`,
`name`, `conversationTimestamp`. No `_data.Info.*`, no LID form anywhere.
The first entry (`62800000001@c.us`) is literally the session's own
`me.id` — an apparent self-chat/saved-messages entry.

**Significant new finding — the chat list and message-history endpoints
disagree on identity, and message-history transparently merges across
identities**: `000000000000000@lid` — the chat used throughout this
project's entire evidence chain since Phase 2.5 — **does not appear in
this chat list at all.** Instead, the real-world contact it refers to is
listed only as `62800000000@c.us`.

Tested directly (both directions, read-only `GET` calls, `limit=5`–`12`):
- `GET /api/test_session/chats/62800000000@c.us/messages` → returns
  messages from **both** `62800000000@s.whatsapp.net` (2 outbound) *and*
  `000000000000000@lid` (the rest) — merged into one chronological list.
- `GET /api/test_session/chats/000000000000000@lid/messages` → returns the
  **same merged set**, confirmed bidirectional.

**This is new evidence beyond what `docs/12-WAHA-REFERENCE.md` already
documented.** The prior "known limitation" section described identity
fragmentation as a *risk* for local storage (two `Chat` rows for one real
contact). This round shows WAHA's own message-history endpoint **already
resolves/merges the two identities server-side** when fetching by either
one — but the **chat-listing endpoint does not expose the LID form at
all**, only the `@c.us` form. Practical implication for Phase 6 design
(not a Phase 4/5 code defect — reconciliation's existing per-known-chat
querying still works correctly per message, protected by the
`(session, provider_message_id)` constraint regardless): **if a BFF "list
chats" endpoint uses `GET /api/{session}/chats` as its source of truth,
the LID-only chat identity this project has extensively used in testing
would never surface as a distinct listed chat — only its `@c.us`
counterpart would.** This is directly relevant to whether the BFF should
treat WAHA's chat list as authoritative, or whether some other approach
(e.g., listing from locally-known `Chat` rows, which Phase 4 already
scopes reconciliation to) is more appropriate — a design question for
Phase 6, not resolved here.

**`POST /api/sendText`** — **NOT invoked**, per explicit instruction not
to send a message without a confirmed safe recipient (none was
established). Its request/response shape is inferred only indirectly:
messages found in history with `"source": "api"` (e.g.
`true_62800000000@c.us_3EB0B21AB186B9D17204AA`, body `"Hi there!"`) are
almost certainly the result of a prior real `sendText` call, giving
circumstantial (not directly confirmed) insight into the resulting
message shape — not a substitute for actually observing the endpoint's
own request/response contract.

**Cross-reference with Phase 2.5/3/4 findings**: `payload.id` /
`messages[].id` format, `_data.Info.ID` distinction, `SenderAlt`
behavior, `fromMe` semantics, and confirmed `limit`+`offset` pagination
(newest-first, `page` non-functional) — all **re-confirmed consistent**
with every live message fetched this round. No contradiction found. The
one genuinely new piece of information is the chat-list/message-merge
behavior above.

## 6. BFF boundary

**A. Operations that should be BFF proxy operations** (live WAHA
interaction, matching the documented "Frontend -> BFF" examples in
`docs/07-API-CONTRACT.md`): session status display, chat listing,
message history, sending a message, session lifecycle control (once its
underlying WAHA endpoints are actually confirmed — Section 4), QR/pairing
display (same caveat).

**B. Backend-internal operations that should NOT be exposed to the
frontend**: the WAHA API key and webhook HMAC secret themselves (never
reach the browser, per every hard rule in this project); WAHA's full raw
session `config`/`me`/`messageCapping` object observed in Section 4
likely contains more detail than a frontend needs — whether to pass it
through verbatim or shape a reduced response is a Phase 6 design
decision, not specified anywhere.

**C. Existing Django operations that already talk to WAHA directly, not
through the BFF**: reconciliation (`apps/sync/waha_client.py`, Phase 4/5)
— confirmed, unchanged, and **not a conflict** with "frontend never calls
WAHA directly" (that rule concerns the browser specifically, not Django).
Worth restating plainly so Phase 6 doesn't assume the BFF is the only
WAHA caller in the system (already flagged in
`docs/generated/PHASE-6-SPEC-REVIEW.md` Section 19).

**Not assumed**: that the BFF must proxy *every* WAHA endpoint verbatim —
no document requires this, and Section 5's chat-list finding is a
concrete reason it might not want to (WAHA's chat list alone would hide
the LID-form conversation this project's own data already depends on).

## 7. Authorization model

**UNSPECIFIED beyond the categories named in `06-SECURITY.md`** ("session
control, reading, sending, blast, user administration and system
administration"). No document states whether this is single-user,
role-based, or session-based (in the WAHA-session sense). **Do not invent
roles.**

**Minimum information required before implementation**: (1) the
authentication decision (Section 3) — authorization can't be designed
independent of how a user is identified; (2) whether one authenticated
user may access *all* WAHA sessions (currently just one, `test_session`,
though `docs/00-MASTER-SPEC.md` anticipates up to 2–3) or whether
per-session authorization is required — **not stated anywhere**, and
genuinely ambiguous given `04-DATA-MODEL.md`'s suggested `Role`/`Permission`
entities were never built (Phase 2 used Django's built-in `auth.Group`/
`Permission` instead, per that phase's own documented decision) without
any session-scoping dimension defined on them.

## 8. CSRF and browser security

- Whether CSRF protection is required is **conditional on the
  authentication decision** (Section 3) — needed for cookie-based auth
  (Option A), not needed by default for header-based bearer tokens
  (Options B/C), per the analysis in the auth-decisions report.
- State-changing BFF methods (once endpoints exist): sending a message,
  marking read, session start/stop/restart/logout — all would need
  whatever CSRF defense the chosen auth mechanism requires.
- CORS: `bff/src/config.ts` already defines `CORS_ALLOWED_ORIGIN`
  (Phase 0), currently **not wired into any actual CORS middleware** in
  `bff/src/index.ts` — the variable exists but does nothing yet. No
  document states the actual origin value(s) for any environment.
  **UNSPECIFIED.**
- Cookie requirements: depend entirely on the auth decision.
- Whether WAHA credentials can ever reach the browser: **explicitly,
  repeatedly forbidden** (`CLAUDE.md` rule 3, multiple documents) — not
  in question, already enforced by the BFF's existing design (the API key
  is read server-side only, `bff/src/config.ts`, never serialized to any
  response).

## 9. Proposed BFF API surface (proposal only — not implemented)

Presented as candidates to evaluate, explicitly not assumed correct, per
the task's own instruction:

| Endpoint (candidate) | Purpose | Auth | Authz | Upstream WAHA call | Data source | Notes |
|---|---|---|---|---|---|---|
| `GET /api/sessions` | List WAHA sessions | Required (mechanism TBD) | "reading" scope | `GET /api/sessions` | WAHA (live) | Thin passthrough plausible |
| `GET /api/sessions/:id` | Session detail/status | Required | "reading" | `GET /api/sessions/{id}` | WAHA (live) | — |
| `POST /api/sessions/:id/start` \| `/stop` \| `/restart` | Session lifecycle | Required | "session control" | **unconfirmed** (Section 4) | WAHA (live) | **Cannot be finalized until the real endpoint is confirmed** |
| `GET /api/sessions/:id/qr` | Pairing QR | Required | "session control" | **inconclusive** (Section 4) | WAHA (live) | Same caveat |
| `GET /api/chats` | List chats | Required | "reading" | `GET /api/{session}/chats` **or** locally-known `Chat` rows | WAHA or PostgreSQL | **Open design question** (Section 5/6) — WAHA's own list hides the LID-form chat this project's data depends on |
| `GET /api/chats/:id/messages` | Message history | Required | "reading" | `GET /api/{session}/chats/{chatId}/messages` | WAHA (live) or PostgreSQL (durable) | Both are plausible sources — WAHA for "live," PostgreSQL for "durable conversation view" per `07-API-CONTRACT.md`'s Frontend→Django category; not resolved which the BFF vs. Django should serve |
| `POST /api/chats/:id/messages` | Send message | Required | "sending" | `POST /api/sendText` | WAHA (live), with an `OutboundOperation` idempotency record in PostgreSQL (Phase 2 model, unused so far) | Needs an idempotency-key contract — not specified |

**Error mapping, pagination behavior, and exact response shape**: not
proposed here beyond noting that `docs/07-API-CONTRACT.md`'s principles
(JSON, consistent errors, request IDs, pagination, idempotency keys) and
this project's own Django-side precedent (Phase 1's `X-Request-ID` +
`{"error": {...}}` envelope) are the only concrete reference points that
exist — whether the BFF should match them exactly is unresolved.

## 10. Data ownership

- **PostgreSQL owns**: durable users, chats/messages (once
  ingested/reconciled), webhook records, sync checkpoints, outbound
  operations, audit, reporting (`00-MASTER-SPEC.md`, unchanged, already
  implemented Phase 2–5).
- **WAHA owns**: live WhatsApp/session state — the real-time source of
  truth for what's happening right now (`00-MASTER-SPEC.md`, unchanged).
- **BFF is**: per every document, **a proxy/gateway with no database
  access of its own** (`docs/generated/PHASE-6-SPEC-REVIEW.md` Section
  17) — not an application API with its own data model, not a read
  model. **No new persistence layer is introduced or proposed here.**
  Whether specific BFF endpoints should read from WAHA directly or (via
  Django) from PostgreSQL is exactly the open design question in
  Section 9's `GET /api/chats*` rows — the BFF itself stays stateless
  either way.

## 11. Failure behavior (documented expectations only — not implemented)

- **WAHA unavailable**: per `docs/03-UI-UX-SPEC.md`/`CLAUDE.md`'s offline
  rule, this must be surfaced as a distinct status, independent of
  office/database status — already a first-class concept in this
  project's design, just not yet wired into any BFF/frontend code.
- **WAHA session disconnected**: reflected in the session's own `status`
  field (confirmed live this round — e.g. `"WORKING"`); a disconnected
  session would presumably show a different value, though no
  disconnected-state example was observed (the real session was healthy
  throughout this verification).
- **Invalid session** (a BFF request naming a WAHA session that doesn't
  exist): not documented; reasonable to expect a `404`-shaped error, not
  specified anywhere.
- **WAHA timeout**: the QR-endpoint probe (Section 4) is a live example
  of WAHA itself hanging rather than erroring — the BFF would need its
  own timeout/circuit-breaking behavior, not specified anywhere.
- **Invalid WAHA response**: not documented.
- **Authentication failure / unauthorized user**: not documented beyond
  the general principle that unauthorized actions should be rejected
  (`docs/09-TEST-PLAN.md`, "Security": *"unauthorized actions return
  401/403"*) — concrete shape unspecified.
- **PostgreSQL unavailable**: already a first-class, tested concept
  Django-side since Phase 1 (`GET /api/health/database/`) — not yet
  connected to anything the BFF does, since the BFF has no direct
  Postgres dependency (Section 10).

## 12. Known limitations

1. Authentication remains unresolved — the single largest blocker,
   consistent with `docs/generated/PHASE-6-SPEC-REVIEW.md`'s verdict.
2. Session lifecycle (start/stop/restart/logout) endpoints could not be
   confirmed by any safe means available this round (Section 4).
3. QR/pairing endpoint existence is inconclusive, not confirmed
   (Section 4).
4. The chat-list vs. message-history identity discrepancy (Section 5) is
   new information that materially affects how a "list chats" BFF
   endpoint should be designed — not something the existing
   `docs/12-WAHA-REFERENCE.md` "known limitation" language fully
   anticipated.
5. `sendText`'s actual request/response contract was not directly
   observed (deliberately, per instruction).
6. The `WAHA_BASE_URL` typo (top of this report) is a real, unrelated bug
   worth fixing, reported but not corrected here.
7. Swagger/OpenAPI documentation is not reachable on this deployment by
   any path tried, with or without the real API key — future
   verification rounds will face the same limitation unless a different
   discovery method becomes available.

## 13. Exact decisions still requiring human approval

1. **Authentication mechanism** (Section 2/3) — the blocking decision.
2. Whether "Frontend → Django BFF → WAHA" in this task's own instructions
   signals a desired architecture change, or was informal shorthand (see
   the terminology flag in the auth-decisions report) — needs an
   explicit answer, not an assumption.
3. Whether the BFF's "list chats"/"get messages" should source from WAHA
   directly, from Django/PostgreSQL, or both (Section 5/9).
4. Authorization model shape — single-user vs. role-based vs.
   session-scoped (Section 7).
5. Whether the BFF should adopt Django's existing request-ID/error-envelope
   convention or define its own (Section 9).
6. Confirmation of session-lifecycle/QR WAHA endpoints via a safe method
   this session didn't have available (real Swagger access, or explicit
   authorization to test against a *non-active* or disposable WAHA
   session).

## 14. Whether Phase 6 is ready for implementation

**NOT READY** — consistent with `docs/generated/PHASE-6-SPEC-REVIEW.md`.
This round resolved and sharpened several open questions with real live
evidence (Sections 4–5) and produced a concrete options analysis for the
one decision blocking everything else (authentication), but did not
resolve that decision, and surfaced one new significant gap (session
lifecycle/QR endpoints unconfirmed) rather than closing it. Recommend
resolving Section 13's items — at minimum item 1 — before implementation
begins.
