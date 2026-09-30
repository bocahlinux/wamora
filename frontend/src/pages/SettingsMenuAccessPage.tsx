import { LayoutGrid } from 'lucide-react';

import { useAdminData } from '../lib/useAdminData';
import { AdminPageGate } from './AdminPageGate';
import { SettingsMenuAccessPanel } from './SettingsMenuAccessPanel';

// Route for the Settings submenu's "Menu Access" item (new — Discussed
// requirement). Superuser-only, same sensitivity as Manage Users > Roles.
export function SettingsMenuAccessPage() {
  const { meQuery, rolesQuery } = useAdminData();
  return (
    <AdminPageGate
      title="Settings — Menu Access"
      description="Control which sidebar menu items are visible per Role."
      icon={LayoutGrid}
      meQuery={meQuery}
      allowed={(me) => me.is_superuser}
      deniedNote="Menu Access is available to Superadmin accounts only."
    >
      {() => <SettingsMenuAccessPanel roles={rolesQuery} />}
    </AdminPageGate>
  );
}
