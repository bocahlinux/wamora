# Phase 6 — BFF Specification Review (Read-Only)

No files were modified. No endpoints, serializers, views, or migrations
were created. This is a documentation/source cross-reference only.

## Documents and source files located and reviewed

Beyond the suggested list, a repo-wide search for "BFF" was run first to
avoid assuming the suggested filenames were exhaustive. Full result: all
18 `docs/*.md` files, `docs/CLAUDE.md`, `CLAUDE.md` (root), `README.md`
(root) and `docs/README.md`, and every `docs/generated/PHASE-*.md` report
(0 through 5) mention BFF at least once. Also inspected as "existing
source files relevant to Phase 6":
- `bff/src/index.ts`, `bff/src/config.ts`, `bff/src/wahaAllowlist.ts` —
  the entire existing BFF codebase (Phase 0 skeleton: a health endpoint,
  an env-driven config object, and a deliberately empty allowlist array).
- `bff/.env.example`, `bff/package.json` — confirms `PORT`, `WAHA_BASE_URL`,
  `WAHA_API_KEY`, `CORS_ALLOWED_ORIGIN` as the only BFF-side config
  established so far.
- Backend URL/view/serializer structure: `backend/apps/*/urls.py`,
  `views.py`. **No `serializers.py` exists anywhere in the backend** —
  confirmed by direct search. Existing Django routes are only
  `/admin/`, `/api/health/`, `/api/health/database/`,
  `/api/webhooks/waha/` — no chat/message/session/contact API exists on
  either side yet.
- `docs/generated/PHASE-0` through `PHASE-5-*.md` — every "Files
  modified"/"Scope confirmation" section was checked; none touched BFF
  code beyond the Phase 0 skeleton, and none contains a BFF endpoint
  specification.

---

## 1. Phase 6 stated objective

**EXPLICITLY SPECIFIED (name only)**: `docs/15-CODING-PHASES.md` lists
phase 6 as `"BFF"` — no accompanying description of deliverables, unlike
this review request's level of detail for other phases.

**IMPLIED BY EXISTING DOCUMENTATION**: combining the phase name with the
BFF's role description elsewhere (`01-ARCHITECTURE.md`, `06-SECURITY.md`,
`CLAUDE.md`), the objective is reasonably inferred as: *implement the
BFF's server-side boundary between the browser and WAHA* — but no
document states this as a formal "Phase 6 objective" statement, and no
document lists concrete Phase 6 deliverables the way `docs/05-WEBHOOK-SYNC-DESIGN.md`
does for reconciliation.

## 2. Exact responsibilities of the BFF

**EXPLICITLY SPECIFIED** (`01-ARCHITECTURE.md`, `06-SECURITY.md`, `CLAUDE.md`,
`00-MASTER-SPEC.md`):
- "Server-side boundary antara browser dan WAHA."
- Protects WAHA credentials (never reach the browser).
- Performs validation/authorization.
- Exposes only the endpoints actually needed.
- Preferred flow: `Browser -> BFF -> WAHA`.
- Reaches WAHA over the Docker network where practical (both are on
  Tencent — this is a local, same-host network hop, distinct from the
  NetBird-routed Django→WAHA path used by reconciliation, Phase 4/5).
- Is explicitly **not** a generic proxy (`00-MASTER-SPEC.md` lists
  "generic BFF proxy" under Non-goals).

**IMPLIED BY EXISTING ARCHITECTURE** (by exclusion): since
`01-ARCHITECTURE.md` assigns "durable application data, webhook
ingestion, reconciliation, audit, reporting, permissions, dan business
rules" to the Backend (Django), the BFF's responsibility is implied to be
narrowly scoped to *live* WAHA interaction only — no durable persistence,
no business rules of its own.

## 3. Explicitly required endpoints

**EXPLICITLY SPECIFIED, but only as a non-exhaustive example list**
(`docs/07-API-CONTRACT.md`, under "Frontend -> BFF", literally headed
"Examples:"): session status; chats; messages; send text; mark read;
session lifecycle; QR/pairing.

