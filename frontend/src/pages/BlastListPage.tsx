import { useMemo, useState } from 'react';
import { Megaphone, Plus, Search, X } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';

import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import { mapBlastCampaignStatus, StatusBadge } from '../components/ui/StatusBadge';
import type { BlastCampaignStatus } from '../lib/djangoApi';
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

const BLAST_STATUS_OPTIONS = Object.keys(BLAST_STATUS_LABEL) as BlastCampaignStatus[];

// GET /api/blast/campaigns/ (backend/apps/blast/views.py
// BlastCampaignListCreateView.get) returns every campaign, newest-first,
// with no pagination envelope (unlike GET /api/chats/) — search/status
// filter below are plain client-side, same reasoning as
// SettingsOfficesPanel/SettingsRolesPanel's own unpaginated tables.
export function BlastListPage() {
  const { claims } = useAuth();
  const canCreate = claims?.scopes.includes(BLAST_SCOPE) ?? false;
  const navigate = useNavigate();
  const query = useApiQuery(() => getBlastCampaigns(), []);

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'' | BlastCampaignStatus>('');

  const filtered = useMemo(() => {
    if (query.status !== 'success') return [];
    const term = search.trim().toLowerCase();
    return query.data.filter((campaign) => {
      if (term && !campaign.name.toLowerCase().includes(term) && !campaign.created_by.toLowerCase().includes(term)) {
        return false;
      }
      if (statusFilter && campaign.status !== statusFilter) return false;
      return true;
    });
  }, [query, search, statusFilter]);

  const hasActiveFilters = search !== '' || statusFilter !== '';

  return (
    <div>
      {query.status === 'success' && query.data.length > 0 ? (
        <div className="wa-toolbar">
          <label className="wa-toolbar-search">
            <Search size={16} strokeWidth={1.75} aria-hidden="true" />
            <input
              type="text"
              placeholder="Search campaigns or creator…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search campaigns"
            />
          </label>
          <select
            className="wa-toolbar__select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as '' | BlastCampaignStatus)}
            aria-label="Filter by status"
          >
            <option value="">All statuses</option>
            {BLAST_STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>
                {BLAST_STATUS_LABEL[status]}
              </option>
            ))}
          </select>
          {hasActiveFilters ? (
            <Button
              variant="ghost"
              onClick={() => {
                setSearch('');
                setStatusFilter('');
              }}
            >
              <X size={14} strokeWidth={1.75} aria-hidden="true" />
              Clear
            </Button>
          ) : null}
        </div>
      ) : null}

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
      ) : filtered.length === 0 ? (
        <EmptyState icon={Search} title="No matching campaigns" description="Try a different search term or clear the filters." />
      ) : (
        <Card>
          <div className="wa-table-wrap">
            <table className="wa-table wa-table--responsive">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Recipients</th>
                  <th>Office</th>
                  <th>Created by</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((campaign) => (
                  <tr key={campaign.id}>
                    <td data-label="Name">
                      <Link to={`/blast/${campaign.id}`} className="wa-blast-table__name-link">
                        {campaign.name}
                      </Link>
                    </td>
                    <td data-label="Status">
                      <StatusBadge status={mapBlastCampaignStatus(campaign.status)} label={BLAST_STATUS_LABEL[campaign.status]} />
                    </td>
                    <td data-label="Recipients">{campaign.recipient_count}</td>
                    <td data-label="Office">{campaign.office?.name ?? '—'}</td>
                    <td data-label="Created by">{campaign.created_by}</td>
                    <td data-label="Created">{new Date(campaign.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
