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

function token(scopes: string[] = ['sending']) {
  return jsonwebtoken.sign({ sub: '42', scopes }, privateKey, {
    algorithm: 'RS256',
    issuer: 'test-issuer',
    audience: 'test-audience',
    expiresIn: '1h',
  });
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
}

// Discussed requirement — Inbox composer typing indicator. Frontend/JWT
// half of the same feature routes.internalTyping.test.ts covers for the
// Office/Celery/bot-reply-delay half.
describe.each([
  ['/api/sessions/test_session/typing/start', 'startTyping'],
  ['/api/sessions/test_session/typing/stop', 'stopTyping'],
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

  it('requires a Bearer JWT', async () => {
    const res = await request(app).post(url).send({ chatId: 'c1@lid' });
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('requires the sending scope', async () => {
    const res = await request(app)
      .post(url)
      .set('Authorization', `Bearer ${token(['reading'])}`)
      .send({ chatId: 'c1@lid' });
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects an unknown session name', async () => {
    const res = await request(app)
      .post(url.replace('test_session', 'some-other-session'))
      .set('Authorization', `Bearer ${token()}`)
      .send({ chatId: 'c1@lid' });
    expect(res.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('requires chatId', async () => {
    const res = await request(app)
      .post(url)
      .set('Authorization', `Bearer ${token()}`)
      .send({});
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it(`calls WAHA ${wahaPath} with {chatId, session} and reports ok: true on success`, async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));

    const res = await request(app)
      .post(url)
      .set('Authorization', `Bearer ${token()}`)
      .send({ chatId: 'c1@lid' });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ ok: true });

    const [callUrl, init] = fetchMock.mock.calls[0];
    expect(String(callUrl)).toContain(`/api/${wahaPath}`);
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({ chatId: 'c1@lid', session: 'test_session' });
  });

  it('reports ok: false (still HTTP 200) when WAHA returns a clean error', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ message: 'bad request' }), { status: 400 }));

    const res = await request(app)
      .post(url)
      .set('Authorization', `Bearer ${token()}`)
      .send({ chatId: 'c1@lid' });

    expect(res.status).toBe(200);
    expect(res.body).toEqual({ ok: false });
  });
});
