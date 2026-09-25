# Phase 9.0 — Ambiguous Send Outcome UX — Implementation Report

**Scope of this task.** Implementation, frontend-only. Per the task's hard
rules: no backend/database/migration change, no WAHA change, no Session
Management change, no reconciliation change, no identity/`@lid`/JID change,
no `status@broadcast` change, no API/BFF/Django contract change, no live
WhatsApp send, no Phase 9 work beyond this one item (9.0), and no
continuation into Phase 11/13/14. All of that is confirmed true of the
actual change made — see Section 7.

---

## 1. Problem (as given)

When `POST /api/sessions/:session/messages` (via the BFF) resolves to the
ambiguous `'unknown'` outcome — a WAHA/BFF timeout where it is genuinely
unconfirmed whether WhatsApp received the message — `InboxPage.tsx`
previously cleared the compose box and showed **nothing**: no banner, no
warning, no text of any kind. This was visually indistinguishable from
"nothing happened yet," and an operator who didn't notice the *absence* of
the normal "Message sent" confirmation line could easily assume the send
succeeded when its actual status was unknown — exactly the risk named in
the task brief and previously identified as a concrete finding in
`docs/generated/PHASE9-DESIGN-AUDIT-REPORT.md` (Section 1, Section 6, Section
10, Section 12).

## 2. Root cause (UI-level, traced before coding)

Traced the full path: `InboxPage.tsx`'s `handleSend()` →
`frontend/src/lib/bffApi.ts::sendMessage()` →
`POST {bffBaseUrl}/api/sessions/:session/messages` →
`bff/src/routes/messages.ts` (unchanged, not touched by this task) → WAHA.
The BFF already correctly returns one of three distinguishable outcomes to
the frontend: `{status: 'sent', providerMessageId?}`, a non-2xx/error
response (mapped to the frontend's `ApiError` taxonomy), or
`{status: 'unknown'}` (`messages.ts:143-146`, confirmed unchanged, not
edited by this task). `frontend/src/lib/bffApi.ts`'s `SendMessageResult`
type already declared `status: 'sent' | 'pending' | 'unknown'`
(`bffApi.ts:105`, confirmed unchanged) — the ambiguity was never in the
network/type layer, which already carried the right information end to end.

The actual gap was purely in `InboxPage.tsx`'s own state and render logic:
it tracked send feedback as **two independent booleans**
(`sendError: ApiError | null`, `sendConfirmed: boolean`), and
`sendConfirmed` was set via `result.data.status !== 'unknown'` — meaning the
`'unknown'` case left `sendConfirmed = false`, the exact same value as
"nothing has been sent yet." **Two structurally different situations
("no send attempted" and "sent, but ambiguous") collapsed into the same
falsy state**, so there was no `if` branch left to render anything for the
ambiguous case — not a missing feature so much as a missing *third state*
that the existing two-boolean shape couldn't represent at all. This is
exactly the class of gap `SessionsPage.tsx` had already solved once, for
the identical ambiguity, with a three-way discriminated union
(`ActionFeedback: {kind:'success'} | {kind:'unknown'} | {kind:'error', error}`).

## 3. Change made

`InboxPage.tsx`'s two booleans were replaced with one discriminated union,
`SendFeedback = {kind:'success'} | {kind:'unknown'} | {kind:'error', error: ApiError}`
— structurally the same shape as `SessionsPage.tsx`'s `ActionFeedback`, but
**not a copy-paste**: `SessionsPage.tsx`'s type is keyed per-*action*
(`{action, kind}`, since one page can trigger five different named
actions); `InboxPage.tsx` has exactly one send target (the open
conversation), so no `action` discriminant was needed — the type was
adapted to the composer's actual, simpler state shape rather than
mechanically copied.

`handleSend()` now sets exactly one of the three variants on every send
attempt, and the render block gained one new branch
(`sendFeedback?.kind === 'unknown'`) showing:

> "The message status could not be confirmed — it may or may not have gone
> through. Wait a moment and check the conversation before sending it
> again, to avoid sending it twice."

— directly stating the message may already have gone through, telling the
operator what to do (wait, check, don't blindly resend), and explicitly
naming the duplicate-send risk, per the task's exact wording. Styled with a
new CSS rule, `.wa-inbox__send-unknown`, matching
`SessionsPage.css`'s `.wa-session-feedback--unknown` visual treatment (a
warning-tinted background chip) for consistency with the one existing
precedent for this exact kind of message — deliberately more visually
prominent than the plain-text success line, since this state needs the
operator's attention.

## 4. Files changed

| File | Nature of change |
|---|---|
| `frontend/src/pages/InboxPage.tsx` | Replaced `sendError`/`sendConfirmed` booleans with one `SendFeedback` union; `handleSend()` now sets `{kind:'unknown'}` explicitly instead of collapsing it into the same falsy state as "no send attempted"; render block gained one new conditional branch. |
| `frontend/src/pages/InboxPage.css` | Added one new rule, `.wa-inbox__send-unknown` (14 lines). The pre-existing `.wa-inbox__send-confirmed` rule was **not modified**. |

No other file was touched. Two unrelated `package-lock.json` diffs
(`bff/`, `frontend/`) were found in the working tree at the start of this
task — pre-existing npm-lockfile normalization artifacts from earlier in
this session (npm-version metadata differences, `libc` field removal),
unrelated to this change and predating it (confirmed by file mtime, and by
the fact this task never ran `npm install` anywhere, including never
touching `bff/` at all). These were reverted via
`git checkout -- frontend/package-lock.json bff/package-lock.json` before
finishing, so the final diff is scoped to exactly the two files above.

## 5. Behavior before / after

| Outcome | Before | After |
|---|---|---|
| `success` (`status: 'sent'`) | Compose box clears; `.wa-inbox__send-confirmed` text shown: "Message sent — it will appear in the history once it's confirmed by the server." | **Identical** — same class, same text, same trigger condition (`status !== 'unknown'` → now `status !== 'unknown'` via the `: {kind:'success'}` fallback branch of the same ternary). No visual or behavioral change. |
| `failure` (network/HTTP error) | Compose box **not** cleared (early `return` before `setDraftText('')`); `<ErrorState error={...}/>` shown. | **Identical** — same early return, same component, same error value passed through (now via `sendFeedback.error` instead of the old `sendError` variable, same underlying `ApiError` object). |
| `unknown` (`status: 'unknown'`) | Compose box **cleared**; **nothing shown**. | Compose box cleared (unchanged); **new warning banner shown**, explicitly stating the outcome is unconfirmed and cautioning against blind resend. |

## 6. Tests run and results

- **Frontend automated tests**: none exist in this project — confirmed
  again this task (`frontend/package.json` has no `test` script; no
  `vitest`/`jest`/`@testing-library` dependency; zero `*.test.tsx`/`*.test.ts`
  files anywhere under `frontend/src`, matching every prior audit this
  session). Per the task's own conditional instruction ("jika test
  infrastructure frontend sudah tersedia"), **no test was added**, since
  adding a test runner from scratch is a separate, much larger decision
  this task's scope does not include and was not asked to make.
- **Typecheck**: `npm run build` (which runs `tsc -b && vite build`, this
  project's only typecheck mechanism — there is no separate `typecheck`
  script) — **passed**, zero TypeScript errors.
- **Build**: same command, `vite build` — **passed**:
  `✓ 1950 modules transformed`, `✓ built in 2.81s`, output emitted to
  `frontend/dist/` (same bundle count/shape as a normal build, no new
  errors or warnings from this change).
- **Lint**: `npm run lint` (`oxlint`) — **passed**. Output showed exactly 5
  pre-existing warnings, all in files this task never touched
  (`StatusBadge.tsx`, `AuthContext.tsx`, `ThemeContext.tsx`) — zero new
  warnings from `InboxPage.tsx`/`InboxPage.css`.
- **Live WhatsApp send**: not performed, per the explicit hard rule — this
  task's verification is code-level (typecheck/build/lint passing, and the
  diff-level behavior-equivalence argument in Section 5) plus manual
  reasoning through the three code paths, not a live send.

