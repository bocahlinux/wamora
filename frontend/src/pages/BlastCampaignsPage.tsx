import { Plus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { Button } from '../components/ui/Button';
import { PageHeader } from '../components/ui/PageHeader';
import { useAuth } from '../lib/AuthContext';
import { BlastListPage } from './BlastListPage';

const BLAST_SCOPE = 'blast';

// Route for the Blast sidebar submenu's "Campaigns" item (previously the
// Campaigns tab of the now-removed BlastPage.tsx tabbed wrapper) — owns
// the section's PageHeader; BlastListPage.tsx itself renders only the
// toolbar/table/empty states, so there is exactly one header per page.
export function BlastCampaignsPage() {
  const { claims } = useAuth();
  const navigate = useNavigate();
  const canCreate = claims?.scopes.includes(BLAST_SCOPE) ?? false;

  return (
    <div>
      <PageHeader
        title="Blast"
        description="Controlled bulk WhatsApp campaigns — draft, submit for approval, and track dispatch."
        actions={
          canCreate ? (
            <Button variant="primary" onClick={() => navigate('/blast/new')}>
              <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
              New campaign
            </Button>
          ) : null
        }
      />
      <BlastListPage />
    </div>
  );
}
