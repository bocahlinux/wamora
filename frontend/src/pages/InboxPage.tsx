import { useCallback, useEffect, useRef, useState } from 'react';
import { LogIn, MessageCircle, Paperclip, Send, TriangleAlert, Users, WifiOff } from 'lucide-react';

import { Button } from '../components/ui/Button';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import { Modal } from '../components/ui/Modal';
import { PageHeader } from '../components/ui/PageHeader';
import { mapSyncStatus, StatusBadge } from '../components/ui/StatusBadge';
import type { ApiError, ApiResult } from '../lib/api';
import { sendMessage } from '../lib/bffApi';
import {
  assignChat,
  getChatMessages,
  getChatOperators,
  getChats,
  getMe,
  getSyncStatus,
  markChatRead,
  recoverSyncCheckpoint,
  unassignChat,
  updateOperatorAvailability,
  type ChatMessage,
  type ChatSummary,
  type OperatorCandidate,
  type SyncStatus,
} from '../lib/djangoApi';
import { config } from '../lib/config';
import { useApiQuery } from '../lib/useApiQuery';
import { useAuth } from '../lib/AuthContext';
import './InboxPage.css';

// Recovery scope gate (Phase 13.B) — reuses the EXISTING JWT scope string
// "system administration" (backend: apps/authn/permissions.py
// HasSystemAdministrationScope), which already gates
// POST /api/sync/recover/:session/ server-side. Hiding the button for a
// caller whose token lacks this scope is a UX courtesy only — the backend
// remains the actual authorization boundary (lib/auth.ts's own
// decodeToken() docstring: "the frontend must never make a security
// decision based on this decoded value alone"). No new scope is
// introduced anywhere.
const SYSTEM_ADMINISTRATION_SCOPE = 'system administration';

// Inbox/Chat (canonical Phase 8) — docs/generated/INBOX-CHAT-DECISION-REPORT.md.
// Request paths, chosen there and reused as-is here:
//   - chat list / message history: Frontend -> Django direct (lib/djangoApi.ts)
//   - send message: Frontend -> BFF -> WAHA, the EXISTING sendText endpoint
//     (lib/bffApi.ts's sendMessage()) — no second send implementation.
// Real-time: plain polling (Section 3 of the decision report explicitly
// defers WebSocket/SSE) — CHAT_LIST_POLL_MS / MESSAGES_POLL_MS below,
// chosen conservative on purpose. Mark-as-read is chat-level, Django-only,
// never synced to WAHA (Section 2).
const CHAT_LIST_POLL_MS = 8000;
const MESSAGES_POLL_MS = 5000;

// Connectivity indicator (Phase 9.1D — docs/generated/PHASE9-1-DESIGN-AUDIT-REPORT.md
// Section 5/7 "Signal A"). Frontend-only: derived entirely from the
// existing ApiError.kind taxonomy already returned by every request
// (lib/api.ts) — no new backend endpoint. Deliberately silent for a single
// isolated poll failure (requires CONNECTIVITY_FAILURE_THRESHOLD
// *consecutive* non-auth failures before showing anything) so a one-off
// blip never flickers a banner in and out every 5-8s; a single success at
// any point resets it immediately. This says nothing about whether
// reconciliation/sync data is current (Signal B, not built by this task)
// or whether WhatsApp itself has new activity — it only reports whether
// this page's own requests to the backend are succeeding right now.
const CONNECTIVITY_FAILURE_THRESHOLD = 2;

type ConnectivityIssue = 'unreachable' | 'unauthorized';

// Sync status (Phase 9.1E — docs/generated/PHASE9-1E-DESIGN-AUDIT-REPORT.md
// Section 6). A multiple of CHAT_LIST_POLL_MS, not an independently
// invented interval: the underlying data (SyncCheckpoint) changes far
// more slowly than chat/message content — RECONCILIATION_INTERVAL_SECONDS
// defaults to 900s backend-side — so polling this every 8s would be
// needlessly frequent. Mirrors the backend view's own
// STALE_THRESHOLD_MULTIPLIER philosophy: a multiplier on an existing
// constant, not a new independent number.
const SYNC_STATUS_POLL_MS = CHAT_LIST_POLL_MS * 4;

