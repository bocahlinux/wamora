# Next Development Audit — Read-Only

**Scope of this task.** Read-only. No source, config, `.env`, database, migration,
WAHA configuration, or dependency file was modified. No write-capable endpoint
was called. No test suite was executed. No WhatsApp message was sent. No
commit was made. Evidence comes from (a) direct reading of the canonical docs
listed below, (b) direct reading of the current backend/BFF/frontend source
via two read-only code-verification passes, and (c) a full read of every file
under `docs/generated/` relevant to Inbox/Chat, reconciliation, session
management, and internal-service auth, via two documentation-digest passes.
Per instruction, Inbox/Chat and outbound reconciliation were **not**
re-implemented, re-audited from scratch, or second-guessed as a feature — but
this task *was* asked to verify, read-only, that the claimed pieces actually
exist, and to report exactly what the documentation trail says about their
verification status, including where that status is less settled than "final"
would suggest. Where something could not be verified without a write or live
action, it is marked **not verified** below, with the evidence that would be
needed.

Canonical docs read in full: `docs/00-MASTER-SPEC.md`, `docs/01-ARCHITECTURE.md`,
`docs/02-REQUIREMENTS.md`, `docs/03-UI-UX-SPEC.md`, `docs/04-DATA-MODEL.md`,
`docs/05-WEBHOOK-SYNC-DESIGN.md`, `docs/06-SECURITY.md`, `docs/07-API-CONTRACT.md`,
`docs/08-DEPLOYMENT.md`, `docs/09-TEST-PLAN.md`, `docs/10-CLAUDE-CODING-GUIDE.md`,
`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`, `docs/12-WAHA-REFERENCE.md`,
`docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`, `docs/14-REPOSITORY-STRUCTURE.md`,
`docs/15-CODING-PHASES.md`, `docs/CLAUDE.md`, `docs/README.md`, and, for
historical baseline only, `docs/generated/PHASE-9-ROADMAP-AUDIT-REPORT.md`
(now substantially superseded — see Section 11).

---

## 1. Executive Summary

The repository has exactly **one git commit** ("Initial project publication") —
history was squashed for GitHub publication, so `docs/generated/*.md` (56
files, ~15.7k lines) is the only available record of *how* the current code
came to be, and it was digested, not skipped, per the task's explicit
instruction not to rely on README/old reports alone. Every claim taken from
those reports was cross-checked against the current source tree directly.

Canonical phases 0–8 and 10 (`docs/15-CODING-PHASES.md`) are implemented and
**code-confirmed** (chat list, conversation view, mark-as-read, inbound
webhook, outbound send, reconciliation machinery, full session lifecycle UI).
Phase 9 (Offline/degraded mode), 11 (Blast), 13 (Failure/security testing) and
14 (Production deployment) have not been started; Phase 12 (Security
hardening) is partially done. Phase 10 (Session management) was built ahead
of Phase 9, repeating a numbering deviation already flagged in the prior
roadmap audit.

**The single most important finding of this audit**: the documentation trail
for outbound reconciliation does not end in a confirmed-working state. The
most recent document in that chain,
`docs/generated/INBOX-RECONCILIATION-TRIGGER-OBSERVABILITY-AUDIT-REPORT.md`,
states in its own words that "the actual root cause (why the request fails
once it's attempted) is still unknown" and ends waiting on the user to
reproduce a live send and report back a log line — no later report closes
that loop. This sits in direct tension with this task's framing that
"outbound reconciliation sudah FINAL dan sudah diverifikasi manual." This
audit does not resolve that tension (it cannot, without a live/write action,
which is out of scope), and it does not treat the task's framing as
disprovable — it simply reports, as instructed, that the paper trail does not
itself show a resolution, and names the exact evidence that would close the
gap (Section 6.A, item 1).

A related, likely-connected finding: the BFF→Django internal-service-key
channel (used by reconciliation trigger, outbound-operation registration, and
audit logging) was traced by
`docs/generated/INTERNAL-SERVICE-KEY-FINGERPRINT-AUDIT-REPORT.md` to a live
process-hygiene bug (a stale, pre-`.env`-edit `manage.py runserver` process
still bound to port 8000 alongside a fresh one), with the recommended fix
explicitly marked "Not implemented." No later report confirms it was applied.

Everything else audited — session management's frontend wiring, identity
display's fallback logic, webhook HMAC verification, the three-plus
reconciliation trigger paths, idempotency at every write boundary — is
implemented as documented and code-confirmed. Full detail follows.

---

## 2. Current Project State

**Git.** One commit, `129fc13` "Initial project publication," clean working
tree. No blame/log history is available for anything; all provenance comes
from `docs/generated/`.

**Canonical phase status** (`docs/15-CODING-PHASES.md`), evidence-based:

| # | Phase | Status | Evidence |
|---|---|---|---|
| 0 | Repository skeleton | Done | `docs/14-REPOSITORY-STRUCTURE.md` layout matches actual tree |
| 1 | Backend foundation | Done | `backend/config/`, 9 Django apps present |
| 2 | Database models + migrations | Done | models confirmed per-app in Section 3 |
| 3 | Webhook ingestion | Done | `apps/webhooks/*`, HMAC + idempotency confirmed |
| 4 | Reconciliation | Done (code) / **live status unresolved** | see Section 6.A.1 |
| 5 | Celery/Redis | Done | `config/celery.py`, `apps/sync/tasks.py` |
| 6 | BFF | Done | `bff/src/routes/*`, allowlist confirmed |
| 7 | Frontend foundation | Done | routing, layout, tokens confirmed |
| 8 | Inbox/chat | Done | see Section 3 |
| 9 | Offline/degraded mode | **Not started** | see Section 10 |
| 10 | Session management | Done (built ahead of Phase 9) | see Section 3 |
| 11 | Blast | **Not started** — zero backend presence | grep-confirmed: no app, no models, only the JWT scope string and one test reference exist |
| 12 | Security hardening | **Partial** | see Section 4 |
| 13 | Failure/security testing | **Partial** — unit-level only | see Section 5 |
| 14 | Production deployment | **Not started / not evidenced** | compose files exist and match hard rules; no evidence of an actual production run in scope |

