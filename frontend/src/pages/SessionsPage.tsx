import { useEffect, useRef, useState } from 'react';
import { LogOut, Play, QrCode, RefreshCw, Smartphone, Square } from 'lucide-react';

import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { Input } from '../components/ui/Input';
import { LoadingState } from '../components/ui/LoadingState';
import { Modal } from '../components/ui/Modal';
import { PageHeader } from '../components/ui/PageHeader';
import { mapWahaStatus, StatusBadge } from '../components/ui/StatusBadge';
import type { ApiError, ApiResult } from '../lib/api';
import {
  getSessionQr,
  getSessionStatus,
  logoutSession,
  requestPairingCode,
  restartSession,
  startSession,
  stopSession,
  type SessionActionResult,
  type SessionLifecycleAction,
  type SessionPairingCodeResult,
  type SessionQrResult,
  type SessionStatus,
} from '../lib/bffApi';
import { config } from '../lib/config';
import { useApiQuery } from '../lib/useApiQuery';
import './SessionsPage.css';

type ActionFeedback =
  | { action: SessionLifecycleAction; kind: 'success' }
  | { action: SessionLifecycleAction; kind: 'unknown' }
  | { action: SessionLifecycleAction; kind: 'error'; error: ApiError };

const ACTION_LABEL: Record<SessionLifecycleAction, string> = {
  start: 'Start',
  stop: 'Stop',
  restart: 'Restart',
  logout: 'Logout',
};

const ACTION_VERB_ING: Record<SessionLifecycleAction, string> = {
  start: 'Starting…',
  stop: 'Stopping…',
  restart: 'Restarting…',
  logout: 'Logging out…',
};

// Status-sync polling (docs/generated/SESSION-MANAGEMENT-STATUS-SYNC-REPORT.md).
// WAHA's status vocabulary is explicitly not enumerated anywhere in this
// project (apps/waha_sessions/models.py's own comment: "WAHA's exact
// status vocabulary is not enumerated... stores the raw reported value
// instead of guessing an enum"), so this deliberately does not hardcode
// a specific "terminal" status list (e.g. assuming 'WORKING'/'STOPPED'
// are the only endpoints) — it polls until the reported status stops
// changing between two consecutive checks (a generic settle-detection
// that works for whatever value WAHA actually reports), bounded by
// POLL_MAX_TICKS as a safety net against an oscillating or wedged status.
const POLL_INTERVAL_MS = 1500;
const POLL_MAX_TICKS = 20; // ~30s ceiling

