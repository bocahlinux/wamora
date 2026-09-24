// docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 10: audit
// is written *after* the WAHA call resolves (never before — AuditLog.result
// has no "pending" choice). Best-effort: a failed write never blocks the
// response already owed to the frontend. A structured local log line is
// always emitted too, as the documented fallback trail for when Django is
// unreachable at write time.

import { config } from './config';
import { writeAuditEvent } from './djangoClient';

export interface AuditParams {
  actorId?: string;
  action: string;
  target: string;
  result: 'success' | 'failure';
}

/** The fallback trail itself — independent of Django's reachability, per
 * contract Section 10's mitigation for the "audit write fails" gap. Never
 * includes a credential value. Exported separately (not only as part of
 * recordAudit) so callers whose Django write goes through a *different*
 * endpoint than writeAuditEvent — e.g. the send-message flow, whose audit
 * write rides along with apps.operations' resolve endpoint — can still
 * emit the same fallback line without duplicating this logic. */
export function logAuditFallback(params: AuditParams): void {
  // eslint-disable-next-line no-console
  console.log(
    JSON.stringify({
      type: 'audit',
      actor_id: params.actorId ?? null,
      action: params.action,
      target: params.target,
      result: params.result,
      timestamp: new Date().toISOString(),
    }),
  );
}

/** Used by routes whose Django audit write is a dedicated call to
 * writeAuditEvent (lifecycle/QR/pairing-code — contract Section 10's
 * "dedicated, narrow endpoint" case). The send-message flow does not use
 * this function directly, since its Django write is combined with the
 * OutboundOperation resolve call instead (contract Section 9/10) — it
 * calls logAuditFallback directly alongside that call. */
export async function recordAudit(params: AuditParams): Promise<void> {
  logAuditFallback(params);

  await writeAuditEvent(params, {
    baseUrl: config.djangoInternalBaseUrl,
    serviceKey: config.internalServiceKey,
    timeoutMs: config.djangoInternalTimeoutMs,
  });
  // Deliberately ignores the result — a missing durable AuditLog row is an
  // accepted, documented degradation (contract Section 10), not something
  // that should surface as an error to the frontend for an action that
  // already happened against WAHA.
}
