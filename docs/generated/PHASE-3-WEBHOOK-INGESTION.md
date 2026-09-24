# Phase 3 — Webhook Ingestion

## 1. Files created

- `backend/apps/webhooks/authentication.py` — HMAC-SHA512 webhook signature verification
- `backend/apps/webhooks/parsing.py` — pure envelope/message parsing (no DB access)
- `backend/apps/webhooks/services.py` — ingestion orchestration (transactions, idempotency, persistence)
- `backend/apps/webhooks/views.py` — `WahaWebhookView` (the endpoint)
- `backend/apps/webhooks/urls.py` — routes `waha/` to the view
- `backend/apps/webhooks/migrations/0002_alter_webhookevent_status.py` — adds the `unsupported` status choice
- `backend/apps/webhooks/tests/__init__.py`, `tests/test_models.py` (moved from the old `tests.py`), `tests/test_authentication.py`, `tests/test_parsing.py`, `tests/test_ingestion.py`, `tests/test_views.py`, `tests/fixtures.py`

## 2. Files modified

- `backend/apps/webhooks/models.py` — added `WebhookEvent.STATUS_UNSUPPORTED`
- `backend/config/urls.py` — mounted `api/webhooks/` → `apps.webhooks.urls`
- `backend/config/settings.py` — added `WAHA_WEBHOOK_HMAC_SECRET`
- `backend/.env.example`, `infrastructure/office/.env.example` — added `WAHA_WEBHOOK_HMAC_SECRET`
- `docs/12-WAHA-REFERENCE.md` — added "Webhook Envelope and Auth — Assumptions Introduced in Phase 3" (new assumptions, not a correction of anything previously stated)
- `backend/apps/webhooks/tests.py` deleted, replaced by the `tests/` package above (same test cases preserved in `test_models.py`, unchanged)

No frontend, BFF, or other backend app files were touched.

## 3. Webhook endpoint

`POST /api/webhooks/waha/`. Not a DRF-user-authenticated view (WAHA is a machine caller, not a Django user) — `authentication_classes`/`permission_classes` are empty and a manual HMAC check gates every request. Uses DRF's `APIView`/`JSONParser`/`request.data` and the project's existing `EXCEPTION_HANDLER` (from Phase 1) so malformed JSON and unhandled errors get the same request-ID/error-envelope treatment as every other endpoint.

## 4. Event handling

Only `event_type == "message"` is processed (the only event type `docs/12-WAHA-REFERENCE.md` has ever listed as observed). Any other event type is durably recorded with `status=unsupported` and the request still returns `200` — WAHA is not told to retry something that will never be supported by retrying. This required adding `WebhookEvent.STATUS_UNSUPPORTED` to the Phase 2 model (small additive `choices` change, no column/constraint change — `makemigrations --check` confirms the only generated migration is a no-op-at-the-SQL-level `AlterField`).

## 5. Identity handling

Implements the Phase 2.5 rule exactly as restated in your instructions: primary identifier (`Info.Sender`/`Info.Chat`, falling back to top-level `from`) stored verbatim as `provider_contact_id`/`provider_chat_id`; `phone_number` populated only from `SenderAlt` when present and in `@s.whatsapp.net` form; the `Alt` value is never used as a primary identity, never merged by string similarity.

One rule beyond Phase 2.5, needed to make ingestion concrete: **Contact records are only ever created/updated from inbound, non-group messages.** For an outbound (`fromMe=true`) message, `Sender` is presumed to be our own account, so it is deliberately never used to create/mutate a `Contact` — only the `Chat` (conversation) is created/reused. This is a new design decision this phase had to make; it is not something Phase 2.5 specified, and it is unverified against real outbound payload structure (see Section 11).

## 6. Idempotency strategy

Two layers, both grounded in Phase 2's unique constraints:

