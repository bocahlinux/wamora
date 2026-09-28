import { useState } from 'react';
import { Plus, ShieldCheck } from 'lucide-react';

import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import { Input } from '../components/ui/Input';
import { Modal } from '../components/ui/Modal';
import type { ApiError } from '../lib/api';
import { createRole, deleteRole, updateRole, type Role } from '../lib/djangoApi';
import { useApiQuery } from '../lib/useApiQuery';
import './SettingsPage.css';

// Dynamic Role-based menu/feature access — the fixed, already-enforced
// scope vocabulary (backend/config/settings.py's JWT_SCOPES verbatim).
// This list is deliberately NOT free text: a Role can only ever grant one
// of these 6 (RoleSerializer.validate_scopes rejects anything else), so a
// Superadmin building a Role here can only toggle capabilities the
// backend/BFF genuinely enforce somewhere, never invent an unenforced one.
const SCOPE_OPTIONS: { value: string; label: string; hint: string }[] = [
  { value: 'reading', label: 'Reading', hint: 'View Dashboard stats, Sessions status, Inbox sync status' },
  { value: 'sending', label: 'Sending', hint: 'Send a WhatsApp message from the Inbox composer' },
  {
    value: 'session control',
    label: 'Session control',
    hint: 'Start, restart, stop, log out, and pair the WhatsApp session',
  },
  { value: 'blast', label: 'Blast', hint: 'Create and submit Blast campaigns' },
  { value: 'user administration', label: 'User administration', hint: 'Manage Offices and Users in Settings' },
  {
    value: 'system administration',
    label: 'System administration',
    hint: 'Mark a stuck reconciliation run as failed (Sync Recovery)',
  },
];

const SCOPE_LABEL: Record<string, string> = Object.fromEntries(SCOPE_OPTIONS.map((o) => [o.value, o.label]));

