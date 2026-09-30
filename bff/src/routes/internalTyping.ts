// Office/Celery -> BFF internal typing-indicator endpoints — discussed
// requirement (human-like bot reply delay,
// `apps.chats.conversation_engine`/`apps.chats.tasks`,
// `BotConfig.reply_delay_seconds`). Mirrors `routes/internalBlast.ts`
// exactly: authenticated by `requireOfficeDispatchKey` ONLY, mounted
// under `/internal` (never `/api`, CLAUDE.md rule 4/5 spirit — this is
// server-to-server only), calls exactly the two newly-allowlisted WAHA
// operations (`startTyping`/`stopTyping`, CLAUDE.md rule 5) and nothing
// else.
//
// Deliberately simpler than `/blast/send`/`/blast/send-list`: a typing
// indicator is fire-and-forget (no `provider_message_id`, no
// OutboundOperation/idempotency-key concept — repeating `startTyping` is
// harmless, there is nothing to deduplicate). The caller
// (`apps.chats.tasks`) already treats any failure here as non-fatal and
// proceeds to send the real message regardless.

import { Router } from 'express';

import { config } from '../config';
import { sendBadRequest, sendNotFound } from '../errors';
import { requireOfficeDispatchKey } from '../middleware/officeAuth';
import { callWaha } from '../wahaClient';
import type { WahaEndpointName } from '../wahaAllowlist';

const router = Router();

async function dispatchTyping(endpointName: Extract<WahaEndpointName, 'startTyping' | 'stopTyping'>, session: string, chatId: string) {
  return callWaha(endpointName, session, {
    baseUrl: config.wahaBaseUrl,
    apiKey: config.wahaApiKey,
    timeoutMs: config.wahaTimeoutMs,
    body: { chatId, session },
  });
}

router.post('/typing/start', requireOfficeDispatchKey, async (req, res) => {
  const { session, chatId } = req.body ?? {};

  if (typeof session !== 'string' || !session) {
    sendBadRequest(res, 'session is required');
    return;
  }
  if (!config.wahaSessionName || session !== config.wahaSessionName) {
    sendNotFound(res, 'Unknown session');
    return;
  }
  if (typeof chatId !== 'string' || !chatId) {
    sendBadRequest(res, 'chatId is required');
    return;
  }

  const result = await dispatchTyping('startTyping', session, chatId);
  // Always HTTP 200 with a plain ok flag — same "trusted internal
  // caller, not a browser" reasoning as /blast/send's own response
  // shape, simplified further since there is no sent/failed/unknown
  // distinction meaningful for a typing indicator (the caller does not
  // branch on it, only logs a warning on failure).
  res.status(200).json({ ok: result.outcome === 'success' });
});

router.post('/typing/stop', requireOfficeDispatchKey, async (req, res) => {
  const { session, chatId } = req.body ?? {};

  if (typeof session !== 'string' || !session) {
    sendBadRequest(res, 'session is required');
    return;
  }
  if (!config.wahaSessionName || session !== config.wahaSessionName) {
    sendNotFound(res, 'Unknown session');
    return;
  }
  if (typeof chatId !== 'string' || !chatId) {
    sendBadRequest(res, 'chatId is required');
    return;
  }

  const result = await dispatchTyping('stopTyping', session, chatId);
  res.status(200).json({ ok: result.outcome === 'success' });
});

export default router;
