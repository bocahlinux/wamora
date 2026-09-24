import { useEffect, useRef, useState } from 'react';
import { MessageCircle, Paperclip, Send, Users } from 'lucide-react';

import { Button } from '../components/ui/Button';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { LoadingState } from '../components/ui/LoadingState';
import { PageHeader } from '../components/ui/PageHeader';
import type { ApiError } from '../lib/api';
import { sendMessage } from '../lib/bffApi';
import {
  getChatMessages,
  getChats,
  markChatRead,
  type ChatMessage,
  type ChatSummary,
} from '../lib/djangoApi';
import { config } from '../lib/config';
import { useApiQuery } from '../lib/useApiQuery';
import './InboxPage.css';

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
      // an error state.
      if (result.ok) setChats(result.data.results);
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
  const [draftText, setDraftText] = useState('');
  const [sendBusy, setSendBusy] = useState(false);
  const [sendError, setSendError] = useState<ApiError | null>(null);
  const [sendConfirmed, setSendConfirmed] = useState(false);

  async function handleSend() {
    const text = draftText.trim();
    if (!text || !selectedChat || !sessionName || sendBusy) return;
    setSendBusy(true);
    setSendError(null);
    setSendConfirmed(false);
    const result = await sendMessage(sessionName, selectedChat.provider_chat_id, text, crypto.randomUUID());
    setSendBusy(false);
    if (!result.ok) {
      setSendError(result.error);
      return;
    }
    setDraftText('');
    // The just-sent message reaches Django's durable copy only once it
    // round-trips through WAHA's own webhook, not instantly — this
    // confirms the send itself, not that history has caught up yet
    // (never fabricate a local message bubble for what hasn't actually
    // been persisted). The polling loop above will pick it up once it
    // lands.
    setSendConfirmed(result.data.status !== 'unknown');
  }

  const listRef = useRef<HTMLDivElement>(null);

  return (
    <div className="wa-inbox">
      <PageHeader title="Inbox" description="Conversations and messages" />

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
                {sendError ? <ErrorState error={sendError} /> : null}
                {sendConfirmed ? (
                  <p className="wa-inbox__send-confirmed" role="status">
                    Message sent — it will appear in the history once it's confirmed by the server.
                  </p>
                ) : null}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
