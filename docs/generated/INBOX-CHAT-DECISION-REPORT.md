# Inbox/Chat — Architecture & Contract Decision Preparation

**Read-only.** No source, config, `.env`, migration, dependency, or
infrastructure file was modified. **No implementation was performed.**
No Inbox UI was built. Canonical Phase 9 was not started.

This report follows `docs/generated/INBOX-CHAT-AUDIT-REPORT.md` and
exists to resolve, as far as the evidence allows, the open questions
that audit surfaced — so the remaining genuine product decisions can be
made in one short pass before implementation begins.

**Additional evidence gathered this task** (beyond the prior audit):
`docs/12-WAHA-REFERENCE.md` (full), `backend/requirements.txt`,
`backend/config/asgi.py`, `backend/config/celery.py`,
`backend/Dockerfile`, `infrastructure/office/docker-compose.yml`,
`backend/config/settings.py`'s CORS block, a repository-wide grep for
any direct Redis/pub-sub/Channels/WebSocket usage in project code
(excluding `venv/`), and a fresh read-only query of this environment's
actual `Chat`/`Message`/`Contact`/`MediaReference`/`WebhookEvent` row
counts and the one existing `Chat` row's detail.

---

## 1. API ownership / request paths

### Resolving the `07-API-CONTRACT.md` vs `00-MASTER-SPEC.md` conflict

**Evidence:**
- `docs/00-MASTER-SPEC.md` "Ownership": *"PostgreSQL: durable users,
  chats/messages, webhook records, sync checkpoints, outbound
  operations, audit, reporting."* — explicit, unambiguous durable-data
  ownership statement.
- `docs/CLAUDE.md` hard rule 5: *"The BFF is not a generic URL proxy; it
  must use an explicit allowlist of WAHA endpoints."* The BFF's
  allowlist (`bff/src/wahaAllowlist.ts`) is a **closed set of WAHA REST
  calls** — it has no concept of "read from Django" at all; every entry
  in it targets WAHA directly.
- **Existing, already-built, already-tested precedent**: the Phase 8
  dashboard work built `GET /api/dashboard/messages/` and `GET
  /api/dashboard/activity/` as **Frontend → Django direct** calls for
  exactly this class of data (durable, DB-backed, no live WAHA
  involvement) — confirmed by re-reading `frontend/src/lib/djangoApi.ts`
  and `backend/apps/dashboard/views.py` again this task.
- Counter-evidence: `docs/07-API-CONTRACT.md` literally lists "chats,
  messages, send text, mark read" under *"Frontend -> BFF."*

