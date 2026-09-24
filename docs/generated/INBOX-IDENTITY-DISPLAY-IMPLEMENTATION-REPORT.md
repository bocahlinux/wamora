# Inbox Identity-Display Implementation Report

Implements the user-approved "Option 3" fix from
[`INBOX-IDENTITY-DISPLAY-AUDIT-REPORT.md`](INBOX-IDENTITY-DISPLAY-AUDIT-REPORT.md):
expose `Contact.phone_number` via the chat-list API and use WhatsApp's
`PushName` field to populate `Contact.display_name`, so the Inbox shows a
human-friendly identity instead of the raw `provider_chat_id`
(`168160971997355@lid`).

No ambiguity was found before implementation, so this went straight to
implementation per the user's own instruction ("Kalau tidak ada ambiguity,
implementasikan perubahan minimal lalu buat report").

## Scope discipline (explicit constraints, verified)

- **No auto-merge.** No code anywhere compares or merges `@lid` /
  `@s.whatsapp.net` / other identity forms. The only identity resolution
  used is `Chat.contact` links that already existed before this change.
- **No existing Chat/Contact association changed.** Nothing here creates
  a `Contact`, changes which `Contact` a `Chat` points to, or edits any
  row other than `display_name` on an *already-resolved* `Contact`.
- **Display-only.** The change is: (a) expose an existing DB field over
  the API, (b) populate another existing DB field from a payload field
  that was already being parsed and stored elsewhere, (c) change how the
  frontend renders those fields. No new persistence rule, no new
  matching logic.
- **BFF, Session Management, send-message, auto-merge, Phase 9**: not
  touched. `git diff --stat` (below) confirms the changed files are
  limited to `backend/apps/webhooks/`, `backend/apps/chats/`,
  `frontend/src/lib/djangoApi.ts`, `frontend/src/pages/InboxPage.tsx`,
  `frontend/src/pages/InboxPage.css`, plus their tests.
- **No outbound WhatsApp message was sent** during this work. All
  verification used the existing automated test suite (fixtures/synthetic
  `ParsedMessage` objects) — no live webhook, no live send.
- **`status@broadcast` filtering**: not touched, as instructed.

## Changes

### Backend

