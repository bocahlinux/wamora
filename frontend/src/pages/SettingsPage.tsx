import { Settings } from 'lucide-react';

import { PlaceholderPage } from './PlaceholderPage';

// No settings/user-administration API exists yet (that's Phase 6's named
// "user administration"/"system administration" scopes, not yet backed
// by any endpoint) — not assigned to Phase 7.
export function SettingsPage() {
  return (
    <PlaceholderPage
      title="Settings"
      icon={Settings}
      description="Application and account settings."
      dependencyNote="Settings has no backing API yet in any coding phase completed so far."
    />
  );
}
