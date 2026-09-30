import { Building2 } from 'lucide-react';

import { useAdminData } from '../lib/useAdminData';
import { AdminPageGate } from './AdminPageGate';
import { SettingsOfficesPanel } from './SettingsOfficesPanel';

// Route for the Settings submenu's "Offices" item (formerly the Offices
// tab of the now-removed tabbed SettingsPage.tsx).
export function SettingsOfficesPage() {
  const { meQuery, officesQuery } = useAdminData();
  return (
    <AdminPageGate
      title="Settings — Offices"
      description="Manage Offices."
      icon={Building2}
      meQuery={meQuery}
      allowed={(me) => me.has_global_access}
      deniedNote="Office management is available to Superadmin and Global Admin accounts."
    >
      {() => <SettingsOfficesPanel offices={officesQuery} refetch={officesQuery.refetch} />}
    </AdminPageGate>
  );
}
