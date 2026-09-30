import { ErrorState } from '../components/ui/ErrorState';
import { PageHeader } from '../components/ui/PageHeader';
import { useBlastAdminAccess } from '../lib/useBlastAdminAccess';
import { BlastTemplatesPanel } from './BlastTemplatesPanel';

// Route for the Blast sidebar submenu's "Templates" item.
export function BlastTemplatesPage() {
  const { hasGlobalAccess, officeChoices, officesQuery } = useBlastAdminAccess();

  return (
    <div>
      <PageHeader title="Blast — Templates" description="Reusable message shapes with per-recipient {{variables}}." />
      {officesQuery.status === 'error' ? (
        <ErrorState error={officesQuery.error} onRetry={officesQuery.refetch} />
      ) : (
        <BlastTemplatesPanel hasGlobalAccess={hasGlobalAccess} officeChoices={officeChoices} />
      )}
    </div>
  );
}
