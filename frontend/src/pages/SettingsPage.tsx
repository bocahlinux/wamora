import { useState } from 'react';
import { Settings } from 'lucide-react';

import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import { PageHeader } from '../components/ui/PageHeader';
import { getMe, getOffices, getRoles, getUsers, type Me } from '../lib/djangoApi';
import { useApiQuery } from '../lib/useApiQuery';
import { PlaceholderPage } from './PlaceholderPage';
import { SettingsBotConfigPanel } from './SettingsBotConfigPanel';
import { SettingsInboxConfigPanel } from './SettingsInboxConfigPanel';
import { SettingsOfficesPanel } from './SettingsOfficesPanel';
import { SettingsRolesPanel } from './SettingsRolesPanel';
import { SettingsUsersPanel } from './SettingsUsersPanel';
import './SettingsPage.css';

type Tab = 'offices' | 'users' | 'inbox-config' | 'roles' | 'bot-config';

// Step 6 (Office & User management) — the only functional Settings
// content so far; anything else stays the same "not yet available"
// placeholder it always was. Gated on GET /api/auth/me/'s
// `has_global_access`/`role` (Superadmin/Global Admin see both Offices
// and Users; an Office Admin sees Users only — they never manage
// Offices themselves, per apps/offices/views.py's own authorization).
// The backend enforces this regardless; hiding the UI here is purely
// so a non-admin never sees management controls that would just 403.
export function SettingsPage() {
  const meQuery = useApiQuery(() => getMe(), []);

  if (meQuery.status === 'loading') {
    return (
      <div>
        <PageHeader title="Settings" description="Application and account settings." />
        <LoadingState label="Loading…" />
      </div>
    );
  }
  if (meQuery.status === 'error') {
    return (
      <div>
        <PageHeader title="Settings" description="Application and account settings." />
        <ErrorState error={meQuery.error} onRetry={meQuery.refetch} />
      </div>
    );
  }

  const me = meQuery.data;
  const canAdminister = me.has_global_access || (me.role?.is_office_admin ?? false);

  if (!canAdminister) {
    return (
      <PlaceholderPage
        title="Settings"
        icon={Settings}
        description="Application and account settings."
        dependencyNote="Office and User management is available to Superadmin, Global Admin, and Office Admin accounts."
      />
    );
  }

  return <AdministrationSettings hasGlobalAccess={me.has_global_access} me={me} />;
}

function AdministrationSettings({ hasGlobalAccess, me }: { hasGlobalAccess: boolean; me: Me }) {
  const [tab, setTab] = useState<Tab>(hasGlobalAccess ? 'offices' : 'users');
  const officesQuery = useApiQuery(() => getOffices(), []);
  const usersQuery = useApiQuery(() => getUsers(), []);
  // Roles CRUD (`/api/roles/`) is Superuser-only server-side
  // (`IsSuperuser`) — not even Global Admin reaches it, so this tab (and
  // its query result) is gated on `me.is_superuser` specifically below,
  // same "always fetch, gate the render" pattern `officesQuery` above
  // already uses for a non-globally-accessing Office Admin.
  const rolesQuery = useApiQuery(() => getRoles(), []);

  return (
    <div>
      <PageHeader title="Settings" description="Manage Offices and Users." />

      <div className="wa-settings-tabs" role="tablist" aria-label="Settings sections">
        {hasGlobalAccess ? (
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'offices'}
            className={['wa-settings-tab', tab === 'offices' ? 'wa-settings-tab--active' : ''].filter(Boolean).join(' ')}
            onClick={() => setTab('offices')}
          >
            Offices
          </button>
        ) : null}
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'users'}
          className={['wa-settings-tab', tab === 'users' ? 'wa-settings-tab--active' : ''].filter(Boolean).join(' ')}
          onClick={() => setTab('users')}
        >
          Users
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'inbox-config'}
          className={['wa-settings-tab', tab === 'inbox-config' ? 'wa-settings-tab--active' : ''].filter(Boolean).join(' ')}
          onClick={() => setTab('inbox-config')}
        >
          Inbox Configuration
        </button>
        {hasGlobalAccess ? (
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'bot-config'}
            className={['wa-settings-tab', tab === 'bot-config' ? 'wa-settings-tab--active' : ''].filter(Boolean).join(' ')}
            onClick={() => setTab('bot-config')}
          >
            Bot Configuration
          </button>
        ) : null}
        {me.is_superuser ? (
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'roles'}
            className={['wa-settings-tab', tab === 'roles' ? 'wa-settings-tab--active' : ''].filter(Boolean).join(' ')}
            onClick={() => setTab('roles')}
          >
            Roles
          </button>
        ) : null}
      </div>

      {tab === 'offices' && hasGlobalAccess ? (
        <SettingsOfficesPanel offices={officesQuery} refetch={officesQuery.refetch} />
      ) : null}

      {tab === 'users' ? (
        officesQuery.status === 'error' && hasGlobalAccess ? (
          <ErrorState error={officesQuery.error} onRetry={officesQuery.refetch} />
        ) : (
          <SettingsUsersPanel
            me={me}
            users={usersQuery}
            offices={officesQuery.status === 'success' ? officesQuery.data : []}
            // Only a globally-accessing actor can assign a Role at all
            // (backend 403s an Office Admin who even sends the field) —
            // reuses the same rolesQuery this page already fetches for
            // the Roles tab, rather than a second /api/roles/ call.
            roles={hasGlobalAccess && rolesQuery.status === 'success' ? rolesQuery.data : []}
          />
        )
      ) : null}

      {tab === 'inbox-config' ? (
        officesQuery.status === 'error' && hasGlobalAccess ? (
          <ErrorState error={officesQuery.error} onRetry={officesQuery.refetch} />
        ) : (
          <SettingsInboxConfigPanel me={me} offices={officesQuery.status === 'success' ? officesQuery.data : []} />
        )
      ) : null}

      {tab === 'bot-config' && hasGlobalAccess ? <SettingsBotConfigPanel /> : null}

      {tab === 'roles' && me.is_superuser ? <SettingsRolesPanel roles={rolesQuery} /> : null}
    </div>
  );
}
