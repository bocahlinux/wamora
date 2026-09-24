// Session status/lifecycle/QR/pairing routes —
// docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Sections 2, 11, 12.

import { Router, type Request, type Response } from 'express';

import { recordAudit } from '../auditHelper';
import { config } from '../config';
import { sendBadRequest, sendConflict, sendWahaUnavailable } from '../errors';
import { requireAuth, requireScope } from '../middleware/auth';
import { acquireOperationLock, releaseOperationLock } from '../operationLock';
import { callWaha, type WahaCallResult } from '../wahaClient';
import { validateSession } from './sessionGuard';

const router = Router();

function wahaCallOptions() {
  return { baseUrl: config.wahaBaseUrl, apiKey: config.wahaApiKey, timeoutMs: config.wahaTimeoutMs };
}

router.get('/sessions/:session/status', requireAuth, requireScope('reading'), async (req, res) => {
  if (!validateSession(req, res)) return;

  const result = await callWaha('getSessionStatus', req.params.session, wahaCallOptions());
  if (result.outcome !== 'success') {
    sendWahaUnavailable(res);
    return;
  }
  const body = (result.json ?? {}) as Record<string, unknown>;
  res.status(200).json({
    session: req.params.session,
    status: body.status,
    engine: body.engine,
    me: body.me,
  });
});

// docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 7:
// project-owned response shape that does not claim an unconfirmed WAHA
// state transition — {success, session, requestedAction} only, never a
// guessed `status`.
//
// Session Management Audit Section 5 hardening (this phase — see
// docs/generated/SESSION-MANAGEMENT-IMPLEMENTATION-REPORT.md):
// 1. An in-process lock (operationLock.ts) rejects a second request for
//    the same (session, action) while the first is still in flight —
//    409, not a second WAHA call — guarding against a double-click.
// 2. `callWaha`'s outcome is now mapped three ways, not two, mirroring
//    messages.ts's existing success/failed/unknown distinction: a
//    confirmed WAHA error (`http_error`) is `failure`; a `timeout` or
//    `network_error` is genuinely ambiguous — WAHA may have applied the
//    action even though no response arrived — and is reported as
//    `unknown`, never silently collapsed into `failure` for the CLIENT
//    response. The durable AuditLog is still binary (success/failure
//    only — `apps.audit.models.AuditLog.RESULT_CHOICES` has no third
//    state, the same accepted limitation messages.ts already has), so
//    `unknown` is recorded there as `failure` — but the HTTP response the
//    frontend actually sees preserves the distinction.
async function handleLifecycleAction(
  req: Request,
  res: Response,
  endpointName: 'startSession' | 'stopSession' | 'restartSession' | 'logoutSession',
  requestedAction: 'start' | 'stop' | 'restart' | 'logout',
): Promise<void> {
  if (!validateSession(req, res)) return;

  const lockKey = `${req.params.session}:${requestedAction}`;
  if (!acquireOperationLock(lockKey)) {
    sendConflict(res, `A ${requestedAction} request for this session is already in progress`);
    return;
  }

  try {
    const result: WahaCallResult = await callWaha(endpointName, req.params.session, wahaCallOptions());

    if (result.outcome === 'success') {
      await recordAudit({
        actorId: req.auth?.sub,
        action: `session.${requestedAction}`,
        target: req.params.session,
        result: 'success',
      });
      res.status(200).json({ success: true, session: req.params.session, requestedAction });
      return;
    }

    // Both branches below record 'failure' for the durable audit trail
    // (AuditLog has no third state) but respond to the client differently.
    await recordAudit({
      actorId: req.auth?.sub,
      action: `session.${requestedAction}`,
      target: req.params.session,
      result: 'failure',
    });

    if (result.outcome === 'http_error') {
      sendWahaUnavailable(res);
      return;
    }
    // timeout or network_error — genuinely ambiguous, never assume failure
    // (docs/09-TEST-PLAN.md Failure test #8, same reasoning messages.ts
    // already applies to sendText).
    res.status(200).json({ success: false, session: req.params.session, requestedAction, outcome: 'unknown' });
  } finally {
    releaseOperationLock(lockKey);
  }
}

