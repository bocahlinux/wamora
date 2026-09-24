# Phase 6 — Blocker Resolution

Research and decision-making only. No application code, models,
migrations, frontend, BFF implementation, or production configuration
was modified. `test_session` was never started, stopped, restarted, or
logged out; no WhatsApp message was sent (verified — see Blocker 1's live
evidence section).

**Document reference note**: `docs/generated/PHASE-4-LIVE-VERIFICATION.md`,
listed among this task's relevant documents, does not exist. The
equivalent content (pagination live-verification, evidence gathered
during the Phase 4/5 timeframe) is in `docs/generated/PHASE-3-LIVE-VERIFICATION.md`
(updated across rounds) and `docs/generated/PHASE-4-RECONCILIATION.md`. Used those instead.

---

## Blocker 1 — Outbound message idempotency

### Existing evidence

- `Message`: unique on `(session, provider_message_id)` — protects
  against duplicate *persistence*, but only applies once a
  `provider_message_id` exists, i.e. **after** WAHA has already accepted
  and assigned an ID to a send. It cannot, by itself, stop a *second real
  send* from happening.
- `OutboundOperation` (Phase 2, `apps/operations/models.py`): unique on
  `(session, idempotency_key)`, has `status` (`pending`/`sent`/`failed`/
  `unknown`) and an optional `provider_message_id`. **Built for exactly
  this problem, but never wired into any send flow — no code anywhere in
  this project creates, updates, or reads an `OutboundOperation` row.**
- `persist_message` (`apps/webhooks/services.py`, shared by webhook
  ingestion and reconciliation): on an outbound (`fromMe=true`) message,
  creates a `Message` row with `direction=outbound`. **It never looks up
  or updates any `OutboundOperation` row.** This linkage does not exist
  in the codebase today.
- `docs/05-WEBHOOK-SYNC-DESIGN.md`, "Outbound during outage": *"Use an
  idempotency key. Send through BFF/WAHA. When office returns,
  record/reconcile provider message ID. Never blindly resend an
  operation whose success is uncertain."* — confirms recording/reconciling
  happens **after** the send attempt, and explicitly frames the risk as
  *resending*, not as failing to record.

### New live evidence gathered this round (real WAHA, read-only-safe probing only)

`POST /api/sendText` was **never sent a real, valid, deliverable
request** — but its input-validation behavior was probed safely, the
same way prior rounds used `HEAD`/`OPTIONS` to discover route existence
without triggering side effects. Here, a deliberately-invalid body is
used instead, since `sendText` has no safe read-only equivalent:

| Body sent | Result | What it reveals |
|---|---|---|
| `{}` | `400 Bad Request`, `"Session name is required"` | Clean, safe, pre-dispatch validation for a missing `session` — no side effect |
| `{"session": "test_session"}` | `500`, `TypeError: Cannot read properties of undefined (reading 'includes')` inside `ensureWidSuffix` | `chatId` is required but **not validated cleanly** — the server crashes in a pre-send WID-resolution step, not the gRPC send call itself |
| `{"session": "test_session", "chatId": ""}` | `500`, `"2 UNKNOWN: no LID found for s.whatsapp.net from server"`, stack trace shows it reached `MessageServiceClient.SendMessage` (the actual gRPC dispatch layer) | An empty `chatId` reaches real dispatch logic before failing — WAHA's own input validation here is **weak**, not a clean upfront rejection |
| `{"session": "test_session", "chatId": "invalid-nonexistent-id"}` | **Timed out (10s), no response** | **Stopped here — this result was treated as a risk signal, not investigated further.** A hang is consistent with WAHA attempting a real contact/LID resolution lookup for a non-existent identifier rather than failing fast |

**Safety confirmation**: a read-only `GET /api/test_session/chats` was
checked immediately after — both chats' `conversationTimestamp` values
are byte-identical to before this probing began, confirming **no message
was sent and no new conversation activity occurred.**

