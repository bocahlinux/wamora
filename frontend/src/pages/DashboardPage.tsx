import { useCallback, useEffect, useState } from 'react';
import { Activity, Database, MessageSquare, RefreshCw, Server, ShieldCheck, Smartphone, TriangleAlert, Webhook, Wifi, Zap } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import { PageHeader } from '../components/ui/PageHeader';
import { mapActivityResult, mapSyncStatus, mapWahaStatus, StatusBadge } from '../components/ui/StatusBadge';
import type { ApiError } from '../lib/api';
import { getBffHealth, getSessionStatus, type SessionStatus } from '../lib/bffApi';
import { config } from '../lib/config';
import type { ActivityItem, DashboardActivity, DashboardMessages, SyncStatus } from '../lib/djangoApi';
import {
  getBackendHealth,
  getDashboardActivity,
  getDashboardMessages,
  getDatabaseHealth,
  getRedisHealth,
  getSyncStatus,
  recoverSyncCheckpoint,
} from '../lib/djangoApi';
import { useApiQuery } from '../lib/useApiQuery';
import { useAuth } from '../lib/AuthContext';
import './DashboardPage.css';

// Recovery scope gate — same EXISTING JWT scope string ("system
// administration", backend: apps/authn/permissions.py
// HasSystemAdministrationScope) InboxPage.tsx already gates its own
// recovery button with. UX courtesy only; the backend remains the
// authoritative boundary. No new scope introduced.
const SYSTEM_ADMINISTRATION_SCOPE = 'system administration';

// Sync status card (Phase 9 offline/degraded-mode completion —
// docs/generated/PHASE-9-OFFLINE-DEGRADED-MODE-COMPLETION-REPORT.md):
// extends InboxPage.tsx's already-proven getSyncStatus/StatusBadge/
// possibly_stuck/recovery pattern to the Dashboard. Deliberately a
// page-local duplicate of Inbox's fetch/poll/recovery logic rather than a
// shared hook — see the completion report's Step 2 for the reasoning
// (Inbox's version is entangled with its own connectivity-indicator
// signal in a way that made a clean, risk-free extraction not worth it
// for ~25 lines of logic). SYNC_STATUS_POLL_MS is the same literal value
// as InboxPage.tsx's own (CHAT_LIST_POLL_MS * 4 = 8000 * 4), not
// re-derived from a Dashboard-local constant that doesn't otherwise
// exist, so the polling cadence for this data stays identical across
// both pages.
const SYNC_STATUS_POLL_MS = 32000;

const SYNC_STATUS_LABEL: Record<SyncStatus['sync_status'], string> = {
  healthy: 'Synced',
  running: 'Syncing',
  stale: 'Sync delayed',
  failed: 'Sync error',
  never_synced: 'Not synced',
};

function describeSyncDetail(status: SyncStatus): string {
  if (status.sync_status === 'never_synced') return 'No reconciliation run yet.';
  if (status.seconds_since_last_run !== null) {
    const minutes = Math.floor(status.seconds_since_last_run / 60);
    if (minutes < 1) return 'Last run less than a minute ago.';
    if (minutes < 60) return `Last run ${minutes} minute${minutes === 1 ? '' : 's'} ago.`;
    const hours = Math.floor(minutes / 60);
    return `Last run ${hours} hour${hours === 1 ? '' : 's'} ago.`;
  }
  if (status.last_run_at) return `Last run at ${new Date(status.last_run_at).toLocaleString()}.`;
  return 'Waiting for the next reconciliation run.';
}

// Row 2's activity feed is kept short by design (a dashboard summary, not
// a full history) — this is a display choice, not a backend limitation;
// the endpoint itself supports a larger ?limit= if a future page needs it.
const ACTIVITY_FEED_LIMIT = 8;

const ACTIVITY_TYPE_ICON: Record<ActivityItem['type'], LucideIcon> = {
  audit: ShieldCheck,
  webhook: Webhook,
};

type IconTint = 'primary' | 'blue' | 'blue-deep';

