// Office/Celery -> BFF internal blast-dispatch endpoint — Phase 11
// (Blast), finalized decision 1. Single-purpose: sends ONE message for
// ONE already-approved blast recipient via the existing allowlisted
// `callWaha('sendText', ...)` path (CLAUDE.md rule 5 — never a generic
// proxy; this route accepts no arbitrary WAHA path/method, only
// session/chatId/text for the one fixed operation). Authenticated by
// `requireOfficeDispatchKey` ONLY — no `requireAuth`/session-JWT
// acceptance of any kind, so a browser/frontend can never reach it even
// if it somehow learned the URL (CLAUDE.md rule 3/4 spirit: this is
// server-to-server only).
//
// Mounted at `/internal/blast/send` (see app.ts) — deliberately NOT
// under `/api`, the prefix every frontend-reachable route uses, as an
// additional structural signal (the actual security boundary is still
// the shared-secret check above, not the path).
//
// Deliberately does NOT call registerOutboundOperation/
// resolveOutboundOperation (djangoClient.ts): those exist because for
// the 1:1 human-send flow (routes/messages.ts), the BFF is the FIRST
// party to learn about the send and must tell Django. Here, Django's own
// Celery task is the caller — it already owns and updates its
// OutboundOperation row directly via the ORM (apps/blast/tasks.py),
// since it runs in the same process/database. Adding a second HTTP hop
// back to Django from here would duplicate state Django already holds
// and introduce a redundant idempotency surface (this project's own
// "reuse, don't duplicate" discipline — see apps/blast/models.py).

import { Router } from 'express';

import { config } from '../config';
import { logAuditFallback } from '../auditHelper';
import { sendBadRequest, sendNotFound } from '../errors';
import { requireOfficeDispatchKey } from '../middleware/officeAuth';
import { callWaha } from '../wahaClient';

const router = Router();

router.post('/blast/send', requireOfficeDispatchKey, async (req, res) => {
  const { session, chatId, text } = req.body ?? {};

  if (typeof session !== 'string' || !session) {
    sendBadRequest(res, 'session is required');
    return;
  }
  // Same "exactly one provisioned session" boundary validateSession()
  // (routes/sessionGuard.ts) enforces for the frontend-facing route —
  // reimplemented inline here rather than imported, since that helper
  // reads req.params.session (a path parameter) and this internal route
  // deliberately takes session in the body instead (there is no human
  // user session to route by path for).
  if (!config.wahaSessionName || session !== config.wahaSessionName) {
    sendNotFound(res, 'Unknown session');
    return;
  }
  if (typeof chatId !== 'string' || !chatId || typeof text !== 'string' || !text) {
    sendBadRequest(res, 'chatId and text are required');
    return;
  }

  // Logged for observability/correlation only — Django's own
  // OutboundOperation row (keyed on this exact value) is the actual
  // idempotency boundary; this route does not deduplicate on it.
  const idempotencyKey = req.header('Idempotency-Key') ?? '';

  const result = await callWaha('sendText', session, {
    baseUrl: config.wahaBaseUrl,
    apiKey: config.wahaApiKey,
    timeoutMs: config.wahaTimeoutMs,
    body: { session, chatId, text },
  });

  let responseStatus: 'sent' | 'failed' | 'unknown';
  let providerMessageId: string | undefined;
  if (result.outcome === 'success') {
    responseStatus = 'sent';
    const body = (result.json ?? {}) as Record<string, unknown>;
    providerMessageId = typeof body.id === 'string' ? body.id : undefined;
  } else if (result.outcome === 'http_error') {
    responseStatus = 'failed';
  } else {
    // timeout or network_error — genuinely ambiguous, mirrors
    // routes/messages.ts's identical reasoning: never assume success or
    // failure for an outcome that could not be confirmed either way.
    responseStatus = 'unknown';
  }

  logAuditFallback({
    action: 'blast.message.send',
    target: `${session}:${chatId}`,
    result: responseStatus === 'sent' ? 'success' : 'failure',
  });

  // Always HTTP 200 with a structured status field — this endpoint's one
  // caller is a trusted internal service (the Django Celery task), which
  // needs the sent/failed/unknown distinction to decide how to resolve
  // its own OutboundOperation/BlastRecipient rows, not a browser needing
  // standard HTTP error-status semantics (unlike routes/messages.ts,
  // whose caller IS a browser).
  res.status(200).json({
    status: responseStatus,
    ...(providerMessageId !== undefined ? { providerMessageId } : {}),
    idempotencyKey: idempotencyKey || undefined,
  });
});

