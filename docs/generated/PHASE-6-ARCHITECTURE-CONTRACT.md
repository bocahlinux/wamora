# Phase 6 — Architecture Decision & API Contract Lock

Architecture/contract resolution only. No application code, models,
migrations, frontend, BFF implementation, or `docker-compose.yml` was
modified. No WAHA call of any kind was made this round (this task's own
instructions said not to rediscover lifecycle endpoints by probing the
live session — none was probed). `test_session` was never started, stopped,
restarted, logged out, or deleted. No credential, key, password, or
environment value is printed anywhere below. Phase 6 is not implemented
by this document. Phase 7 is not started.

## 0. Two things flagged before the substantive sections

### 0.1 Document-name mismatches in this task's own file list

This task's instructions named `docs/07-BFF.md`, `docs/08-FRONTEND.md`,
`docs/09-INBOX.md`, `docs/10-OFFLINE.md`, and `docs/15-coding-phases.md`.
None of these exist. The actual `docs/` directory contains
`07-API-CONTRACT.md`, `08-DEPLOYMENT.md`, `09-TEST-PLAN.md`,
`10-CLAUDE-CODING-GUIDE.md`, and `15-CODING-PHASES.md` (capitalized).
This is the same kind of mismatch flagged in prior Phase 6 rounds — all
five files that actually exist were read and used for this document; no
content was invented to fill in for the named-but-nonexistent files.

### 0.2 A real scope question this task's own evidence raised

`docs/15-CODING-PHASES.md` lists **"6. BFF"**, **"8. Inbox/chat"**, and
**"10. Session management"** as three *separate* phases. Nothing in this
document decides whether session-lifecycle/QR routes and chat/message
routes "belong to" Phase 6 versus Phases 8/10 — that's a project-scoping
question, not an architecture question, and this task didn't ask for it
to be resolved. **What this document does do**: define the concrete API
contract for these capabilities now (as instructed), on the reasoning
that Phase 6's job is to establish the BFF's foundational
shape (auth verification, the allowlist mechanism, WAHA connectivity,
error/availability contract) that Phases 8/10 would then build specific
routes on top of — whichever phase's code actually ships a given route,
the contract decided here should still apply. **Flagged as an open
scoping question for confirmation, not decided here.**

---

# 1. BFF → WAHA authentication / key scope

### Evidence gathered this round, not previously surfaced

`docs/00-MASTER-SPEC.md`: *"Awal: 1 session, kemungkinan maksimal 2–3"*
("Initially 1 session, possibly max 2-3") and `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`
"Final" #2: *"Initial session: 1; expected max 2–3."* — **this is a
Final (not Open) project decision**, and it directly changes the
cost/benefit of session-scoped keys versus what
`docs/generated/PHASE-6-WAHA-LIFECYCLE-API-CONTRACT.md` Section 8
estimated (that document didn't find this line and reasoned from "no
documented multi-session requirement" — a weaker, "grep found nothing"
basis). With a documented, capped 2–3 sessions, provisioning one
session-scoped key per session is trivial, not a scaling concern.

### Options evaluated (per this task's own A/B/C/D framing)

- **A — reuse the existing global `WAHA_API_KEY`**: **REJECTED.** This is
  the same key Django already uses for reconciliation
  (`docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` Section 9's
  diagram already shows separate BFF/Django credentials as the intended
  design). Sharing one key across two independently-deployed processes
  on two different trust zones (Tencent vs. Office) means a compromise
  of either one has the same blast radius as compromising the other, and
  neither can be rotated independently without affecting both. Also:
  this is the exact type of key that was subject to the credential
  exposure incident in `docs/generated/PHASE-6-WAHA-LIFECYCLE-VERIFICATION.md`
  Section 3 — reusing an admin-equivalent key for a new component is a
  reason for more caution here, not less.
- **B — a dedicated (but still full/admin) WAHA API key for the BFF,
  separate from Django's**: better than A (independent rotation,
  independent blast radius from Django's key) but still fails this
  task's own stated requirement — *"The BFF must NOT receive unnecessary
  server/admin capabilities such as environment inspection, server
  administration, [or] destructive session deletion"* — a full/admin key
  can do all of those things by definition.
- **C — a session-scoped WAHA API key**: confirmed **actually
  documented and supported** by the official WAHA security
  documentation (fetched in the prior round;
  `docs/generated/PHASE-6-WAHA-LIFECYCLE-API-CONTRACT.md` Section 8) —
  minted via `POST /api/keys` with `isAdmin: false`, `session:
  "<name>"`, and a per-action `actions` object (`read`, `send`,
  `control`, `setting`, `app`, `delete`). This is not this project
  inventing a scoping scheme; it's WAHA's own documented mechanism.
- **D — another mechanism**: none found in the fetched documentation
  beyond A/B/C.

### Final decision

**C — one session-scoped WAHA API key per session, minted for the BFF**,
with `actions: {read: true, send: true, control: true, setting: false,
app: false, delete: false}`.

- **Least privilege**: covers exactly what Section 2's route contract
  below needs (`read` for status, `send` for messages, `control` for
  start/stop/restart/QR/pairing-code) and nothing else. `delete` is
  explicitly `false` — see Section 8. `setting`/`app` are `false` — no
  BFF responsibility in any standing document touches session
  configuration or WAHA "apps." A session-scoped key also has no access
  to the Keys API itself (minting/revoking other keys) or to
  admin/global endpoints — a **direct, structural mitigation** for the
  exact class of incident in the prior verification report (an ordinary
  key reaching `/api/server/environment`), though this document
  reiterates, as the prior one did, that this specific claim is a
  reasonable inference from the documented admin/session-key
  distinction, not independently live-tested this round (doing so would
  require minting a real key, which this documentation-only task does
  not do).
- **Number of sessions**: capped at 2–3 by a Final project decision
  (above) — provisioning cost is bounded and small, removing the one
  real objection a session-scoped-key design would otherwise have at
  larger scale.
- **Operational cost**: one key per session, minted once using the
  existing admin key, stored as the BFF's WAHA credential — the same
  *kind* of one-time provisioning step this project already performs for
  the webhook HMAC secret.