router.post('/sessions/:session/start', requireAuth, requireScope('session control'), (req, res) =>
  handleLifecycleAction(req, res, 'startSession', 'start'),
);
router.post('/sessions/:session/stop', requireAuth, requireScope('session control'), (req, res) =>
  handleLifecycleAction(req, res, 'stopSession', 'stop'),
);
router.post('/sessions/:session/restart', requireAuth, requireScope('session control'), (req, res) =>
  handleLifecycleAction(req, res, 'restartSession', 'restart'),
);
router.post('/sessions/:session/logout', requireAuth, requireScope('session control'), (req, res) =>
  handleLifecycleAction(req, res, 'logoutSession', 'logout'),
);

// docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 12: the
// payload is forwarded essentially as-is; the envelope is BFF-owned and
// minimized. WAHA's exact QR response shape is undocumented at the field
// level, so the mapping below is a generic, content-type-driven adapter —
// isolated here, in one place, as the contract requires — not a guess at
// specific WAHA field names.
// No operation lock here, deliberately: unlike the lifecycle actions,
// re-requesting a QR is expected, normal UX (a QR expires and the caller
// is meant to refresh it — task instruction "allow the user to
// retry/refresh"), so a duplicate-request guard would fight the intended
// behavior rather than protect against an accidental double-click.
router.get('/sessions/:session/qr', requireAuth, requireScope('session control'), async (req, res) => {
  if (!validateSession(req, res)) return;

  const result = await callWaha('getQr', req.params.session, wahaCallOptions());

  await recordAudit({
    actorId: req.auth?.sub,
    action: 'session.qr_request',
    target: req.params.session,
    // AuditLog has no third state (see handleLifecycleAction's comment
    // above) — 'unknown' is recorded as 'failure' here too.
    result: result.outcome === 'success' ? 'success' : 'failure',
  });

  if (result.outcome === 'http_error' && result.status === 404) {
    sendConflict(res, 'Session is not awaiting pairing');
    return;
  }
  if (result.outcome === 'timeout' || result.outcome === 'network_error') {
    // Ambiguous — WAHA may have processed the request even though no
    // response arrived. Never report this as a confirmed failure.
    res.status(200).json({ session: req.params.session, outcome: 'unknown' });
    return;
  }
  if (result.outcome !== 'success') {
    sendWahaUnavailable(res);
    return;
  }

  const isJson = result.contentType?.includes('application/json');
  const isImage = result.contentType?.includes('image/');
  res.status(200).json({
    session: req.params.session,
    format: isJson ? 'json' : isImage ? 'image' : 'raw',
    data: isJson ? result.json : result.bodyBase64,
  });
});

router.post('/sessions/:session/pairing-code', requireAuth, requireScope('session control'), async (req, res) => {
  if (!validateSession(req, res)) return;

  const phoneNumber = req.body?.phoneNumber;
  if (typeof phoneNumber !== 'string' || phoneNumber.trim() === '') {
    sendBadRequest(res, 'phoneNumber is required');
    return;
  }

  const lockKey = `${req.params.session}:pairing-code`;
  if (!acquireOperationLock(lockKey)) {
    sendConflict(res, 'A pairing-code request for this session is already in progress');
    return;
  }

  try {
    const result = await callWaha('requestPairingCode', req.params.session, {
      ...wahaCallOptions(),
      body: { phoneNumber },
    });

    await recordAudit({
      actorId: req.auth?.sub,
      action: 'session.pairing_code_request',
      target: req.params.session,
      // AuditLog has no third state — 'unknown' is recorded as 'failure'.
      result: result.outcome === 'success' ? 'success' : 'failure',
    });

    if (result.outcome === 'timeout' || result.outcome === 'network_error') {
      res.status(200).json({ session: req.params.session, outcome: 'unknown' });
      return;
    }
    if (result.outcome !== 'success') {
      sendWahaUnavailable(res);
      return;
    }

    const body = (result.json ?? {}) as Record<string, unknown>;
    res.status(200).json({ session: req.params.session, code: body.code ?? result.bodyText });
  } finally {
    releaseOperationLock(lockKey);
  }
});

export default router;
