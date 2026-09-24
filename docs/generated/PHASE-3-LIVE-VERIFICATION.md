# Phase 3 — Live Verification / Hardening Review

Third and current revision. No application code was changed in any round
of this review — every finding below was either (a) evidence you captured
directly from the real deployed WAHA instance, or (b) this project's
already-committed code executed against that real evidence using a
disposable in-memory database, never the real Postgres. No architecture,
schema, or normalization rule was changed or invented.

All evidence is from one deployment: WAHA `devlikeapro/waha:gows`, engine
GOWS, version `2026.9.1`, session `test_session`. Nothing here should be
assumed to hold for other WAHA versions/engines.

## Round 1 recap (network reachability only)

Confirmed genuine network reachability to `<TENCENT_WAHA_HOST>:3000` (ping +
authentic WAHA/NestJS 401 responses on every route tested). No API key was
available to that round, so no authenticated call could be made. Full
detail preserved in git history of this file / the original round-1
content is superseded by the rounds below.

## Round 2 recap (webhook payload + code-level replay)

You supplied one real captured inbound webhook (session `test_session`,
`payload.id = false_000000000000000@lid_2A19C241A2D8A0CD88E6`). This
project's actual `parse_envelope`/`parse_message`/`ingest_webhook` code
was executed against it (disposable in-memory SQLite, not the real
Postgres): every field parsed correctly, including an exact timestamp
match, and redelivering the identical payload produced zero duplicate
rows.

## Round 3 — new evidence (this update)

You manually queried the real deployment:
`GET /api/test_session/chats/000000000000000%40lid/messages?limit=10`,
returning 4 real messages (2 inbound, 2 outbound).

### Confirmed facts

1. **REST `messages[].id` == webhook `payload.id`**, byte-for-byte, for
   the same message (`false_000000000000000@lid_2A19C241A2D8A0CD88E6`).
   This is the single most consequential new fact — see "Blockers"
   below.
2. **`payload.id` / `messages[].id`** and **`_data.Info.ID`** are
   confirmed distinct, non-interchangeable values across all 4 messages
   (e.g. `false_000000000000000@lid_2A19C241A2D8A0CD88E6` vs.
   `2A19C241A2D8A0CD88E6`).
3. **Inbound identity**: `Sender == Chat` (both `000000000000000@lid`)
   consistently across both inbound messages; `SenderAlt` consistently
   `62800000000@s.whatsapp.net`; `fromMe`/`Info.IsFromMe` = `false`.
4. **Outbound identity, confirmed**: `Sender` is **our own account**
   (`62800000001@s.whatsapp.net`, and `62800000001:1@s.whatsapp.net`
   with a device suffix in the second example) — **not** the chat
   partner. `Chat` remains the conversation identifier regardless of
   direction. This directly confirms the Phase 3 implementation's
   decision never to create/update a `Contact` from an outbound message's
   `Sender` was correct.
5. **`SenderAlt` can be an empty string**, not just absent (`""` observed
   on one outbound message). The current parser already handles this
   correctly (verified: empty string is treated the same as missing).
6. **The same real-world phone number appears under two different
   primary `Chat` identifiers** across different messages:
   `000000000000000@lid` (inbound + one outbound reply) vs.
   `62800000000@s.whatsapp.net`/`@c.us` (a separate outbound message) —
   the latter's number matches the former's `SenderAlt` exactly. This
   confirms, with real evidence, a risk that was previously only
   theoretical (see "Known limitation," below).
7. **The top-level `from` field is not always byte-identical to
   `Info.Chat`**, even within the same message and even when referring to
   the same conversation — one outbound example has `from:
   62800000000@c.us` and `Info.Chat: 62800000000@s.whatsapp.net`
   simultaneously. The implementation always preferred `Info.Chat` in
   every observed case (it was present every time), so this has not
   caused an actual parsing problem — but the `from`-fallback code path
   remains untested by any real example.
8. **LID is not universally "the" primary identifier form** — one
   outbound message's `Chat` is represented entirely in JID/`@c.us` form
   with no LID anywhere. The rule that *is* universally supported:
   "store whatever WAHA reports as primary, verbatim, never override with
   `Alt`" — not "LID specifically is always used."

### Still-unverified items

