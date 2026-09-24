# Inbox/Chat — Three-Finding Audit Report

Read-only. **No source, database, migration, `.env`, configuration, or
live WAHA session was modified.** One read-only WAHA REST call was made
(`GET /api/sessions/no_epahari`, the same "Observed endpoint" already
used throughout this project) to inspect its configured webhook URL — no
session action, no send, no reconciliation was triggered this task.

---

## Finding 1 — `status@broadcast`

**Confirmed root cause**: yes, this is WhatsApp's own built-in Status
(24h stories) pseudo-chat, and it genuinely comes from WAHA's real
`GET /api/{session}/chats` response — not a bug in this project's
parsing. Verified directly in this environment's database: `Chat` id 7,
`provider_chat_id = "status@broadcast"`, created by the chat-discovery
step this session's earlier reconciliation run added
(`apps/sync/reconciliation.py::_discover_chats`,
`backend/apps/sync/reconciliation.py:109`). It has 2 real `Message` rows
attached (ids 40/41), also pulled in by the same reconciliation run's
existing per-chat message-history loop — WAHA genuinely reports message-
like entries for this pseudo-chat when its history is fetched.

**Recommended filter locations** (not implemented):

1. **Primary, read-layer**: `apps/chats/views.py::ChatListView.get()`
   (`backend/apps/chats/views.py:46`) — add
   `.exclude(provider_chat_id='status@broadcast')` to the queryset. This
   is a pure presentation decision: the row (and its messages) still
   exist in the database exactly as WAHA reported them, nothing is
   discarded, and it's trivially reversible. Matches this project's
   existing precedent of presentation-layer filtering (e.g.
   `MediaReferenceSerializer` already excludes `storage_reference` at
   the serializer layer, not the model layer).
2. **Secondary, defense-in-depth, discovery-layer**:
   `apps/sync/reconciliation.py::_discover_chats()`
   (`backend/apps/sync/reconciliation.py:109`) — skip creating a `Chat`
   row at all when `provider_chat_id == 'status@broadcast'`. Cheaper
   (avoids ever fetching its message history in future reconciliation
   runs) but more invasive (Django would never record it at all, even
   for potential future audit/analytics use).

**Recommendation, not a decision**: apply #1 alone first (minimal,
reversible, doesn't touch ingestion). Add #2 only if avoiding the wasted
WAHA history fetch is judged worth the extra ingestion-layer change —
this is a product/performance trade-off, not resolved here.

No other WhatsApp-internal pseudo-chat pattern (e.g. broadcast lists)
was found in the current 8-row dataset — this audit only confirms
`status@broadcast` specifically, not a general rule for "all pseudo-
chats," since no other example exists yet to generalize from.

---

## Finding 2 — Identity fragmentation for `62811520892`

**Confirmed by direct database inspection** (not inferred):

| Chat | `provider_chat_id` | Linked Contact | Messages |
|---|---|---|---|
| id 3 | `168160971997355@lid` | Contact id 3, `phone_number = 62811520892` | 8 inbound + 1 outbound |
| id 8 | `62811520892@s.whatsapp.net` | none | 3 outbound |
| id 5 | `62811520892@c.us` | none | **0** (empty chat, discovery-only) |

**Contact id 3's `phone_number` field already contains `62811520892`** —
this is not new evidence I derived; it's the existing, already-verified
`extract_phone_number()` rule (`apps/webhooks/parsing.py:162`, only
trusts a `SenderAlt` ending in `@s.whatsapp.net`) already having done its
job correctly on real inbound messages from `168160971997355@lid`. This
confirms your own observation: `SenderAlt` for that chat's inbound
messages is indeed `62811520892@s.whatsapp.net`.

