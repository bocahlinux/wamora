// Phase 14 Blocker B3 (TLS/reverse proxy) — bff/src/app.ts, bff/src/config.ts.
import { beforeEach, describe, expect, it, vi } from 'vitest';

const baseConfig = {
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
  officeDispatchServiceKey: '',
  rateLimitMaxPerMinute: 300,
};

describe('trust proxy setting', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('does not trust any proxy by default (TRUST_PROXY unset)', async () => {
    vi.doMock('../src/config', () => ({ config: { ...baseConfig, trustProxy: false } }));
    const { createApp } = await import('../src/app');
    const app = createApp();
    expect(app.get('trust proxy')).toBe(false);
  });

  it('trusts exactly one hop when TRUST_PROXY=true', async () => {
    vi.doMock('../src/config', () => ({ config: { ...baseConfig, trustProxy: true } }));
    const { createApp } = await import('../src/app');
    const app = createApp();
    expect(app.get('trust proxy')).toBe(1);
  });
});
