# Reconciliation Trigger Not Firing — Root Cause Audit (Read-Only)

Follow-up to
[`INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md`](INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md).
Live manual test still shows the outbound message missing from Inbox
after that fix. **Read-only audit** — no code, config, `.env`, database,
migration, or WAHA session was changed; no WhatsApp message was sent;
only `GET`/read-only WAHA calls and read-only DB queries were used.

## Executive summary

**Root cause is CONFIRMED and it is not in the reconciliation logic at
all.** The BFF's own `.env` has `DJANGO_INTERNAL_BASE_URL` and
`INTERNAL_SERVICE_KEY` both present as keys but **empty**. Every
BFF→Django internal call — including the new `triggerReconciliation()`
— short-circuits to a silent no-op *before any HTTP request is ever
attempted*, inside `djangoClient.ts::postJson()`'s own existing guard
clause. This is a pre-existing environment configuration gap, not a bug
in the reconciliation-trigger implementation, and it has been silently
degrading **every** internal BFF→Django call (not just this new one)
since this feature was built — proven below by zero rows, ever, in two
unrelated Django tables that should have been populated by ordinary
send-message usage.

## A. BFF send flow — traced in actual source

`bff/src/routes/messages.ts:125-136` (current live file, re-read this
task):
```ts
if (finalStatus === 'sent') {
    void triggerReconciliation({ session, chatId }, djangoCallOptions());
    res.status(200).json({ status: 'sent', providerMessageId });
    return;
}
```
- `session`/`chatId` are the exact same values already used for the
  `sendText` call two steps earlier (`session = req.params.session`,
  `chatId` destructured from the request body) — no transformation, no
  mismatch possible here.
- `triggerReconciliation()` **is called** unconditionally whenever
  `finalStatus === 'sent'`, confirming this line does execute for a
  successful send (matches the user's own observation that WhatsApp
  received the message).
- The call is `void`-prefixed (fire-and-forget), and its promise is never
  awaited, inspected, or logged — **any failure inside it is invisible
  at this call site by design** (this was intentional, per the approved
  design: "postJson() never throws, so no .catch() is needed" — true,
  but it also means a *silent no-op* looks identical to a *successful
  fire-and-forget dispatch* from this call site alone).

## B. Django internal endpoint — traced, and proven never reached

`bff/src/djangoClient.ts::postJson()` (the function `triggerReconciliation`
calls):
```ts
async function postJson<T>(path, body, options, method = 'POST') {
  if (!options.baseUrl || !options.serviceKey) {
    return { ok: false };
  }
  ...
}
```
**This is the actual failure point.** `options.baseUrl`/`options.serviceKey`
come from `djangoCallOptions()` → `config.djangoInternalBaseUrl` /
`config.internalServiceKey` → `bff/src/config.ts`:
```ts
djangoInternalBaseUrl: process.env.DJANGO_INTERNAL_BASE_URL ?? '',
internalServiceKey: process.env.INTERNAL_SERVICE_KEY ?? '',
```

