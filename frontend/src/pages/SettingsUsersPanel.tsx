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
  type Role,
} from '../lib/djangoApi';
import { useApiQuery } from '../lib/useApiQuery';
import './SettingsPage.css';

// The Role merge — `role` is now the ONE field carrying both
// organizational standing (Office-scoping/administrative authority) and
// feature/menu access, replacing what used to be a fixed 3-value enum
// (Office role) plus a separate "Custom Role" picker. `me` decides what
// this admin is allowed to pick: a globally-accessing user (Superadmin/
// Global Admin) may choose any Role/Office, including one with
// `grants_global_access`; an Office Admin may pick any Role EXCEPT one
// with `grants_global_access` (server-enforced in
// UserListCreateView.post/UserDetailView.patch) — this panel mirrors
// that in the form purely as UX guidance; the backend remains the
// actual boundary regardless.
export function SettingsUsersPanel({
  me,
  users,
  offices,
  roles,
}: {
  me: Me;
  users: ReturnType<typeof useApiQuery<AdminUser[]>>;
  offices: Office[];
  /** The Role catalog — readable by Superadmin, Global Admin, AND Office
   * Admin (`RoleListCreateView.get`'s `_admin_scope` check), since even
   * an Office Admin needs it to populate this picker now that Role is
   * dynamic. */
  roles: Role[];
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
                    <td>{user.is_superuser ? 'Superadmin' : (user.role?.name ?? '—')}</td>
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
        roles={roles}
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
  roles,
  canPickGlobalAdmin,
  canPickOffice,
  defaultOffice,
  onClose,
  onSaved,
}: {
  user: AdminUser | 'new' | null;
  offices: Office[];
  roles: Role[];
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
        roles={roles}
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
  roles,
  canPickGlobalAdmin,
  canPickOffice,
  defaultOffice,
  onClose,
  onSaved,
}: {
  user: AdminUser | 'new' | null;
  offices: Office[];
  roles: Role[];
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
  const [initial, setInitial] = useState(editing?.initial ?? '');
  const [isActive, setIsActive] = useState(editing?.is_active ?? true);
  // Roles this actor may pick from at all — an Office Admin may never
  // select one with `grants_global_access` (server-enforced regardless;
  // this only avoids offering a choice that will just 403).
  const pickableRoles = canPickGlobalAdmin ? roles : roles.filter((r) => !r.grants_global_access);
  const [roleId, setRoleId] = useState<number | ''>(editing?.role?.id ?? '');
  const [officeId, setOfficeId] = useState<number | ''>(editing?.office?.id ?? defaultOffice?.id ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const selectedRole = pickableRoles.find((r) => r.id === roleId) ?? null;
  const officeRequired = selectedRole !== null ? !selectedRole.grants_global_access : true;
  const showOfficePicker = canPickOffice && officeRequired;

  async function handleSubmit() {
    if (busy) return;
    if (roleId === '') {
      setError({ kind: 'validation', message: 'A Role is required.' });
      return;
    }
    if (officeRequired && canPickOffice && officeId === '') {
      setError({ kind: 'validation', message: 'An Office is required for this Role.' });
      return;
    }
    if (isNew && !initial.trim()) {
      setError({ kind: 'validation', message: 'An Initial is required.' });
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
        initial: initial.trim(),
        role: roleId,
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
      ...(initial.trim() ? { initial: initial.trim() } : {}),
      ...(password ? { password } : {}),
      role: roleId,
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
      <Input
        label="Initial (shown to citizens when this user claims a chat)"
        value={initial}
        onChange={(e) => setInitial(e.target.value)}
        disabled={busy}
        maxLength={10}
      />

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
          value={roleId}
          onChange={(e) => setRoleId(e.target.value ? Number(e.target.value) : '')}
          disabled={busy}
        >
          <option value="">Select a Role…</option>
          {pickableRoles.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>
        <p className="wa-settings-form__hint">
          Decides both Office-scoping/administrative authority and which menus/features this account can use
          (Settings → Roles).
        </p>
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
        <p className="wa-settings-form__hint">A Role with global access has no Office.</p>
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
