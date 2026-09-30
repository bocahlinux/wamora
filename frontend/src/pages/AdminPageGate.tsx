import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import { PageHeader } from '../components/ui/PageHeader';
import type { Me } from '../lib/djangoApi';
import type { QueryState } from '../lib/useApiQuery';
import { PlaceholderPage } from './PlaceholderPage';

interface AdminPageGateProps {
  title: string;
  description: string;
  icon: LucideIcon;
  meQuery: QueryState<Me> & { refetch: () => void };
  allowed: (me: Me) => boolean;
  deniedNote: string;
  children: (me: Me) => ReactNode;
}

// Shared loading/error/not-allowed shell for every Settings/Manage Users
// page (each now its own route) — the exact same loading/error/gate
// boilerplate the original tabbed SettingsPage.tsx applied once for the
// whole section, factored out so 7+ pages don't each hand-roll it.
export function AdminPageGate({ title, description, icon, meQuery, allowed, deniedNote, children }: AdminPageGateProps) {
  if (meQuery.status === 'loading') {
    return (
      <div>
        <PageHeader title={title} description={description} />
        <LoadingState label="Loading…" />
      </div>
    );
  }
  if (meQuery.status === 'error') {
    return (
      <div>
        <PageHeader title={title} description={description} />
        <ErrorState error={meQuery.error} onRetry={meQuery.refetch} />
      </div>
    );
  }
  if (!allowed(meQuery.data)) {
    return <PlaceholderPage title={title} icon={icon} description={description} dependencyNote={deniedNote} />;
  }
  return (
    <div>
      <PageHeader title={title} description={description} />
      {children(meQuery.data)}
    </div>
  );
}
