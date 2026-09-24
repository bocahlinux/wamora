import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import type { ApiError } from './api';
import { clearToken, decodeToken, getToken, isExpired, login as loginRequest, storeToken, type JwtClaims } from './auth';

interface AuthContextValue {
  isAuthenticated: boolean;
  claims: JwtClaims | null;
  login: (username: string, password: string) => Promise<{ ok: true } | { ok: false; error: ApiError }>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function readValidClaims(): JwtClaims | null {
  const token = getToken();
  if (!token) return null;
  const claims = decodeToken(token);
  if (!claims || isExpired(claims)) {
    clearToken();
    return null;
  }
  return claims;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [claims, setClaims] = useState<JwtClaims | null>(readValidClaims);

  // The 8-hour access token has no refresh mechanism in v1 (contract
  // Section 4) — once it expires, the UI must treat the user as signed
  // out rather than silently keep sending a stale token.
  useEffect(() => {
    if (!claims) return;
    const msUntilExpiry = claims.exp * 1000 - Date.now();
    if (msUntilExpiry <= 0) {
      setClaims(null);
      return;
    }
    const timer = window.setTimeout(() => {
      clearToken();
      setClaims(null);
    }, msUntilExpiry);
    return () => window.clearTimeout(timer);
  }, [claims]);

  const login = useCallback(async (username: string, password: string) => {
    const result = await loginRequest(username, password);
    if (!result.ok) {
      return { ok: false as const, error: result.error };
    }
    storeToken(result.data.access_token);
    const decoded = decodeToken(result.data.access_token);
    setClaims(decoded);
    return { ok: true as const };
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setClaims(null);
  }, []);

  const value = useMemo(
    () => ({ isAuthenticated: claims !== null, claims, login, logout }),
    [claims, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
