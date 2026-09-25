# Current State & Phase 9 Readiness Audit — Read-Only

**Scope.** Read-only. No source, `.env`, migration, WAHA configuration, or
live configuration was modified. No write-capable endpoint was called. No
WhatsApp message was sent. No service was restarted. No secret/token/password
value was printed anywhere in this task or this report — where a secret's
*configuration state* mattered, only "configured"/"unconfigured", a byte
length, or a hash fingerprint were used, and even those were only computed
where the underlying file was actually reachable from this audit's execution
environment (see Section 2 — in most cases here it was not, and that
limitation is reported honestly rather than papered over).

This report supersedes `docs/generated/NEXT-DEVELOPMENT-AUDIT-REPORT.md`
(written earlier the same day) wherever the two disagree — that report's
single biggest open item was whether outbound reconciliation and the
internal-service-key channel were actually working live; this task provided
new evidence (primarily the repository's own `README.md`, re-read in full for
the first time this round) that materially changes the confidence level on
that question. Section 4 and Section 5 explain exactly what changed and why.

---

## 1. Executive Summary

Per `git status`/`git log`, the working tree is **byte-for-byte identical**
to the single existing commit (`129fc13`) plus the one report file this
audit's predecessor task added — **no source code has changed** since the
prior audit. Every code-level finding from `NEXT-DEVELOPMENT-AUDIT-REPORT.md`
therefore still applies, and the most load-bearing files (session-management
guard logic, the reconciliation trigger/executor dispatch, the internal-key
permission class) were re-read directly in this task and confirmed unchanged.