**This is recorded as the final decision**, not left open, because the
evidence for it is now strong on every axis this task asked to evaluate.
The one residual, explicitly-flagged uncertainty: whether the *specific
deployed* WAHA version (`2026.9.1`) actually has the Keys API reachable
and behaving as documented — not live-verified this round, and not
required to be, since this document does not implement anything. If the
Keys API turns out to be unavailable on this deployment when Phase 6
implementation begins, **Option B (dedicated, non-scoped key) is the
documented fallback**, not Option A.

**No credential was minted, changed, or viewed in the process of writing
this section.**

---

# 2. Final BFF route contract

### A repository-grounded correction to this task's own framing, made explicit rather than silently applied

This task's own prompt asked to "define" `GET chats` / `GET chat
detail` / `GET messages/history` **as BFF endpoints**. Per this task's
own instruction to verify architecture claims against the repository
rather than accept them blindly (stated explicitly for Section 5, and
applied here too since the evidence is just as direct): **chats and
message history are already a decided, not-through-the-BFF concern.**
`docs/generated/PHASE-6-BLOCKER-RESOLUTION.md`'s "Blocker 2" resolution
states plainly: *"list chats" and "get message history" should be served
from Django's own durable Chat/Message tables, not proxied live from
WAHA* — because WAHA's live chat-list cannot be reliably matched to
Django's already-accumulated `Chat` rows (the LID/`@c.us` fragmentation
problem), and because durable reads must keep working during a WAHA
outage per the Availability requirement. This is independently
corroborated by `docs/00-MASTER-SPEC.md`'s own "Ownership" section,
found this round: *"WAHA: live WhatsApp/session state. PostgreSQL:
durable ... chats/messages ..."* — an explicit, direct statement that
chats/messages are PostgreSQL/Django's owned data, not WAHA-live data.
`docs/07-API-CONTRACT.md` already has a "Frontend → Django" section
listing "durable conversation views" for exactly this reason.

**Conclusion: chat list and message history are Django/DRF endpoints
(Frontend → Django directly), not BFF endpoints.** They are documented
below for completeness (since this task asked for them), explicitly
marked as **not part of the BFF's contract**, so a reader doesn't
mistake their presence here for a reversal of the already-decided
source-of-truth.

### Session (BFF-owned — WAHA is the source of truth for this data, per `00-MASTER-SPEC.md` "Ownership")

| Method | Path | Auth | Authz scope | Request | Response (success) | Response (error) | Upstream | Durable-data or live? | Works if Django down? | Idempotent? |
|---|---|---|---|---|---|---|---|---|---|---|
| GET | `/api/sessions/:session/status` | JWT | `reading` | none | `200` `{session, status, engine, me}` (subset of WAHA's session object) | `401`/`403`/`404`/upstream-error shape | `GET /api/sessions/{session}` | Live (WAHA) | **Yes** | N/A (read) |
| POST | `/api/sessions/:session/start` | JWT | `session control` | none | `200` `{success, session, requestedAction: "start"}` — see Section 7, no status claimed | same pattern | `POST /api/sessions/{session}/start` | Live (WAHA) | **Yes** (WAHA call); audit write degrades — see Section 9 | Yes — WAHA's own `start` is documented idempotent |
| POST | `/api/sessions/:session/stop` | JWT | `session control` | none | `200` `{success, session, requestedAction: "stop"}` | same pattern | `POST /api/sessions/{session}/stop` | Live (WAHA) | **Yes**; audit degrades | Yes — documented idempotent |
| POST | `/api/sessions/:session/restart` | JWT | `session control` | none | `200` `{success, session, requestedAction: "restart"}` | same pattern | `POST /api/sessions/{session}/restart` | Live (WAHA) | **Yes**; audit degrades | Not documented idempotent (restart always stops+starts if not already stopped) — repeated calls have a real effect each time |
| GET | `/api/sessions/:session/qr` | JWT | `session control` | none | `200` — QR proxied as-is (Section 6); never logged | `401`/`403`/`404`; `409` if not in `SCAN_QR_CODE` (proposed, WAHA-unconfirmed) | `GET /api/{session}/auth/qr` | Live (WAHA) | **Yes**; audit-of-the-request degrades | N/A (read, but time-sensitive — 60s/20s expiry) |
| POST | `/api/sessions/:session/pairing-code` | JWT | `session control` | `{"phoneNumber": "..."}` | `200` — code proxied; never logged | same pattern | `POST /api/{session}/auth/request-code` | Live (WAHA) | **Yes**; audit degrades | Not established by documentation |

**Not exposed** (`logout`, `delete`, `create`, `update`) — see Section 8
for the evidenced rationale per operation.

### Chats / Messages — **not BFF endpoints** (documented here for completeness only)

| Capability | Owner | Rationale |
|---|---|---|
| List chats | Django/DRF, direct (`Frontend → Django`) | Source-of-truth decision above; requires Django, degrades (labelled, not hidden) during an Office outage per `docs/03-UI-UX-SPEC.md`'s "label data as live/cached/stale/unavailable" |
| Chat detail | Django/DRF, direct | Same reasoning |
| Message history | Django/DRF, direct | Same reasoning |

### Send message (BFF-owned — the one message-related action that must reach WAHA live, since the frontend never calls WAHA directly)

| Method | Path | Auth | Authz scope | Request | Response (success) | Response (error) | Upstream | Works if Django down? | Idempotent? |
|---|---|---|---|---|---|---|---|---|---|
| POST | `/api/sessions/:session/messages` | JWT | `sending` | header `Idempotency-Key: <key>`; body `{chatId, text}` | `200` `{status: "sent"\|"pending"\|"unknown", providerMessageId?}` | `401`/`403`/`400` invalid body; `409` if the same key already resolved to `failed` (requires a new key — see Section 3) | `POST /api/sendText` | **Degraded, not fully unavailable** — see Section 3/9: the WAHA send itself still works; idempotency-key *registration* is best-effort and silently weaker without Django | **Yes**, via `OutboundOperation` (Section 3) — the entire reason this table's other rows don't need their own idempotency column |

### Health/readiness (BFF-owned — required, not optional, per the already-decided degraded-mode contract)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` (already exists as a skeleton stub) | none (operational endpoint) | Extend the existing stub to report `{status: "ok", waha: {reachable: bool}}` — satisfies `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` Section 7's requirement that "error responses must identify *which* upstream failed," which the current bare `{status: "ok", service: "bff"}` stub does not |

