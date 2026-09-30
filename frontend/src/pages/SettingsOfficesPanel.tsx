import { useMemo, useState } from 'react';
import { Building2, Plus, Search, X } from 'lucide-react';

import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { Input } from '../components/ui/Input';
import { LoadingState } from '../components/ui/LoadingState';
import { Modal } from '../components/ui/Modal';
import type { ApiError } from '../lib/api';
import { createOffice, updateOffice, type Office } from '../lib/djangoApi';
import { useApiQuery } from '../lib/useApiQuery';
import './SettingsPage.css';

// Step 6 (Office management) — Office Admin never reaches this panel at
// all (SettingsPage.tsx only renders it for a globally-accessing user);
// this file only needs to worry about Superadmin/Global Admin UX.
export function SettingsOfficesPanel({ offices, refetch }: { offices: ReturnType<typeof useApiQuery<Office[]>>; refetch: () => void }) {
  const [modalOffice, setModalOffice] = useState<Office | 'new' | null>(null);
  // Offices is never server-side paginated (see getOffices' own comment —
  // it's a full-list dropdown source elsewhere), so search/status filter
  // here are plain client-side — the FULL list is already in memory.
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'' | 'active' | 'inactive'>('');

  const filtered = useMemo(() => {
    if (offices.status !== 'success') return [];
    const term = search.trim().toLowerCase();
    return offices.data.filter((office) => {
      if (term && !office.name.toLowerCase().includes(term)) return false;
      if (statusFilter === 'active' && !office.is_active) return false;
      if (statusFilter === 'inactive' && office.is_active) return false;
      return true;
    });
  }, [offices, search, statusFilter]);

  const hasActiveFilters = search !== '' || statusFilter !== '';

  return (
    <Card>
      <div className="wa-settings-panel__header">
        <span className="wa-settings-panel__title">Offices</span>
        <Button variant="primary" onClick={() => setModalOffice('new')}>
          <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
          New Office
        </Button>
      </div>

      {offices.status === 'success' && offices.data.length > 0 ? (
        <div className="wa-settings-toolbar">
          <label className="wa-settings-search">
            <Search size={16} strokeWidth={1.75} aria-hidden="true" />
            <input
              type="text"
              placeholder="Search Offices…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search Offices"
            />
          </label>
          <select
            className="wa-settings-toolbar__select"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as '' | 'active' | 'inactive')}
            aria-label="Filter by status"
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
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

      {offices.status === 'loading' ? (
        <LoadingState label="Loading offices…" />
      ) : offices.status === 'error' ? (
        <ErrorState error={offices.error} onRetry={offices.refetch} />
      ) : offices.data.length === 0 ? (
        <EmptyState icon={Building2} title="No offices yet" description="Create the first Office to start assigning users to it." />
      ) : filtered.length === 0 ? (
        <EmptyState icon={Search} title="No matching Offices" description="Try a different search term or clear the filters." />
      ) : (
        <div className="wa-settings-table-wrap">
          <table className="wa-settings-table wa-settings-table--responsive">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((office) => (
                <tr key={office.id}>
                  <td data-label="Name">{office.name}</td>
                  <td data-label="Status">
                    <Badge tone={office.is_active ? 'success' : 'neutral'}>{office.is_active ? 'Active' : 'Inactive'}</Badge>
                  </td>
                  <td data-label="Created">{new Date(office.created_at).toLocaleDateString()}</td>
                  <td data-label="">
                    <Button variant="ghost" onClick={() => setModalOffice(office)}>
                      Edit
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <OfficeFormModal
        office={modalOffice}
        onClose={() => setModalOffice(null)}
        onSaved={() => {
          setModalOffice(null);
          refetch();
        }}
      />
    </Card>
  );
}

function OfficeFormModal({
  office,
  onClose,
  onSaved,
}: {
  office: Office | 'new' | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  // Keyed by which Office (or "new") is open, so the form below remounts
  // — and its local state resets — every time a different one opens,
  // instead of carrying over stale values from whatever was edited last.
  const openKey = office === null ? 'closed' : office === 'new' ? 'new' : office.id;
  const title = office === 'new' ? 'New Office' : office ? `Edit ${office.name}` : '';
  return (
    <Modal open={office !== null} onClose={onClose} title={title}>
      <OfficeForm key={openKey} office={office} onClose={onClose} onSaved={onSaved} />
    </Modal>
  );
}

function OfficeForm({
  office,
  onClose,
  onSaved,
}: {
  office: Office | 'new' | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = office === 'new';
  const editing = office !== null && office !== 'new' ? office : null;
  const [name, setName] = useState(editing?.name ?? '');
  const [isActive, setIsActive] = useState(editing?.is_active ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSubmit() {
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    const result = isNew
      ? await createOffice(trimmed)
      : await updateOffice(editing!.id, { name: trimmed, is_active: isActive });
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onSaved();
  }

  return (
    <div className="wa-settings-form">
      <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} disabled={busy} />
      {!isNew ? (
        <label className="wa-settings-checkbox-row">
          <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} disabled={busy} />
          <span>Active (an inactive Office cannot be picked for a new Blast campaign)</span>
        </label>
      ) : null}
      {error ? <ErrorState error={error} /> : null}
      <div className="wa-settings-form__actions">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant="primary" onClick={handleSubmit} disabled={busy || !name.trim()}>
          {busy ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  );
}
