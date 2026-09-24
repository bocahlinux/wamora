# Inbox — Outbound Message Missing From History (Read-Only Audit)

Scope respected exactly as instructed: **read-only**, no code/DB/config
change, no additional WhatsApp message sent, no LID/JID auto-merge or
identity-resolution change, `status@broadcast` not touched, BFF not
modified, no implementation performed. This report only investigates and
recommends.

## 1. Observed behavior

- User sent a reply from the Inbox composer to the chat that displays as
  `Yuk Code Creative / 62811520892` (`Chat.id = 3`,
  `provider_chat_id = 168160971997355@lid`).
- WAHA/WhatsApp actually received and delivered the message (confirmed by
  the user directly on the WhatsApp side, and consistent with the UI
  showing the "sent" confirmation banner, not an error).
- The outbound message never appeared in the Inbox conversation history,
  neither immediately nor after the 5s polling interval.

## 2. Exact root cause

**WAHA did not deliver a webhook event for this outbound (self-sent)
message.** Django's ingestion pipeline is not broken and did not silently
drop or filter anything — it simply never received anything to process
for this send. This is a live, first-time confirmation of a risk this
project's own reference doc already flagged as an open, unverified
question (Section 4 below).

This is **not** a bug in `parse_message()`/`persist_message()`, **not** a
bug in `GET /api/chats/:id/messages/`, and **not** a frontend
rendering/filtering bug — all three are demonstrated working correctly
for outbound messages by an existing, already-persisted row from a prior
session (`Message.id = 23`, Section 4).

## 3. Evidence from code

- **Composer never does optimistic insertion.** `InboxPage.tsx`'s
  `handleSend()` only sets `sendConfirmed` from the BFF's response; it
  never appends a locally-fabricated message to `messages` state. History
  is only ever populated from `getChatMessages()` (poll or initial
  fetch). This is deliberate (see the function's own comment: "never
  fabricate a local message bubble for what hasn't actually been
  persisted") — so the UI correctly shows nothing until Django actually
  has a durable copy.
- **The send path never writes to Django at all.** `bff/src/routes/messages.ts`
  (`POST /sessions/:session/messages`) only registers/resolves an
  `OutboundOperation` idempotency record in Django and calls WAHA's
  `sendText` — there is no code path, in the BFF or the frontend, that
  creates a `Message` row directly. The **only** way an outbound message
  ever becomes visible in the Inbox is via `persist_message()`, and the
  **only** two callers of `persist_message()` are webhook ingestion
  (`apps/webhooks/services.py::ingest_webhook`) and reconciliation
  (`apps/sync/reconciliation.py`). Nothing else in this codebase inserts
  a `Message`.
- **`persist_message()` correctly handles `from_me=True` when it does
  run.** The `Message.objects.create(...)` call
  (`backend/apps/webhooks/services.py:122-131`) is unconditional —
  `direction` is simply derived from `parsed.from_me`
  (`Message.DIRECTION_OUTBOUND if parsed.from_me else ...`). Only the
  Contact-identity block above it (`if not parsed.from_me and not
  parsed.is_group:`) is skipped for outbound, by design (an outbound
  message's `Sender` is the account's own identity, never used to
  create/update a Contact). The message itself is still created and
  linked to `chat` regardless.
- **`parse_message()` has no from_me-based branch that would reject or
  drop an outbound payload.** `from_me` is read from `payload.fromMe`
  (falling back to `Info.IsFromMe`) purely to set `ParsedMessage.from_me`
  — there is no code path where `from_me=True` causes
  `MessageParsingError` or an early return.
- **`GET /api/chats/:id/messages/`** (`apps/chats/views.py::ChatMessagesView`)
  queries `chat.messages` with no `direction` filter, and
  **`MessageSerializer`** exposes `direction` as a plain field with no
  conditional exclusion. **`InboxPage.tsx`** renders every message
  returned, using `direction` only to pick a CSS class
  (`wa-inbox__bubble--${message.direction}`), never to filter.

## 4. Evidence from database / prior live webhook history

Live, read-only query against the real dev PostgreSQL database (`manage.py shell`, no writes):

**Recent `WebhookEvent` rows (all of them — table has exactly 4 rows):**

| id | event_type | status | provider_event_id | received_at (UTC) |
|---|---|---|---|---|
| 2 | session.status | unsupported | webhook-verification-001 | 2026-09-24 14:38:09 |
| 3 | message | processed | false_168160971997355@lid_2A6981D843E638E21C36 | 2026-09-24 14:44:21 |
| 4 | message | processed | false_168160971997355@lid_2A07362EE6000A851353 | 2026-09-24 14:44:33 |
| 5 | message | processed | false_168160971997355@lid_2A067E1C5A265971BD44 | 2026-09-24 14:59:00 |

All three real `message` events today are **inbound** (`false_...` prefix
= `fromMe=false`). Current server time at the moment of this audit:
**2026-09-24 15:03:50 UTC** — i.e. up to ~5 minutes after the last
confirmed inbound webhook, and after the user's own outbound test.
**Zero** `WebhookEvent` rows exist for any outbound/self-sent message
today, and zero rows of any kind were created after `id=5` (14:59:00).

**Chat 3's message history** (`Message.objects.filter(chat_id=3)`,
newest first, relevant excerpt):
```
44  inbound   false_168160971997355@lid_2A067E1C5A265971BD44   2026-09-24 14:59:01  'Cek ya'
43  inbound   false_168160971997355@lid_2A07362EE6000A851353   2026-09-24 14:44:34  'Wah udah masuk nih webhooknya'
42  inbound   false_168160971997355@lid_2A6981D843E638E21C36   2026-09-24 14:44:22  'Tes'
24  inbound   false_168160971997355@lid_2A69B9A76142A56A0CE7   2026-09-23 05:10:35  'Tes'
23  outbound  true_168160971997355@lid_A588F68CE9231B4DDE50896B0A4EC41A  2026-09-23 05:14:16  'Tes'
```
**Message 23 proves the full pipeline (parse → persist → serialize →
render, including `direction='outbound'`) already works end-to-end when
a `message` webhook with `fromMe=true` actually arrives** — this is not
speculative; it's a real row already sitting in the same chat, same
Contact, same code path. It was almost certainly ingested via a
**reconciliation** run (`apps/sync/reconciliation.py`, which also calls
`persist_message()` but reads from WAHA's REST message-history endpoint,
not from a live webhook push) rather than a real-time webhook, since no
`WebhookEvent` row exists that old (the `WebhookEvent` table only has 4
rows total, all from today — reconciliation deliberately never creates a
`WebhookEvent` row, only `ingest_webhook()` does).

