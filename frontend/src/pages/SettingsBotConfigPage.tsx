import { Bot } from 'lucide-react';

import { useAdminData } from '../lib/useAdminData';
import { AdminPageGate } from './AdminPageGate';
import { SettingsBotConfigPanel } from './SettingsBotConfigPanel';

// Route for the Settings submenu's "Bot Configuration" item.
export function SettingsBotConfigPage() {
  const { meQuery } = useAdminData();
  return (
    <AdminPageGate
      title="Settings — Bot Configuration"
      description="Configure the automated Conversation/Bot Engine."
      icon={Bot}
      meQuery={meQuery}
      allowed={(me) => me.has_global_access}
      deniedNote="Bot Configuration is available to Superadmin and Global Admin accounts."
    >
      {() => <SettingsBotConfigPanel />}
    </AdminPageGate>
  );
}
