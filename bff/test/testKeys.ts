// Ephemeral RSA key pair generation for tests only — mirrors
// backend/apps/authn/tests/keys.py. Never written to disk, never
// committed.

import { generateKeyPairSync } from 'crypto';

export function generateTestKeyPair(): { privateKey: string; publicKey: string } {
  const { privateKey, publicKey } = generateKeyPairSync('rsa', {
    modulusLength: 2048,
    privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
    publicKeyEncoding: { type: 'spki', format: 'pem' },
  });
  return { privateKey, publicKey };
}