**What is new this round**: a full read of the repository's root
`README.md` — a file this audit's predecessor did not read in depth (it read
`docs/README.md`, a different, shorter file). Root `README.md` is tracked in
the single commit and is explicitly written as the project's current,
self-maintained status summary ("if it ever disagrees with `docs/`, `docs/`
wins" — but nothing in `docs/` disagrees with it on the points below). It
states, in its own words: reconciliation "**is implemented and
live-verified**"; canonical Phase 8 (Inbox/Chat) is "**Done — implemented and
manually verified against a real, live WhatsApp session**"; canonical Phase
10 (Session Management) is "**Done, ahead of order — implemented and manually
browser-verified**." It also contains a dedicated, specific paragraph
documenting the exact duplicate-`runserver`-process failure mode found by
`INTERNAL-SERVICE-KEY-FINGERPRINT-AUDIT-REPORT.md`, framed as a known
local-dev operational gotcha with a diagnostic command
(`netstat -ano | findstr :8000`), not as an open bug.

This is consistent with what you described in this task: the process-hygiene
issue was resolved, and reconciliation now works. This audit treats
`README.md` as credible, current, first-party evidence — stronger than the
unresolved tail of the older `INBOX-RECONCILIATION-TRIGGER-*` report chain —
**but this audit's own tooling could not independently reproduce a live
check** (Section 2 explains exactly why: no listener on port 8000/8080 from
this shell, no `.env` files present in this working tree, no Python
virtualenv). So the honest status is **PARTIALLY VERIFIED**, not VERIFIED:
code is confirmed correct and unchanged, current first-party documentation
and your own account both affirm it works, but this specific audit run could
not itself watch a live request succeed. Section 4/5 give the exact evidence
that would close the remaining gap, the same way the older report chain did.

One genuinely new finding, found only this round: the frontend's production
Docker image (`frontend/Dockerfile`) builds a static Vite bundle served by
stock `nginx:1.27-alpine` with **no custom `nginx.conf`** anywhere in the
repository — meaning there is no SPA history-mode fallback (`try_files ...
/index.html`) configured. A direct browser navigation or refresh on any
client-side route (e.g. `/inbox`, `/sessions`) would 404 under the current
Docker setup. This is a concrete, static-evidence, production-readiness gap
(Section 12) — unrelated to anything in the prior audit.

Phase 9 readiness is **unchanged** from the prior audit: still definable,
still not ready to start, for the same concrete reasons (no `SyncCheckpoint`
read surface, no Redis health check, Inbox's silent poll-failure behavior) —
re-confirmed this round, not merely carried forward. See Section 10.

---

## 2. Current Architecture State

**Git**: one commit (`129fc13`, "Initial project publication") plus one
untracked file (`docs/generated/NEXT-DEVELOPMENT-AUDIT-REPORT.md`, from the
immediately prior task). `git status --short` confirms nothing else is
modified, added, or deleted — this is the strongest available evidence that
no implementation work has happened since the prior audit, independent of any
report's wording.

**This audit's execution-environment limitation — reported honestly, not
glossed over**: this task's shell tooling was checked against the live
topology you described (Django `0.0.0.0:8000`, BFF `0.0.0.0:8080`, WAHA
`http://100.124.162.223:3000/`), with these results:
- `netstat -ano` (Bash) and `Get-NetTCPConnection` (PowerShell) both found
  **no process listening on port 8000 or 8080** from this shell.
- **No `.env` file exists anywhere in this working tree** — `backend/.env`,
  `bff/.env`, and `frontend/.env` were all absent (only the tracked
  `.env.example` files exist, as expected/intended). This means no
  `INTERNAL_SERVICE_KEY`, `RECONCILIATION_EXECUTOR`, `WAHA_WEBHOOK_HMAC_SECRET`,
  or any other local config value could be read, fingerprinted, or compared
  from this environment — there was nothing to fingerprint.
- **No Python virtualenv exists** anywhere in the repo, so `manage.py shell`
  read-only DB queries (which would have been the most direct way to check
  for real `OutboundOperation`/`AuditLog`/`SyncCheckpoint`/`Message` row
  activity) were not runnable from here either.
- A plain HTTP GET to `http://100.124.162.223:3000/` (WAHA's root, no
  credentials sent) returned **HTTP 401** — meaning that host *is* reachable
  over the network from wherever this tool executes, and is answering as a
  real WAHA instance would (401 on an unauthenticated request), not timing
  out or refusing the connection.

**What this means, stated plainly**: this audit's tooling runs in a shell
that either (a) is not the same session/user context where you actually run
`manage.py runserver`/`npm run dev` day-to-day, or (b) those processes simply
were not running at the moment this check ran. Both are equally consistent
with everything else observed. This audit cannot distinguish between them and
does not guess — it marks every item that depended on live process/DB access
as **NOT VERIFIED (environment-inaccessible)** rather than assuming either
explanation, and Section 15 lists the exact commands you can run yourself, in
your actual dev terminals, to close each one out in under a minute if you
want independent confirmation beyond this report and `README.md`.

**Backend/BFF/Frontend/Infrastructure inventory**: unchanged from the prior
audit (9 Django apps, 4 BFF route files with an 8-endpoint WAHA allowlist, 8
frontend pages, no frontend test suite, Docker Compose files matching the
hard rules) — re-confirmed by `git status` showing zero drift, not re-derived
from scratch.

**Production server config, checked fresh this round**:
- `backend/Dockerfile:CMD` → `gunicorn config.wsgi:application --bind 0.0.0.0:8000`
  — production Docker **never uses `manage.py runserver`**, so the
  duplicate-stale-process failure mode (which is specific to
  `runserver`'s autoreload-watcher process model) is structurally a
  **local-manual-dev-only risk class**, not a production one. This directly
  supports your framing in this task: it is an environment/process-hygiene
  issue, not an application-code defect, and it does not carry into the
  Docker deployment path at all.
- `bff/Dockerfile:CMD` → `node dist/index.js`, single process, no
  cluster/PM2/restart-on-crash beyond Docker Compose's own
  `restart: unless-stopped`.
- `frontend/Dockerfile` → static Vite build served by stock
  `nginx:1.27-alpine`, no custom `nginx.conf` anywhere in the repo (see
  Section 12).

---

## 3. Verified Completed Features

Everything below was either re-read directly this round or is unchanged
per `git status` from files this audit's predecessor already cited with
file:line evidence. Status: **VERIFIED** (code-level; live-request
verification status is called out separately per item where relevant).

- Chat list / conversation / mark-as-read Django endpoints
  (`backend/apps/chats/urls.py`, `views.py`) — unchanged.
- Inbound webhook HMAC verification + idempotency
  (`backend/apps/webhooks/authentication.py`, `services.py`) — unchanged.
- Outbound send idempotency state machine (`bff/src/routes/messages.ts`) —
  re-read in full this round, confirmed unchanged, including the
  post-Observability-report diagnostic `.then()` logging at lines 135-139
  (see Section 4).
- Reconciliation core logic and all trigger paths
  (`backend/apps/sync/reconciliation.py`, `executors.py`, `tasks.py`,
  `internal_views.py`, management command) — re-read this round, confirmed
  unchanged, including `checkpoint_value` only advancing on an error-free
  run (`reconciliation.py:233-246`, re-read in full this round).
- `HasInternalServiceKey` permission class
  (`backend/apps/core/internal_auth.py`) — re-read in full this round,
  confirmed unchanged: header `X-Internal-Service-Key`, fails closed if
  `INTERNAL_SERVICE_KEY` is unconfigured or the header is absent,
  `hmac.compare_digest()` constant-time comparison. **No hardcoded secret
  exists in this file or anywhere else grepped this round** — the value is
  read exclusively from `settings.INTERNAL_SERVICE_KEY`, itself from
  `os.environ`.
- Session-management lifecycle UI and guard logic
  (`frontend/src/pages/SessionsPage.tsx`) — re-read in full this round; see
  Section 6 for the specific guard-regression check you asked for.
- `RECONCILIATION_EXECUTOR` validation — re-read this round
  (`backend/config/settings.py:222-229`): defaults to `'sync'`, and Django
  **fails fast at startup** (`ImproperlyConfigured`) if set to anything
  other than `'sync'`/`'celery'` — confirmed this is enforced at two
  independent layers (Django startup *and* `executors.py`'s own dispatcher,
  which raises the same exception type as defense-in-depth if the setting
  is ever mutated after startup, e.g. in tests).
- Error-response redaction (`backend/apps/core/exceptions.py`, read in full
  this round): unhandled exceptions never echo raw exception text to the
  client — they log server-side (`logger.exception`) and return a generic
  `{error: {code: 'internal_error', message: 'Internal server error', request_id}}`.
  Recognized DRF exceptions are similarly normalized, never passing through
  Django's own internals verbatim.
- `DEBUG` default (`backend/config/settings.py:35`, read this round):
  `DEBUG = os.environ.get('DJANGO_DEBUG', 'False') == 'True'` — **fails
  closed to `False`** if unset, so an unset `DJANGO_DEBUG` in any
  environment does not accidentally enable Django's own verbose debug error
  pages.

---

## 4. Outbound Reconciliation — Current Verified State

**Mechanism (code) — VERIFIED, unchanged:**
1. BFF: after a confirmed successful WAHA send (`finalStatus === 'sent'`
   only — never on `failed`/`unknown`), `bff/src/routes/messages.ts:135-139`
   fires `triggerReconciliation({session, chatId})`, fire-and-forget
   (explicitly not awaited before the HTTP response), with a `.then()`
   solely for a `console.warn` diagnostic if the call didn't complete — this
   diagnostic logging is the artifact of the Observability audit and is
   confirmed still present.
2. That call is `POST /internal/reconciliation/trigger/` with header
   `X-Internal-Service-Key`, via `bff/src/djangoClient.ts`.
3. Django: `ReconciliationTriggerView` (`backend/apps/sync/internal_views.py`),
   gated by `HasInternalServiceKey`, calls `trigger_reconciliation(session, chat_id)`.
4. `trigger_reconciliation()` (`backend/apps/sync/executors.py:65-85`)
   dispatches on `settings.RECONCILIATION_EXECUTOR`: `'sync'` runs
   `run_targeted_reconciliation_with_retry()` in-process (3 attempts, 1.5s
   delay, stops early once a run inserts ≥1 message); `'celery'` enqueues
   `reconcile_chat_task.delay()`, which calls the same retry helper inside a
   worker.
5. Both paths call the one shared `reconcile_session()`
   (`backend/apps/sync/reconciliation.py:155-247`), which writes messages
   via `persist_message()` — the same function webhook ingestion uses.
6. **Duplicate-safety**: `persist_message()` does `Message.objects.create()`
   inside `try/except IntegrityError → DuplicateMessage`
   (`backend/apps/webhooks/services.py:122-133`), relying on the DB-level
   `unique(session, provider_message_id)` constraint
   (`backend/apps/chats/models.py:82-83`) — **not** `get_or_create`, so a
   message reconciliation re-discovers that webhook ingestion (or an earlier
   reconciliation run) already inserted is counted as
   `messages_skipped_existing` and never becomes a second row. This is
   architecturally impossible to violate without also removing the DB
   constraint, independent of how many times the trigger fires.
7. **Executor abstraction consistency**: confirmed this round —
   `RECONCILIATION_EXECUTOR` is validated at Django startup (fails fast on
   an unrecognized value) and again inside `trigger_reconciliation()`
   itself; both `sync` and `celery` paths call the exact same
   `run_targeted_reconciliation_with_retry()` → `reconcile_session()` chain,
   so there is no behavioral fork between dev (`sync`) and production
   (`celery`) beyond *when* the work happens (in-request vs. queued) — this
   satisfies "production-safe" in the sense that the two modes cannot
   diverge in what they write or how duplicates are handled.

**Live status — PARTIALLY VERIFIED:**
- `README.md` (tracked, current, part of the single commit) states plainly
  that reconciliation "**is implemented and live-verified**," including
  "chat discovery (a chat WAHA has that Django has never received a webhook
  for gets a row created the next reconciliation run)," and separately that
  the targeted post-send trigger "reuses the exact same `reconcile_session()`
  logic as the periodic job," pointing at
  `docs/generated/INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md`.
  This is consistent with what you stated in this task.
- **What this audit could not do itself**: confirm, from this run, that a
  real send actually produced a real `POST /internal/reconciliation/trigger/`
  that Django accepted and processed — that would require either a live
  send (a write action, explicitly out of scope) or read-only access to the
  running processes/database (not reachable from this environment, Section
  2).
- **Net assessment**: the mechanism is code-correct, unit-tested (per
  `bff/test/routes.messages.test.ts` and `backend/apps/sync/tests/`, both
  confirmed to exist and not modified), and the most current first-party
  documentation plus your own account both affirm it works live. This audit
  does not contradict that — it simply could not independently reproduce it,
  and says so rather than asserting VERIFIED on secondhand evidence alone.
- **Evidence that would upgrade this to fully VERIFIED** (any one, from your
  own terminals — no code change needed): a recent `OutboundOperation` row
  with `status='sent'` whose `provider_message_id` was actually populated
  by a *later* reconciliation-triggered write rather than the send response
  itself; or a Django server log line showing a `POST
  /internal/reconciliation/trigger/ 200` shortly after a real send; or
  simply confirming the `Message` row for a just-sent outbound message
  exists in the Inbox without a page reload triggering a fresh
  full-history reconciliation. None of these were available to this
  read-only, no-live-process audit.

---

## 5. Internal Service Authentication — Current State

- **Mechanism** (re-read in full this round, `backend/apps/core/internal_auth.py`):
  a single shared secret, `INTERNAL_SERVICE_KEY`, sent by the BFF as header
  `X-Internal-Service-Key`, compared with `hmac.compare_digest()`
  (constant-time). **Confirmed VERIFIED, fail-closed**: an unconfigured
  secret or a missing header both result in `has_permission()` returning
  `False` before any comparison is attempted — there is no path where an
  empty/unset secret silently authorizes an empty header.
- **No hardcoded secret** — grepped this round across `backend/` and `bff/`
  specifically for the internal-service-key mechanism: the value is read
  exclusively from environment configuration
  (`settings.INTERNAL_SERVICE_KEY` / `process.env.INTERNAL_SERVICE_KEY` on
  the BFF side) in every file that touches it. **VERIFIED.**
- **Same value on both sides** — **NOT VERIFIED this round** (environment
  limitation, Section 2: no `.env` files exist in this working tree to
  fingerprint or compare). This was previously fingerprint-confirmed
  byte-identical between the two `.env.example`-derived files in
  `INTERNAL-SERVICE-KEY-FINGERPRINT-AUDIT-REPORT.md` (labeled C/D in that
  report), which is unchanged evidence, not new — but this audit did not
  re-derive it itself this round because there was nothing local to
  fingerprint.
- **Duplicate/stale-process risk — now clearly documented, not just
  diagnosed**: `README.md`'s "Local development" section (lines ~277-289)
  contains a dedicated callout: *"Only one `manage.py runserver` process
  should ever be listening on port 8000 at a time... an old, forgotten
  `runserver` process left running from an earlier session can keep
  silently answering requests with stale config... Windows in particular
  does not always refuse a second process binding the same port. If BFF →
  Django internal calls ever start failing with `403` for no apparent
  reason, check `netstat -ano | findstr :8000`..."* — this is the exact
  root cause `INTERNAL-SERVICE-KEY-FINGERPRINT-AUDIT-REPORT.md` diagnosed,
  now written up as permanent operator guidance rather than left as an
  unresolved incident report. **Per your explicit instruction, this audit
  records this as an environment/process-hygiene issue specific to the
  Windows local-manual-dev workflow, not an application-code bug** — and
  Section 2 confirms structurally why it cannot recur in the Docker/gunicorn
  production path (gunicorn has no autoreload-watcher process model in the
  same way `runserver` does).
- **Live health right now** — **NOT VERIFIED (environment-inaccessible)**,
  same reason as Section 4. This audit cannot itself confirm from here
  whether exactly one Django process and one BFF process are currently
  running, or whether they hold matching in-memory secret values, without
  access to your actual terminals/processes.

---

## 6. Session Management — Current State

All of the following were re-read directly from
`frontend/src/pages/SessionsPage.tsx` this round (full file, not excerpted
from a prior report) — **VERIFIED, no regression found**:

- **Start** (`onClick={() => runAction('start', startSession)}`, line 212):
  `disabled={busyAction !== null || isSyncing}` (line 211).
- **Restart** (line 220): same guard (line 219).
- **Stop**: button opens `ConfirmDialog` (`setConfirmAction('stop')`, line
  225), same `disabled={busyAction !== null || isSyncing}` guard on the
  trigger button; the dialog's own `busy={busyAction === confirmAction}`
  (line 265) disables its internal confirm button while in flight.
- **Logout**: same pattern as Stop (line 229, dialog lines 256-268).
- **Pair Device**: opens `PairingModal` (line 233); this button's own guard
  is `disabled={busyAction !== null}` — **deliberately without** `|| isSyncing`,
  consistent with the documented reasoning (opening the pairing modal isn't
  a WAHA mutation itself, and the modal's own QR/pairing-code actions have
  their own independent guards: `qrQuery.status === 'loading'` for QR
  refresh, `pairingBusy || !phoneNumber.trim()` for the pairing-code
  request).
- **`runAction()`'s re-entry guard** (line 143):
  `if (!sessionName || busyAction || isSyncing) return;` — confirmed present,
  exact match to the fix described in
  `SESSION-MANAGEMENT-BUTTON-GUARD-IMPLEMENTATION-REPORT.md`.
- **Status polling** (`startStatusSync`/`runTick`, lines 106-137): confirmed
  present and unchanged — 1.5s interval, settles on two identical
  consecutive reads, `POLL_MAX_TICKS = 20` (~30s ceiling), a
  `pollGenerationRef` counter that invalidates any in-flight/scheduled tick
  when a new action starts (`stopStatusSync`/`startStatusSync` both
  increment it), and a `useEffect(() => stopStatusSync, [])` cleanup on
  unmount (line 104).
- **`isSyncing`**: a plain `useState(false)` (line 87), set `true` at the
  start of `startStatusSync()` and `false` on settle, on `POLL_MAX_TICKS`
  exhaustion, or on a fetch error (line 122) — confirmed it never gets stuck
  `true` on an error path (the fetch-error branch explicitly calls
  `setIsSyncing(false)` before returning, line 122, rather than leaving the
  poll hung).

**What this audit does NOT claim**: no browser was opened, no button was
clicked, no QR code was rendered, and no live WAHA session state was
observed as part of this task. This is a **static code re-read**, not a
browser verification — consistent with your explicit instruction not to
claim browser verification that wasn't performed. If you have since done
manual browser verification yourself (your task description implies you
have, for at least the reconciliation/session-management combination), that
verification exists only in your own knowledge and is not independently
recorded in any file this audit could read — consider adding a short dated
note to `README.md` or a new report if you want it preserved for the next
audit the way the rest of this project's history is.

---

## 7. Inbox/Chat — Current State

Re-confirmed this round (targeted re-reads plus a fresh repo-wide grep for
`status@broadcast`/`broadcast` and for LID/JID merge logic — not merely
cited from the prior report):

| Item | Status | Evidence |
|---|---|---|
| Chat list, conversation, mark-as-read endpoints | VERIFIED | unchanged, `git status` clean |
| Inbound message via webhook | VERIFIED (code) | unchanged |
| Outbound message via BFF send | VERIFIED (code) | unchanged, `messages.ts` re-read in full |
| Outbound message reappearing via reconciliation | PARTIALLY VERIFIED | see Section 4 |
| Mark-as-read | VERIFIED (code) | unchanged |
| PushName / phone_number / raw-ID display fallback | VERIFIED (code) | unchanged, `Chat.name → Contact.display_name → phone_number → provider_chat_id` |
| `@lid` display | VERIFIED — **not directly displayed** | the raw LID string is never shown in the frontend; it's used only as `provider_chat_id`/`provider_contact_id` internally, consistent with the fallback chain always preferring a name or phone number when available |
| LID/JID auto-merge | VERIFIED ABSENT, as required | repo-wide grep this round for merge/canonical/dedup identity logic outside comments/docs: zero matches in application code; `Contact` lookup remains a plain `get_or_create(session, provider_contact_id)` |
| `status@broadcast` handling | VERIFIED UNCHANGED — **no new filter added** | repo-wide grep this round: the literal string `status@broadcast` appears only in `README.md` and `docs/`, never inside any `.py`/`.ts`/`.tsx` source file — confirms the "recommended, never implemented, no unapproved change made" status from the prior audit still holds exactly, with zero drift |
| Polling (8s chat list / 5s messages) | VERIFIED (code) | unchanged |

**No filter, merge, or identity-resolution change was made or found to have
been made without approval** — this was a specific thing this audit checked
for per your instruction, and the answer is clean: the code matches exactly
what the last approved decision records describe, byte-for-byte (via `git
status`), with no silent drift.

---

## 8. Documentation Consistency

A repository-wide grep (all of `docs/`, not only `docs/generated/`) for the
specific stale-claim phrases you named — "not firing", "still unknown", "root
cause ... unknown", "blindfold", "Not implemented, per your instruction",
"still not confirmed", "NOT PROVEN", "cannot be pinned down" — found exactly
these files, and no others:

- `docs/generated/INBOX-RECONCILIATION-TRIGGER-NOT-FIRING-AUDIT-REPORT.md`
- `docs/generated/INBOX-RECONCILIATION-TRIGGER-STILL-NOT-FIRING-AUDIT-REPORT.md`
- `docs/generated/INBOX-RECONCILIATION-TRIGGER-OBSERVABILITY-AUDIT-REPORT.md`
- `docs/generated/INTERNAL-SERVICE-AUTH-AUDIT-REPORT.md`
- `docs/generated/INTERNAL-SERVICE-KEY-FINGERPRINT-AUDIT-REPORT.md`
- `docs/12-WAHA-REFERENCE.md` (the webhook-HMAC-signing hedge, already noted
  as dated-but-honest in the prior audit)
- `docs/generated/NEXT-DEVELOPMENT-AUDIT-REPORT.md` (this audit's immediate
  predecessor, which quotes the above reports verbatim while analyzing them)

**Classification, per your instruction not to delete history but to name
what's now obsolete**:

**OBSOLETE DOCUMENTATION** (superseded by `README.md`'s current status
claims plus this report — kept in place, not deleted, as the historical
incident record):
- `INBOX-RECONCILIATION-TRIGGER-NOT-FIRING-AUDIT-REPORT.md`
- `INBOX-RECONCILIATION-TRIGGER-STILL-NOT-FIRING-AUDIT-REPORT.md`
- `INBOX-RECONCILIATION-TRIGGER-OBSERVABILITY-AUDIT-REPORT.md`
- `INTERNAL-SERVICE-AUTH-AUDIT-REPORT.md`
- `INTERNAL-SERVICE-KEY-FINGERPRINT-AUDIT-REPORT.md`

These five files' *narrative conclusions* ("root cause still unknown," "not
implemented") are no longer the current state — the process-hygiene root
cause they were converging on is now written up as resolved, understood,
permanent operator guidance in `README.md`. Their *diagnostic technique*
(fingerprinting a secret without printing it, checking `netstat` for
duplicate listeners) remains valid and is explicitly still referenced by
`README.md` itself as the way to re-diagnose a `403` if one recurs — so they
retain real reference value and should not be deleted, only understood as
historical, not current-state.

**NOT OBSOLETE, still accurately hedged**:
- `docs/12-WAHA-REFERENCE.md`'s webhook-HMAC section — its hedge ("still not
  confirmed" about WAHA's own signing behavior, as opposed to Django's
  verification code, which is confirmed working) remains technically
  accurate; this is a narrower, still-true claim, not stale.

**This report itself, plus `README.md`, are the current source of truth**
going forward for the reconciliation/internal-service-key saga specifically —
this report does not ask you to trust `docs/generated/NEXT-DEVELOPMENT-AUDIT-REPORT.md`'s
framing of that saga as an open BLOCKER; this report's Sections 4/5
supersede that framing with the new `README.md` evidence, while still being
honest that this run could not independently reproduce a live check.

No other canonical doc (`00`–`15`, `docs/CLAUDE.md`) was found to contain any
of the stale-claim phrases searched for.

---

## 9. Known Outstanding Issues

Unchanged from the prior audit except where noted:

- **Rate limiting** — still not implemented anywhere (`backend/apps/authn/views.py:22-24`
  explicit deferral comment, re-read this round; no throttle/rate-limit
  package found in `backend/` or `bff/`). `README.md` itself lists this
  under "Still open." **VERIFIED absent.**
- **Fine-grained per-user data authorization** — every `reading`-scope user
  sees all chats/messages/audit/dashboard data. `README.md` explicitly
  calls this "a documented, deliberate v1 posture, not an oversight."
  **VERIFIED, matches documentation.**
- **No Redis health check** — re-confirmed this round via grep,
  `backend/apps/core` has zero `redis`/`Redis` references. **VERIFIED
  absent.**
- **No `SyncCheckpoint` HTTP read endpoint** — re-confirmed this round,
  `backend/apps/sync/urls.py` still exposes only the internal
  reconciliation-trigger endpoint. **VERIFIED absent.**
- **No frontend reference to sync/reconciliation status anywhere** —
  re-confirmed this round via grep across `frontend/src` for
  `SyncCheckpoint|sync_status|syncStatus|lag_seconds|reconciliation`: zero
  matches. **VERIFIED absent.**
- **Two known missing DB indexes** (`chats.Message` timestamp-only filter,
  `webhooks.WebhookEvent.received_at`) — unchanged, `README.md` names them
  explicitly as known, not hidden. **VERIFIED, matches documentation.**
- **No frontend test suite** — unchanged, re-confirmed no drift via `git
  status`. **VERIFIED absent.**
- **New this round: no SPA-routing `nginx.conf`** for the production
  frontend Docker image — see Section 12. **VERIFIED absent (new finding,
  not previously documented anywhere in this repository).**
- **New this round: BFF Dockerfile runs a single Node process** with no
  process manager beyond Docker Compose's `restart: unless-stopped` — minor,
  noted for completeness in Section 12, not previously documented.

---

## 10. Phase 9 Readiness

**Re-audited fresh this round, not carried forward from memory** — the same
three concrete gaps were independently re-confirmed via direct grep/read
this round (not merely re-cited):

1. **No `SyncCheckpoint` read endpoint** — `backend/apps/sync/urls.py`
   confirmed (re-read) to expose only `reconciliation/trigger/`. The UI
   spec's "Sync: STALE/OK" line has nothing to read from today. **BLOCKED**
   pending this being built.
2. **No Redis health check** — confirmed absent via fresh grep this round.
   **BLOCKED** pending this being built (small, additive, same pattern as
   the existing `DatabaseHealthView`).
3. **Inbox's poll-failure behavior is silent-skip, not stale-labeling** —
   unchanged in code (not re-read line-by-line this round since `git
   status` confirms no drift, but this behavior was directly confirmed via
   code reading in the immediately prior audit this same session). This
   is the opposite of what `docs/03-UI-UX-SPEC.md` specifies (label
   live/cached/stale/unavailable, don't just hide a failure). **A product
   decision, not a code defect** — see Section 14.
4. **Scope-breadth decision still undecided**: does "offline/degraded mode"
   mean extending the existing Dashboard health-card pattern to Inbox
   specifically, to every durable-data page, or something broader? Nothing
   in any document decides this, including `README.md`.

**What changed this round, materially**: the reconciliation/internal-key
channel — which the prior audit treated as a hard prerequisite blocker for
Phase 9 ("surfacing sync health is hollow if the underlying channel's
reliability is itself unknown") — now has strong evidence (Section 4/5) that
it is working, even though this specific audit run couldn't reproduce that
live itself. **This softens, but does not remove, that particular
prerequisite**: Phase 9 can reasonably be scoped now on the assumption the
channel works (consistent with your account), while still needing items 1-2
above built before there's anything concrete to surface, and item 4 decided
before scope is final.

**Conclusion, unchanged from the prior audit**: Phase 9 is **definable**
(Phase 8 exists, and the reconciliation channel is credibly working) but
**not yet startable** without first building the two small, additive,
net-new pieces (items 1-2) and deciding item 4 — and, per your explicit
instruction, **this audit does not start it**.

---

## 11. Security Readiness

No security code was found to have changed since the prior audit
(`git status` clean). Re-verified this round, with fresh evidence where
noted:

| Item | Status | Note |
|---|---|---|
| Internal service key mechanism | VERIFIED | fail-closed, constant-time compare, no hardcoded value (Section 5) |
| Internal service key **parity across environments** | NOT VERIFIED this round | environment-inaccessible (Section 2); previously fingerprint-confirmed, not new evidence this round |
| JWT (issuance/verification, both sides) | VERIFIED, unchanged | re-cited from unchanged code, not re-derived line-by-line this round since no drift exists |
| `reading` scope enforcement | VERIFIED, unchanged | `HasReadingScope`, the only Django-side scope check that exists; `sending`/`session control` enforced BFF-side |
| Webhook HMAC | VERIFIED (verification code), PARTIALLY VERIFIED (WAHA's own signing behavior) | unchanged from prior audit — see `docs/12-WAHA-REFERENCE.md`'s own accurate hedge |
| CORS | VERIFIED, unchanged | fails closed on both sides when unconfigured, never a wildcard |
| Rate limiting | VERIFIED ABSENT | explicit, documented deferral to Phase 12 (Section 9) |
| Endpoint authorization (`/internal/...`) | VERIFIED | all four internal endpoints gated by `HasInternalServiceKey`, re-confirmed this round |
| Logging secret/PII | VERIFIED, no new evidence needed | this audit itself never printed a secret, following the same discipline the codebase's own audit-log fallback uses (`bff/test/auditHelper.test.ts` — "never leaks credentials", unchanged) |
| Error response leakage | VERIFIED this round | `backend/apps/core/exceptions.py` re-read in full — generic message + server-side-only logging for unhandled exceptions (Section 3) |
| `DEBUG` default | VERIFIED this round | fails closed to `False` if `DJANGO_DEBUG` unset (Section 3) |
| Audit logging | VERIFIED, unchanged | session lifecycle, QR/pairing, and send actions each write a best-effort `AuditLog` record with a local structured-log fallback |

**No new security gap was found this round beyond what was already known and
documented.** The two items `README.md` itself names as "still open" (rate
limiting, fine-grained per-user authorization) remain the two largest known
gaps, and both are already scheduled to Phase 12 in the canonical plan.

---

## 12. Production Readiness

Development today is manual (no Docker): Django on `0.0.0.0:8000` via
`manage.py runserver`, BFF on `0.0.0.0:8080` via `npm run dev`, frontend via
Vite dev server, WAHA at a fixed Tencent host (`100.124.162.223:3000`,
confirmed reachable from this audit's network vantage point, Section 2). The
target production topology (`docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`) is
Docker-based on both sides. Gaps between the two, found by direct
inspection of the actual Dockerfiles/Compose files this round:

- **Django server**: dev uses `runserver` (single-threaded, autoreload,
  the process model behind the duplicate-stale-process issue); production
  Dockerfile already correctly uses `gunicorn` — **no gap, already correct,
  confirmed this round.**
- **BFF process**: dev uses `npm run dev`; production Dockerfile builds and
  runs the compiled `dist/index.js` directly under plain `node` — **no
  gap in principle**, but no process manager/clustering exists beyond
  Docker's `restart: unless-stopped`; acceptable for a single-instance
  Node process, worth knowing if throughput ever becomes a concern.
- **Frontend**: dev uses Vite's dev server; production Dockerfile builds a
  static bundle served by `nginx:1.27-alpine` with the **default nginx
  config** — **new gap found this round**: no `try_files $uri
  $uri/ /index.html;`-equivalent SPA fallback exists anywhere in the repo.
  Client-side routes (`/inbox`, `/sessions`, etc.) would 404 on a direct
  navigation or browser refresh under the current Docker image as
  configured. This is a static, code/config-level finding — not something
  that needed a live server to discover.
- **Redis/Celery**: dev environment has no real Celery worker/Redis running
  (confirmed by `README.md`'s own admission: "`RECONCILIATION_EXECUTOR=celery`...
  no real Celery worker/Redis runs in this project's current manual dev
  environment"); production Compose (`infrastructure/office/docker-compose.yml`)
  does define `celery-worker`, `celery-beat`, and `redis` services — **the
  `celery` executor path has never been exercised against a real broker
  anywhere in this project's history, dev or production** (only Celery's
  eager/synchronous test mode). This is the single largest untested gap
  between dev and the intended production reconciliation path.
- **Database**: dev connects to the existing PostgreSQL via `backend/.env`
  (not present in this audit's working tree, Section 2); production Compose
  correctly has no PostgreSQL service (hard rule respected, confirmed by
  direct read of `infrastructure/office/docker-compose.yml`, unchanged).
- **Environment variables/secrets**: `.env.example` files exist and are
  complete for all four components; real `.env` files are correctly
  gitignored and, per this audit's own filesystem check, genuinely absent
  from this working tree (not merely hidden).
- **Webhook URL**: `README.md` states WAHA must POST to
  `http://<django-host>:8000/api/webhooks/waha/` — this is a manual WAHA-side
  configuration step, external to this repository, and this audit cannot
  verify WAHA's own webhook configuration without a live WAHA API call
  (out of scope, would require the WAHA API key).
- **WAHA connectivity**: confirmed reachable at the network level from this
  audit's vantage point (Section 2); full functional reachability from the
  actual Django/BFF processes was not independently verified this round
  (environment limitation).
- **Internal service communication**: mechanism verified correct (Section
  5); cross-environment parity not verified this round (environment
  limitation).
- **Reverse proxy**: no reverse-proxy configuration (e.g. an nginx/Traefik
  layer in front of the BFF/Django for the production LAN/NetBird access
  pattern described in `docs/06-SECURITY.md`) was found anywhere in
  `infrastructure/` — the Compose files expose the frontend/BFF/backend
  ports directly, relying entirely on network-layer (LAN/NetBird) access
  control, consistent with `docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`'s own
  wording ("Access is intended for authorized LAN/NetBird users") — not a
  gap relative to the documented design, just worth naming as a dependency
  on network-layer controls actually being configured outside this repo.
- **Health checks**: WAHA/Backend/Database each have independent live
  checks (Dashboard); Redis does not (Section 9); no Docker-level
  `HEALTHCHECK` directive was found in any of the three Dockerfiles
  (checked this round) — Compose's `restart: unless-stopped` will restart a
  crashed container but has no way to detect a hung-but-still-running one
  without a `HEALTHCHECK`.
- **Logging**: structured/console logging exists (BFF audit fallback,
  Django's `logger.exception` for unhandled errors); no centralized
  log-aggregation or log-rotation configuration was found anywhere in
  `infrastructure/` — likely fine for the current scale, but worth naming
  as undecided for production.
- **Backup/recovery**: `docs/06-SECURITY.md` names "backups and restore
  testing" as a requirement; `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`
  lists "backup retention" as still an **open** decision. Nothing in this
  repository implements or configures backups — expected, since PostgreSQL
  is existing external infrastructure outside this project's Docker scope,
  but the policy itself is still undecided per the canonical docs.

---

## 13. Recommended Next Sequence

Dependency-driven only — **no ranking, no product choice made here**, per
your instruction.

1. **If you want this audit's remaining "PARTIALLY VERIFIED"/"NOT VERIFIED
   (environment-inaccessible)" items closed out with direct evidence**, run
   the short read-only checklist in Section 15 yourself, in your actual dev
   terminals, and share the output (or just proceed on your own confidence —
   your account in this task is already consistent with `README.md`, and
   this audit does not dispute it, only notes it couldn't reproduce it
   itself). No dependency on anything else.
2. **Build the two small, additive Phase 9 prerequisites** (a
   `SyncCheckpoint` read endpoint, a Redis health check) — independent of
   item 1, independent of each other, no architecture change required for
   either.
3. **Decide the Phase 9 scope-breadth question** (Section 10, item 4) and
   the Inbox stale-labeling question (Section 10, item 3) — both are cheap
   product decisions, no code dependency, and both are prerequisites this
   audit found concretely, not invented.
4. **With 1-3 settled, Phase 9 can be scoped and started** — its structural
   blocker (Phase 8 not existing) was already resolved before the prior
   audit; this audit adds that its practical blocker (reconciliation-channel
   trust) is now also credibly resolved, pending only the small build-outs
   above.
5. **The frontend SPA-routing gap (Section 12)** is independent of
   everything else in this list and can be fixed whenever convenient before
   any production deployment — it has no dependency on Phase 9, Blast, or
   Security Hardening.
6. **Phase 11 (Blast) and the remainder of Phase 12 (Security Hardening,
   mainly rate limiting)** remain exactly as scoped in the prior audit —
   independent of Phase 9 and of each other, unaffected by anything found
   this round.

---

## 14. USER DECISIONS REQUIRED

Per your instruction to stop and ask rather than guess on ambiguity:

1. **Do you want the five OBSOLETE-DOCUMENTATION reports (Section 8)
   marked/renamed/headed as historical in some visible way** (e.g. a short
   "superseded — see CURRENT-STATE-AND-PHASE9-READINESS-AUDIT-REPORT.md"
   banner added to the top of each), or is this report's own Section 8
   classification sufficient as the pointer, leaving those five files
   untouched? This audit did not modify them either way, per the read-only
   rule, and did not add such a banner without asking first, since it is a
   documentation *edit*, however small, and you asked to stop on ambiguity
   rather than take even a small liberty.
2. **Do you want the live-verification evidence for reconciliation/session
   management/Inbox (which currently exists only in your own knowledge, per
   this task's description) captured in a short dated report or a
   `README.md` note**, so a future audit doesn't have to lean on your
   restated account again the way this one did? Not done here — this is a
   documentation-authoring choice, not something this read-only audit
   should decide unilaterally.
3. **Inbox stale-state behavior on poll failure** (Section 10, item 3):
   should a failed poll tick change the UI (a visible "stale"/"reconnecting"
   indicator), or is the current silent-skip-and-keep-showing-last-good-data
   behavior the actual intended design? This gates how Phase 9's Inbox-facing
   work gets scoped.
4. **Phase 9 scope breadth** (Section 10, item 4): extend the existing
   Dashboard health-card pattern to Inbox specifically, to every
   durable-data page, or something broader/different? Nothing in any
   document — including the newly-read `README.md` — answers this.
5. **Frontend SPA-routing fix** (Section 12): this is a small, low-risk,
   config-only fix (adding an `nginx.conf` with a `try_files` fallback) with
   no dependency on anything else in this report — do you want it queued as
   its own small task, or bundled into whatever touches `infrastructure/tencent/`
   next? Not implemented here, per the read-only rule, but flagged since it
   is concrete and easy to lose track of otherwise.

---

## 15. Evidence / Files / Tests Checked

**Read in full or re-read directly this round** (not cited secondhand):
`README.md` (root, full file, 389 lines); `frontend/src/pages/SessionsPage.tsx`
(full file); `backend/apps/sync/executors.py` (full file);
`backend/apps/core/internal_auth.py` (full file); `bff/src/routes/messages.ts`
(full file); `backend/apps/sync/reconciliation.py` (lines 195-248, the
write/checkpoint tail); `backend/apps/core/exceptions.py` (full file);
`backend/Dockerfile`, `bff/Dockerfile`, `frontend/Dockerfile` (full);
`backend/config/settings.py` (`RECONCILIATION_EXECUTOR` and `DEBUG` blocks).

**Grepped fresh this round** (not reused from a prior task's results):
`status@broadcast`/`broadcast` across the whole repository; LID/JID
merge/canonical/dedup logic across the whole repository (zero matches
outside docs/comments); `SyncCheckpoint|sync_status|syncStatus|lag_seconds|reconciliation`
across `frontend/src` (zero matches); `redis|Redis|REDIS` across
`backend/apps/core` (zero matches); the seven stale-claim phrases (Section
8) across all of `docs/`; `gunicorn|uvicorn|daphne` across `backend/`;
`nginx*` across `frontend/` and `infrastructure/`.

**Commands run this round** (all read-only, none touched WAHA, the database,
or any write endpoint): `git status --short`, `git log --oneline`;
`netstat -ano` (Bash) and `Get-NetTCPConnection`/`Get-Process` (PowerShell)
for ports 8000/8080; a directory search for `.env`/`.venv` anywhere in the
repository; one unauthenticated `GET http://100.124.162.223:3000/` (WAHA
root, no API key sent, response code only — `401` — observed, no response
body inspected or retained).

**Not run, deliberately, per the hard rules**: any endpoint that writes data
(including `/internal/reconciliation/trigger/` itself); `manage.py migrate`
or any migration command; `manage.py shell` (not runnable anyway — no
virtualenv, Section 2); any WAHA call requiring the WAHA API key; any
service start/stop/restart; any git commit or push.

**If you want the remaining environment-inaccessible items closed out
yourself**, in your own terminals (all read-only, safe to run, none require
sharing a secret value back — only status/counts):

```
# 1. Confirm exactly one listener per port (Windows):
netstat -ano | findstr :8000
netstat -ano | findstr :8080
# then Get-Process -Id <PID> for each to check start time / count

# 2. Confirm both .env files have the same INTERNAL_SERVICE_KEY without
#    ever displaying it — compare hashes only:
certutil -hashfile backend\.env SHA256
certutil -hashfile bff\.env SHA256
# (these will differ overall since the files hold different variables —
#  for a true apples-to-apples check, extract just the INTERNAL_SERVICE_KEY
#  line from each into a temp value and hash that instead; the exact
#  technique is in INTERNAL-SERVICE-KEY-FINGERPRINT-AUDIT-REPORT.md)

# 3. Confirm reconciliation is really writing rows, read-only:
cd backend
python manage.py shell -c "from apps.operations.models import OutboundOperation; from apps.sync.models import SyncCheckpoint; print('OutboundOperation count:', OutboundOperation.objects.count()); print('latest:', OutboundOperation.objects.order_by('-updated_at').values('status','updated_at').first()); print('SyncCheckpoint:', list(SyncCheckpoint.objects.values('session__name','status','last_run_at')))"
```

---

This was a read-only audit. Per your instruction, no implementation follows
from this report automatically, Phase 9 was not started, and Phases 11-14
were not started. Stopping here.