**`backend/apps/webhooks/parsing.py`**
- `ParsedMessage` gained a `push_name: Optional[str]` field.
- `parse_message()` now reads `_data.Info.PushName`, defensively coerced
  to `None` unless it is a non-empty string (same defensive style as the
  file's other optional-field extraction).

**`backend/apps/webhooks/services.py`** (`persist_message`)
- Inside the existing `if not parsed.from_me and not parsed.is_group:`
  block — the same block that already resolves/creates the `Contact` and
  updates `phone_number` — added:
  ```python
  if parsed.push_name and contact.display_name != parsed.push_name:
      contact.display_name = parsed.push_name
      contact.save(update_fields=['display_name', 'updated_at'])
  ```
  Because this is the *same* `contact` object already resolved by the
  pre-existing `get_or_create(session=session,
  provider_contact_id=parsed.sender_provider_id)` call above it, it is
  structurally impossible for this line to create a new `Contact` or
  touch a different `Chat`/`Contact` row. Outbound and group messages
  never enter this block at all, so a `PushName` on those payloads is
  silently ignored (verified by test).

**`backend/apps/chats/serializers.py`** (`ChatListSerializer`)
- Added `phone_number = serializers.SerializerMethodField()`, reading
  `obj.contact.phone_number`. Reuses the view's existing
  `select_related('contact')` — no new query (verified by the existing
  N+1 test, still asserting exactly 2 queries against `chats_chat`).

### Frontend

**`frontend/src/lib/djangoApi.ts`**
- `ChatSummary` gained `phone_number: string | null`.

**`frontend/src/pages/InboxPage.tsx`**
- New helper:
  ```ts
  function chatDisplay(chat: ChatSummary): { primary: string; secondary: string | null } {
    const friendlyName = chat.name || chat.contact_name;
    if (friendlyName) return { primary: friendlyName, secondary: chat.phone_number };
    if (chat.phone_number) return { primary: chat.phone_number, secondary: null };
    return { primary: chat.provider_chat_id, secondary: null };
  }
  ```
  This is exactly the fallback chain the user specified: name → phone →
  `provider_chat_id`, with phone shown as secondary text when a name is
  available (e.g. "Yuk Code Creative" / "62811520892").
- Both display sites — the chat-list item and the conversation header —
  now use `chatDisplay()` instead of rendering `provider_chat_id`
  directly.

**`frontend/src/pages/InboxPage.css`**
- Added `.wa-inbox__chat-item__secondary`,
  `.wa-inbox__conversation-title-group`, `.wa-inbox__conversation-subtitle`
  for the new secondary-line rendering.

## Existing data (Chat/Contact for `168160971997355@lid`)

No backfill/migration was needed. `ChatListSerializer.get_phone_number`
reads `Contact.phone_number` directly, and the audit already established
that this specific `Contact` row has `phone_number = "62811520892"` set
(from the earlier `SenderAlt`-derived extraction). So this chat will show
`62811520892` as soon as the API is hit — no new `PushName` required for
this already-existing record. This was not separately re-verified against
the live dev database in this task (no live webhook or live DB write was
made, per the no-outbound-testing constraint); it follows directly from
`get_phone_number`'s logic and the audit's prior finding.

## Testing

**Backend** — `DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test`:
```
Ran 254 tests in 11.249s
OK
```
(243 pre-existing + 11 new; 0 failures, 0 errors.)

New tests added:
- `apps/webhooks/tests/test_parsing.py` — `PushName` extraction: present,
  absent, non-string, empty-string.
- `apps/webhooks/tests/test_ingestion.py`
  (`PersistMessagePushNameTests`) — inbound `PushName` updates
  `display_name` on the already-resolved `Contact` (and confirms exactly
  one `Contact`/`Chat` row exists afterward); missing `PushName` leaves
  `display_name` untouched; outbound and group messages with a
  `PushName` never create a `Contact` at all.
- `apps/chats/test_views.py` (`ChatListViewTests`) — `phone_number` is
  returned from the linked `Contact`; `null` when the `Contact` has no
  phone number; `null` when no `Contact` is linked.

Also fixed one pre-existing test broken by the new required
`ParsedMessage.push_name` field:
`PersistMessageDuplicateTests.test_duplicate_message_raises_duplicate_message`
now passes `push_name=None` explicitly, matching this dataclass's
existing no-default-value convention (same as `sender_alt`).

**Backend checks:**
```
python manage.py check                          -> System check identified no issues (0 silenced)
python manage.py makemigrations --check --dry-run -> No changes detected
```
No new migration — no model field was added (`display_name` and
`phone_number` on `Contact` already existed).

**Frontend:**
```
npx tsc -b --noEmit  -> 0 errors
npm run lint (oxlint) -> only pre-existing warnings in unrelated files
                          (StatusBadge.tsx, ThemeContext.tsx, AuthContext.tsx);
                          nothing in InboxPage.tsx/.css or djangoApi.ts
npm run build          -> succeeded, 1950 modules transformed
```

## What was NOT done (by design)

- No LID/JID auto-merge, and no change to how `Chat.contact` gets
  assigned.
- No `status@broadcast` filtering work.
- No BFF, Session Management, send-message, or Phase 9 changes.
- No outbound WhatsApp message was sent for testing.
- No live verification against the real dev database (would have
  required either a live webhook delivery or a live DB write, both
  outside this task's read-only-except-the-approved-diff constraint).

## Files changed

```
backend/apps/webhooks/parsing.py
backend/apps/webhooks/services.py
backend/apps/webhooks/tests/test_parsing.py
backend/apps/webhooks/tests/test_ingestion.py
backend/apps/chats/serializers.py
backend/apps/chats/test_views.py
frontend/src/lib/djangoApi.ts
frontend/src/pages/InboxPage.tsx
frontend/src/pages/InboxPage.css
```

---

Per instruction: stopping here. No further phase or task will be started
without being asked.
