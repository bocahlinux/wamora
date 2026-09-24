import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

import { AppShell } from '../components/layout/AppShell';
import { useAuth } from '../lib/AuthContext';

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <AppShell>{children}</AppShell>;
}
