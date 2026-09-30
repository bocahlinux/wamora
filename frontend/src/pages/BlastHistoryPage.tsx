import { ErrorState } from '../components/ui/ErrorState';
import { PageHeader } from '../components/ui/PageHeader';
import { useBlastAdminAccess } from '../lib/useBlastAdminAccess';
import { BlastHistoryPanel } from './BlastHistoryPanel';

// Route for the Blast sidebar submenu's "History" item.
export function BlastHistoryPage() {
  const { hasGlobalAccess, officeChoices, officesQuery } = useBlastAdminAccess();

  return (
    <div>
      <PageHeader title="Blast — History" description="Every recipient outcome across every campaign — dashboard or external API." />
      {officesQuery.status === 'error' ? (
        <ErrorState error={officesQuery.error} onRetry={officesQuery.refetch} />
      ) : (
        <BlastHistoryPanel hasGlobalAccess={hasGlobalAccess} officeChoices={officeChoices} />
      )}
    </div>
  );
}
