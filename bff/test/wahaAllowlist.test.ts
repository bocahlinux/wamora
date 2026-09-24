import { describe, expect, it } from 'vitest';

import { WAHA_ALLOWED_ENDPOINTS } from '../src/wahaAllowlist';

describe('WAHA_ALLOWED_ENDPOINTS', () => {
  it('contains exactly the eight endpoints in the Phase 6 contract, nothing else', () => {
    expect(Object.keys(WAHA_ALLOWED_ENDPOINTS).sort()).toEqual(
      [
        'getSessionStatus',
        'startSession',
        'stopSession',
        'restartSession',
        'logoutSession',
        'getQr',
        'requestPairingCode',
        'sendText',
      ].sort(),
    );
  });

  it('never includes delete/create/update session endpoints', () => {
    const paths = Object.values(WAHA_ALLOWED_ENDPOINTS).map((e) => e.path('test_session'));
    for (const path of paths) {
      expect(path).not.toMatch(/\/sessions\/?$/);
    }
  });

  it('builds the exact documented path for each endpoint', () => {
    expect(WAHA_ALLOWED_ENDPOINTS.getSessionStatus.path('test_session')).toBe('/api/sessions/test_session');
    expect(WAHA_ALLOWED_ENDPOINTS.startSession.path('test_session')).toBe('/api/sessions/test_session/start');
    expect(WAHA_ALLOWED_ENDPOINTS.stopSession.path('test_session')).toBe('/api/sessions/test_session/stop');
    expect(WAHA_ALLOWED_ENDPOINTS.restartSession.path('test_session')).toBe('/api/sessions/test_session/restart');
    expect(WAHA_ALLOWED_ENDPOINTS.logoutSession.path('test_session')).toBe('/api/sessions/test_session/logout');
    expect(WAHA_ALLOWED_ENDPOINTS.getQr.path('test_session')).toBe('/api/test_session/auth/qr');
    expect(WAHA_ALLOWED_ENDPOINTS.requestPairingCode.path('test_session')).toBe(
      '/api/test_session/auth/request-code',
    );
    expect(WAHA_ALLOWED_ENDPOINTS.sendText.path('test_session')).toBe('/api/sendText');
  });

  it('URL-encodes the session name to prevent path injection', () => {
    expect(WAHA_ALLOWED_ENDPOINTS.getSessionStatus.path('../../etc/passwd')).not.toContain('../');
  });
});