1. **WebhookEvent layer** (primary): `get_or_create(session, provider_event_id)`. A resolved duplicate (status already `processed`/`failed`/`unsupported`) short-circuits with no reprocessing. A duplicate still at `pending` (a prior attempt started but never finished — e.g. an infra failure mid-processing) is **retried**, not skipped — this lets WAHA's own webhook retry behavior recover a stuck event.
2. **Message layer** (defensive backstop): if `Message.objects.create` still hits the `(session, provider_message_id)` unique constraint despite passing the WebhookEvent check, this is treated as "already resolved via a different event delivery" and marked `processed`, not `failed`. This path is currently unreachable through normal parsing, since `provider_event_id` and `provider_message_id` are both sourced from the same assumed field (`payload.id`) — it exists specifically so the system degrades safely if that 1:1 assumption turns out to be wrong once verified live.

## 7. Transaction strategy

`WahaSession` get_or_create and `WebhookEvent` get_or_create happen first, outside any wrapping transaction, so the raw event is durably recorded before any processing is attempted (satisfies "record the raw webhook event" as a distinct, earlier step). Message processing (`Chat` get_or_create, `Contact` get_or_create/update, `Message.create`) all happens inside one `transaction.atomic()` block, so any failure — controlled or not — rolls back the whole set together; there is no code path that can leave a `Contact` without its `Chat`, or a `Chat` without its `Message`. A genuinely unexpected exception (e.g. a database error) is **not** caught inside that block — it propagates to the view, becomes a `500` via the existing exception handler, and leaves the `WebhookEvent` at `pending` (never falsely `processed`), which is both honest and retry-friendly. Verified directly by test (`test_unexpected_failure_leaves_webhook_event_pending_and_rolls_back_chat_contact`, `test_retry_after_transient_failure_completes_processing`).

## 8. Security validation

- **Webhook authentication**: HMAC-SHA512 over the raw request body via `X-Webhook-Hmac`, matching WAHA's own publicly documented webhook HMAC feature. **This is a flagged assumption, not a verified fact** — see Section 11. Fails closed: an unconfigured secret or a missing/invalid signature is always rejected (`401`), never silently allowed.
- **No secrets in responses**: verified by test (`test_secret_never_present_in_response`) that the configured secret never appears in any response body.
- **No leaked internals**: verified by test that malformed-request error bodies contain no traceback, no `.py` file paths, no `django.db` references.
- **Unauthenticated requests never touch the database**: verified by test — signature check happens before any DB access.

## 9. Tests

69 tests total (46 new for Phase 3, 23 carried over from Phases 1–2), all passing. Breakdown of the new ones:
- **Envelope** (7): valid envelope, non-object body, missing `event`/`session`/`payload`/`payload.id`, unsupported-event-type-still-valid.
- **Message parsing** (7): inbound LID sender, outbound, missing Alt, fallback to top-level `from`, missing message ID / chat identifier / `fromMe` → `MessageParsingError`.
- **Phone extraction** (4): JID→digits, absent→blank, LID never treated as phone, non-numeric local part rejected.
- **HTTP envelope** (3): malformed JSON → 400, missing fields → 400, unsupported type → 200 + recorded.
- **HTTP message** (6): full inbound persistence chain, outbound without fabricating a Contact, outbound-only chat has no contact, missing Alt → blank phone, broken payload → recorded failed not crashed, message ID preserved verbatim.
- **Idempotency** (2 HTTP + 3 service-layer): duplicate delivery doesn't duplicate the message, attempts counter increments, same message ID across two different sessions both persist (proves session-scoped identity), transient-failure retry recovers and completes.
- **Database integrity** (3): rollback on unexpected failure, retry-after-failure completes, FK integrity (`message.session`/`message.chat` correct).
- **Security** (7): missing/invalid signature rejected, unauthenticated request never touches DB, valid signature accepted, secret never in response, no traceback/path/module leakage on error.
- **Authentication unit tests** (5): valid/invalid/missing signature, unconfigured-secret fails closed, tampered body rejected.

## 10. Live verification results

**None of the "Live WAHA verification" requirements could be executed. This is stated plainly per your own instruction not to fake results.** Re-confirmed before starting this phase (same checks as Phase 2.5): Docker daemon is not reachable from this session, `localhost:3000` refuses connection, no `WAHA_BASE_URL`-style env var is set, and no captured payload file exists anywhere in the repository.

