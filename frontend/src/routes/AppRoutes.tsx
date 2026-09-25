import { Route, Routes } from 'react-router-dom';

import { BlastCreatePage } from '../pages/BlastCreatePage';
import { BlastDetailPage } from '../pages/BlastDetailPage';
import { BlastListPage } from '../pages/BlastListPage';
import { DashboardPage } from '../pages/DashboardPage';
import { InboxPage } from '../pages/InboxPage';
import { LoginPage } from '../pages/LoginPage';
import { NotFoundPage } from '../pages/NotFoundPage';
import { ReportsPage } from '../pages/ReportsPage';
import { SessionsPage } from '../pages/SessionsPage';
import { SettingsPage } from '../pages/SettingsPage';
import { WhatsAppPage } from '../pages/WhatsAppPage';
import { ProtectedRoute } from './ProtectedRoute';

// Routes assigned to Phase 7 only (task Section 10) — no route exists for
// functionality belonging to a later phase beyond a placeholder shell,
// per docs/15-CODING-PHASES.md's phase boundaries.
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <DashboardPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/whatsapp"
        element={
          <ProtectedRoute>
            <WhatsAppPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/inbox"
        element={
          <ProtectedRoute>
            <InboxPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/sessions"
        element={
          <ProtectedRoute>
            <SessionsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/blast"
        element={
          <ProtectedRoute>
            <BlastListPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/blast/new"
        element={
          <ProtectedRoute>
            <BlastCreatePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/blast/:id"
        element={
          <ProtectedRoute>
            <BlastDetailPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/reports"
        element={
          <ProtectedRoute>
            <ReportsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings"
        element={
          <ProtectedRoute>
            <SettingsPage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
