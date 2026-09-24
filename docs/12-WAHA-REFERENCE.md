# WAHA Reference

Current environment:
- image: `devlikeapro/waha:gows`
- engine: GOWS
- observed version: 2026.9.1
- API port: 3000
- sessions: `/app/.sessions`
- media: `/app/.media`

Observed endpoints:
- GET `/api/sessions`
- GET `/api/sessions/{session}`
- GET `/api/{session}/chats`
- GET `/api/{session}/chats/{chatId}/messages?limit=10`
- POST `/api/sendText`

Observed webhook event:
- `message`

Production implementation must verify endpoint details against the installed WAHA version and official documentation.

## Pagination — CONFIRMED against the real deployed instance

`GET /api/{session}/chats/{chatId}/messages` pagination, verified by the
project operator directly against this deployment (session `test_session`,
chat `000000000000000@lid`):

- `limit` + `offset` work correctly as pagination: `?limit=2` returned the
  2 newest messages; `?limit=2&offset=2` returned the next 2 older
  messages, with no overlap and no gap between the two calls.
- Ordering is **newest-first** (descending by recency).
- `page` does **not** work as pagination: `?limit=2&page=2` returned the
  identical result as `?limit=2` (i.e. `page` is silently ignored by this
  WAHA version). Never send `page`.
- Response shape is a bare JSON array of message objects (no
  `{"messages": [...]}` wrapper).
- The response includes additional top-level fields beyond what this
  project currently parses (`source`, `to`, `participant`, `hasMedia`,
  `media`, `ack`, `ackName`, `replyTo`) and additional `_data.Info.*`
  fields (`AddressingMode`, `BroadcastListOwner`, `ServerID`, `PushName`,
  `VerifiedName`, `DeviceSentMeta`, etc.) — none of these are used by the
  current parser; noted here for awareness, not yet needed.

Implemented in `apps/sync/waha_client.py` (single-page fetch with
`limit`+`offset`, never `page`) and `apps/sync/reconciliation.py` (the
bounded multi-page loop and its three stopping conditions — see that
module's docstring).

## WhatsApp Identity: LID, JID, and Phone Number

**Evidence source.** Originally based on a single reported message example
(session `test_session`). Since extended with **real evidence from the
actual deployed WAHA instance**: one live webhook delivery, plus a manual
`GET /api/test_session/chats/000000000000000%40lid/messages?limit=10` REST
query returning 4 real messages (2 inbound, 2 outbound). See
`docs/generated/PHASE-3-LIVE-VERIFICATION.md` for the full evidence and
reasoning behind every claim below. This is still evidence from **one
session, one WAHA version (GOWS, `2026.9.1`), one deployment** — do not
assume other versions/engines behave identically.

### Observed fields, inbound (2 real messages, both consistent)

```
from:                 000000000000000@lid
_data.Info.Chat:      000000000000000@lid
_data.Info.Sender:    000000000000000@lid
_data.Info.SenderAlt: 62800000000@s.whatsapp.net
fromMe / Info.IsFromMe: false
```

For inbound messages, `Sender == Chat` — the party who sent the message
*is* the chat partner, as expected for a 1:1 chat.

### Observed fields, outbound (2 real messages — structurally different from each other)

```
Message A — reply within the SAME chat as the inbound examples above:
  Chat:        000000000000000@lid   (same chat as inbound)
  Sender:      62800000001@s.whatsapp.net   (OUR OWN account — NOT the contact)
  SenderAlt:   "" (empty string)
  from:        000000000000000@lid   (matches Chat, NOT Sender)
  fromMe / Info.IsFromMe: true

Message B — a different send, same underlying phone number as above:
  Chat:        62800000000@s.whatsapp.net   (JID form)
  Sender:      62800000001:1@s.whatsapp.net  (our own account, w/ device suffix)
  from:        62800000000@c.us   (a THIRD distinct namespace — differs from
               Chat even within this same message)
  fromMe / Info.IsFromMe: true
```

### What this evidence establishes

- **Inbound**: `Sender == Chat`, consistently, across both observed
  messages. `SenderAlt` reliably carries the JID/phone form alongside the
  LID form.
- **Outbound**: `Sender` is **not** the chat partner — it is our own
  account's identifier (confirmed: `62800000001@...`, a different number
  entirely from either contact seen). `Chat` remains the conversation
  identifier regardless of direction. This confirms the Phase 3
  implementation's decision to never create/update a `Contact` from an
  outbound message's `Sender` was correct, not just a defensive guess.
