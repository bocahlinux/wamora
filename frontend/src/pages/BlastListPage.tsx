import { Megaphone, Plus } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import { PageHeader } from '../components/ui/PageHeader';
import { mapBlastCampaignStatus, StatusBadge } from '../components/ui/StatusBadge';
import type { BlastCampaignListItem, BlastCampaignStatus } from '../lib/djangoApi';
import { getBlastCampaigns } from '../lib/djangoApi';
import { useApiQuery } from '../lib/useApiQuery';
import { useAuth } from '../lib/AuthContext';
import './BlastPage.css';

// Phase 11 Blast — backend/apps/blast/views.py's own module docstring:
// creating a campaign requires the 'blast' scope (HasBlastScope); reading
// the list/detail is 'blast' OR 'system administration'. Reusing the exact
// same inline claims-check idiom InboxPage.tsx already established for its
// "system administration"-gated recovery button — no new scope-checking
// utility (task requirement).
const BLAST_SCOPE = 'blast';

const BLAST_STATUS_LABEL: Record<BlastCampaignStatus, string> = {
  draft: 'Draft',
  pending_approval: 'Pending approval',
  approved: 'Approved',
  sending: 'Sending',
  completed: 'Completed',
  rejected: 'Rejected',
  failed: 'Failed',
};

function campaignMeta(campaign: BlastCampaignListItem): string {
  const recipients = `${campaign.recipient_count} recipient${campaign.recipient_count === 1 ? '' : 's'}`;
  return `${campaign.session} · ${recipients} · by ${campaign.created_by}`;
}

// GET /api/blast/campaigns/ (backend/apps/blast/views.py
// BlastCampaignListCreateView.get) returns every campaign, newest-first,
// with no pagination envelope (unlike GET /api/chats/) — this list is
// rendered in full, no page param, matching what the endpoint actually
// returns (serializers.py:70-84's BlastCampaignListSerializer fields).
export function BlastListPage() {
  const { claims } = useAuth();
  const canCreate = claims?.scopes.includes(BLAST_SCOPE) ?? false;
  const navigate = useNavigate();
  const query = useApiQuery(() => getBlastCampaigns(), []);

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

      {query.status === 'loading' ? (
        <LoadingState label="Loading campaigns…" />
      ) : query.status === 'error' ? (
        <ErrorState error={query.error} onRetry={query.refetch} />
      ) : query.data.length === 0 ? (
        <EmptyState
          icon={Megaphone}
          title="No campaigns yet"
          description="Blast campaigns you create or that need approval will appear here."
          action={
            canCreate ? (
              <Button variant="primary" onClick={() => navigate('/blast/new')}>
                <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
                New campaign
              </Button>
            ) : undefined
          }
        />
      ) : (
        <Card>
          <ul className="wa-blast-list">
            {query.data.map((campaign) => (
              <li key={campaign.id}>
                <Link to={`/blast/${campaign.id}`} className="wa-blast-list__row">
                  <div className="wa-blast-list__main">
                    <p className="wa-blast-list__name">{campaign.name}</p>
                    <p className="wa-blast-list__meta">{campaignMeta(campaign)}</p>
                  </div>
                  <div className="wa-blast-list__side">
                    <StatusBadge
                      status={mapBlastCampaignStatus(campaign.status)}
                      label={BLAST_STATUS_LABEL[campaign.status]}
                    />
                    <span className="wa-blast-list__date">{new Date(campaign.created_at).toLocaleString()}</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
