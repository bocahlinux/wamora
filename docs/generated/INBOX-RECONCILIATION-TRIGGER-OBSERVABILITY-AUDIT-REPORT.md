# Reconciliation Trigger — Observability Audit & Diagnostic Logging

Follow-up to
[`INBOX-RECONCILIATION-TRIGGER-STILL-NOT-FIRING-AUDIT-REPORT.md`](INBOX-RECONCILIATION-TRIGGER-STILL-NOT-FIRING-AUDIT-REPORT.md).
That audit ruled out every cause checkable from outside the live
processes (config, network, WAHA availability, chat-ID identity) and
concluded the remaining failure is invisible because `djangoClient.ts`'s
`postJson()` collapses every outcome — missing config, a thrown
exception, and a non-2xx Django response — into the same silent
`{ok:false}`, logged nowhere. **This task adds the minimal diagnostic
logging needed to make that outcome observable**, per your explicit
authorization to do so (Section 3/4 of your instructions). No behavior,
architecture, endpoint, database schema, or WAHA state was changed, and
no WhatsApp message was sent.

## What was added

**`bff/src/djangoClient.ts`** — `postJson()` (the single function behind
every BFF→Django internal call: register/resolve outbound operation,
audit-event write, and the reconciliation trigger) now logs, on every
call, one line per phase:
1. **Before the request**: `[djangoClient] -> POST <url> (X-Internal-Service-Key
   attached, length=64)` — or, if config is missing, `[djangoClient]
   skipped POST <path>: DJANGO_INTERNAL_BASE_URL not configured` (or
   `INTERNAL_SERVICE_KEY not configured`), naming exactly which value is
   empty, and never attempting `fetch()` at all in that case.
2. **After a response arrives**: `[djangoClient] <- POST <url>
   status=<code>` — and, if the status is non-2xx, the Django error
   envelope's `code`/`request_id` (from `apps.core.exceptions.api_exception_handler`'s
   shape) appended, e.g. `status=403 code=permission_denied request_id=abc123`.
3. **If `fetch()` throws**: `[djangoClient] x  POST <url> threw
   <ErrorName>: <message>` — e.g. `threw TypeError: fetch failed` or a
   Node network error's name/message (`ECONNREFUSED`, `AbortError`, etc.).

**Never logged, anywhere**: `options.serviceKey`'s value (only its
*length* is logged, confirming it was attached without revealing it),
any JWT, and the request/response **body** (which could carry a chat ID
or send-result data) — only method, path, host, HTTP status, and the
error envelope's non-sensitive `code`/`request_id` fields.

**`bff/src/routes/messages.ts`** — the fire-and-forget trigger call gained
a `.then()` (not `await`) that logs a warning line,
`[messages] reconciliation trigger did not complete for
session=<session> chatId=<chatId>`, whenever the result resolves to
`{ok:false}`. This does **not** change the fire-and-forget timing — the
response to the frontend is still sent immediately, unchanged; the
`.then()` callback only runs after that response has already gone out.

**Tests** — `bff/test/djangoClient.test.ts` (new, 6 tests) proves each
logging branch fires correctly and that the secret value itself never
appears in any logged line; `bff/test/auditHelper.test.ts` (2 existing
tests) updated to count only audit-JSON log lines instead of the total
`console.log` call count, since that count legitimately increased by
design.

**Verification**: `npm test` → 110/110 passing (104 pre-existing + 6
new). `npm run typecheck` → clean. `npm run build` → clean.

## Answering your 6 questions — what this enables, and what still needs your live test

This task's logging was verified correct via **unit tests with a mocked
`fetch`** (Section above) — it was **not** exercised against your live
processes, because doing so would require either sending a real message
(forbidden) or invoking the reconciliation-trigger endpoint directly,
which performs real writes (`reconcile_session()` can insert `Message`
rows) — per your own instruction 5, that requires your explicit
approval, which this task did not seek. So the honest answer to each
question is: **the code path is now provably correct and will log the
answer live**, but the *actual* live values (A-F below) are not yet
captured — they will appear in your BFF terminal the next time you send
a message from the Inbox composer.