interface HealthCardProps {
  icon: LucideIcon;
  tint: IconTint;
  title: string;
  query: ReturnType<typeof useApiQuery<{ ok: boolean; detail: string }>>;
}

// Card layout (icon badge left; bold title + inline status badge; detail
// below) matches wamora-design-assets/assets/reference/wamora-frontend-reference.png's
// "Dashboard (Light/Dark Mode)" row 1 cards — each service's icon badge
// uses a distinct tint from the approved primary/blue palette (design
// spec Section 4), not one flat neutral gray for all three.
function HealthCard({ icon: Icon, tint, title, query }: HealthCardProps) {
  return (
    <Card className="wa-health-card">
      <div className={`wa-health-card__icon wa-health-card__icon--${tint}`}>
        <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
      </div>
      <div className="wa-health-card__body">
        <div className="wa-health-card__title-row">
          <p className="wa-health-card__title">{title}</p>
          {query.status === 'loading' ? null : query.status === 'error' ? (
            <StatusBadge status="error" label="Unreachable" />
          ) : (
            <StatusBadge status={query.data.ok ? 'healthy' : 'error'} label={query.data.ok ? 'Healthy' : 'Degraded'} />
          )}
        </div>
        {query.status === 'loading' ? (
          <LoadingState label="Checking…" />
        ) : (
          <p className="wa-health-card__detail">{query.status === 'error' ? 'Could not reach this service.' : query.data.detail}</p>
        )}
      </div>
    </Card>
  );
}

// Row 2, "messages today / message volume" (design spec Section 10).
// messages_today and every trend bucket come straight from GET
// /api/dashboard/messages/ — see docs/generated/PHASE-8-DASHBOARD-BACKEND-FOUNDATION-REPORT.md
// Section 4 for the exact contract. "Today" is the UTC calendar day
// (this project's only configured timezone — TIME_ZONE='UTC' in
// config/settings.py, also the convention docs/generated/PHASE-5-CELERY-REDIS.md
// already established for Celery to avoid a second time source), labeled
// explicitly below so it's never mistaken for the viewer's local day.
function MessagesCard({ query }: { query: ReturnType<typeof useApiQuery<DashboardMessages>> }) {
  return (
    <Card className="wa-metric-card">
      <div className="wa-health-card__icon wa-health-card__icon--primary">
        <MessageSquare size={20} strokeWidth={1.75} aria-hidden="true" />
      </div>
      <div className="wa-metric-card__body">
        <p className="wa-health-card__title">Messages Today</p>
        {query.status === 'loading' ? (
          <LoadingState label="Loading messages…" />
        ) : query.status === 'error' ? (
          <ErrorState error={query.error} onRetry={query.refetch} />
        ) : (
          <>
            <p className="wa-metric-card__count">{query.data.messages_today}</p>
            <div className="wa-metric-card__chart" role="img" aria-label="Messages per hour today, UTC">
              {query.data.trend.map((bucket) => {
                const max = Math.max(1, ...query.data.trend.map((b) => b.count));
                const hourLabel = new Date(bucket.hour).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });
                return (
                  <div
                    key={bucket.hour}
                    className="wa-metric-card__bar"
                    style={{ height: `${(bucket.count / max) * 100}%` }}
                    title={`${hourLabel} UTC — ${bucket.count} message${bucket.count === 1 ? '' : 's'}`}
                  />
                );
              })}
            </div>
            <p className="wa-health-card__detail">Hourly trend (UTC)</p>
          </>
        )}
      </div>
    </Card>
  );
}

