# Inbox — Why `62811520892` Displays as `168160971997355@lid`

Read-only. **No source, database, `.env`, config, WAHA session, or data
was changed.** No message was sent. No identity merge was performed or
proposed for automatic execution. This audit uses **two real, fresh
webhook deliveries** received after the webhook-config fix
(`docs/generated/INBOX-WEBHOOK-FIX-REPORT.md`) — not reconciliation-
derived data, per your explicit instruction.

## ROOT CAUSE

**This is not a merge bug and not a wrong-chat bug.** The message
genuinely belongs to `Chat.provider_chat_id = "168160971997355@lid"` —
that *is* the chat WAHA reports for this conversation on inbound
delivery, confirmed twice now by real webhooks. The number
`62811520892` is displayed instead of the `@lid` string **nowhere** in
this system — it never was. What you're seeing is simply the **fallback
to the raw provider chat ID**, because nothing has ever populated a
human-readable name for this chat or its contact: `Chat.name` is empty,
`Contact.display_name` is empty. `Contact.phone_number` (`62811520892`)
*is* already correctly stored and already linked to this exact chat —
it's just never been wired into what the UI displays. See "CURRENT INBOX
DISPLAY LOGIC" below for the exact line.

## RAW WEBHOOK IDENTITY EVIDENCE

Two real `WebhookEvent` rows (`event_type='message'`, `status='processed'`)
arrived after the config fix: ids 3 and 4, received
2026-09-24 14:44:21 and 14:44:33 UTC. Full raw payload of the most recent
(id 4), every identity-relevant field — **no secret/HMAC/API-key/token
value appears in this payload at all** (webhook payloads only ever carry
message content and WhatsApp-side metadata, never this project's own
credentials):

| Field (your requested name) | Actual field in payload | Value |
|---|---|---|
| `id` | top-level `id` | `false_168160971997355@lid_2A07362EE6000A851353` |
| `chatId` | `_data.Info.Chat` | `168160971997355@lid` |
| `from` | top-level `from` | `168160971997355@lid` |
| `to` | top-level `to` | `null` |
| `sender` | `_data.Info.Sender` | `168160971997355@lid` |
| `senderAlt` | `_data.Info.SenderAlt` | **`62811520892@s.whatsapp.net`** |
| `participant` (group sender) | top-level `participant` | `null` |
| `author` | — | **field does not exist anywhere in this payload** — WAHA/whatsmeow's real schema uses `Sender`/`Chat`/`SenderAlt`/`RecipientAlt`, not `author`; not invented, not found |
| `RecipientAlt` | `_data.Info.RecipientAlt` | `""` (empty string, not null) |
| `fromMe` | top-level `fromMe` (and `_data.Info.IsFromMe`, matching) | `false` |
| `body` | top-level `body` | `"Wah udah masuk nih webhookny­a"` |
| `timestamp` | top-level `timestamp` (unix) / `_data.Info.Timestamp` (ISO) | `1790261074` / `2026-09-24T14:44:34Z` |
| `_serialized` | — | not present under this name anywhere in the payload |
| (new, not previously requested) | `_data.Info.PushName` | **`"Yuk Code Creative"`** — see "SAFE FIX OPTIONS" |
| (new) | `_data.Info.IsGroup` | `false` |

**What each identifier represents, determined directly from this real
payload** (not inferred from older reconciliation data):

- **`62811520892`**: only ever appears via `SenderAlt`
  (`62811520892@s.whatsapp.net`) — never as a top-level field, never as
  `Chat`, never as `Sender`.
- **`168160971997355@lid`**: the chat/conversation identifier —
  `_data.Info.Chat`, matching the top-level `from` (inbound message,
  `Sender == Chat`, consistent with every prior inbound example already
  documented in `docs/12-WAHA-REFERENCE.md`).
- **Our own account**: not present in this specific payload at all —
  `to` is `null` for this inbound delivery (the earlier, older reference
  evidence for "our own account's identifier" came from *outbound*
  messages, a different payload shape, not this one).
- **The WAHA chat/conversation ID**: `168160971997355@lid`, same as
  above — there is only one chat identifier in this payload, not two
  competing ones.

## DATABASE IDENTITY EVIDENCE

Both real messages were correctly persisted into the **already-existing**
`Chat` id 3 (not a new row — `persist_message()`'s `get_or_create` found
the existing chat by `provider_chat_id`):

