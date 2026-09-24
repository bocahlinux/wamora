# Targeted Reconciliation Trigger — Design Check (Read-Only)

Follow-up to `docs/generated/INBOX-OUTBOUND-MESSAGE-MISSING-AUDIT-REPORT.md`
(approved fix direction: trigger `reconcile_session(session,
chat_ids=[chatId])` right after a confirmed `sent` outbound send). This is
a **read-only design check** — no code, database, config, or WAHA session
was changed, no WhatsApp message was sent. One open decision (Section 7)
needs your input before implementation starts.

## 1. Recommended implementation location

**Trigger point: `bff/src/routes/messages.ts`, immediately after `finalStatus`
is computed as `'sent'`** (right where `logAuditFallback` and
`resolveOutboundOperation` already run today, `messages.ts:97-123`). This
is the single place in the whole system that already knows, with
certainty, that WAHA accepted the send — reusing it means no new
signal/state has to be invented or threaded through anywhere else.

**Django side: a new internal endpoint**, following the exact existing
pattern in `apps/operations/views.py` /
`apps/core/internal_auth.py` (`HasInternalServiceKey`, wired under the
same `internal/` URL prefix `config/urls.py` already uses for
`apps.operations` and `apps.audit`). This reuses the BFF↔Django trust
boundary that already exists for `registerOutboundOperation`/
`resolveOutboundOperation`/`writeAuditEvent` — no new auth mechanism.

## 2. Exact request/data flow

```
InboxPage.handleSend()
  -> bffApi.sendMessage(session, chatId, text, idempotencyKey)   [UNCHANGED]
  -> BFF POST /api/sessions/:session/messages                     [UNCHANGED]
       -> registerOutboundOperation()                             [UNCHANGED]
       -> callWaha('sendText', ...)                                [UNCHANGED]
       -> finalStatus === 'sent'?
            -> resolveOutboundOperation()                         [UNCHANGED]
            -> logAuditFallback()                                 [UNCHANGED]
            -> NEW: fire-and-forget POST to Django
               /internal/reconciliation/trigger/
               body: { session, chat_id: chatId }
               (NOT awaited before responding to the frontend — see Section 7)
       -> res.json({ status: 'sent', providerMessageId })          [UNCHANGED, same timing]
  <- frontend receives 'sent' exactly as fast as today
  <- (in the background) Django processes the targeted reconciliation
  <- frontend's EXISTING 5s message-history poll (getChatMessages)
     picks up the new row once Django has it — no frontend change needed
```

**Nothing changes in the frontend.** `selectedChat.provider_chat_id` (the
`chatId` already sent to the BFF today) and `sessionName` (already sent
as the URL param today) are exactly the two values the new Django
endpoint needs — both already flow through the *existing* request. This
directly answers your audit questions #2/#3: the BFF already has
everything it needs from the current request; no new field needs to
travel from the frontend.

## 3. Files that would need modification

| File | Change |
|---|---|
| `backend/apps/sync/reconciliation.py` | None — `reconcile_session(session_name, chat_ids=[...])` already supports exactly this call shape. |
| `backend/apps/sync/tasks.py` | `reconcile_session_task` gains an optional `chat_ids=None` passthrough param (only needed for the Celery-based variant, Section 7 Option A). |
| **New**: `backend/apps/sync/internal_views.py` (or add to `apps/operations/views.py`) | New `ReconciliationTriggerView` — `permission_classes = [HasInternalServiceKey]`, same as every other internal endpoint. |
| **New/edit**: `backend/apps/sync/urls.py` (new) + `backend/config/urls.py` | Wire `internal/reconciliation/trigger/` the same way `internal/outbound-operations/` is already wired. |
| `bff/src/djangoClient.ts` | One new function, `triggerReconciliation({session, chatId}, options)` — same `postJson` helper already used for the other three internal calls. |
| `bff/src/routes/messages.ts` | One new call, fired (not awaited) right after `finalStatus === 'sent'`. |

**Not touched**: `apps/webhooks/*` (webhook behavior unchanged), `apps/chats/*`
(no API contract change — the existing `GET /api/chats/:id/messages/`
already returns outbound messages once they exist, per the prior audit),
`InboxPage.tsx`/frontend (no new data needed), Session Management, any
LID/JID identity code, `status@broadcast` handling.

## 4. Race condition: WAHA accept vs. message availability via REST

This is real and needs handling — your own audit question #6 is correct
to raise it. `WahaClient.fetch_chat_messages()` has no retry of its own
(`apps/sync/waha_client.py:53-94`, a single synchronous `requests.get`),
and this project has no existing evidence of how quickly a just-sent
message becomes visible via
`GET /api/{session}/chats/{chatId}/messages` after `POST /api/sendText`
returns — the two are different WAHA subsystems (send path vs. history
store), and nothing in this codebase has ever measured the gap between
them.