**Backend** (`backend/`): 9 Django apps — `core, authn, waha_sessions, chats,
webhooks, sync, operations, audit, dashboard`
(`backend/config/settings.py:67-75`). URL mounting confirmed at
`backend/config/urls.py:20-30`.

**BFF** (`bff/`): 4 route/middleware files
(`health.ts`, `session.ts`, `messages.ts`, `sessionGuard.ts`), an 8-endpoint
closed WAHA allowlist (`bff/src/wahaAllowlist.ts`), 11 test files.

**Frontend** (`frontend/`): 8 top-level pages — Dashboard, Inbox, Sessions,
Login, WhatsApp (placeholder), Reports (placeholder), Settings (placeholder),
NotFound. **Zero test files exist** anywhere under `frontend/src`
(no `vitest`/`jest` config, no `*.test.tsx`).

**Infrastructure**: `infrastructure/tencent/docker-compose.yml` (frontend,
bff, waha — WAHA has no published port) and
`infrastructure/office/docker-compose.yml` (backend, celery-worker,
celery-beat, redis — no PostgreSQL service) both match the hard rules in
`docs/CLAUDE.md` and `docs/13-FINAL-DEPLOYMENT-TOPOLOGY.md`. Both `.env.example`
files are present and unpopulated with real secrets.

---

## 3. Completed Features

### Session Management — focus area

**Status: code-complete and frontend-wired.** All six BFF lifecycle actions
are called from real UI in `frontend/src/pages/SessionsPage.tsx`:

| Action | Route | Confirmation dialog | Guard |
|---|---|---|---|
| Start | `POST /api/sessions/:session/start` (`bff/src/routes/session.ts:108`) | No | `busyAction !== null \|\| isSyncing` |
| Restart | `.../restart` (`:114`) | No | same |
| Stop | `.../stop` (`:111`) | **Yes** (`ConfirmDialog`) | same, plus dialog-level busy flag |
| Logout | `.../logout` (`:117`) | **Yes** | same |
| QR | `GET .../qr` (`:132`) | No (deliberate — repeat-fetch is expected UX) | loading-state disable |
| Pairing code | `POST .../pairing-code` (`:170`) | No | `pairingBusy \|\| !phoneNumber.trim()` |

BFF-side hardening: an in-process `operationLock.ts` gives `409` on a
duplicate in-flight mutation per `session:action` key (not applied to `qr`,
by design); WAHA `timeout`/`network_error` responses collapse to
`{outcome:'unknown'}` rather than a raw `502`.

**Two real bugs were found and fixed during this feature's build, both
frontend-only**:
1. Status-sync gap — a single post-action `refetch()` could catch WAHA in a
   transitional state (e.g. `STARTING`) and never re-check. Fixed with a
   self-contained poller in `SessionsPage.tsx` (1.5s interval, stops on two
   identical consecutive reads, capped ~30s, generation-counter cancellation).
2. Button-guard gap — buttons re-enabled as soon as the BFF's HTTP response
   returned, *before* the above poller's settlement window finished, letting
   a user fire a second real WAHA call mid-settlement. Fixed by adding
   `|| isSyncing` to every mutating button's disabled condition and to
   `runAction()`'s re-entry guard. Confirmed **not** a bug in the BFF's
   operation lock — that lock was never meant to span the settlement window.

**What still needs manual verification** (explicitly, per every report that
touched this feature): **no browser verification was performed and none is
claimed** for any of the above — not for the buttons, the confirm dialog, the
QR image render, the pairing-code display, dark/light theme rendering, or
narrow-viewport behavior. Additionally unresolved, requiring a live WAHA
instance to answer (not answerable from code):
- Whether WAHA itself is idempotent for a second `start` on an
  already-starting session, or a second `stop` on an already-stopped one.
- Whether the QR image's assumed `image/png` MIME prefix is actually correct
  (never confirmed against a real WAHA QR response).
- Whether a non-superuser account with only the "session control" Django
  Group has ever actually been exercised end-to-end (never tested).

A separate, now-resolved diagnostic: `SESSION-MANAGEMENT-WAHA-CONFIG-AUDIT-REPORT.md`
found the local dev "WAHA Not reachable" health-card reading was **not** a
real connectivity failure — it was `bff/.env`'s `WAHA_SESSION_NAME` being
empty (causing the BFF's own `/health` check to silently skip calling WAHA)
plus `frontend/.env`'s `VITE_WAHA_SESSION_NAME` holding a stale placeholder
(`test_session`) instead of the real live session name. This was a config
correction, not a code fix, and was left for the user to apply manually — it
is not itself re-verified as applied by any later report.

### Inbox / Chat — focus area (per instruction: verified read-only, not
re-implemented or re-audited as a feature)

All of the following were independently confirmed against the **current
source code** by this audit, not merely cited from prior reports:

- **Chat list**: `GET /api/chats/` → `ChatListView`
  (`backend/apps/chats/urls.py:7`, `views.py:31-53`) — Django-direct (not via
  BFF), JWT + `HasReadingScope`, paginated, ordered by `last_message_at` desc.
- **Conversation**: `GET /api/chats/:id/messages/` → `ChatMessagesView`
  (`urls.py:8`, `views.py:56-73`) — same auth, paginated, ordered
  `-timestamp,-id`.
