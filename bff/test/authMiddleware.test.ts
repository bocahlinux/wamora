import express from 'express';
import jsonwebtoken from 'jsonwebtoken';
import request from 'supertest';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { generateTestKeyPair } from './testKeys';

const { privateKey, publicKey } = generateTestKeyPair();

vi.mock('../src/config', () => ({
  config: {
    jwtPublicKey: publicKey,
    jwtIssuer: 'test-issuer',
    jwtAudience: 'test-audience',
  },
}));

function sign(scopes: string[] = []) {
  return jsonwebtoken.sign({ sub: '1', scopes }, privateKey, {
    algorithm: 'RS256',
    issuer: 'test-issuer',
    audience: 'test-audience',
    expiresIn: '1h',
  });
}

describe('requireAuth / requireScope', () => {
  let app: express.Express;

  beforeEach(async () => {
    vi.resetModules();
    const { requireAuth, requireScope } = await import('../src/middleware/auth');
    app = express();
    app.get('/reading-only', requireAuth, requireScope('reading'), (_req, res) => res.json({ ok: true }));
    app.get('/public', (_req, res) => res.json({ ok: true }));
  });

  it('rejects a request with no Authorization header', async () => {
    const res = await request(app).get('/reading-only');
    expect(res.status).toBe(401);
    expect(res.body.error.code).toBe('unauthorized');
  });

  it('rejects a malformed Authorization header', async () => {
    const res = await request(app).get('/reading-only').set('Authorization', 'Token abc');
    expect(res.status).toBe(401);
  });

  it('rejects an invalid token', async () => {
    const res = await request(app).get('/reading-only').set('Authorization', 'Bearer not-a-real-token');
    expect(res.status).toBe(401);
  });

  it('rejects a valid token lacking the required scope', async () => {
    const token = sign(['sending']);
    const res = await request(app).get('/reading-only').set('Authorization', `Bearer ${token}`);
    expect(res.status).toBe(403);
    expect(res.body.error.code).toBe('forbidden');
  });

  it('allows a valid token carrying the required scope', async () => {
    const token = sign(['reading', 'sending']);
    const res = await request(app).get('/reading-only').set('Authorization', `Bearer ${token}`);
    expect(res.status).toBe(200);
  });

  it('never requires auth for a route that does not use the middleware', async () => {
    const res = await request(app).get('/public');
    expect(res.status).toBe(200);
  });
});