const SYNC_STATUS_LABEL: Record<SyncStatus['sync_status'], string> = {
  healthy: 'Synced',
  running: 'Syncing',
  stale: 'Sync delayed',
  failed: 'Sync error',
  never_synced: 'Not synced',
};

function mergeNewestFirst(existing: ChatMessage[], freshPage1: ChatMessage[]): ChatMessage[] {
  const existingIds = new Set(existing.map((m) => m.id));
  const newOnes = freshPage1.filter((m) => !existingIds.has(m.id));
  if (newOnes.length === 0) return existing;
  return [...newOnes, ...existing];
}

// Display-identity fix — docs/generated/INBOX-IDENTITY-DISPLAY-AUDIT-REPORT.md.
// No identity merge, no new resolution — just a display fallback over
// fields the API already exposes: a real name (Chat.name or the
// Contact's PushName-derived display_name) first, else the Contact's
// phone number, else the raw provider chat ID exactly as before this
// fix. The phone number is shown as secondary information only when a
// real name is already the primary line, to avoid showing it twice.
function chatDisplay(chat: ChatSummary): { primary: string; secondary: string | null } {
  const friendlyName = chat.name || chat.contact_name;
  if (friendlyName) return { primary: friendlyName, secondary: chat.phone_number };
  if (chat.phone_number) return { primary: chat.phone_number, secondary: null };
  return { primary: chat.provider_chat_id, secondary: null };
}