- **Webhook HMAC authentication** — no signature/HMAC evidence has been
  captured in any round. `X-Api-Key` (used for this round's REST query)
  is a separate mechanism from webhook signing and does not inform this.
- **Whether WAHA sends a webhook for outbound/self-sent messages at
  all** — the 2 outbound examples were found via REST history query, not
  a captured webhook delivery. Field structure is now confirmed; webhook
  *delivery* of that structure is not.
- **Group message/chat behavior** — all 4 real messages observed across
  every round are `IsGroup: false`.
- **WAHA → this project's actual Django endpoint, live delivery** — still
  not tested; all evidence gathered this round was via manual REST GET
  queries, not a live webhook POST to `/api/webhooks/waha/`.
- **Django → real PostgreSQL persistence** — still not tested; all
  code-level verification used a disposable in-memory SQLite database.
- **Why the same contact appears under two different `Chat` identities**
  — observed (fact 6 above), but the mechanism is not established by this
  evidence and is not speculated on further here.
- **Long-term LID stability** for a given contact on this deployment.

### Any code changes

**None.** Per your instruction, code is changed only if evidence
demonstrates the existing implementation is incorrect. It does not:
`payload.id` as both `provider_event_id` and `provider_message_id` is
now positively confirmed correct (fact 1); the outbound Contact-skip
design is confirmed correct (fact 4); empty-string `SenderAlt` handling
is confirmed correct (fact 5); verbatim, non-merging storage of
`Chat`/`Contact` identifiers is confirmed to behave exactly as designed,
including in the case that reveals its known limitation (fact 6) — which
is not a bug, since no safe merge rule is supported by this evidence and
none was invented, per the standing rule repeated again in your own
instructions this round (point 8: "SenderAlt should remain optional
metadata rather than the primary identity").

### Any documentation changes

`docs/12-WAHA-REFERENCE.md`:
- "WhatsApp Identity" section rewritten to incorporate all 4 real
  messages: new outbound field tables, the confirmed empty-`SenderAlt`
  case, the confirmed `from`≠`Info.Chat` namespace inconsistency, and the
  now-confirmed-real (not just theoretical) same-contact-two-Chat-IDs
  finding, explicitly marked as a known limitation rather than a defect.
- "Webhook Envelope and Auth" section updated: the `payload.id` vs.
  REST `messages[].id` question is marked **RESOLVED**; outbound
  structure marked **field-shape confirmed / webhook-delivery still
  unconfirmed**.

This file (`docs/generated/PHASE-3-LIVE-VERIFICATION.md`) rewritten to
fold all three rounds into one coherent, current document.

### Known limitation (not a defect) — identity fragmentation risk, now confirmed real

Storing `Chat`/`Contact` identifiers verbatim (per the standing,
repeatedly-reaffirmed rule) means the same real-world contact **can**
end up represented by two separate `Chat`/`Contact` rows if WAHA reports
them under different primary identifiers in different messages, as
observed in fact 6. This project has not implemented, and per your
explicit instruction should not invent, any merge/normalization logic to
collapse these — doing so "based only on string similarity or phone
number," which is the only signal currently available, is exactly what
you've asked not to do. This is recorded here as a known, real,
evidence-backed limitation for whichever future phase takes on deeper
identity resolution, not something Phase 3 or this review should attempt
to fix now.

### Whether the remaining Phase 3 blockers are resolved

From the prior round's blocker list:

1. ~~REST endpoint identifier format unverified~~ — **RESOLVED** (fact 1).
   This was the most architecturally significant blocker, since it
   directly gates whether Phase 4 reconciliation's core comparison
   (webhook-sourced vs. REST-sourced message identity) can work at all.
2. **HMAC/webhook authentication — still unresolved.** No new evidence.
3. **No live delivery test against this project's actual endpoint —
   still unresolved.**
4. **No live Django ↔ PostgreSQL test — still unresolved.**
5. ~~Outbound handling entirely unverified~~ — **partially resolved**:
   field-level structure is now confirmed (facts 4, 5, 7, 8); whether
   outbound messages arrive via webhook at all remains open.
6. **New item this round**: the identity-fragmentation risk (fact 6) is
   now a confirmed, real design constraint rather than a hypothetical —
   not a blocker to implementation, but something any reconciliation or
   identity-resolution work must consciously account for rather than
   discover by surprise.

### Whether Phase 4 may now proceed

**Nuanced answer, not a flat yes/no, because the evidence itself is
nuanced:**

The single blocker most directly relevant to Phase 4's actual subject
matter — reconciliation comparing webhook-ingested data against
REST-fetched history — is now resolved with strong, real evidence
(fact 1). That was the most important open question from the prior
review, and it came back in Phase 4's favor: `Message.provider_message_id`
can be compared directly against REST `messages[].id`, no translation
layer needed.

Separately, the production-readiness gaps for the *existing* webhook
pipeline (HMAC auth, live Django delivery, live Postgres persistence)
remain open — but these are orthogonal to Phase 4's own implementation
and testing, which (like Phase 3 was) can be built against fixtures and
this now-real evidence, then subjected to its own live-verification pass
afterward, the same pattern already used successfully across Phases 3
and this review.

The one thing Phase 4 must **not** do is treat identity resolution as
solved: fact 6 confirms real contacts can fragment across two `Chat`
rows, and reconciliation logic must be designed with that reality in mind
(e.g., not silently assuming one `Chat` row per real contact) rather than
discovering it as a surprise defect later.

Given all of this, my honest assessment: **implementation of Phase 4 is
now reasonably supportable** on the strength of fact 1, **conditional on**
Phase 4's design explicitly acknowledging the identity-fragmentation
limitation rather than ignoring it, and **not** claiming the pipeline is
production-ready (HMAC/live-delivery/live-Postgres gaps still stand). I
am not starting Phase 4 in this turn — every one of your instructions
this round said not to, and that decision is yours to make.
