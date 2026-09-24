# Phase 2.5 — WAHA LID/JID Identity Verification

Read-only verification. No Django models, migrations, or application code
were modified. `docs/12-WAHA-REFERENCE.md` was updated with a new section;
no other documentation file required changes (see Section 9).

## 1. Files inspected

- `docs/12-WAHA-REFERENCE.md`
- `docs/04-DATA-MODEL.md`
- `docs/05-WEBHOOK-SYNC-DESIGN.md`
- `docs/07-API-CONTRACT.md`
- `docs/CLAUDE.md`
- `docs/14-REPOSITORY-STRUCTURE.md` (checked for consistency per Section 9)
- Repository-wide search for any stored webhook payload/fixture files
  (none exist — see Section 3)

None of the four architecture/data documents (04, 05, 07, CLAUDE.md)
mention LID, JID, or any WhatsApp identifier format prior to this phase's
edit to `12-WAHA-REFERENCE.md`. `04-DATA-MODEL.md`'s only identity-related
statement is the "Message identity" rule (stable provider ID scoped by
session, never body/timestamp/sender) — which concerns the *message's own*
identity, not participant (contact/chat) identity, and is unaffected by
this verification.

## 2. WAHA environment inspected

**Not independently inspected — no access available from this session.**
Concretely checked and confirmed absent:

- `docker ps` — Docker daemon itself is not reachable from this session
  (`error during connect: ... dockerDesktopLinuxEngine ...`); no containers
  of any kind could be listed, let alone a WAHA one.
- `curl http://localhost:3000/api/sessions` — connection failed (exit 7,
  connection refused/unreachable).
- No `WAHA_BASE_URL`/`WAHA_API_KEY`-style environment variables set in this
  shell; no relevant `/etc/hosts` entries.
- Repository-wide search for the exact strings `000000000000000`,
  `62800000000`, `test_session`, `@lid`, `SenderAlt` — **zero matches**
  anywhere in the project (no fixture, log, or captured-payload file
  exists on disk).

Reported environment (operator-supplied, not independently verified by
this session): image `devlikeapro/waha:gows`, engine GOWS, observed
version `2026.9.1`, session name `test_session`. This matches what was
already in `docs/12-WAHA-REFERENCE.md` prior to this phase, except the
session name, which is new information from this conversation and is
recorded in the new doc section as the source example's session — not
added to the general "Current environment" block, since that block
describes the environment generally rather than one specific session.

## 3. Real payload evidence

**No payload file exists in this project.** The field values in your
instructions (`from: 000000000000000@lid`, `Info.SenderAlt:
62800000000@s.whatsapp.net`, etc.) are the only source of this data
available to this session — supplied directly in your message, not read
from a file, log, or live API response by any assistant action.

This is stated plainly because your instructions describe this as "the
real webhook payload already captured by the project," and I want the
record to be accurate: it is not currently captured *in* the project (no
file holds it) — it exists only in this conversation. I did not treat this
as a reason to distrust the data (see reasoning below), but I recommend
saving the raw payload into the repository if you want it to remain
available as durable, independently re-checkable evidence — right now
`docs/12-WAHA-REFERENCE.md`'s new section is the only place it's recorded.

**Why I treated the reported data as credible anyway:** the field names
given (`_data.Info.Chat`, `_data.Info.Sender`, `_data.Info.SenderAlt`,
`_data.Info.RecipientAlt`, `_data.Info.IsGroup`, `_data.Info.IsFromMe`,
`_data.Info.Type`) match whatsmeow's (the Go library GOWS is built on)
internal `MessageInfo` struct field names precisely, including the
`SenderAlt`/`RecipientAlt` fields whatsmeow added specifically to carry a
linked alternate identifier once WhatsApp began rolling out LIDs. This is
a level of structural detail that lines up with genuine library internals
rather than a generic/invented example. I'm relying on general knowledge
of the whatsmeow/WAHA field-naming convention only to *recognize* that this
is plausible, real payload shape — not to assert anything about *this
deployment's* actual runtime behavior beyond what's in the reported
example.

## 4. Observed identity fields

| Field | Reported value | Role |
|---|---|---|
| `from` (top-level) | `000000000000000@lid` | Simplified WAHA API sender field, LID form |
| `_data.Info.Chat` | `000000000000000@lid` | Raw whatsmeow chat identifier, LID form |
| `_data.Info.Sender` | `000000000000000@lid` | Raw whatsmeow sender identifier, LID form |
| `_data.Info.SenderAlt` | `62800000000@s.whatsapp.net` | Linked alternate identifier for the same sender, JID/phone form |
| `_data.Info.RecipientAlt` | not given a concrete value | Presumed alt form of the recipient; unconfirmed |
| `_data.Info.IsGroup`, `IsFromMe`, `Type` | not given concrete values | Listed as fields to check; not analyzable without example values |

`Chat` and `Sender` being identical in this example is expected for a
direct (non-group) chat, where the chat's identity and the sole other
participant's identity coincide.

## 5. LID/JID findings

**Established** (from this one example): WAHA/GOWS can report a
participant using an LID-form identifier as the *primary* `Sender`/`Chat`
value, while simultaneously exposing the corresponding JID/phone-number
form for the *same* participant in a separate `SenderAlt` field on the
same event. WAHA itself is asserting the linkage — it is not something
that has to be inferred or guessed.