- **Inbound webhook**: `POST /api/webhooks/waha/` → `WahaWebhookView`
  (`backend/apps/webhooks/urls.py:6`, `views.py:14-67`).
- **Outbound send**: `POST /api/sessions/:session/messages`
  (`bff/src/routes/messages.ts:24`) — frontend calls this via
  `sendMessage()` (`frontend/src/lib/bffApi.ts:113-119`) from
  `InboxPage.tsx:147`, with a fresh `crypto.randomUUID()` idempotency key per
  send attempt.
- **Outbound reconciliation**: implemented, wired, unit-tested — see the
  dedicated Reconciliation focus area below and **Section 6.A.1 for its
  unresolved live-verification status**.
- **Mark as read**: `POST /api/chats/:id/read/` → `ChatMarkReadView`
  (`urls.py:9`, `views.py:76-88`), sets `Chat.last_read_at`. Data model is a
  single nullable `DateTimeField` on `Chat` (`models.py:41`) —
  **chat-level, not per-message, not per-user**; "unread" is a *derived*
  boolean (`ChatListSerializer.get_unread`, `serializers.py:46-55`:
  `last_message_at is None → False`; `last_read_at is None → True`; else
  compare timestamps), never synced to WAHA (no WAHA read-receipt capability
  is used anywhere in the codebase).
- **Identity display**: `InboxPage.tsx:48-53`, precedence
  `Chat.name → Contact.display_name (PushName-derived) → phone_number → raw provider_chat_id`.
  No `@lid`/`@s.whatsapp.net` string ever appears in frontend code — the
  frontend only ever sees the already-resolved `phone_number`/name fields
  the backend serializes.
- **Polling**: two independent `useEffect`+`setInterval` loops in
  `InboxPage.tsx` — chat list every 8000ms (`InboxPage.tsx:31`), open
  conversation's messages every 5000ms (`:32`). No WebSocket/SSE. A failed
  poll tick is **silently skipped** — it does not surface an error/stale
  state over an already-populated view (see Section 10 for why this matters
  for Phase 9).
- **Authentication/scope**: all three chat endpoints require
  `JWTAuthentication` + `IsAuthenticated` + `HasReadingScope`
  (`backend/apps/authn/permissions.py:14-19`) — confirmed the first Django
  endpoints in the project to check a JWT scope claim at all.

### WAHA Integration — endpoint map, proven vs. assumed

**Proven against a real deployed instance** (per `docs/12-WAHA-REFERENCE.md`,
itself citing live REST/webhook evidence, and matched to code that
implements exactly this):
- `GET /api/{session}/chats/{chatId}/messages?limit=N&offset=N` — pagination
  behavior (newest-first, `limit`+`offset` work, `page` is silently ignored)
  explicitly confirmed against the real deployment; implemented in
  `backend/apps/sync/waha_client.py:53-94` using `limit`+`offset`, never
  `page`.
- `POST /api/sendText` — used throughout (outbound send path), long
  operational history per the reports digested.
- Inbound `message` webhook event — real captured delivery evidence exists
  (envelope shape, `payload.id` composite-key format, LID/JID/phone identity
  fields) per `docs/12-WAHA-REFERENCE.md` and corroborated by two real,
  live-delivered webhooks used as evidence in
  `INBOX-IDENTITY-DISPLAY-AUDIT-REPORT.md`.
- `GET /api/{session}/chats` — used by `apps/sync/waha_client.py:96-145`;
  originally an "observed" (not as deeply re-verified as the paginated
  messages endpoint) endpoint per `docs/12-WAHA-REFERENCE.md`.
- `GET /api/sessions/{session}` (status) — used by the BFF's
  `getSessionStatus` allowlist entry and the `/health` check; real live
  session (`no_epahari`, status `WORKING`) was confirmed reachable per
  `SESSION-MANAGEMENT-WAHA-CONFIG-AUDIT-REPORT.md`.

**Implemented and allowlisted, but not confirmed against live WAHA execution
(live browser/WAHA test not documented anywhere in the report set)**:
- Session lifecycle mutations — `startSession`, `stopSession`,
  `restartSession`, `logoutSession` — implemented in
  `bff/src/wahaAllowlist.ts` and `bff/src/routes/session.ts`, unit-tested
  with mocks, never exercised against a real WAHA instance in any browser
  session on file.
- `getQr` / `requestPairingCode` — same status; the QR image's MIME type is
  an explicit, stated assumption, not an observed fact.
- Webhook HMAC-SHA512 signing (`X-Webhook-Hmac` header) — the *verification
  code* is implemented, unit-tested, and (per the Inbox/Chat digest) was
  confirmed to correctly accept real live webhook deliveries once the Django
  secret was correctly configured — but WAHA's own signing behavior/algorithm
  was never independently confirmed from WAHA's own documentation or a
  captured signature; it remains, in `docs/12-WAHA-REFERENCE.md`'s own words,
  an assumption about the *mechanism*, now with corroborating (not
  conclusive) evidence that it works in practice.

