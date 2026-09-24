# Targeted Reconciliation Trigger — Implementation Report

Implements the approved fix from
[`INBOX-OUTBOUND-MESSAGE-MISSING-AUDIT-REPORT.md`](INBOX-OUTBOUND-MESSAGE-MISSING-AUDIT-REPORT.md)
and
[`INBOX-OUTBOUND-RECONCILIATION-TRIGGER-DESIGN-CHECK.md`](INBOX-OUTBOUND-RECONCILIATION-TRIGGER-DESIGN-CHECK.md),
built to the **same-source-code, executor-swaps-by-config** design you
specified. No ambiguity blocked implementation, so this went straight to
code per your instruction ("Jika design sudah cukup jelas,
implementasikan langsung").

## 1. Root cause (recap)

This WAHA deployment sends no webhook for self-sent (outbound) messages.
WhatsApp/WAHA accepts and delivers the send correctly, but Django never
receives a `message` event for it, so no `Message` row is ever created —
the Inbox has nothing to show until the next full/periodic
reconciliation reads it from WAHA's REST history. Full detail and
evidence in the audit report linked above.

## 2. Existing architecture found (re-confirmed this task)

- `apps.sync.reconciliation.reconcile_session(session_name, chat_ids=None, ...)`
  already supports a targeted, single-(or-multi-)chat run — no change
  needed to it at all.
- `apps.sync.tasks.reconcile_session_task`/`reconcile_all_sessions_task`
  are the only existing Celery tasks; the periodic one is wired via
  `config/celery.py`'s `add_periodic_task`.
- `apps.core.internal_auth.HasInternalServiceKey` + the `internal/` URL
  prefix (`config/urls.py`) is the established BFF↔Django trust boundary,
  already used by `apps.operations` (outbound-operation idempotency) and
  `apps.audit`.
- `bff/src/djangoClient.ts` already has the established fire-and-forget
  pattern for best-effort BFF→Django calls (`writeAuditEvent`, etc.) —
  callers never treat a failure here as fatal.
- **Celery/Redis confirmed NOT reachable in this manual dev
  environment** (re-confirmed from the design check): `CELERY_BROKER_URL`
  in `.env` is still the Docker-Compose default `redis://redis:6379/0`,
  that hostname doesn't resolve on this dev PC, and no worker process is
  running. However, this project's own test suite already has a proven
  way to exercise Celery tasks with zero real broker —
  `@override_settings(CELERY_TASK_ALWAYS_EAGER=True,
  CELERY_TASK_EAGER_PROPAGATES=True)` (used throughout
  `apps/sync/tests/test_tasks.py`) — so the `celery` executor path is
  fully unit-testable today despite the environment gap.
- No existing "environment mode" or "executor" config pattern existed to
  copy — `RECONCILIATION_EXECUTOR` is a new, narrowly-scoped setting, not
  a rename of something already established.

## 3. Design final

**One dispatcher function, `apps.sync.executors.trigger_reconciliation(session_name,
chat_id)`, selects the executor by reading `settings.RECONCILIATION_EXECUTOR`
at call time.** Both executors call the exact same
`reconcile_session()` — nothing about *what* runs ever differs, only
*where*:

```
BFF (unchanged contract, one new fire-and-forget call)
  routes/messages.ts: finalStatus === 'sent'
    -> void triggerReconciliation({session, chatId}, djangoCallOptions())   [NOT awaited]
    -> res.json({status:'sent', providerMessageId})                        [unchanged timing]

Django: POST /internal/reconciliation/trigger/  (HasInternalServiceKey)
  -> apps.sync.executors.trigger_reconciliation(session, chat_id)
       RECONCILIATION_EXECUTOR == 'sync'   -> run_targeted_reconciliation_with_retry() IN-PROCESS
       RECONCILIATION_EXECUTOR == 'celery' -> reconcile_chat_task.delay(session, chat_id)
                                                 -> (Celery worker) run_targeted_reconciliation_with_retry()
       (anything else)                     -> raise ImproperlyConfigured (also fails Django startup)

run_targeted_reconciliation_with_retry(session_name, chat_id):
    up to 3x: reconcile_session(session_name, chat_ids=[chat_id])
    stop as soon as messages_inserted > 0, else short sleep and retry
```

`run_targeted_reconciliation_with_retry()` is the **one** shared
implementation of "reconcile this chat, tolerating WAHA's REST-history
lag" — called directly by the `sync` path, and from inside the new
`reconcile_chat_task` for the `celery` path. Neither executor duplicates
reconciliation/persistence logic; both are thin callers of existing or
newly-shared logic.

## 4. Executor abstraction

`backend/apps/sync/executors.py` (new, ~90 lines):
- `run_targeted_reconciliation_with_retry(session_name, chat_id, waha_client=None)`
  — the bounded retry loop (`MAX_ATTEMPTS = 3`, `RETRY_DELAY_SECONDS = 1.5`),
  calling `reconcile_session(session_name, chat_ids=[chat_id])` and
  stopping as soon as `result.messages_inserted > 0`. Every attempt is a
  plain call to the existing, already-tested `reconcile_session()` — safe
  to repeat, since it's already duplicate-safe at the DB constraint
  layer.
- `trigger_reconciliation(session_name, chat_id)` — the dispatcher.
  Returns the `ReconciliationResult` for `sync` (caller has it
  immediately), or `None` for `celery` (already enqueued, no result yet).
  Raises `ImproperlyConfigured` for anything else — **never** silently
  falls back to `sync`.

## 5. Development behavior

`RECONCILIATION_EXECUTOR` unset (or explicitly `sync`, the default):
1. BFF fires `POST /internal/reconciliation/trigger/` after a confirmed
   `sent` outcome, without awaiting it.
2. Django's `ReconciliationTriggerView` runs
   `run_targeted_reconciliation_with_retry()` **in the same request**,
   inline — no Celery, no Redis. Up to ~3 x (WAHA round-trip + 1.5s
   backoff) seconds before that endpoint's own response returns — this
   is fine, because nothing is waiting on it (Section 3).
3. Once `reconcile_session()` inserts the message, it's an ordinary
   `Message` row — the existing `GET /api/chats/:id/messages/` and the
   Inbox's existing 5s poll pick it up with zero further code, exactly as
   proven by the pre-existing `Message.id=23` (reconciliation-inserted
   outbound message, audit report Section 4).

## 6. Production behavior

`RECONCILIATION_EXECUTOR=celery`:
1. Same BFF call, same contract, same fire-and-forget — **zero BFF code
   difference** between environments.
2. Django's `ReconciliationTriggerView` calls
   `reconcile_chat_task.delay(session, chat_id)` and returns immediately
   (`202`, not awaited for a result) — the retry loop then runs inside a
   Celery worker process, using the Office deployment's already-running
   Redis broker (`infrastructure/office/`).
3. Same `reconcile_session()`, same `Message` row, same existing
   Inbox-read path picks it up — identical end state to Section 5, only
   the execution location differs.

## 7. Configuration required

New environment variable, `backend/.env` / `backend/.env.example`:

| Value | Meaning | Requires |
|---|---|---|
| `RECONCILIATION_EXECUTOR=sync` (default if unset) | In-process, inline | Nothing extra — works with today's manual dev setup |
| `RECONCILIATION_EXECUTOR=celery` | Enqueue via Celery | A running Celery worker with a reachable Redis broker (`CELERY_BROKER_URL`, already provisioned for the Office deployment) |

**Default value**: `sync` — chosen because it's what works with zero new
infrastructure, matching this project's current manual-dev reality; it
is not a "production default", it's a "no infra assumed" default.

**Invalid value behavior**: Django refuses to start at all —
`config/settings.py` raises `ImproperlyConfigured` immediately at import
time for any value other than `sync`/`celery`. This is the loudest
possible failure mode (the process never comes up), by design.

**`celery` selected but Celery/Redis unavailable**: **no silent
fallback to `sync`** (explicitly required — Section F of your request).
`reconcile_chat_task.delay(...)` will raise when it cannot reach the
broker; that exception propagates out of `ReconciliationTriggerView` and
is handled by this project's existing global DRF exception handler
(`apps.core.exceptions.api_exception_handler`) exactly like any other
unhandled error — a logged server error and a `500` response. The BFF's
fire-and-forget call simply discards that failure (same as any other
best-effort `djangoClient.ts` call failing) — the send flow itself is
unaffected either way, but the reconciliation genuinely does not happen
and is visible in Django's own error log, not hidden.

## 8. Files changed

**Backend:**
```
backend/config/settings.py            RECONCILIATION_EXECUTOR setting + startup validation
backend/.env.example                  documents the new variable
backend/apps/sync/executors.py        NEW — dispatcher + shared retry helper
backend/apps/sync/tasks.py            + reconcile_chat_task (thin, calls the shared helper)
backend/apps/sync/internal_views.py   NEW — POST /internal/reconciliation/trigger/
backend/apps/sync/urls.py             NEW
backend/config/urls.py                + internal/ include for apps.sync
backend/apps/sync/tests/test_executors.py       NEW
backend/apps/sync/tests/test_internal_views.py  NEW
backend/apps/sync/tests/test_tasks.py           + ReconcileChatTaskTests
```

**BFF:**
```
bff/src/djangoClient.ts        + triggerReconciliation()
bff/src/routes/messages.ts     + one fire-and-forget call after finalStatus === 'sent'
bff/test/routes.messages.test.ts  + 5 new tests (reconciliation trigger describe block)
```

**Not touched** (verified via `git status` before/after): `apps/webhooks/*`,
`apps/chats/*` (no API contract change), `InboxPage.tsx`/any frontend
file, Session Management, any `@lid`/identity code, `status@broadcast`,
`apps/webhooks/authentication.py` (webhook HMAC), Phase 9.

## 9. Tests

**Backend** — `DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test`:
```
Ran 272 tests in 11.072s
OK
```
(254 pre-existing + 18 new: 9 in `test_executors.py`, 2 in
`test_tasks.py::ReconcileChatTaskTests`, 7 in `test_internal_views.py`.)

Coverage highlights:
- Retry loop stops as soon as a message is found (1 call when found
  immediately, up to 3 when it takes longer) — via a small dedicated
  stub client, `time.sleep` mocked so tests run in milliseconds.
- Retry loop gives up cleanly (no exception) after 3 attempts with
  nothing found.
- Repeated attempts never insert a duplicate `Message` (idempotency
  preserved under retry).
- `sync` executor dispatches to the retry helper and never enqueues a
  Celery task; `celery` executor enqueues `reconcile_chat_task.delay()`
  and never runs reconciliation synchronously.
- An invalid `RECONCILIATION_EXECUTOR` raises `ImproperlyConfigured`
  (tested via `override_settings`, bypassing the startup-time check to
  prove the dispatcher's own defense-in-depth check).
- `reconcile_chat_task` (Celery, run under
  `CELERY_TASK_ALWAYS_EAGER=True` — no real broker needed) delegates to,
  and does not duplicate, the shared retry helper; an integration-style
  test proves it actually persists a `Message` via a stubbed `WahaClient`.
- Internal endpoint: `403` without/with wrong `X-Internal-Service-Key`;
  `400` for missing `session`/`chat_id`; dispatches with exactly the
  given `(session, chat_id)`; `200` + `executor: 'sync'` with a result
  body, or `202` + `executor: 'celery'` with no result; an end-to-end
  test with a stubbed WAHA client proves a real `Message` gets inserted
  through the full endpoint→dispatcher→retry-loop→reconcile_session path.

`python manage.py check` → clean. `makemigrations --check --dry-run` →
`No changes detected` (no model changes this task).

**One issue caught and fixed during this task**: an early draft of
`test_does_not_enqueue_a_celery_task` did not stub `WahaClient`, which
meant it constructed a **real** `WahaClient()` from the real dev `.env`
values and made 3 real HTTP requests to the live WAHA instance at
`100.124.162.223:3000` (visible as real `HTTP 422` responses and ~5s
real network gaps in the test run's own log output) before its retry
loop gave up. This was caught by noticing the test suite's total runtime
jump to 15.5s; fixed by mocking `apps.sync.executors.reconcile_session`
directly (same pattern already used by the sibling `celery`-executor
test) so no real `WahaClient` is ever constructed. Re-run: full
`apps.sync` suite in 0.336s, full backend suite in 11.072s. No WhatsApp
message was sent by this (the accidental calls were read-only chat
history `GET` requests, not sends), but it's called out here in full
per this project's "no live WAHA calls in tests" expectation, since it
did happen briefly during development of this fix.

**BFF** — `npm test`:
```
Test Files  10 passed (10)
     Tests  104 passed (104)
```
New tests (5, in `routes.messages.test.ts`'s new `describe('reconciliation
trigger (fire-and-forget)')` block):
- Trigger fires with `{session, chat_id}` matching the request, only
  after a confirmed `sent` outcome.
- Does **not** fire on a `failed` (WAHA error) outcome.
- Does **not** fire on an `unknown` (timeout) outcome.
- The send response is not delayed even when the trigger call's promise
  **never resolves** (proves true fire-and-forget, not a disguised
  blocking call).
- A failed/unreachable trigger call has no effect on the send response.

`npm run typecheck` → clean. `npm run build` → clean.

## 10. Production / deployment steps

1. In the Office deployment's environment configuration, set
   `RECONCILIATION_EXECUTOR=celery` (alongside the `CELERY_BROKER_URL`/
   `CELERY_RESULT_BACKEND` values that infrastructure already sets for
   the periodic reconciliation job — no new infrastructure to provision).
2. Nothing else — no code change, no new migration, no new dependency.
3. Verify (once deployed) that a real outbound send there is followed by
   a `reconcile_chat_task` entry in Celery's own logs/monitoring, same as
   how `reconcile_session_task`/`reconcile_all_sessions_task` are already
   observed today.

## 11. Does DEV → production require a source-code change?

**No.** The only difference is the value of one environment variable,
`RECONCILIATION_EXECUTOR` (`sync` in dev, `celery` in production). Every
file in Section 8 ships identically to both environments. This was the
explicit goal ("SAME SOURCE CODE... Perbedaan deployment cukup melalui
infrastructure + configuration") and is mechanically enforced by
`trigger_reconciliation()` being the single place that branches on the
setting — no `if settings.DEBUG` / `if environment == 'production'` /
hardcoded hostname anywhere in this change (confirmed by re-reading every
new/changed file for this task).

## 12. Risks / known limitations

- **`sync` executor ties up a Django request-handling thread for the
  duration of the retry loop** (up to ~3 x WAHA round-trip + backoff,
  a few seconds worst case). Acceptable at today's message volume
  (manual, single-developer testing); would need revisiting only if dev
  send volume grows substantially before switching to `celery` — not a
  correctness issue, a throughput one.
- **Session-wide `SyncCheckpoint` advancement** (pre-existing property of
  `reconcile_session()`, not introduced by this change, re-flagged from
  the design check): a successful targeted run can advance the
  session-wide checkpoint watermark based on just that one chat's newest
  message. This fix makes that a more frequent occurrence (every
  confirmed send, not just the periodic full-session job). The per-chat
  first page is always still fetched regardless, so recent messages are
  never missed — only very old, multi-page-deep backlog completeness for
  otherwise-quiet chats is the theoretical edge case. Not addressed here
  (would require changing `reconcile_session`'s checkpoint model, out of
  this fix's scope).
- **The retry loop cannot distinguish "the exact message we just sent"
  from any other new activity in the same chat** — by design (Section 4
  of the design check): it treats "any new message in this chat"
  as success, which is strictly more correct, not a narrower risk, but
  worth remembering if a future feature ever needs message-level
  confirmation of a specific send.
- **`celery` executor is not exercised against a real broker in this
  project's test suite** (by design — Celery's `ALWAYS_EAGER` mode is
  used instead, matching the existing convention for
  `reconcile_session_task`). The real, networked `celery` path has not
  been live-verified in this task, since no Celery worker/Redis is
  running in this dev environment; the same is already true of every
  other existing Celery task in this project.
- **No live, real send was tested end-to-end in this task** — per
  instruction, no outbound WhatsApp message was sent during this work.
  A live verification (send one real message from the Inbox composer,
  confirm it appears within a few seconds) is still outstanding and
  should be your next manual step, whenever you're ready.

---

No WhatsApp message was sent during this task. Session Management,
Inbox UI, `@lid`/identity resolution, `status@broadcast`, webhook HMAC
behavior, and the send-message request/response contract were not
touched. Not proceeding to Phase 9 or any other task automatically —
stopping here as instructed.
