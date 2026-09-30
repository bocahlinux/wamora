import { Key } from 'lucide-react';

import { useAdminData } from '../lib/useAdminData';
import { AdminPageGate } from './AdminPageGate';
import { SettingsBlastApiPanel } from './SettingsBlastApiPanel';

// Route for the Settings submenu's "Blast API" item.
export function SettingsBlastApiPage() {
  const { meQuery } = useAdminData();
  return (
    <AdminPageGate
      title="Settings — Blast API"
      description="External Blast-trigger API keys and the dynamic inter-message delay."
      icon={Key}
      meQuery={meQuery}
      allowed={(me) => me.has_global_access}
      deniedNote="Blast API settings are available to Superadmin and Global Admin accounts."
    >
      {() => <SettingsBlastApiPanel />}
    </AdminPageGate>
  );
}