- **`SenderAlt` can be an empty string, not just absent** — confirmed on
  outbound Message A (`SenderAlt: ""`). The current parser already treats
  empty string the same as missing (verified: `extract_phone_number`
  treats both as "no phone number available").
- **The top-level `from` field does not always match `Info.Chat` byte-for-byte,
  even when both refer to the same conversation** — Message B's `from`
  (`62800000000@c.us`) and `Info.Chat` (`62800000000@s.whatsapp.net`) are
  different strings, different namespaces (`@c.us` vs `@s.whatsapp.net`),
  for what is presumably the same conversation. The implementation always
  prefers `Info.Chat` over `from` when both are present (which was true in
  every observed message), so this has not caused an actual problem yet —
  but it means the `from` fallback path, if ever exercised on a message
  where `Info.Chat` is absent, could introduce yet another identifier
  namespace inconsistency. This fallback path remains untested by any real
  example (`Info.Chat`/`Info.Sender` were present in all 4 observed
  messages).
- **CONFIRMED REAL, not just theoretical: the same real-world contact can
  appear under two different primary chat identifiers.** Message B's
  `Chat`/`from` (`62800000000@s.whatsapp.net` / `62800000000@c.us`) share
  the exact phone number (`62800000000`) that appears as `SenderAlt` on
  the *other* chat (`000000000000000@lid`, seen in the inbound messages
  and outbound Message A). This is strong circumstantial evidence — not
  independently confirmed by WAHA itself the way `SenderAlt` explicitly
  links LID↔JID — that these represent the same real person, split across
  two different `Chat` identities. **Why this happens is not established
  by this evidence** (possibly different send mechanisms/targets — not
  inferred further here, per instruction not to speculate beyond
  evidence). What *is* established: storing chat/contact identity
  verbatim, as this project has always done, has a real, now-observed
  cost — it can produce two separate `Chat`/`Contact` rows for what may be
  one real conversation. This is **not** treated as a defect in the
  current implementation: per the standing rule (never merge LID/JID by
  string or phone-number similarity, and never invent a normalization
  rule not supported by evidence), no safe merge rule can be derived from
  this evidence alone, so none has been implemented. This is recorded as
  a **known, confirmed limitation** for whichever future phase addresses
  contact/chat identity resolution more deeply.
- **LID is not universally "the" primary form** — Message B shows a chat
  represented entirely in JID/`@c.us` form, no LID anywhere. The rule that
  *is* universally supported by evidence is "store whatever WAHA reports
  as primary (`Info.Chat`/`Info.Sender`, or `from` as fallback), verbatim,
  never overridden by `Alt`" — not "LID is always used."

### What remains unknown (not established by available evidence)

- **Why** the same contact appears under two different `Chat` identities
  in different messages (different send mechanism? different point in
  time? not established).
- Whether `SenderAlt`/`RecipientAlt` is reliably populated whenever a LID
  is used, or only sometimes — the one case observed where it could have
  appeared for an outbound message showed `""` (empty), and no
  `RecipientAlt` value has been observed at all.
- Group chat behavior (`Info.IsGroup = true`) — all 4 observed real
  messages are `IsGroup: false`. **Not verified.**
- Long-term LID stability for a given contact on this deployment.

### Stable provider identifier vs. what must NOT be used as DB identity

- The **primary identifier WAHA reports** for a chat/sender (`Info.Chat` /
  `Info.Sender`, falling back to top-level `from` only when the nested
  form is absent — not yet exercised by any real example) is the value to
  store as the provider identifier verbatim — whichever form (LID, JID, or
  `@c.us`) WAHA happens to report, stored as an opaque string, never
  reformatted or guessed at.
- A phone number extracted from an `Alt` field must **not** be used as the
  sole or primary database identity for a `Contact`/`Chat` — confirmed
  correct by the outbound evidence above (using it would have fabricated
  a "Contact" representing our own account).
- Do not construct or guess a JID from a phone number, a LID from
  anything, or merge two `Chat`/`Contact` rows based on phone-number
  overlap — even though real evidence now shows this overlap does happen,
  no safe merge rule is supported by the evidence, so none is implemented.

