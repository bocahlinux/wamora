import { ShieldCheck } from 'lucide-react';

import { useAdminData } from '../lib/useAdminData';
import { AdminPageGate } from './AdminPageGate';
import { SettingsRolesPanel } from './SettingsRolesPanel';

// Route for the Manage Users submenu's "Roles" item (formerly the Roles
// tab of the now-removed tabbed SettingsPage.tsx) — Superadmin-only,
// unchanged from before.
export function ManageUsersRolesPage() {
  const { meQuery, rolesQuery } = useAdminData();
  return (
    <AdminPageGate
      title="Manage Users — Roles"
      description="Define Roles: feature/menu access and organizational standing."
      icon={ShieldCheck}
      meQuery={meQuery}
      allowed={(me) => me.is_superuser}
      deniedNote="Roles are available to Superadmin accounts only."
    >
      {() => <SettingsRolesPanel roles={rolesQuery} />}
    </AdminPageGate>
  );
}
