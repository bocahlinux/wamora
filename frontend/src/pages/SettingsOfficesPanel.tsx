import { useState } from 'react';
import { Building2, Plus } from 'lucide-react';

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

  return (
    <Card>
      <div className="wa-settings-panel__header">
        <span className="wa-settings-panel__title">Offices</span>
        <Button variant="primary" onClick={() => setModalOffice('new')}>
          <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
          New Office
        </Button>
      </div>

      {offices.status === 'loading' ? (
        <LoadingState label="Loading offices…" />
      ) : offices.status === 'error' ? (
        <ErrorState error={offices.error} onRetry={offices.refetch} />
      ) : offices.data.length === 0 ? (
        <EmptyState icon={Building2} title="No offices yet" description="Create the first Office to start assigning users to it." />
      ) : (
        <div className="wa-settings-table-wrap">
          <table className="wa-settings-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {offices.data.map((office) => (
                <tr key={office.id}>
                  <td>{office.name}</td>
                  <td>
                    <Badge tone={office.is_active ? 'success' : 'neutral'}>{office.is_active ? 'Active' : 'Inactive'}</Badge>
                  </td>
                  <td>{new Date(office.created_at).toLocaleDateString()}</td>
                  <td>
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
