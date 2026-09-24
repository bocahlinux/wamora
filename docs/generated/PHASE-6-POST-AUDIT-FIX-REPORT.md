# Phase 6 — Post-Audit Fix Report

Narrow correction of the three items identified in
`docs/generated/PHASE-6-POST-IMPLEMENTATION-AUDIT.md`. No database model
or migration was changed, no frontend file was touched, no live WAHA
endpoint was called (every test uses mocked `fetch`/HTTP, exactly as in
every prior Phase 6 round), and no unrelated file was modified. Phase 7
was not started.

## Findings addressed

### 1. NON-COMPLIANT — send-message audit fallback

**Fixed.** `bff/src/auditHelper.ts` was refactored to export the local
`console.log` fallback logic as its own function, `logAuditFallback()`,
separately from `recordAudit()` (which now just calls
`logAuditFallback()` followed by the Django write — no logic was
duplicated, only extracted). `bff/src/routes/messages.ts` now calls
`logAuditFallback()` directly, unconditionally, immediately after the
WAHA call's outcome is known and immediately before attempting the
Django resolve — matching the exact ordering every other sensitive route
already used via `recordAudit()`.

**Sequencing preserved exactly as required**:
- Still strictly audit-*after*-WAHA-resolution — `finalStatus` is
  computed from the real WAHA result before `logAuditFallback()` is ever
  called; no code path logs or writes an audit record before the WAHA
  call completes.
- No "pending" audit state was introduced — the fallback line, like the
  durable `AuditLog` row, only ever carries a final `success`/`failure`
  result.
- No `AuditLog` schema change.
- Actor identity (`req.auth?.sub`, the JWT subject) flows into the
  fallback line exactly as it already flowed into the Django write — the
  same value, sourced the same way.
- If the Django write still succeeds, behavior is unchanged — the
  fallback line is additive, not a replacement; `resolveOutboundOperation`
  is still called exactly as before when `operationId` is defined.
- **The fallback now fires even when registration itself failed**
  (`operationId` undefined — Django unreachable from the very start of
  the flow), which is the single clearest case where a record of the
  action mattered and previously there was none at all. This slightly
  broadens where the fallback fires versus the narrowest possible fix,
  deliberately — a partial fix that still left the "Django was down for
  the whole request" case silent would not have actually closed the gap
  the audit found.

**Tests added** (`bff/test/routes.messages.test.ts`, new `describe('local
audit fallback ...')` block, 3 tests; `bff/test/auditHelper.test.ts`, new
file, 4 tests):
- Normal case: Django reachable — fallback line emitted **and** the
  Django write still happens (asserted together, proving the fallback is
  additive, not a substitute).
- Django unreachable for the entire flow (both register and resolve
  calls fail) — fallback line still emitted, response to the frontend
  still succeeds.
- A failed send (WAHA returns an error) — fallback line correctly
  carries `result: "failure"`.
- Direct unit tests of `logAuditFallback`/`recordAudit` in isolation,
  including a check that no credential value ever appears in the logged
  line.

### 2. JWT `kid` clarification

**Fixed — documentation/comments only, no redesign, no multi-key support
added**, per the explicit instruction not to build rotation unless the
contract already required it (it didn't; it just described the
mechanism as `FINAL` when only single-key verification was actually
built).

- `docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md` Section 4's
  "Rotation" bullet was rewritten to state plainly: v1 is single-key
  verification only; `kid` is present in every issued token but is never
  read by the BFF's verifier; a real rotation mechanism (multiple keys,
  `kid`-based selection) is **not implemented** and is a **DEPENDENCY**
  on future work, not a built "FINAL (mechanism)" as the section
  previously implied. The "Key distribution" bullet's "a static 1–2-key
  set" wording was also corrected to "a static key" (singular), since a
  second key isn't actually held anywhere today.
- `bff/src/jwt.ts` and `backend/apps/authn/jwt_utils.py` both gained an
  explicit comment stating the same thing at the code level: `kid` exists
  for forward compatibility only and is currently inert.
