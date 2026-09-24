# Reconciliation Trigger Still Not Firing — Second Root Cause Audit (Read-Only)

Follow-up to
[`INBOX-RECONCILIATION-TRIGGER-NOT-FIRING-AUDIT-REPORT.md`](INBOX-RECONCILIATION-TRIGGER-NOT-FIRING-AUDIT-REPORT.md).
You filled in `DJANGO_INTERNAL_BASE_URL`/`INTERNAL_SERVICE_KEY` on both
sides and restarted both processes, but the outbound message still does
not appear in the Inbox. **Read-only audit** — no code, config, `.env`,
database, or WAHA session was changed; no WhatsApp message was sent;
only `GET` requests (to WAHA and to Django's public, no-auth health
endpoint) and read-only DB/file queries were used.

## 1. Exact failure point

**Last proven-successful point**: the BFF resolves `finalStatus === 'sent'`
and calls `triggerReconciliation({session, chatId}, ...)` — proven by
the message genuinely reaching WhatsApp and the composer's confirmation
UI, exactly as before.

**First proven-failed point**: **Django's `/internal/reconciliation/trigger/`
endpoint is never actually reached** — proven by zero new
`OutboundOperation`, `AuditLog`, or `SyncCheckpoint` activity across
three fresh outbound test sends made *after* the config fix and process
restarts.

**What changed since the last audit, and what didn't**: the previously-confirmed
cause (empty config) is now genuinely fixed — verified below. Despite
that, the symptom is identical. This means a **second, different**
failure exists somewhere inside the BFF process's actual `fetch()` call
or Django's request handling for that call — and this audit's honest
conclusion is that **the exact sub-step cannot be pinned down further
from outside the live processes**, because the current implementation
has no logging at that call site at all (Section 4 explains why, and
Section 5 recommends fixing that observability gap). Everything checkable
from outside has been checked and ruled out (Section 2).

## 2. Evidence

**Config is now genuinely non-empty and matching (re-verified this task,
values never printed):**
- `bff/.env`: `DJANGO_INTERNAL_BASE_URL=http://192.168.100.200:8000` (shown — not a secret), `INTERNAL_SERVICE_KEY` present, 64 characters.
- `backend/.env`: `INTERNAL_SERVICE_KEY` present, 64 characters.
- Direct byte-for-byte comparison of the two `INTERNAL_SERVICE_KEY` values (read into memory, compared for equality, **never printed**): **MATCH**.
- Django's own loaded `settings.INTERNAL_SERVICE_KEY` (via `manage.py shell`, a fresh process reading the same `.env`): also 64 characters — consistent with the file.
- `bff/.env` line for `DJANGO_INTERNAL_BASE_URL` has a plain LF ending, no stray `\r`/whitespace (checked with `cat -A`) — rules out a URL-construction parsing glitch for that specific value.

**The live, actually-listening processes are the freshly-restarted ones
(not stale):**
| Port | Component | PID | Process start time | `.env` last modified |
|---|---|---|---|---|
| 8080 | BFF (node) | 67752 | 2026-09-24 22:51:24 local | `bff/.env`: 22:51:04 (20s earlier) |
| 8000 | Django (python) | 68792 | 2026-09-24 22:53:35 local | `backend/.env`: 22:53:24 (11s earlier) |

Confirmed via `Get-NetTCPConnection -State Listen` → PID → `Get-Process`
StartTime. Both live processes started **after** their respective
`.env` edits — a genuine restart happened, not a stale process still
serving old config.

**Network path is fine:**
```
GET http://192.168.100.200:8000/api/health/  -> HTTP 200, 2ms
GET http://127.0.0.1:8000/api/health/        -> HTTP 200, 2ms
```
The exact host:port the BFF is configured to call is reachable,
fast, and correctly serving Django — from this machine, the same
machine the BFF runs on.

**Frontend targets the same live BFF**: `frontend/.env`'s
`VITE_BFF_BASE_URL=http://localhost:8080` matches the port the live,
freshly-restarted BFF process (PID 67752) is actually bound to.

