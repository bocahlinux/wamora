# Inbox — Live Webhook Ingestion Fix

Follow-up to `docs/generated/INBOX-CHAT-FINDINGS-AUDIT-REPORT.md`
(Finding 3). **Scope respected exactly as instructed**: identity/`@lid`
merge, `status@broadcast`, the Inbox UI, the BFF, message sending, and
Session Management were **not touched**. No outbound WhatsApp message
was sent. Canonical Phase 9 was not started.

**Result up front: the Django side is fixed and verified. The WAHA side
still needs your action — I stopped there rather than guess, per your
explicit instruction.** No real inbound-message test could be completed
yet, because WAHA's webhook still points at the wrong address (Section
2) — sending a real message right now would still not arrive, through no
fault of the Django-side fix.

## 1. Audit — confirmed facts

- **WAHA's actual webhook config for `no_epahari`** (`GET
  /api/sessions/no_epahari`, re-confirmed fresh this task, full object,
  not just the fields read last time):
  ```json
  {
    "url": "http://webhook-test:8000/webhook",
    "events": ["session.status", "message"],
    "hmac": { "key": null },
    "retries": { "delaySeconds": 2, "attempts": 15, "policy": "exponential" },
    "customHeaders": null
  }
  ```
  Two problems, confirmed, not changed: the URL doesn't resolve to
  anything reachable (Section 2), and **`hmac.key` is `null` — WAHA is
  not configured to sign its deliveries with any secret at all.**
- **Django's real webhook endpoint**: `/api/webhooks/waha/`
  (`backend/config/urls.py` → `backend/apps/webhooks/urls.py` →
  `WahaWebhookView`, `backend/apps/webhooks/views.py:14`) — re-confirmed
  live and reachable this task (Section 3), not merely read from source.
- **Django's HMAC implementation**: HMAC-SHA512 of the raw request body,
  header `X-Webhook-Hmac` (`WEBHOOK_SIGNATURE_HEADER = 'HTTP_X_WEBHOOK_HMAC'`,
  `backend/apps/webhooks/authentication.py:6`), compared with
  `hmac.compare_digest`. This matches the shape WAHA's own config
  exposes (a `hmac.key` field) — i.e. Django's expected mechanism and
  WAHA's actual configuration structure agree on what a "webhook HMAC
  secret" is; they just don't currently hold the same value (WAHA has
  none at all).
- **`WAHA_WEBHOOK_HMAC_SECRET` before this task**: confirmed empty
  (names-only check, same safe method used throughout this project).
- **Connectivity**: your own proof (`curl` from the WAHA/VPS host to
  `192.168.100.200:8000` succeeding with a real Django `404`) is taken as
  given, and independently corroborated from this side this task —
  Section 3.

## 2. Webhook URL — current vs. correct

| | Value |
|---|---|
| **Current** (WAHA-side, unchanged) | `http://webhook-test:8000/webhook` |
| **Correct**, per your confirmed topology + the real Django route | `http://192.168.100.200:8000/api/webhooks/waha/` |

Two independent problems with the current value, both already flagged in
the prior audit and re-confirmed here: the host `webhook-test` does not
match your dev PC's real address, and the path `/webhook` does not match
the real Django route (`/api/webhooks/waha/`, trailing slash — Django's
`APPEND_SLASH` would otherwise redirect a POST, which most webhook
senders don't safely follow; using the exact correct path avoids that
entirely).

## 3. Connectivity and endpoint verification (this task, live)

- `netstat` confirmed Django is listening on `0.0.0.0:8000` (matches your
  `python manage.py runserver 0.0.0.0:8000`), not just `127.0.0.1` — a
  real prerequisite for being reachable from another host at all.
- `POST http://192.168.100.200:8000/api/webhooks/waha/` (your dev PC's
  own LAN IP, simulating exactly how WAHA would reach it) →
  `401 {"code":"unauthorized","message":"Invalid webhook signature"}` —
  **reachable and correctly gated**, not silently dropped, not a
  connection failure. Confirms your own connectivity proof and this
  project's endpoint agree.

## 4. `WAHA_WEBHOOK_HMAC_SECRET` — status and mechanism

**Status: fixed on the Django side.** A new, cryptographically random
64-character hex secret (`secrets.token_hex(32)`, Python's standard
library CSPRNG — the same class of generation already used for this
project's other key material) was generated and set as
`WAHA_WEBHOOK_HMAC_SECRET` in `backend/.env`.

**Mechanism, confirmed matching on both sides**: WAHA's own webhook
config structure (`webhooks[].hmac.key`, seen directly via the live `GET`
above) and Django's implementation (HMAC-SHA512 of the raw body, shared
secret) are the same mechanism — WAHA's `hmac.key` just needs to be set
to the **same** value now configured in `backend/.env`.

**The secret value itself is not reproduced in this report** — it lives
only in `backend/.env`, per this project's standing secret-handling
rule. You can view it directly with a text editor if you need to copy it
into WAHA's config yourself: `backend/.env`, the
`WAHA_WEBHOOK_HMAC_SECRET` line.

## 5. Minimum required change — what's done, what's still needed

**Done (Django side, this task):**
1. `WAHA_WEBHOOK_HMAC_SECRET` set in `backend/.env` (Section 4).
2. Django restarted (`python manage.py runserver 0.0.0.0:8000`) to load
   it — `.env` is only read once, at process startup
   (`backend/config/env.py`), so this was required, not optional.
3. **Verified working**, without sending any outbound WhatsApp message or
   fabricating any conversation data (Section 7).

