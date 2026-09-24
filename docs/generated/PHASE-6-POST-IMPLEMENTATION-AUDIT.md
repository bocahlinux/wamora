# Phase 6 — Post-Implementation Contract Audit

Read-only audit. No code, model, migration, frontend, configuration, or
live WAHA state was modified. No state-changing WAHA endpoint was
called — this audit re-read source files and reasoned about them; it did
not execute the application or any test beyond what's already recorded
in `PHASE-6-IMPLEMENTATION-REPORT.md`. Phase 7 was not started.

## Executive summary

The implementation matches `docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md`
closely. The specific discrepancy flagged for investigation — whether
the implemented `/messages` route is a WAHA chat/message-history proxy —
**is not a violation**: it is confirmed, by direct source inspection, to
be the send-message endpoint only (`POST`, calls WAHA's `sendText`), and
no route, allowlist entry, or test anywhere in the BFF touches WAHA's
chat list or message history. The implementation report's phrasing
("...messages)") was imprecise shorthand that could be misread in
isolation, not a description of what the code actually does.

Independent of that question, this audit found **one genuine
non-compliance** (the send-message flow's audit trail has no local-log
fallback when Django is fully unreachable, unlike every other route) and
**two items needing your clarification** (JWT key-rotation support is
partially built — Django issues a `kid` but the BFF never uses it to
select among multiple keys — and the `providerMessageId` extraction
guesses a specific WAHA field name while its own comment claims it
doesn't guess). None of these block Phase 7; all are narrow and
independently fixable.

## Contract compliance table

| Area | Verdict | Notes |
|---|---|---|
| Route set (8 BFF routes + `/health`) | COMPLIANT | Exact match to contract Section 2's table — verified against `bff/src/app.ts` and every file under `bff/src/routes/` |
| HTTP methods/paths | COMPLIANT | Verified against `wahaAllowlist.ts` and each route file directly |
| `/messages` = send, not history-proxy | COMPLIANT | No `GET` chats/history route or allowlist entry exists anywhere in `bff/src` |
| JWT authentication (RS256, issuer/audience/expiry) | COMPLIANT | `algorithms: ['RS256']` explicitly pinned (`bff/src/jwt.ts`) — rejects algorithm-confusion attempts, tested |
| JWT key rotation (`kid`) | NEEDS CLARIFICATION | Django issues `kid` (`apps/authn/jwt_utils.py`); BFF's `verifyToken` accepts only one static public key and never inspects `kid` |
| Scope → route authorization | COMPLIANT | Verified route-by-route below |
| WAHA allowlist | COMPLIANT | Structurally closed — `callWaha()` only accepts one of 8 named keys; no chat/history endpoint is a member |
| Outbound idempotency state machine | COMPLIANT | Matches contract Section 9's transition table exactly, including the FAILED-never-stale-retryable rule |
| `providerMessageId` field extraction | NEEDS CLARIFICATION | Code assumes WAHA's success response field is named `id`; comment claims no assumption is made — imprecise, and untested for a different field name |
| Audit-after-resolution sequencing | COMPLIANT | Verified: WAHA call always resolves before any audit write, for all 9 sensitive actions |
| Audit local-log fallback | **NON-COMPLIANT** (narrow) | Present for lifecycle/QR/pairing-code (`auditHelper.recordAudit`); **absent** for send-message (`messages.ts` calls `djangoClient.resolveOutboundOperation` directly) |
| Django↔BFF internal auth | COMPLIANT | Shared secret, constant-time compare, fails closed when unconfigured |
| WAHA credential isolation | COMPLIANT | Never in any BFF response; asserted directly in tests |
| Session-scoped key vs. single-session implementation | COMPLIANT | Matches the documented v1 scope decision exactly — one configured session, no session→key map |
| QR/pairing adapter | COMPLIANT | Minimal envelope, binary-safe (base64), isolated to one file; `expiresInSeconds` never populated (IMPLEMENTATION DETAIL, not attempted, not a violation) |
| Error/status mapping | COMPLIANT | 401/403/404/400/409/502 all match the contract's Section 13 table, including the `409 requires_new_idempotency_key` case |
| Phase 6/7/8/9/10/12/14 boundary | COMPLIANT | No frontend, chat/message-read, UI, rate-limiting, or deployment code was touched |
| Schema/migrations | COMPLIANT | None created; none required (unchanged since the implementation report) |

## Route-by-route audit

| Route | Method | Contract scope | Implemented scope | Verdict |
|---|---|---|---|---|
| `/health` | GET | none | none | COMPLIANT |
| `/api/sessions/:session/status` | GET | `reading` | `reading` | COMPLIANT |
| `/api/sessions/:session/start` | POST | `session control` | `session control` | COMPLIANT |
| `/api/sessions/:session/stop` | POST | `session control` | `session control` | COMPLIANT |
| `/api/sessions/:session/restart` | POST | `session control` | `session control` | COMPLIANT |
| `/api/sessions/:session/logout` | POST | `session control` | `session control` | COMPLIANT |
| `/api/sessions/:session/qr` | GET | `session control` | `session control` | COMPLIANT |
| `/api/sessions/:session/pairing-code` | POST | `session control` | `session control` | COMPLIANT |
| `/api/sessions/:session/messages` | POST | `sending` | `sending` | COMPLIANT — confirmed send-only (see below) |

**On the flagged discrepancy, specifically**: `bff/src/routes/messages.ts`
contains exactly one handler, `router.post('/sessions/:session/messages', ...)`.
It (1) validates `Idempotency-Key` + `chatId`/`text`, (2) registers/looks
up an `OutboundOperation` via Django, (3) calls WAHA's `sendText`
endpoint (`callWaha('sendText', ...)` → `POST /api/sendText`), (4)
resolves the operation and writes its audit row. There is no code path
that calls WAHA's chat-list or message-history endpoints, and
`WAHA_ALLOWED_ENDPOINTS` (`bff/src/wahaAllowlist.ts`) has no member for
either — meaning it would be a TypeScript compile error to even attempt
one from this file. **If this route is ever changed to proxy message
history, that would be the contract violation; the route as it exists
today is not one.** Recommend only a documentation clarity fix: the
implementation report's shorthand `"...messages)"` should read
`"...messages — send only)"` in any future revision, to avoid this exact
question recurring.

## Authentication/authorization audit

- **Signing/verification**: RS256 only, explicitly pinned on both ends
  (`jwt.encode(..., algorithm=settings.JWT_ALGORITHM)` where
  `JWT_ALGORITHM = 'RS256'` is a hardcoded Django setting; BFF's
  `jwt.verify(token, publicKey, {algorithms: ['RS256'], ...})`). An
  HS256-signed token using the public key as an HMAC secret is rejected
  (tested) — the classic algorithm-confusion attack is closed. COMPLIANT.
- **Claims**: `sub`, `iss`, `aud`, `iat`, `exp`, `scopes` all present and
  checked (issuer/audience/expiry via the `jsonwebtoken` library's
  built-in verification, not hand-rolled). COMPLIANT.
- **Scope computation**: `compute_scopes()` — superuser gets all six
  scope names; otherwise, scopes are exactly the `JWT_SCOPES` names that
  match a Django `Group` the user belongs to. `Group` is already
  registered in Django admin by default, so this is immediately usable
  without further code. Matches the contract's "implementation detail,
  Django Group remains the system of record" framing. COMPLIANT.
- **Key rotation** (`kid`): Django's `issue_access_token` sets
  `headers={'kid': settings.JWT_KID}` on every issued token. The BFF's
  `verifyToken(token, {publicKey, issuer, audience})` takes a single
  static public key and never reads the token's `kid` header to select
  among candidates. **This means the contract's described rotation
  mechanism ("retain the old public key briefly... `kid` tells the BFF
  which key to use") is not actually implemented** — only single-key
  verification exists today. This does not break anything at the
  project's current scale (one key, no rotation has happened), but the
  contract's Section 4 labeled the rotation *mechanism* "FINAL," which a
  reader could reasonably take to mean it was built. **NEEDS
  CLARIFICATION**: was multi-key/`kid`-based verification expected in
  this implementation pass, or is single-key-only acceptable until a
  rotation is actually needed?
- **`INTERNAL_SERVICE_KEY`**: constant-time comparison
  (`hmac.compare_digest`), fails closed when unconfigured or when the
  header is empty (verified directly in `apps/core/internal_auth.py` and
  its test file). Distinct from end-user JWTs — confirmed no code path
  accepts a JWT in place of this header or vice versa. COMPLIANT with
  contract requirement #12.

## Idempotency audit

Verified `apps/operations/views.py` against contract Section 9's
transition table line by line:

- First request → `get_or_create` inserts `PENDING`. Matches.
- Duplicate, existing `PENDING`/`SENT` → returned as-is, `retryable`
  always `False` for `SENT` (not in the retryable status set) and
  correctly time-gated for `PENDING`. Matches.
- Duplicate, existing `FAILED` → `retryable` is `False` **unconditionally**,
  regardless of `updated_at` age — confirmed in code (`FAILED` is not a
  member of the tuple checked for staleness) and confirmed by a
  dedicated test (`test_stale_failed_row_is_still_not_retryable`).
  Matches the contract's explicit "FAILED is never stale-retry-eligible"
  rule precisely.
- Duplicate, existing `UNKNOWN`, fresh → not retryable. Matches.
- Duplicate, existing `UNKNOWN`/`PENDING`, stale (`updated_at` older than
  `OUTBOUND_OPERATION_STALE_SECONDS`, default 30) → `retryable: true`,
  and the BFF (`messages.ts`) falls through to call WAHA again **using
  the same operation id**, not a new row. Matches.
- WAHA success/failure/timeout → `sent`/`failed`/`unknown` respectively,
  via `resolveOutboundOperation`. Matches.
- Django unreachable at registration → BFF proceeds to WAHA anyway
  (`djangoClient.postJson` returns `{ok: false}` on any network failure
  or non-2xx, and `messages.ts` checks `registration.ok` before deciding
  to short-circuit — an unreachable Django means `registration.ok` is
  `false`, so the code falls through to calling WAHA). Matches, and
  tested (`'proceeds to WAHA when Django is unreachable at registration time'`).

**No schema change was used or needed** — `retryable` is computed from
the existing `updated_at` (`auto_now=True`) at read/resolve time, never
stored.

## Audit-log audit

- **Sequencing**: confirmed — every one of the 9 sensitive actions
  (start/stop/restart/logout/qr/pairing-code/send, and status/health
  which are non-sensitive reads) writes its audit record only after the
  WAHA call's outcome is known, never before. No code path constructs an
  `AuditLog`/calls `writeAuditEvent`/`resolveOutboundOperation` prior to
  the `callWaha` result being available. COMPLIANT with the
  audit-after-resolution requirement and with `AuditLog.result` having
  no "pending" choice.
- **Actor linkage**: `req.auth?.sub` (the JWT subject, a stringified
  Django user PK) flows into every audit call, converted back to an
  integer FK on the Django side (`toActorId`). COMPLIANT.
- **Local-log fallback — confirmed gap**: `bff/src/auditHelper.ts`'s
  `recordAudit()` emits a `console.log` structured line *before*
  attempting the Django write, so the fallback trail exists regardless
  of Django's reachability — this is used by all three lifecycle-style
  routes (`session.ts`: start/stop/restart/logout/qr/pairing-code, via
  `recordAudit`). **`messages.ts` never calls `recordAudit` at all** — it
  calls `djangoClient.resolveOutboundOperation` directly, which has no
  local-log side effect. **Practical consequence**: if Django is
  unreachable at the moment a send resolves (whether the send itself
  succeeded or failed against WAHA), there is currently **no record
  anywhere** — not even a local log line — that the action happened, for
  that one route only. Every other sensitive action retains at least the
  local fallback in the same failure scenario. **Classified NON-COMPLIANT**
  against contract Section 10's stated mitigation ("the BFF also emits a
  structured local log line for every sensitive action, independent of
  Django's reachability") — "every" did not carve out an exception for
  sends, and the code does. **Recommended correction** (not made by this
  audit): route the send-message resolve step through the same local-log
  helper, or add an equivalent `console.log` call in `messages.ts`
  immediately before `resolveOutboundOperation`.

## WAHA boundary audit

- Allowlist (`bff/src/wahaAllowlist.ts`) contains exactly the 8 members
  the contract's Section 2 table lists — `getSessionStatus`,
  `startSession`, `stopSession`, `restartSession`, `logoutSession`,
  `getQr`, `requestPairingCode`, `sendText`. No `delete`, no
  create/update, no chat-list, no message-history member exists.
  Confirmed by direct read and by `wahaAllowlist.test.ts` (which asserts
  the exact key set). COMPLIANT with `CLAUDE.md` rule 5.
- **Enforcement is structural, not just tested**: `callWaha()`'s first
  parameter is typed `WahaEndpointName`, a union of exactly those 8
  string literals — calling it with anything else is a compile-time
  TypeScript error, not a runtime check that could be bypassed by a
  future careless edit. This is a stronger guarantee than a runtime
  allowlist check and is noted as a positive finding, not just
  COMPLIANT.
- WAHA API key: read only from `config.wahaApiKey` (server-side env),
  never appears in any response body (asserted directly in
  `routes.session.test.ts`/`routes.messages.test.ts`/`routes.health.test.ts`),
  never sent as a query parameter (asserted in `wahaClient.test.ts`).
  COMPLIANT.
- Session-scoping: the BFF holds one API key, for one configured session
  (`WAHA_SESSION_NAME`); any `:session` path parameter not matching it is
  rejected with `404` before any WAHA call is attempted
  (`sessionGuard.ts`). This matches the documented v1 decision precisely
  — the contract's "session-scoped key" and "dedicated key" options are
  operationally identical at the BFF's call site (an API key value), so
  there is no code-level distinction to audit between them; which one is
  actually minted is an operational choice outside this code. COMPLIANT.

## Django boundary audit

- Two internal endpoints exist exactly where the contract specifies:
  `POST /internal/outbound-operations/`, `PATCH /internal/outbound-operations/<id>/`,
  `POST /internal/audit-events/`. Both apps' `urls.py` confirmed directly.
- Both are gated by `HasInternalServiceKey` only — `authentication_classes
  = []` on every internal view, confirming the end-user JWT is never
  involved in these calls (contract requirement #12). COMPLIANT.
- No model was modified. `OutboundOperation.audit_log` (pre-existing FK)
  and `TimeStampedModel.updated_at` (pre-existing, `auto_now=True`) are
  the only schema elements these new views depend on. COMPLIANT with "do
  not modify database models unless the contract explicitly permits it"
  — nothing here required permission to modify anything, since nothing
  was modified.
- `apps.authn` (new app) has no models — `makemigrations --check
  --dry-run` reported "No changes detected" both at the time of the
  implementation report and re-confirmed by inspecting the app's file
  list now (`apps/authn/` contains no `models.py`/`migrations/`).

## Phase boundary audit

No file outside `backend/apps/{authn,operations,audit,core}/*`,
`backend/config/{settings,urls}.py`, `backend/requirements.txt`,
`backend/.env.example`, `bff/*`, and the two infrastructure
`.env.example` files was touched (cross-checked against the file list in
`PHASE-6-IMPLEMENTATION-REPORT.md` Section 3 and re-verified by
re-reading the current state of every file this audit inspected).
Specifically confirmed absent from this round's changes:

- `frontend/` — untouched (Phase 7).
- Any Django DRF endpoint serving chats/chat-detail/message-history
  (Phase 8) — none exists anywhere in `apps/chats` or elsewhere.
- Any offline/degraded-mode UI logic (Phase 9) — no UI exists at all.
- Any session-management *screen* (Phase 10) — no UI exists at all.
- Rate limiting on `/api/auth/login/` or any other route (Phase 12) —
  confirmed absent; `LoginView`'s own docstring explicitly defers this.
- `apps/webhooks/parsing.py`'s `session.status` handling extension, and
  any change to WAHA's live webhook target (Phase 14 / operational) —
  both untouched, correctly left as documented dependencies.

No boundary violation found.

## Test coverage audit

236 tests exist (168 Django + 68 BFF, per the implementation report);
this audit did not re-run them (no code changed, so no re-run was
necessary to trust the previously-reported result), but did read the
test files to check for the specific "false confidence" failure mode
this task asked about:

- **`providerMessageId` extraction** (`messages.ts` assumes WAHA's
  `sendText` success response has a field literally named `id`): the
  only test exercising the success path (`'first request: registers,
  calls WAHA, resolves to sent'`) mocks exactly `{id: 'wa-msg-1'}`,
  which means the test *passes regardless of whether this assumption is
  correct* — it never exercises the case where WAHA's real field is
  named something else (e.g. `messageId`). The code itself degrades
  gracefully in that case (`providerMessageId` becomes `undefined`
  rather than throwing), so nothing is *broken* by this gap, but the
  test suite does not currently prove that graceful degradation, and the
  code comment ("never guessed at with false confidence") overstates
  what the code actually does — it does make a specific, reasonable, but
  unconfirmed guess. **Recommended correction** (not made by this
  audit): add a test where the mocked WAHA response has no `id` field,
  asserting the send still returns `200 {status: 'sent',
  providerMessageId: undefined}` rather than failing; soften the comment
  to say "a best-effort guess at the field name, not a confirmed one."
- **The `404→409` QR mapping test** locks in the BFF's own policy
  decision (documented as "proposed, WAHA-unconfirmed" in the contract)
  as if it were a confirmed fact about WAHA. This is not false confidence
  about WAHA's behavior — it correctly tests the BFF's chosen mapping
  policy, which is a legitimate thing to pin down regardless of whether
  WAHA is later found to behave differently (at which point the policy,
  not the test, would need revisiting). Not flagged as a problem.
- **No test currently exists proving the send-message audit-fallback
  gap** (the NON-COMPLIANT finding above) — this is not itself false
  confidence, since no test claims that fallback exists for sends; it's
  simply an untested, unimplemented area now identified for the first
  time by this audit rather than by a test.
- No other test was found asserting a specific, unconfirmed WAHA
  response field as if it were documented fact, outside the one item
  above.

## Confirmed discrepancies

1. **NON-COMPLIANT**: send-message flow has no local-log audit fallback
   when Django is unreachable, unlike every other sensitive action
   (Audit-log audit section, above).
2. **NEEDS CLARIFICATION**: JWT key rotation (`kid`-based multi-key
   verification) is issued by Django but not consumed by the BFF —
   single-key verification only exists today (Authentication/authorization
   audit section, above).
3. **NEEDS CLARIFICATION**: `providerMessageId` extraction assumes a
   specific, unconfirmed WAHA field name (`id`); its own code comment
   overstates the neutrality of this assumption, and no test exercises
   the case where the assumption is wrong (Test coverage audit section,
   above).

The originally-flagged `/messages` question is **not** a discrepancy —
confirmed COMPLIANT by direct source inspection (Route-by-route audit
section, above).

## Non-blocking dependencies

Unchanged from `PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md` Section 15 and
`PHASE-6-IMPLEMENTATION-REPORT.md` Section 5/6 — re-confirmed still
accurate, not re-litigated here: the frontend (Phase 7), Django
chat/message read endpoints (Phase 8), webhook target correction and
`session.status` parser extension (Phase 14 / `apps/webhooks`), and rate
limiting / broader security hardening (Phase 12).

## Recommended corrections, if any

Per this task's instruction, **no correction was made by this audit.**
For your consideration before or alongside Phase 7:

1. Add a local-log fallback to the send-message resolve step, matching
   what every other route already has (addresses discrepancy 1).
2. Decide whether BFF-side `kid`-based multi-key JWT verification is
   needed now or can remain single-key until an actual rotation is
   planned; document whichever is chosen (addresses discrepancy 2).
3. Either confirm WAHA's real `sendText` success field name via a future
   live-verification round and rename the assumption accordingly, or
   soften the code comment and add the missing-field test case now
   (addresses discrepancy 3).
4. Optional documentation-only fix: reword
   `PHASE-6-IMPLEMENTATION-REPORT.md`'s "...messages)" to "...messages —
   send only)" so this exact question doesn't need re-investigating
   later.

None of these require a schema change, a live WAHA call, or touching
`frontend/`.

---

## PHASE 6 VERIFIED — READY FOR PHASE 7

The one confirmed non-compliance (send-message audit-fallback gap) and
the two clarification items are narrow, well-understood, and each
independently fixable without touching Phase 7's own scope or requiring
a live WAHA session. Nothing found here contradicts the architecture,
reopens a schema question, or requires re-deciding anything the
architecture contract already settled. Recommend fixing item 1 (the
audit-trail gap) before or shortly after Phase 7 begins, since it's a
real, if narrow, observability gap — but it does not block starting
Phase 7 itself.
