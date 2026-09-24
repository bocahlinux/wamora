# Phase 6 — WAHA Session Lifecycle & QR Verification

**This task was originally halted before completion, after a
credential-exposure incident during early probing (Section 3). The user
rotated the exposed credentials (WAHA dashboard password, Swagger
password, WAHA API key) and authorized a resumed round, which is
documented in Section 13.** No application code, models, migrations,
frontend, BFF, `docker-compose.yml`, webhook configuration, or WAHA
session state was modified in either round. `test_session` was never
started, stopped, restarted, or logged out, in either round.

## 1. Environment

Same as every prior round: `http://<TENCENT_WAHA_HOST>:3000`, session
`test_session`, GOWS engine, version `2026.9.1`. Authenticated using the
existing `WAHA_API_KEY` already present in `backend/.env` (value never
printed).

## 2. What was actually done before stopping

1. Re-confirmed (from existing reports, not re-fetched live this round)
   that `docs/12-WAHA-REFERENCE.md` and prior generated reports list no
   documented session-lifecycle (start/stop/restart/logout) or QR
   endpoint paths — nothing new to add from documentation review.
2. Probed a broader set of candidate paths for Swagger/API documentation
   and general server info, all via safe `GET` requests: `/`,
   `/dashboard`, `/api/version`, `/api/server/status`, `/api/server`,
   `/api/server/environment`, `/health`, `/api/health`, `/status`,
   `/reference`, `/api/reference`, `/redoc`, `/scalar`, `/api-reference`,
   `/swagger-json`, `/v1/swagger.json`, `/api/v1`, `/metrics`.
3. Four of those returned `200`: `/api/version`, `/api/server/status`,
   `/api/server/environment`, `/health`. The first two and `/health` are
   benign (version/engine info, process uptime, disk-space health for
   the media/sessions volumes — no session-specific or sensitive data).

## 3. Incident — credential exposure, and why this task stopped here

`/api/server/environment` — reachable with the same `X-Api-Key` already
used for every other read-only call in this project — returned a **full
environment-variable dump**, including `WAHA_DASHBOARD_PASSWORD` and
`WHATSAPP_SWAGGER_PASSWORD` (both real-looking, usable-looking values,
not obviously placeholders) and what appears to be a **SHA-512 hash** of
`WAHA_API_KEY` (prefixed `sha512:`, not the raw key). This response was
printed to this session's own tool output before its sensitivity was
recognized — a mistake on this session's part; an unfamiliar endpoint's
response should have been treated as potentially sensitive before being
displayed.

**These values are not reproduced anywhere in this report.** They were
not used for anything — no attempt was made to log into the WAHA
Dashboard or Swagger UI with them, since those credentials were never
given to this session for that purpose, and using them would have
exceeded the read-only-API-key authorization this task actually granted.
The user was informed immediately and asked how to proceed; the answer
was **stop entirely**, which this session did.

**Recommendation, not an action taken**: rotate `WAHA_DASHBOARD_PASSWORD`
and `WHATSAPP_SWAGGER_PASSWORD`, and consider whether `WAHA_API_KEY`
itself is worth rotating out of caution, since a hash of it has now
appeared in a conversation transcript. Also worth reviewing: whether
`/api/server/environment` should be reachable with an ordinary API key
at all, independent of anything this session did.

## 4. Session lifecycle endpoints — NOT EXECUTED

Not reached this round. Prior rounds
(`docs/generated/PHASE-6-SPEC-RESOLUTION.md` Section 4,
`docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` Section 5) already
established: list/get/me session endpoints are live-confirmed; start/
stop/restart/logout remain **UNKNOWN** (no safe verification method was
found even before this round, and this round did not add anything before
stopping).

## 5. Session START — NOT EXECUTED

Not attempted, consistent with prior rounds (`test_session` is running;
starting a running session was never in scope).

## 6. QR / Pairing — NOT EXECUTED (unchanged from prior finding)

No new evidence gathered this round. Prior finding stands: a candidate
path timed out rather than 404'd (suggestive, not confirmed) — see
`docs/generated/PHASE-6-SPEC-RESOLUTION.md` Section 4. Not re-tested.

## 7. Session status webhook — NOT EXECUTED

Not attempted this round. Existing evidence (webhook config includes
`session.status` as an event type) is unchanged from
`docs/generated/PHASE-6-ARCHITECTURE-DECISION.md` Section 5.

## 8. BFF API contract implications

Not produced this round — insufficient new evidence, and this task did
not reach that stage before stopping.

## 9. Safe vs. unsafe live operations — summary of this round only

| Operation | Result |
|---|---|
| `GET /api/version` | **LIVE VERIFIED** — benign, confirmed engine/version, matches all prior rounds |
| `GET /api/server/status` | **LIVE VERIFIED** — benign, process uptime only |
| `GET /health` | **LIVE VERIFIED** — benign, disk-space health for media/sessions volumes |
| `GET /api/server/environment` | **LIVE VERIFIED to exist, but its response should not have been retrieved without more caution** — see Section 3 |
| Everything in Sections 4–8 | **NOT EXECUTED** |