// Session Management phase — docs/generated/SESSION-MANAGEMENT-IMPLEMENTATION-REPORT.md.
// Scope note (unchanged from Phase 7): "session/status presentation" was
// this page's Phase 7 scope; start/stop/restart/logout/QR/pairing-code
// (this phase) reuse the existing, already-tested BFF endpoints — no
// backend/BFF contract change was needed for the UI itself (the BFF
// hardening in the same report is a reliability fix, not a new contract).
export function SessionsPage() {
  const sessionName = config.wahaSessionName;
  const statusQuery = useApiQuery(() => getSessionStatus(sessionName), [sessionName]);

  const [busyAction, setBusyAction] = useState<SessionLifecycleAction | null>(null);
  const [feedback, setFeedback] = useState<ActionFeedback | null>(null);
  const [confirmAction, setConfirmAction] = useState<'stop' | 'logout' | null>(null);
  const [pairingOpen, setPairingOpen] = useState(false);

  // Freshest known status since the last mutation, refreshed by
  // startStatusSync() below. Overrides statusQuery's (only-fetched-once)
  // data whenever set, so the badge never keeps showing a stale value
  // after Start/Stop/Restart/Logout without needing a manual page
  // refresh. `null` means "no mutation has completed yet — defer to
  // statusQuery's own initial-load value."
  const [liveStatus, setLiveStatus] = useState<SessionStatus | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);
  const pollGenerationRef = useRef(0);
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function stopStatusSync() {
    pollGenerationRef.current += 1; // invalidates any in-flight/scheduled tick
    if (pollTimeoutRef.current !== null) {
      clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
    setIsSyncing(false);
  }

  // Always unmount/navigation-safe: this cleanup fires when SessionsPage
  // itself unmounts (component unmount, or the user navigates to a
  // different route via react-router), independent of any in-progress
  // action.
  useEffect(() => stopStatusSync, []);

  function startStatusSync() {
    pollGenerationRef.current += 1;
    const generation = pollGenerationRef.current;
    setIsSyncing(true);
    runTick(generation, undefined, POLL_MAX_TICKS);
  }

  function runTick(generation: number, previousStatus: string | undefined, ticksLeft: number) {
    if (!sessionName) return;
    getSessionStatus(sessionName).then((result) => {
      if (generation !== pollGenerationRef.current) return; // superseded/cancelled
      if (!result.ok) {
        // Stop cleanly on a fetch error/timeout — never spin forever on a
        // failing background check. The last known-good status (if any)
        // stays displayed rather than being replaced with an alarming
        // error state for what may just be a transient blip.
        setIsSyncing(false);
        return;
      }
      setLiveStatus(result.data);
      const current = result.data.status;
      const settled = previousStatus !== undefined && current === previousStatus;
      if (settled || ticksLeft <= 0) {
        setIsSyncing(false);
        return;
      }
      pollTimeoutRef.current = setTimeout(() => {
        if (generation !== pollGenerationRef.current) return;
        runTick(generation, current, ticksLeft - 1);
      }, POLL_INTERVAL_MS);
    });
  }

  async function runAction(
    action: SessionLifecycleAction,
    fn: (session: string) => Promise<ApiResult<SessionActionResult>>,
  ) {
    if (!sessionName || busyAction || isSyncing) return;
    setBusyAction(action);
    setFeedback(null);
    const result = await fn(sessionName);
    setBusyAction(null);
    if (!result.ok) {
      setFeedback({ action, kind: 'error', error: result.error });
      return;
    }
    setFeedback({ action, kind: result.data.outcome === 'unknown' ? 'unknown' : 'success' });
    // Never leave a stale status displayed as current after a mutation —
    // for both a confirmed success and an ambiguous "unknown" outcome,
    // start polling until the real status settles (see runTick above).
    // A confirmed error is not followed by a sync: the mutation didn't
    // reach WAHA, so there's nothing new to wait for.
    startStatusSync();
  }

  async function handleConfirmed() {
    const action = confirmAction;
    if (!action) return;
    await runAction(action, action === 'stop' ? stopSession : logoutSession);
    setConfirmAction(null);
  }

  const displayedStatus = liveStatus ?? (statusQuery.status === 'success' ? statusQuery.data : null);

  return (
    <div>
      <PageHeader title="Sessions" description="WhatsApp session status and controls" />

      {!sessionName ? (
        <Card>
          <EmptyState
            icon={Smartphone}
            title="No session configured"
            description="Set VITE_WAHA_SESSION_NAME to enable session management."
          />
        </Card>
      ) : (
        <>
          <Card className="wa-session-card">
            <div className="wa-session-card__icon">
              <Smartphone size={20} strokeWidth={1.75} aria-hidden="true" />
            </div>
            <div className="wa-session-card__body">
              <div className="wa-session-card__title-row">
                <p className="wa-session-card__name">{displayedStatus?.session ?? sessionName}</p>
                {displayedStatus ? (
                  <StatusBadge status={mapWahaStatus(displayedStatus.status)} label={displayedStatus.status ?? 'Unknown'} />
                ) : statusQuery.status === 'error' ? (
                  <StatusBadge status="error" label="Unreachable" />
                ) : null}
              </div>

              {!displayedStatus && statusQuery.status === 'loading' ? (
                <LoadingState label="Loading session status…" />
              ) : !displayedStatus && statusQuery.status === 'error' ? (
                <ErrorState error={statusQuery.error} onRetry={statusQuery.refetch} />
              ) : isSyncing ? (
                <p className="wa-session-feedback wa-session-feedback--syncing" role="status">
                  Checking status…
                </p>
              ) : null}

              <div className="wa-session-card__actions">
                <Button
                  variant="primary"
                  disabled={busyAction !== null || isSyncing}
                  onClick={() => runAction('start', startSession)}
                >
                  <Play size={16} strokeWidth={1.75} aria-hidden="true" />
                  {busyAction === 'start' ? ACTION_VERB_ING.start : 'Start'}
                </Button>
                <Button
                  variant="secondary"
                  disabled={busyAction !== null || isSyncing}
                  onClick={() => runAction('restart', restartSession)}
                >
                  <RefreshCw size={16} strokeWidth={1.75} aria-hidden="true" />
                  {busyAction === 'restart' ? ACTION_VERB_ING.restart : 'Restart'}
                </Button>
                <Button variant="danger" disabled={busyAction !== null || isSyncing} onClick={() => setConfirmAction('stop')}>
                  <Square size={16} strokeWidth={1.75} aria-hidden="true" />
                  Stop
                </Button>
                <Button variant="danger" disabled={busyAction !== null || isSyncing} onClick={() => setConfirmAction('logout')}>
                  <LogOut size={16} strokeWidth={1.75} aria-hidden="true" />
                  Logout
                </Button>
                <Button variant="secondary" disabled={busyAction !== null} onClick={() => setPairingOpen(true)}>
                  <QrCode size={16} strokeWidth={1.75} aria-hidden="true" />
                  Pair device
                </Button>
              </div>

              {feedback ? (
                feedback.kind === 'error' ? (
                  <ErrorState error={feedback.error} />
                ) : feedback.kind === 'unknown' ? (
                  <p className="wa-session-feedback wa-session-feedback--unknown" role="status">
                    The {ACTION_LABEL[feedback.action].toLowerCase()} request timed out before a response arrived — the
                    session may or may not have been affected. Check the status above, or try again.
                  </p>
                ) : (
                  <p className="wa-session-feedback wa-session-feedback--success" role="status">
                    {ACTION_LABEL[feedback.action]} succeeded.
                  </p>
                )
              ) : null}
            </div>
          </Card>

          <ConfirmDialog
            open={confirmAction !== null}
            title={confirmAction === 'stop' ? 'Stop this session?' : 'Log out this session?'}
            description={
              confirmAction === 'stop'
                ? 'This stops the WhatsApp session. You can start it again afterward.'
                : 'This logs the WhatsApp session out. You will need to pair again (QR or pairing code) to reconnect.'
            }
            confirmLabel={confirmAction ? ACTION_LABEL[confirmAction] : 'Confirm'}
            busy={busyAction === confirmAction}
            onCancel={() => setConfirmAction(null)}
            onConfirm={handleConfirmed}
          />

          <PairingModal open={pairingOpen} onClose={() => setPairingOpen(false)} sessionName={sessionName} />
        </>
      )}
    </div>
  );
}