**Deeper inspection attempted, genuine limitation found**: I could not
inspect the raw `SenderAlt`/`RecipientAlt`/`participant`/`IsFromMe`
fields for the specific messages in Chat id 8 (`62811520892@s.whatsapp.net`)
or confirm whether they structurally match your `SenderAlt` observation,
because **this project has never received a single live webhook**
(`WebhookEvent.objects.count() == 0` — see Finding 3) — the only raw
payload storage this project has is `WebhookEvent.payload`, and every
message currently in the database (including all of Chat id 8's) arrived
via REST-based reconciliation, which never stores the raw WAHA response,
only the fields `parse_message()` extracts into `Message`'s own columns
(no sender/alt/participant field exists on `Message` at all — confirmed
by re-reading `apps/chats/models.py`). **So the specific field-level
evidence you're asking for, for Chat id 8's own messages, does not exist
anywhere in this database to inspect** — only Chat id 3's inbound
messages (which happened to be captured with enough fidelity via the
Contact-creation path) have a confirmed `SenderAlt` value on record.

**1. Can `@lid` be deterministically mapped to `62811520892`?** Yes, but
only in the direction and scope already implemented: an *inbound*
message on a `@lid` chat, whose `SenderAlt` is a well-formed
`@s.whatsapp.net` value, reliably yields that phone number
(`Contact.phone_number`, already populated correctly here). This is
**not** the same as saying "Chat id 8 (`62811520892@s.whatsapp.net`) is
therefore the same conversation as Chat id 3 (`168160971997355@lid`)" —
that would require trusting that an *outbound* message's `Chat` field,
in `@s.whatsapp.net` form, reliably refers to the *contact*, which
`docs/12-WAHA-REFERENCE.md`'s own evidence explicitly warns against:
its "Message B" example shows an outbound message whose `Sender` was
**our own account's** number, in `@s.whatsapp.net` form — structurally
the same shape as what Chat id 8 exhibits. Without the raw payload for
Chat id 8's specific messages (which doesn't exist to inspect), I cannot
rule out that Chat id 8 is structurally the "our own account" case
rather than the "contact, just in a different ID form" case.

**2. Does the project already have a field for this?** `Contact.phone_number`
already exists and already serves as a *soft*, informational
cross-reference (not a merge key) — no `Chat`-to-`Chat` alias/canonical-
identity field or table exists anywhere in `apps/chats/models.py`.

**3/4. No merge implemented or recommended for automatic execution** —
consistent with your explicit instruction, and independently justified
by the evidence gap above.

**5. Minimal safe design, if you decide to pursue this** (not
implemented, and deliberately *not* an automatic merge):

- Do **not** attempt a `@lid`/`@c.us` suffix-stripping or phone-number-
  string-equality auto-merge rule — the evidence gap above is exactly
  why that would be unsafe (risk of merging a contact's chat with a
  chat that actually represents your own account).
- **Safer, smaller alternative**: surface `Contact.phone_number` (or its
  absence) more visibly wherever chats are listed — e.g. the Inbox API
  already returns `contact_name`; a `phone_number` field could be added
  the same way — so a **human operator** can visually notice "these two
  chat entries share the same phone number" and decide for themselves,
  rather than the system silently deciding. This requires no schema
  change (the data already exists) and no merge logic.
- **If an explicit, human-confirmed merge is wanted later**: the
  smallest schema addition would be a nullable, self-referencing
  `Contact.canonical_contact = FK('self', null=True)` (or an equivalent
  on `Chat`), populated **only** by a deliberate, explicit action (an
  admin action or a dedicated confirm-merge endpoint a human triggers
  after reviewing both chats) — never inferred automatically from
  string matching. This is a design sketch for a future decision, not a
  recommendation to build it now.

**Edge-case risks that make automatic merging genuinely unsafe today**
(from the already-documented evidence, restated for this specific case):
outbound messages can report `Chat`/`Sender` values representing *your
own account*, in the exact same ID shapes (`@s.whatsapp.net`, `@c.us`)
that a contact's chat can also appear in; group-chat behavior is
entirely unverified; and no `RecipientAlt` value has ever been observed
at all. Any of these could produce a false-positive merge if automated.

---