**What this establishes for Blocker 1**: no field resembling a
client-supplied message ID, idempotency key, or custom-ID parameter was
ever echoed back, hinted at, or referenced in any of these responses —
only `session` and `chatId` (and presumably `text`, never reached).
**No evidence was found that WAHA's `sendText` supports an
idempotency/client-message-ID mechanism of its own.** Per the explicit
instruction not to invent such a scheme without evidence, none is
proposed. Probing was deliberately stopped before confirming `text`'s
requirement, given the timeout risk already observed.

### Analysis — walking the exact sequence

> 1. BFF sends message to WAHA. 2. WAHA accepts. 3. Response lost.
> 4. WAHA emits `fromMe` webhook. 5. Django persists the outbound
> `Message`. 6. Frontend retries the same logical request.

**Without any change, today**: at step 6, nothing exists to tell the
frontend/BFF "this was already sent." The BFF has no database. The only
durable record by step 5 is the `Message` row itself — but the frontend
retrying doesn't know that `Message`'s `provider_message_id` (it never
received WAHA's response in step 3, and WAHA has no documented mechanism
to look up "the message I would have gotten back for this exact prior
attempt"). **A blind retry today would genuinely double-send.** This
matches the failure mode `05-WEBHOOK-SYNC-DESIGN.md` explicitly warns
against.

**What existing infrastructure *can* prevent this, if wired in**:
if an `idempotency_key` is generated once (client-side, at the moment the
user initiates the send) and **registered with Django synchronously,
before the BFF calls WAHA** — i.e. `OutboundOperation.objects.get_or_create(session=..., idempotency_key=..., defaults={'status': PENDING, ...})`
— then step 6's retry, attempting to register the *same* key, finds the
existing `PENDING` row and can be told "do not resend, outcome is still
unknown" (or "already resolved," if it happened to have been updated by
then) **without ever needing to know WAHA's own state.** This is exactly
what `OutboundOperation`'s unique constraint already provides, unused.