Concretely, not executed:
- **Outbound message verification** against a real WAHA `sendText` response — not performed. `OUTBOUND_MESSAGE_ENVELOPE` in `tests/fixtures.py` is explicitly synthetic (constructed by this session, mirroring the inbound shape with `fromMe: true`), not a real observed payload. Its docstring says so.
- **REST endpoint verification** (`sessions`/`chats`/`chat messages` identifier form vs. webhook form) — not performed. No REST client code was written this phase for this reason (it wasn't needed for the webhook endpoint itself, and writing it without anything to call would just be more unverifiable code).
- **Group behavior** — not performed, no safe test group was available to this session in the first place (no live access at all). Explicitly reported as unverified, not invented.
- **Live integration test** (send one real message to the deployed webhook endpoint, verify Django receives it) — not performed, not possible from this environment. Not faked.

What **was** done instead, honestly within reach: every test that references real observed data uses the exact fields reported during Phase 2.5 (`000000000000000@lid`, `62800000000@s.whatsapp.net`, `test_session`, `Halo pak`) as a fixture, not a live re-fetch.

## 11. Known limitations

Ranked by how much they matter if wrong:

1. **`payload.id` as the stable event/message ID** — the single biggest assumption in this phase. No reported example ever showed this field. If real WAHA payloads use a different field name (or nest it differently), the envelope validator will reject every real webhook with a 400, and nothing will be ingested until this is fixed. **Verify this first**, before relying on this endpoint against real traffic.
2. **Webhook HMAC authentication mechanism** — assumed from WAHA's public documentation, not from this deployment. If the actual configuration differs (different header, different algorithm, or none at all configured on the WAHA side), every real webhook will be rejected with 401. Both this and #1 fail *safe* (nothing gets silently corrupted — they fail loud, as 400/401), but both need a live check before production use.
3. **Outbound message structure** — entirely unverified; the implementation assumes structural symmetry with inbound (same `Info.Chat`/`Info.Sender` fields), differing only in `fromMe`. Explicitly flagged per your instruction not to assume this.
4. **Contact skip on outbound** is a new rule this phase introduced (Section 5) to avoid fabricating a Contact from what's presumed to be our own account identifier — reasonable given current evidence, but not something Phase 2.5 itself specified, so flagging it as a judgment call.
5. **Timestamp fallback**: if `payload.timestamp` is absent or non-numeric, the message is stored with server-receipt time rather than the true WhatsApp timestamp. Not observed to be a problem, but not confirmed absent either.
6. **Group-message handling**: contact/chat linking for group messages is intentionally minimal (no per-participant sender tracking) — consistent with Phase 2's schema, which has no `Message.sender` field, but this means group conversations get materially less identity detail than 1:1 chats until a later phase revisits this.
7. **`MediaReference` is not created** by this phase — it wasn't in the 15 numbered pipeline objectives, so it was left out rather than guessed at.

## 12. Documentation changes

- `docs/12-WAHA-REFERENCE.md`: added a new section listing the additional WAHA-behavior assumptions this phase needed to introduce (envelope shape, `payload.id`, HMAC auth) — framed as new assumptions requiring future verification, not as corrections to anything previously stated (nothing was discovered to contradict prior documentation, since no live access was available to discover anything).
- No other documentation file required changes. `04-DATA-MODEL.md`, `05-WEBHOOK-SYNC-DESIGN.md`, `07-API-CONTRACT.md`, `CLAUDE.md` were all re-read before coding and remain consistent with what was built.

## 13. Unresolved questions

None blocking — everything above is disclosed as a flagged assumption or explicitly-unverified item rather than a stop-the-phase ambiguity, consistent with how Phase 2.5 was handled. The two highest-priority items to resolve before trusting this against real traffic are #1 and #2 in Section 11 (stable ID field name, webhook auth mechanism) — both are cheap to confirm once live access exists (one real webhook delivery would settle both), but neither could be confirmed from this environment.

---

**Scope confirmation**: only Phase 3 was implemented. No reconciliation, no outbound operation processing, no authentication (user-facing), no frontend/BFF changes, no blast, no reporting, no production deployment.