## 10. BFF API implications

Not produced — out of reach this round.

## 11. Remaining limitations

Identical to every prior round: session lifecycle (start/stop/restart/
logout) and QR/pairing endpoints remain unverified against the real
deployment, by any safe method found so far. This round adds one new,
unrelated finding (Section 3) rather than closing that gap.

## 12. Phase 6 readiness

**PHASE 6 NOT READY**

Unchanged from `docs/generated/PHASE-6-BLOCKER-RESOLUTION.md`'s
conclusion — session lifecycle and QR endpoints remain the specific
missing evidence blocking full readiness. This round did not resolve
that; it stopped early due to the credential-exposure incident in
Section 3.

**Specific missing evidence/decisions still required**:
1. Session lifecycle (start/stop/restart/logout) endpoint paths, methods,
   and safety — no safe verification method has been found in any round.
2. QR/pairing endpoint confirmation.
3. ~~A decision on whether/how to continue live WAHA verification at all,
   given the credential exposure — and separately, whether to rotate the
   exposed credentials~~ — **resolved**: credentials rotated by the user,
   verification resumed. See Section 13.

## 13. Resumed round (post-credential-rotation)

**Security constraints for this round** (per the user's explicit
resume instructions, followed throughout): only the ordinary API key was
used; `/api/server/environment` was never accessed again; no attempt was
made to reach the WAHA Dashboard or Swagger UI; `.env`/environment
variables were never dumped or inspected beyond the established
in-process safe-loader pattern; no credential value, hash, token, QR
payload, or pairing code appears anywhere below.

### 13.1 New API key confirmed working

`GET /api/sessions/test_session` (already-vetted safe endpoint from prior
rounds) → `200`. Printed only non-sensitive fields:

- `status`: `WORKING`
- `presence`: `offline`
- `engine.gows.connected`: `true`

This confirms the rotated key is functional and the real session is
unchanged (still connected/paired) — no state was altered.

### 13.2 Attempt to close the lifecycle/QR gap

No new safe verification method was found this round beyond what prior
rounds already established:

- **Swagger/OpenAPI documentation remains unreachable** by any
  known-safe path across every round attempted so far (all return `401`
  or `404`); `/api/server/environment` was not retried as a way to find
  it, per this round's explicit constraints.
- **`OPTIONS`** is confirmed unreliable for existence-checking (proven via
  control test in a prior round — returns `204` uniformly regardless of
  route existence) and was not used to infer anything this round.
- **`HEAD`** is reliable only for GET-type routes (validated in a prior
  round); lifecycle operations (start/stop/restart/logout) are
  conventionally `POST`-type, where `HEAD` gives no signal, so it was not
  used to probe them this round.
- **Start**: `test_session` is already running — starting an already-running
  session was not attempted, consistent with every prior round and with
  the resume instructions' guidance not to force the session into a
  different state just to test an endpoint.