**UNSPECIFIED**: exact URL paths, HTTP methods, request bodies, response
bodies, status codes, or a formal endpoint table for any of these. No
document provides a concrete BFF API schema.

## 4. Explicitly forbidden responsibilities

**EXPLICITLY SPECIFIED**:
- Not a generic URL proxy (`CLAUDE.md` rule 5, `01-ARCHITECTURE.md`,
  `06-SECURITY.md`, `00-MASTER-SPEC.md` Non-goals).
- No arbitrary target URL / SSRF protection — allowlist only
  (`06-SECURITY.md`).
- WAHA API key must never reach the frontend/browser/localStorage/bundle
  (`CLAUDE.md` rule 3, `docs/CLAUDE.md`).
- Frontend must never call WAHA directly — the BFF is the only path
  (`CLAUDE.md` rule 4).

**IMPLIED BY EXCLUSION**: durable persistence, audit-of-record, reporting,
reconciliation, and general business rules stay with Django
(`01-ARCHITECTURE.md`'s explicit ownership split) — nothing states "the
BFF must not do X" for these directly, but their explicit assignment to
Django, combined with the BFF's stated narrow scope, makes this a strong
inference rather than an explicit prohibition.

## 5. Authentication requirements

**EXPLICITLY SPECIFIED**: authentication is a required capability
(`docs/02-REQUIREMENTS.md`, "Security" section lists it as a category).

**UNSPECIFIED — and explicitly flagged as unresolved by the docs
themselves**: `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`, "Open" section,
item 1: *"exact auth implementation."* No document specifies the
mechanism (session cookie? JWT? OAuth? something else), where it is
issued/verified (BFF, Django, or both), or how a frontend request
authenticates against the BFF specifically. **This is the single largest
gap for Phase 6** — nearly every other endpoint requirement depends on it.

## 6. Authorization requirements

**EXPLICITLY SPECIFIED** (`06-SECURITY.md`): *"Separate permissions for
session control, reading, sending, blast, user administration and system
administration."*

**UNSPECIFIED**: the permission model itself (roles vs. scopes vs.
claims), where authorization is enforced (BFF before calling WAHA?
Django? both, redundantly?), and how the BFF would even know a given
frontend user's permissions (it has no database access — see Section
17 — so it would need this from Django or from the auth token itself,
neither of which is specified).

## 7. Session-scoping requirements

Two distinct meanings of "session" are relevant, and the docs don't
distinguish them explicitly:
- **WAHA session** (e.g. `test_session`) — **IMPLIED BY EXISTING WAHA
  REFERENCE**: every observed real WAHA endpoint is session-scoped
  (`GET /api/{session}/chats`, etc. — `docs/12-WAHA-REFERENCE.md`), so
  BFF endpoints that wrap these would need to accept/pass a session
  identifier. No document states the BFF's own URL shape for this
  (e.g. whether the BFF mirrors `/api/{session}/...` or uses a different
  convention).
- **User/browser auth session** — **UNSPECIFIED entirely**, tied
  directly to the unresolved auth mechanism (Section 5).

## 8. Request/response contract requirements

**EXPLICITLY SPECIFIED** (`docs/07-API-CONTRACT.md`, "Principles"):
*"JSON, consistent errors, request IDs, pagination, timestamps,
permissions, and idempotency keys for side-effecting operations."* Stated
once, under the general "API Contract" document, not separately for BFF
vs. Django — reasonably read as applying to both, though not stated for
BFF by name.

**IMPLIED BY EXISTING CODE**: Django's own API (Phase 1) already
implements a concrete version of this — `apps.core.middleware.RequestIDMiddleware`
(`X-Request-ID` header) and `apps.core.exceptions.api_exception_handler`
(a `{"error": {"code", "message", "request_id"}}` envelope). No document
says the BFF must reuse this exact shape, but it is the only concrete
precedent that exists in this project for what "consistent errors" and
"request IDs" mean in practice.

**UNSPECIFIED**: whether the BFF is expected to match Django's envelope
exactly, use its own, or whether frontend code is expected to handle two
different error shapes from the two backends it talks to.