**Not established** (explicitly unknown, stated per your instruction not
to claim certainty without evidence):
- Whether `Sender`/`Chat` is always LID for this contact, or can vary.
- Whether `SenderAlt`/`RecipientAlt` is reliably present whenever LID is
  used, or only sometimes.
- What identifier form the REST `chats`/`messages` endpoints return for
  the same chat (not observed at all).
- Group-chat behavior (`IsGroup = true` case — no example available).
- LID stability over time for a given contact on this deployment.

## 6. Contact identity conclusion

`Contact.provider_contact_id` should store WAHA's reported *primary*
identifier for the contact (`Sender`, as observed) verbatim, in whichever
form WAHA gives it (LID or JID) — the field is a format-agnostic
`CharField`, so it can structurally hold either. `Contact.phone_number`
should be populated from an `Alt` field only when present, treated as
optional supplementary data, never as the row's identity key. This
directly mirrors the schema's existing two-field split — see Section 8.

## 7. Chat identity conclusion

`Chat.provider_chat_id` should follow the same rule as `Contact`: store
WAHA's primary `Chat` value verbatim. For the one direct-chat example
available, this coincides with the sender's identifier; group-chat
behavior is unverified and should be checked before Phase 3 treats it as
settled (see the open item in the new `12-WAHA-REFERENCE.md` section).

## 8. Message identity conclusion

No evidence suggests `Message.provider_message_id` is affected by the
LID/JID distinction — that distinction concerns *participant* identifiers
(who sent/received), not the message's own stable ID token. The existing
`04-DATA-MODEL.md` "Message identity" rule (stable provider ID scoped by
session) is orthogonal to this finding and requires no change.

## 9. Schema impact

**No migration required.** The Phase 2 schema shape — `Contact` with a
single opaque `provider_contact_id` plus an optional `phone_number`, and
`Chat` with a single opaque `provider_chat_id` — already matches the
"primary identifier + optional supplementary phone number" shape the
observed evidence calls for. What was missing was not a field, but a
*documented rule* for which WAHA field populates `provider_contact_id`
and which populates `phone_number`, and an explicit instruction not to
key identity off the `Alt` field. That rule is now recorded in
`docs/12-WAHA-REFERENCE.md`.

Cross-document consistency check: `04-DATA-MODEL.md`, `05-WEBHOOK-SYNC-DESIGN.md`,
`12-WAHA-REFERENCE.md`, `14-REPOSITORY-STRUCTURE.md`, and `CLAUDE.md` were
compared. No contradictions found. `14-REPOSITORY-STRUCTURE.md` does not
touch identity at all. `04-DATA-MODEL.md`'s message-identity rule and
`05-WEBHOOK-SYNC-DESIGN.md`'s "compare stable IDs" reconciliation language
are both about message-level identity, which this phase's findings do not
alter. No other documentation file required changes.

## 10. Recommended Phase 3 rules

Per the "Recommended normalization rule" now in `docs/12-WAHA-REFERENCE.md`:

1. Store the primary WAHA-reported identifier (`Sender`/`Chat`, or the
   simplified `from`/`to`/chat-id equivalent) verbatim as
   `provider_contact_id`/`provider_chat_id` — never the `Alt` form.
2. Populate `phone_number` from an `Alt` field only when present; treat
   absence as normal, not an error.
3. Never create a second `Contact`/`Chat` row keyed by an `Alt` value when
   a row already exists under the primary identifier from the same event.
4. Before writing the actual ingestion code, confirm live: (a) REST
   `chats`/`messages` endpoint identifier form vs. webhook primary field
   for the same chat, and (b) group-chat behavior. Both are open items,
   not blocking documentation, but should inform the ingestion
   implementation directly.

## 11. Remaining unknowns

- LID/JID consistency over time and across API surfaces (webhook vs. REST)
  for the same contact/chat — unverified.
- `SenderAlt`/`RecipientAlt` reliability (always present vs. sometimes) —
  unverified.
- Group-chat identifier behavior — unverified (no example available).
- Long-term LID stability for a given contact on this specific deployment
  — unverified (general WhatsApp platform design intends stability, but
  that is outside knowledge, not a confirmed observation here).
- The message's own stable-ID field name/format — not shown in the
  reported example; believed unaffected by this finding but not directly
  confirmed.

## 12. Is Phase 3 safe to begin?

**Conditionally yes**, with the normalization rule above treated as
best-current-understanding rather than fully settled fact. The Phase 2
schema requires no change. The open items in Section 11 — particularly
REST-vs-webhook identifier consistency and group-chat behavior — should be
confirmed against live traffic before (or early within) Phase 3's webhook
ingestion work, since getting them wrong risks silently fragmenting
contact/chat history (multiple rows for one real contact). This is a
recommendation to verify defensively during Phase 3, not a blocker to
starting it.

---

**Summary for the end of this phase:**
- **Phase 3 can proceed.**
- **No schema change is required.**
- **Identity rule Phase 3 should follow:** store WAHA's primary reported
  identifier (`Sender`/`Chat`) verbatim as `provider_contact_id`/
  `provider_chat_id`; populate `phone_number` only from an `Alt` field
  when present; never key identity off an `Alt` value; verify REST-endpoint
  identifier consistency and group-chat behavior against live traffic
  during Phase 3 implementation rather than assuming them.