- **Stop / Restart / Logout**: per this round's explicit stop conditions
  ("Before performing any destructive or session-invalidating operation
  such as logout, explicitly stop and ask for confirmation" and "Do NOT
  log out the real WhatsApp session"), **none of these were attempted**.
  No safe, non-invoking way to verify their existence or exact contract
  was found (see `HEAD`/`OPTIONS` limitations above) — verifying them at
  all would require either real documentation (still unreachable) or
  actually invoking them against the live, paired `test_session` session.
- **QR / pairing**: `test_session` is already paired (`status: WORKING`).
  A candidate path (`/api/{session}/auth/qr`) returned an inconclusive
  timeout in a prior round rather than a clean `404`. This round did not
  retry it: QR/pairing endpoints are typically only meaningful for an
  unpaired session, retrying a request that already timed out once
  against the real paired session carries risk with no plausible safe
  payoff, and the resume instructions explicitly say not to force a
  session into a different state to test an endpoint.

### 13.3 Evidence table

| Capability | Endpoint | Method | Auth | Request | Response shape | Live verified? | Side effects | Notes |
|---|---|---|---|---|---|---|---|---|
| List sessions | `/api/sessions` | GET | `X-Api-Key` | none | array of session objects | CONFIRMED BY LIVE EVIDENCE (prior round) | none | Not re-tested this round |
| Get session | `/api/sessions/{session}` | GET | `X-Api-Key` | none | session object (`status`, `me`, `engine`, `config`) | CONFIRMED BY LIVE EVIDENCE | none | Re-confirmed this round with rotated key |
| Get session "me" | `/api/sessions/{session}/me` | GET | `X-Api-Key` | none | `me` object | CONFIRMED BY LIVE EVIDENCE (prior round) | none | Not re-tested this round |
| Session status | (embedded field, no separate endpoint) | GET | `X-Api-Key` | none | `status` string | CONFIRMED BY LIVE EVIDENCE | none | Re-confirmed this round: `WORKING` |
| List chats | `/api/{session}/chats` | GET | `X-Api-Key` | none | array of chat summaries | CONFIRMED BY LIVE EVIDENCE (prior round) | none | Not re-tested this round |
| Chat messages | `/api/{session}/chats/{chatId}/messages` | GET | `X-Api-Key` | `limit`, `offset` query params | array of message objects | CONFIRMED BY LIVE EVIDENCE (prior round) | none | Not re-tested this round |
| `sendText` | `/api/sendText` | POST | `X-Api-Key` | `session`, `chatId`, `text` | message object on success; `400`/`500` observed on invalid input | CONFIRMED BY LIVE EVIDENCE (schema only, prior round) | Would send a real WhatsApp message with valid input | Not invoked with valid data; not in this round's scope |
| Start session | unknown | unknown | unknown | unknown | unknown | **UNVERIFIED** | Would attempt to (re)connect an already-connected session | Not safely testable — session already running |
| Stop session | unknown | unknown | unknown | unknown | unknown | **UNVERIFIED** | Would disconnect the real, in-use WhatsApp session | STOP CONDITION — not attempted without explicit confirmation |
| Restart session | unknown | unknown | unknown | unknown | unknown | **UNVERIFIED** | Would disconnect/reconnect the real session | STOP CONDITION — not attempted without explicit confirmation |
| Logout session | unknown | unknown | unknown | unknown | unknown | **UNVERIFIED** | Would unlink the real WhatsApp account, requiring re-pairing by scanning a new QR code | Explicitly forbidden by the task's own instructions — not attempted, not proposed |
| QR / pairing | candidate: `/api/{session}/auth/qr` | GET (candidate, unconfirmed) | `X-Api-Key` (assumed) | none | unknown | INFERRED (candidate path exists, based on a timeout rather than a 404, in a prior round) | Unknown — real behavior against a paired session unconfirmed | Not retried this round; likely only meaningful for an unpaired session |

### 13.4 Why stop/restart remain unresolved, and a recommendation

No safe, non-invoking method to verify `stop`/`restart` was found across
every round attempted (documentation unreachable; `HEAD`/`OPTIONS` give
no signal on `POST`-type routes). The only way to close this gap further
would be to actually invoke one of these operations against the real,
live `test_session` session — which the resume instructions require
stopping and asking about first (STOP CONDITION 4: "a required lifecycle
operation cannot be performed safely without changing the
production-like session state").

**This report does not recommend doing so.** `test_session` (WhatsApp
number `@test_business` per prior rounds' evidence) appears to be a
real, actively-used business connection, not a disposable test session.
Even a nominally "safe/reversible" stop or restart carries real,
non-zero operational risk on a live GOWS multi-device session (e.g. an
unexpected need to re-scan a QR code if WhatsApp's servers treat the
disconnect as a delink) that this project has no way to fully rule out
without documentation. If this gap is to be closed at all, the safer
path is a **disposable/non-production WAHA session** dedicated to
lifecycle testing, rather than experimenting on the real one — that
decision is left to the user, not taken here.

`logout` is not part of this recommendation at all: the resume
instructions forbid it outright ("Do NOT log out the real WhatsApp
session"), independent of any confirmation.

## 14. Phase 6 readiness (updated)

**PHASE 6 NOT READY** — unchanged conclusion.

What changed this round: the credential-exposure incident is resolved
(rotated, and re-verified not to block ordinary API-key use). What did
not change: session lifecycle (start/stop/restart/logout) and QR/pairing
endpoints remain unverified **by live evidence**. No safe method to close
that specific gap was found in this round or any prior round; closing it
requires either official documentation (see Section 15 — since obtained)
or a deliberate, explicitly-authorized live test — ideally against a
disposable session rather than `test_session`.

## 15. Superseded classification — see the dedicated contract document

A later round obtained official WAHA documentation
(<https://waha.devlike.pro/docs/how-to/sessions/>,
<https://waha.devlike.pro/docs/how-to/security/>) and used it to refine
the blanket "UNVERIFIED" label above into three distinct categories —
**DOCUMENTED/IMPLEMENTATION-READY**, **LIVE VERIFIED**, and **NOT LIVE
TESTED** (a meaningfully different thing from "unknown endpoint"). That
full reclassification, the endpoint/response tables, the proposed BFF
contract, the WAHA authentication-scoping recommendation, and the
newly-surfaced audit-actor-attribution gap live in
`docs/generated/PHASE-6-WAHA-LIFECYCLE-API-CONTRACT.md` — **this section
intentionally does not duplicate that content**, to avoid the two
documents drifting out of sync. This report's Sections 1–14 above are
preserved unchanged as the historical record of what was actually
attempted live, including the credential-exposure incident; they are not
retracted or edited, only superseded in their *readiness conclusion* by
the newer document.

**Current Phase 6 readiness, per the newer document**: still **NOT
READY**, but the reason has narrowed — lifecycle/QR is no longer an
"unknown API" gap, only a "finalize a handful of architecture decisions,
optionally live-confirm response shapes later" gap. See
`docs/generated/PHASE-6-WAHA-LIFECYCLE-API-CONTRACT.md` Section 16 for
the current, authoritative answer.
