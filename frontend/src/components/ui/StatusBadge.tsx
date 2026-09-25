import { CircleCheck, CircleOff, Info, LoaderCircle, QrCode, RefreshCw, TriangleAlert, type LucideIcon, CircleX } from 'lucide-react';

import { Badge, type BadgeTone } from './Badge';
import './StatusBadge.css';

// wamora-design-assets design spec Section 9: "Status must be understandable
// without relying only on color." The reference boards (assets/reference/)
// pair each status pill with a small semantic icon, not a bare color dot —
// icons reused from the spec's own Lucide mapping (Section 6) where one is
// named there (Success/Warning/Error/Info/QR); reasonable same-family
// choices for the remaining statuses the table doesn't cover.
export type StatusKind = 'healthy' | 'working' | 'scan_qr' | 'starting' | 'syncing' | 'warning' | 'error' | 'offline' | 'unknown';

const STATUS_MAP: Record<StatusKind, { label: string; tone: BadgeTone; icon: LucideIcon }> = {
  healthy: { label: 'Healthy', tone: 'success', icon: CircleCheck },
  working: { label: 'Working', tone: 'success', icon: CircleCheck },
  starting: { label: 'Starting', tone: 'info', icon: LoaderCircle },
  scan_qr: { label: 'Scan QR', tone: 'warning', icon: QrCode },
  syncing: { label: 'Syncing', tone: 'info', icon: RefreshCw },
  warning: { label: 'Warning', tone: 'warning', icon: TriangleAlert },
  error: { label: 'Error', tone: 'error', icon: CircleX },
  offline: { label: 'Offline', tone: 'offline', icon: CircleOff },
  unknown: { label: 'Unknown', tone: 'neutral', icon: Info },
};

interface StatusBadgeProps {
  status: StatusKind;
  label?: string;
}

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const entry = STATUS_MAP[status];
  const Icon = entry.icon;
  return (
    <Badge tone={entry.tone}>
      <Icon size={12} strokeWidth={2} aria-hidden="true" className="wa-status-icon" />
      {label ?? entry.label}
    </Badge>
  );
}

/** Maps a raw WAHA session status string (contract-defined, e.g. WORKING,
 * SCAN_QR_CODE, STOPPED, FAILED, STARTING) into the visual vocabulary
 * above — spec Section 9: "The exact backend values must follow the
 * actual API contract; the UI may map them into the visual system." Never
 * invents a status the backend didn't report; anything unrecognized falls
 * back to 'unknown' rather than guessing. */
export function mapWahaStatus(raw: string | undefined): StatusKind {
  switch (raw) {
    case 'WORKING':
      return 'working';
    case 'SCAN_QR_CODE':
      return 'scan_qr';
    case 'STARTING':
      return 'starting';
    case 'STOPPED':
      return 'offline';
    case 'FAILED':
      return 'error';
    default:
      return 'unknown';
  }
}

/** Maps Phase 9.1A's sync-status endpoint's raw `sync_status` string
 * (docs/generated/PHASE9-1A-SYNC-STATUS-IMPLEMENTATION-REPORT.md) into the
 * same visual vocabulary above — deliberately scoped to *data freshness*
 * only, never to WhatsApp/connectivity state (see
 * docs/generated/PHASE9-1E-DESIGN-AUDIT-REPORT.md Section 3/4): no label
 * anywhere here says or implies "offline"/"disconnected"/"WhatsApp". Never
 * invents a status the backend didn't report — an unrecognized value
 * falls back to 'unknown' rather than guessing, same as the two mappers
 * above. */
export function mapSyncStatus(raw: string | undefined): StatusKind {
  switch (raw) {
    case 'healthy':
      return 'healthy';
    case 'running':
      return 'syncing';
    case 'stale':
      return 'warning';
    case 'failed':
      return 'error';
    case 'never_synced':
      return 'unknown';
    default:
      return 'unknown';
  }
}

/** Maps the Phase 8 dashboard activity feed's raw `result` string
 * (AuditLog: 'success'/'failure'; WebhookEvent: 'pending'/'processed'/
 * 'failed'/'unsupported' — apps/audit/models.py, apps/webhooks/models.py)
 * into the same visual vocabulary as mapWahaStatus above. Never invents a
 * result the backend didn't report — anything unrecognized falls back to
 * 'unknown' rather than guessing. */
export function mapActivityResult(raw: string): StatusKind {
  switch (raw) {
    case 'success':
    case 'processed':
      return 'healthy';
    case 'pending':
      return 'starting';
    case 'failure':
    case 'failed':
      return 'error';
    case 'unsupported':
      return 'warning';
    default:
      return 'unknown';
  }
}