**Handling, per your constraint ("retry/backoff kecil hanya untuk
targeted reconciliation, bukan polling global")**: the new internal
endpoint (or the task it enqueues) runs a small bounded loop — call
`reconcile_session(session, chat_ids=[chat_id])`, inspect
`result.messages_inserted`; if it's `0`, wait a short fixed delay (e.g.
1.5s) and try again, up to e.g. 3 total attempts, stopping as soon as
`messages_inserted > 0`. This is **not** a new persistence path — every
attempt is a plain call to the existing `reconcile_session()`, which is
already idempotent (duplicate `Message` rows are rejected at the DB
constraint layer, `DuplicateMessage` is already handled) — so retrying it
blindly is safe by construction, not a new correctness risk.

This also means the fix does **not** need to distinguish "the message we
just sent" from any other message — `reconcile_session` for that one
chat will pick up *anything* new in it (including messages that arrived
from the other party in the same window), which is strictly more
correct, not a narrower/riskier check.

## 5. Confirms reconciliation already produces user-visible results

`GET /api/chats/:id/messages/` (`apps/chats/views.py::ChatMessagesView`)
reads directly from `chat.messages` with no source-distinguishing filter
— it has no way to know or care whether a given `Message` row was
inserted by a live webhook or by reconciliation. This is already proven
by `Message.id=23` (prior audit, Section 4): a reconciliation-inserted
outbound message already renders correctly today through this exact
endpoint and through `InboxPage.tsx`'s existing rendering, with zero
special-casing. So once the targeted reconciliation call successfully
inserts the row, the existing 5s poll makes it appear with no further
code needed.

## 6. Minimal implementation plan

1. `apps/sync/internal_views.py` (new): `ReconciliationTriggerView.post()`
   — validates `{session, chat_id}`, runs the bounded retry loop from
   Section 4 calling `reconcile_session(session, chat_ids=[chat_id])`,
   returns a small JSON status (`{triggered: true, messages_inserted: N}`)
   — the BFF ignores this response either way (fire-and-forget), but
   returning something concrete keeps the endpoint testable in isolation.
2. Wire it under `internal/reconciliation/trigger/` (`apps/sync/urls.py` +
   `config/urls.py`), same `HasInternalServiceKey` permission as the
   existing internal endpoints.
3. `bff/src/djangoClient.ts`: add `triggerReconciliation()`, same shape
   as `writeAuditEvent()` (fire-and-forget already-established pattern:
   caller does not have to treat a failure here as fatal).
4. `bff/src/routes/messages.ts`: call it once, right after
   `finalStatus === 'sent'` is known — **not awaited** before
   `res.status(200).json(...)` (see Section 7 for why this matters more
   than it looks).
5. No `reconcile_session()` or `persist_message()` changes at all.

## 7. Open decision — needs your input before implementing

**Celery/Redis is not currently reachable from this manual dev
environment**, confirmed live, read-only, this task:
- `backend/.env`'s `CELERY_BROKER_URL` is still the Docker-Compose-style
  default, `redis://redis:6379/0` (`config/settings.py:177`'s own
  fallback value — `.env` has not overridden it for this dev topology).
- The hostname `redis` **does not resolve** on this dev PC (`nslookup
  redis` → `Non-existent domain`).
- **No `celery` worker process is currently running** on this machine
  (checked via process list).
- This project's test suite never actually exercises `.delay()` —
  `apps/sync/tests/test_tasks.py` calls the task function directly as
  plain Python, and no settings file sets
  `CELERY_TASK_ALWAYS_EAGER`. The only place `.delay()` is used for real
  is `reconcile_all_sessions_task` via Celery beat, which requires a
  running worker + reachable broker — infrastructure this project
  documents for the **Office deployment**
  (`infrastructure/office/`, per root `CLAUDE.md`'s scope list — celery +
  redis are Office-side, not part of the Tencent/BFF/WAHA side, and not
  currently running in this manual PC-dev session at all).

This means: **if the new Django endpoint enqueues via
`reconcile_session_task.delay(...)` (Option A), it will not visibly do
anything in your current manual dev testing** — the task would sit
unconsumed in a broker connection that doesn't even resolve. This isn't
a flaw in the design, just a fact about what's actually running on this
PC right now, and it would need Celery worker + Redis actually started
locally before you could see it work end-to-end.

Two ways to proceed — **please pick one**:

- **Option A — enqueue via Celery (`reconcile_session_task.delay(session,
  chat_ids=[chat_id])`)**. Architecturally matches how this project's
  only other background job already works, and is what the real Office
  deployment would use. Retry/backoff (Section 4) would live *inside* the
  task, using `self.retry(countdown=...)` the same way
  `reconcile_session_task` already does for transient exceptions
  (`apps/sync/tasks.py:32-39`), except triggered by "0 messages inserted
  yet" rather than by a raised exception. **Requires you to actually
  start a Celery worker (and have Redis reachable) in this dev
  environment before you can verify the fix live** — out of scope for
  this design check to set up.
