import jsonwebtoken from 'jsonwebtoken';
import { describe, expect, it } from 'vitest';

import { JwtVerificationError, verifyToken } from '../src/jwt';
import { generateTestKeyPair } from './testKeys';

const { privateKey, publicKey } = generateTestKeyPair();
const ISSUER = 'test-issuer';
const AUDIENCE = 'test-audience';

function sign(overrides: Record<string, unknown> = {}, opts: jsonwebtoken.SignOptions = {}) {
  return jsonwebtoken.sign(
    { sub: '1', scopes: ['reading'], ...overrides },
    privateKey,
    { algorithm: 'RS256', issuer: ISSUER, audience: AUDIENCE, expiresIn: '1h', ...opts },
  );
}

describe('verifyToken', () => {
  it('accepts a validly-signed token and returns its claims', () => {
    const token = sign();
    const claims = verifyToken(token, { publicKey, issuer: ISSUER, audience: AUDIENCE });
    expect(claims.sub).toBe('1');
    expect(claims.scopes).toEqual(['reading']);
    expect(claims.iss).toBe(ISSUER);
    expect(claims.aud).toBe(AUDIENCE);
  });

  it('rejects an expired token', () => {
    const token = sign({}, { expiresIn: '-1h' });
    expect(() => verifyToken(token, { publicKey, issuer: ISSUER, audience: AUDIENCE })).toThrow(
      JwtVerificationError,
    );
  });

  it('rejects a token with the wrong issuer', () => {
    const token = sign({}, { issuer: 'someone-else' });
    expect(() => verifyToken(token, { publicKey, issuer: ISSUER, audience: AUDIENCE })).toThrow(
      JwtVerificationError,
    );
  });

  it('rejects a token with the wrong audience', () => {
    const token = sign({}, { audience: 'someone-else' });
    expect(() => verifyToken(token, { publicKey, issuer: ISSUER, audience: AUDIENCE })).toThrow(
      JwtVerificationError,
    );
  });

  it('rejects a token signed with a different key pair (invalid signature)', () => {
    const other = generateTestKeyPair();
    const token = jsonwebtoken.sign({ sub: '1', scopes: [] }, other.privateKey, {
      algorithm: 'RS256',
      issuer: ISSUER,
      audience: AUDIENCE,
      expiresIn: '1h',
    });
    expect(() => verifyToken(token, { publicKey, issuer: ISSUER, audience: AUDIENCE })).toThrow(
      JwtVerificationError,
    );
  });

  it('rejects an HS256-signed token even if it happens to carry the right claims (algorithm confusion)', () => {
    const token = jsonwebtoken.sign({ sub: '1', scopes: [] }, publicKey, {
      algorithm: 'HS256',
      issuer: ISSUER,
      audience: AUDIENCE,
      expiresIn: '1h',
    });
    expect(() => verifyToken(token, { publicKey, issuer: ISSUER, audience: AUDIENCE })).toThrow(
      JwtVerificationError,
    );
  });

  it('rejects garbage input', () => {
    expect(() => verifyToken('not-a-jwt', { publicKey, issuer: ISSUER, audience: AUDIENCE })).toThrow(
      JwtVerificationError,
    );
  });

  it('throws when no public key is configured', () => {
    expect(() => verifyToken(sign(), { publicKey: '', issuer: ISSUER, audience: AUDIENCE })).toThrow(
      JwtVerificationError,
    );
  });

  it('defaults missing/non-array scopes to an empty array', () => {
    const token = sign({ scopes: undefined });
    const claims = verifyToken(token, { publicKey, issuer: ISSUER, audience: AUDIENCE });
    expect(claims.scopes).toEqual([]);
  });

  // v1 documented behavior (docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md
  // Section 4, corrected after the post-implementation audit): verification
  // uses exactly one statically-configured public key. `kid` is present in
  // issued tokens for forward compatibility only — it is never read here,
  // so a token is accepted purely on a valid signature against that single
  // key, regardless of what `kid` says.
  it('verifies successfully regardless of the token header kid value (v1: no key lookup by kid)', () => {
    const token = jsonwebtoken.sign({ sub: '1', scopes: [] }, privateKey, {
      algorithm: 'RS256',
      issuer: ISSUER,
      audience: AUDIENCE,
      expiresIn: '1h',
      keyid: 'some-other-key-id-the-bff-has-never-heard-of',
    });
    const claims = verifyToken(token, { publicKey, issuer: ISSUER, audience: AUDIENCE });
    expect(claims.sub).toBe('1');
  });

  it('verifies successfully when the token has no kid header at all', () => {
    const token = jsonwebtoken.sign({ sub: '1', scopes: [] }, privateKey, {
      algorithm: 'RS256',
      issuer: ISSUER,
      audience: AUDIENCE,
      expiresIn: '1h',
    });
    expect(jsonwebtoken.decode(token, { complete: true })?.header.kid).toBeUndefined();
    const claims = verifyToken(token, { publicKey, issuer: ISSUER, audience: AUDIENCE });
    expect(claims.sub).toBe('1');
  });
});