This is exactly the gap `docs/12-WAHA-REFERENCE.md` already flagged as
unresolved (lines 238-243, written before this project had live outbound
webhook evidence either way):

> "Still unconfirmed: whether WAHA sends a *webhook* for outbound/self-sent
> messages at all — the 2 outbound examples were found via a REST history
> query, not a captured webhook delivery, so it remains unknown whether
> this project's webhook endpoint will ever actually receive an outbound
> `message` event in practice."

Today's live evidence answers this, for this deployment: **no**, at
least not observed in 3 consecutive inbound deliveries succeeding while
0 outbound deliveries occurred in the same window.

**One caveat on certainty**: a rejected webhook (bad/missing HMAC
signature) never creates a `WebhookEvent` row either —
`WahaWebhookView.post()` checks the signature and returns `401` *before*
calling `ingest_webhook()` (`apps/webhooks/views.py:33-45`). So this
audit cannot fully rule out "WAHA attempted delivery but the signature
was rejected" purely from DB state — only Django's own console log
(`Rejected webhook request: invalid or missing signature`, printed by
the same code path) would show that, and this task had no access to that
live process's console output. However, this is very unlikely to be the
actual explanation here: the exact same session/webhook config
successfully delivered and passed signature verification for 3 inbound
messages minutes earlier and later within the same short window, with no
config change in between.

## 5. Was the outbound message actually stored, or lost?

**Lost — not stored anywhere in Django.** WhatsApp itself has the
message (confirmed by the user), but Django's database has no `Message`
row for it, because nothing ever called `persist_message()` for it. It
is not sitting in an unprocessed/failed `WebhookEvent` either (the table
has exactly 4 rows, none matching). The next full or targeted
reconciliation run against session `no_epahari` would very likely pick
it up via the REST message-history endpoint (the same mechanism that
must have produced `Message.id=23`) — but this audit did not trigger one
and has not verified that. Nothing was actually destroyed; it's simply
absent from Django until either a webhook eventually arrives (unlikely,
per Section 4) or a reconciliation run reads it from WAHA's own REST
history.

## 6. Files / functions relevant to a fix (not changed)

- `apps/sync/reconciliation.py::reconcile_session(session_name,
  chat_ids=...)` — already supports a **targeted** (single-chat) run via
  the existing `chat_ids` parameter, and already shares the exact same
  `persist_message()` used by webhook ingestion, so it applies identical
  Contact/Chat/Message rules with zero behavioral drift risk.