function PairingModal({ open, onClose, sessionName }: { open: boolean; onClose: () => void; sessionName: string }) {
  const [mode, setMode] = useState<'qr' | 'phone'>('qr');

  const qrQuery = useApiQuery<SessionQrResult | null>(async () => {
    if (!open || mode !== 'qr') return { ok: true, data: null };
    return getSessionQr(sessionName);
  }, [open, mode, sessionName]);

  const [phoneNumber, setPhoneNumber] = useState('');
  const [pairingBusy, setPairingBusy] = useState(false);
  const [pairingResult, setPairingResult] = useState<
    { kind: 'code'; data: SessionPairingCodeResult } | { kind: 'unknown' } | { kind: 'error'; error: ApiError } | null
  >(null);

  async function handleRequestPairingCode() {
    const trimmed = phoneNumber.trim();
    if (!trimmed || pairingBusy) return;
    setPairingBusy(true);
    setPairingResult(null);
    const result = await requestPairingCode(sessionName, trimmed);
    setPairingBusy(false);
    if (!result.ok) {
      setPairingResult({ kind: 'error', error: result.error });
      return;
    }
    setPairingResult(result.data.outcome === 'unknown' ? { kind: 'unknown' } : { kind: 'code', data: result.data });
  }

  return (
    <Modal open={open} onClose={onClose} title="Pair a device">
      <div className="wa-pairing-modal__tabs">
        <Button variant={mode === 'qr' ? 'primary' : 'ghost'} onClick={() => setMode('qr')}>
          QR code
        </Button>
        <Button variant={mode === 'phone' ? 'primary' : 'ghost'} onClick={() => setMode('phone')}>
          Phone number
        </Button>
      </div>

      {mode === 'qr' ? (
        <div className="wa-pairing-modal__section">
          {qrQuery.status === 'loading' ? (
            <LoadingState label="Loading QR code…" />
          ) : qrQuery.status === 'error' ? (
            <ErrorState error={qrQuery.error} onRetry={qrQuery.refetch} />
          ) : qrQuery.data === null ? null : qrQuery.data.outcome === 'unknown' ? (
            <p className="wa-session-feedback wa-session-feedback--unknown" role="status">
              Could not confirm the QR request before it timed out — try refreshing.
            </p>
          ) : qrQuery.data.format === 'image' && typeof qrQuery.data.data === 'string' ? (
            // WAHA's exact image subtype isn't forwarded by the BFF
            // (bff/src/routes/session.ts only reports format: 'image', not
            // the original content-type) — PNG is assumed as WAHA's
            // documented common case, not verified against a live
            // instance. Flagged here rather than silently guessed.
            <img
              className="wa-pairing-modal__qr-image"
              src={`data:image/png;base64,${qrQuery.data.data}`}
              alt="WhatsApp pairing QR code"
            />
          ) : (
            <>
              <p className="wa-session-feedback wa-session-feedback--unknown" role="status">
                WAHA returned this pairing data in a format this page doesn't render visually yet (its exact field
                shape isn't documented) — shown as raw data below.
              </p>
              <pre className="wa-pairing-modal__raw">{JSON.stringify(qrQuery.data?.data, null, 2)}</pre>
            </>
          )}
          <Button variant="secondary" onClick={qrQuery.refetch} disabled={qrQuery.status === 'loading'}>
            <RefreshCw size={16} strokeWidth={1.75} aria-hidden="true" />
            Refresh QR
          </Button>
        </div>
      ) : (
        <div className="wa-pairing-modal__section">
          <Input
            label="Phone number"
            placeholder="e.g. 628123456789"
            value={phoneNumber}
            onChange={(e) => setPhoneNumber(e.target.value)}
            disabled={pairingBusy}
          />
          <Button variant="primary" onClick={handleRequestPairingCode} disabled={pairingBusy || !phoneNumber.trim()}>
            {pairingBusy ? 'Requesting…' : 'Request pairing code'}
          </Button>
          {pairingResult?.kind === 'code' ? (
            <p className="wa-pairing-modal__code">{pairingResult.data.code ?? 'No code returned'}</p>
          ) : pairingResult?.kind === 'unknown' ? (
            <p className="wa-session-feedback wa-session-feedback--unknown" role="status">
              The request timed out before a response arrived — try again.
            </p>
          ) : pairingResult?.kind === 'error' ? (
            <ErrorState error={pairingResult.error} />
          ) : null}
        </div>
      )}
    </Modal>
  );
}
