// BFF -> Django internal endpoints —
// docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 8.
// Authenticated by INTERNAL_SERVICE_KEY (a static shared secret, distinct
// from the end user's JWT — requirement #12). Every call here is
// synchronous but best-effort: callers must proceed regardless of the
// result (register/resolve/audit degradation is documented behavior, not
// an error state — contract Sections 9/10/14).

export interface DjangoCallOptions {
  baseUrl: string;
  serviceKey: string;
  timeoutMs: number;
}

export type DjangoResult<T> = { ok: true; data: T } | { ok: false };

/** The JWT `sub` claim is a string (Django user PK stringified);
 * Django's internal endpoints expect an integer FK value. */
function toActorId(actorId: string | undefined): number | null {
  if (!actorId) return null;
  const parsed = Number(actorId);
  return Number.isInteger(parsed) ? parsed : null;
}

// Diagnostic logging — docs/generated/INBOX-RECONCILIATION-TRIGGER-OBSERVABILITY-AUDIT-REPORT.md.
// This channel has been observed to silently no-op (every failure mode —
// missing config, thrown exception, non-2xx Django response — previously
// collapsed into the same indistinguishable `{ok:false}`, with nothing
// logged anywhere). These lines make each outcome observable. NEVER logs
// `options.serviceKey`, any JWT, or the request/response body (which can
// carry a phone-shaped chat id or, on the audit-event path, message
// send outcomes) — only method, path, HTTP status, and a short,
// non-body error code/message extracted from a JSON error envelope.
function logInternal(line: string): void {
  console.log(`[djangoClient] ${line}`);
}

async function postJson<T>(
  path: string,
  body: unknown,
  options: DjangoCallOptions,
  method: 'POST' | 'PATCH' = 'POST',
): Promise<DjangoResult<T>> {
  if (!options.baseUrl || !options.serviceKey) {
    logInternal(
      `skipped ${method} ${path}: ${!options.baseUrl ? 'DJANGO_INTERNAL_BASE_URL' : 'INTERNAL_SERVICE_KEY'} not configured`,
    );
    return { ok: false };
  }
  const url = new URL(path, options.baseUrl);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs);
  logInternal(`-> ${method} ${url} (X-Internal-Service-Key attached, length=${options.serviceKey.length})`);
  try {
    const response = await fetch(url, {
      method,
      headers: {
        'Content-Type': 'application/json',
        'X-Internal-Service-Key': options.serviceKey,
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) {
      // Best-effort: extract only the error envelope's code/request_id
      // (apps.core.exceptions.api_exception_handler's shape) — never the
      // raw body, which could otherwise echo back request data.
      let detail = '';
      try {
        const errBody = (await response.json()) as { error?: { code?: string; request_id?: string } };
        if (errBody?.error) {
          detail = ` code=${errBody.error.code ?? 'unknown'} request_id=${errBody.error.request_id ?? 'none'}`;
        }
      } catch {
        /* non-JSON or empty error body — status code alone is still logged below */
      }
      logInternal(`<- ${method} ${url} status=${response.status}${detail}`);
      return { ok: false };
    }
    logInternal(`<- ${method} ${url} status=${response.status}`);
    const data = (await response.json()) as T;
    return { ok: true, data };
  } catch (err) {
    const name = err instanceof Error ? err.name : typeof err;
    const message = err instanceof Error ? err.message : String(err);
    logInternal(`x  ${method} ${url} threw ${name}: ${message}`);
    return { ok: false };
  } finally {
    clearTimeout(timer);
  }
}

export interface OutboundOperationState {
  id: number;
  created: boolean;
  status: 'pending' | 'sent' | 'failed' | 'unknown';
  provider_message_id: string;
  retryable: boolean;
}

export function registerOutboundOperation(
  params: { session: string; idempotencyKey: string; destination: string; operationType: string },
  options: DjangoCallOptions,
): Promise<DjangoResult<OutboundOperationState>> {
  return postJson<OutboundOperationState>(
    '/internal/outbound-operations/',
    {
      session: params.session,
      idempotency_key: params.idempotencyKey,
      destination: params.destination,
      operation_type: params.operationType,
    },
    options,
  );
}

export function resolveOutboundOperation(
  id: number,
  params: {
    status: 'sent' | 'failed' | 'unknown';
    providerMessageId?: string;
    actorId?: string;
    action?: string;
    target?: string;
    result?: 'success' | 'failure';
  },
  options: DjangoCallOptions,
): Promise<DjangoResult<OutboundOperationState>> {
  return postJson<OutboundOperationState>(
    `/internal/outbound-operations/${id}/`,
    {
      status: params.status,
      provider_message_id: params.providerMessageId ?? '',
      actor_id: toActorId(params.actorId),
      action: params.action ?? '',
      target: params.target ?? '',
      result: params.result ?? null,
    },
    options,
    'PATCH',
  );
}

export interface ReconciliationTriggerResult {
  triggered: boolean;
  executor?: 'sync' | 'celery';
}

/** POST /internal/reconciliation/trigger/ —
 * docs/generated/INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md.
 * This WAHA deployment sends no webhook for self-sent messages, so the
 * caller (routes/messages.ts) fires this once, fire-and-forget, right
 * after a confirmed successful send — never awaited before that route's
 * own response is sent. The result is informational only; a failure here
 * has no effect on the send flow, same best-effort philosophy as every
 * other function in this file. */
export function triggerReconciliation(
  params: { session: string; chatId: string },
  options: DjangoCallOptions,
): Promise<DjangoResult<ReconciliationTriggerResult>> {
  return postJson<ReconciliationTriggerResult>(
    '/internal/reconciliation/trigger/',
    { session: params.session, chat_id: params.chatId },
    options,
  );
}

export function writeAuditEvent(
  params: { actorId?: string; action: string; target: string; result: 'success' | 'failure' },
  options: DjangoCallOptions,
): Promise<DjangoResult<{ id: number }>> {
  return postJson<{ id: number }>(
    '/internal/audit-events/',
    {
      actor_id: toActorId(params.actorId),
      action: params.action,
      target: params.target,
      result: params.result,
    },
    options,
  );
}
