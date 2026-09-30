import { useState } from 'react';
import { LayoutGrid } from 'lucide-react';

import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import { Modal } from '../components/ui/Modal';
import type { ApiError } from '../lib/api';
import { updateRole, type Role } from '../lib/djangoApi';
import { MENU_ITEMS, MENU_ITEM_GROUPS } from '../lib/menuItems';
import { useApiQuery } from '../lib/useApiQuery';
import './SettingsPage.css';

// Discussed requirement — Menu Access: per-Role control over which
// sidebar leaf items render, independent from `scopes` (which still
// govern actual API authorization, unchanged). See Sidebar.tsx's own
// `isMenuItemVisible`/`VisibilityContext` for exactly how this is
// applied, and `Role.visible_menu_items`'s own model docstring
// (backend/apps/offices/models.py) for the null/[]/list-vs-list meaning.
export function SettingsMenuAccessPanel({ roles }: { roles: ReturnType<typeof useApiQuery<Role[]>> }) {
  const [modalRole, setModalRole] = useState<Role | null>(null);

  function summarize(role: Role): { label: string; tone: 'neutral' | 'warning' | 'info' } {
    if (role.visible_menu_items === null) return { label: 'Default (based on scopes)', tone: 'neutral' };
    if (role.visible_menu_items.length === 0) return { label: 'Hidden entirely', tone: 'warning' };
    return { label: `Customized — ${role.visible_menu_items.length} item(s)`, tone: 'info' };
  }

  return (
    <Card>
      <div className="wa-settings-panel__header">
        <span className="wa-settings-panel__title">Menu Access</span>
      </div>
      <p className="wa-blast-section__description" style={{ marginBottom: 'var(--space-4)' }}>
        Controls which sidebar menu items render for each Role. This never changes what a Role can actually DO —
        that's still governed by its scopes (Manage Users &gt; Roles) — only what appears in the sidebar.
      </p>

      {roles.status === 'loading' ? (
        <LoadingState label="Loading roles…" />
      ) : roles.status === 'error' ? (
        <ErrorState error={roles.error} onRetry={roles.refetch} />
      ) : roles.data.length === 0 ? (
        <EmptyState icon={LayoutGrid} title="No Roles yet" description="Create a Role first, under Manage Users > Roles." />
      ) : (
        <div className="wa-settings-table-wrap">
          <table className="wa-settings-table wa-settings-table--responsive">
            <thead>
              <tr>
                <th>Role</th>
                <th>Menu Access</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {roles.data.map((role) => {
                const summary = summarize(role);
                return (
                  <tr key={role.id}>
                    <td data-label="Role">{role.name}</td>
                    <td data-label="Menu Access">
                      <Badge tone={summary.tone}>{summary.label}</Badge>
                    </td>
                    <td data-label="">
                      <Button variant="ghost" onClick={() => setModalRole(role)}>
                        Edit
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <MenuAccessModal role={modalRole} onClose={() => setModalRole(null)} onSaved={() => { setModalRole(null); roles.refetch(); }} />
    </Card>
  );
}

function MenuAccessModal({ role, onClose, onSaved }: { role: Role | null; onClose: () => void; onSaved: () => void }) {
  return (
    <Modal open={role !== null} onClose={onClose} title={role ? `Menu Access — ${role.name}` : ''}>
      {role ? <MenuAccessForm key={role.id} role={role} onClose={onClose} onSaved={onSaved} /> : null}
    </Modal>
  );
}

function MenuAccessForm({ role, onClose, onSaved }: { role: Role; onClose: () => void; onSaved: () => void }) {
  const [mode, setMode] = useState<'default' | 'custom'>(role.visible_menu_items === null ? 'default' : 'custom');
  const [selected, setSelected] = useState<Set<string>>(new Set(role.visible_menu_items ?? []));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  function toggle(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function handleSave() {
    if (busy) return;
    setBusy(true);
    setError(null);
    const result = await updateRole(role.id, {
      visible_menu_items: mode === 'default' ? null : Array.from(selected),
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
      <label className="wa-settings-checkbox-row">
        <input type="radio" name="menu-access-mode" checked={mode === 'default'} onChange={() => setMode('default')} disabled={busy} />
        <span>Use default (based on this Role's scopes and organizational standing)</span>
      </label>
      <label className="wa-settings-checkbox-row">
        <input type="radio" name="menu-access-mode" checked={mode === 'custom'} onChange={() => setMode('custom')} disabled={busy} />
        <span>Customize — pick exactly which menu items this Role sees</span>
      </label>

      {mode === 'custom' ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {MENU_ITEM_GROUPS.map((group) => (
            <div key={group}>
              <span className="wa-blast-form__label">{group}</span>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)', marginTop: 'var(--space-1)' }}>
                {MENU_ITEMS.filter((item) => item.group === group).map((item) => (
                  <label key={item.key} className="wa-settings-checkbox-row">
                    <input type="checkbox" checked={selected.has(item.key)} onChange={() => toggle(item.key)} disabled={busy} />
                    <span>{item.label}</span>
                  </label>
                ))}
              </div>
            </div>
          ))}
          {selected.size === 0 ? (
            <p className="wa-blast-form__hint">No items selected — this Role's sidebar will be entirely empty.</p>
          ) : null}
        </div>
      ) : null}

      {error ? <ErrorState error={error} /> : null}
      <div className="wa-settings-form__actions">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant="primary" onClick={handleSave} disabled={busy}>
          {busy ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  );
}