**Not used anywhere in the codebase**: WAHA endpoints beyond the 8 in the
BFF's allowlist and the 2 used by `apps/sync/waha_client.py` — the BFF
allowlist is a closed `Record` type (`WahaEndpointName`), and `callWaha()`
cannot be called with anything outside it (`bff/src/wahaClient.ts:29-34`) —
structurally enforced, not just convention. No arbitrary-URL construction
exists anywhere in the BFF (satisfies `docs/CLAUDE.md` hard rule #5).

### Identity — focus area

- **`@lid` / `@s.whatsapp.net` / `phone_number` / `PushName`**: `Contact`
  model (`backend/apps/chats/models.py:7-19`) stores `provider_contact_id`
  (verbatim, whichever form WAHA reports — LID, JID, or `@c.us`),
  `display_name` (populated from `PushName` on inbound non-group messages,
  `apps/webhooks/services.py:112-114`), and `phone_number` (populated **only**
  from a non-empty `@s.whatsapp.net`-form alt identifier —
  `extract_phone_number()`, `apps/webhooks/parsing.py:175-182` — never from a
  LID). No separate `lid` field exists; the LID (or whatever primary form
  WAHA reports) lives in `provider_contact_id`/`provider_chat_id` verbatim.
- **Auto-merge**: **confirmed not implemented, anywhere.** A repo-wide grep
  for merge/canonical/dedup identity logic outside comments/docs returns
  nothing; `Contact` lookup is a plain
  `get_or_create(session, provider_contact_id)`
  (`apps/webhooks/services.py:98-101`) — two different provider IDs for the
  same real person (e.g. a LID form and a JID form) will silently create two
  separate `Contact`/`Chat` rows. This is documented in
  `docs/12-WAHA-REFERENCE.md` as a **known, confirmed, deliberately
  unresolved limitation** (real evidence of the same phone number appearing
  under two different `Chat` identifiers exists, but no safe merge rule is
  supported by the evidence on file, so none was implemented) — consistent
  with this task's instruction that auto-merge is explicitly out of scope for
  this audit too.
- One specific unresolved case remains open in the docs: `Chat` id 8
  (`62811520892@s.whatsapp.net`, reconciliation-derived, no `Contact` row) —
  the Identity-Display Audit Report could not rule out that this is
  structurally the "our own account" case rather than a genuine second
  identity for an already-known contact, because the raw `SenderAlt`/
  `RecipientAlt` payload for its own messages was never captured.

### Webhook — focus area

- **Endpoint**: `POST /api/webhooks/waha/` (`backend/apps/webhooks/urls.py:6`).
- **HMAC**: header `X-Webhook-Hmac`
  (`WEBHOOK_SIGNATURE_HEADER='HTTP_X_WEBHOOK_HMAC'`,
  `apps/webhooks/authentication.py:6`), `hmac.new(secret, raw_body, sha512).hexdigest()`
  compared via `hmac.compare_digest(...)` — **constant-time**, fails closed
  if the secret or header is missing (`:9-28`).
- **Event types with real handling**: exactly one — `'message'`
  (`SUPPORTED_EVENT_TYPES = {'message'}`, `apps/webhooks/parsing.py:41`).
- **Event types received but not handled**: any other `event` value is
  stored as a `WebhookEvent` row with `status='unsupported'` and never
  parsed further (`apps/webhooks/services.py:55-58`) — recorded, not acted
  on. No other event-type string (e.g. `message.ack`, `session.status`,
  presence, group events) appears anywhere in production code; `'session.status'`
  exists only as an example value in a test fixture.
- **Idempotency**: two layers — `WebhookEvent` unique on `(session,
  provider_event_id)` (`apps/webhooks/models.py:47-49`, via
  `get_or_create`), and `Message` unique on `(session, provider_message_id)`
  (`apps/chats/models.py:82-83`, enforced via `IntegrityError` →
  `DuplicateMessage` inside `persist_message()`,
  `apps/webhooks/services.py:122-133`, not `get_or_create` at that layer).

### Reconciliation — focus area

- **Core logic**: `reconcile_session()`
  (`backend/apps/sync/reconciliation.py:155-247`) — the single business-logic
  entry point used by every trigger path below.
- **Trigger paths — all confirmed to exist in current code**:
  1. HTTP, BFF-callable: `POST /internal/reconciliation/trigger/` →
     `ReconciliationTriggerView` (`apps/sync/internal_views.py:30-55`),
     `HasInternalServiceKey`-gated.
  2. Celery, periodic (production): `reconcile_all_sessions_task`, scheduled
     via `sender.add_periodic_task(settings.RECONCILIATION_INTERVAL_SECONDS, ...)`
     in `backend/config/celery.py:12-28` (not a `CELERY_BEAT_SCHEDULE` dict —
     registered programmatically), default interval 900s.
  3. Celery, targeted: `reconcile_chat_task` — used when
     `RECONCILIATION_EXECUTOR='celery'`.
  4. Management command (dev/manual): `python manage.py reconcile <session>`
     (`apps/sync/management/commands/reconcile.py`).
- **Sync vs. Celery dispatch**: `trigger_reconciliation()`
  (`apps/sync/executors.py:65-85`) branches on `settings.RECONCILIATION_EXECUTOR`
  (`'sync'` = in-process, dev default; `'celery'` = enqueue, production) —
  same source code either way, config-switched, not a separate
  implementation per environment.
- **Post-send trigger from the BFF**: `bff/src/routes/messages.ts:135-139`
  fires (fire-and-forget, not awaited) `triggerReconciliation({session, chatId})`
  **only after a confirmed successful send** (`finalStatus === 'sent'`),
  which calls `POST /internal/reconciliation/trigger/` via
  `bff/src/djangoClient.ts:157-166`. This is the exact mechanism whose live
  firing status is unresolved — see Section 6.A.1.
- **Retry behavior**: two independent layers —
  `run_targeted_reconciliation_with_retry()` (`apps/sync/executors.py:39-62`,
  3 attempts, 1.5s delay, stops early once `messages_inserted > 0`) runs
  regardless of executor choice; Celery tasks additionally declare
  `max_retries=3, retry_backoff=True, retry_backoff_max=600, retry_jitter=True`
  (`apps/sync/tasks.py:33-40,69-76`) for the `celery` executor path.
- **Idempotency**: relies on the same `persist_message()` /
  `IntegrityError`-on-unique-constraint mechanism as webhook ingestion —
  reconciliation and webhook ingestion share one write path, so a message
  seen by both is only ever stored once. `SyncCheckpoint.checkpoint_value`
  advances only on a fully error-free run (`apps/sync/reconciliation.py:233-246`).
- **What has never been live-verified, per the reports' own words**: the
  `celery` executor path against a real broker; end-to-end firing of the
  post-send trigger against a live BFF+Django pair (Section 6.A.1); the
  exact latency between a WAHA-accepted send and that message becoming
  visible via REST history (no timing evidence exists in the project).

### Other confirmed-complete items

- **Auth**: JWT RS256 login/`/me`, independently verified by both Django and
  the BFF; token stored in `sessionStorage` (not `localStorage`, deliberate,
  `frontend/src/lib/auth.ts:28-42` — satisfies `docs/CLAUDE.md` hard rule #3
  in spirit, since the token itself carries no WAHA credential and the WAHA
  key never reaches the browser).
- **Internal-service-key mechanism itself** (as *code*, distinct from its
  live operational status — see Section 6.A.2): `X-Internal-Service-Key`
  header, `hmac.compare_digest()` constant-time comparison
  (`backend/apps/core/internal_auth.py:18-30`), fails closed if unconfigured.
  Correctly implemented; the open issue is a live process/config-drift
  problem, not a code defect.
- **CORS**: fails closed on both sides when unconfigured
  (`bff/src/corsOptions.ts:11-25`; Django `CORS_ALLOWED_ORIGINS` — see
  `docs/generated/PHASE-7-CORS-FIX-REPORT.md`), never a wildcard,
  `credentials:false` on the BFF (no cookie-based auth).
- **GitHub publication remediation**: real PII (phone numbers, a real LID,
  real session/business names) and real internal IPs were substituted with
  synthetic placeholders across 21 doc/fixture files before the single
  publication commit; `.gitignore` broadened from `.env` to `*.env`/`.env.*`.

---

## 4. In-Progress / Partially Done Features

- **Outbound reconciliation, live status** — code-complete, unit-tested,
  architecturally sound; **live end-to-end firing is unresolved** per the
  documentation trail (Section 6.A.1). Listed here rather than purely under
  "Completed" precisely because this audit found no evidence, independent of
  the task's own framing, that closes that loop.
- **Internal-service-key channel reliability** — mechanism is correct code;
  a specific live incident (duplicate `manage.py runserver` processes) was
  diagnosed but its fix was explicitly marked "Not implemented" in the last
  report to touch it (Section 6.A.2).
- **Dashboard Row 2 "WhatsApp Sessions" card** — confirmed still an
  `EmptyState` placeholder (`frontend/src/pages/DashboardPage.tsx:152-203`,
  comment explicitly citing the multi-session dependency). Depends on the
  BFF's single-session restriction changing (`bff/src/routes/sessionGuard.ts:11-18`
  rejects any `:session` other than the one configured
  `WAHA_SESSION_NAME`) — confirmed still true, grep-verified this round.