| Question | Answered by this task's logging |
|---|---|
| A. Does the BFF actually call `fetch()`? | Yes, proven by unit test — and now you'll see `[djangoClient] -> POST ...` in your BFF console the instant it happens (or `skipped ...` naming the missing var, if config were ever unset again). |
| B. Does fetch succeed or throw? | You'll see either `<- POST ... status=NNN` (succeeded, got a response) or `x  POST ... threw <Name>: <message>` (threw before getting a response — e.g. `ECONNREFUSED`, `ENOTFOUND`, `AbortError` for a timeout). |
| C. If it succeeds, what HTTP status? | Logged directly: `status=200`/`202` (Django accepted it) or `status=403`/`400`/`500` (Django rejected it) — plus, for a rejection, the error envelope's `code` (e.g. `code=permission_denied` for an auth mismatch, `code=invalid` for a validation error). |
| D. Does the request reach Django? | Distinguished directly now: a `threw` line means it never reached Django (network/DNS/timeout); a `status=` line of any kind means it did reach Django and got a real HTTP response. |
| E. If it reaches Django, why no `OutboundOperation`/`AuditLog`/`SyncCheckpoint`? | If you see `status=403`, that's your answer (`HasInternalServiceKey` rejected it before the view body ran — despite the file-level key match found previously, meaning the *live* Django process's in-memory value differs from the file, which would itself be a new, separate finding). If you see `status=200`/`202` but the DB still doesn't change, that would point at a bug inside `trigger_reconciliation()`/`reconcile_session()` itself, not the network layer — a different investigation than this one. |
| F. If it doesn't reach Django, what's the actual fetch error? | Logged verbatim (name + message) — no more guessing between "DNS," "connection refused," "timeout," or something else. |

## What was deliberately NOT done

- **No live invocation of `/internal/reconciliation/trigger/`** (or any
  other internal endpoint) was made — per your instruction 5, since it
  performs real writes and you did not pre-approve a live call.
- **No fix for the underlying failure** was implemented — the actual
  root cause (why the request fails once it's attempted) is still
  unknown; this task only removed the blindfold.
- **No behavior change**: response timing, the fire-and-forget contract,
  the executor dispatch, `reconcile_session()`, the database schema, and
  the send-message request/response contract are all byte-for-byte
  unchanged — confirmed by the full existing test suite (104 pre-existing
  tests) still passing unmodified except for the two count-based
  assertions that had to loosen to accommodate the new, expected log
  lines (their actual intent — "the audit fallback line is emitted" — is
  unchanged and still verified).
- **Not touched**: Inbox UI, `@lid`/identity resolution, `status@broadcast`,
  Session Management, `sendText` behavior, WAHA configuration, database
  schema, production architecture, Phase 9 (confirmed via `git status` —
  this task's diff is exactly `bff/src/djangoClient.ts`,
  `bff/src/routes/messages.ts`, `bff/test/auditHelper.test.ts`, and the
  new `bff/test/djangoClient.test.ts`).

## Next step (yours)

Send one message from the Inbox composer while watching the BFF's
terminal. You should see, within the same second, either:
- `[djangoClient] -> POST http://192.168.100.200:8000/internal/reconciliation/trigger/ (X-Internal-Service-Key attached, length=64)`
  followed by a `<- POST ... status=...` line (tells you C/D/E directly), or
- an `x  POST ... threw ...` line (tells you F directly), or
- a `skipped ...` line (would mean config is empty again, contradicting
  the previous audit's findings — worth re-checking if you see this).

Paste that line (or its absence) back and the next step can target the
exact failure it reveals, instead of continuing to audit blind.

---

No source behavior, `.env`, database, or WAHA session was changed. No
WhatsApp message was sent. No write-performing endpoint was invoked live.
Not proceeding to Phase 9 or any other task — stopping here as instructed.