---

# 3. Outbound message idempotency — exact flow

### The flow, resolved end to end

1. **Frontend → BFF**: `POST /api/sessions/:session/messages`, header
   `Idempotency-Key: abc123`, body `{chatId, text}`.
2. **BFF authenticates/authorizes** the JWT (`sending` scope required).
3. **BFF → Django, synchronously, bounded timeout (proposed, e.g.
   ~2-3s — not specified by any doc, flagged OPEN)**: register the
   operation — `OutboundOperation.objects.get_or_create(session=session,
   idempotency_key=key, defaults={destination: chatId, operation_type:
   'sendText', status: PENDING})`.
   - **Existing row found, status `PENDING` or `SENT`**: this is a
     retry of an already-in-flight or already-resolved send. **The BFF
     must not call WAHA.** Return the existing row's current state to
     the frontend.
   - **Existing row found, status `FAILED` or `UNKNOWN`**: **do not
     auto-retry.** A `FAILED`/`UNKNOWN` outcome was already recorded (or
     is ambiguous); silently reusing the same key to try again risks
     exactly the double-send this mechanism exists to prevent, since a
     prior attempt's real-world effect on WhatsApp isn't fully known.
     Return the existing state; **a genuinely new attempt requires a new
     idempotency key**, which is a deliberate, visible user/frontend
     action, not something the BFF decides silently. **This is a
     proposed policy, not WAHA-mandated — flagged for confirmation.**
   - **No existing row (new key) — proceed.**
   - **Django unreachable (timeout)**: per the narrow exception already
     accepted in `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md`
     Section 2 and confirmed in `docs/generated/PHASE-6-BLOCKER-RESOLUTION.md`,
     **the BFF proceeds to WAHA anyway.** This is a real, accepted risk
     window, not an oversight: real-time duplicate-send prevention is
     itself a feature that depends on Office persistence, and
     `docs/00-MASTER-SPEC.md`'s own Availability wording says exactly
     this class of feature "becomes degraded" during an outage — it does
     not promise universal duplicate protection regardless of Office
     state.
4. **BFF → WAHA**: `POST /api/sendText`.
5. **WAHA responds** — success (with some message identifier, exact
   field name not confirmed — see `docs/generated/PHASE-6-BLOCKER-RESOLUTION.md`,
   probing was stopped before reaching a real success response) or an
   error, or the BFF's own call to WAHA times out.
6. **BFF → Django, synchronously, best-effort**: resolve the same
   `OutboundOperation` row (identified by `session` + `idempotency_key`,
   which the BFF already holds from step 1 — **this is the exact
   correlation mechanism**, see below):
   - WAHA returned success → `status = SENT`, `provider_message_id =
     <id>`.
   - WAHA returned a clean error (e.g. `400`) → `status = FAILED`.
   - **The BFF's own call to WAHA itself was inconclusive** (timeout,
     connection reset — WAHA may or may not have processed it) →
     `status = UNKNOWN`. This is precisely what `STATUS_UNKNOWN` was
     built for.
7. **BFF returns the final (or best-known) state to the frontend.**

### Answering the specific correlation question directly