- **Security hardening (Phase 12)** — partially done. Present:
  `X_FRAME_OPTIONS='DENY'`, `SECURE_CONTENT_TYPE_NOSNIFF=True`
  (`backend/config/settings.py:342-343`), constant-time comparisons on both
  HMAC checks, closed-allowlist WAHA calls, fail-closed CORS/internal-auth,
  JWT algorithm pinning (BFF test suite explicitly checks HS256
  algorithm-confusion rejection). **Missing**: rate limiting — explicitly
  and currently deferred, confirmed live in code:
  `backend/apps/authn/views.py:22-24` ("Rate limiting ... is explicitly
  Phase 12 ... scope, not implemented here"); no `express-rate-limit`-style
  package or DRF throttle class exists anywhere in `bff/` or `backend/`
  (grep-confirmed this round). No automated secret scanner has ever been
  run (manual `grep`/`sed` only, per `GITHUB-SECURITY-AUDIT.md`).
- **JWT scopes** — 6 scopes defined
  (`reading, sending, session control, blast, user administration, system administration`,
  `backend/config/settings.py:289-296`), all issued into every token via
  `compute_scopes()`. Enforced: `reading` (Django, `HasReadingScope`),
  `sending` + `session control` (BFF route guards). **Not enforced
  anywhere**: `blast`, `user administration`, `system administration` — no
  code path checks them (expected, since Blast/user-admin features don't
  exist yet). The frontend never reads the `scopes` claim to gate UI
  (`decodeToken()` exists in `frontend/src/lib/auth.ts` but nothing calls it
  for authorization decisions) — a cosmetic gap only, since every action a
  low-scope user could attempt is still correctly rejected server-side.

---

## 5. Pending / Not Started Features

- **Phase 9 — Offline/degraded mode.** Not started. See Section 10 for a
  full readiness assessment.
- **Phase 11 — Blast.** Zero backend presence: no Django app, no
  `BlastCampaign`/`BlastRecipient` models (both only listed as "suggested
  entities" in `docs/04-DATA-MODEL.md`, never created). The only occurrences
  of "blast" in the entire backend are the reserved-but-unenforced JWT scope
  string and one test reference to it.
- **Phase 13 — Failure/security testing.** Only partially exercised. Unit
  tests confirm webhook idempotency, outbound-operation idempotency, and
  reconciliation duplicate-safety in isolation. `docs/09-TEST-PLAN.md`'s
  eight named failure scenarios (office off / Postgres off / Redis off /
  BFF-WAHA off / network partition both directions / duplicate webhook /
  recovery reconciles / ambiguous outbound) do not have a dedicated
  multi-service integration test suite exercising them together — this
  audit found none under any `tests/` directory in either `backend/` or
  `bff/`.
- **Phase 14 — Production deployment.** Compose files exist and satisfy the
  hard rules (no Postgres service, no public WAHA port), but this audit
  found no evidence of an actual production deployment having been run or
  verified.
- **Redis health card.** `docs/03-UI-UX-SPEC.md`'s global-status example
  names WAHA/WhatsApp/Backend/Database/Sync; the Dashboard currently has
  WAHA/Backend/Database only. Grep-confirmed this round: no `redis`/`Redis`
  string anywhere in `backend/apps/core`.
- **WhatsApp / Reports / Settings pages.** Still explicit placeholders; no
  functional spec exists for any of them anywhere in `docs/`.
- **LID/JID/`@c.us` auto-merge.** Confirmed not implemented (Section 3,
  Identity). Per this task's own instruction, not implemented here either.
- **`status@broadcast` chat-list filtering.** Repeatedly recommended across
  three separate reports in the Inbox/Chat chain, never implemented.
- **Two known missing indexes**, unchanged from the prior roadmap audit:
  `chats.Message` has no index supporting a chat-agnostic `timestamp` filter
  (only `(session, last_message_at)` on `Chat`, and message ordering relies
  on `(chat, timestamp)`-shaped queries); `webhooks.WebhookEvent` has an
  index on `status` only, not `received_at`.

---

## 6. Open Questions

### A. BLOCKER

1. **Is outbound reconciliation actually firing in live use?** The last
   document in the reconciliation-trigger saga
   (`INBOX-RECONCILIATION-TRIGGER-OBSERVABILITY-AUDIT-REPORT.md`) ends with
   the root cause of the trigger not firing explicitly unresolved
   ("this task only removed the blindfold"), waiting on the user to
   reproduce and report a log line. No later report in the entire
   `docs/generated/` set closes this. This is the item most directly in
   tension with this task's framing that reconciliation is FINAL and
   manually verified. **Evidence that would resolve it** (any one of):
   recent, real row activity in `OutboundOperation`/`AuditLog`/
   `SyncCheckpoint` for the currently-connected session, timestamped after
   the Observability report; a BFF or Django log line showing a successful
   `/internal/reconciliation/trigger/` call; or a new report documenting the
   reproduction the Observability report asked for. None of these were
   available to this read-only audit.

2. **Is the internal-service-key channel actually healthy right now?**
   `INTERNAL-SERVICE-KEY-FINGERPRINT-AUDIT-REPORT.md` traced live `403`s to
   a stale `manage.py runserver` process (pre-dating a `.env` edit) still
   bound to port 8000 alongside a fresh one, with the BFF not running at
   all at audit time. The report's own recommended fix ("kill every process
   bound to port 8000/8080, verify with `netstat`, start exactly one of
   each") is explicitly marked **"Not implemented, per your instruction to
   audit only."** No later report confirms this was carried out. Since
   reconciliation-trigger, outbound-operation registration, and audit
   logging all depend on this exact channel, **this is very likely the same
   underlying issue as item 1, not an independent one** — but that is an
   inference, not confirmed by any document.

3. **Provenance gap from the squashed history.** With one git commit,
   nothing independently corroborates *when* a documented fix landed in the
   working tree, or whether a later manual edit undid it, beyond this
   audit's own direct reading of the current code (which is authoritative
   for *current* state, but silent on *history*). This affects how much
   weight any single "implementation report" should carry relative to this
   audit's own code citations, which take precedence wherever the two
   disagree.

### B. SHOULD DECIDE BEFORE NEXT FEATURE

4. **What does "Phase 9" mean going forward** — the literal canonical
   numbering (`docs/15-CODING-PHASES.md` item 9, Offline/degraded mode), or
   whatever phase is practically next? Raised and left open by the prior
   roadmap audit; still open now.
5. **Is multi-session support (2–3 sessions) still a near-term goal?**
   `docs/00-MASTER-SPEC.md` phrases it as "kemungkinan maksimal 2–3" — soft,
   not committed. This gates whether the BFF's single-session
   `sessionGuard` restriction needs to change before the Dashboard's
   sessions-summary card or any multi-session Inbox work can proceed.
6. **When does rate limiting (Phase 12) get scheduled?** No code exists yet
   for it anywhere; the login and outbound-send endpoints are both
   currently unthrottled in every environment.
7. **Should Inbox surface a "stale" state when polling fails?** Confirmed
   this round: a failed poll tick in `InboxPage.tsx` is silently skipped —
   it does not change the UI to indicate the data may be out of date. This
   is the opposite of `docs/03-UI-UX-SPEC.md`'s explicit instruction to
   label data live/cached/stale/unavailable rather than hide a failure. Not
   a bug in the sense of incorrect behavior (it was a deliberate choice to
   avoid flicker over a populated view), but a product decision about
   whether "silent" is the right choice once Phase 9 is in scope.

### C. NICE TO HAVE

8. Redis health card — isolated, additive, `CELERY_BROKER_URL` already
   configured.
9. Frontend scope-based UI gating (hide session-control/sending affordances
   from a `reading`-only-scope user) — currently cosmetic only, since
   server-side enforcement already correctly rejects unauthorized actions.
10. `status@broadcast` pseudo-chat filtering — recommended three times,
    implemented zero times.
11. An automated secret-scanner pass (e.g. `gitleaks`/`trufflehog`) before
    any further public pushes — every pass on file so far has been manual.
12. Live-browser verification of the full session-management UI (buttons,
    modal, confirm dialog, QR, pairing code) against a real WAHA instance —
    explicitly never performed, per every report that touched this feature.

### D. DOCUMENTATION ONLY

13. `docs/12-WAHA-REFERENCE.md`'s webhook-HMAC section still reads "still
    not confirmed" for the signing mechanism, which is now stale relative
    to the corroborating evidence gathered afterward (real live webhooks
    successfully verified once the Django secret was set correctly, per the
    Inbox/Chat report chain). Worth a small update; not urgent, and the
    section is already carefully hedged rather than wrong.
14. `docs/generated/PHASE-9-ROADMAP-AUDIT-REPORT.md`'s "current product
    surface" tables for Inbox and Sessions are now factually superseded by
    the work this report documents — still a useful historical record of
    the Dashboard/design-spec gap analysis, but should not be read as
    current state. This report supersedes it for that purpose.

---

## 7. Architecture Dependencies

- **Phase 9** depends on Phase 8 existing (now satisfied) **and** on a
  sync-status read surface that does not exist yet: `apps/sync/urls.py`
  exposes only the internal reconciliation-trigger endpoint — there is no
  HTTP read endpoint for `SyncCheckpoint` anywhere, and grep confirms zero
  frontend references to sync/reconciliation status at all. Phase 9 also
  depends, practically, on Section 6.A being resolved first — surfacing
  "sync health" is not meaningful while the channel that keeps sync healthy
  has an unconfirmed live status.
- **Phase 11 (Blast)** can reuse the existing `OutboundOperation`
  idempotency-key pattern directly, but needs net-new models
  (`BlastCampaign`/`BlastRecipient`, neither exists), a new Django app, and
  a resolved product decision on rate/approval limits
  (`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md` "Open: blast limits/approval" —
  still open, unchanged by anything found in this audit).
- **Redis health card** depends on nothing new — `CELERY_BROKER_URL` is
  already a configured setting; only a new view + URL + one frontend card
  following the existing `DatabaseHealthView` pattern are needed.
- **Dashboard sessions-summary card** depends on the BFF's
  single-session `sessionGuard` restriction changing, which itself depends
  on the open product decision in item 5 above.
- **Frontend scope-gating** depends on nothing new — `decodeToken()`
  already exists and already decodes the `scopes` claim; only call sites are
  missing.
- **Inbox "stale" labeling** depends on extending the health-check pattern
  (currently Dashboard-only) to the Inbox page specifically, since Inbox's
  own polling has no failure-visibility today.

---

## 8. Risks

1. **Reconciliation/internal-key channel's live status is unconfirmed**
   (Section 6.A) — the highest-impact risk in this audit, because it
   underlies the "final, verified" claim for outbound reconciliation and
   would also undermine any future feature (Blast, Phase 9 sync-status)
   built on the same BFF→Django internal channel if not actually resolved.
2. **No rate limiting anywhere** — login and outbound-send endpoints are
   currently exposed to unlimited request volume from any authenticated (or,
   for login, unauthenticated) client.
3. **No automated secret scanning** — the only defense against a future
   accidental secret commit is manual review, same as the process that was
   used (successfully, but by hand) before the one existing publication
   commit.
4. **No frontend test suite at all** — any regression in Inbox or Sessions
   UI would only be caught by manual browser testing, none of which is
   documented as having been performed for either feature.
5. **Structural single-session constraint** — `sessionGuard`'s restriction
   is a design decision embedded in route-handling logic, not a config
   toggle; changing it for multi-session support is an additive-but-real
   code change, not a flag flip.
6. **WAHA webhook HMAC scheme remains an assumption about WAHA's own
   behavior**, not something confirmed from WAHA's documentation or a
   captured raw signature — mitigated (not eliminated) by real live webhook
   evidence found in the digested reports. Worth re-confirming if the pinned
   WAHA version (`2026.9.1`, per `docs/12-WAHA-REFERENCE.md`) is ever
   upgraded.
7. **Two known missing DB indexes** — minor performance risk at current
   scale, not urgent, unchanged from the prior audit's finding.
8. **Local dev process hygiene** (duplicate `manage.py runserver` instances)
   is itself a recurrence risk, independent of whether it's the actual root
   cause of item 1 above — nothing in the repo guards against it happening
   again.

---

## 9. Candidate Next Steps

Presented as dependency facts only — **no ranking, no product choice made
here**, per instruction.

**A. Resolve the reconciliation-trigger / internal-service-key open items
(Section 6.A).** This is verification, not new feature work. No
prerequisites. Everything that depends on the internal-service-key channel
(reconciliation, any future Blast outbound work, any future audit-log
consumer) benefits from knowing its real state first.

**B. Phase 9 — Offline/degraded mode.** Its primary prerequisite (Phase 8)
is satisfied. Concretely missing before it can be scoped as more than "read
the Dashboard pattern again": a `SyncCheckpoint` read endpoint (net new — no
HTTP surface exists for it today), a Redis health check (net new, small), and
a decision on Inbox-specific stale-state UX (Section 6.B.7). Practically
benefits from Candidate A being resolved first (surfacing sync health is
hollow if the underlying channel's reliability is itself unknown).

**C. Phase 11 — Blast.** Needs a new Django app and two new models from
scratch; needs a resolved rate/approval-limits decision
(`docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`, still open); can reuse the
existing `OutboundOperation` idempotency pattern directly. No dependency on
Phase 9 or on Candidate A, though it would inherit the same internal-channel
risk if that risk turns out to be systemic rather than incident-specific.

**D. Phase 12 — Security hardening completion.** Mainly rate limiting
(login, send, session control, blast, sync, per `docs/06-SECURITY.md`'s
named list) — the rest of that document's items are already implemented.
Independent of Phases 9 and 11.

**E. Small, independent items** — no dependency on anything above, could be
done alongside any of A–D: Redis health card; `status@broadcast` chat-list
filter; frontend scope-based UI gating; an automated secret-scanner pass.

---

## 10. Phase 9 Readiness

**Canonical definition** (`docs/15-CODING-PHASES.md` item 9): "Offline/degraded
mode." **Basis in the master spec**: `docs/00-MASTER-SPEC.md` "Availability" —
WAHA/Tencent must keep working when the office server is down; features
needing office persistence degrade with a clear status; reconciliation fixes
data once office returns. **Basis in the UI spec**: `docs/03-UI-UX-SPEC.md`
requires a global status distinguishing WAHA / WhatsApp / Backend / Database /
Sync, and instructs that data be labeled live/cached/stale/unavailable rather
than the whole system reading as "offline."

**Dependency check**:
- Phase 8 (the main durable-data feature to degrade) — **satisfied**,
  code-confirmed in Section 3, unlike the prior roadmap audit's finding
  (written before Phase 8 existed).
- A concrete UI surface to degrade — **now exists** (Inbox).

**Gaps that remain before Phase 9 can be concretely scoped**, all confirmed
by direct inspection this round:
1. No HTTP read endpoint exists for `SyncCheckpoint` anywhere in the backend
   — `apps/sync/urls.py` only exposes the internal trigger endpoint. The UI
   spec's "Sync: STALE/OK" line has nothing to read from today.
2. No Redis health check exists anywhere (`backend/apps/core` grep-confirmed
   clean of any `redis`/`Redis` reference).
3. Inbox's polling failure behavior is silent-skip, not stale-labeling — the
   opposite of what the UI spec asks for (Section 6.B.7).
4. The Dashboard already implements the closest existing analog (3 of the
   spec's named signals: WAHA, Backend, Database) — a reusable pattern, not
   a gap by itself, but Phase 9 still needs a scope decision: extend this
   pattern to Inbox specifically, to every durable-data page, or something
   broader. Nothing in the docs decides this.

**Ambiguity between documentation and code**: none found that blocks
scoping — the canonical docs are internally consistent about what Phase 9
should cover. The open ambiguity is in scope *breadth* (gap 4), which is a
product decision, not a doc/code contradiction.

**Conclusion**: Phase 9 is now **definable** (its blocking prerequisite from
the prior audit — Phase 8 not existing — is resolved), but not yet
**ready to start** without first: (a) resolving the reconciliation/internal-key
open items, since a sync-health indicator is not meaningful to build on top
of a channel whose live reliability is itself unconfirmed, and (b) a product
decision on scope breadth (gap 4). Neither of these is a large effort, but
both are prerequisites this audit found, not assumptions it invented.

---

## 11. Documentation Drift

- **`docs/12-WAHA-REFERENCE.md`** — webhook HMAC section reads "still not
  confirmed" in a way that is now more hedged than the evidence on file
  supports (Section 6.D.13). Low priority; the hedge is honest, just dated.
- **`docs/generated/PHASE-9-ROADMAP-AUDIT-REPORT.md`** — its Section 1
  product-surface tables for Inbox and Sessions are factually superseded by
  this report (Section 6.D.14). It remains a valid historical record of the
  Dashboard/design-spec gap analysis performed at that time.
- **`docs/07-API-CONTRACT.md`** — already contains its own correction note
  pointing at `INBOX-CHAT-DECISION-REPORT.md` for the
  Frontend→Django-vs-BFF resolution on chats/messages/mark-read. Confirmed
  consistent with the actual code (`GET /api/chats/` etc. live under
  Django, not the BFF) — cited here only to confirm this is **not** drift,
  since the self-correction is easy to misread as stale text on a first
  pass.
- No other canonical doc (`00`, `01`, `02`, `03`, `04`, `05`, `06`, `08`,
  `09`, `10`, `11`, `13`, `14`, `docs/CLAUDE.md`) was found to contradict
  current code in this audit's review. They describe the system at a level
  general enough that the current implementation reads as a consistent
  refinement of what they specify, not a departure from it.

---

## 12. Recommended Investigation Order

Dependency-driven only — **not a priority ranking**, per instruction.

1. **Resolve Section 6.A (reconciliation-trigger / internal-service-key live
   status).** No prerequisites. Cheapest available check without a live
   send: read-only inspection of current `OutboundOperation`/`AuditLog`/
   `SyncCheckpoint` row counts and most-recent timestamps in the real
   database, and/or a process check confirming exactly one `manage.py
   runserver` (or production WSGI process) and one BFF process are running.
   Everything else in this list is more trustworthy once this is settled.
2. **If item 1 is confirmed healthy**, no further action is needed there. If
   it is not, it becomes a hard prerequisite for trusting any future feature
   that shares the same BFF→Django internal channel — most notably Blast
   (Candidate C) and Phase 9's sync-status surfacing (Candidate B).
3. **Decide Section 6.B items 4 and 5** — what "Phase 9" means going forward,
   and whether multi-session is still a near-term goal. Both are cheap,
   independent product decisions with no code dependency, and both unblock
   downstream scoping work (Dashboard sessions card, Phase 9 breadth).
4. **With 1–3 settled**, Phase 9 has the fewest remaining unresolved
   prerequisites of any not-yet-started phase (its blocking dependency,
   Phase 8, is done; its remaining gaps — a `SyncCheckpoint` read endpoint,
   a Redis health check, Inbox stale-state UX — are all small and additive).
   This is a structural observation about readiness, not a recommendation to
   build it before Blast or Security Hardening.
5. **Blast (Phase 11) and Security Hardening (Phase 12)** can be scoped
   independently of Phase 9 and of each other, in parallel with the above —
   Blast is gated on its own open product decision (rate/approval limits,
   `docs/11-DECISIONS-AND-OPEN-QUESTIONS.md`), Security Hardening is gated
   mainly on implementing rate limiting across the already-identified
   endpoint list.

---

This was a read-only audit. No implementation was performed and none should
follow automatically from this report — per instruction, stop here.
