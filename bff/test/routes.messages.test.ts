import type { Express } from 'express';
import jsonwebtoken from 'jsonwebtoken';
import request from 'supertest';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { generateTestKeyPair } from './testKeys';

const { privateKey, publicKey } = generateTestKeyPair();

vi.mock('../src/config', () => ({
  config: {
    port: 8080,
    wahaBaseUrl: 'http://waha.internal:3000',
    wahaApiKey: 'test-waha-api-key',
    wahaSessionName: 'test_session',
    corsAllowedOrigin: '',
    jwtPublicKey: publicKey,
    jwtIssuer: 'test-issuer',
    jwtAudience: 'test-audience',
    djangoInternalBaseUrl: 'http://django.internal:8000',
    internalServiceKey: 'internal-secret',
    djangoInternalTimeoutMs: 1000,
    wahaTimeoutMs: 1000,
  },
}));

function token() {
  return jsonwebtoken.sign({ sub: '42', scopes: ['sending'] }, privateKey, {
    algorithm: 'RS256',
    issuer: 'test-issuer',
    audience: 'test-audience',
    expiresIn: '1h',
  });
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

const SEND_URL = '/api/sessions/test_session/messages';

describe('POST /api/sessions/:session/messages', () => {
  let app: Express;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    vi.resetModules();
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { createApp } = await import('../src/app');
    app = createApp();
  });

  const routeFetch = (registerResponse: unknown, wahaResponse: Response, resolveResponse: unknown = { id: 1 }) => {
    fetchMock.mockImplementation((url: string, init: RequestInit) => {
      const href = String(url);
      if (href.includes('/internal/outbound-operations/') && init.method === 'PATCH') {
        return Promise.resolve(jsonResponse(resolveResponse));
      }
      if (href.includes('/internal/outbound-operations/')) {
        return Promise.resolve(jsonResponse(registerResponse));
      }
      return Promise.resolve(wahaResponse);
    });
  };

  it('requires the Idempotency-Key header', async () => {
    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', `Bearer ${token()}`)
      .send({ chatId: 'c1@lid', text: 'hi' });
    expect(res.status).toBe(400);
  });

  it('requires chatId and text', async () => {
    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', 'k1')
      .send({});
    expect(res.status).toBe(400);
  });

  it('first request: registers, calls WAHA, resolves to sent', async () => {
    routeFetch(
      { id: 1, created: true, status: 'pending', provider_message_id: '', retryable: false },
      jsonResponse({ id: 'wa-msg-1' }),
    );

    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', 'k1')
      .send({ chatId: 'c1@lid', text: 'hi' });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: 'sent', providerMessageId: 'wa-msg-1' });

    const resolveCall = fetchMock.mock.calls.find(
      ([url, init]) => String(url).includes('/internal/outbound-operations/1/') && (init as RequestInit).method === 'PATCH',
    );
    expect(resolveCall).toBeDefined();
    const body = JSON.parse((resolveCall![1] as RequestInit).body as string);
    expect(body.status).toBe('sent');
    expect(body.action).toBe('message.send');
  });

  it('WAHA success response without an "id" field: still resolves to sent, providerMessageId undefined, no throw', async () => {
    // docs/generated/PHASE-6-POST-AUDIT-FIX-REPORT.md item 3: `id` is a
    // best-effort, unconfirmed guess at WAHA's real field name — its
    // absence must never fail the send.
    routeFetch(
      { id: 1, created: true, status: 'pending', provider_message_id: '', retryable: false },
      jsonResponse({ someOtherField: 'not-id' }),
    );

    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', 'k1')
      .send({ chatId: 'c1@lid', text: 'hi' });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: 'sent', providerMessageId: undefined });

    const resolveCall = fetchMock.mock.calls.find(
      ([url, init]) => String(url).includes('/internal/outbound-operations/1/') && (init as RequestInit).method === 'PATCH',
    );
    const body = JSON.parse((resolveCall![1] as RequestInit).body as string);
    expect(body.status).toBe('sent');
    expect(body.provider_message_id).toBe('');
  });

  it('duplicate key, existing PENDING row: does not call WAHA again', async () => {
    routeFetch(
      { id: 1, created: false, status: 'pending', provider_message_id: '', retryable: false },
      jsonResponse({ id: 'should-not-be-called' }),
    );

    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', 'k1')
      .send({ chatId: 'c1@lid', text: 'hi' });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: 'pending', providerMessageId: undefined });
    const wahaSendCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/sendText'));
    expect(wahaSendCalls).toHaveLength(0);
  });

  it('duplicate key, existing SENT row: returns the existing result, no second WAHA call', async () => {
    routeFetch(
      { id: 1, created: false, status: 'sent', provider_message_id: 'wa-msg-1', retryable: false },
      jsonResponse({}),
    );

    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', 'k1')
      .send({ chatId: 'c1@lid', text: 'hi' });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: 'sent', providerMessageId: 'wa-msg-1' });
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/sendText'))).toHaveLength(0);
  });

  it('duplicate key, fresh FAILED row: requires a new idempotency key, no WAHA call', async () => {
    routeFetch(
      { id: 1, created: false, status: 'failed', provider_message_id: '', retryable: false },
      jsonResponse({}),
    );

    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', 'k1')
      .send({ chatId: 'c1@lid', text: 'hi' });

    expect(res.status).toBe(409);
    expect(res.body.error.code).toBe('requires_new_idempotency_key');
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/sendText'))).toHaveLength(0);
  });

  it('duplicate key, fresh UNKNOWN row (not retryable yet): no WAHA call', async () => {
    routeFetch(
      { id: 1, created: false, status: 'unknown', provider_message_id: '', retryable: false },
      jsonResponse({}),
    );

    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', 'k1')
      .send({ chatId: 'c1@lid', text: 'hi' });

    expect(res.status).toBe(409);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/sendText'))).toHaveLength(0);
  });

  it('duplicate key, STALE UNKNOWN row (retryable): calls WAHA again using the same operation id', async () => {
    routeFetch(
      { id: 1, created: false, status: 'unknown', provider_message_id: '', retryable: true },
      jsonResponse({ id: 'wa-msg-2' }),
    );

    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', 'k1')
      .send({ chatId: 'c1@lid', text: 'hi' });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: 'sent', providerMessageId: 'wa-msg-2' });
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/sendText'))).toHaveLength(1);
  });

  it('WAHA returns a clean error: resolves to failed', async () => {
    routeFetch(
      { id: 1, created: true, status: 'pending', provider_message_id: '', retryable: false },
      new Response(JSON.stringify({ message: 'bad request' }), { status: 400 }),
    );

    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', 'k1')
      .send({ chatId: 'c1@lid', text: 'hi' });

    expect(res.status).toBe(502);
    const resolveCall = fetchMock.mock.calls.find(
      ([url, init]) => String(url).includes('/internal/outbound-operations/1/') && (init as RequestInit).method === 'PATCH',
    );
    const body = JSON.parse((resolveCall![1] as RequestInit).body as string);
    expect(body.status).toBe('failed');
  });

  it('WAHA call times out: resolves to unknown, never claims success or failure', async () => {
    fetchMock.mockImplementation((url: string, init: RequestInit) => {
      const href = String(url);
      if (href.includes('/internal/outbound-operations/') && init.method === 'PATCH') {
        return Promise.resolve(jsonResponse({ id: 1 }));
      }
      if (href.includes('/internal/outbound-operations/')) {
        return Promise.resolve(
          jsonResponse({ id: 1, created: true, status: 'pending', provider_message_id: '', retryable: false }),
        );
      }
      // WAHA sendText: simulate an abort/timeout.
      return new Promise((_resolve, reject) => {
        (init.signal as AbortSignal).addEventListener('abort', () => {
          const err = new Error('aborted');
          err.name = 'AbortError';
          reject(err);
        });
      });
    });

    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', 'k1')
      .send({ chatId: 'c1@lid', text: 'hi' });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: 'unknown' });
  });

  it('proceeds to WAHA when Django is unreachable at registration time (documented degradation)', async () => {
    fetchMock.mockImplementation((url: string) => {
      const href = String(url);
      if (href.includes('/internal/')) {
        return Promise.reject(new Error('django unreachable'));
      }
      return Promise.resolve(jsonResponse({ id: 'wa-msg-3' }));
    });

    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', 'k1')
      .send({ chatId: 'c1@lid', text: 'hi' });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: 'sent', providerMessageId: 'wa-msg-3' });
  });

  // docs/generated/PHASE-6-POST-AUDIT-FIX-REPORT.md item 1: the send flow
  // must emit the same local structured audit fallback line every other
  // sensitive route already has, regardless of Django's reachability.
  describe('local audit fallback (contract Section 10 mitigation)', () => {
    it('is emitted alongside a normal, successful Django audit write', async () => {
      const logSpy = vi.spyOn(console, 'log').mockImplementation(() => undefined);
      routeFetch(
        { id: 1, created: true, status: 'pending', provider_message_id: '', retryable: false },
        jsonResponse({ id: 'wa-msg-1' }),
      );

      await request(app)
        .post(SEND_URL)
        .set('Authorization', `Bearer ${token()}`)
        .set('Idempotency-Key', 'k1')
        .send({ chatId: 'c1@lid', text: 'hi' });

      const auditLine = logSpy.mock.calls.map((call) => call[0]).find((line) => String(line).includes('"type":"audit"'));
      expect(auditLine).toBeDefined();
      const parsed = JSON.parse(auditLine as string);
      expect(parsed.action).toBe('message.send');
      expect(parsed.result).toBe('success');
      // The local fallback logs the raw JWT `sub` claim (a string) — only
      // the Django-bound payload converts it to an integer FK.
      expect(parsed.actor_id).toBe('42');

      // Django audit write still happened too — the fallback is additive,
      // not a replacement (existing "keep the existing behavior" requirement).
      const resolveCall = fetchMock.mock.calls.find(
        ([url, init]) => String(url).includes('/internal/outbound-operations/1/') && (init as RequestInit).method === 'PATCH',
      );
      expect(resolveCall).toBeDefined();

      logSpy.mockRestore();
    });

    it('is still emitted when Django is unreachable for the entire flow (registration and resolve both fail)', async () => {
      const logSpy = vi.spyOn(console, 'log').mockImplementation(() => undefined);
      fetchMock.mockImplementation((url: string) => {
        const href = String(url);
        if (href.includes('/internal/')) {
          return Promise.reject(new Error('django unreachable'));
        }
        return Promise.resolve(jsonResponse({ id: 'wa-msg-4' }));
      });

      const res = await request(app)
        .post(SEND_URL)
        .set('Authorization', `Bearer ${token()}`)
        .set('Idempotency-Key', 'k1')
        .send({ chatId: 'c1@lid', text: 'hi' });

      expect(res.status).toBe(200);
      const auditLine = logSpy.mock.calls.map((call) => call[0]).find((line) => String(line).includes('"type":"audit"'));
      expect(auditLine).toBeDefined();
      const parsed = JSON.parse(auditLine as string);
      expect(parsed.action).toBe('message.send');
      expect(parsed.result).toBe('success');

      logSpy.mockRestore();
    });

    it('reflects a failed send outcome (result: failure) in the fallback line', async () => {
      const logSpy = vi.spyOn(console, 'log').mockImplementation(() => undefined);
      routeFetch(
        { id: 1, created: true, status: 'pending', provider_message_id: '', retryable: false },
        new Response('bad request', { status: 400 }),
      );

      await request(app)
        .post(SEND_URL)
        .set('Authorization', `Bearer ${token()}`)
        .set('Idempotency-Key', 'k1')
        .send({ chatId: 'c1@lid', text: 'hi' });

      const auditLine = logSpy.mock.calls.map((call) => call[0]).find((line) => String(line).includes('"type":"audit"'));
      const parsed = JSON.parse(auditLine as string);
      expect(parsed.result).toBe('failure');

      logSpy.mockRestore();
    });
  });

  describe('reconciliation trigger (fire-and-forget)', () => {
    // docs/generated/INBOX-OUTBOUND-RECONCILIATION-IMPLEMENTATION-REPORT.md
    const fullMock = (opts: {
      registerResponse: unknown;
      wahaResponse: Response;
      resolveResponse?: unknown;
      onTrigger?: (body: unknown) => void;
      triggerResponse?: Response;
    }) => {
      fetchMock.mockImplementation((url: string, init: RequestInit) => {
        const href = String(url);
        if (href.includes('/internal/reconciliation/trigger/')) {
          opts.onTrigger?.(JSON.parse(init.body as string));
          return Promise.resolve(opts.triggerResponse ?? jsonResponse({ triggered: true, executor: 'sync' }));
        }
        if (href.includes('/internal/outbound-operations/') && init.method === 'PATCH') {
          return Promise.resolve(jsonResponse(opts.resolveResponse ?? { id: 1 }));
        }
        if (href.includes('/internal/outbound-operations/')) {
          return Promise.resolve(jsonResponse(opts.registerResponse));
        }
        return Promise.resolve(opts.wahaResponse);
      });
    };

    it('fires the trigger with the session and chatId, after a confirmed sent outcome', async () => {
      let triggerBody: unknown;
      fullMock({
        registerResponse: { id: 1, created: true, status: 'pending', provider_message_id: '', retryable: false },
        wahaResponse: jsonResponse({ id: 'wa-msg-1' }),
        onTrigger: (body) => {
          triggerBody = body;
        },
      });

      const res = await request(app)
        .post(SEND_URL)
        .set('Authorization', `Bearer ${token()}`)
        .set('Idempotency-Key', 'k1')
        .send({ chatId: 'c1@lid', text: 'hi' });

      expect(res.status).toBe(200);
      expect(triggerBody).toEqual({ session: 'test_session', chat_id: 'c1@lid' });
    });

    it('does NOT fire the trigger when WAHA returns a clean error (failed)', async () => {
      let triggerCalled = false;
      fullMock({
        registerResponse: { id: 1, created: true, status: 'pending', provider_message_id: '', retryable: false },
        wahaResponse: new Response(JSON.stringify({ message: 'bad request' }), { status: 400 }),
        onTrigger: () => {
          triggerCalled = true;
        },
      });

      await request(app)
        .post(SEND_URL)
        .set('Authorization', `Bearer ${token()}`)
        .set('Idempotency-Key', 'k1')
        .send({ chatId: 'c1@lid', text: 'hi' });

      expect(triggerCalled).toBe(false);
    });

    it('does NOT fire the trigger when the send outcome is unknown (timeout)', async () => {
      let triggerCalled = false;
      fetchMock.mockImplementation((url: string, init: RequestInit) => {
        const href = String(url);
        if (href.includes('/internal/reconciliation/trigger/')) {
          triggerCalled = true;
          return Promise.resolve(jsonResponse({ triggered: true }));
        }
        if (href.includes('/internal/outbound-operations/') && init.method === 'PATCH') {
          return Promise.resolve(jsonResponse({ id: 1 }));
        }
        if (href.includes('/internal/outbound-operations/')) {
          return Promise.resolve(
            jsonResponse({ id: 1, created: true, status: 'pending', provider_message_id: '', retryable: false }),
          );
        }
        return new Promise((_resolve, reject) => {
          (init.signal as AbortSignal).addEventListener('abort', () => {
            const err = new Error('aborted');
            err.name = 'AbortError';
            reject(err);
          });
        });
      });

      const res = await request(app)
        .post(SEND_URL)
        .set('Authorization', `Bearer ${token()}`)
        .set('Idempotency-Key', 'k1')
        .send({ chatId: 'c1@lid', text: 'hi' });

      expect(res.status).toBe(200);
      expect(res.body).toEqual({ status: 'unknown' });
      expect(triggerCalled).toBe(false);
    });

    it('the send response is not delayed by the trigger call, even if it never resolves', async () => {
      // The trigger's fetch is a promise that NEVER resolves — proves the
      // route does not await it before responding.
      fetchMock.mockImplementation((url: string, init: RequestInit) => {
        const href = String(url);
        if (href.includes('/internal/reconciliation/trigger/')) {
          return new Promise(() => {
            /* never resolves */
          });
        }
        if (href.includes('/internal/outbound-operations/') && init.method === 'PATCH') {
          return Promise.resolve(jsonResponse({ id: 1 }));
        }
        if (href.includes('/internal/outbound-operations/')) {
          return Promise.resolve(
            jsonResponse({ id: 1, created: true, status: 'pending', provider_message_id: '', retryable: false }),
          );
        }
        return Promise.resolve(jsonResponse({ id: 'wa-msg-1' }));
      });

      const res = await request(app)
        .post(SEND_URL)
        .set('Authorization', `Bearer ${token()}`)
        .set('Idempotency-Key', 'k1')
        .send({ chatId: 'c1@lid', text: 'hi' });

      expect(res.status).toBe(200);
      expect(res.body).toEqual({ status: 'sent', providerMessageId: 'wa-msg-1' });
    });

    it('a failed trigger call (Django unreachable) does not affect the send response', async () => {
      fetchMock.mockImplementation((url: string, init: RequestInit) => {
        const href = String(url);
        if (href.includes('/internal/reconciliation/trigger/')) {
          return Promise.reject(new Error('django unreachable'));
        }
        if (href.includes('/internal/outbound-operations/') && init.method === 'PATCH') {
          return Promise.resolve(jsonResponse({ id: 1 }));
        }
        if (href.includes('/internal/outbound-operations/')) {
          return Promise.resolve(
            jsonResponse({ id: 1, created: true, status: 'pending', provider_message_id: '', retryable: false }),
          );
        }
        return Promise.resolve(jsonResponse({ id: 'wa-msg-1' }));
      });

      const res = await request(app)
        .post(SEND_URL)
        .set('Authorization', `Bearer ${token()}`)
        .set('Idempotency-Key', 'k1')
        .send({ chatId: 'c1@lid', text: 'hi' });

      expect(res.status).toBe(200);
      expect(res.body).toEqual({ status: 'sent', providerMessageId: 'wa-msg-1' });
    });
  });

  it('never leaks the WAHA API key in any response', async () => {
    routeFetch(
      { id: 1, created: true, status: 'pending', provider_message_id: '', retryable: false },
      jsonResponse({ id: 'wa-msg-1' }),
    );
    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', `Bearer ${token()}`)
      .set('Idempotency-Key', 'k1')
      .send({ chatId: 'c1@lid', text: 'hi' });
    expect(JSON.stringify(res.body)).not.toContain('test-waha-api-key');
  });
});
