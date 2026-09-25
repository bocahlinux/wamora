import type { Express } from 'express';
import request from 'supertest';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/config', () => ({
  config: {
    port: 8080,
    wahaBaseUrl: 'http://waha.internal:3000',
    wahaApiKey: 'test-waha-api-key',
    wahaSessionName: 'test_session',
    corsAllowedOrigin: '',
    jwtPublicKey: '',
    jwtIssuer: 'test-issuer',
    jwtAudience: 'test-audience',
    djangoInternalBaseUrl: '',
    internalServiceKey: '',
    djangoInternalTimeoutMs: 1000,
    wahaTimeoutMs: 1000,
    officeDispatchServiceKey: 'office-dispatch-secret',
  },
}));

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

const SEND_URL = '/internal/blast/send';

describe('POST /internal/blast/send', () => {
  let app: Express;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    vi.resetModules();
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { createApp } = await import('../src/app');
    app = createApp();
  });

  it('rejects a request with no X-Office-Dispatch-Key header', async () => {
    const res = await request(app).post(SEND_URL).send({ session: 'test_session', chatId: 'c1@lid', text: 'hi' });
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects a request with the wrong key', async () => {
    const res = await request(app)
      .post(SEND_URL)
      .set('X-Office-Dispatch-Key', 'wrong-secret')
      .send({ session: 'test_session', chatId: 'c1@lid', text: 'hi' });
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('a valid session/user JWT alone (no office dispatch key) is never sufficient — this route accepts no Bearer auth at all', async () => {
    const res = await request(app)
      .post(SEND_URL)
      .set('Authorization', 'Bearer whatever-a-frontend-jwt-would-be')
      .send({ session: 'test_session', chatId: 'c1@lid', text: 'hi' });
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects an unknown session name', async () => {
    const res = await request(app)
      .post(SEND_URL)
      .set('X-Office-Dispatch-Key', 'office-dispatch-secret')
      .send({ session: 'some-other-session', chatId: 'c1@lid', text: 'hi' });
    expect(res.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('requires chatId and text', async () => {
    const res = await request(app)
      .post(SEND_URL)
      .set('X-Office-Dispatch-Key', 'office-dispatch-secret')
      .send({ session: 'test_session' });
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('calls WAHA sendText and reports sent on success', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'wa-msg-1' }));

    const res = await request(app)
      .post(SEND_URL)
      .set('X-Office-Dispatch-Key', 'office-dispatch-secret')
      .set('Idempotency-Key', 'blast:1:1')
      .send({ session: 'test_session', chatId: 'c1@lid', text: 'hi' });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: 'sent', providerMessageId: 'wa-msg-1', idempotencyKey: 'blast:1:1' });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/api/sendText');
    expect((init as RequestInit).method).toBe('POST');
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({ session: 'test_session', chatId: 'c1@lid', text: 'hi' });
  });

  it('reports failed (HTTP 200) when WAHA returns a clean error — never a duplicate-triggering non-200', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ message: 'bad request' }), { status: 400 }));

    const res = await request(app)
      .post(SEND_URL)
      .set('X-Office-Dispatch-Key', 'office-dispatch-secret')
      .send({ session: 'test_session', chatId: 'c1@lid', text: 'hi' });

    expect(res.status).toBe(200);
    expect(res.body.status).toBe('failed');
  });

  it('reports unknown when the WAHA call times out', async () => {
    fetchMock.mockImplementation((_url: string, init: RequestInit) => {
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
      .set('X-Office-Dispatch-Key', 'office-dispatch-secret')
      .send({ session: 'test_session', chatId: 'c1@lid', text: 'hi' });

    expect(res.status).toBe(200);
    expect(res.body.status).toBe('unknown');
  });

  it('never leaks the WAHA API key in any response', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'wa-msg-1' }));
    const res = await request(app)
      .post(SEND_URL)
      .set('X-Office-Dispatch-Key', 'office-dispatch-secret')
      .send({ session: 'test_session', chatId: 'c1@lid', text: 'hi' });
    expect(JSON.stringify(res.body)).not.toContain('test-waha-api-key');
  });

  it('never calls Django (registerOutboundOperation/resolveOutboundOperation) — this route only calls WAHA', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'wa-msg-1' }));
    await request(app)
      .post(SEND_URL)
      .set('X-Office-Dispatch-Key', 'office-dispatch-secret')
      .send({ session: 'test_session', chatId: 'c1@lid', text: 'hi' });
    const djangoCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/internal/outbound-operations/'));
    expect(djangoCalls).toHaveLength(0);
  });
});