Checked `bff/.env` directly (names-only / non-empty-only checks, no
secret values printed, per this project's standing convention):
```
DJANGO_INTERNAL_BASE_URL: EMPTY or missing value
INTERNAL_SERVICE_KEY:     EMPTY or missing value
```
Both keys exist in the file but have nothing after `=`. So at runtime,
`config.djangoInternalBaseUrl === ''` and `config.internalServiceKey === ''`
— `postJson()`'s guard clause is true, and it returns `{ ok: false }`
**without ever constructing a `fetch()` call**. `POST
/internal/reconciliation/trigger/` is never sent. This is not a network
failure, not a 403, not a 500 — it is Python/Node-level "never dialed the
phone."

**Proof this isn't new, and isn't specific to the reconciliation
endpoint**: `registerOutboundOperation()` and `resolveOutboundOperation()`
go through the exact same `postJson()` with the exact same
`djangoCallOptions()`. Read-only query against the real dev database:
```
apps.operations.models.OutboundOperation.objects.count() -> 0 rows, ever
apps.audit.models.AuditLog.objects.count()               -> 0 rows, ever
```
Every prior send (including the earlier outbound test messages already
sitting in the `Message` table via reconciliation, e.g. IDs 23/25-27)
has **always** silently skipped Django's idempotency bookkeeping and
audit logging — this is `messages.ts`'s own documented "proceeds to WAHA
when Django is unreachable" degradation path, which has apparently been
the *normal* path in this dev environment the whole time, not an
exceptional one. This confirms the gap predates and is unrelated to the
reconciliation-trigger implementation.

**On the Django side**: also checked `backend/.env`'s
`INTERNAL_SERVICE_KEY` — also empty. So even in a hypothetical world
where the BFF's guard clause didn't exist and it tried anyway,
`apps.core.internal_auth.HasInternalServiceKey` fails closed on an
unconfigured secret and would reject with `403` regardless. Both sides
of this channel are simultaneously unconfigured.

## C. Executor — confirmed correct, and confirmed never invoked

```
$ python manage.py shell -c "from django.conf import settings; print(settings.RECONCILIATION_EXECUTOR)"
sync
```
`RECONCILIATION_EXECUTOR` does resolve to `'sync'` as intended for this
dev environment (default, unset in `.env` — no misconfiguration here).
No Celery involvement is possible or occurring (re-confirmed: no
`celery` process running, `redis` hostname still doesn't resolve on this
PC — unchanged from the prior design check).

However, this is moot for the actual failure: `trigger_reconciliation()`
(and therefore `run_targeted_reconciliation_with_retry()` /
`reconcile_session()`) is a **Python function that only exists inside
Django** — it cannot run at all unless Django's HTTP endpoint is hit
first. Since B proved the request never leaves the BFF process, none of
this Django-side code ever executes. No exception is being swallowed
here — there is nothing to swallow, because nothing was called.

## D. Reconciliation — chat ID/identity check (no mismatch found)

The chat used throughout is consistently `168160971997355@lid`:
- Frontend sends `chatId: selectedChat.provider_chat_id` = `168160971997355@lid` to the BFF (unchanged from before this fix).
- The BFF forwards the identical string as both `chatId` to WAHA's `sendText` and (intended to be) `chat_id` to the reconciliation trigger.
- WAHA's own REST history (Section E) uses that exact same identifier.
- Django's `Chat` row (id=3) has `provider_chat_id = '168160971997355@lid'`.

No `@lid`/`@s.whatsapp.net`/`@c.us` mismatch anywhere in this path — this
is not an identity-fragmentation issue, consistent with your instruction
not to touch that area.

## E. WAHA history — read-only check, message confirmed available

`WahaClient().fetch_chat_messages('no_epahari', '168160971997355@lid', limit=5, offset=0)`
(the exact same call `reconcile_session()` already makes), read-only, no
send:
```
id=true_168160971997355@lid_3EB0E156F18ACB517C9E0A  fromMe=True  2026-09-24 15:44:12 UTC  "halo, test kirim pesan ya"
id=true_168160971997355@lid_3EB0769182CE79DEB4B864  fromMe=True  2026-09-24 15:43:20 UTC  "tes"
id=true_168160971997355@lid_3EB00F76E235ED66332493  fromMe=True  2026-09-24 14:59:21 UTC  "halo"
id=false_168160971997355@lid_2A067E1C5A265971BD44   fromMe=False 2026-09-24 14:59:01 UTC  "Cek ya"   <- already in DB as Message.id=44
id=true_168160971997355@lid_3EB0DED117477A61A1A8DF  fromMe=True  2026-09-24 14:44:41 UTC  "test"
```
**The outbound messages are already fully available in WAHA's REST
history** — confirmed, not a timing/race-condition problem. The newest
one (15:44:12 UTC) was already ~3 minutes old at the moment of this
check (this audit ran at 15:47:28 UTC), far beyond the 3-attempt/~4.5s
retry window the fix's retry loop uses. Had `reconcile_session()` ever
actually been called for this chat, it would have found and inserted
these on its very first attempt, no retries needed.

## F. Database — read-only query results

```
Message table: newest row is id=44 (inbound, 2026-09-24 14:59:01 UTC,
                "Cek ya") — nothing since. No outbound row exists for
                any of the 3 messages confirmed present in WAHA above.
SyncCheckpoint (session no_epahari): status=ok,
                last_run_at = 2026-09-24 14:04:25 UTC,
                checkpoint_value = 2026-09-24T13:28:12 UTC
```
`SyncCheckpoint.last_run_at` is set unconditionally by every single
`reconcile_session()` call, success or failure
(`apps/sync/reconciliation.py:233`, runs before the had_error branch).
It being frozen at **14:04:25 — over 1h40m before this audit, and before
every single one of today's message webhook events (14:44, 14:59) and
all of the outbound test sends (14:44-15:44)** — is direct, durable proof
that `reconcile_session()` has not executed even once since then, via
any path (not the new trigger, not the periodic Celery job, which is
independently confirmed not running).

## G. Frontend — not investigated further

Not needed: the root cause is fully explained upstream of anything the
frontend or `GET /api/chats/:id/messages/` could affect, since no
`Message` row was ever created for these outbound sends to begin with.
(For reference, the previous audit already proved this endpoint and the
frontend's rendering have no direction-based filtering, via the
pre-existing `Message.id=23`.)

## H. Timeline (reconstructed from DB/WAHA evidence — see limitations)

| Point | Evidence | Value |
|---|---|---|
| T0/T1 (send accepted by WAHA) | WAHA's own message timestamp | 2026-09-24 **15:44:12** UTC (newest outbound message) |
| T2 (`triggerReconciliation()` called in BFF) | Code trace (Section A) | ~same instant as T1 — executes synchronously right after `finalStatus==='sent'` |
| T3 (Django endpoint receives it) | **Never** — `postJson()` returns before any request is sent (Section B) | N/A |
| T4 (`reconcile_session()` starts) | **Never** — `SyncCheckpoint.last_run_at` frozen at 14:04:25 (Section F) | N/A |
| T5 (message visible via WAHA REST) | Confirmed already available (Section E) | ≤ 15:44:12, i.e. immediately |
| T6 (Message row inserted) | Never happened | N/A |
| T7 (frontend poll sees it) | Never happened | N/A |

**Limitation**: this task has no access to the live BFF or Django
processes' own console output (both are run manually by you, outside
this session's reach) — T0-T2 are inferred from WAHA's own recorded
message timestamp and the code path, not a captured log line saying
"trigger called." This does not weaken the conclusion (B/F's database
evidence is independent and durable), but it's the one gap in direct
observability worth naming.

## I. Conclusion

**CONFIRMED:**
1. `bff/.env` has `DJANGO_INTERNAL_BASE_URL=` and `INTERNAL_SERVICE_KEY=`
   both empty.
2. `djangoClient.ts::postJson()` returns `{ok:false}` without sending any
   HTTP request whenever either is empty — applies identically to
   `registerOutboundOperation`, `resolveOutboundOperation`,
   `writeAuditEvent`, and `triggerReconciliation`.
3. `OutboundOperation` and `AuditLog` have zero rows ever in the real dev
   database — proving this silent no-op predates and is independent of
   the reconciliation-trigger feature; it has affected every send made
   through this BFF so far.
4. `SyncCheckpoint.last_run_at` has not advanced since 14:04:25 UTC,
   proving `reconcile_session()` has not run via any path since then.
5. WAHA's REST history already contains the missing outbound messages,
   confirmed via a direct read-only fetch — there is no availability/race
   issue; reconciliation would succeed immediately if it ever ran.
6. No chat-ID/identity mismatch exists anywhere in this path.
7. `RECONCILIATION_EXECUTOR` correctly resolves to `sync` in this
   environment — the executor selection itself is not implicated.

**LIKELY:**
- This configuration gap predates this task's implementation entirely
  (it explains OutboundOperation/AuditLog being empty since inception,
  not just the new trigger) — inferred from the DB evidence, not from
  seeing when the `.env` lines were added.

**NOT PROVEN:**
- Whether the live BFF process is actually running the latest edited
  code at all (vs. a stale process) — moot to the root cause either way
  (even correct code hits the same empty-config no-op), but not
  independently confirmed from this session, since no access to that
  process's console exists.
- Exact BFF-side wall-clock timestamps for T0-T2 (inferred, not
  directly logged — see Section H's limitation note).

## Recommended minimal fix (NOT implemented — audit only)

Purely a **configuration** fix, no source code change:

1. Set a real, non-empty `DJANGO_INTERNAL_BASE_URL` in `bff/.env` —
   per your confirmed dev topology, `http://192.168.100.200:8000`.
2. Generate a fresh shared secret and set it as `INTERNAL_SERVICE_KEY` in
   **both** `bff/.env` and `backend/.env` with the **identical** value
   (same pattern already used for `WAHA_WEBHOOK_HMAC_SECRET` earlier this
   session — `secrets.token_hex(32)` or equivalent).
3. Restart **both** the BFF (`npm run dev`) and Django
   (`python manage.py runserver`) processes — both `bff/src/config.ts`
   and `backend/config/settings.py` only read `.env` once, at process
   startup.
4. Re-test: send one message from the Inbox composer and confirm it
   appears in history within a few seconds. This single fix should also
   retroactively make `OutboundOperation`/`AuditLog` start being
   populated for ordinary sends, not just the reconciliation trigger —
   worth checking as a bonus confirmation signal.

No reconciliation/persistence/identity code needs to change — Section D
confirms there is no chat-ID mismatch, and Section E confirms
`reconcile_session()` would succeed immediately (no retry-timing issue)
once it actually gets called.

---

No code, config, `.env`, database, or WAHA session was changed during
this audit. No WhatsApp message was sent. Not implementing any fix, not
proceeding to Phase 9 or any other task — stopping here as instructed.