// Discussed requirement — Conversation/Bot Engine interactive list menus
// (`apps.chats.conversation_engine`, via `apps.blast.bff_client.send_list_message`
// — same Django-side module `send_blast_message` above already lives in,
// despite the "blast" name; this module is really this project's one
// generic Office/Celery/Django -> BFF internal-dispatch surface, not
// blast-exclusive). New ALLOWLISTED WAHA operation (`sendList`,
// CLAUDE.md rule 5) — `sendText` above is completely untouched, both
// remain available side by side. Verified live against this exact WAHA
// deployment (GOWS engine) by the project operator directly, request
// shape confirmed via a real successful `sendList` call before this
// route was written — never a guess from WAHA's general docs alone.
router.post('/blast/send-list', requireOfficeDispatchKey, async (req, res) => {
  const { session, chatId, list } = req.body ?? {};

  if (typeof session !== 'string' || !session) {
    sendBadRequest(res, 'session is required');
    return;
  }
  if (!config.wahaSessionName || session !== config.wahaSessionName) {
    sendNotFound(res, 'Unknown session');
    return;
  }
  if (typeof chatId !== 'string' || !chatId || !list || typeof list !== 'object') {
    sendBadRequest(res, 'chatId and list are required');
    return;
  }

  const idempotencyKey = req.header('Idempotency-Key') ?? '';

  // WAHA's confirmed `sendList` request shape (project operator's own
  // live-verified curl, not from general docs): {chatId, message: {...},
  // reply_to, session} — `list` here IS that inner `message` object,
  // built by apps.chats.conversation_engine, passed through verbatim
  // (never reshaped here — this route stays a thin, allowlisted pass-
  // through, same discipline as `/blast/send` above).
  const result = await callWaha('sendList', session, {
    baseUrl: config.wahaBaseUrl,
    apiKey: config.wahaApiKey,
    timeoutMs: config.wahaTimeoutMs,
    body: { session, chatId, message: list, reply_to: null },
  });

  let responseStatus: 'sent' | 'failed' | 'unknown';
  let providerMessageId: string | undefined;
  if (result.outcome === 'success') {
    responseStatus = 'sent';
    const body = (result.json ?? {}) as Record<string, unknown>;
    providerMessageId = typeof body.id === 'string' ? body.id : undefined;
  } else if (result.outcome === 'http_error') {
    responseStatus = 'failed';
  } else {
    responseStatus = 'unknown';
  }

  logAuditFallback({
    action: 'blast.list.send',
    target: `${session}:${chatId}`,
    result: responseStatus === 'sent' ? 'success' : 'failure',
  });

  res.status(200).json({
    status: responseStatus,
    ...(providerMessageId !== undefined ? { providerMessageId } : {}),
    idempotencyKey: idempotencyKey || undefined,
  });
});

// Blast number-validity check (Discussed requirement, live-verified
// against the real WAHA deployment — see wahaAllowlist.ts's own comment
// for the evidence): `{numberExists: boolean}` for a definite answer,
// `null` ONLY for a genuine BFF/WAHA-level failure (timeout/network/http
// error) — never conflated with a definite `false`, so
// apps.blast.tasks.dispatch_blast_recipient_task can short-circuit on a
// definite `false` only, exactly like sendText's own sent/failed/unknown
// discipline.
router.get('/blast/check-number', requireOfficeDispatchKey, async (req, res) => {
  const session = typeof req.query.session === 'string' ? req.query.session : '';
  const phone = typeof req.query.phone === 'string' ? req.query.phone : '';

  if (!session) {
    sendBadRequest(res, 'session is required');
    return;
  }
  if (!config.wahaSessionName || session !== config.wahaSessionName) {
    sendNotFound(res, 'Unknown session');
    return;
  }
  if (!phone) {
    sendBadRequest(res, 'phone is required');
    return;
  }

  const result = await callWaha('checkNumberExists', session, {
    baseUrl: config.wahaBaseUrl,
    apiKey: config.wahaApiKey,
    timeoutMs: config.wahaTimeoutMs,
    query: { phone, session },
  });

  if (result.outcome !== 'success') {
    res.status(200).json({ numberExists: null });
    return;
  }

  const body = (result.json ?? {}) as Record<string, unknown>;
  const numberExists = typeof body.numberExists === 'boolean' ? body.numberExists : null;
  res.status(200).json({ numberExists });
});

export default router;