**Still needed — WAHA side, requires your action:**
4. Update session `no_epahari`'s webhook config so:
   - `url` = `http://192.168.100.200:8000/api/webhooks/waha/`
   - `hmac.key` = the exact value now in `backend/.env`'s
     `WAHA_WEBHOOK_HMAC_SECRET`

**Why I stopped here instead of making this change myself**: this
project's own `docs/12-WAHA-REFERENCE.md` lists only 5 endpoints ever
independently confirmed ("Observed") against this real deployment
(`GET /api/sessions`, `GET /api/sessions/{session}`,
`GET /api/{session}/chats`, `GET /api/{session}/chats/{chatId}/messages`,
`POST /api/sendText`) — **no endpoint for writing/updating a session's
webhook configuration has ever been confirmed in this project.** I
checked for an accessible API reference on the live instance itself
(`/api-json`, `/`, `/swagger` — all `401`, this deployment doesn't expose
one) rather than guess. WAHA's general public documentation describes a
config-update mechanism, but attempting it here — unverified, against
your real, currently-connected, actively-relied-on session — is exactly
the kind of guess your instructions told me not to make, and a wrong
write attempt risks disrupting a live session you explicitly said not to
touch. This is a genuine "cannot verify — stopping" case, not
reluctance: **please update this via whatever tool/method you originally
used to configure `no_epahari`'s webhook** (WAHA dashboard, a request you
send yourself, etc.), using the exact URL and secret above. Tell me once
it's done and I'll verify against real, live traffic.

## 6. Service/process restart requirements

- **Django**: already restarted this task (Section 5) — no further
  restart needed unless you edit `backend/.env` again yourself.
- **WAHA**: whatever the correct mechanism turns out to be for applying
  its own config update (Section 5) — some WAHA versions apply a
  webhook-config change live, others may require the session itself to
  be restarted server-side as part of that update. This project has no
  confirmed evidence either way for this specific deployment/version —
  flagged as something to observe when you make the change, not
  something I've verified.
- **BFF, frontend**: not affected by this change at all — neither reads
  `WAHA_WEBHOOK_HMAC_SECRET`, and this task didn't touch either.

## 7. Live verification performed — without sending an outbound message

Per your explicit instruction not to send outbound WhatsApp traffic, this
task's verification is a **synthetic, correctly-signed webhook request
sent directly to Django** (not through WAHA at all — this proves the
Django-side signature gate works, independent of whether WAHA's own
config has been fixed yet):

- Computed a real HMAC-SHA512 signature over a small JSON body using the
  exact new secret and the exact algorithm `verify_waha_webhook_signature`
  implements, then `POST`ed it to `http://localhost:8000/api/webhooks/waha/`
  with `X-Webhook-Hmac: <signature>`.
- **Used `event: "session.status"`, not `event: "message"`** —
  deliberately, so this test could prove the auth gate now works without
  ever creating anything that looks like a fabricated conversation
  message. WAHA's own config already subscribes to `session.status`
  too (Section 1), so this is a realistic event shape, not an invented
  one.
- Result: **`200 {"status":"ok","webhook_event_id":2,"processing_status":"unsupported"}`**
  — the signature check **passed** (previously always `401`), a real
  `WebhookEvent` row was durably created, and it's correctly marked
  `unsupported` (Django only processes `message` events —
  `SUPPORTED_EVENT_TYPES = {'message'}` — this is expected, correct
  behavior for a `session.status` event, not a new gap).
- **Negative control, re-confirmed**: the same request with a
  deliberately wrong signature still returns `401 Invalid webhook
  signature` — fail-closed behavior is intact, not accidentally
  weakened.
- **Confirmed no fabricated data**: `WebhookEvent.objects.count()` is now
  `1` (exactly the synthetic test above, nothing else); `Message.objects.count()`
  is unchanged at `17` (the real data from the earlier reconciliation
  run — untouched, no fake message added).

**What this proves**: once WAHA's config is corrected (Section 5, item
4), a real `message` webhook delivery will pass the same signature check
this synthetic one just did, then proceed into `ingest_webhook()` →
`persist_message()` exactly like every already-tested code path already
verified in this project's automated tests.

**What this does NOT yet prove**: that WAHA will actually deliver
anything, since its config still points at the wrong address. That
requires Section 5's still-open WAHA-side change first.

## 8. Backend checks after the change

```
DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test
→ Ran 243 tests — OK (unchanged from before this task; test settings use
  their own override_settings JWT/webhook keys, never backend/.env, so
  this change had no effect on them, as expected)

python manage.py check
→ System check identified no issues (0 silenced)
```

No new test was added this task — the fix is a configuration value, not
new application logic; `verify_waha_webhook_signature`'s fail-closed and
valid-signature behavior are already covered by existing tests
(`apps/webhooks/tests/test_authentication.py`, not modified), and this
task's live synthetic-webhook check (Section 7) is the appropriate
verification for a config change, not a new unit test.

## 9. What's not done yet, and the exact next step

- **WAHA's webhook `url`/`hmac.key` still need updating** (Section 5) —
  this is the one remaining blocker before a real inbound message from
  `62811520892` will reach Django at all.
- Once you've updated it: tell me, and I'll verify (still without an
  outbound send) by checking `WebhookEvent`/`Message`/`Chat` after your
  real inbound test message, and confirm it surfaces via
  `GET /api/chats/:id/messages/` and, if you check the browser yourself,
  Inbox polling.
- Identity fragmentation (`@lid`/`@c.us`/`@s.whatsapp.net`) and
  `status@broadcast` remain exactly as documented in the prior audit —
  not touched, not decided, per your explicit scope boundary this task.

---

Not proceeding to Phase 9 or any further implementation automatically.
Waiting for the WAHA-side webhook config update, then your go-ahead to
verify a real inbound message.
