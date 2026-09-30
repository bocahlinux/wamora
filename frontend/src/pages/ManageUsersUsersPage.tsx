import { Users } from 'lucide-react';

import { useAdminData } from '../lib/useAdminData';
import { AdminPageGate } from './AdminPageGate';
import { SettingsUsersPanel } from './SettingsUsersPanel';

// Route for the Manage Users submenu's "Users" item (formerly the Users
// tab of the now-removed tabbed SettingsPage.tsx) — now its own
// top-level sidebar section rather than living under Settings.
export function ManageUsersUsersPage() {
  const { meQuery, officesQuery, rolesQuery } = useAdminData();
  const hasGlobalAccess = meQuery.status === 'success' && meQuery.data.has_global_access;

  return (
    <AdminPageGate
      title="Manage Users — Users"
      description="Create and manage user accounts."
      icon={Users}
      meQuery={meQuery}
      allowed={(me) => me.has_global_access || (me.role?.is_office_admin ?? false)}
      deniedNote="User management is available to Superadmin, Global Admin, and Office Admin accounts."
    >
      {(me) => (
        <SettingsUsersPanel
          me={me}
          offices={officesQuery.status === 'success' ? officesQuery.data : []}
          // Only a globally-accessing actor can assign a Role at all
          // (backend 403s an Office Admin who even sends the field).
          roles={hasGlobalAccess && rolesQuery.status === 'success' ? rolesQuery.data : []}
        />
      )}
    </AdminPageGate>
  );
}
