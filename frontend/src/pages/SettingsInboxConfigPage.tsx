import { Inbox } from 'lucide-react';

import { useAdminData } from '../lib/useAdminData';
import { AdminPageGate } from './AdminPageGate';
import { SettingsInboxConfigPanel } from './SettingsInboxConfigPanel';

// Route for the Settings submenu's "Inbox Configuration" item.
export function SettingsInboxConfigPage() {
  const { meQuery, officesQuery } = useAdminData();
  return (
    <AdminPageGate
      title="Settings — Inbox Configuration"
      description="Configure per-Office Inbox handoff behavior."
      icon={Inbox}
      meQuery={meQuery}
      allowed={(me) => me.has_global_access || (me.role?.is_office_admin ?? false)}
      deniedNote="Inbox Configuration is available to Superadmin, Global Admin, and Office Admin accounts."
    >
      {(me) => <SettingsInboxConfigPanel me={me} offices={officesQuery.status === 'success' ? officesQuery.data : []} />}
    </AdminPageGate>
  );
}
