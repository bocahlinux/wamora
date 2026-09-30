import { useState } from 'react';
import { Check, Copy, Key, Plus } from 'lucide-react';

import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { Input } from '../components/ui/Input';
import { LoadingState } from '../components/ui/LoadingState';
import { Modal } from '../components/ui/Modal';
import type { ApiError } from '../lib/api';
import {
  createBlastApiKey,
  getBlastApiKeys,
  getBlastSettings,
  revokeBlastApiKey,
  updateBlastSettings,
  type BlastApiKey,
} from '../lib/djangoApi';
import { useApiQuery } from '../lib/useApiQuery';
import './SettingsPage.css';

// Discussed requirement — external Blast-trigger API. Superadmin/Global-
// Admin-only (SettingsPage.tsx only renders this panel when
// me.has_global_access), mirroring the Roles tab's superuser-only
// precedent. Combines API key management with the dynamic inter-message
// delay (BlastSettings) — both are the same "system-wide Blast dispatch
// configuration" concern, not two separate tabs. A key is global (carries
// no Office at all — apps.blast.models.BlastApiKey's own docstring).
export function SettingsBlastApiPanel() {
  const keysQuery = useApiQuery(() => getBlastApiKeys(), []);
  const settingsQuery = useApiQuery(() => getBlastSettings(), []);

  const [modalOpen, setModalOpen] = useState(false);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<BlastApiKey | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [revokeError, setRevokeError] = useState<ApiError | null>(null);

  async function handleRevoke() {
    if (!revokeTarget || revokeBusy) return;
    setRevokeBusy(true);
    setRevokeError(null);
    const result = await revokeBlastApiKey(revokeTarget.id);
    setRevokeBusy(false);
    if (!result.ok) {
      setRevokeError(result.error);
      return;
    }
    setRevokeTarget(null);
    keysQuery.refetch();
  }

  return (
    <div>
      <Card className="wa-blast-section" style={{ marginBottom: 'var(--card-gap)' }}>
        <div className="wa-settings-panel__header">
          <span className="wa-settings-panel__title">Inter-message delay</span>
        </div>
        {settingsQuery.status === 'loading' ? (
          <LoadingState label="Loading…" />
        ) : settingsQuery.status === 'error' ? (
          <ErrorState error={settingsQuery.error} onRetry={settingsQuery.refetch} />
        ) : (
          <DelaySettingForm current={settingsQuery.data.inter_message_delay_seconds} onSaved={settingsQuery.refetch} />
        )}
      </Card>

      <Card>
        <div className="wa-settings-panel__header">
          <span className="wa-settings-panel__title">API keys</span>
          <Button
            variant="primary"
            onClick={() => {
              setCreatedKey(null);
              setModalOpen(true);
            }}
          >
            <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
            New API key
          </Button>
        </div>

        {keysQuery.status === 'loading' ? (
          <LoadingState label="Loading API keys…" />
        ) : keysQuery.status === 'error' ? (
          <ErrorState error={keysQuery.error} onRetry={keysQuery.refetch} />
        ) : keysQuery.data.length === 0 ? (
          <EmptyState
            icon={Key}
            title="No API keys yet"
            description="Create a key so an external system (e.g. the tax backend) can send a single message, a freeform blast, or a templated blast — for any session, all with one key."
          />
        ) : (
          <div className="wa-settings-table-wrap">
            <table className="wa-settings-table wa-settings-table--responsive">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Key prefix</th>
                  <th>Status</th>
                  <th>Last used</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {keysQuery.data.map((key) => (
                  <tr key={key.id}>
                    <td data-label="Name">{key.name}</td>
                    <td data-label="Key prefix">
                      <code>{key.key_prefix}…</code>
                    </td>
                    <td data-label="Status">
                      <Badge tone={key.is_active ? 'success' : 'neutral'}>{key.is_active ? 'Active' : 'Revoked'}</Badge>
                    </td>
                    <td data-label="Last used">{key.last_used_at ? new Date(key.last_used_at).toLocaleString() : 'Never'}</td>
                    <td data-label="">
                      {key.is_active ? (
                        <Button variant="ghost" onClick={() => setRevokeTarget(key)}>
                          Revoke
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={createdKey ? 'API key created' : 'New API key'}>
        {createdKey ? (
          <RawKeyReveal rawKey={createdKey} onClose={() => setModalOpen(false)} />
        ) : (
          <CreateKeyForm
            onCreated={(rawKey) => {
              setCreatedKey(rawKey);
              keysQuery.refetch();
            }}
            onClose={() => setModalOpen(false)}
          />
        )}
      </Modal>

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revoke API key?"
        description={`"${revokeTarget?.name}" will no longer be able to trigger Blast campaigns. This cannot be undone, but past campaigns it triggered stay fully attributable.`}
        confirmLabel="Revoke"
        variant="danger"
        busy={revokeBusy}
        onConfirm={handleRevoke}
        onCancel={() => {
          setRevokeTarget(null);
          setRevokeError(null);
        }}
      />
      {revokeError ? <ErrorState error={revokeError} /> : null}
    </div>
  );
}

function DelaySettingForm({ current, onSaved }: { current: number; onSaved: () => void }) {
  const [value, setValue] = useState(String(current));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);

  async function handleSave() {
    const parsed = Number(value);
    if (busy || !Number.isFinite(parsed) || parsed < 0) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    const result = await updateBlastSettings(Math.round(parsed));
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setSaved(true);
    onSaved();
  }

  return (
    <div className="wa-settings-form">
      <p className="wa-blast-section__description">
        Applies to every Blast campaign — dashboard and external-API-triggered alike. Takes effect immediately for
        any campaign scheduled after saving.
      </p>
      <Input
        label="Seconds between each message"
        type="number"
        min={0}
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          setSaved(false);
        }}
        disabled={busy}
      />
      {error ? <ErrorState error={error} /> : null}
      {saved ? <p className="wa-blast-detail__feedback wa-blast-detail__feedback--success">Saved.</p> : null}
      <div className="wa-settings-form__actions">
        <Button variant="primary" onClick={handleSave} disabled={busy || value.trim() === ''}>
          {busy ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  );
}

function CreateKeyForm({ onCreated, onClose }: { onCreated: (rawKey: string) => void; onClose: () => void }) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSubmit() {
    if (busy || !name.trim()) return;
    setBusy(true);
    setError(null);
    const result = await createBlastApiKey(name.trim());
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onCreated(result.data.raw_key);
  }

  return (
    <div className="wa-settings-form">
      <p className="wa-blast-section__description">
        This key is global — it works for a single ad-hoc message, a freeform blast, or a templated blast, against
        any session named in each request.
      </p>
      <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} disabled={busy} />
      {error ? <ErrorState error={error} /> : null}
      <div className="wa-settings-form__actions">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant="primary" onClick={handleSubmit} disabled={busy || !name.trim()}>
          {busy ? 'Creating…' : 'Create'}
        </Button>
      </div>
    </div>
  );
}

function RawKeyReveal({ rawKey, onClose }: { rawKey: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(rawKey);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can fail (permissions/insecure context) — the
      // raw key stays selectable/visible in the <code> block below
      // either way, so this is a non-fatal UX convenience only.
    }
  }

  return (
    <div className="wa-settings-form">
      <p className="wa-blast-section__description">
        This key is shown <strong>only once</strong>. Copy it now — it cannot be retrieved again after this dialog
        closes.
      </p>
      <pre className="wa-blast-form__preview-list" style={{ wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}>
        {rawKey}
      </pre>
      <div className="wa-settings-form__actions">
        <Button variant="secondary" onClick={handleCopy}>
          {copied ? <Check size={16} strokeWidth={1.75} aria-hidden="true" /> : <Copy size={16} strokeWidth={1.75} aria-hidden="true" />}
          {copied ? 'Copied' : 'Copy to clipboard'}
        </Button>
        <Button variant="primary" onClick={onClose}>
          Done
        </Button>
      </div>
    </div>
  );
}