**Despite all of the above, the internal channel shows zero activity,
across three fresh outbound sends made after the fix:**
```
OutboundOperation.objects.count() = 0   (still, unchanged)
AuditLog.objects.count()          = 0   (still, unchanged)
SyncCheckpoint.last_run_at        = 2026-09-24 14:04:25 UTC (still frozen — unchanged)
```
Read-only WAHA REST history (`fetch_chat_messages`, the same call
`reconcile_session()` uses) confirms three genuinely new outbound
messages exist and are fully available, sent well after the config fix:
```
15:51:51 UTC  "ini coba kirim lagi ya,"
15:53:50 UTC  "walah belum masuk juga pesannya di inbox"
15:56:31 UTC  "cek lagi deh ini ya"
```
None of these produced any Django-side trace whatsoever.

**Node has native `fetch`** (v24.18.0 — not a missing-global issue).

## 3. End-to-end trace

| Step | Component | Expected | Actual | Status |
|---|---|---|---|---|
| 1 | Frontend composer | POST to BFF with chatId/session | (assumed, unchanged from before) | Not independently re-verified this task, no reason to suspect it (unchanged code) |
| 2 | BFF: WAHA sendText | WAHA accepts, returns success | Confirmed — message reached WhatsApp (user-observed) and is present in WAHA REST history | ✅ Proven working |
| 3 | BFF: `finalStatus === 'sent'` | Reached | Reached (implied by successful send + confirmation UI, code path unconditional on success) | ✅ Proven working |
| 4 | BFF: `triggerReconciliation()` called | Called, fire-and-forget | Called (unconditional in code at this point) — but its outcome is invisible (no `.catch()`, no log) | ⚠️ Called, outcome unknown |
| 5 | BFF: config read (`baseUrl`/`serviceKey`) | Non-empty, matching | **Confirmed non-empty and matching** (Section 2) — previously the confirmed failure point, now fixed | ✅ Fixed this task |
| 6 | BFF: `fetch()` to Django | HTTP request sent | **Cannot confirm from outside** — network path itself is proven fine (Section 2), but whether *this specific process's fetch call* actually fires is unobservable without live console access | ❓ Not provable read-only |
| 7 | Django: `/internal/reconciliation/trigger/` receives request | Request logged/handled | **Zero evidence it was ever received** — no `OutboundOperation`/`AuditLog` row (same shared internal-endpoint pathway other calls use), no `SyncCheckpoint` update | ❌ No evidence of arrival |
| 8 | Django: `HasInternalServiceKey` passes | 200/202 | N/A — never reached this far provably | ❓ Unreachable to verify |
| 9 | Django: `trigger_reconciliation()` → `reconcile_session()` | Runs, calls WAHA REST | N/A | ❓ Unreachable to verify |
| 10 | WAHA REST history has the message | Yes | **Confirmed yes** — read-only fetch shows all 3 new outbound messages available immediately, no lag | ✅ Proven — not the bottleneck |
| 11 | Django `Message` row created | Yes | **No** — `Message` table has no outbound row past id=27 (2026-09-23); nothing for any of today's 3 new outbound tests | ❌ Confirmed not happening |
| 12 | `GET /api/chats/:id/messages/` returns it | N/A | N/A (nothing to return — no row exists) | Not applicable |
| 13 | Frontend 5s poll picks it up | N/A | N/A | Not applicable |

## 4. Root cause

**CONFIRMED (this task):**
1. The previously-confirmed cause (empty `DJANGO_INTERNAL_BASE_URL`/`INTERNAL_SERVICE_KEY`)
   is genuinely fixed: both values are present, non-empty, byte-identical
   between `bff/.env` and `backend/.env`, and loaded by processes that
   were demonstrably restarted after the edits and are the actual
   processes currently listening on the ports the frontend/BFF target.
2. The network path from the BFF's machine to
   `http://192.168.100.200:8000` works, is fast, and is not the
   bottleneck.
3. WAHA's REST history is not the bottleneck — the messages are fully
   available immediately, well within (and long after) the fix's 3-attempt
   retry window.
4. Despite 1-3, the internal channel still shows **zero** evidence of
   ever being used — for the new trigger endpoint **and** for the
   pre-existing `registerOutboundOperation`/`resolveOutboundOperation`
   calls, which share the exact same `postJson()` mechanism. This proves
   the remaining failure is generic to *any* BFF→Django internal call in
   the live process, not specific to the reconciliation-trigger feature.

