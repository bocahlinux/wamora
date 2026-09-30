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

// Discussed requirement — human-like bot reply delay
// (apps.chats.conversation_engine/apps.chats.tasks, BotConfig.reply_delay_seconds).
// Office/Celery -> BFF half; mirrors routes.internalBlast.test.ts exactly.
describe.each([
  ['/internal/typing/start', 'startTyping'],
  ['/internal/typing/stop', 'stopTyping'],
])('POST %s', (url, wahaPath) => {
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
    const res = await request(app).post(url).send({ session: 'test_session', chatId: 'c1@lid' });
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects a request with the wrong key', async () => {
    const res = await request(app)
      .post(url)
      .set('X-Office-Dispatch-Key', 'wrong-secret')
      .send({ session: 'test_session', chatId: 'c1@lid' });
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('a valid session/user JWT alone (no office dispatch key) is never sufficient — this route accepts no Bearer auth at all', async () => {
    const res = await request(app)
      .post(url)
      .set('Authorization', 'Bearer whatever-a-frontend-jwt-would-be')
      .send({ session: 'test_session', chatId: 'c1@lid' });
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects an unknown session name', async () => {
    const res = await request(app)
      .post(url)
      .set('X-Office-Dispatch-Key', 'office-dispatch-secret')
      .send({ session: 'some-other-session', chatId: 'c1@lid' });
    expect(res.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('requires chatId', async () => {
    const res = await request(app)
      .post(url)
      .set('X-Office-Dispatch-Key', 'office-dispatch-secret')
      .send({ session: 'test_session' });
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it(`calls WAHA ${wahaPath} with {chatId, session} and reports ok: true on success`, async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));

    const res = await request(app)
      .post(url)
      .set('X-Office-Dispatch-Key', 'office-dispatch-secret')
      .send({ session: 'test_session', chatId: 'c1@lid' });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ ok: true });

    const [callUrl, init] = fetchMock.mock.calls[0];
    expect(String(callUrl)).toContain(`/api/${wahaPath}`);
    expect((init as RequestInit).method).toBe('POST');
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({ chatId: 'c1@lid', session: 'test_session' });
  });

  it('reports ok: false (still HTTP 200) when WAHA returns a clean error', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ message: 'bad request' }), { status: 400 }));

    const res = await request(app)
      .post(url)
      .set('X-Office-Dispatch-Key', 'office-dispatch-secret')
      .send({ session: 'test_session', chatId: 'c1@lid' });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ ok: false });
  });

  it('never leaks the WAHA API key in any response', async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    const res = await request(app)
      .post(url)
      .set('X-Office-Dispatch-Key', 'office-dispatch-secret')
      .send({ session: 'test_session', chatId: 'c1@lid' });
    expect(JSON.stringify(res.body)).not.toContain('test-waha-api-key');
  });
});
