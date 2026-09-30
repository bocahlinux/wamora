import { Navigate, Route, Routes } from 'react-router-dom';

import { BlastCampaignsPage } from '../pages/BlastCampaignsPage';
import { BlastCreatePage } from '../pages/BlastCreatePage';
import { BlastDetailPage } from '../pages/BlastDetailPage';
import { BlastHistoryPage } from '../pages/BlastHistoryPage';
import { BlastTemplatesPage } from '../pages/BlastTemplatesPage';
import { DashboardPage } from '../pages/DashboardPage';
import { InboxPage } from '../pages/InboxPage';
import { LoginPage } from '../pages/LoginPage';
import { ManageUsersRolesPage } from '../pages/ManageUsersRolesPage';
import { ManageUsersUsersPage } from '../pages/ManageUsersUsersPage';
import { NotFoundPage } from '../pages/NotFoundPage';
import { ProfilePage } from '../pages/ProfilePage';
import { ReportsPage } from '../pages/ReportsPage';
import { SessionsPage } from '../pages/SessionsPage';
import { SettingsBlastApiPage } from '../pages/SettingsBlastApiPage';
import { SettingsBotConfigPage } from '../pages/SettingsBotConfigPage';
import { SettingsInboxConfigPage } from '../pages/SettingsInboxConfigPage';
import { SettingsMenuAccessPage } from '../pages/SettingsMenuAccessPage';
import { SettingsOfficesPage } from '../pages/SettingsOfficesPage';
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
      <Route path="/blast" element={<Navigate to="/blast/campaigns" replace />} />
      <Route
        path="/blast/campaigns"
        element={
          <ProtectedRoute>
            <BlastCampaignsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/blast/templates"
        element={
          <ProtectedRoute>
            <BlastTemplatesPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/blast/history"
        element={
          <ProtectedRoute>
            <BlastHistoryPage />
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
      <Route path="/reports" element={<ProtectedRoute><ReportsPage /></ProtectedRoute>} />

      {/* Discussed requirement — "Manage Users" is now its own top-level
          sidebar section (Users/Roles), separate from Settings. */}
      <Route path="/manage-users" element={<Navigate to="/manage-users/users" replace />} />
      <Route
        path="/manage-users/users"
        element={
          <ProtectedRoute>
            <ManageUsersUsersPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/manage-users/roles"
        element={
          <ProtectedRoute>
            <ManageUsersRolesPage />
          </ProtectedRoute>
        }
      />

      {/* Discussed requirement — Settings is now a submenu (Offices/
          Inbox Configuration/Bot Configuration/Blast API/Menu Access)
          instead of one tabbed page; Users/Roles moved to Manage Users
          above. */}
      <Route path="/settings" element={<Navigate to="/settings/offices" replace />} />
      <Route
        path="/settings/offices"
        element={
          <ProtectedRoute>
            <SettingsOfficesPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/inbox-config"
        element={
          <ProtectedRoute>
            <SettingsInboxConfigPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/bot-config"
        element={
          <ProtectedRoute>
            <SettingsBotConfigPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/blast-api"
        element={
          <ProtectedRoute>
            <SettingsBlastApiPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/settings/menu-access"
        element={
          <ProtectedRoute>
            <SettingsMenuAccessPage />
          </ProtectedRoute>
        }
      />

      <Route
        path="/profile"
        element={
          <ProtectedRoute>
            <ProfilePage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