## 9. Error response requirements

Same principle as Section 8 ("consistent errors"). **UNSPECIFIED**: no
concrete error schema is defined for the BFF anywhere.

## 10. Pagination/filter/search requirements

**EXPLICITLY SPECIFIED** (as a principle only): pagination is listed in
`docs/07-API-CONTRACT.md`'s principles.

**IMPLIED BY EXISTING WAHA REFERENCE**: WAHA's own confirmed pagination
mechanism (`limit`+`offset`, newest-first, `page` does not work —
`docs/12-WAHA-REFERENCE.md`, confirmed live in Phase 4/5) exists for the
underlying chat-history endpoint the BFF would presumably wrap — but no
document states whether the BFF should expose this same mechanism
verbatim to the frontend, translate it, or something else.

**UNSPECIFIED**: filtering and search are not mentioned in any document
for the BFF (or anywhere else) — not even as a stated principle.

## 11. Chat/message API requirements

**EXPLICITLY SPECIFIED** (functional categories only): "chats", "messages",
"send text", "mark read" appear in `docs/07-API-CONTRACT.md`'s example
list and `docs/00-MASTER-SPEC.md`'s feature list ("chat list; message
history; receive/send/reply; mark as read").

**IMPLIED BY EXISTING WAHA REFERENCE**: the underlying WAHA calls these
would presumably wrap are confirmed and observed —
`GET /api/{session}/chats`, `GET /api/{session}/chats/{chatId}/messages`,
`POST /api/sendText` (`docs/12-WAHA-REFERENCE.md`). No "mark as read"
WAHA endpoint has ever been observed or documented anywhere in this
project.

**UNSPECIFIED**: the BFF's own endpoint paths, methods, and request/
response schemas for any of these.

## 12. Contact API requirements

