// JWT verification — docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md
// Section 4. The BFF only ever verifies (never issues) a token, using the
// public half of Django's RS256 key pair. No live call to Django is made
// here — that's the entire point of this design (Section 9's Availability
// boundary: already-issued tokens keep verifying even if Django is down).
//
// v1 behavior, stated explicitly: verification uses exactly ONE
// statically-configured public key (VerifyOptions.publicKey). Issued
// tokens do carry a `kid` header (apps/authn/jwt_utils.py), but this
// module does not read it and performs no key lookup/selection — there is
// no key registry, no multi-key set, no JWKS endpoint. `kid`'s only
// purpose today is forward compatibility (so a future multi-key rotation
// mechanism, if built, has something to key off of); it is inert until
// that mechanism actually exists. Do not assume rotation support from its
// presence in a token.

import jwt from 'jsonwebtoken';

export interface JwtClaims {
  sub: string;
  iss: string;
  aud: string;
  iat: number;
  exp: number;
  scopes: string[];
}

export class JwtVerificationError extends Error {}

export interface VerifyOptions {
  publicKey: string;
  issuer: string;
  audience: string;
}

/** Throws JwtVerificationError for any invalid/expired/wrong-audience/
 * wrong-issuer/wrong-algorithm token — callers map this to 401, never leak
 * the underlying library error text (docs/06-SECURITY.md log redaction). */
export function verifyToken(token: string, options: VerifyOptions): JwtClaims {
  if (!options.publicKey) {
    throw new JwtVerificationError('JWT public key is not configured');
  }
  try {
    const decoded = jwt.verify(token, options.publicKey, {
      algorithms: ['RS256'],
      issuer: options.issuer,
      audience: options.audience,
    });
    if (typeof decoded === 'string') {
      throw new JwtVerificationError('Unexpected token payload shape');
    }
    const scopes = Array.isArray(decoded.scopes) ? (decoded.scopes as string[]) : [];
    return {
      sub: String(decoded.sub),
      iss: String(decoded.iss),
      aud: String(decoded.aud),
      iat: Number(decoded.iat),
      exp: Number(decoded.exp),
      scopes,
    };
  } catch (err) {
    if (err instanceof JwtVerificationError) {
      throw err;
    }
    throw new JwtVerificationError(err instanceof Error ? err.message : 'Invalid token');
  }
}