**Recommendation**: adopt **Frontend → Django direct** for chat list and
message history, matching the Dashboard precedent and the master spec's
explicit ownership statement. The BFF's role stays exactly what it
already is — live WAHA session control and sending — and does not grow a
new "proxy Django's own data back out through me" responsibility, which
would be architecturally redundant (an extra network hop for data the
BFF doesn't own and has no independent way to validate) and would
require inventing new `wahaAllowlist.ts` entries that don't actually
call WAHA for anything.

**This is a recommendation, not a unilateral resolution** — see
"USER DECISIONS REQUIRED" at the end; it is evidence-backed but the
final call is still yours to confirm, per this task's own instruction
not to silently resolve product decisions.

**Documents that would become stale if adopted**: `docs/07-API-CONTRACT.md`'s
"Frontend -> BFF" example line would need editing to drop "chats,
messages, mark read," leaving only what's actually BFF-appropriate
("send text," session lifecycle, QR/pairing — all live WAHA actions).
Not changed in this task; flagged for your future edit alongside
whichever implementation phase acts on this recommendation.

### Recommended request path, per operation

| Operation | Recommended path | Evidence |
|---|---|---|
| (a) Chat list | Frontend → Django | Durable data, `00-MASTER-SPEC.md` ownership, Dashboard precedent |
| (b) Message history | Frontend → Django | Same |
| (c) Send message | Frontend → BFF → WAHA | **Unchanged** — already built, tested, live-action-appropriate; `docs/CLAUDE.md` rule 4 requires this path for anything touching WAHA |
| (d) Mark as read | Frontend → Django (recommended default) | See Section 2 — no confirmed WAHA capability to sync read state exists in this project's evidence; a durable, Django-owned UI-attention flag doesn't need WAHA at all |
| (e) Session/status operations | Frontend → BFF → WAHA | **Unchanged** — already built and manually verified in the Session Management phase; Inbox does not need to touch this |
| (f) Real-time incoming message delivery | Not yet — see Section 3 | No existing real-time infrastructure; recommend continuing the established polling pattern short-term |

---

## 2. Mark-as-read semantics

**Facts found in code (not inference):**
- `Message` has no read/seen field. `Chat` has no read/seen field. No
  such entity appears in `docs/04-DATA-MODEL.md`'s own "Suggested
  entities" list either.
- `apps/webhooks/parsing.py`: `SUPPORTED_EVENT_TYPES = {'message'}` —
  the parser recognizes exactly one event type.
- `docs/12-WAHA-REFERENCE.md` "Observed webhook event: `message`" — **in
  this project's entire history of real, live verification against the
  actual deployed WAHA instance, only the `message` event type has ever
  been observed.** No read-receipt/`ack`/`seen`-style event has ever
  been captured or documented here.
- `docs/12-WAHA-REFERENCE.md` "Observed endpoints" lists `GET
  /api/sessions`, `GET /api/sessions/{session}`, `GET
  /api/{session}/chats`, `GET
  /api/{session}/chats/{chatId}/messages`, `POST /api/sendText` — **no
  mark-as-read/mark-as-seen REST endpoint has ever been observed or
  documented for this deployment.**

**Conclusion, stated as fact, not assumption**: this project currently
has **zero confirmed evidence**, in either direction, that WAHA
read-receipt synchronization (marking a chat "seen" on the actual phone,
or receiving a "the recipient read this" event) is available at all on
this deployment. This is not "WAHA doesn't support it" (that would be
overclaiming the negative) — it is "never observed, never tested, not
documented here."

**Recommended semantics (a product-facing choice, marked clearly as
recommendation)**: **per-chat**, not per-message. Reasoning: the
practical operator need this feature serves — "which conversations have
I already looked at in this tool" — is naturally chat-scoped, not
message-scoped; no document anywhere asks for per-message granularity
(e.g. "read up to message X," used by some chat apps for multi-device
sync), and building that would require tracking a read-position per
message per user, a materially larger data model for a requirement
nothing in this project's specs actually asks for.

**Minimum data model, if per-chat is chosen** (not created here — no
migration was made): a single nullable field on `Chat`, e.g.
`last_read_at: DateTimeField(null=True, blank=True)` — no new table
needed, comparable in shape to the already-existing `last_message_at`
field.

**Explicitly a product decision, not resolved here**: whether "mark as
read" should attempt to also sync back to WAHA/the phone at all. Given
the complete absence of confirmed WAHA read-sync capability in this
project's evidence, doing so would require new, unverified WAHA
integration work (confirming whether such an endpoint even exists on
this WAHA version, and how) before it could be implemented safely — this
audit does not recommend attempting that until it's separately
confirmed to exist, and does not decide whether it's even wanted
(read-receipt behavior can be a sensitive privacy/UX choice for the
business, independent of technical feasibility).

---

## 3. Real-time incoming messages

**Facts found in code, not assumption:**
- `backend/requirements.txt` has no `channels`, `channels-redis`,
  `daphne`, `uvicorn`, or `websockets` package — Django Channels
  (WebSocket support) is not installed.
- `backend/config/asgi.py` exists but is **the unmodified Django-default
  file** (`get_asgi_application()`, no Channels routing) — its presence
  is `django-admin startproject` boilerplate, not evidence of any actual
  ASGI/WebSocket capability being used.
- `backend/Dockerfile`'s `CMD` is `gunicorn config.wsgi:application` —
  **confirmed**: this project is actually served over **WSGI**, not
  ASGI, in its real deployment (`infrastructure/office/docker-compose.yml`
  runs the `backend` image with no command override, so the Dockerfile's
  gunicorn/WSGI command is what actually runs).
- No direct `redis.Redis(...)`/pub-sub/`publish`/`subscribe` call exists
  anywhere in `backend/apps/` or `backend/config/` (grep, `venv/`
  excluded) — Redis is used **exclusively** through Celery's broker/
  result-backend abstraction (`config/celery.py`), never as a
  general-purpose pub/sub bus.
- No frontend polyfill/library for WebSocket or SSE exists
  (`frontend/package.json` unchanged: only `lucide-react`, `react`,
  `react-dom`, `react-router-dom`).
- The two most recent frontend features in this project (Dashboard,
  Session Management) both independently arrived at the same fallback:
  periodic polling via plain `fetch`/`useApiQuery`, with Session
  Management's `runTick`/settle-detection being the most sophisticated
  example built so far.

**WebSocket vs SSE, compared against THIS project's actual architecture:**

| | WebSocket (via Django Channels) | Server-Sent Events (SSE) |
|---|---|---|
| New dependencies needed | Yes — `channels`, `channels-redis` (or similar), an ASGI server | No — a `StreamingHttpResponse` view can run under plain WSGI/gunicorn (with caveats on gunicorn worker/connection limits, noted below) |
| Serving-model change | Yes — the Dockerfile's `CMD` would need to switch from `gunicorn ...wsgi` to an ASGI server (Daphne/uvicorn), a real infrastructure change | No — no Dockerfile/serving change required |
| Auth | Cannot reuse the existing `Authorization: Bearer <JWT>` header cleanly — browsers don't let JS set custom headers on the WebSocket handshake; the token would have to move to a query string or subprotocol, a genuinely different (and slightly weaker — URLs get logged) auth transport than every other endpoint in this project uses | **Reuses the exact existing pattern** — SSE is a normal `GET` request; `EventSource` also can't set custom headers in the browser's native API (same limitation), but a same-origin-via-BFF-or-cookie workaround is more familiar and still simpler than a full Channels auth handshake; token-in-query-string is still a plausible fallback either way |
| CORS | New surface — WebSocket connections aren't governed by the existing `CorsMiddleware`/`CORS_ALLOWED_ORIGINS` config at all; Channels needs its own Origin validation | **Fully reuses the existing CORS setup** — it's an HTTP response, `corsheaders` already governs it exactly like every other Django endpoint |
| Redis reuse | The already-running Redis instance *could* back Channels' channel layer (`channels-redis`) without adding a new **infrastructure service** — but still requires new **application dependencies** and the ASGI-server change above | Doesn't need Redis pub/sub at all for a simple polling-loop-inside-a-stream implementation; could optionally use Redis later for efficiency, but isn't required to start |
| Consistency with existing project patterns | None — would be the first real-time mechanism this project has ever built | Closer in spirit to a "long-lived poll," conceptually adjacent to the polling this project already uses everywhere |

**Recommendation**: **do not adopt either WebSocket or SSE yet.**
Continue the same polling pattern already established and manually
verified twice in this project (Dashboard, Session Management) — a
periodic `GET` for new messages in the currently-open chat (and,
optionally, chat-list "last message" refresh), using the exact same
`useApiQuery`-adjacent approach already proven. This requires **zero**
new dependencies, **zero** infrastructure change, and is consistent with
every real-time-ish need this project has solved so far. **If** a truly
push-based mechanism becomes a real product requirement later, **SSE is
the smaller, lower-risk option of the two** given this project's actual
architecture (no Channels, WSGI-served, no existing pub/sub) — but
adopting it is still a separate, explicitly flagged future decision, not
recommended as part of an initial Inbox/Chat build.

**Redis reuse, direct answer**: the Redis **instance** is already
running and could technically back a pub/sub mechanism without new
*infrastructure* — but the *application* has no pub/sub code today, and
adopting either WS or SSE-with-Redis would still mean adding new
dependencies and/or new serving infrastructure. Redis being present does
not, by itself, make either option "free."

**Auth/CORS implications, direct answer**: WebSocket would require a new
auth transport (token in query string/subprotocol, not the existing
Bearer header) and new Origin-validation logic outside the existing
`corsheaders` setup. SSE would not — it reuses the existing HTTP
request/response machinery, including CORS, almost entirely as-is (the
same browser-side "can't set custom headers" limitation as WebSocket
does apply to `EventSource`, but the server-side auth/CORS handling
stays inside Django's existing, already-audited pattern rather than
needing a parallel one).

---

## 4. Chat discovery / synchronization

**Facts, confirmed by re-reading the code this task:**
- Chats are created today **exclusively** via
  `apps/webhooks/services.py::persist_message()`
  (`Chat.objects.get_or_create(...)`), called by either live webhook
  ingestion or reconciliation's own message-persist step. **A chat is
  never created except as a side effect of persisting a message for
  it.**
- `apps/sync/reconciliation.py::reconcile_session()` only iterates
  `Chat.objects.filter(session=session)` — **chats already in the
  database.** It cannot discover a chat Django has never seen a message
  for.
- `docs/12-WAHA-REFERENCE.md` confirms **`GET /api/{session}/chats` is
  an observed, working WAHA endpoint on this deployment** — WAHA *can*
  enumerate all of a session's chats. **This capability exists on the
  WAHA side; it is simply not yet wrapped by anything in
  `apps/sync/waha_client.py`, which currently only implements
  `fetch_chat_messages()`.**

**This is genuinely good news relative to the prior audit's framing**:
the missing piece is a small, well-scoped Django-side addition (one new
`WahaClient` method + a discovery step), not a WAHA-side limitation.

**Recommended minimum safe synchronization strategy** (not implemented
here):
1. Add `WahaClient.fetch_chats(session)` calling the already-observed
   `GET /api/{session}/chats`, following the exact same pattern
   (`requests.get`, `X-Api-Key` header, error handling) as
   `fetch_chat_messages()`.
2. A new, small discovery step — either as its own function or folded
   into `reconcile_session()` before the existing per-chat loop — that
   `Chat.objects.get_or_create()`s a row (no message yet, just
   `provider_chat_id`/`is_group`) for every chat WAHA reports that
   Django doesn't already have, **before** the existing message-history
   loop runs (so a newly-discovered chat immediately also gets its
   history reconciled in the same run, no separate pass needed).
3. This reuses the existing checkpoint/error-handling machinery as-is —
   no new model, no new migration, and the existing
   `unique_chat_per_session` constraint already makes the discovery step
   safely idempotent/duplicate-proof by construction.

This is a **recommendation for a future implementation step**, not
something this task built.

---

## 5. Pagination and query design

**Facts:**
- `REST_FRAMEWORK` in `backend/config/settings.py` has no
  `DEFAULT_PAGINATION_CLASS` — confirmed again this task. Every existing
  DRF view is unpaginated (fine for the Dashboard's small, bounded
  responses; not fine here).
- `Chat` already has `Index(fields=['session', 'last_message_at'])` —
  directly supports "list this session's chats, most recent first."
  `Message` already has `Index(fields=['chat', 'timestamp'])` — directly
  supports "this chat's messages, in time order." **Both needed indexes
  already exist** — no new index is required for the basic list/history
  queries.

**Recommended pagination strategy, smallest project-consistent
addition** (not applied here):
- **Chat list**: DRF's `PageNumberPagination` (or `LimitOffsetPagination`
  — either is a single, standard, well-understood DRF class, no custom
  code) as a Django-wide `DEFAULT_PAGINATION_CLASS`, or scoped to just
  the chats app's views via `pagination_class` if a project-wide default
  is judged too broad a change. Ordered by `-last_message_at`, which the
  existing index already supports.
