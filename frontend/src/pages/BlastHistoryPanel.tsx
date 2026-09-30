import { useEffect, useState } from 'react';
import { History, Search, X } from 'lucide-react';

import { Card } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import { Pagination } from '../components/ui/Pagination';
import { mapBlastRecipientStatus, StatusBadge } from '../components/ui/StatusBadge';
import {
  getBlastHistory,
  type BlastCampaignSource,
  type BlastRecipientStatus,
  type OfficeChoice,
} from '../lib/djangoApi';
import { useApiQuery } from '../lib/useApiQuery';
import './BlastPage.css';

const DJANGO_PAGE_SIZE = 25;
const SEARCH_DEBOUNCE_MS = 300;

const STATUS_LABEL: Record<BlastRecipientStatus, string> = {
  pending: 'Pending',
  sending: 'Sending',
  sent: 'Sent',
  failed: 'Failed',
  skipped: 'Skipped',
  invalid_number: 'Invalid number',
};
const STATUS_OPTIONS = Object.keys(STATUS_LABEL) as BlastRecipientStatus[];

const SOURCE_LABEL: Record<BlastCampaignSource, string> = {
  dashboard: 'Dashboard',
  api: 'External API',
};

// Discussed requirement — Blast History: a flattened, server-side
// paginated, filterable audit table across every campaign's recipients.
// This — never the Inbox (see apps.chats.authorization.chats_visible_to's
// own inbound-message requirement) — is where a blast send's outcome is
// actually visible.
export function BlastHistoryPanel({ hasGlobalAccess, officeChoices }: { hasGlobalAccess: boolean; officeChoices: OfficeChoice[] }) {
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'' | BlastRecipientStatus>('');
  const [officeFilter, setOfficeFilter] = useState<number | ''>('');
  const [sourceFilter, setSourceFilter] = useState<'' | BlastCampaignSource>('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    setPage(1);
  }, [search, statusFilter, officeFilter, sourceFilter, dateFrom, dateTo]);

  const history = useApiQuery(
    () =>
      getBlastHistory({
        page,
        page_size: DJANGO_PAGE_SIZE,
        search: search || undefined,
        status: statusFilter || undefined,
        office: hasGlobalAccess && officeFilter !== '' ? officeFilter : undefined,
        source: sourceFilter || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
      }),
    [page, search, statusFilter, officeFilter, sourceFilter, dateFrom, dateTo],
  );

  const hasActiveFilters =
    search !== '' || statusFilter !== '' || officeFilter !== '' || sourceFilter !== '' || dateFrom !== '' || dateTo !== '';

  function clearFilters() {
    setSearchInput('');
    setStatusFilter('');
    setOfficeFilter('');
    setSourceFilter('');
    setDateFrom('');
    setDateTo('');
  }

  return (
    <div>
      <div className="wa-toolbar">
        <label className="wa-toolbar-search">
          <Search size={16} strokeWidth={1.75} aria-hidden="true" />
          <input
            type="text"
            placeholder="Search destination or campaign…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            aria-label="Search history"
          />
        </label>
        <select
          className="wa-toolbar__select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as '' | BlastRecipientStatus)}
          aria-label="Filter by status"
        >
          <option value="">All statuses</option>
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {STATUS_LABEL[status]}
            </option>
          ))}
        </select>
        <select
          className="wa-toolbar__select"
          value={sourceFilter}
          onChange={(e) => setSourceFilter(e.target.value as '' | BlastCampaignSource)}
          aria-label="Filter by source"
        >
          <option value="">Dashboard + API</option>
          <option value="dashboard">Dashboard only</option>
          <option value="api">External API only</option>
        </select>
        {hasGlobalAccess ? (
          <select
            className="wa-toolbar__select"
            value={officeFilter}
            onChange={(e) => setOfficeFilter(e.target.value ? Number(e.target.value) : '')}
            aria-label="Filter by Office"
          >
            <option value="">All Offices</option>
            {officeChoices.map((office) => (
              <option key={office.id} value={office.id}>
                {office.name}
              </option>
            ))}
          </select>
        ) : null}
        <input
          type="date"
          className="wa-toolbar__select"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          aria-label="From date"
        />
        <input
          type="date"
          className="wa-toolbar__select"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          aria-label="To date"
        />
        {hasActiveFilters ? (
          <Button variant="ghost" onClick={clearFilters}>
            <X size={14} strokeWidth={1.75} aria-hidden="true" />
            Clear
          </Button>
        ) : null}
      </div>

      {history.status === 'loading' ? (
        <LoadingState label="Loading history…" />
      ) : history.status === 'error' ? (
        <ErrorState error={history.error} onRetry={history.refetch} />
      ) : history.data.results.length === 0 ? (
        <EmptyState
          icon={hasActiveFilters ? Search : History}
          title={hasActiveFilters ? 'No matching history' : 'No blast history yet'}
          description={
            hasActiveFilters
              ? 'Try a different search term or clear the filters.'
              : 'Every recipient outcome across every campaign — dashboard or external API — appears here.'
          }
        />
      ) : (
        <>
          <Card>
            <div className="wa-table-wrap">
              <table className="wa-table wa-table--responsive">
                <thead>
                  <tr>
                    <th>Destination</th>
                    <th>Status</th>
                    <th>Campaign</th>
                    <th>Template</th>
                    <th>Source</th>
                    <th>Office</th>
                    <th>Sent</th>
                  </tr>
                </thead>
                <tbody>
                  {history.data.results.map((row) => (
                    <tr key={row.id}>
                      <td data-label="Destination">{row.destination}</td>
                      <td data-label="Status">
                        <StatusBadge status={mapBlastRecipientStatus(row.status)} label={STATUS_LABEL[row.status]} />
                        {row.status === 'failed' || row.status === 'invalid_number' ? (
                          <div className="wa-blast-recipients__failure">{row.failure_reason}</div>
                        ) : null}
                      </td>
                      <td data-label="Campaign">{row.campaign.name}</td>
                      <td data-label="Template">{row.campaign.template?.name ?? '—'}</td>
                      <td data-label="Source">{SOURCE_LABEL[row.campaign.source]}</td>
                      <td data-label="Office">{row.campaign.office?.name ?? '—'}</td>
                      <td data-label="Sent">{row.sent_at ? new Date(row.sent_at).toLocaleString() : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <Pagination
            page={history.data.page}
            hasPrevious={history.data.page > 1}
            hasNext={history.data.page < history.data.num_pages}
            onPrevious={() => setPage((p) => Math.max(1, p - 1))}
            onNext={() => setPage((p) => p + 1)}
            totalCount={history.data.count}
            pageSize={DJANGO_PAGE_SIZE}
          />
        </>
      )}
    </div>
  );
}