export function InboxPage() {
  const sessionName = config.wahaSessionName;

  // ---- Connectivity indicator (Phase 9.1D) -------------------------------
  // Fed only by the two background polling loops below (chat list,
  // messages) — deliberately not by the first-load queries (which already
  // have their own ErrorState + manual retry) or by write actions
  // (send/mark-as-read, which already have their own feedback). One
  // combined signal for both loops, not two separate indicators, since in
  // practice a Django/network outage affects both simultaneously (design
  // report Section 7's recommended default).
  const [connectivityIssue, setConnectivityIssue] = useState<ConnectivityIssue | null>(null);
  const connectivityFailureCountRef = useRef(0);

  function reportPollOutcome(result: ApiResult<unknown>) {
    if (result.ok) {
      connectivityFailureCountRef.current = 0;
      setConnectivityIssue(null);
      return;
    }
    if (result.error.kind === 'unauthorized' || result.error.kind === 'forbidden') {
      // Not a connectivity problem — never mislabel this as "server
      // offline" (the task's explicit requirement). In practice
      // AuthContext's own JWT-expiry timer already redirects to /login
      // before this is usually seen; this covers the narrower case of a
      // server-side 401/403 the client's own decoded expiry didn't
      // predict. No threshold delay — retrying will not fix this, so
      // there's no reason to wait for a second failure.
      connectivityFailureCountRef.current = 0;
      setConnectivityIssue('unauthorized');
      return;
    }
    // Every other ApiError.kind (network_error, timeout, server_error,
    // not_found, validation, unknown) is treated uniformly as
    // connectivity-class — the existing taxonomy already distinguishes
    // "auth" from everything else, and this indicator does not need a
    // finer split than that.
    connectivityFailureCountRef.current += 1;
    if (connectivityFailureCountRef.current >= CONNECTIVITY_FAILURE_THRESHOLD) {
      setConnectivityIssue('unreachable');
    }
  }

  // ---- Sync status (Phase 9.1E) ------------------------------------------
  // Independent of chat-list/messages polling — a page-level,
  // session-scoped signal, not tied to selectedChatId (design report
  // Section 5). No dedicated loading/error UI is needed (Section 3: "not
  // yet fetched" renders nothing), so this is one effect — an immediate
  // fetch plus its own interval — rather than useApiQuery's separate
  // first-load/poll split, which exists specifically to drive a
  // LoadingState/ErrorState this feature doesn't need.
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);

  // Phase 13.B: pulled out of the polling useEffect below (unchanged
  // otherwise) so the post-recovery refetch (handleRecoverConfirmed
  // further down) can reuse this exact same read — no second/duplicate
  // fetch implementation, no new polling loop.
  const fetchSyncStatus = useCallback(async () => {
    if (!sessionName) return;
    const result = await getSyncStatus(sessionName);
    if (result.ok) {
      setSyncStatus(result.data);
      reportPollOutcome(result);
      return;
    }
    if (result.error.kind === 'not_found') {
      // Django has never heard of this session name at all — not a
      // connectivity problem (never fed into reportPollOutcome).
      // Treated identically to a known session that simply hasn't been
      // reconciled yet (design report Section 9).
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
    // Connectivity-class failure — keep showing the last known sync
    // status rather than blanking it, the same "freeze, don't blank"
    // discipline the chat list/messages polls already use below.
    reportPollOutcome(result);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionName]);

  useEffect(() => {
    // Reset immediately so a previous session's status is never shown
    // against a new session (defensive — config.wahaSessionName is a
    // static build-time value in practice, but this keeps the guarantee
    // explicit rather than assumed).
    setSyncStatus(null);
    if (!sessionName) return undefined;

    fetchSyncStatus();
    const interval = setInterval(fetchSyncStatus, SYNC_STATUS_POLL_MS);
    return () => clearInterval(interval);
  }, [sessionName, fetchSyncStatus]);

  // ---- Reconciliation recovery (Phase 13.B) --------------------------------
  // docs/generated/PHASE-13B-RECONCILIATION-DIAGNOSTICS-UI-DESIGN-AUDIT-REPORT.md
  // Section 6/9. Visible only when possibly_stuck === true AND the caller's
  // JWT carries the existing "system administration" scope (server-side
  // authoritative gate unchanged: HasSystemAdministrationScope). Reuses
  // ConfirmDialog (Section 6.3) and, on success, refetches sync status via
  // fetchSyncStatus above rather than fabricating the resulting status
  // locally (task requirement).
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
      // Covers 401/403 (already-categorized by lib/api.ts), 404, the
      // 409 concurrent_state_change / not_stale / not_running /
      // no_checkpoint cases (all surfaced as ApiError.kind: 'validation'
      // with the backend's own operator-appropriate message, per the
      // design audit Section 6.6), and any generic failure — no new
      // error-handling code, reuses the existing ErrorState/ApiError
      // taxonomy verbatim. Never auto-retried, never auto-reissued.
      setRecoveryFeedback({ kind: 'error', error: result.error });
      return;
    }
    setRecoveryFeedback({ kind: 'success' });
    // Refetch from the server rather than fabricating the resulting
    // status locally (task requirement) — reuses the existing read, no
    // new polling loop.
    fetchSyncStatus();
  }

  // ---- Operator assignment (Step 14 foundation) ----------------------------
  // Backend (apps.authn.permissions.HasOfficeAdminAccess) remains the sole
  // authority — `canManageAssignment` only decides whether to SHOW the
  // controls, mirroring `canRecover` above's own established pattern.
  const meQuery = useApiQuery(() => getMe(), []);
  const canManageAssignment =
    meQuery.status === 'success' && (meQuery.data.has_global_access || (meQuery.data.role?.is_office_admin ?? false));
  const isOperator = meQuery.status === 'success' && (meQuery.data.role?.is_operator ?? false);

  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [operatorsState, setOperatorsState] = useState<
    { status: 'loading' } | { status: 'success'; data: OperatorCandidate[] } | { status: 'error'; error: ApiError } | null
  >(null);
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignFeedback, setAssignFeedback] = useState<{ kind: 'error'; error: ApiError } | null>(null);

  function applyAssignedTo(chatId: number, assignedTo: ChatSummary['assigned_to']) {
    setChats((prev) => (prev ? prev.map((c) => (c.id === chatId ? { ...c, assigned_to: assignedTo } : c)) : prev));
  }

  async function openAssignModal() {
    if (!selectedChat) return;
    setAssignModalOpen(true);
    setAssignFeedback(null);
    setOperatorsState({ status: 'loading' });
    const result = await getChatOperators(selectedChat.id);
    setOperatorsState(result.ok ? { status: 'success', data: result.data } : { status: 'error', error: result.error });
  }

  async function handleAssign(userId: number) {
    if (!selectedChat || assignBusy) return;
    setAssignBusy(true);
    setAssignFeedback(null);
    const result = await assignChat(selectedChat.id, userId);
    setAssignBusy(false);
    if (!result.ok) {
      setAssignFeedback({ kind: 'error', error: result.error });
      return;
    }
    applyAssignedTo(selectedChat.id, result.data.assigned_to);
    setAssignModalOpen(false);
  }

  async function handleUnassign() {
    if (!selectedChat || assignBusy) return;
    setAssignBusy(true);
    const result = await unassignChat(selectedChat.id);
    setAssignBusy(false);
    if (!result.ok) return;
    applyAssignedTo(selectedChat.id, null);
  }

  // ---- Self availability toggle (Step 14) — only for an actual Operator ---
  // Current value always comes straight from /api/auth/me/'s own
  // `is_available` (never guessed/defaulted locally) — refetched after a
  // successful toggle so the displayed state always matches the server.
  const [availabilityBusy, setAvailabilityBusy] = useState(false);

  async function handleToggleAvailability() {
    if (meQuery.status !== 'success' || availabilityBusy) return;
    setAvailabilityBusy(true);
    await updateOperatorAvailability(!meQuery.data.is_available);
    setAvailabilityBusy(false);
    meQuery.refetch();
  }

  // ---- Chat list --------------------------------------------------------
  const chatsQuery = useApiQuery(() => getChats(1), []);
  const [chats, setChats] = useState<ChatSummary[] | null>(null);

  useEffect(() => {
    if (chatsQuery.status === 'success') setChats(chatsQuery.data.results);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatsQuery.status === 'success' ? chatsQuery.data : chatsQuery.status]);

  useEffect(() => {
    const interval = setInterval(async () => {
      const result = await getChats(1);
      // Silent background refresh — a transient failure just skips this
      // tick, it never replaces an already-shown, working chat list with
      // an error state. The connectivity indicator (Phase 9.1D) is the
      // only thing that reacts to a failed tick now.
      if (result.ok) setChats(result.data.results);
      reportPollOutcome(result);
    }, CHAT_LIST_POLL_MS);
    return () => clearInterval(interval);
  }, []);

  // ---- Selected chat / message history -----------------------------------
  const [selectedChatId, setSelectedChatId] = useState<number | null>(null);
  const selectedChat = chats?.find((c) => c.id === selectedChatId) ?? null;

  const messagesQuery = useApiQuery<{ results: ChatMessage[]; next: string | null } | null>(async () => {
    if (selectedChatId === null) return { ok: true, data: null };
    return getChatMessages(selectedChatId, 1);
  }, [selectedChatId]);

  const [messages, setMessages] = useState<ChatMessage[] | null>(null);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);

  useEffect(() => {
    setMessages(null);
    setNextPage(null);
  }, [selectedChatId]);

  useEffect(() => {
    if (messagesQuery.status === 'success' && messagesQuery.data) {
      setMessages(messagesQuery.data.results);
      setNextPage(messagesQuery.data.next ? 2 : null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messagesQuery.status === 'success' ? messagesQuery.data : messagesQuery.status]);

  useEffect(() => {
    if (selectedChatId === null) return undefined;
    const interval = setInterval(async () => {
      const result = await getChatMessages(selectedChatId, 1);
      if (result.ok) setMessages((prev) => mergeNewestFirst(prev ?? [], result.data.results));
      reportPollOutcome(result);
    }, MESSAGES_POLL_MS);
    return () => clearInterval(interval);
  }, [selectedChatId]);

  async function handleLoadOlder() {
    if (selectedChatId === null || nextPage === null || loadingOlder) return;
    setLoadingOlder(true);
    const result = await getChatMessages(selectedChatId, nextPage);
    setLoadingOlder(false);
    if (!result.ok) return;
    setMessages((prev) => [...(prev ?? []), ...result.data.results]);
    setNextPage(result.data.next ? nextPage + 1 : null);
  }

  // ---- Mark as read -------------------------------------------------------
  async function handleSelectChat(chat: ChatSummary) {
    setSelectedChatId(chat.id);
    if (!chat.unread) return;
    // Real API call, not a locally-fabricated state flip — the local
    // "unread: false" update below just mirrors what this call actually
    // just confirmed durably in Django.
    const result = await markChatRead(chat.id);
    if (!result.ok) return;
    setChats((prev) => (prev ? prev.map((c) => (c.id === chat.id ? { ...c, unread: false } : c)) : prev));
  }

  // ---- Composer -------------------------------------------------------------
  // Three-way send feedback (Phase 9.0 — docs/generated/PHASE9-DESIGN-AUDIT-REPORT.md
  // Section 10/12, docs/generated/PHASE9-0-UNKNOWN-SEND-OUTCOME-IMPLEMENTATION-REPORT.md):
  // mirrors SessionsPage.tsx's existing, proven ActionFeedback pattern for
  // the exact same ambiguity (a BFF/WAHA timeout — genuinely unknown
  // whether WhatsApp received it). Replaces the previous two independent
  // booleans (`sendError`/`sendConfirmed`), which could not represent
  // "sent, but ambiguous" as a distinct, renderable state.
  type SendFeedback = { kind: 'success' } | { kind: 'unknown' } | { kind: 'error'; error: ApiError };

  const [draftText, setDraftText] = useState('');
  const [sendBusy, setSendBusy] = useState(false);
  const [sendFeedback, setSendFeedback] = useState<SendFeedback | null>(null);

  async function handleSend() {
    const text = draftText.trim();
    if (!text || !selectedChat || !sessionName || sendBusy) return;
    setSendBusy(true);
    setSendFeedback(null);
    const result = await sendMessage(sessionName, selectedChat.provider_chat_id, text, crypto.randomUUID());
    setSendBusy(false);
    if (!result.ok) {
      setSendFeedback({ kind: 'error', error: result.error });
      return;
    }
    setDraftText('');
    // 'sent': the just-sent message reaches Django's durable copy only once
    // it round-trips through WAHA's own webhook or reconciliation, not
    // instantly — this confirms WAHA accepted the send, not that history
    // has caught up yet (never fabricate a local message bubble for what
    // hasn't actually been persisted). The polling loop above will pick it
    // up once it lands.
    // 'unknown': a BFF/WAHA timeout — whether WAHA even accepted the send
    // is itself unconfirmed. Never presented as success or as failure,
    // since neither is actually known.
    setSendFeedback(result.data.status === 'unknown' ? { kind: 'unknown' } : { kind: 'success' });
  }

  const listRef = useRef<HTMLDivElement>(null);

  return (
    <div className="wa-inbox">
      <PageHeader
        title="Inbox"
        description="Conversations and messages"
        actions={
          <>
            {isOperator ? (
              <Button variant="secondary" disabled={availabilityBusy} onClick={handleToggleAvailability}>
                {meQuery.status === 'success' && meQuery.data.is_available ? 'Available' : 'Unavailable'}
              </Button>
            ) : null}
            {syncStatus ? (
              <StatusBadge
                status={mapSyncStatus(syncStatus.sync_status, syncStatus.possibly_stuck)}
                label={SYNC_STATUS_LABEL[syncStatus.sync_status]}
              />
            ) : null}
          </>
        }
      />

      {syncStatus?.possibly_stuck ? (
        <div className="wa-inbox__sync-stuck" role="status">
          <p className="wa-inbox__sync-stuck-text">
            <TriangleAlert size={14} strokeWidth={1.75} aria-hidden="true" />
            Reconciliation may be stuck — it has been running longer than expected. This is a diagnostic signal,
            not confirmation that the run has failed.
          </p>
          {canRecover ? (
            <Button variant="secondary" disabled={recoveryBusy} onClick={() => setRecoveryConfirmOpen(true)}>
              Mark reconciliation as failed…
            </Button>
          ) : null}
        </div>
      ) : null}

      {recoveryFeedback?.kind === 'success' ? (
        <p className="wa-inbox__sync-recovery-feedback wa-inbox__sync-recovery-feedback--success" role="status">
          Reconciliation for {sessionName} was marked as failed. A future reconciliation run can start cleanly.
        </p>
      ) : recoveryFeedback?.kind === 'error' ? (
        <ErrorState error={recoveryFeedback.error} />
      ) : null}

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

      {connectivityIssue ? (
        <p className="wa-inbox__connectivity" role="status">
          {connectivityIssue === 'unauthorized' ? (
            <>
              <LogIn size={14} strokeWidth={1.75} aria-hidden="true" />
              Your session needs to be renewed — sign in again to continue.
            </>
          ) : (
            <>
              <WifiOff size={14} strokeWidth={1.75} aria-hidden="true" />
              Can&apos;t reach the server right now — showing the last data loaded. Retrying
              automatically; this doesn&apos;t mean WhatsApp itself is offline.
            </>
          )}
        </p>
      ) : null}

      {!sessionName ? (
        <EmptyState
          icon={MessageCircle}
          title="No session configured"
          description="Set VITE_WAHA_SESSION_NAME to enable the inbox."
        />
      ) : (
        <div className="wa-inbox__panes">
          <div className={`wa-inbox__chat-list ${selectedChatId !== null ? 'wa-inbox__chat-list--hidden-mobile' : ''}`}>
            {chatsQuery.status === 'loading' && chats === null ? (
              <LoadingState label="Loading chats…" />
            ) : chatsQuery.status === 'error' && chats === null ? (
              <ErrorState error={chatsQuery.error} onRetry={chatsQuery.refetch} />
            ) : chats && chats.length === 0 ? (
              <EmptyState icon={MessageCircle} title="No conversations yet" description="Chats will appear here once messages arrive." />
            ) : (
              <ul className="wa-inbox__chat-items">
                {chats?.map((chat) => {
                  const display = chatDisplay(chat);
                  return (
                    <li key={chat.id}>
                      <button
                        type="button"
                        className={[
                          'wa-inbox__chat-item',
                          chat.id === selectedChatId ? 'wa-inbox__chat-item--active' : '',
                          chat.unread ? 'wa-inbox__chat-item--unread' : '',
                        ]
                          .filter(Boolean)
                          .join(' ')}
                        onClick={() => handleSelectChat(chat)}
                      >
                        <span className="wa-inbox__chat-item__icon" aria-hidden="true">
                          {chat.is_group ? <Users size={18} strokeWidth={1.75} /> : <MessageCircle size={18} strokeWidth={1.75} />}
                        </span>
                        <span className="wa-inbox__chat-item__body">
                          <span className="wa-inbox__chat-item__name">{display.primary}</span>
                          {display.secondary ? (
                            <span className="wa-inbox__chat-item__secondary">{display.secondary}</span>
                          ) : null}
                        </span>
                        {chat.unread ? <span className="wa-inbox__unread-dot" aria-label="Unread" /> : null}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <div className={`wa-inbox__conversation ${selectedChatId === null ? 'wa-inbox__conversation--hidden-mobile' : ''}`}>
            {selectedChat === null ? (
              <EmptyState icon={MessageCircle} title="Select a conversation" description="Choose a chat from the list to view its messages." />
            ) : (
              <>
                <div className="wa-inbox__conversation-header">
                  <Button variant="ghost" className="wa-inbox__back" onClick={() => setSelectedChatId(null)}>
                    Back
                  </Button>
                  <span className="wa-inbox__conversation-title-group">
                    <span className="wa-inbox__conversation-title">{chatDisplay(selectedChat).primary}</span>
                    {chatDisplay(selectedChat).secondary ? (
                      <span className="wa-inbox__conversation-subtitle">{chatDisplay(selectedChat).secondary}</span>
                    ) : null}
                  </span>
                  {/* Step 14 (Operator assignment foundation) — backend
                      (HasOfficeAdminAccess + can_view_chat) remains sole
                      authority; canManageAssignment only decides display. */}
                  <span className="wa-inbox__assignment">
                    <span className="wa-inbox__assignment-label">
                      {selectedChat.assigned_to
                        ? `Assigned: ${selectedChat.assigned_to.first_name || selectedChat.assigned_to.username}`
                        : 'Unassigned'}
                    </span>
                    {canManageAssignment ? (
                      <>
                        <Button variant="secondary" onClick={openAssignModal}>
                          {selectedChat.assigned_to ? 'Reassign' : 'Assign'}
                        </Button>
                        {selectedChat.assigned_to ? (
                          <Button variant="ghost" disabled={assignBusy} onClick={handleUnassign}>
                            Unassign
                          </Button>
                        ) : null}
                      </>
                    ) : null}
                  </span>
                </div>

                <div className="wa-inbox__messages" ref={listRef}>
                  {messagesQuery.status === 'loading' && messages === null ? (
                    <LoadingState label="Loading messages…" />
                  ) : messagesQuery.status === 'error' && messages === null ? (
                    <ErrorState error={messagesQuery.error} onRetry={messagesQuery.refetch} />
                  ) : messages && messages.length === 0 ? (
                    <EmptyState icon={MessageCircle} title="No messages yet" description="Nothing has been exchanged in this chat yet." />
                  ) : (
                    <>
                      {nextPage !== null ? (
                        <Button variant="ghost" disabled={loadingOlder} onClick={handleLoadOlder}>
                          {loadingOlder ? 'Loading…' : 'Load older messages'}
                        </Button>
                      ) : null}
                      {/* Stored newest-first (matches the API/WAHA convention);
                          rendered oldest-at-top for a conventional reading order. */}
                      {messages
                        ?.slice()
                        .reverse()
                        .map((message) => (
                          <div
                            key={message.id}
                            className={`wa-inbox__bubble wa-inbox__bubble--${message.direction}`}
                          >
                            {message.body ? <p className="wa-inbox__bubble-text">{message.body}</p> : null}
                            {message.media.length > 0 ? (
                              <p className="wa-inbox__bubble-media">
                                <Paperclip size={14} strokeWidth={1.75} aria-hidden="true" />
                                {message.media.map((m) => m.file_name || m.mime_type || 'Attachment').join(', ')}{' '}
                                (preview not available)
                              </p>
                            ) : null}
                            <p className="wa-inbox__bubble-time">{new Date(message.timestamp).toLocaleString()}</p>
                          </div>
                        ))}
                    </>
                  )}
                </div>

                <div className="wa-inbox__composer">
                  <textarea
                    className="wa-inbox__composer-input"
                    placeholder="Type a message…"
                    value={draftText}
                    onChange={(e) => setDraftText(e.target.value)}
                    disabled={sendBusy}
                    rows={2}
                  />
                  <Button variant="primary" onClick={handleSend} disabled={sendBusy || !draftText.trim()}>
                    <Send size={16} strokeWidth={1.75} aria-hidden="true" />
                    {sendBusy ? 'Sending…' : 'Send'}
                  </Button>
                </div>
                {sendFeedback?.kind === 'error' ? (
                  <ErrorState error={sendFeedback.error} />
                ) : sendFeedback?.kind === 'unknown' ? (
                  <p className="wa-inbox__send-unknown" role="status">
                    The message status could not be confirmed — it may or may not have gone through. Wait a
                    moment and check the conversation before sending it again, to avoid sending it twice.
                  </p>
                ) : sendFeedback?.kind === 'success' ? (
                  <p className="wa-inbox__send-confirmed" role="status">
                    Message sent — it will appear in the history once it's confirmed by the server.
                  </p>
                ) : null}
              </>
            )}
          </div>
        </div>
      )}

      <Modal open={assignModalOpen} onClose={() => setAssignModalOpen(false)} title="Assign operator">
        {operatorsState === null || operatorsState.status === 'loading' ? (
          <LoadingState label="Loading operators…" />
        ) : operatorsState.status === 'error' ? (
          <ErrorState error={operatorsState.error} />
        ) : operatorsState.data.length === 0 ? (
          <EmptyState icon={Users} title="No available operators" description="No operator in this chat's Office is currently available." />
        ) : (
          <ul className="wa-inbox__operator-list">
            {operatorsState.data.map((operator) => (
              <li key={operator.id}>
                <Button
                  variant="secondary"
                  disabled={assignBusy}
                  onClick={() => handleAssign(operator.id)}
                  className="wa-inbox__operator-option"
                >
                  {[operator.first_name, operator.last_name].filter(Boolean).join(' ') || operator.username}
                </Button>
              </li>
            ))}
          </ul>
        )}
        {assignFeedback?.kind === 'error' ? <ErrorState error={assignFeedback.error} /> : null}
      </Modal>
    </div>
  );
}
