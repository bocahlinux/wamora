import { useEffect, useState } from 'react';
import { Inbox } from 'lucide-react';

import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import type { ApiError } from '../lib/api';
import {
  getOfficeInboxConfig,
  updateOfficeInboxConfig,
  type Me,
  type Office,
  type OfficeInboxConfig,
} from '../lib/djangoApi';
import type { QueryState } from '../lib/useApiQuery';
import './SettingsPage.css';

// Step 10 (Office Inbox configuration foundation) — Superadmin/Global
// Admin pick which Office to configure (same picker-vs-fixed pattern as
// BlastCreatePage.tsx's Office field); an Office Admin configures only
// their own Office, no picker. Saving this never sends a WhatsApp
// message — it is storage/foundation only (OfficeInboxConfigView's own
// docstring); no automatic welcome/waiting/offline flow exists yet.
export function SettingsInboxConfigPanel({ me, offices }: { me: Me; offices: Office[] }) {
  const hasGlobalAccess = me.has_global_access;
  const fixedOfficeId = hasGlobalAccess ? null : (me.office?.id ?? null);
  const [pickedOfficeId, setPickedOfficeId] = useState<number | ''>('');
  const officeId = hasGlobalAccess ? pickedOfficeId : (fixedOfficeId ?? '');

  const [configState, setConfigState] = useState<QueryState<OfficeInboxConfig> | null>(null);

  useEffect(() => {
    if (officeId === '') {
      setConfigState(null);
      return;
    }
    let cancelled = false;
    setConfigState({ status: 'loading' });
    getOfficeInboxConfig(officeId).then((result) => {
      if (cancelled) return;
      setConfigState(result.ok ? { status: 'success', data: result.data } : { status: 'error', error: result.error });
    });
    return () => {
      cancelled = true;
    };
  }, [officeId]);

  return (
    <Card>
      <div className="wa-settings-panel__header">
        <span className="wa-settings-panel__title">Inbox Configuration</span>
      </div>

      {hasGlobalAccess ? (
        <div className="wa-settings-form__field">
          <label className="wa-settings-form__label" htmlFor="inbox-config-office">
            Office
          </label>
          <select
            id="inbox-config-office"
            className="wa-settings-form__select"
            value={pickedOfficeId}
            onChange={(e) => setPickedOfficeId(e.target.value ? Number(e.target.value) : '')}
          >
            <option value="">Select an Office…</option>
            {offices.map((office) => (
              <option key={office.id} value={office.id}>
                {office.name}
              </option>
            ))}
          </select>
        </div>
      ) : !fixedOfficeId ? (
        <EmptyState
          icon={Inbox}
          title="No Office assigned"
          description="You are not assigned to any Office; contact an administrator."
        />
      ) : null}

      {officeId === '' ? null : configState === null || configState.status === 'loading' ? (
        <LoadingState label="Loading configuration…" />
      ) : configState.status === 'error' ? (
        <ErrorState error={configState.error} />
      ) : (
        <InboxConfigForm
          key={officeId}
          officeId={officeId}
          config={configState.data}
          onSaved={(updated) => setConfigState({ status: 'success', data: updated })}
        />
      )}
    </Card>
  );
}

function InboxConfigForm({
  officeId,
  config,
  onSaved,
}: {
  officeId: number;
  config: OfficeInboxConfig;
  onSaved: (updated: OfficeInboxConfig) => void;
}) {
  const [enabled, setEnabled] = useState(config.enabled);
  const [welcomeMessage, setWelcomeMessage] = useState(config.welcome_message);
  const [waitingMessage, setWaitingMessage] = useState(config.waiting_message);
  const [offlineMessage, setOfflineMessage] = useState(config.offline_message);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);

  async function handleSubmit() {
    if (busy) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    const result = await updateOfficeInboxConfig(officeId, {
      enabled,
      welcome_message: welcomeMessage,
      waiting_message: waitingMessage,
      offline_message: offlineMessage,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onSaved(result.data);
    setSaved(true);
  }

  return (
    <div className="wa-settings-form">
      <label className="wa-settings-checkbox-row">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} disabled={busy} />
        <span>Inbox enabled</span>
      </label>

      <div className="wa-settings-form__field">
        <label className="wa-settings-form__label" htmlFor="inbox-config-welcome">
          Welcome message
        </label>
        <textarea
          id="inbox-config-welcome"
          className="wa-settings-form__textarea"
          rows={3}
          value={welcomeMessage}
          onChange={(e) => setWelcomeMessage(e.target.value)}
          disabled={busy}
        />
      </div>

      <div className="wa-settings-form__field">
        <label className="wa-settings-form__label" htmlFor="inbox-config-waiting">
          Waiting message
        </label>
        <textarea
          id="inbox-config-waiting"
          className="wa-settings-form__textarea"
          rows={3}
          value={waitingMessage}
          onChange={(e) => setWaitingMessage(e.target.value)}
          disabled={busy}
        />
      </div>

      <div className="wa-settings-form__field">
        <label className="wa-settings-form__label" htmlFor="inbox-config-offline">
          Offline message
        </label>
        <textarea
          id="inbox-config-offline"
          className="wa-settings-form__textarea"
          rows={3}
          value={offlineMessage}
          onChange={(e) => setOfflineMessage(e.target.value)}
          disabled={busy}
        />
      </div>

      {error ? <ErrorState error={error} /> : null}
      {saved && !error ? <p className="wa-settings-form__hint">Saved.</p> : null}

      <div className="wa-settings-form__actions">
        <Button variant="primary" onClick={handleSubmit} disabled={busy}>
          {busy ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  );
}
