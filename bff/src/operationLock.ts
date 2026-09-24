// Session Management Audit (docs/generated/SESSION-MANAGEMENT-AUDIT-REPORT.md
// Section 5) found the session-control mutations (start/stop/restart/
// logout/pairing-code) had no protection at all against a double-click or
// rapid repeat — two near-simultaneous requests both reach WAHA
// independently.
//
// This is deliberately NOT the same mechanism as messages.ts's
// Idempotency-Key / operations.OutboundOperation pattern. That pattern
// solves a different problem: making a message send durably retry-safe
// across page reloads and BFF restarts, keyed by a client-supplied key
// tied to a specific (destination, content) pair. Session lifecycle
// actions have no destination/content to key on, and this project's BFF
// runs as a single process per Tencent VPS (docs/00-MASTER-SPEC.md) — an
// in-process guard is enough to catch the actual failure mode here (a
// user's own double-click hitting this same running process while the
// first request is still in flight), without inventing a second,
// incompatible durable-idempotency architecture or requiring a new
// client-facing header.
//
// Documented limitation: this lock is per-process memory only. It does
// NOT survive a BFF restart and does NOT coordinate across multiple BFF
// instances, if this ever becomes a multi-instance deployment. That is
// an accepted trade-off for the problem being solved, not an oversight.

const inFlight = new Set<string>();

/** Returns true and marks `key` as in-flight if it wasn't already;
 * returns false (does nothing) if `key` is already in-flight. */
export function acquireOperationLock(key: string): boolean {
  if (inFlight.has(key)) return false;
  inFlight.add(key);
  return true;
}

export function releaseOperationLock(key: string): void {
  inFlight.delete(key);
}