```
Message id 42: chat_id=3, provider_message_id=false_168160971997355@lid_2A6981D843E638E21C36, direction=inbound, body="Tes", timestamp=2026-09-24 14:44:22 UTC
Message id 43: chat_id=3, provider_message_id=false_168160971997355@lid_2A07362EE6000A851353, direction=inbound, body="Wah udah masuk nih webhooknya", timestamp=2026-09-24 14:44:34 UTC

Chat id 3:  provider_chat_id=168160971997355@lid, contact_id=3, name='' (empty), last_message_at=2026-09-24 14:44:34 UTC
Chat id 8:  provider_chat_id=62811520892@s.whatsapp.net, contact_id=None, name='' (empty), last_message_at=2026-09-23 13:05:13 UTC (unchanged by this webhook)

Contact id 3: provider_contact_id=168160971997355@lid, phone_number=62811520892, display_name='' (empty)
```

**Schema correction to your question**: `Message` has **no `sender` or
`recipient` field at all** — confirmed directly from the model
(`backend/apps/chats/models.py`, fields: `session, chat,
provider_message_id, direction, message_type, body, status, timestamp`
— nothing else). Sender/recipient identity is not stored per-message in
this schema; it only exists at the `Contact`/`Chat` level. This isn't a
bug this audit found — it's this project's existing, deliberate schema
(`Message identity` rule, `docs/04-DATA-MODEL.md`), stated here because
your requested field list assumed it might exist.

**Comparing Chat 3 and Chat 8, directly**: `Chat.contact` links Chat 3 to
Contact 3 (`phone_number=62811520892`). **Chat 8 has `contact_id=None` —
it is not linked to any Contact at all**, including Contact 3. This is
because `persist_message()` only ever creates/links a `Contact` from an
**inbound, non-group** message (`if not parsed.from_me and not
parsed.is_group`) — Chat 8's 3 messages are all `outbound`
(`true_62811520892@c.us_...` provider_message_ids, confirmed earlier this
session), so no Contact-linking logic ever ran for them at all. This is
existing, already-verified, deliberate behavior
(`apps/webhooks/parsing.py` module docstring: "Contact identity is only
ever derived from INBOUND, non-group messages").

## Answering your question 8 directly

**Is `168160971997355@lid → 62811520892` proven by the newest webhooks,
or only by old reconciliation data?**

**Proven independently by the newest webhooks — not only inherited from
reconciliation.** Both fresh, real, live-delivered messages (ids 42, 43)
carry `SenderAlt = 62811520892@s.whatsapp.net` on the *exact same*
`Chat`/`Sender` (`168160971997355@lid`) your earlier reconciliation run
had already observed. `persist_message()` re-ran its
`extract_phone_number()` check on this fresh data and found the value
**unchanged** (`62811520892`, matching what was already stored) —
independent confirmation, not a repeat of stale data. **This strengthens
confidence in exactly the inbound mapping this project's rule already
trusts** (`@lid` chat + inbound `SenderAlt` → phone number) — it does
**not** newly prove anything about Chat 8 (`62811520892@s.whatsapp.net`),
since neither of these two fresh webhooks is an outbound message from
that chat, or any message on Chat 8 at all. The evidence gap for Chat 8
specifically (identified in the prior audit) is **unchanged** by this
new data.

## CURRENT INBOX DISPLAY LOGIC

Exact location, both places the displayed name is chosen — no merge
logic, no identity resolution, just a plain fallback chain:

```
frontend/src/pages/InboxPage.tsx:190  (chat list item)
frontend/src/pages/InboxPage.tsx:211  (conversation header)
{chat.name || chat.contact_name || chat.provider_chat_id}
```

- `chat.name` — Django's `Chat.name` field, via `ChatListSerializer`
  (`backend/apps/chats/serializers.py`) — **always empty**, nothing in
  this codebase has ever written to it.
- `chat.contact_name` — `ChatListSerializer.get_contact_name()`, returns
  `obj.contact.display_name` — **always empty**, `Contact.display_name`
  is never populated by `persist_message()`
  (`backend/apps/webhooks/services.py`) or anywhere else.
- Falls through to `chat.provider_chat_id` — the raw, always-populated
  identifier — which for this chat is `168160971997355@lid`.

## WHY 62811520892 APPEARS AS 168160971997355@lid

Because both of the two fields that *would* show something friendlier
(`Chat.name`, `Contact.display_name`) are empty, and the fallback
correctly (not incorrectly) falls all the way back to the one field
that's guaranteed to exist: the raw provider chat ID. **This is the
system behaving exactly as coded — a display-completeness gap, not an
identity-resolution defect.** The phone number `62811520892` was never
"lost" or "merged away" — it's sitting right there in
`Contact.phone_number`, correctly linked, just never read by the
serializer or the frontend.

## SAFE FIX OPTIONS (not implemented — no merge required for any of these)

All three below operate **only on Chat 3's own, already-linked Contact**
— none of them touches Chat 8, none of them merges or creates a
cross-chat identity link, none of them guesses at a phone-number-string
match:

1. **Expose `Contact.phone_number` in the API and use it as a display
   fallback.** `ChatListSerializer` already has the Contact object in
   hand (`select_related('contact')`); add a `phone_number` field
   alongside the existing `contact_name`, and have the frontend fall
   back to it: `chat.name || chat.contact_name || chat.phone_number ||
   chat.provider_chat_id`. Zero parsing change, zero migration — the
   data already exists and is already correctly linked.
2. **Populate `Contact.display_name` from `_data.Info.PushName`.**
   **New evidence, not previously documented**: this real payload
   includes `_data.Info.PushName: "Yuk Code Creative"` — WhatsApp's own
   self-reported display name for the sender, sitting unused in every
   inbound webhook this project has ever received. Extracting it in
   `apps/webhooks/parsing.py::parse_message()` (same file, same
   function, same evidence-gated style already used for every other
   field) and writing it to `Contact.display_name` in
   `persist_message()` (`backend/apps/webhooks/services.py`) would give
   a genuinely friendly name, still scoped to Chat 3/Contact 3 alone —
   no merge. **Caveat**: this is the *first* time `PushName` has been
   observed in this project's evidence — its reliability (always
   present? stable across messages? absent for some senders?) hasn't
   been established the way `SenderAlt` has across multiple examples,
   so treat it the same evidence-gated way this project treats every
   other field: extract defensively, never required, log and continue
   if absent.