**LIKELY:**
- The failure is occurring inside the live BFF process's actual
  `fetch()` call or in how Django's request pipeline handles it — but
  **which** (a thrown exception before the request is even sent, a
  connection-level failure specific to that process's runtime state, or
  an auth/permission rejection on Django's side that never creates a DB
  row because it's rejected before the view body runs) cannot be
  distinguished from outside, because:
  - `djangoClient.ts::postJson()` catches **any** error and returns
    `{ok:false}` uniformly — a thrown `TypeError`, a DNS failure, a
    connection refusal, and a timeout are all indistinguishable from
    each other at this call site, and none of them are logged anywhere.
  - `messages.ts`'s fire-and-forget call (`void triggerReconciliation(...)`)
    never inspects the result at all — by design (Section 3 of the
    original design check), so even a `{ok:false}` never surfaces.
  - Even a Django-side `403` (wrong/mismatched key, despite the file-level
    match found in Section 2 — e.g. if the *live* Django process somehow
    has a different in-memory value than the current file, which cannot
    be fully ruled out without reading that live process's own memory)
    would leave **zero** database trace, since `HasInternalServiceKey`
    rejects before the view's `post()` body (and therefore before any
    `OutboundOperation`/reconciliation write) ever runs — this would be
    visible only in Django's own live console (`django.request` WARNING:
    `Forbidden: /internal/reconciliation/trigger/`), which this audit has
    no access to.

**NOT PROVEN:**
- Whether the BFF's `fetch()` call is throwing before sending anything,
  being sent but rejected by Django (auth or otherwise), or something
  else entirely — this genuinely cannot be determined without either (a)
  you checking your own live BFF and Django terminal windows for any
  output logged at the moment of a test send (Django would print a
  `django.request` WARNING line for a `403`/`400` on this endpoint; the
  BFF currently prints nothing for this call either way, which is itself
  a finding — see Section 5), or (b) an explicitly-authorized live
  diagnostic call, which this audit's read-only scope did not extend to
  and which this task therefore did not perform.

## 5. Recommended minimal fix (NOT implemented)

Two independent, additive changes — both diagnostic/observability only,
no behavior change to the working parts:

1. **Add a `.catch()`/result-check to the fire-and-forget call in
   `bff/src/routes/messages.ts`** that logs a single warning line (e.g.
   via the existing `logAuditFallback`-style structured console log, or
   a plain `console.warn`) when `triggerReconciliation()` resolves with
   `{ok:false}`. This does not change the fire-and-forget *timing*
   (still not awaited before `res.json(...)`), it only makes an
   already-silent failure visible. This is the single highest-value
   change for actually diagnosing this specific problem, since right now
   there is no way — for you or for any future audit — to tell "never
   attempted" apart from "attempted and failed" apart from "succeeded."
2. **Ask you to reproduce one send while watching both the BFF and
   Django terminal windows live**, since that is the one piece of
   evidence this read-only, no-live-console audit genuinely cannot
   obtain on its own. Specifically look for:
   - BFF: any uncaught exception/stack trace printed around the time of
     the send (would indicate a bug in the fire-and-forget call itself,
     not a network issue).
   - Django: any `django.request` WARNING line mentioning
     `/internal/reconciliation/trigger/` (a `403` would confirm an
     auth/key issue despite the file-level match found here; total
     silence would confirm the request never arrives at all, pointing
     back at the BFF side).

Neither of these was implemented, per your instruction to audit only.

## 6. Production impact

Both recommended changes are dev-diagnostic in nature and executor-agnostic:
- The logging addition in `messages.ts` runs identically regardless of
  `RECONCILIATION_EXECUTOR` (it logs the *BFF-side* dispatch outcome, a
  layer entirely above the sync/celery executor split) — no divergence
  between development and production behavior would be introduced.
- Reproducing a live test is a one-time diagnostic action, not a
  deployment step.
- Neither recommendation touches `RECONCILIATION_EXECUTOR`,
  `apps.sync.executors`, or any executor-specific code — the
  same-source-code-both-environments property established in the
  previous implementation report is unaffected either way.

## 7. Explicitly NOT changed

- No source code was changed.
- No `.env` file was changed (both were only *read*, and secret values
  were never printed — only lengths and an equality result).
- No database write occurred (all queries were read-only `SELECT`s via
  Django's ORM in read-only `manage.py shell -c` invocations; no
  `.save()`/`.create()`/`.update()`/`.delete()` was called).
- No WhatsApp message was sent (all WAHA calls were `fetch_chat_messages`,
  a `GET`, reading history that already existed from your own prior
  tests).
- No WAHA session lifecycle operation (no start/stop/restart/logout) was
  performed.
- Not proceeding to Phase 9 or any other task — stopping here as
  instructed.