- **Message history**: same pagination class, ordered by `-timestamp`
  (or `timestamp`, per the earlier-flagged, still-undecided
  oldest-vs-newest-first UI convention — a display choice, not a query
  one; either direction is supported by the existing `(chat, timestamp)`
  index). Given WAHA's own REST history endpoint is confirmed
  newest-first (`docs/12-WAHA-REFERENCE.md`), ordering Django's own
  message-history endpoint the same way (`-timestamp`) would keep the
  two sources visually/conceptually consistent, though this is a
  recommendation, not a requirement stated by any doc.

**No index or migration is proposed as urgent** for this specific
feature — the existing indexes already cover it. (The two *separate*,
already-known, already-reported index gaps — `Message.timestamp` alone
for the Dashboard's chat-agnostic query, and `WebhookEvent.received_at`
— are pre-existing findings from earlier reports, unrelated to Inbox's
own per-chat queries, and not revisited here.)

---

## 6. Composer/send-message integration

**Audited again this task, unchanged from the Session Management
reports**: `bff/src/routes/messages.ts`'s `POST
/sessions/:session/messages` — requires `Idempotency-Key` header,
`{chatId, text}` body, `session control`... **correction, re-verified
directly**: requires the **`sending`** scope (`requireScope('sending')`
in `messages.ts`, distinct from the lifecycle routes' `session control`
scope) — returns `{status: 'sent'|'pending'|'unknown', providerMessageId?}`
or a `409` requiring a new idempotency key for a terminal failure.

**How the future Inbox composer should call it** (recommendation, not
implemented): exactly as `SessionsPage.tsx` already calls other BFF
endpoints — a typed client function in `frontend/src/lib/bffApi.ts`
(e.g. `sendMessage(session, chatId, text, idempotencyKey)`), generating
a fresh idempotency key per user-initiated send attempt (e.g.
`crypto.randomUUID()`, already available in the browser, no new
dependency), using `authHeader()` exactly like every existing client
function.

**Missing contract for replying inside a selected chat**: none found to
be missing — `chatId` is already exactly what identifies which
conversation to send into (`Chat.provider_chat_id`, the same identifier
Django's own chat rows already store), so the existing endpoint's
contract already supports "reply in this chat" with no change. The only
integration work is **frontend-side wiring**, not a BFF contract gap.

**Not modified**: this task did not touch `bff/src/routes/messages.ts` or
any part of the send-message flow.

---

## 7. Security/authentication

**Audited (re-read, not assumed) this task:**

| Layer | Mechanism | Scope model |
|---|---|---|
| Django (Dashboard endpoints, precedent for chat reads) | `apps.authn.authentication.JWTAuthentication` + `IsAuthenticated` | No scope check — any authenticated user |
| BFF (session lifecycle) | `requireAuth` + `requireScope('session control')` | Scope-gated |
| BFF (send message) | `requireAuth` + `requireScope('sending')` | Scope-gated |
| BFF (session status, read) | `requireAuth` + `requireScope('reading')` | Scope-gated |

`JWT_SCOPES` (`backend/config/settings.py`) already defines `reading`
and `sending` — both directly reusable, already-existing scope names,
not new ones that would need inventing.

**Recommended minimum permissions for Inbox** (recommendation, not
applied):
- **Read** (chat list, message history): `IsAuthenticated`, matching the
  Dashboard's existing posture — **or**, if the project wants to start
  gating message *content* more tightly than aggregate dashboard numbers
  (a real, reasonable distinction — see the prior audit's Section 8),
  requiring the JWT's `reading` scope specifically (mirroring the BFF's
  own status-read gate) rather than bare authentication. **This choice
  is explicitly a product decision** (Section 10/"USER DECISIONS
  REQUIRED") — this project has no existing precedent for a Django
  endpoint checking JWT scopes (only the BFF does today), so either
  choice would be a genuine, deliberate step, not a default to fall
  back on silently.
- **Send**: already gated by the BFF's `sending` scope — no change
  needed.
- **Mark as read**: recommend the same scope as read access (whichever
  is chosen above) — marking something read is a read-adjacent action,
  not a distinct privilege tier; no document suggests otherwise.

**No auth code was changed.**

---

## 8. Data reality

**Current dev database counts** (read-only query, this task):

| Table | Count |
|---|---|
| `Chat` | 1 |
| `Message` | 0 |
| `Contact` | 0 |
| `MediaReference` | 0 |
| `WebhookEvent` | 0 |

**The single existing `Chat` row** (`provider_chat_id =
168160971997355@lid`, `created_at = 2026-09-23 11:56:01`) has **zero**
associated messages, and its creation predates every webhook-ingestion
event currently in the database (`WebhookEvent` count is 0 — meaning
whatever created this row did not go through the normal
webhook-ingestion path that would also have created a `Message`
alongside it, since `persist_message()` always creates both together).
Its timestamp aligns with this project's earlier Phase 3/4 live-
verification work against the real WAHA instance
(`docs/generated/PHASE-3-LIVE-VERIFICATION.md`/`PHASE-4-RECONCILIATION.md`
era) — most plausibly a leftover artifact from that manual testing, not
a row created by the code paths that exist today. This is an honest
observation, not a firm causal claim — this task did not dig further
into exactly how it was created, since doing so wouldn't change any
recommendation here.

**What can actually be tested with current data**: essentially only the
**empty-state** and **single-chat-with-no-messages** UI paths. A chat
list with one real entry could render; a message thread would always
show zero messages regardless of which chat is opened. **No positive-
path test of real message history, unread badges (once built), or
composer-reply-in-context is currently possible without either (a) live
WhatsApp traffic flowing through the real webhook while this session's
number is connected, or (b) running reconciliation against a chat that
actually has WAHA-side history** (the earlier Session Management reports
already established that `no_epahari` is the one real, currently-
connected session — reconciling *that* session's already-known chat(s)
would be the realistic way to get real test data, though this task did
not run reconciliation, per its read-only scope).

**No test data was fabricated. No database write occurred.**

---

## 9. Implementation dependency graph

Adapted to this repository's actual state (not a generic template):

```
contract decision (Section 1 — Frontend→Django for reads)
        │
        ▼