3. **Both together** — `PushName` as the primary friendly name,
   `phone_number` as a secondary fallback, `provider_chat_id` as the
   final fallback exactly as today. No option here requires deciding
   anything about Chat 8 or any merge.

## RISKS OF AUTO-MERGING LID/JID (restated, not newly changed by this audit)

This audit's new evidence does not reduce these risks — it only
strengthens the *inbound* side of the picture, which was never the risky
side to begin with:

- Outbound messages have already been documented (and, per this
  project's own evidence, structurally observed) reporting `Chat`/
  `Sender` values that represent **your own account**, not the contact —
  in the *same* ID shapes (`@s.whatsapp.net`, `@c.us`) that a real
  contact's chat can also appear in. A phone-number-string match alone
  cannot distinguish these two cases.
- Chat 8 specifically has **zero** inbound messages and **zero** linked
  Contact — there is still no direct evidence establishing what real-
  world entity Chat 8 actually represents, only a suggestive (not
  proven) phone-number coincidence with Chat 3.
- Group-chat behavior remains completely unverified in this project.
- No `RecipientAlt` value has ever been observed non-empty anywhere,
  including in this newest evidence (`""` again) — one whole class of
  potential corroborating evidence remains untested.

**None of this new evidence changes the standing recommendation: no
automatic merge rule is safe to implement yet.**

## RECOMMENDED NEXT STEP

Not a decision made for you — options, in increasing order of scope:

1. **Smallest, zero-risk**: Fix Option 1 alone (expose
   `Contact.phone_number`, frontend fallback) — makes Chat 3 display
   `62811520892` instead of the raw `@lid` string, today, using data
   that already exists and is already correctly linked. No merge, no
   new field, no migration.
2. **Slightly larger, still zero-merge**: Add Fix Option 2 (`PushName`
   extraction) alongside it, for an even friendlier name
   ("Yuk Code Creative") — needs a small parser change but no schema
   change (`Contact.display_name` already exists, just unused).
3. **Deferred, needs your decision, not evidence-ready**: whether/how to
   address Chat 8 (and any other `@c.us`/`@s.whatsapp.net` duplicate)
   at all — still blocked on the same evidence gap the prior audit
   identified; this task's new webhook data doesn't close it.

This audit stops here, as instructed. Waiting for your decision on which
(if any) of the above to implement.

---

Read-only audit complete. No implementation performed. Not proceeding
automatically.