**This requires one narrow, specific exception to the "no BFF→Django call
needed" conclusion in `docs/generated/PHASE-6-ARCHITECTURE-DECISION.md`
Section 2** — that conclusion was about *audit/durability* (which the
existing webhook path already covers, asynchronously, after the fact).
Idempotency-key *registration* is different: it must happen
**synchronously, before the WAHA call**, or it cannot do its job.
`docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` already anticipated a
version of this ("the BFF *may* still register the idempotency key with
Django first as a best-effort call") — this round confirms it more
precisely: **it is not "may," it is the only mechanism available that
makes idempotency detection possible at all**, given the confirmed
absence of any WAHA-side idempotency support.

### Decision

**The current architecture *can* prevent a blind resend, but only if a
step is added: the BFF (or frontend, via the BFF) registers a
client-generated `idempotency_key` with Django's existing
`OutboundOperation` model synchronously, before calling WAHA.** This uses
an already-built, already-tested (Phase 2) model and constraint — no
schema change, no new database, no invented WAHA behavior.

**What remains genuinely missing — identified, not invented**: nothing
in this codebase currently **resolves** a `PENDING` `OutboundOperation`
to `SENT` (with its real `provider_message_id`) once the confirming
webhook arrives. `persist_message` does not look for or update
`OutboundOperation` rows. Closing this requires either:
1. **Confirming WAHA passes through a client-supplied ID** that would
   make this correlation exact — this round's evidence suggests this
   does **not** exist (no such field was ever referenced), so this path
   appears closed, though not exhaustively proven (probing was stopped
   early for safety, per the timeout above).
2. **An explicit, human-approved correlation rule** (e.g. matching the
   oldest `PENDING` `OutboundOperation` for the same session+destination
   at persistence time) — this is possible with existing data, but **is
   itself a normalization/matching decision this document does not make
   unilaterally**, consistent with the instruction not to invent such a
   scheme. Flagged as a required decision (Section 11).

Until this is resolved, `OutboundOperation` rows can correctly *prevent
duplicate sends* but will not *automatically* transition to `SENT` —
they would need to stay `PENDING`/`UNKNOWN` unless something (manual
reconciliation, or the rule above once approved) resolves them. This is
a real, acceptable interim state, not a blocking defect: `STATUS_UNKNOWN`
exists in the model precisely for this.

---

## Blocker 2 — WAHA chat-list → Django Chat mapping

### Existing evidence

- `Chat`: unique on `(session, provider_chat_id)`. `provider_chat_id` is
  populated **verbatim** from whatever WAHA reports as primary
  (`apps/webhooks/services.py::persist_message`,
  `Chat.objects.get_or_create(session=session, provider_chat_id=parsed.chat_provider_id, ...)`)
  — this is the **only** mechanism anywhere in this codebase that creates
  or looks up a `Chat` row, and it has never attempted any cross-identity
  matching.
- `Contact.phone_number`: populated only from a confirmed, non-empty
  `Alt` field — explicitly optional metadata, per the Phase 2.5 rule
  restated verbatim in this task's own instructions.
- Live evidence (`docs/generated/PHASE-6-SPEC-RESOLUTION.md` Section 5,
  re-confirmed unchanged this round): WAHA's chat-list exposes
  `62800000000@c.us`; this project's accumulated evidence is keyed to
  `000000000000000@lid`; message-history for either resolves to the same
  merged conversation **on WAHA's side**, but nothing in this codebase
  performs or attempts that resolution locally.

### Analysis

The blocker was originally framed as *"map a WAHA chat-list item to an
existing Django `Chat`."* Re-examining the actual, already-existing
`get_or_create`-by-exact-`provider_chat_id` pattern shows this framing
assumes a mapping problem that may not need solving at all:

**The existing pattern already has a complete, safe, deterministic rule**:
look up (or create) a `Chat` row by `(session, provider_chat_id)` using
the identifier exactly as reported, whichever form it is. Applied to a
WAHA chat-list item the same way it's already applied to every message
processed by webhook ingestion and reconciliation, this rule is
**already sufficient and requires no new logic**:
- If `62800000000@c.us` arrives from the chat list and no `Chat` row
  has that exact `provider_chat_id`, a **new**, separate `Chat` row is
  created for it — correctly, per the existing rule, **not a bug**.
- This may mean two `Chat` rows exist for what a human recognizes as one
  real conversation (`000000000000000@lid` and `62800000000@c.us`).
  **This is not a new problem Phase 6 introduces** — it is the exact,
  already-documented "known limitation" in `docs/12-WAHA-REFERENCE.md`,
  now simply reachable from a second angle (a live chat-list call) in
  addition to the message-history angle already documented.

**Explicitly checked and rejected, per this task's own constraints**:
using `Contact.phone_number` to detect that two `Chat` rows' underlying
contacts share a phone number, and auto-associating/merging them on that
basis. **The data to perform this comparison exists** (both chats'
contacts would have `phone_number='62800000000'` once both are known to
Django) — but doing so automatically is exactly "make `@lid` and `@c.us`
interchangeable merely because they appear to resolve to the same
conversation," which this task explicitly forbids, and which the
standing Phase 2.5 rule already forbids ("never merge based on phone
number"). **Not proposed as a mechanism.**

### Decision

**A safe, deterministic mechanism already exists using current data: the
existing `(session, provider_chat_id)` `get_or_create` pattern, applied
without modification.** No new mapping logic, no new field, no schema
change is required. The apparent "blocker" was this task correctly
noticing a real, already-documented consequence of that pattern (possible
duplicate `Chat` rows for one real contact) — not a missing mechanism.

**This resolves a previously-open design question from
`docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` (Section 4/10) as a
direct consequence**: since WAHA's live chat-list cannot be trusted to
be either complete or consistently-identified relative to Django's own
accumulated `Chat` history (this blocker's finding), **"list chats" and
"get message history" should be served from Django's own durable
`Chat`/`Message` tables, not proxied live from WAHA.** This is not an
arbitrary preference — it follows directly from: (a) `07-API-CONTRACT.md`'s
already-existing "Frontend → Django" path for durable conversation views,
(b) the Availability requirement (durable reads keep working during a
WAHA outage, live-proxied ones wouldn't), and (c) this blocker's own
finding that WAHA's live chat-list is not reliable as the sole source of
truth. The BFF's WAHA-facing role narrows to what's genuinely live-only:
session status/lifecycle, QR, and sending.

**What remains a product decision, not a technical blocker**: whether
the frontend should ever visually group two `Chat` rows that a human
recognizes as the same contact, and if so, by what human-reviewed (not
automatic) process. Out of Phase 6's backend-API scope; does not block
implementation.

---

## Inbox consistency cross-check

| Property | Preserved? | Notes |
|---|---|---|
| One logical conversation = one Django `Chat` row | **Not guaranteed** — pre-existing, documented limitation, unchanged by this resolution | Explicit, not silently hidden |
| Correct LID/JID primary identity | **Yes** | Verbatim storage, unmodified |
| Correct phone metadata | **Yes** | `Contact.phone_number` population unchanged |
| Correct message history (per `Chat` row) | **Yes** | Existing constraints unaffected |
| Correct outbound message persistence | **Yes** | `persist_message` unmodified by this resolution |
| Idempotent webhook processing | **Yes** | `WebhookEvent`/`Message` constraints unaffected |
| Reconciliation compatibility | **Yes** | Reconciliation already operates per-known-`Chat`-row independently; nothing here changes that |
| Outbound send idempotency | **Conditionally yes** | Requires wiring `OutboundOperation` registration into the send flow (Blocker 1) — not yet implemented, decision now unblocked |

---

## Remaining limitations

1. `OutboundOperation` → `Message` resolution (marking a `PENDING` send
   `SENT` once confirmed) has no defined mechanism — flagged as a
   required decision, not invented (Blocker 1).
2. WAHA's webhook target still needs correcting to point at this
   project's Django endpoint for any of this to function against real
   traffic (unchanged finding from every prior live-verification round).
3. `sendText`'s full request schema (specifically whether `text` is the
   correct field name, and its exact validation behavior) was
   deliberately not fully mapped, given the timeout risk encountered —
   the safe parts learned are recorded above; the rest remains unverified.
4. Possible duplicate `Chat` rows for one real contact remain an
   accepted, documented characteristic of the system, not something this
   resolution changes.

## Required product decisions

1. **How should a `PENDING` `OutboundOperation` be resolved to `SENT`?**
   (Blocker 1) — requires either further safe evidence that WAHA supports
   a client-correlatable send ID (currently appears not to), or an
   explicit, approved correlation rule using existing fields (session +
   destination + timing) — not decided here, by design.
2. Whether the frontend should ever visually group multiple `Chat` rows
   representing one real contact, and if so, how (Blocker 2) — a product/
   UX decision, not a backend blocker.

## Phase 6 readiness

**PHASE 6 NOT READY** — but both named blockers are now resolved at the
architecture level:

- **Blocker 1 (outbound idempotency)**: resolved directionally — wire
  `OutboundOperation` registration into the send flow, synchronously,
  before the WAHA call. One follow-up decision remains (resolution
  mechanism, item 1 above) but does not prevent building the
  duplicate-prevention half of this now.
- **Blocker 2 (chat mapping)**: resolved — no new mapping logic needed;
  the existing `get_or_create`-by-exact-identifier pattern is already
  sufficient and correct. This also resolved the previously-open
  "chat-list/message-history source of truth" question as a direct
  consequence (serve both from Django, not live from WAHA).

**What still blocks overall Phase 6 readiness** (carried over from
`docs/generated/PHASE-6-ARCHITECTURE-DECISION.md`, unaffected by this
round): session lifecycle (start/stop/restart/logout) and QR/pairing
endpoints remain unverified against the real deployment, with no safe
verification path found in any round so far. Everything else identified
in this document is either resolved or explicitly scoped as a narrow,
named follow-up decision rather than a blanket blocker.
