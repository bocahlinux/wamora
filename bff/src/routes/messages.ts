// Send-message route — docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md
// Section 9's exact idempotency state machine.

import { Router } from 'express';

import { logAuditFallback } from '../auditHelper';
import { config } from '../config';
import { registerOutboundOperation, resolveOutboundOperation, triggerReconciliation } from '../djangoClient';
import { sendBadRequest, sendWahaUnavailable } from '../errors';
import { requireAuth, requireScope } from '../middleware/auth';
import { callWaha } from '../wahaClient';
import { validateSession } from './sessionGuard';

const router = Router();

function djangoCallOptions() {
  return {
    baseUrl: config.djangoInternalBaseUrl,
    serviceKey: config.internalServiceKey,
    timeoutMs: config.djangoInternalTimeoutMs,
  };
}

router.post('/sessions/:session/messages', requireAuth, requireScope('sending'), async (req, res) => {
  if (!validateSession(req, res)) return;

  const idempotencyKey = req.header('Idempotency-Key');
  if (!idempotencyKey) {
    sendBadRequest(res, 'Idempotency-Key header is required');
    return;
  }
  const { chatId, text } = req.body ?? {};
  if (typeof chatId !== 'string' || !chatId || typeof text !== 'string' || !text) {
    sendBadRequest(res, 'chatId and text are required');
    return;
  }

  const session = req.params.session;

  // Step 1: register (or find) the OutboundOperation — contract Section 9,
  // "First request" / "Duplicate request" rows. Best-effort: if Django is
  // unreachable, proceed to WAHA anyway (a real, accepted degradation —
  // contract Section 9/14, not an oversight).
  const registration = await registerOutboundOperation(
    { session, idempotencyKey, destination: chatId, operationType: 'sendText' },
    djangoCallOptions(),
  );

  if (registration.ok && !registration.data.created) {
    const existing = registration.data;
    if (existing.status === 'pending' || existing.status === 'sent') {
      // Never call WAHA again for an in-flight or already-resolved send.
      res.status(200).json({ status: existing.status, providerMessageId: existing.provider_message_id || undefined });
      return;
    }
    if (existing.status === 'failed' || (existing.status === 'unknown' && !existing.retryable)) {
      res.status(409).json({
        error: { code: 'requires_new_idempotency_key', message: 'This idempotency key already resolved to a terminal, non-retryable state' },
      });
      return;
    }
    // existing.status is 'pending' or 'unknown' and retryable (stale) —
    // fall through and retry using the SAME row's id, not a new one.
  }

  const operationId = registration.ok ? registration.data.id : undefined;

  // Step 2: call WAHA.
  const result = await callWaha('sendText', session, {
    baseUrl: config.wahaBaseUrl,
    apiKey: config.wahaApiKey,
    timeoutMs: config.wahaTimeoutMs,
    body: { session, chatId, text },
  });

  // Step 3: resolve — contract Section 9's success/failure/unknown rows.
  let finalStatus: 'sent' | 'failed' | 'unknown';
  let providerMessageId: string | undefined;
  if (result.outcome === 'success') {
    finalStatus = 'sent';
    const body = (result.json ?? {}) as Record<string, unknown>;
    // WAHA's real sendText success response has not been live-verified
    // (contract Section 9) — `id` is a best-effort, unconfirmed guess at
    // the field name, not a documented fact. If it's absent or not a
    // string, the send still resolves successfully as `sent`; it simply
    // carries no providerMessageId, rather than throwing or guessing at
    // an alternative field name.
    providerMessageId = typeof body.id === 'string' ? body.id : undefined;
  } else if (result.outcome === 'http_error') {
    finalStatus = 'failed';
  } else {
    // timeout or network_error — genuinely ambiguous, never assume success
    // or failure (docs/09-TEST-PLAN.md Failure test #8).
    finalStatus = 'unknown';
  }

  // Audit-after-resolution (contract Section 10) — WAHA's outcome is
  // already known at this point, never before. The local fallback line is
  // emitted unconditionally, exactly like every other sensitive action
  // (auditHelper.recordAudit), including when registration itself failed
  // (operationId undefined, e.g. Django was unreachable from the start) —
  // that is, if anything, the clearest case where the fallback matters.
  logAuditFallback({
    actorId: req.auth?.sub,
    action: 'message.send',
    target: session,
    result: finalStatus === 'sent' ? 'success' : 'failure',
  });

  if (operationId !== undefined) {
    await resolveOutboundOperation(
      operationId,
      {
        status: finalStatus,
        providerMessageId,
        actorId: req.auth?.sub,
        action: 'message.send',
        target: session,
        result: finalStatus === 'sent' ? 'success' : 'failure',
      },
      djangoCallOptions(),
    );
  }

  if (finalStatus === 'sent') {
    // This WAHA deployment sends no webhook for self-sent messages
    // (docs/generated/INBOX-OUTBOUND-MESSAGE-MISSING-AUDIT-REPORT.md), so
    // without this the just-sent message would sit unseen in the Inbox
    // until the next periodic reconciliation. Deliberately NOT awaited —
    // the send response must never wait on this
    // (docs/generated/INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md).
    // postJson() (djangoClient.ts) never throws, so this .then() is only
    // for observability (docs/generated/INBOX-RECONCILIATION-TRIGGER-OBSERVABILITY-AUDIT-REPORT.md)
    // — it still never blocks this response.
    void triggerReconciliation({ session, chatId }, djangoCallOptions()).then((result) => {
      if (!result.ok) {
        console.warn(`[messages] reconciliation trigger did not complete for session=${session} chatId=${chatId}`);
      }
    });
    res.status(200).json({ status: 'sent', providerMessageId });
    return;
  }
  if (finalStatus === 'unknown') {
    res.status(200).json({ status: 'unknown' });
    return;
  }
  sendWahaUnavailable(res);
});

export default router;