## 7. Evidence that success/failure behavior is unchanged, and that nothing
outside scope was touched

- **Success/failure equivalence**: demonstrated structurally in Section 5 —
  every condition, class name, component, and string used for the success
  and error cases is byte-for-byte the same as before; only the data
  container changed shape (two booleans → one union), and the union's
  `'success'`/`'error'` variants are populated at the exact same call sites,
  with the exact same trigger conditions, as the old
  `sendConfirmed`/`sendError` booleans were.
- **No backend/BFF/database/reconciliation/session-management/identity
  change**: confirmed by `git diff --stat` showing exactly two files
  changed, both under `frontend/src/pages/`
  (`InboxPage.tsx`, `InboxPage.css`) — no file under `backend/`, `bff/`,
  `infrastructure/`, or any migration file appears in the diff.
  `bff/src/routes/messages.ts` (the send/idempotency/reconciliation-trigger
  logic) was read this task to trace the outcome shape (Section 2) but was
  never opened with a write tool and is unmodified.
- **No LID/JID/identity change, no auto-merge, no `status@broadcast`
  filter**: none of this task's edits touch any identity-resolution code
  (`chatDisplay()`, `apps/webhooks/parsing.py`, `apps/chats/*`) — confirmed
  by the diff itself containing no reference to any of those symbols or
  files.
- **No Session Management change**: `SessionsPage.tsx`/`SessionsPage.css`
  were read (to study the existing `ActionFeedback` pattern, Section 2/3)
  but not edited — confirmed absent from `git diff --stat`.

## 8. What was not done (explicitly, per the task's stop conditions)

- No health endpoint, `SyncCheckpoint` endpoint, Redis health check, or
  webhook heartbeat — out of scope for 9.0, reserved for later Phase 9
  items per `docs/generated/PHASE9-DESIGN-AUDIT-REPORT.md`.
- No broader Inbox stale-state/connectivity indicator (Section 7/8 of the
  design audit) — this task addressed only the send-outcome gap (Section
  10/12 of that report), not the read-polling staleness model.
- No frontend test added (Section 6 — conditional on test infrastructure
  existing, which it does not).
- No live/manual browser verification was performed as part of this task —
  the change was verified by typecheck/build/lint and by structural
  code-reading (Section 5/7), not by opening a browser or sending a real
  WhatsApp message. If you want this manually verified in a running
  browser against the real dev WAHA session, that remains an open item, the
  same way every other UI change in this project's history has explicitly
  labeled unverified browser behavior rather than claiming it.
- No further Phase 9 work was started, per the task's explicit instruction
  to stop after 9.0.

---

This implementation is complete and scoped to exactly the ambiguous-send-
outcome UX described in the task. Stopping here, per instruction — not
continuing to any further Phase 9 item.