DRF pagination config (Section 5) ──────────┐
        │                                    │
        ▼                                    │
apps.chats read API (list + message history) │
  (serializers/views/urls, reuses            │
  JWTAuthentication — Section 7 decides      │
  scope requirement)                         │
        │                                    │
        ├──────────────► chat discovery (Section 4 —
        │                 independent, can land before
        │                 or after the read API; only
        │                 needs the WahaClient addition)
        ▼
frontend djangoApi.ts client functions
        │
        ▼
Inbox UI: chat-list pane + conversation pane
  (reuses Card/LoadingState/ErrorState/EmptyState —
  no new list/pagination component exists yet, per the
  prior audit's Section 4 finding — this is new frontend
  component work, not just wiring)
        │
        ├──────────────► composer, wired to the EXISTING,
        │                 unmodified BFF sendText
        │                 (Section 6 — independent, no
        │                 backend/BFF work, can land in
        │                 parallel with the read side)
        │
        ├──────────────► mark-as-read (Section 2 — needs
        │                 its own small migration + a
        │                 product decision first;
        │                 independent of chat discovery
        │                 and real-time)
        │
        └──────────────► real-time delivery (Section 3 —
                          explicitly deferred; polling
                          fallback needs no new work
                          beyond what the read API already
                          provides — just an interval timer
                          on the frontend, same pattern as
                          Dashboard/Sessions)