*"How does the system correlate the resulting WAHA message with the
`OutboundOperation`?"* — **Not via any WAHA-side field** (Blocker 1's
probing found no client-correlatable ID WAHA echoes back — this remains
true and is not re-invented here). **The correlation is done by the BFF
itself**, which is the one component present for both step 3
(`idempotency_key` → row identity) and step 5 (WAHA's real response) in
the same request lifecycle. This **resolves the specific "required
product decision" left open in `docs/generated/PHASE-6-BLOCKER-RESOLUTION.md`
item 1** — no heuristic/approximate matching rule (e.g. "oldest PENDING
row for the same destination") is needed at all for the synchronous
happy path, because the BFF never loses track of *which* row it
registered.

**A necessary corresponding implementation requirement, named but not
built here** (out of this task's scope — "Do NOT modify application
code"): `persist_message` (`apps/webhooks/services.py`) still does not
look up or update `OutboundOperation` rows. This document's design does
not depend on that changing for the synchronous flow above — but see the
failure scenarios below for where it would still help, or where it can't
help at all.

### Failure scenarios, answered individually

- **BFF crashes after registering (step 3) but before calling WAHA (step
  4)**: the `OutboundOperation` row is stuck `PENDING` with WAHA never
  actually called. A retry with the same key hits step 3's "existing
  `PENDING`" branch and — per the policy above — **does not
  auto-retry**. This means a row that's genuinely stuck (WAHA was never
  called) looks identical, from the BFF's perspective, to one where WAHA
  *was* called and the crash happened afterward. **This document does
  not invent a staleness-timeout auto-retry policy** (e.g. "treat
  `PENDING` older than N seconds as safe to retry") — that would itself
  be exactly the kind of unapproved heuristic this project has
  repeatedly refused to add. **Flagged OPEN**: resolving a
  long-stuck-`PENDING` row requires either an operator/reconciliation
  process (not designed here) or a future, explicitly-approved staleness
  rule.
- **WAHA accepts the message but the BFF times out waiting for the
  response**: this is exactly the `UNKNOWN` case in step 6 — the safe,
  conservative outcome, matching `docs/09-TEST-PLAN.md`'s own Failure
  test #8 ("Ambiguous outbound result does not cause duplicate send").
  Resolving an `UNKNOWN` row later requires the same not-yet-approved
  correlation rule as the stuck-`PENDING` case — not solved by this
  document, consistent with Blocker 1's original finding.
- **The frontend retries the same `Idempotency-Key`**: this is the core
  case the mechanism exists for — handled cleanly by step 3's
  `get_or_create`, no ambiguity.
- **A webhook arrives before the WAHA REST response returns** (a
  theoretical race, not observed): even in this order, `persist_message`
  (even if extended to attempt `OutboundOperation` resolution) has no
  reliable way to know *which* `idempotency_key` a given inbound webhook
  message corresponds to, for the same reason as above — WAHA doesn't
  echo a client-supplied ID. **This race does not change the
  conclusion**: it's subsumed by the same unresolved correlation-rule
  gap, not a new problem.
- **The same message is later observed via reconciliation**: `Message`
  persistence itself already works correctly and independently
  (`docs/generated/PHASE-6-BLOCKER-RESOLUTION.md`'s "Inbox consistency
  cross-check": "Reconciliation compatibility: Yes"). `OutboundOperation`
  *status* resolution specifically would benefit from the same future
  `persist_message` extension named above, bounded by the same
  correlation-rule gap.

### Exactly-once — stated honestly, per this task's explicit request

**What is achieved, deterministically**: duplicate *dispatch* prevention
— the same `idempotency_key` can never cause a second `POST /api/sendText`
call, as long as Django was reachable at registration time (step 3).
This is the part that actually matters most (never double-message a real
WhatsApp contact) and it is fully solved by existing, unmodified
infrastructure (`OutboundOperation`'s unique constraint).

**What is not fully exactly-once**: automatic *status resolution* for
`PENDING`/`UNKNOWN` rows in the crash/timeout edge cases above. This is
an external constraint (WAHA's confirmed lack of a client-correlatable
send ID — `docs/generated/PHASE-6-BLOCKER-RESOLUTION.md`), not a gap in
this project's own design, and is recorded as a known, accepted
limitation rather than solved by inventing an unapproved heuristic.

---

# 4. Chat identity and source of truth

**Confirm or reject A/B/C, using repository evidence, as instructed:**
**B — Django durable `Chat`/`Message` records are the source of truth
for the inbox — already decided**, not newly decided by this document.
Evidence:

1. `docs/generated/PHASE-6-BLOCKER-RESOLUTION.md` ("Blocker 2"): *"list
   chats" and "get message history" should be served from Django's own
   durable Chat/Message tables, not proxied live from WAHA"* — reached
   because WAHA's live chat-list cannot be reliably matched to Django's
   accumulated `Chat` rows (the confirmed LID/`@c.us` fragmentation), and
   because Availability requires durable reads to survive a WAHA outage.
2. `docs/00-MASTER-SPEC.md` "Ownership" (found this round, corroborating
   independently): *"PostgreSQL: durable ... chats/messages ..."* —
   direct evidence chats/messages are Django-owned data.
3. `docs/07-API-CONTRACT.md`'s existing "Frontend → Django" section
   already lists "durable conversation views" separately from
   "Frontend → BFF."

**No merge of `000000000000000@lid` and the `@c.us` identifier is
proposed, confirmed, or implied anywhere in this document** — both
remain distinct `provider_chat_id` values, exactly as the standing
Phase 2.5 rule requires.

### Answering the specific sub-questions

- **How do chat records become visible in the inbox?** Via whatever
  already creates them today: `persist_message`
  (`apps/webhooks/services.py`), called from webhook ingestion (Phase 3)
  and reconciliation (Phase 4/5) — `Chat.objects.get_or_create(session,
  provider_chat_id=...)`. No new mechanism is introduced.
- **How are new WAHA chat-list entries ingested?** Not by the BFF at
  all, and not by any new "chat-list sync" job this document proposes —
  a chat only becomes known to Django when a `Message` for it is
  actually persisted (via webhook or reconciliation). This is the
  existing, unmodified behavior; this document does not add a separate
  chat-list-polling ingestion path, since none is evidenced as required.
- **Is the BFF allowed to create `Chat` records?** **No.** Confirmed by
  reading `apps/webhooks/services.py` directly this round:
  `persist_message` is the **only** code path anywhere in this
  repository that creates a `Chat` row, and it's Django-side, invoked
  only from webhook ingestion and reconciliation. The BFF has no
  database access at all (an already-standing architectural rule) and
  this document does not propose changing that.
- **May only webhook/reconciliation code create them?** **Yes**, per the
  above — this is already how the codebase behaves today, not a new
  restriction being introduced.
- **What happens when the WAHA chat list contains an identifier not yet
  known to Django?** Per decision B above, the BFF doesn't serve the
  WAHA chat list at all, so this scenario doesn't arise through the BFF.
  If a Django-side "chat list" endpoint (Phase 8, out of this document's
  scope) ever separately queried WAHA's live chat list for comparison,
  an unknown identifier would simply not yet have a `Chat` row — visible
  in the inbox only once a `Message` for it is actually persisted. Not
  designed further here, since it's a Phase 8 (Inbox/chat) concern, not
  Phase 6 (BFF).

---

# 5. Audit actor identity

### The task's proposed sequence, checked against the repository — and revised

This task proposed: *BFF → Django records the audit event → BFF → WAHA
performs the action* (audit-before-action). **Checked against the actual
`AuditLog` model** (`apps/audit/models.py`) **and found not to fit**:
`result` is a required `CharField` with only two choices,
`RESULT_SUCCESS`/`RESULT_FAILURE` (no "attempted"/"pending" value) — the
model has no way to record an audit entry before the outcome is known
without either inventing a schema-breaking placeholder value or adding a
third status choice, and this task explicitly forbids schema
changes/migrations this round.

**Revised, repository-consistent sequence: audit is written *after* the
WAHA call resolves, not before.**

1. Frontend → BFF (authenticated).
2. BFF performs the authorized action against WAHA (Section 2's
   lifecycle/send endpoints).
3. WAHA responds (success or failure — including the `UNKNOWN` case for
   lifecycle calls, mirrored from Section 3's send design if a similar
   ambiguous-timeout situation occurs).
4. **BFF → Django, synchronously, best-effort, bounded timeout**: write
   one `AuditLog` row with the now-known final `{actor, action, target,
   result}`.
5. BFF returns the WAHA result to the frontend, **regardless of whether
   step 4 succeeded** — an audit-write failure must never block a
   user-facing operation that already happened.

For the **send-message** endpoint specifically, this can be the *same*
Django call that resolves the `OutboundOperation` row (Section 3, step
6) — Django can write both the `OutboundOperation` update and the
`AuditLog` row in one transaction, server-side, avoiding a second
BFF→Django round trip. For lifecycle actions (no `OutboundOperation`
involved), a dedicated, narrow endpoint is needed — proposed:
`POST /internal/audit-events` (Django-side, authenticated by a separate
BFF↔Django service credential, not the end user's JWT, since this is a
server-to-server call), body `{actor_id, action, target, result}`.

### Answering the specific consistency questions

- **Django audit write succeeds but WAHA call fails**: **cannot happen in
  this design** — audit is written *after* WAHA's outcome is known, so
  the recorded `result` is always the true, final one. This eliminates
  the race the task's original ordering would have created.
- **WAHA succeeds but the audit write fails** (Django unreachable/error
  at step 4): the user-visible action already happened; no `AuditLog`
  row exists for it. **A real, accepted gap** — this document proposes
  the BFF also emit a structured local log line for every sensitive
  action (actor, action, target, result, timestamp) as a fallback
  operational trail independent of Django's availability, so the event
  isn't *entirely* unrecoverable even without a database row. This does
  not satisfy `docs/06-SECURITY.md`'s durable-audit requirement by
  itself, but bounds the blast radius of the gap to "Office was down at
  that exact moment," a narrower and more honest claim than pretending
  the gap doesn't exist.
- **BFF crashes between WAHA's response and the audit write**: identical
  to the above — same proposed mitigation, same honest limitation.

### Explicit statement of the consistency model (as instructed, no transactional guarantee claimed)

**There is no cross-system transaction between WAHA and Django.** WAHA's
own execution is the sole source of truth for whether an action actually
happened. Django's `AuditLog` is a best-effort, usually-reliable but not
guaranteed record of it. A missing audit row does not mean the action
didn't happen; it means the action's record-keeping degraded, which per
`docs/00-MASTER-SPEC.md`'s Availability section is an accepted,
documented category of degradation during an Office outage, not a
silent violation of a promise this project never made.

**Known limitation, not fixed here**: `AuditLog` has no request/
correlation-ID field (its own docstring deliberately limits it to
exactly five fields). Correlating a specific audit row back to a
specific frontend request, if ever needed, would require embedding an ID
in `target` as a compound string, or a future schema change — flagged,
not solved, consistent with "Do NOT modify database schema."

---

# 6. QR / pairing response contract

**Documented WAHA behavior** (from
`docs/generated/PHASE-6-WAHA-LIFECYCLE-API-CONTRACT.md` Section 6,
restated for this document's completeness): `GET /api/{session}/auth/qr`
returns a QR code in one of several formats (image/base64/raw per query
parameter — exact parameter name not captured by the fetched
documentation this round); first code expires in 60s, each subsequent in
20s, up to 6 total; only meaningful while the session is in or moving
toward `SCAN_QR_CODE`. `POST /api/{session}/auth/request-code` is the
phone-number-based alternative, documented to exist, with no further
field-level detail captured.

**Project-level BFF contract, kept deliberately narrow given the
undocumented specifics above**:

```
GET /api/sessions/:session/qr
  -> 200 { session, format, data, expiresInSeconds }
     - format/data proxy whatever WAHA returned, as-is (Section 2 of
       the prior contract document already decided against BFF-side
       QR interpretation)
     - expiresInSeconds: only included if the BFF can derive it from
       WAHA's own response; otherwise omitted rather than guessed
  -> 409 if WAHA/the session is not in a pairable state (proposed,
     WAHA-unconfirmed status code)
```

```
POST /api/sessions/:session/pairing-code
  body: { phoneNumber }
  -> 200 { session, code }
  -> 400 if phoneNumber is missing/malformed (BFF-side validation,
     not WAHA-confirmed)
```

**Distinction upheld explicitly, as instructed**: everything above
labeled "documented WAHA behavior" comes from the official docs fetched
in the prior round; everything under "project-level BFF contract" is
this project's own proposed shape, not something WAHA itself returns
verbatim — the two are not the same thing and this document does not
conflate them.

---

# 7. Lifecycle response contracts

WAHA's own response bodies for `start`/`stop`/`restart`/`logout`/`delete`
are **not shown** by the fetched documentation (confirmed absent in
`docs/generated/PHASE-6-WAHA-LIFECYCLE-API-CONTRACT.md` Section 5 — only
the `create` endpoint's response was shown). **This document does not
invent an exact upstream response body.**

**Decision: normalize to a project-owned shape that does not claim an
unconfirmed state transition**, per this task's own explicit guidance:

```
{
  "success": true,
  "session": "test_session",
  "requestedAction": "start" | "stop" | "restart"
}
```

**Deliberately excluded from this shape: a `status` field.** Since
WAHA's response body for these five operations is unconfirmed, the BFF
cannot honestly claim "status is now X" from the lifecycle call's own
response. The frontend is expected to separately call `GET
/api/sessions/:session/status` (Section 2) after a lifecycle action to
observe the real, current state — this is a **safer contract than
guessing**, and matches this task's explicit instruction: *"design the
endpoint to return an operation/result that does not falsely claim a
state transition that was not confirmed."* If a future live test
confirms WAHA's real response body includes a trustworthy `status`
field, this contract can be extended to include it — not assumed now.

On WAHA error, the BFF returns `{"success": false, "session": ...,
"requestedAction": ..., "error": "<safe, non-credential message>"}`,
mirroring the existing `apps.core.exceptions.api_exception_handler`
pattern's spirit (server-side detail logged, generic detail returned).

---

# 8. Session lifecycle endpoint policy — explicit, evidenced

| Operation | Exposed via BFF? | Evidence |
|---|---|---|
| **start** | **Yes** | `docs/00-MASTER-SPEC.md` "Fitur" explicitly lists *"start/stop/restart"* as a product feature |
| **stop** | **Yes** | Same |
| **restart** | **Yes** | Same |
| **QR** | **Yes** | `docs/00-MASTER-SPEC.md` "Fitur" explicitly lists *"QR/pairing"* |
| **pairing code** | **Yes** | Same feature line covers WAHA's phone-number-linking alternative to QR |
| **logout** | **No** | **Absent from `docs/00-MASTER-SPEC.md`'s "Fitur" list entirely** — only start/stop/restart are named, not logout. This task's own instruction ("Do NOT expose logout ... unless repository requirements explicitly prove they are required") is decisive here: nothing does. Independently, this round's own instructions forbid even testing logout against the real session under any circumstance. |
| **delete** | **No** | Also absent from the Fitur list; the single most destructive/irreversible operation (removes session config and data entirely, per official docs); reads as `docs/06-SECURITY.md`'s "system administration" category, which is explicitly *separate* from "session control" — the category the BFF's scoped key and JWT-`session control` claim are both limited to (Section 1/10) |
| **create / update session** | **No** | Not a documented end-user capability anywhere in `docs/`; this project has exactly one (soon 2–3) pre-existing, operationally-managed session — provisioning a new one is an operational task, not an app feature |

---

# 9. Office-down (Availability) boundary

### Must work without Django

- `GET /api/sessions/:session/status` — WAHA-live, no Django dependency.
- `POST start` / `stop` / `restart` — the WAHA call itself has no
  Django dependency. (Audit write degrades — see below.)
- `GET qr` / `POST pairing-code` — same.
- `POST messages` (send) — the WAHA call itself works without Django.
  **What degrades, precisely**: idempotency-key *registration/duplicate
  detection* (Section 3, step 3) — without Django reachable, the BFF
  proceeds to WAHA anyway, meaning duplicate-send protection is not
  guaranteed during an actual Office outage. This is the one place
  where "still works" and "still fully safe" are not the same claim,
  and this document does not blur that distinction.
- **JWT verification for an already-authenticated user** — this is the
  entire reason JWT was chosen over Django sessions/DRF `TokenAuthentication`
  (`docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` Section 1): the
  BFF verifies a previously-issued token locally, using an
  already-distributed public key (Section 10), with no live Django call.
  So permission/authorization checks for an existing session **do not**
  require Django — only issuing a **brand-new** token does (below).

### Requires Django (degrades or fails during an Office outage)

- Chat list / message history / chat detail (Section 4 — Django is the
  durable source of truth for these by design).
- Actor-attributed `AuditLog` writes (Section 5) — degrade to
  BFF-local structured logs only, not lost entirely, but not durable
  either.
- Idempotency-key duplicate-*detection* guarantee specifically (not the
  send itself — see above).
- **Brand-new logins** — a new JWT can only be issued by Django (the
  system of record for `auth.User`/`Group`/`Permission`); this fails
  closed during an outage, an accepted, explicit exception to "WAHA/Tencent
  keeps working," consistent with `docs/00-MASTER-SPEC.md`'s Availability
  wording, which only promises continuity for what's already working,
  not for new sessions being established mid-outage.

This table is the concrete artifact `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md`
Section 7 said Phase 6 "must not omit" — a precise
which-upstream-failed signal for Phase 7/9's UI to consume, now written
down operation-by-operation rather than as a general principle.

---

# 10. Authentication token design

The architectural choice (Django-issued, independently-verified signed
token) is **not** revisited — only the implementation-level questions
below, as instructed.

- **Signing algorithm: asymmetric (RS256 or ES256), not HS256.**
  Justified specifically by this project's own topology and history, not
  generic best practice alone: Django (Office) and the BFF (Tencent) run
  in two differently-trusted zones connected over NetBird/LAN
  (`docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`), and this project has already
  had one real credential-exposure incident on infrastructure adjacent
  to the BFF's side of that boundary
  (`docs/generated/PHASE-6-WAHA-LIFECYCLE-VERIFICATION.md` Section 3).
  With a symmetric secret (HS256), anything that can *verify* a token
  can also *forge* one — meaning a compromise of the BFF alone would be
  enough to mint arbitrary, fully-privileged tokens. With asymmetric
  signing, the BFF holds only the public key and can verify but never
  forge; only Django (holding the private key) can issue valid tokens.
  Given this project's demonstrated exposure surface on the Tencent
  side, this is a concrete, not theoretical, reason to prefer asymmetric
  signing here. **No dependency currently exists on either side for
  JWT** (confirmed this round: `backend/requirements.txt` has no
  `PyJWT`/`djangorestframework-simplejwt`; `bff/package.json` has no
  `jsonwebtoken`/`jose`) — this is a fully greenfield choice, not a
  constraint imposed by an already-chosen library.
- **Claims (proposed)**: `sub` (Django user ID), `iss`
  (e.g. `waha-monitoring-django`), `aud` (e.g. `waha-monitoring-bff`),
  `iat`, `exp`, and a `scopes` claim listing the permission categories
  from `docs/06-SECURITY.md` verbatim (`reading`, `sending`, `session
  control`, `blast`, `user administration`, `system administration`) —
  reusing that document's own category names rather than inventing a
  parallel vocabulary. **How Django's existing `auth.User`/`Group`/`Permission`
  model maps to these specific scope strings is an implementation
  detail, correctly left open here**, not an architecture decision.
- **Issuer / audience**: Django is the sole issuer; the BFF is
  currently the sole audience (one BFF process exists in this
  architecture) — `aud` is still recorded explicitly rather than
  omitted, so a future second consumer doesn't silently start accepting
  tokens meant for the BFF.
- **Expiration and refresh — mechanism decided, exact value OPEN**: a
  short-lived access token plus a refresh flow that itself requires
  Django (since only Django can mint a new token). **This creates a real,
  named tension with the Availability requirement**: the longer the
  access-token lifetime, the longer an already-logged-in user survives
  an Office outage without needing Django again — but a longer lifetime
  also means a compromised/leaked token stays valid longer. **This
  document does not pick a number** (no project document specifies one)
  — it is recorded as an explicit product/security tradeoff requiring a
  deliberate choice, not silently defaulted.
- **Key distribution**: Django holds the private signing key;
  environment/secret-managed, never committed
  (`docs/08-DEPLOYMENT.md`: *"Secrets must be environment/secret-managed
  and never committed"* — generic, applies here as it does to
  `WAHA_API_KEY`/the webhook HMAC secret). The public verification key
  is provisioned to the BFF through the same class of manual,
  environment-based mechanism already used for those other cross-site
  secrets — no new distribution infrastructure (e.g. a JWKS endpoint) is
  proposed, since this project's scale (one BFF, one Django, 2–3 WAHA
  sessions) doesn't evidence a need for one.
- **Rotation**: because signing is asymmetric, rotating means
  distributing a *new* public key to the BFF before Django starts
  signing with the corresponding new private key, and retaining the old
  public key briefly (a small, statically-configured 1–2-key set, not a
  live discovery service) so already-issued, not-yet-expired tokens
  signed with the old key remain verifiable during the transition — a
  `kid` (key ID) claim in the token header is the standard way to tell
  the BFF which key to use. **Exact rotation cadence/triggers**: not
  specified by any document — OPEN, an operational policy decision.
- **Behavior when Django is temporarily unavailable**: already-issued,
  not-yet-expired tokens keep verifying locally at the BFF (no live
  check required — the entire point of this design, Section 9). New
  logins and token refreshes fail closed with a clear "cannot
  authenticate, Office unreachable" response — an accepted, explicit
  exception, not a silent failure mode.

---

# 11. Final decision matrix

| Decision | Final decision | Evidence | Implementation impact | Remaining uncertainty |
|---|---|---|---|---|
| Authentication mechanism | Django-issued, independently-verified signed token | `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` §1 (unchanged) | New BFF middleware + Django issuance endpoint | none at architecture level |
| Token signing algorithm | Asymmetric (RS256/ES256) | §10, this document | Key-pair generation, distribution | exact algorithm (RS256 vs ES256) — **OPEN** |
| Token expiration/refresh value | Mechanism decided; exact lifetime **OPEN** | §10 | Refresh endpoint on Django | outage-survival window vs. leak exposure tradeoff — **OPEN, needs product decision** |
| BFF→WAHA credential | Session-scoped key(s), `read+send+control`, no `delete`/`setting`/`app` | §1 | Mint 1 key per session (2–3 total) via Keys API | Keys API reachability on this deployment — **not live-tested**, non-blocking (B is documented fallback) |
| BFF route contract (session) | Locked — table in §2 | §2 | New BFF routes, allowlist entries | exact WAHA response-body fields for start/stop/restart/logout/delete — **OPEN** (§7 designed around this gap, not blocked by it) |
| Chats/messages BFF exposure | **Not exposed via BFF** — Django-direct | §2, §4; `PHASE-6-BLOCKER-RESOLUTION.md` | No BFF chat/message routes; Django/DRF routes are a Phase 8 concern | none |
| Send-message idempotency flow | Locked — full flow in §3 | §3 | `OutboundOperation` wiring into a new Django endpoint + BFF send route | staleness/retry policy for stuck `PENDING`/`UNKNOWN` rows — **OPEN**, deliberately not invented |
| Chat identity / source of truth | **Django durable records** | §4; corroborated by `00-MASTER-SPEC.md` "Ownership" | Confirms Phase 8 (not 6) owns chat/message serving | none |
| Audit sequencing | **After** the WAHA call, not before | §5 — repository-verified against `AuditLog`'s schema | New narrow BFF→Django audit endpoint (+ reuse of §3's endpoint for sends) | correlation/request-ID field — **OPEN**, would need a schema change, deferred |
| QR/pairing contract | BFF proxies WAHA's payload as-is; narrow project-owned envelope | §6 | New BFF QR/pairing routes | exact WAHA response field names — **OPEN** |
| Lifecycle response shape | Project-owned `{success, session, requestedAction}`, no unconfirmed `status` claim | §7 | Applies uniformly to start/stop/restart | none — this is designed specifically to not depend on the open WAHA response-body gap |
| Lifecycle endpoint exposure | start/stop/restart/QR/pairing-code exposed; logout/delete/create/update not | §8 | Defines the BFF allowlist's exact contents for session ops | none |
| Office-down boundary | Locked — table in §9 | §9 | Drives Phase 9's degraded-mode UI signal contract | none |
| Doc-name/scope mismatches (§0) | Flagged, not resolved | §0 | none (documentation hygiene only) | which phase (6 vs 8/10) actually ships each route — **OPEN**, a project-scoping question |

## Final BFF route table

| Method | Route | Auth | Django | WAHA | Purpose |
|---|---|---|---|---|---|
| GET | `/api/sessions/:session/status` | JWT (`reading`) | No | Yes | Live session status |
| POST | `/api/sessions/:session/start` | JWT (`session control`) | Best-effort (audit) | Yes | Start session |
| POST | `/api/sessions/:session/stop` | JWT (`session control`) | Best-effort (audit) | Yes | Stop session |
| POST | `/api/sessions/:session/restart` | JWT (`session control`) | Best-effort (audit) | Yes | Restart session |
| GET | `/api/sessions/:session/qr` | JWT (`session control`) | Best-effort (audit) | Yes | QR retrieval |
| POST | `/api/sessions/:session/pairing-code` | JWT (`session control`) | Best-effort (audit) | Yes | Pairing code |
| POST | `/api/sessions/:session/messages` | JWT (`sending`) | Required for idempotency registration (best-effort if down), best-effort for resolution/audit | Yes | Send message |
| GET | `/health` | none | No | Yes (reachability probe only) | Degraded-mode signal |

## Final data-flow diagrams

**1. Authentication**
```
Frontend --login(credentials)--> Django
Django --verifies against auth.User/Group/Permission--> Django
Django --issues JWT (RS/ES-signed, scopes claim)--> Frontend
Frontend --Authorization: Bearer <jwt>--> BFF
BFF --verifies signature locally (public key, no Django call)--> BFF
```

**2. Session lifecycle**
```
Frontend --POST /api/sessions/:s/start (JWT)--> BFF
BFF --verify JWT, check `session control` scope--> BFF
BFF --POST /api/sessions/{s}/start (session-scoped key)--> WAHA
WAHA --200/error--> BFF
BFF --best-effort: POST /internal/audit-events {actor,action,target,result}--> Django
BFF --{success, session, requestedAction}--> Frontend
Frontend --GET /api/sessions/:s/status (separately)--> BFF --> WAHA
```

**3. Inbox/chat retrieval**
```
Frontend --GET chats / messages--> Django (DRF, direct — NOT via BFF)
Django --reads durable Chat/Message tables--> PostgreSQL
```

**4. Send message**
```
Frontend --POST /api/sessions/:s/messages, Idempotency-Key: k--> BFF
BFF --verify JWT (`sending`)--> BFF
BFF --sync, best-effort: register OutboundOperation(session,k)--> Django
  (existing PENDING/SENT -> return early, no WAHA call)
  (Django unreachable -> proceed anyway, degraded)
BFF --POST /api/sendText--> WAHA
WAHA --success(id)/error/timeout--> BFF
BFF --sync, best-effort: resolve OutboundOperation -> SENT/FAILED/UNKNOWN
              + write AuditLog (same Django transaction)--> Django
BFF --{status, providerMessageId?}--> Frontend
```

**5. Audit**
```
BFF-initiated action resolves against WAHA (success/fail/unknown)
        |
        v
BFF --best-effort, bounded timeout--> Django: AuditLog.objects.create(actor, action, target, result)
        |
        v (always, regardless of the above call's outcome)
BFF --result--> Frontend
BFF --structured local log line (fallback trail)--> BFF's own logs
```

**6. Office-down behavior**
```
Django/PostgreSQL: OFFLINE
Frontend --already-issued JWT--> BFF: verifies locally, no Django call — OK
BFF --session status/start/stop/restart/QR/send--> WAHA — OK (send: idempotency degraded)
Frontend --chat list / message history--> Django — FAILS, labeled "unavailable" per 03-UI-UX-SPEC.md
Frontend --brand-new login--> Django — FAILS, fails closed
BFF audit writes --> Django — FAIL, BFF falls back to local logging only
```

## Phase 6 implementation checklist

**MUST IMPLEMENT**
- BFF JWT verification middleware (public-key based, local, no Django round-trip).
- BFF WAHA allowlist entries for: status, start, stop, restart, qr,
  pairing-code, sendText — nothing else (`bff/src/wahaAllowlist.ts`).
- BFF routes per §2's table, including the `/health` extension.
- Django: JWT issuance endpoint (login), using the new asymmetric key pair.
- Django: narrow `OutboundOperation` registration/resolution endpoint
  (§3), reachable only by the BFF's service credential.
- Django: narrow audit-event endpoint (§5), reachable only by the BFF's
  service credential.
- Session-scoped WAHA API key(s) minted via the Keys API and configured
  as the BFF's WAHA credential (§1).

**MUST TEST**
- Idempotency-Key retry behavior (existing `PENDING`/`SENT`/`FAILED`/`UNKNOWN`
  rows all handled per §3's table) — directly maps to
  `docs/09-TEST-PLAN.md`'s "Ambiguous outbound result does not cause
  duplicate send."
- JWT verification continues working with Django simulated as
  unreachable (§9).
- Audit write failure does not block a successful WAHA action from
  reaching the frontend (§5).
- Lifecycle endpoints never claim an unconfirmed `status` (§7).
- WAHA allowlist rejects any non-allowlisted path (`CLAUDE.md` rule 5).

**MUST VERIFY LIVE** (deferred — none performed this round, per this
task's explicit instruction not to touch production WAHA state)
- Actual response bodies for start/stop/restart/logout/delete.
- Actual QR/pairing-code response field names.
- Session-scoped API key actually blocked from `/api/server/environment`
  and other admin endpoints.
- Whether WAHA sends a webhook for outbound/self-sent messages at all
  (still unconfirmed from Phase 3).

**DEFERRED / NOT IN PHASE 6**
- Chat list / chat detail / message history endpoints (Django/DRF,
  Phase 8 per §0.2/§4).
- Any visual grouping of multiple `Chat` rows representing one real
  contact (product/UX decision, `PHASE-6-BLOCKER-RESOLUTION.md`).
- Staleness/auto-retry policy for stuck `PENDING`/`UNKNOWN`
  `OutboundOperation` rows (§3 — explicitly not invented).
- `logout`/`delete`/create/update session endpoints (§8 — not exposed at
  all, not merely deferred).
- Token rotation automation, exact expiration value (§10 — OPEN, product
  decision).

## Final readiness decision

**PHASE 6 NOT READY**

Every item this task asked to resolve now has either a **locked
decision** or an **explicitly named OPEN item** — there is no remaining
"unknown API" or "unknown architecture" category left (that was the
state of things before the WAHA documentation was obtained; it no longer
is). What blocks implementation now is a shorter, concrete list, not a
specification gap:

1. **Confirm this document's decisions** — none of §1–§10's "Final
   decision"/"Decision" items have been confirmed by you yet; this
   document proposes and evidences them but does not unilaterally treat
   silence as approval.
2. **Two explicit product/security tradeoffs with no defensible default
   this document can pick alone**: JWT expiration lifetime (§10 —
   outage-survival vs. leak-exposure), and the stuck-`PENDING`/`UNKNOWN`
   `OutboundOperation` resolution policy (§3 — auto-retry-after-timeout
   vs. manual-only).
3. **The §0.2 scoping question**: whether session-lifecycle/QR and
   send-message routes ship as part of "Phase 6" or are deferred to
   Phases 8/10 per `docs/15-CODING-PHASES.md`'s own phase list — this
   document defines the *contract* regardless, but not *which phase's
   code* implements it.
4. **A small number of narrow OPEN technical items** that do not block
   starting implementation but should be tracked: exact WAHA
   response-body fields for lifecycle/QR (worked around by §7's
   conservative contract, not blocking), signing algorithm choice
   between RS256/ES256, exact JWT claim-to-Django-permission mapping.

None of the above require further live testing against `test_session`,
and none require re-discovering WAHA's API — that gap is closed.