// Row 2, "system activity feed" — merges AuditLog + WebhookEvent via GET
// /api/dashboard/activity/. Presentation (icon/status tone) is derived
// deterministically from the actual `type`/`result` the backend reports
// (StatusBadge.mapActivityResult); action/target are shown as the raw
// backend strings rather than an invented human-readable sentence.
function ActivityCard({ query }: { query: ReturnType<typeof useApiQuery<DashboardActivity>> }) {
  return (
    <Card className="wa-metric-card wa-metric-card--activity">
      <div className="wa-health-card__icon wa-health-card__icon--blue">
        <Activity size={20} strokeWidth={1.75} aria-hidden="true" />
      </div>
      <div className="wa-metric-card__body">
        <p className="wa-health-card__title">Recent Activity</p>
        {query.status === 'loading' ? (
          <LoadingState label="Loading activity…" />
        ) : query.status === 'error' ? (
          <ErrorState error={query.error} onRetry={query.refetch} />
        ) : query.data.results.length === 0 ? (
          <EmptyState icon={Activity} title="No recent activity" description="Nothing has happened yet." />
        ) : (
          <ul className="wa-activity-list">
            {query.data.results.map((item) => {
              const TypeIcon = ACTIVITY_TYPE_ICON[item.type];
              return (
                <li key={item.id} className="wa-activity-list__item">
                  <TypeIcon size={16} strokeWidth={1.75} aria-hidden="true" className="wa-activity-list__icon" />
                  <div className="wa-activity-list__body">
                    <p className="wa-activity-list__action">{item.action}</p>
                    <p className="wa-activity-list__target">{item.target || '—'}</p>
                  </div>
                  <StatusBadge status={mapActivityResult(item.result)} label={item.result} />
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
}

// Row 2, single-session WAHA status. Mirrors SessionsPage.tsx's own
// status display (same query, same StatusBadge/mapWahaStatus vocabulary)
// so "connected"/"disconnected"/"scanning QR"/etc. never diverge between
// the two pages. Deliberately does not poll (unlike SessionsPage's
// post-mutation settle-poller) — this card is read-only, so there's no
// mutation to settle after; a plain fetch-once-on-mount, refreshed like
// every other Dashboard card only on a full page reload.
function SessionsCard({ sessionName, query }: { sessionName: string; query: ReturnType<typeof useApiQuery<SessionStatus>> }) {
  return (
    <Card className="wa-metric-card">
      <div className="wa-health-card__icon wa-health-card__icon--blue-deep">
        <Smartphone size={20} strokeWidth={1.75} aria-hidden="true" />
      </div>
      <div className="wa-metric-card__body">
        <div className="wa-health-card__title-row">
          <p className="wa-health-card__title">WhatsApp Session</p>
          {!sessionName ? null : query.status === 'success' ? (
            <StatusBadge status={mapWahaStatus(query.data.status)} label={query.data.status ?? 'Unknown'} />
          ) : query.status === 'error' ? (
            <StatusBadge status="error" label="Unreachable" />
          ) : null}
        </div>
        {!sessionName ? (
          <EmptyState
            icon={Smartphone}
            title="No session configured"
            description="Set VITE_WAHA_SESSION_NAME to enable session status."
          />
        ) : query.status === 'loading' ? (
          <LoadingState label="Checking session…" />
        ) : query.status === 'error' ? (
          <p className="wa-health-card__detail">Could not reach this service.</p>
        ) : (
          <p className="wa-health-card__detail">{query.data.session}</p>
        )}
      </div>
    </Card>
  );
}

// Row 2, reconciliation sync-status card. Same session-scoped
// getSyncStatus read, StatusBadge/mapSyncStatus vocabulary, possibly_stuck
// warning chip and admin-gated manual-recovery action as InboxPage.tsx —
// see the module-level comment above for why this duplicates rather than
// shares Inbox's fetch/poll/recovery logic. This says nothing about
// WhatsApp/BFF connectivity (that's the WhatsApp Session card above); it
// is purely about reconciliation data freshness, matching Inbox's own
// "never say offline/disconnected here" discipline (StatusBadge.tsx's
// mapSyncStatus docstring).
function SyncStatusCard({ sessionName }: { sessionName: string }) {
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);

  const fetchSyncStatus = useCallback(async () => {
    if (!sessionName) return;
    const result = await getSyncStatus(sessionName);
    if (result.ok) {
      setSyncStatus(result.data);
      return;
    }
    if (result.error.kind === 'not_found') {
      // Django has never heard of this session name at all — treated
      // identically to a known session that hasn't been reconciled yet,
      // same as InboxPage.tsx's own fetchSyncStatus.
      setSyncStatus({
        session: sessionName,
        sync_status: 'never_synced',
        checkpoint_status: null,
        last_run_at: null,
        seconds_since_last_run: null,
        checkpoint_updated_at: null,
        possibly_stuck: false,
        last_webhook_received_at: null,
      });
      return;
    }
    // Connectivity-class failure — keep showing the last known sync status
    // rather than blanking it (same "freeze, don't blank" discipline used
    // throughout this app). The Dashboard's own health-row cards already
    // surface backend/BFF unreachability generally; this card doesn't need
    // a second, duplicate connectivity indicator.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionName]);

  useEffect(() => {
    setSyncStatus(null);
    if (!sessionName) return undefined;
    fetchSyncStatus();
    const interval = setInterval(fetchSyncStatus, SYNC_STATUS_POLL_MS);
    return () => clearInterval(interval);
  }, [sessionName, fetchSyncStatus]);

  const { claims } = useAuth();
  const canRecover = claims?.scopes.includes(SYSTEM_ADMINISTRATION_SCOPE) ?? false;

  const [recoveryConfirmOpen, setRecoveryConfirmOpen] = useState(false);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [recoveryFeedback, setRecoveryFeedback] = useState<
    { kind: 'success' } | { kind: 'error'; error: ApiError } | null
  >(null);

  async function handleRecoverConfirmed() {
    if (!sessionName || recoveryBusy) return;
    setRecoveryBusy(true);
    setRecoveryFeedback(null);
    const result = await recoverSyncCheckpoint(sessionName);
    setRecoveryBusy(false);
    setRecoveryConfirmOpen(false);
    if (!result.ok) {
      setRecoveryFeedback({ kind: 'error', error: result.error });
      return;
    }
    setRecoveryFeedback({ kind: 'success' });
    fetchSyncStatus();
  }

  return (
    <Card className="wa-metric-card">
      <div className="wa-health-card__icon wa-health-card__icon--primary">
        <RefreshCw size={20} strokeWidth={1.75} aria-hidden="true" />
      </div>
      <div className="wa-metric-card__body">
        <div className="wa-health-card__title-row">
          <p className="wa-health-card__title">Reconciliation Sync</p>
          {!sessionName ? null : syncStatus ? (
            <StatusBadge
              status={mapSyncStatus(syncStatus.sync_status, syncStatus.possibly_stuck)}
              label={SYNC_STATUS_LABEL[syncStatus.sync_status]}
            />
          ) : null}
        </div>
        {!sessionName ? (
          <EmptyState
            icon={RefreshCw}
            title="No session configured"
            description="Set VITE_WAHA_SESSION_NAME to enable sync status."
          />
        ) : !syncStatus ? (
          <LoadingState label="Checking sync status…" />
        ) : (
          <>
            <p className="wa-health-card__detail">{describeSyncDetail(syncStatus)}</p>
            {syncStatus.possibly_stuck ? (
              <div className="wa-metric-card__sync-stuck" role="status">
                <p className="wa-metric-card__sync-stuck-text">
                  <TriangleAlert size={14} strokeWidth={1.75} aria-hidden="true" />
                  Reconciliation may be stuck — running longer than expected.
                </p>
                {canRecover ? (
                  <Button variant="secondary" disabled={recoveryBusy} onClick={() => setRecoveryConfirmOpen(true)}>
                    Mark reconciliation as failed…
                  </Button>
                ) : null}
              </div>
            ) : null}
            {recoveryFeedback?.kind === 'success' ? (
              <p className="wa-metric-card__sync-recovery-feedback wa-metric-card__sync-recovery-feedback--success" role="status">
                Reconciliation for {sessionName} was marked as failed. A future run can start cleanly.
              </p>
            ) : recoveryFeedback?.kind === 'error' ? (
              <ErrorState error={recoveryFeedback.error} />
            ) : null}
          </>
        )}
      </div>

      {sessionName ? (
        <ConfirmDialog
          open={recoveryConfirmOpen}
          title={`Mark reconciliation for ${sessionName} as failed?`}
          description="Reconciliation is only suspected to be stuck — this is based on how long it has been running, not proof the process has stopped. Confirming will mark the current run as failed so a future reconciliation can start cleanly; it will not start a new run automatically, and this cannot be undone. Only continue if you believe this run is no longer active."
          confirmLabel="Mark as failed"
          busy={recoveryBusy}
          onCancel={() => setRecoveryConfirmOpen(false)}
          onConfirm={handleRecoverConfirmed}
        />
      ) : null}
    </Card>
  );
}

// Dashboard structure follows wamora-design-assets design spec Section 10
// ("Row 1 — system health", "Row 2 — sessions + activity"). Row 1's
// Redis card (docs/generated/PHASE9-1C-REDIS-HEALTH-IMPLEMENTATION-REPORT.md,
// PHASE9-1F-REDIS-DASHBOARD-IMPLEMENTATION-REPORT.md) reports only
// whether the Celery broker Redis responds to PING — it says nothing
// about Celery worker/beat liveness, a deliberately separate, unresolved
// question (see the 9.1F design audit's Section 4 boundary). Row 2's
// session card (docs/generated/NEXT-SESSIONS-CONNECTIVITY-IMPLEMENTATION-REPORT.md)
// shows the single configured session's live WAHA status (Frontend -> BFF
// -> WAHA, reusing SessionsPage.tsx's own getSessionStatus/mapWahaStatus)
// — a true multi-session summary still needs further BFF work the BFF
// doesn't have yet (docs/generated/PHASE-8-DASHBOARD-DATA-UI-AUDIT-REPORT.md),
// a remaining, documented gap, not a silent omission.
export function DashboardPage() {
  const wahaQuery = useApiQuery(async () => {
    const result = await getBffHealth();
    if (!result.ok) return result;
    return { ok: true, data: { ok: result.data.waha.reachable, detail: result.data.waha.reachable ? 'Connected' : 'Not reachable' } };
  }, []);

  const backendQuery = useApiQuery(async () => {
    const result = await getBackendHealth();
    if (!result.ok) return result;
    return { ok: true, data: { ok: result.data.status === 'ok', detail: 'Running' } };
  }, []);

  const databaseQuery = useApiQuery(async () => {
    const result = await getDatabaseHealth();
    if (!result.ok) return result;
    return { ok: true, data: { ok: result.data.status === 'ok', detail: 'Connected' } };
  }, []);

  const redisQuery = useApiQuery(async () => {
    const result = await getRedisHealth();
    if (!result.ok) return result;
    return {
      ok: true,
      data: {
        ok: result.data.status === 'ok',
        detail: result.data.status === 'ok' ? 'Connected' : 'Unreachable',
      },
    };
  }, []);

  const messagesQuery = useApiQuery(() => getDashboardMessages(), []);
  const activityQuery = useApiQuery(() => getDashboardActivity(ACTIVITY_FEED_LIMIT), []);

  const sessionName = config.wahaSessionName;
  const sessionQuery = useApiQuery(() => getSessionStatus(sessionName), [sessionName]);

  return (
    <div>
      <PageHeader title="Dashboard" description="Overview of your WhatsApp operations and system status" />

      <section className="wa-dashboard__health-row" aria-label="System health">
        <HealthCard icon={Wifi} tint="primary" title="WAHA" query={wahaQuery} />
        <HealthCard icon={Server} tint="blue" title="Backend (Django)" query={backendQuery} />
        <HealthCard icon={Database} tint="blue-deep" title="PostgreSQL" query={databaseQuery} />
        <HealthCard icon={Zap} tint="primary" title="Redis" query={redisQuery} />
      </section>

      <section className="wa-dashboard__row2" aria-label="Messages, activity, sessions and sync status">
        <MessagesCard query={messagesQuery} />
        <ActivityCard query={activityQuery} />
        <SessionsCard sessionName={sessionName} query={sessionQuery} />
        <SyncStatusCard sessionName={sessionName} />
      </section>
    </div>
  );
}
