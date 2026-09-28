import { useState } from 'react';
import { Plus, Users } from 'lucide-react';

import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { Input } from '../components/ui/Input';
import { LoadingState } from '../components/ui/LoadingState';
import { Modal } from '../components/ui/Modal';
import type { ApiError } from '../lib/api';
import {
  createUser,
  updateUser,
  type AdminUser,
  type Me,
  type Office,
  type OfficeRole,
} from '../lib/djangoApi';
import { useApiQuery } from '../lib/useApiQuery';
import './SettingsPage.css';

const ROLE_LABEL: Record<OfficeRole, string> = {
  global_admin: 'Global Admin',
  office_admin: 'Office Admin',
  operator: 'Operator',
};

// Step 6 (User management). `me` decides what this admin is allowed to
// pick: a globally-accessing user (Superadmin/Global Admin) may choose
// any role/Office; an Office Admin is restricted server-side to
// office_admin/operator within their own Office — this panel mirrors
// that in the form (no Global Admin option, no Office picker) purely as
// UX guidance; the backend remains the actual boundary regardless.
export function SettingsUsersPanel({
  me,
  users,
  offices,
}: {
  me: Me;
  users: ReturnType<typeof useApiQuery<AdminUser[]>>;
  offices: Office[];
}) {
  const [modalUser, setModalUser] = useState<AdminUser | 'new' | null>(null);
  const canPickGlobalAdmin = me.has_global_access;
  const canPickOffice = me.has_global_access;

  return (
    <Card>
      <div className="wa-settings-panel__header">
        <span className="wa-settings-panel__title">Users</span>
        <Button variant="primary" onClick={() => setModalUser('new')}>
          <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
          New user
        </Button>
      </div>

      {users.status === 'loading' ? (
        <LoadingState label="Loading users…" />
      ) : users.status === 'error' ? (
        <ErrorState error={users.error} onRetry={users.refetch} />
      ) : users.data.length === 0 ? (
        <EmptyState icon={Users} title="No users yet" description="Create the first user for this Office." />
      ) : (
        <div className="wa-settings-table-wrap">
          <table className="wa-settings-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Name</th>
                <th>Role</th>
                <th>Office</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users.data.map((user) => {
                const isSelf = user.id === me.id;
                const canEdit = !isSelf || me.is_superuser;
                return (
                  <tr key={user.id}>
                    <td>{user.username}</td>
                    <td>{[user.first_name, user.last_name].filter(Boolean).join(' ') || '—'}</td>
                    <td>{user.is_superuser ? 'Superadmin' : user.role ? ROLE_LABEL[user.role] : '—'}</td>
                    <td>{user.office?.name ?? '—'}</td>
                    <td>
                      <Badge tone={user.is_active ? 'success' : 'neutral'}>{user.is_active ? 'Active' : 'Inactive'}</Badge>
                    </td>
                    <td>
                      {user.is_superuser ? null : (
                        <Button variant="ghost" onClick={() => setModalUser(user)} disabled={!canEdit}>
                          Edit
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <UserFormModal
        user={modalUser}
        offices={offices}
        canPickGlobalAdmin={canPickGlobalAdmin}
        canPickOffice={canPickOffice}
        defaultOffice={me.office}
        onClose={() => setModalUser(null)}
        onSaved={() => {
          setModalUser(null);
          users.refetch();
        }}
      />
    </Card>
  );
}

function UserFormModal({
  user,
  offices,
  canPickGlobalAdmin,
  canPickOffice,
  defaultOffice,
  onClose,
  onSaved,
}: {
  user: AdminUser | 'new' | null;
  offices: Office[];
  canPickGlobalAdmin: boolean;
  canPickOffice: boolean;
  defaultOffice: { id: number; name: string } | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const openKey = user === null ? 'closed' : user === 'new' ? 'new' : user.id;
  const title = user === 'new' ? 'New user' : user ? `Edit ${user.username}` : '';
  return (
    <Modal open={user !== null} onClose={onClose} title={title}>
      <UserForm
        key={openKey}
        user={user}
        offices={offices}
        canPickGlobalAdmin={canPickGlobalAdmin}
        canPickOffice={canPickOffice}
        defaultOffice={defaultOffice}
        onClose={onClose}
        onSaved={onSaved}
      />
    </Modal>
  );
}

function UserForm({
  user,
  offices,
  canPickGlobalAdmin,
  canPickOffice,
  defaultOffice,
  onClose,
  onSaved,
}: {
  user: AdminUser | 'new' | null;
  offices: Office[];
  canPickGlobalAdmin: boolean;
  canPickOffice: boolean;
  defaultOffice: { id: number; name: string } | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = user === 'new';
  const editing = user !== null && user !== 'new' ? user : null;

  const [username, setUsername] = useState(editing?.username ?? '');
  const [password, setPassword] = useState('');
  const [firstName, setFirstName] = useState(editing?.first_name ?? '');
  const [lastName, setLastName] = useState(editing?.last_name ?? '');
  const [isActive, setIsActive] = useState(editing?.is_active ?? true);
  const [role, setRole] = useState<OfficeRole>(editing?.role ?? 'operator');
  const [officeId, setOfficeId] = useState<number | ''>(editing?.office?.id ?? defaultOffice?.id ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const officeRequired = role !== 'global_admin';
  const showOfficePicker = canPickOffice && officeRequired;

  async function handleSubmit() {
    if (busy) return;
    if (officeRequired && canPickOffice && officeId === '') {
      setError({ kind: 'validation', message: 'An Office is required for this role.' });
      return;
    }
    setBusy(true);
    setError(null);

    if (isNew) {
      const result = await createUser({
        username: username.trim(),
        password,
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        role,
        office: officeRequired ? (officeId === '' ? undefined : officeId) : null,
      });
      setBusy(false);
      if (!result.ok) {
        setError(result.error);
        return;
      }
      onSaved();
      return;
    }

    const result = await updateUser(editing!.id, {
      first_name: firstName.trim(),
      last_name: lastName.trim(),
      is_active: isActive,
      ...(password ? { password } : {}),
      role,
      office: officeRequired ? (officeId === '' ? null : officeId) : null,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onSaved();
  }

  return (
    <div className="wa-settings-form">
      {isNew ? (
        <Input label="Username" value={username} onChange={(e) => setUsername(e.target.value)} disabled={busy} />
      ) : null}
      <Input
        label={isNew ? 'Password' : 'New password (leave blank to keep current)'}
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        disabled={busy}
      />
      <Input label="First name" value={firstName} onChange={(e) => setFirstName(e.target.value)} disabled={busy} />
      <Input label="Last name" value={lastName} onChange={(e) => setLastName(e.target.value)} disabled={busy} />

      {!isNew ? (
        <label className="wa-settings-checkbox-row">
          <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} disabled={busy} />
          <span>Active</span>
        </label>
      ) : null}

      <div className="wa-settings-form__field">
        <span className="wa-settings-form__label">Role</span>
        <select
          className="wa-settings-form__select"
          value={role}
          onChange={(e) => setRole(e.target.value as OfficeRole)}
          disabled={busy}
        >
          {canPickGlobalAdmin ? <option value="global_admin">Global Admin</option> : null}
          <option value="office_admin">Office Admin</option>
          <option value="operator">Operator</option>
        </select>
      </div>

      {showOfficePicker ? (
        <div className="wa-settings-form__field">
          <span className="wa-settings-form__label">Office</span>
          <select
            className="wa-settings-form__select"
            value={officeId}
            onChange={(e) => setOfficeId(e.target.value ? Number(e.target.value) : '')}
            disabled={busy}
          >
            <option value="">Select an Office…</option>
            {offices.map((office) => (
              <option key={office.id} value={office.id}>
                {office.name}
              </option>
            ))}
          </select>
        </div>
      ) : officeRequired ? (
        <p className="wa-settings-form__hint">Office: {defaultOffice?.name ?? '—'} (your own Office)</p>
      ) : (
        <p className="wa-settings-form__hint">A Global Admin has no Office.</p>
      )}

      {error ? <ErrorState error={error} /> : null}

      <div className="wa-settings-form__actions">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button
          variant="primary"
          onClick={handleSubmit}
          disabled={busy || (isNew && (!username.trim() || !password))}
        >
          {busy ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  );
}