```

Contact-info pane (nice-to-have, prior audit) and search/filter (blocked
on product decision, prior audit) are not shown above — both are
independent leaves off the "Inbox UI" node, addable at any point once
the core read/send path exists.

---

## 10. Final decision table

| Decision | Recommended choice | Evidence | Why | Implementation impact | Requires user/product decision? |
|---|---|---|---|---|---|
| Chat list / message history request path | Frontend → Django direct | `00-MASTER-SPEC.md` ownership; Dashboard precedent (`/api/dashboard/*`) | Durable data Django already owns; no live WAHA call needed; avoids a redundant BFF hop | New `apps.chats` views/urls/serializers; `07-API-CONTRACT.md` line becomes stale | **YES** — confirm the recommendation |
| Send message request path | Frontend → BFF → WAHA (unchanged) | Already built, tested, live-verified for auth/routing | It's a live WAHA action; `docs/CLAUDE.md` rule 4 requires this path | None — reuse as-is | No — already established, not in question |
| Mark-as-read granularity | Per-chat | No doc asks for per-message; simplest model that serves the stated need | Smaller data model, one nullable field | One new `Chat` field (migration, not created here) | **YES** — confirm granularity and whether WAHA-sync is even wanted |
| Mark-as-read request path | Frontend → Django | No confirmed WAHA read-sync capability exists in this project's evidence | Avoids building on an unverified WAHA capability | Small Django endpoint, reuses the chosen read-auth pattern | **YES** — tied to the above |
| Real-time delivery mechanism | Keep polling (defer WS/SSE) | No Channels, WSGI-served (`Dockerfile` `CMD`), no pub/sub code anywhere | Zero new dependencies/infra; consistent with every existing real-time-ish feature in this project | None now; SSE flagged as the lower-risk future option if push delivery is later required | **YES** — confirm deferring is acceptable, or pick WS/SSE now |
| Chat discovery | Add `WahaClient.fetch_chats()` + a discovery step in/near reconciliation | `GET /api/{session}/chats` already observed working on this deployment | Closes the "reconciliation only knows already-known chats" gap with a small, contained addition | New client method + small reconciliation change; no schema change | No — evidence-supported, low-risk; flagged only for scheduling, not for a product call |
| Pagination mechanism | DRF `PageNumberPagination`/`LimitOffsetPagination`, added as `DEFAULT_PAGINATION_CLASS` or per-view | Standard DRF, matches "pagination" already named as a contract principle (`07-API-CONTRACT.md`) | Smallest addition that satisfies an already-stated requirement | One settings change + `pagination_class` on new views | No — mechanical choice, not a product question |
| Read-endpoint auth scope | `IsAuthenticated` only, OR require `reading` scope | No precedent either way for Django (only the BFF scope-gates today) | Message content may deserve tighter gating than aggregate dashboard numbers, but no doc mandates it | If scoped: small addition to the new views' `permission_classes` | **YES** — genuine open choice, no existing precedent to defer to |

---

## USER DECISIONS REQUIRED

Only the items that genuinely cannot be determined from existing code or
specification:

1. **Confirm (or reject) Frontend → Django direct as the read path** for
   chat list and message history, superseding `07-API-CONTRACT.md`'s
   literal "Frontend -> BFF" example line for this specific case.
2. **Mark-as-read**: confirm per-chat granularity is sufficient, and
   decide whether it should ever attempt to sync back to WAHA/the phone
   at all (a privacy/UX choice, independent of and prior to any
   technical feasibility check).
3. **Real-time delivery**: confirm that continuing to poll (no
   WebSocket/SSE yet) is acceptable for the first Inbox implementation,
   or explicitly choose to invest in SSE/WebSocket infrastructure now
   instead.
4. **Read-endpoint authorization**: decide whether the new Django chat/
   message endpoints should require bare authentication (matching the
   Dashboard) or the JWT's `reading` scope specifically (matching the
   BFF's own tighter posture for live data) — there is no existing
   Django precedent either way to defer to.

Everything else in this report (pagination mechanism, chat-discovery
approach, composer integration, index sufficiency) is evidence-supported
enough to proceed without further input once the four items above are
answered.

---

This was a read-only decision-preparation pass. No implementation was
performed. Not proceeding to Inbox/Chat implementation or canonical
Phase 9 automatically.