- **No key registry, JWKS endpoint, database table, or refresh-token
  system was added** — none of that was requested, and none was built.

**Tests added** (`bff/test/jwt.test.ts`, 2 new tests) to accurately
document the chosen v1 behavior as a passing test rather than leaving it
implicit:
- A token signed with an arbitrary, unrecognized `kid` still verifies
  successfully (proves `kid` is not used for key lookup).
- A token with no `kid` header at all also still verifies successfully.

### 3. WAHA send response `providerMessageId`

**Fixed — comment corrected, behavior confirmed already-correct, test
added.** No live WAHA call was made or needed for this fix.

- The code in `bff/src/routes/messages.ts` already resolved successfully
  without throwing when WAHA's response lacks an `id` field
  (`typeof body.id === 'string' ? body.id : undefined` — a type-guarded
  read, not a direct property access that could throw). **No functional
  change was required here** — the audit's concern was specifically that
  the accompanying comment claimed *"never guessed at with false
  confidence"* while the code does make a specific (reasonable, but
  unconfirmed) guess at the field name `id`. The comment was rewritten to
  say exactly that: `id` is "a best-effort, unconfirmed guess... not a
  documented fact," and its absence "still resolves successfully as
  `sent`... rather than throwing or guessing at an alternative field
  name" — accurate on both counts now.
- **No alternative field names were introduced** (e.g. no fallback chain
  trying `messageId`, `_id`, etc.) and **no message-body/timestamp
  correlation heuristic was added** — both explicitly forbidden by this
  task, and neither was needed to close the gap the audit found.

**Test added** (`bff/test/routes.messages.test.ts`): a WAHA success
response containing no `id` field (a different field, `someOtherField`,
is present instead) — asserts the send still returns `200 {status:
"sent", providerMessageId: undefined}`, and that the Django resolve call
still receives `provider_message_id: ""` — proving the graceful
degradation the comment now describes.

## Exact files changed

| File | Change |
|---|---|
| `bff/src/auditHelper.ts` | Extracted `logAuditFallback()` as its own export; `recordAudit()` now calls it rather than duplicating the `console.log` logic |
| `bff/src/routes/messages.ts` | Calls `logAuditFallback()` unconditionally after the WAHA outcome is known; corrected the `providerMessageId` comment |
| `bff/src/jwt.ts` | Added an explicit v1-single-key-only doc comment |
| `backend/apps/authn/jwt_utils.py` | Added the matching explicit v1-single-key-only doc comment |
| `docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md` | Corrected Section 4's "Rotation" and "Key distribution" bullets to match actual v1 behavior |
| `bff/test/routes.messages.test.ts` | +4 tests: no-`id`-field success case, 3-test audit-fallback `describe` block |
| `bff/test/jwt.test.ts` | +2 tests: `kid` ignored for verification (arbitrary `kid`, and no `kid` at all) |
| `bff/test/auditHelper.test.ts` | New file, 4 tests: direct unit coverage of `logAuditFallback`/`recordAudit` |

8 files changed, all within `bff/`, `backend/apps/authn/`, or
`docs/generated/`. Nothing outside these was touched — cross-checked
directly by file-modification-time against
`PHASE-6-POST-IMPLEMENTATION-AUDIT.md`'s own creation time.

## Audit fallback behavior (current, corrected state)

Every one of the 9 sensitive BFF actions (start, stop, restart, logout,
qr, pairing-code, and now send) now emits the same local structured
`console.log` line — `{type: "audit", actor_id, action, target, result,
timestamp}` — unconditionally, before or regardless of whether the
corresponding Django write succeeds. `status`/`health` (non-sensitive
reads) still do not, unchanged, consistent with the contract's "sensitive
operations" framing (`docs/06-SECURITY.md`).

## JWT v1 key behavior and `kid` decision

