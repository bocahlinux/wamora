// Phase 6 authentication contract —
// docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md Section 4:
// Django issues an RS256 JWT via POST /api/auth/login/, an 8-hour
// single access token, no refresh mechanism in v1. This module implements
// exactly that — no second authentication scheme is invented, no refresh
// endpoint is called (none exists).

import { request } from './api';
import { config } from './config';

const STORAGE_KEY = 'wamora.access_token';

export interface LoginSuccess {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface JwtClaims {
  sub: string;
  iss: string;
  aud: string;
  iat: number;
  exp: number;
  scopes: string[];
}

/** sessionStorage, not localStorage — an access token is a bearer
 * credential; sessionStorage at least scopes it to the tab/session
 * lifetime rather than persisting indefinitely (docs/generated/PHASE-6-ARCHITECTURE-CONTRACT.md
 * Section 10's own reasoning: "avoid localStorage for anything
 * long-lived, due to XSS exposure"). Still readable by any script on the
 * page (no storage mechanism the browser offers is immune to XSS) —
 * mitigated by keeping the token's own lifetime short (8h, per contract). */
export function storeToken(token: string): void {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, token);
  } catch {
    // Storage unavailable — the user simply won't stay logged in across
    // a reload; not a hard failure.
  }
}

export function getToken(): string | null {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function clearToken(): void {
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to do.
  }
}

/** Decodes the JWT payload for UI purposes only (e.g. showing the
 * signed-in username, hiding nav items the token's scopes don't cover).
 * This is NOT verification — the BFF/Django independently verify the
 * signature on every request; the frontend must never make a security
 * decision based on this decoded value alone. */
export function decodeToken(token: string): JwtClaims | null {
  try {
    const [, payload] = token.split('.');
    if (!payload) return null;
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(json) as JwtClaims;
  } catch {
    return null;
  }
}

export function isExpired(claims: JwtClaims): boolean {
  return Date.now() >= claims.exp * 1000;
}

export async function login(username: string, password: string) {
  return request<LoginSuccess>(`${config.djangoBaseUrl}/api/auth/login/`, {
    method: 'POST',
    body: { username, password },
  });
}

export function authHeader(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}