- `apps/sync/waha_client.py::WahaClient.fetch_chat_messages(session,
  chat_id, limit, offset)` — the underlying REST call reconciliation
  already uses; no new WAHA integration would be needed.
- `bff/src/routes/messages.ts` — the point where a successful `sent`
  outcome is already known, if a "trigger a reconciliation for this one
  chat right after a confirmed send" approach were chosen.
- `frontend/src/pages/InboxPage.tsx::handleSend()` — alternatively, the
  point where a "refetch this chat's messages once, shortly after a
  confirmed send" retry could be added on the frontend side instead,
  without touching the BFF.

## 7. Minimal fix recommended (not implemented — awaiting approval)

Two independent, non-mutually-exclusive options, both reusing existing,
already-tested mechanisms rather than adding a new persistence path:

1. **Frontend-only, smallest blast radius**: after `sendMessage()`
   resolves with `status: 'sent'`, do one extra `getChatMessages(chatId,
   1)` fetch a few seconds later (on top of the existing 5s poll this
   already effectively does) — this alone will **not** fix anything,
   since Django still has no row to return. Not viable by itself; listed
   only to explicitly rule it out as insufficient.
2. **Trigger a targeted reconciliation after a confirmed send** (the
   real fix): once the BFF's `sendText` call resolves as `status:
   'sent'`, call `reconcile_session(session, chat_ids=[chatId])` for
   that one chat — either synchronously from Django (a new small
   endpoint the BFF calls, mirroring how `registerOutboundOperation`/
   `resolveOutboundOperation` already call Django) or via the existing
   Celery task (`apps.sync.tasks.reconcile_session_task`) enqueued
   asynchronously. This directly closes the gap using the exact
   mechanism that already produced `Message.id=23` — no new WAHA
   endpoint, no new parsing logic, no new identity rule.
3. **(Longer-term, out of scope for a minimal fix)**: a periodic
   background reconciliation (e.g. every N minutes, all active chats)
   would also eventually surface outbound messages without any per-send
   hook, at the cost of latency and needing its own scheduling decision
   — not recommended as the *minimal* fix, but worth noting as the more
   general solution to "WAHA outbound webhooks may never come."

No specific option is being implemented now, per instruction to stop
after the audit.

## 8. Risks / regressions to weigh before implementing

- Calling `reconcile_session` synchronously inside the BFF's send-message
  request path would add real WAHA REST latency to every send response
  — likely better done asynchronously (fire-and-forget Celery task) so
  the send response time is unaffected.
- `reconcile_session`'s discovery/pagination logic (`apps/sync/reconciliation.py`)
  was built and tested for scheduled/manual full-session runs; a
  single-chat, per-send invocation is a new call pattern (low volume
  today, but every future send would trigger one) — needs its own
  rate/latency consideration once implemented, not assumed safe by
  default.
- Any fix here must **not** change `persist_message()`'s Contact/identity
  rules — the existing evidence (`Message.id=23` already correctly
  outbound, correctly attributed to `Chat.id=3`) shows the current rules
  are already correct for this case; the fix is purely about *triggering*
  ingestion, not changing what happens once it runs.
- Must confirm whether `reconcile_session`/`reconcile_session_task` is
  safe to call frequently against the live, connected `no_epahari`
  session (rate limits, WAHA-side load) before wiring it to fire on every
  send — not evaluated in this audit.

## 9. Tests to run after implementing a fix

- Existing full backend suite (currently 254 tests, all passing) must
  stay green.
- A new test proving: after a `sendText` success, the targeted
  reconciliation call is made with exactly the sent chat's
  `provider_chat_id` (mock/stub `WahaClient`, no real WAHA call in
  tests).
- A new test proving a failed/`unknown` send outcome does **not** trigger
  the extra reconciliation call (only a confirmed `sent` outcome should).
- A regression test confirming the existing idempotency/`OutboundOperation`
  flow in `bff/src/routes/messages.ts` is unaffected (same status codes,
  same duplicate-key behavior) if the fix touches that file.
- A live, manual verification once implemented: send one real outbound
  message from the Inbox composer and confirm it appears in the
  conversation history within the existing poll interval, without a
  second, unrelated outbound test message being required (reuse the
  planned real test, don't add extra sends beyond what's needed).

---

Read-only audit complete. No code, database, config, or WAHA session was
changed. No additional WhatsApp message was sent. Stopping here and
awaiting approval before implementing anything from Section 7.