### Normalization rule — status: implemented, evidence-confirmed correct for the cases observed

1. `Contact.provider_contact_id` / `Chat.provider_chat_id` — store the
   primary identifier exactly as WAHA reports it. **Confirmed correct**
   for all 4 observed real messages (2 inbound, 2 outbound).
2. `Contact.phone_number` — populate only from a non-empty `Alt` field in
   `@s.whatsapp.net` form. **Confirmed correct**, including the
   empty-string case.
3. Never create a second `Contact`/`Chat` row using an `Alt` value as the
   primary identifier. **Confirmed correct** — and confirmed to leave the
   known limitation above (possible duplicate `Chat` rows for the same
   real contact) unresolved, deliberately, per the standing "do not
   invent a normalization rule" instruction.
4. REST vs. webhook identifier format for **messages**: **RESOLVED** — see
   the Phase 3 section below. REST vs. webhook identifier format for
   **chats/contacts** specifically (as opposed to messages) was not
   separately re-tested this round, but the REST response's `_data.Info.*`
   fields for the same chat were consistent with the webhook's, which is
   corroborating (not exhaustive) evidence they agree here too.
5. Group chat behavior remains unverified — do not assume it matches 1:1
   behavior.

This rule continues to require no schema change to the Phase 2 models.

## Webhook Envelope and Auth — Assumptions Introduced in Phase 3

Phase 3 (webhook ingestion) needed to assume a few additional facts beyond
what any prior phase confirmed. Status as of the Phase 3 Live Verification
review (see `docs/generated/PHASE-3-LIVE-VERIFICATION.md` for full
evidence):

- **Envelope shape**: top-level `event`, `session`, `payload` — **CONFIRMED**
  against one real captured webhook delivery from session `test_session`
  (event `message`, real `payload.id`/`from`/`fromMe`/`body`/`timestamp`
  all present and correctly typed).
- **Stable event/message ID — `payload.id`**: **CONFIRMED present and
  correctly parsed** against real evidence: `false_000000000000000@lid_2A19C241A2D8A0CD88E6`.
  Its shape is a composite key, not a bare token — it encodes
  `{IsFromMe}_{Chat}_{Info.ID}`. `payload.id` and `_data.Info.ID` are
  confirmed **different values** for the same message and are not
  interchangeable.
  **RESOLVED — the single biggest prior open item**: a manual REST query
  (`GET /api/test_session/chats/000000000000000%40lid/messages?limit=10`)
  against the real deployment returned `messages[].id` equal, byte-for-byte,
  to the webhook's `payload.id` for the same message
  (`false_000000000000000@lid_2A19C241A2D8A0CD88E6`). The other 3 messages
  returned by that same query follow the identical `{fromMe}_{chat}_{Info.ID}`
  format (corroborating, though only the one message was cross-checked
  directly against a captured webhook delivery). **Conclusion: reconciliation
  can safely compare `Message.provider_message_id` directly against REST
  `messages[].id` — no extraction or normalization of `_data.Info.ID` is
  needed or should be added.**
- **Webhook authentication**: still assumed to be WAHA's publicly
  documented HMAC-SHA512 signature feature (`X-Webhook-Hmac` header,
  shared secret) — **still not confirmed**. No signature/HMAC evidence has
  been captured in any round so far (the REST query used `X-Api-Key`,
  which is a separate mechanism for calling WAHA's own API, not for
  WAHA's outgoing webhook signing).
- **Outbound message structure**: field-level shape now **confirmed via
  REST** (2 real outbound messages inspected) — see the "WhatsApp
  Identity" section above for the full detail (Sender = our own account,
  Chat = conversation partner, SenderAlt often empty). **Still
  unconfirmed**: whether WAHA sends a *webhook* for outbound/self-sent
  messages at all — the 2 outbound examples were found via a REST history
  query, not a captured webhook delivery, so it remains unknown whether
  this project's webhook endpoint will ever actually receive an outbound
  `message` event in practice.
- **Group message structure**: still entirely unverified — all 4 real
  messages observed so far are `IsGroup: false`.

If further live verification changes any of this, update this section and
`apps/webhooks/parsing.py` / `apps/webhooks/authentication.py` together —
the code's docstrings point back here.