- **Option B — run `reconcile_session()` synchronously inside the new
  Django internal endpoint**, with the same small retry loop, no Celery
  involved at all. Works immediately in the current manual dev setup
  with zero new infrastructure. The BFF still satisfies "don't make the
  frontend wait" because the BFF does not `await` this call before
  responding — Node's fetch simply keeps running in the background after
  `res.json()` has already been sent (a standard, already-idiomatic
  fire-and-forget in this codebase's own style — see
  `logAuditFallback`'s "audit-after-resolution... emitted
  unconditionally" comment for the same non-blocking philosophy applied
  elsewhere). The tradeoff: this Django request thread is blocked for up
  to ~3 x (WAHA round-trip + backoff delay) seconds, which is fine at
  today's message volume but is a real, if small, worker-thread cost
  under Django's synchronous WSGI/gunicorn serving model
  (`backend/Dockerfile`'s `CMD ["gunicorn", ...]`) — something to
  monitor if send volume grows, not a correctness issue.

Given this project is still in manual, one-developer live testing and
you'll want to actually see this work today, **Option B is the
pragmatic recommendation** — it reuses 100% of the same
`reconcile_session()` call either way, and migrating it to Option A later
(once Office-side Celery/Redis is actually running) is a small, isolated
change (move the retry loop from the view into the task, change one
`fetch` call in `messages.ts` from "fire and forget on the sync
endpoint" to "fire and forget on the enqueue endpoint" — the BFF-side
code barely changes). But this is your call, not mine to decide
unilaterally — please confirm A or B before I implement anything.

## 8. Potential failure modes

- **WAHA REST history genuinely doesn't have the message yet even after
  3 retries** (slower backend-side propagation than expected) — the
  targeted reconciliation simply finds nothing this time; the *next*
  full/periodic reconciliation (whenever that next runs) will still pick
  it up eventually, exactly as it does today. No regression versus the
  current (broken) behavior — this is strictly additive.
- **The targeted call's session-wide `SyncCheckpoint` advance side
  effect**: `reconcile_session()` maintains **one checkpoint per
  session, not per chat** (`apps/sync/reconciliation.py:171-172`,
  `SyncCheckpoint.objects.get_or_create(session=session)`). A successful
  targeted run for one chat can advance the *session-wide*
  `checkpoint_value` to that chat's newest message timestamp. This is
  pre-existing behavior of `reconcile_session` (not something this
  fix introduces), but a **new, more frequent caller** (every confirmed
  send, versus only the periodic full-session job today) makes it worth
  restating: if chat A gets many targeted reconciliations advancing the
  global checkpoint forward while chat B has older, never-yet-fetched
  deep history, a later full-session run may fetch fewer back-pages for
  chat B than it would have otherwise (the per-chat page-1 fetch always
  still happens, so recent messages are never missed — only *very old,
  multi-page-deep* backlog completeness for quiet chats is the
  theoretical edge here). Flagged as a pre-existing design property being
  exercised more often, not a new bug — worth a one-line mention to you,
  not a blocker.
- **Django internal endpoint reachable from BFF but WAHA itself is down
  at trigger time**: `reconcile_session` already handles
  `WahaClientError` per-chat (`chat_fetch_errors`, `had_error=True`,
  checkpoint not advanced) — existing, already-tested behavior, nothing
  new to build.
- **BFF's fire-and-forget call itself fails (network/timeout) to
  Django**: no effect on the send flow (the frontend already got its
  `sent` response) — consistent with the "best-effort" philosophy every
  other `djangoClient.ts` call already documents.
- **Duplicate targeted triggers for the same chat in quick succession**
  (e.g. user sends two messages back-to-back before the first
  reconciliation finishes): safe — `reconcile_session` per chat is
  naturally idempotent/duplicate-safe by the existing DB constraint; two
  concurrent runs for the same chat would each just skip whatever the
  other already inserted (`DuplicateMessage`), not conflict destructively. Not evaluated for a full concurrency/locking analysis, since existing reconciliation already tolerates duplicate messages by design, and this project's job volume does not warrant one for this minimal fix.

## 9. Tests that should be added

- `apps/sync/test_internal_views` (new, mirroring
  `apps/operations/test_views.py`'s style): unauthenticated /
  wrong-service-key request → `403`; valid request with a known
  `session`+`chat_id` → triggers `reconcile_session` with exactly
  `chat_ids=[chat_id]` (mock/stub, no real WAHA call); unknown
  `session`/`chat_id` handled without a 500.
- A test proving the retry loop stops as soon as
  `messages_inserted > 0` (stub `WahaClient` returns nothing on attempt 1,
  one message on attempt 2 — assert only 2 calls were made, not 3).
- A test proving the loop gives up cleanly after the max attempts with
  no exception when WAHA genuinely has nothing new.
- BFF-side: a test on `messages.ts` proving the new call fires only when
  `finalStatus === 'sent'` (not on `failed`/`unknown`), and proving it
  does not delay `res.json(...)` (e.g. assert the response is sent before
  the mocked Django call's promise resolves).
- Full existing backend suite (254 tests) and BFF suite must stay green.
- One live, manual verification once implemented and approved: send one
  real outbound message from the Inbox composer and confirm it appears
  in history within a few seconds — reusing your already-planned real
  test, not an additional one.

---

Read-only design check complete. No code, database, config, or WAHA
session was changed. No WhatsApp message was sent. Waiting for your
decision on Section 7 (Option A vs. B) before implementing anything.
