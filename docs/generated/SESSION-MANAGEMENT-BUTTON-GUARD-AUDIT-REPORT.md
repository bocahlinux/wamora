# Session Management — Action Button Re-Enable Audit

Read-only. No source, config, `.env`, dependency, or infrastructure file
was modified. No action was taken against the live `no_epahari` session.

## 1. Root cause

`frontend/src/pages/SessionsPage.tsx`'s `runAction()`:

```ts
async function runAction(action, fn) {
  if (!sessionName || busyAction) return;
  setBusyAction(action);
  ...
  const result = await fn(sessionName);   // the mutation HTTP round-trip
  setBusyAction(null);                    // ← re-enables every button HERE
  ...
  startStatusSync();                      // ← polling starts AFTER that
}
```

Every action button's `disabled` prop is `busyAction !== null` — it
tracks **only** whether the mutation's own HTTP request is in flight.
`setBusyAction(null)` runs the instant that request resolves, which is
*before* `startStatusSync()` (the settlement-polling loop from the
previous fix) even starts. `isSyncing` — the state that's actually true
for the whole `STARTING`-to-settled window — is never read by any
button's `disabled` condition at all.

So the button re-enables exactly when the BFF's HTTP response comes
back, not when the session has actually finished changing state. That
gap (BFF response ↔ WAHA reaching a settled status) is precisely the
window your test clicked into.

## 2. Current behavior

1. Click Restart → `busyAction = 'restart'` → button disabled.
2. BFF responds `200` (WAHA acknowledged the restart request, nothing
   more) → `busyAction = null` → **button re-enabled**, while the real
   session is still `STARTING`.
3. `startStatusSync()` begins polling in the background (`isSyncing =
   true`), but no button reads `isSyncing`.
4. A second click during this window passes the guard
   (`if (!sessionName || busyAction) return;` — `busyAction` is `null`
   again) and fires a **second, real** `POST /sessions/:session/restart`.

## 3. Does the BFF operation lock prevent this?

**No — confirmed by re-reading `bff/src/routes/session.ts` and
`bff/src/operationLock.ts` directly, not assumed.**

```ts
if (!acquireOperationLock(lockKey)) { sendConflict(res, ...); return; }
try {
  const result = await callWaha(endpointName, ...);   // one round-trip to WAHA
  ...
} finally {
  releaseOperationLock(lockKey);                       // released right here
}
```

The lock is held for exactly the duration of the BFF's own call to WAHA
— i.e., however long WAHA takes to *acknowledge* the restart request
(fast: WAHA doesn't block that response on the session finishing its
transition). It is released as soon as that one HTTP exchange completes,
**long before** the session reaches a settled status. By the time your
second click's request reaches the BFF, the first operation's lock has
already been released — the lock was never designed to, and does not,
cover the settlement window. It correctly does exactly one thing:
prevents two requests from overlapping *the same in-flight WAHA call*.
It was never meant to (and structurally cannot, without a larger design
change — see Section 5) know whether the session has finished settling.

This matches the two earlier reports' own stated scope for the lock
(`SESSION-MANAGEMENT-IMPLEMENTATION-REPORT.md` Section 3: an in-process
guard against a *double-click reaching the BFF*, not a durable
"operation in progress" tracker) — the audit isn't finding a bug in the
lock, it's finding a UX gap in a layer above it that the lock was never
responsible for.

## 4. Expected behavior

Start/Stop/Restart/Logout buttons should stay disabled for the **entire**
window from click to settled status — i.e. `disabled` should depend on
`busyAction !== null || isSyncing`, not `busyAction !== null` alone. This
is a strictly frontend concern: only the frontend has (or should have) a
concept of "settlement polling" at all; the BFF is intentionally
stateless per-request.

## 5. Frontend-only, or does the BFF need to change?

**Frontend-only fix is sufficient and recommended.** Making the BFF lock
span the settlement window would mean the BFF itself polling WAHA status
before releasing the lock and responding — a materially larger, riskier
change:
- It would make every mutation response slow (blocking on however long
  settlement takes, up to the ~30s window already established), directly
  contradicting the existing, deliberate design
  (`docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md` Section 7:
  the response shape "does not claim an unconfirmed WAHA state
  transition" — the whole point was a fast acknowledge, not a
  wait-for-settled response).
