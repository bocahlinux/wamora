# Session Management — Action Button Guard Fix (Implementation)

Implements exactly Section 6 of
`docs/generated/SESSION-MANAGEMENT-BUTTON-GUARD-AUDIT-REPORT.md`, as
approved. **Inbox/Chat was NOT started. Canonical Phase 9 was NOT
started.**

## Scope adherence

Only `frontend/src/pages/SessionsPage.tsx` was changed — three edits,
all additive (`|| isSyncing`), nothing removed or restructured:

1. `runAction()`'s early-return guard:
   ```diff
   - if (!sessionName || busyAction) return;
   + if (!sessionName || busyAction || isSyncing) return;
   ```
2. The Start button's `disabled` prop:
   ```diff
   - disabled={busyAction !== null}
   + disabled={busyAction !== null || isSyncing}
   ```
3. The Restart button — same change.
4. The Stop button — same change.
5. The Logout button — same change.

**Left unchanged, exactly as scoped:**
- The "Pair device" button — still `disabled={busyAction !== null}`.
- `ConfirmDialog` and its `busy` prop.
- The polling/settlement algorithm (`runTick`, `startStatusSync`,
  `stopStatusSync`, `pollGenerationRef`, `POLL_INTERVAL_MS`,
  `POLL_MAX_TICKS`) — not touched at all.
- Every other file: no BFF, backend, `.env`, API contract, dependency,
  or infrastructure file was modified.

## Verification

```
npx tsc -b --noEmit
→ clean, 0 errors

npm run lint (oxlint)
→ 5 warnings, 0 errors — identical to the pre-existing set from every
  prior report this session (StatusBadge.tsx ×2, ThemeContext.tsx,
  AuthContext.tsx ×2). No new warning from this change.

npm run build (tsc -b && vite build)
→ built in 160ms, 0 errors, 0 warnings
```

**No regression found**: the diff is three additive `|| isSyncing`
clauses and one additive guard clause — no existing condition, prop, or
code path was removed or restructured, so no existing behavior for the
success/error/loading/empty states, the confirm dialog, or the QR/
pairing modal could have changed. Confirmed directly by re-reading the
full file after editing (not merely inferred from the diff being small).

## What is NOT claimed

**No browser verification was performed and none is claimed.** Per your
own instruction, you'll do the manual browser pass yourself — the audit
report's Section 8 already lists safe verification steps that avoid
further disrupting the live `no_epahari` session.

---

Stopping here, as requested. Not proceeding to Inbox/Chat or canonical
Phase 9. Waiting for your manual browser testing.