// Superadmin-only (SettingsPage.tsx only renders this panel for
// me.is_superuser, matching the backend's IsSuperuser gate on
// /api/roles/ exactly) — this file only needs to worry about that UX.
export function SettingsRolesPanel({ roles }: { roles: ReturnType<typeof useApiQuery<Role[]>> }) {
  const [modalRole, setModalRole] = useState<Role | 'new' | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<ApiError | null>(null);

  async function handleDeleteConfirmed() {
    if (!deleteTarget || deleteBusy) return;
    setDeleteBusy(true);
    setDeleteError(null);
    const result = await deleteRole(deleteTarget.id);
    setDeleteBusy(false);
    if (!result.ok) {
      setDeleteError(result.error);
      return;
    }
    setDeleteTarget(null);
    roles.refetch();
  }

  return (
    <Card>
      <div className="wa-settings-panel__header">
        <span className="wa-settings-panel__title">Roles</span>
        <Button variant="primary" onClick={() => setModalRole('new')}>
          <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
          New Role
        </Button>
      </div>

      {roles.status === 'loading' ? (
        <LoadingState label="Loading roles…" />
      ) : roles.status === 'error' ? (
        <ErrorState error={roles.error} onRetry={roles.refetch} />
      ) : roles.data.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title="No Roles yet"
          description="Create a Role to control which menus/features a user's account can use, then assign it to them from Users."
        />
      ) : (
        <div className="wa-settings-table-wrap">
          <table className="wa-settings-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Organizational standing</th>
                <th>Grants</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {roles.data.map((role) => (
                <tr key={role.id}>
                  <td>{role.name}</td>
                  <td>
                    {[
                      role.grants_global_access ? 'Global access' : null,
                      role.is_office_admin ? 'Office Admin' : null,
                      role.is_operator ? 'Operator' : null,
                    ]
                      .filter(Boolean)
                      .join(', ') || '—'}
                  </td>
                  <td>
                    {role.scopes.length === 0
                      ? '—'
                      : role.scopes.map((s) => SCOPE_LABEL[s] ?? s).join(', ')}
                  </td>
                  <td>
                    <Button variant="ghost" onClick={() => setModalRole(role)}>
                      Edit
                    </Button>
                    <Button variant="ghost" onClick={() => setDeleteTarget(role)}>
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <RoleFormModal
        role={modalRole}
        onClose={() => setModalRole(null)}
        onSaved={() => {
          setModalRole(null);
          roles.refetch();
        }}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title={deleteTarget ? `Delete "${deleteTarget.name}"?` : 'Delete Role?'}
        description="Any user still assigned this Role must be reassigned or cleared first — the server will refuse the delete otherwise."
        confirmLabel="Delete"
        busy={deleteBusy}
        onCancel={() => {
          setDeleteTarget(null);
          setDeleteError(null);
        }}
        onConfirm={handleDeleteConfirmed}
      />
      {deleteError ? <ErrorState error={deleteError} /> : null}
    </Card>
  );
}

function RoleFormModal({
  role,
  onClose,
  onSaved,
}: {
  role: Role | 'new' | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const openKey = role === null ? 'closed' : role === 'new' ? 'new' : role.id;
  const title = role === 'new' ? 'New Role' : role ? `Edit ${role.name}` : '';
  return (
    <Modal open={role !== null} onClose={onClose} title={title}>
      <RoleForm key={openKey} role={role} onClose={onClose} onSaved={onSaved} />
    </Modal>
  );
}

function RoleForm({
  role,
  onClose,
  onSaved,
}: {
  role: Role | 'new' | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = role === 'new';
  const editing = role !== null && role !== 'new' ? role : null;

  const [name, setName] = useState(editing?.name ?? '');
  const [scopes, setScopes] = useState<Set<string>>(new Set(editing?.scopes ?? []));
  const [grantsGlobalAccess, setGrantsGlobalAccess] = useState(editing?.grants_global_access ?? false);
  const [isOfficeAdmin, setIsOfficeAdmin] = useState(editing?.is_office_admin ?? false);
  const [isOperator, setIsOperator] = useState(editing?.is_operator ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  function toggleScope(value: string) {
    setScopes((prev) => {
      const next = new Set(prev);
      if (next.has(value)) next.delete(value);
      else next.add(value);
      return next;
    });
  }

  async function handleSubmit() {
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    const payload = {
      name: trimmed,
      scopes: Array.from(scopes),
      grants_global_access: grantsGlobalAccess,
      is_office_admin: isOfficeAdmin,
      is_operator: isOperator,
    };
    const result = isNew ? await createRole(payload) : await updateRole(editing!.id, payload);
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

      <div className="wa-settings-form__field">
        <span className="wa-settings-form__label">Organizational standing</span>
        <label className="wa-settings-checkbox-row">
          <input
            type="checkbox"
            checked={grantsGlobalAccess}
            onChange={(e) => setGrantsGlobalAccess(e.target.checked)}
            disabled={busy}
          />
          <span>Global access — sees/acts across every Office (must have no Office; excludes the other two below)</span>
        </label>
        <label className="wa-settings-checkbox-row">
          <input
            type="checkbox"
            checked={isOfficeAdmin}
            onChange={(e) => setIsOfficeAdmin(e.target.checked)}
            disabled={busy}
          />
          <span>Office Admin — administrative authority within their own Office (approve/reject Blast, assign/unassign chats)</span>
        </label>
        <label className="wa-settings-checkbox-row">
          <input
            type="checkbox"
            checked={isOperator}
            onChange={(e) => setIsOperator(e.target.checked)}
            disabled={busy}
          />
          <span>Operator — eligible as a chat-assignment target and may toggle their own availability</span>
        </label>
        <p className="wa-settings-form__hint">
          A Role with Global access must have no Office when assigned to a user — Office Admin/Operator require one.
        </p>
      </div>

      <div className="wa-settings-form__field">
        <span className="wa-settings-form__label">Grants access to</span>
        {SCOPE_OPTIONS.map((opt) => (
          <label key={opt.value} className="wa-settings-checkbox-row">
            <input
              type="checkbox"
              checked={scopes.has(opt.value)}
              onChange={() => toggleScope(opt.value)}
              disabled={busy}
            />
            <span>
              {opt.label} — {opt.hint}
            </span>
          </label>
        ))}
      </div>

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