- It would duplicate settlement-detection logic in two places (BFF and
  frontend) instead of one.
- It's unnecessary: the frontend already has full, working
  settlement-detection (`runTick`/`isSyncing`) from the prior fix — it
  just isn't wired to the buttons yet.

Not recommended, but noted for completeness: the BFF lock *could*
additionally be used as defense-in-depth even after this frontend fix,
but there is no concrete gap left to defend against once the frontend
guard is correct (a disabled button can't be clicked; the lock's
existing double-click protection remains exactly as useful as before for
the narrower race it already covers). Not proposing this — adding it
without a demonstrated remaining gap would be exactly the kind of
unnecessary change the audit is asked to avoid.

## 6. Files that would need to change (if approved — not done)

- `frontend/src/pages/SessionsPage.tsx` only:
  - The `runAction()` guard: `if (!sessionName || busyAction) return;` →
    add `|| isSyncing`, so the action is blocked even if a disabled
    button is somehow still activated (keyboard, a stray event) —
    defense-in-depth alongside the visual `disabled` state, not a
    replacement for it.
  - The four mutation buttons' `disabled` props (Start, Restart, Stop,
    Logout): `disabled={busyAction !== null}` → `disabled={busyAction
    !== null || isSyncing}`.
  - "Pair device" button: **no dependency found, left unchanged**, per
    the task's own constraint. Opening the QR/pairing modal doesn't call
    WAHA by itself; the QR/pairing-code requests inside it are already
    independently guarded (QR has no lock by design — deliberate, per
    the earlier report; pairing-code has its own BFF lock). No
    interaction was found between a pending lifecycle-settlement sync
    and the pairing modal that would require disabling this button too.
  - `ConfirmDialog`'s `busy` prop: **no change needed** — the dialog
    already closes (`setConfirmAction(null)`) right after `runAction`
    resolves, before the settlement-polling phase begins, so it's never
    open during the window this audit is about.

No BFF, backend, `.env`, or API contract file needs to change.

## 7. Risk of the proposed change

**Low.** It only tightens an existing `disabled` condition (strictly
more conservative — buttons become disabled in strictly more situations,
never fewer) and adds one clause to an existing early-return guard. It
does not touch: the polling/settlement algorithm itself, the BFF, any
network call, the confirm dialog, or the QR/pairing flow. The only
user-visible behavior change is buttons staying disabled for up to
~30s longer in the worst case (the existing `POLL_MAX_TICKS` ceiling)
while a session settles — which is the explicitly requested fix, not a
side effect.

## 8. Safe manual tests (won't disturb `no_epahari` further)

Since a Restart-during-STARTING double-click was already reproduced
once, avoid repeating that specifically. Safer options, in order of
preference:

1. **No-click confirmation of the current bug** (already effectively
   done by your test, but repeatable without side effects): open
   DevTools → Elements, click Restart once, and watch the Restart
   button's `disabled` attribute in the DOM inspector — it should show
   `disabled` briefly (during the HTTP round-trip) then disappear well
   before the badge reaches `WORKING`, without clicking it again. This
   confirms the gap visually with zero additional requests sent.
2. **Post-fix verification without a second mutation**: after the fix is
   applied, click Restart once and watch the button's `disabled`
   attribute the same way — it should now stay `disabled` for the entire
   `STARTING` → settled window, disappearing only once the badge shows
   the settled value. No second click needed to confirm the fix.
3. **If you do want to confirm the guard actively blocks a second click**
   post-fix, prefer testing it on **Start** rather than **Restart/Stop**
   if the session is ever in a stopped state during other testing (less
   disruptive to an actively-connected session than repeated restarts),
   or defer that specific click-through test until a non-production/
   test session is available.
4. Avoid additional Stop/Logout testing on `no_epahari` until you're
   ready to accept that disruption — Section 6's fix doesn't require it
   to be verified; the `disabled`-attribute inspection in #1/#2 is
   sufficient to confirm correctness without touching WAHA at all.

---

No change was made. Not proceeding to Inbox/Chat or canonical Phase 9.
Waiting for approval before implementing Section 6.