**Not mentioned as a BFF responsibility anywhere.** `docs/04-DATA-MODEL.md`
lists `Contact` as a durable entity, and `01-ARCHITECTURE.md`'s ownership
split assigns durable data to Django, not the BFF. **IMPLIED BY DATA
OWNERSHIP**: if a Contact API exists at all as something distinct from
WAHA's own live chat listing, it would logically belong to
"Frontend -> Django" (`docs/07-API-CONTRACT.md`'s "durable conversation
views"), not the BFF. **UNSPECIFIED** whether the BFF needs any
Contact-related endpoint at all.

## 13. Session API requirements

**EXPLICITLY SPECIFIED** (functional categories): "session status",
"session lifecycle", "QR/pairing" (`07-API-CONTRACT.md`);
"monitoring session; start/stop/restart; QR/pairing"
(`00-MASTER-SPEC.md` features).

**Significant gap, worth flagging directly**: `docs/12-WAHA-REFERENCE.md`
only ever confirmed `GET /api/sessions`, `GET /api/sessions/{session}`,
`GET /api/{session}/chats`, `GET /api/{session}/chats/{chatId}/messages`,
and `POST /api/sendText` against the real deployed WAHA instance. **No
start/stop/restart or QR-pairing WAHA endpoint has ever been observed,
tested, or documented anywhere in this project's evidence chain**
(Phases 2.5–5 all verified message/history/pagination behavior, never
session lifecycle control). This is a real, concrete gap: a stated
product feature and a stated BFF responsibility category rest on WAHA
endpoints that have never been confirmed to exist or behave a particular
way on this deployment.

## 14. Audit/logging requirements

**EXPLICITLY SPECIFIED** (`06-SECURITY.md`): *"Record actor, time,
action, target and result for sensitive operations."* Implemented on the
Django side (Phase 2's `AuditLog` model).

**UNSPECIFIED**: how a BFF-initiated action (e.g. a user sending a
message through the BFF) gets recorded in Django's `AuditLog` — no
document describes a BFF→Django audit-event flow, a shared audit API, or
whether the BFF is expected to log independently instead. Given
`01-ARCHITECTURE.md` assigns "audit" to Django specifically, this is a
real architectural gap: the BFF is the component initiating many
sensitive actions but has no described mechanism to get them into the
system of record.

## 15. Rate-limit requirements

**EXPLICITLY SPECIFIED** (`06-SECURITY.md`): *"Rate limits: Login, send,
session control, blast and expensive sync."* — the categories are named.

**UNSPECIFIED**: exact limits (requests per second/minute, per-user vs.
per-IP), enforcement point (BFF vs. Django vs. both), and mechanism
(in-memory, Redis-backed, etc.). Since "send" and "session control" are
BFF-domain operations, BFF-level enforcement is clearly implied as
necessary somewhere, but nothing concrete exists to implement against.

## 16. CORS/CSRF requirements

**IMPLIED BY EXISTING CODE**: `bff/.env.example`/`bff/src/config.ts`
already define a `CORS_ALLOWED_ORIGIN` variable (Phase 0 scaffold,
currently unused by any actual CORS middleware — `bff/src/index.ts` has
no CORS handling implemented yet). This implies restricting the BFF to a
specific frontend origin was anticipated, but no document states the
actual policy (which origins in which environments, credentialed
requests or not).

**UNSPECIFIED**: CSRF — `docs/02-REQUIREMENTS.md`/`06-SECURITY.md` both
say "where applicable" without resolving whether it's applicable, which
depends entirely on the unresolved auth mechanism (cookie-based auth
would need CSRF defense; token-in-header auth typically would not).

## 17. Database access rules

**No document mentions the BFF accessing any database.** `04-DATA-MODEL.md`
and `01-ARCHITECTURE.md` describe PostgreSQL as exclusively Django's
domain. **IMPLIED BY ARCHITECTURE** (strongly, by consistent silence
plus the explicit "Backend: durable application data" ownership
statement): the BFF is expected to be stateless with **no database
access of its own** — not stated as an explicit prohibition anywhere,
but not contradicted anywhere either, and consistent with every other
document's framing of the BFF as a live-only gateway.

## 18. Interaction with existing Phase 3 webhook ingestion

**EXPLICITLY SPECIFIED (by topology, meaning no interaction)**: the
webhook path is `WAHA -> Django` directly (`docs/07-API-CONTRACT.md`,
"WAHA -> Django" section; confirmed by Phase 3's actual implementation,
`apps/webhooks/views.py`, which is a Django endpoint WAHA calls directly).
**The BFF has no role in webhook ingestion.**

## 19. Interaction with Phase 4 reconciliation

**EXPLICITLY SPECIFIED (by topology, meaning no interaction) — with a
worth-noting architectural detail**: reconciliation is Django calling
WAHA directly (`apps/sync/waha_client.py`, Phase 4/5, using its own
`WAHA_BASE_URL`/`WAHA_API_KEY` configured on the Django side, confirmed
live in Phase 5's verification). **This means Django and the BFF are two
independent, separately-credentialed callers of WAHA** — this does not
contradict "frontend never calls WAHA directly" (that rule is
specifically about the frontend/browser, not about Django), but it is
worth stating plainly so a Phase 6 implementer doesn't assume the BFF is
the *only* thing in this system that ever talks to WAHA.

## 20. Interaction with Phase 5 Celery/Redis

**EXPLICITLY SPECIFIED (by topology, meaning no interaction)**: Celery
and Redis are Office-side, Django-only infrastructure
(`docs/00-MASTER-SPEC.md`, `08-DEPLOYMENT.md`). No document describes any
BFF relationship with either.

## 21. Requirements that Phase 7 (Frontend) depends on

Phase 7 will need, at minimum: the BFF's base URL/response envelope
shape, an authentication mechanism the frontend can implement against,
and a CORS policy allowing the frontend's actual origin. **The
authentication gap (Section 5) is a direct, blocking dependency** — the
frontend cannot be built against an undefined auth contract without
either Phase 6 resolving it or Phase 7 inventing something Phase 6 never
specified.

## 22. Requirements that Phase 8 (Inbox/Chat) depends on

Phase 8 needs concrete, stable chat-list/message-history/send/mark-read
contracts (paths, request/response shapes, pagination behavior) from
Phase 6 — none of which currently exist beyond the functional-category
examples in Section 11. Fully blocked on Phase 6 defining them.

## 23. Ambiguities or missing specifications (consolidated)

1. Exact authentication mechanism (explicitly marked "Open" —
   `11-DECISIONS-AND-OPEN-QUESTIONS.md`) — the largest, most blocking gap.
2. Authorization enforcement point and permission model.
3. Concrete BFF endpoint paths/methods/request/response schemas for
   every functional category in Section 3.
4. Concrete error-envelope shape for the BFF specifically.
5. Pagination mechanism for BFF-exposed listing endpoints.
6. Session-lifecycle and QR-pairing WAHA endpoints — never observed or
   confirmed against the real deployment (Section 13).
7. BFF→Django audit-event flow (Section 14).
8. Exact rate-limit values and enforcement mechanism.
9. CORS policy specifics; whether CSRF applies (depends on #1).
10. WebSocket vs. SSE for real-time updates — explicitly listed as "Open"
    (`11-DECISIONS-AND-OPEN-QUESTIONS.md`) and directly relevant if any
    BFF endpoint is meant to stream live updates to the frontend.
11. TLS/domain — explicitly "Open" — affects whether the BFF terminates
    TLS itself or sits behind something else.
12. NetBird/firewall rules — explicitly "Open" — affects real-world
    reachability, though not the BFF's own code.

## 24. Conflicts between documents

**None found.** Consistent with every prior phase's validation in this
project (Phase 0's architecture validation also found zero conflicts):
every document that touches the BFF agrees on its role, its boundaries,
and the hard rules around it. The challenge for Phase 6 is **sparseness
of specification, not contradiction** — nothing says two incompatible
things; most things simply aren't said at all.

## 25. Things that must NOT be invented during implementation

- The authentication mechanism (session/JWT/OAuth/other) — explicitly
  open; inventing one would be exactly the kind of undocumented
  architectural decision this project's standing rules forbid making
  silently.
- Exact endpoint paths/methods/schemas — not specified, and per this
  project's established pattern (Phases 3/4/5), a foundational API
  contract like this is the kind of decision that has previously
  warranted stopping to confirm rather than choosing unilaterally.
- Session-lifecycle/QR-pairing WAHA endpoint paths — never observed
  live; inventing them risks the exact "invented endpoint" failure mode
  this project has repeatedly guarded against for WAHA-facing code.
- Rate-limit numeric values.
- CORS allowed-origin values beyond the existing placeholder env var.
- Any Contact/Chat identity merge or normalization logic — the standing
  rule from Phase 2.5 onward continues to apply unchanged; nothing in
  Phase 6's scope touches or should touch this.
- A PostgreSQL container, or any BFF-side database access at all
  (Section 17).

## 26. Recommended implementation boundary for Phase 6

Given that authentication — the one gap nearly everything else depends
on — is explicitly unresolved, a full BFF implementation cannot proceed
without either resolving it first or inventing a major, undocumented
architectural decision. A narrower, defensible starting boundary *would*
exist (wrapping only the WAHA endpoints already confirmed live — session
status, chat listing, message history — behind the existing allowlist
pattern, deferring anything requiring auth, session-lifecycle control, or
rate-limit specifics), but that boundary itself is a scoping decision,
not something this read-only review should decide. Recommend surfacing
the authentication question explicitly before any Phase 6 implementation
begins.

---

## Final verdict

**PHASE 6 SPEC NOT READY**

Reasoning: the specifications are sufficient to identify the BFF's role,
boundaries, and hard constraints with confidence (Sections 2, 4, 17–20),
but insufficient to implement the actual required endpoints without
inventing a major API contract — specifically, the authentication
mechanism (Section 5), which is explicitly marked unresolved in the
project's own decisions log and which nearly every other requirement in
this review depends on. Endpoint paths/schemas, session-lifecycle WAHA
behavior, audit-event flow, and rate-limit specifics are secondary gaps
that compound this, but authentication alone is sufficient to make this
verdict "NOT READY" rather than "READY with minor gaps."