## Finding 3 — Incoming messages not appearing automatically

**Two independent, compounding root causes were found — either one
alone would fully explain the symptom; both are present.**

### Root cause A — WAHA is configured to send webhooks to the wrong address

Read-only check: `GET /api/sessions/no_epahari` against the real, live
WAHA instance (the same "Observed endpoint" already used elsewhere in
this project) returns:

```
config.webhooks: [{ "url": "http://webhook-test:8000/webhook", "events": ["session.status", "message"] }]
```

WAHA **is** subscribed to `message` events for this session — that part
is correctly configured. But the destination URL,
`http://webhook-test:8000/webhook`, does not match:
- **Host**: `webhook-test` is not this project's Django service name in
  either compose file (`infrastructure/office/docker-compose.yml`'s
  service is `backend`) — it will very likely not resolve to this
  Django instance from WAHA's network at all.
- **Path**: `/webhook` does not match the actual, real endpoint path —
  confirmed from `backend/config/urls.py` +
  `backend/apps/webhooks/urls.py`: the real path is
  **`/api/webhooks/waha/`** (`WahaWebhookView`, `backend/apps/webhooks/views.py:14`),
  not `/webhook`.

Even if the host resolved correctly, WAHA would be POSTing to the wrong
path and getting a `404`, never reaching `WahaWebhookView.post()`
(`backend/apps/webhooks/views.py:30`) at all.