**Confirmed, documented, and now tested**: v1 uses exactly one
statically-configured RS256 public key on the BFF side. `kid` is issued
on every token (forward-compatible) but is not read or used for key
selection anywhere. No rotation mechanism exists. This is now stated
consistently in the contract document, both pieces of code, and a test
in `bff/test/jwt.test.ts` that would fail if a future change silently
started requiring `kid` to match something. Multi-key rotation, if
needed later, remains a scoped, not-yet-designed `DEPENDENCY` — explicitly
not built this round, per instruction.

## WAHA `providerMessageId` assumption

**Unchanged in substance, corrected in description, now tested.** The
field name `id` remains a best-effort assumption about WAHA's real
`sendText` success response — still unconfirmed by any live call (none
was made or permitted this round). The send flow already degraded
gracefully when the assumption doesn't hold; this is now explicitly
tested and accurately described in code, rather than implicitly relied
upon.

## Tests executed and exact results

**BFF** (`npx vitest run`):
```
Test Files  8 passed (8)
     Tests  78 passed (78)
```
(68 from the implementation report + 10 new this round: 3 audit-fallback
integration tests + 1 no-`id`-field test in `routes.messages.test.ts`, 2
`kid`-ignored tests in `jwt.test.ts`, 4 unit tests in the new
`auditHelper.test.ts`.)

**TypeScript type-check** (`npx tsc --noEmit`): clean, no errors.

**BFF production build** (`npm run build`): succeeds cleanly; build
output removed afterward (gitignored, verification-only).

**Django** (`manage.py test`, via the existing `config.settings_test`
SQLite override — the same pre-existing environment workaround used in
every prior round, since `DB_USER` still lacks `CREATEDB` against the
real PostgreSQL in this sandbox):
```
Ran 168 tests in 3.158s
OK
```
Unchanged from the implementation report (168 = 122 original + 46 from
Phase 6) — this fix round added no new Django tests, since neither
Django-side change (item 2's comment) altered any testable behavior; the
existing `test_token_header_carries_configured_kid` test already
documents that `kid` is set on issuance, which remains true and
sufficient.

**Combined: 246 tests, 246 passing, 0 failing.**

## Migration/schema verification

`manage.py makemigrations --check --dry-run` → `"No changes detected"`.
No model was touched this round (only a docstring in
`apps/authn/jwt_utils.py`, no field/class change). Confirmed no
migration exists or was created.

## Confirmation: frontend/ untouched

Verified directly: no file under `frontend/` has a modification time
newer than the post-implementation audit report, and no file under
`frontend/` was opened, read, or edited during this task.

## Confirmation: no live WAHA state was modified

No script or command in this session made an HTTP request to a real WAHA
base URL. Every test — including the three new audit-fallback tests and
the new no-`id`-field test — mocks `fetch` via `vi.stubGlobal`/`vi.fn()`,
identically to every existing Phase 6 test. `no_epahari` (the real
session) was not referenced by any code or test changed this round.

## Remaining Phase 6 limitations/dependencies

Unchanged from `docs/generated/PHASE-6-POST-IMPLEMENTATION-AUDIT.md`'s
"Non-blocking dependencies" section — re-confirmed still accurate, not
re-litigated here: the frontend (Phase 7), Django chat/message read
endpoints (Phase 8), webhook target correction and `session.status`
parser extension (Phase 14 / `apps/webhooks`), rate limiting / broader
security hardening (Phase 12), and — newly and explicitly named as a
dependency rather than a silent gap — a real multi-key JWT rotation
mechanism, if and when key rotation is actually needed.

---

## PHASE 6 FINALIZED — READY FOR PHASE 7

All three audit findings are resolved: the audit-fallback gap is closed
with equivalent behavior to every other route, the JWT `kid` situation
is now accurately documented and tested rather than ambiguously implied,
and the `providerMessageId` assumption is honestly described and
explicitly tested for its degradation path. 246 tests pass, type
-checking and the production build are clean, no schema or migration
exists, `frontend/` was never touched, and no live WAHA call was made at
any point.
