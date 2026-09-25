import { useEffect, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';

import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import { Modal } from '../components/ui/Modal';
import { PageHeader } from '../components/ui/PageHeader';
import { mapBlastCampaignStatus, mapBlastRecipientStatus, StatusBadge } from '../components/ui/StatusBadge';
import type { ApiError } from '../lib/api';
import {
  approveBlastCampaign,
  getBlastCampaign,
  getMe,
  rejectBlastCampaign,
  resolveBlastRecipient,
  submitBlastCampaign,
  type BlastCampaignDetail,
  type BlastCampaignStatus,
  type BlastRecipientStatus,
} from '../lib/djangoApi';
import { useApiQuery } from '../lib/useApiQuery';
import { useAuth } from '../lib/AuthContext';
import './BlastPage.css';

// Same inline scope-check idiom as InboxPage.tsx/BlastListPage.tsx — no
// new scope-checking utility (task requirement).
const BLAST_SCOPE = 'blast';
const SYSTEM_ADMINISTRATION_SCOPE = 'system administration';

const BLAST_STATUS_LABEL: Record<BlastCampaignStatus, string> = {
  draft: 'Draft',
  pending_approval: 'Pending approval',
  approved: 'Approved',
  sending: 'Sending',
  completed: 'Completed',
  rejected: 'Rejected',
  failed: 'Failed',
};

const RECIPIENT_STATUS_LABEL: Record<BlastRecipientStatus, string> = {
  pending: 'Pending',
  sending: 'Sending',
  sent: 'Sent',
  failed: 'Failed',
  skipped: 'Skipped',
};

function formatTimestamp(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '—';
}

// Client-side aggregation of the real per-recipient statuses the detail
// endpoint already returns (serializers.py's BlastRecipientSerializer) —
// not a fabricated progress bar (task Section 5's explicit constraint).
function countByStatus(campaign: BlastCampaignDetail): Record<BlastRecipientStatus, number> {
  const counts: Record<BlastRecipientStatus, number> = { pending: 0, sending: 0, sent: 0, failed: 0, skipped: 0 };
  for (const recipient of campaign.recipients) {
    counts[recipient.status] += 1;
  }
  return counts;
}

export function BlastDetailPage() {
  const params = useParams<{ id: string }>();
  const campaignId = Number(params.id);
  const navigate = useNavigate();
  const { claims } = useAuth();

  const campaignQuery = useApiQuery(() => getBlastCampaign(campaignId), [campaignId]);
  const meQuery = useApiQuery(() => getMe(), []);

  const [campaign, setCampaign] = useState<BlastCampaignDetail | null>(null);
  useEffect(() => {
    if (campaignQuery.status === 'success') setCampaign(campaignQuery.data);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignQuery.status === 'success' ? campaignQuery.data : campaignQuery.status]);

  const isCreator = meQuery.status === 'success' && campaign !== null && meQuery.data.username === campaign.created_by;
  const canSubmit = (claims?.scopes.includes(BLAST_SCOPE) ?? false) && isCreator;
  const canApprove = (claims?.scopes.includes(SYSTEM_ADMINISTRATION_SCOPE) ?? false) && !isCreator;
  // Reject has NO creator restriction server-side (backend/apps/blast/views.py
  // BlastCampaignRejectView — unlike ApproveView, it never checks
  // created_by_id), so this UI doesn't invent one either.
  const canReject = claims?.scopes.includes(SYSTEM_ADMINISTRATION_SCOPE) ?? false;
  // Phase 11 stuck-recovery fix (backend/apps/blast/views.py's
  // BlastRecipientResolveView) — same admin gate as approve/reject, no
  // creator restriction (recovering a stuck send is not a self-approval
  // concern).
  const canRecover = claims?.scopes.includes(SYSTEM_ADMINISTRATION_SCOPE) ?? false;

  // ---- Submit --------------------------------------------------------------
  const [submitBusy, setSubmitBusy] = useState(false);
  const [submitFeedback, setSubmitFeedback] = useState<{ kind: 'error'; error: ApiError } | null>(null);

  async function handleSubmit() {
    if (!campaign || submitBusy) return;
    setSubmitBusy(true);
    setSubmitFeedback(null);
    const result = await submitBlastCampaign(campaign.id);
    setSubmitBusy(false);
    if (!result.ok) {
      setSubmitFeedback({ kind: 'error', error: result.error });
      return;
    }
    setCampaign(result.data);
  }

  // ---- Approve --------------------------------------------------------------
  const [approveConfirmOpen, setApproveConfirmOpen] = useState(false);
  const [approveBusy, setApproveBusy] = useState(false);
  const [approveFeedback, setApproveFeedback] = useState<{ kind: 'error'; error: ApiError } | null>(null);

  async function handleApproveConfirmed() {
    if (!campaign || approveBusy) return;
    setApproveBusy(true);
    setApproveFeedback(null);
    const result = await approveBlastCampaign(campaign.id);
    setApproveBusy(false);
    setApproveConfirmOpen(false);
    if (!result.ok) {
      // Covers the 409 'daily_budget_exceeded' case (views.py:171-179) as
      // an ApiError.kind: 'validation' with the backend's own message,
      // via the existing 400/409 -> 'validation' mapping in lib/api.ts.
      setApproveFeedback({ kind: 'error', error: result.error });
      return;
    }
    setCampaign(result.data);
  }

  // ---- Reject (reason is optional server-side — serializers.py's
  // BlastCampaignRejectSerializer) ------------------------------------------
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [rejectBusy, setRejectBusy] = useState(false);
  const [rejectFeedback, setRejectFeedback] = useState<{ kind: 'error'; error: ApiError } | null>(null);

  async function handleRejectConfirmed() {
    if (!campaign || rejectBusy) return;
    setRejectBusy(true);
    setRejectFeedback(null);
    const result = await rejectBlastCampaign(campaign.id, rejectReason.trim());
    setRejectBusy(false);
    if (!result.ok) {
      setRejectFeedback({ kind: 'error', error: result.error });
      return;
    }
    setCampaign(result.data);
    setRejectOpen(false);
    setRejectReason('');
  }

  // ---- Resolve a stuck (`sending`) recipient (Phase 11 stuck-recovery fix) --
  const [resolveTarget, setResolveTarget] = useState<
    { recipientId: number; destination: string; status: 'sent' | 'failed' } | null
  >(null);
  const [resolveBusy, setResolveBusy] = useState(false);
  const [resolveFeedback, setResolveFeedback] = useState<{ kind: 'error'; error: ApiError } | null>(null);

  async function handleResolveConfirmed() {
    if (!campaign || !resolveTarget || resolveBusy) return;
    setResolveBusy(true);
    setResolveFeedback(null);
    const result = await resolveBlastRecipient(campaign.id, resolveTarget.recipientId, resolveTarget.status);
    setResolveBusy(false);
    if (!result.ok) {
      // Covers 409 'not_sending' (already resolved/still in-flight) and
      // 409 'concurrent_state_change' (raced the original dispatch task
      // or another recovery call) as an ApiError.kind: 'validation'.
      setResolveFeedback({ kind: 'error', error: result.error });
      return;
    }
    setCampaign(result.data);
    setResolveTarget(null);
  }

  return (
    <div>
      <Button variant="ghost" className="wa-blast-back" onClick={() => navigate('/blast')}>
        <ArrowLeft size={16} strokeWidth={1.75} aria-hidden="true" />
        Back to campaigns
      </Button>

      {campaignQuery.status === 'loading' && campaign === null ? (
        <LoadingState label="Loading campaign…" />
      ) : campaignQuery.status === 'error' && campaign === null ? (
        <ErrorState error={campaignQuery.error} onRetry={campaignQuery.refetch} />
      ) : campaign === null ? null : (
        <>
          <PageHeader
            title={campaign.name}
            description={`Session ${campaign.session} · Created by ${campaign.created_by}`}
            actions={<StatusBadge status={mapBlastCampaignStatus(campaign.status)} label={BLAST_STATUS_LABEL[campaign.status]} />}
          />

          <Card>
            <div className="wa-blast-detail__grid">
              <div>
                <p className="wa-blast-detail__fact-label">Session</p>
                <p className="wa-blast-detail__fact-value">{campaign.session}</p>
              </div>
              <div>
                <p className="wa-blast-detail__fact-label">Recipients</p>
                <p className="wa-blast-detail__fact-value">{campaign.recipient_count}</p>
              </div>
              <div>
                <p className="wa-blast-detail__fact-label">Created</p>
                <p className="wa-blast-detail__fact-value">{formatTimestamp(campaign.created_at)}</p>
              </div>
              <div>
                <p className="wa-blast-detail__fact-label">Last updated</p>
                <p className="wa-blast-detail__fact-value">{formatTimestamp(campaign.updated_at)}</p>
              </div>
              <div>
                <p className="wa-blast-detail__fact-label">Approved by</p>
                <p className="wa-blast-detail__fact-value">{campaign.approved_by ?? '—'}</p>
              </div>
              <div>
                <p className="wa-blast-detail__fact-label">Approved at</p>
                <p className="wa-blast-detail__fact-value">{formatTimestamp(campaign.approved_at)}</p>
              </div>
            </div>

            <p className="wa-blast-detail__fact-label">Message template</p>
            <p className="wa-blast-detail__template">{campaign.message_template}</p>

            {campaign.status === 'rejected' && campaign.rejected_reason ? (
              <p className="wa-blast-detail__rejected-reason">
                <strong>Rejection reason:</strong> {campaign.rejected_reason}
              </p>
            ) : null}
          </Card>

          <div className="wa-blast-detail__actions">
            {campaign.status === 'draft' && canSubmit ? (
              <Button variant="primary" disabled={submitBusy} onClick={handleSubmit}>
                {submitBusy ? 'Submitting…' : 'Submit for approval'}
              </Button>
            ) : null}
            {campaign.status === 'pending_approval' && canApprove ? (
              <Button variant="primary" disabled={approveBusy} onClick={() => setApproveConfirmOpen(true)}>
                Approve
              </Button>
            ) : null}
            {campaign.status === 'pending_approval' && canReject ? (
              <Button variant="danger" disabled={rejectBusy} onClick={() => setRejectOpen(true)}>
                Reject
              </Button>
            ) : null}
          </div>

          {submitFeedback?.kind === 'error' ? <ErrorState error={submitFeedback.error} /> : null}
          {approveFeedback?.kind === 'error' ? <ErrorState error={approveFeedback.error} /> : null}
          {rejectFeedback?.kind === 'error' && !rejectOpen ? <ErrorState error={rejectFeedback.error} /> : null}

          <ConfirmDialog
            open={approveConfirmOpen}
            title="Approve this campaign?"
            description={`Approving starts dispatch: ${campaign.recipient_count} message(s) will be queued and sent with a throttled delay between each. The server re-checks the session's remaining daily budget at approval time. This cannot be undone.`}
            confirmLabel="Approve"
            variant="primary"
            busy={approveBusy}
            onCancel={() => setApproveConfirmOpen(false)}
            onConfirm={handleApproveConfirmed}
          />

          <Modal open={rejectOpen} onClose={() => setRejectOpen(false)} title="Reject this campaign?">
            <div className="wa-blast-reject-modal">
              <p className="wa-confirm-dialog__description">
                Rejecting is terminal — this campaign cannot be resubmitted. Dispatch never starts.
              </p>
              <div className="wa-blast-form__field">
                <label className="wa-blast-form__label" htmlFor="blast-reject-reason">
                  Reason (optional)
                </label>
                <textarea
                  id="blast-reject-reason"
                  className="wa-blast-form__textarea"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  disabled={rejectBusy}
                  rows={3}
                />
              </div>
              {rejectFeedback?.kind === 'error' && rejectOpen ? <ErrorState error={rejectFeedback.error} /> : null}
              <div className="wa-blast-reject-modal__actions">
                <Button variant="secondary" onClick={() => setRejectOpen(false)} disabled={rejectBusy}>
                  Cancel
                </Button>
                <Button variant="danger" onClick={handleRejectConfirmed} disabled={rejectBusy}>
                  {rejectBusy ? 'Rejecting…' : 'Reject'}
                </Button>
              </div>
            </div>
          </Modal>

          <Card>
            <p className="wa-blast-detail__fact-label">Dispatch progress</p>
            <div className="wa-blast-progress">
              {(() => {
                const counts = countByStatus(campaign);
                return (
                  <>
                    <StatusBadge status="healthy" label={`${counts.sent} sent`} />
                    <StatusBadge status="error" label={`${counts.failed} failed`} />
                    <StatusBadge status="syncing" label={`${counts.sending} sending`} />
                    <StatusBadge status="unknown" label={`${counts.pending} pending`} />
                    {counts.skipped > 0 ? <StatusBadge status="offline" label={`${counts.skipped} skipped`} /> : null}
                  </>
                );
              })()}
            </div>

            <div className="wa-blast-recipients__wrap">
              <table className="wa-blast-recipients">
                <thead>
                  <tr>
                    <th>Destination</th>
                    <th>Status</th>
                    <th>Scheduled for</th>
                    <th>Sent at</th>
                    <th>Failure reason</th>
                    {canRecover ? <th>Recovery</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {campaign.recipients.map((recipient) => (
                    <tr key={recipient.id}>
                      <td>{recipient.destination}</td>
                      <td>
                        <StatusBadge
                          status={mapBlastRecipientStatus(recipient.status)}
                          label={RECIPIENT_STATUS_LABEL[recipient.status]}
                        />
                      </td>
                      <td>{formatTimestamp(recipient.scheduled_for)}</td>
                      <td>{formatTimestamp(recipient.sent_at)}</td>
                      <td className="wa-blast-recipients__failure">{recipient.failure_reason || '—'}</td>
                      {canRecover ? (
                        <td className="wa-blast-recipients__recovery">
                          {recipient.status === 'sending' ? (
                            <div className="wa-blast-recipients__recovery-actions">
                              <Button
                                variant="secondary"
                                onClick={() =>
                                  setResolveTarget({ recipientId: recipient.id, destination: recipient.destination, status: 'sent' })
                                }
                              >
                                Mark sent
                              </Button>
                              <Button
                                variant="danger"
                                onClick={() =>
                                  setResolveTarget({ recipientId: recipient.id, destination: recipient.destination, status: 'failed' })
                                }
                              >
                                Mark failed
                              </Button>
                            </div>
                          ) : (
                            '—'
                          )}
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {resolveFeedback?.kind === 'error' ? <ErrorState error={resolveFeedback.error} /> : null}
          </Card>

          <ConfirmDialog
            open={resolveTarget !== null}
            title={resolveTarget?.status === 'sent' ? 'Mark this recipient as sent?' : 'Mark this recipient as failed?'}
            description={
              resolveTarget
                ? `${resolveTarget.destination} is stuck in "sending" — this app lost track of whether the ` +
                  `message actually went out (e.g. a worker crash). This does NOT resend anything; it only ` +
                  `records the outcome you've confirmed externally (e.g. by checking the actual WhatsApp chat). ` +
                  `Choose "${resolveTarget.status === 'sent' ? 'Mark sent' : 'Mark failed'}" only if you're sure.`
                : ''
            }
            confirmLabel={resolveTarget?.status === 'sent' ? 'Mark sent' : 'Mark failed'}
            variant={resolveTarget?.status === 'sent' ? 'primary' : 'danger'}
            busy={resolveBusy}
            onCancel={() => setResolveTarget(null)}
            onConfirm={handleResolveConfirmed}
          />
        </>
      )}
    </div>
  );
}