**Not fixed here** — this is live WAHA session configuration, and you
explicitly said not to change it. Correcting it (via WAHA's own session-
config update mechanism, not covered by this audit's scope) is a
decision/action for you.

### Root cause B — Django rejects every webhook unconditionally, even if one arrived

`backend/apps/webhooks/authentication.py:9`
(`verify_waha_webhook_signature`) — its own docstring states plainly:
*"Fails closed: an unconfigured secret... is always rejected."* Read-
only check (names-only, no value ever printed, same safe method used
throughout this session): `WAHA_WEBHOOK_HMAC_SECRET` in `backend/.env`
is **empty**. The function's own logic:

```python
secret = settings.WAHA_WEBHOOK_HMAC_SECRET
if not secret or not signature_header:
    return False
```

An empty secret makes this return `False` **unconditionally, for every
request, regardless of what WAHA sends** — `WahaWebhookView.post()`
(`backend/apps/webhooks/views.py:30`) then always returns `401` before
ever calling `ingest_webhook()`
(`backend/apps/webhooks/services.py:28`), which is the **first** place a
durable `WebhookEvent` row would be created (`get_or_create` is its
first action).

**This is directly confirmed, not inferred, by a third piece of
evidence**: `WebhookEvent.objects.count()` in the real dev database is
**0** — not "the specific message you sent is missing," but **zero
webhook events of any kind have ever been durably recorded**, consistent
with every delivery attempt (if any reached Django at all) being
rejected at the signature check, every single time.

### Answering your 8 numbered questions directly

1. **Did WAHA send a `message` event for your test?** Not independently
   confirmed (no raw delivery log exists to inspect — console-only
   Django logging, `backend/config/settings.py:319`, nothing persisted).
   WAHA *is* subscribed to `message` events (Root cause A's evidence),
   so it very likely attempted to.
2. **Did Django receive the webhook?** Cannot be confirmed either way
   from available evidence — Root cause A means it likely never even
   reached a listening service at the configured address.
3. **Did it reach `WebhookEvent`?** **No** — confirmed, table is empty.
4. **Did it pass `SUPPORTED_EVENT_TYPES`?** Not reached — the request
   never gets past signature verification (Root cause B) to be parsed at
   all.
5. **Was `persist_message()` called?** No — same reason.
6. **Was a `Message` row created via the webhook path?** No.
7. **If a Message row existed but the UI didn't show it — API/frontend
   issue?** Not applicable here — no row exists at all, so this isn't an
   API/frontend problem. (For completeness: the `GET /api/chats/:id/messages/`
   endpoint and frontend polling were both re-confirmed working
   correctly against the 17 real rows that *did* arrive via
   reconciliation, per the implementation report's Section 7/8 — so if
   this were a "row exists, UI doesn't show it" case, it would not be.)
8. **Where's the break?** Both root causes above, independently
   sufficient, currently compounding.

**What reconciliation's existing behavior means for you right now**:
until both root causes are fixed, no message will ever arrive
automatically — the *only* way new messages currently enter this
database is a manual/scheduled reconciliation run (like the one this
session's implementation report already performed once). This was
**not re-run for this audit** — per your explicit instruction, no
reconciliation was triggered this task.

---

## Summary: file/line references

| Finding | File | Line |
|---|---|---|
| status@broadcast discovery | `backend/apps/sync/reconciliation.py` | `_discover_chats`, line 109 |
| status@broadcast recommended filter | `backend/apps/chats/views.py` | `ChatListView.get`, line 46 |
| phone-number extraction (existing, correct) | `backend/apps/webhooks/parsing.py` | `extract_phone_number`, line 162 |
| Contact/Chat models (no alias field exists) | `backend/apps/chats/models.py` | whole file |
| Webhook signature check (fails closed) | `backend/apps/webhooks/authentication.py` | `verify_waha_webhook_signature`, line 9 |
| Webhook receiving view | `backend/apps/webhooks/views.py` | `WahaWebhookView.post`, line 30 |
| Webhook durable recording (never reached) | `backend/apps/webhooks/services.py` | `ingest_webhook`, line 28 |
| Django URL routing for the webhook | `backend/config/urls.py` + `backend/apps/webhooks/urls.py` | resolves to `/api/webhooks/waha/` |
| Django logging (console-only, no history) | `backend/config/settings.py` | `LOGGING`, line 319 |

## Recommended minimal changes (not applied — for your decision)

1. **Filter `status@broadcast`** in `ChatListView`'s queryset
   (`backend/apps/chats/views.py:46`) — one `.exclude(...)` clause.
2. **Fix WAHA's configured webhook URL** for session `no_epahari` to
   point at this Django deployment's actual, reachable address and the
   real path `/api/webhooks/waha/` — a live WAHA session-config change,
   which you said not to make in this task; flagged for your own action.
3. **Set a real `WAHA_WEBHOOK_HMAC_SECRET`** in `backend/.env`, matching
   whatever secret is configured (or will be configured) on the WAHA
   side for this session's webhook — a `.env` change, which you said not
   to make in this task; flagged for your own action.
4. **Identity fragmentation**: no code change recommended yet — the
   evidence gap (no raw payload ever captured for Chat id 8's messages)
   means a safe design can't be fully specified until either (a) a live
   webhook is captured once Root causes A/B above are fixed, giving real
   field-level evidence for an outbound `@s.whatsapp.net`-form message,
   or (b) you decide the softer, non-merging "show phone_number in the
   UI for a human to notice" option is sufficient without ever needing
   real merge evidence.

## What still needs your decision

- Whether to apply the `status@broadcast` filter, and whether to filter
  at discovery time too (Section "Finding 1").
- The correct real webhook URL WAHA should be sending to, and whether
  you want to reconfigure it on the WAHA side (Root cause A) — this
  audit did not determine what that correct address should be, since
  that depends on your actual NetBird/LAN topology, which wasn't
  independently re-verified this task.
- Whether/when to set `WAHA_WEBHOOK_HMAC_SECRET` (Root cause B), and
  what value (must match whatever WAHA-side webhook secret is or will be
  configured for this session — not independently discoverable from
  Django's side).
- Whether to pursue any identity-alias design at all right now, given
  the evidence gap, or wait until a real webhook delivery (post-fix)
  provides the missing field-level evidence first.

---

This was a read-only audit. No implementation was performed, no live
session was changed, no message was sent, no reconciliation was
triggered. Not proceeding to Phase 9 or any implementation automatically.
