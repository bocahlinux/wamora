import { useEffect, useMemo, useState } from 'react';
import { Bot, Search, X } from 'lucide-react';

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
  BOT_ACTION_COMPLETE_SESSION,
  BOT_ACTION_HANDOFF_TO_OPERATOR,
  BOT_ACTION_SEND_TEXT,
  BOT_ACTION_SHOW_MENU,
  createBotMenu,
  createBotMenuItem,
  createBotTrigger,
  deleteBotMenu,
  deleteBotMenuItem,
  deleteBotTrigger,
  getBotConfig,
  getBotMenus,
  getBotTriggers,
  updateBotConfig,
  updateBotMenu,
  updateBotMenuItem,
  updateBotTrigger,
  type BotConfig,
  type BotMenu,
  type BotMenuItem,
  type BotMenuItemActionType,
  type BotTrigger,
} from '../lib/djangoApi';
import './SettingsPage.css';

const ACTION_LABEL: Record<BotMenuItemActionType, string> = {
  [BOT_ACTION_SEND_TEXT]: 'Send text (completes session)',
  [BOT_ACTION_SHOW_MENU]: 'Show another menu',
  [BOT_ACTION_COMPLETE_SESSION]: 'Complete session',
  [BOT_ACTION_HANDOFF_TO_OPERATOR]: 'Hand off to operator (extension point)',
};

type SubTab = 'config' | 'menus' | 'triggers';

interface ScopedData {
  config: BotConfig;
  menus: BotMenu[];
  triggers: BotTrigger[];
}

// Conversation/Bot Engine admin UI — GLOBAL only. There is exactly ONE
// shared bot across every Office (discussed requirement: "bot ini
// berlaku untuk semua office") — per-Office menu/trigger/config content
// is no longer an available admin workflow at all, not even for a
// Superadmin/Global Admin (this panel is already restricted to them —
// apps.bot.views._may_access — but previously still offered an
// office-scope picker left over from before that decision, which was
// confusing and is removed here). `office=<id>`-scoped `BotConfig`/
// `BotMenu`/`BotTrigger` rows remain a supported *data shape* server-side
// (nothing deleted, per this project's "no destructive change without
// approval" convention) — this UI simply never creates or targets one.
// An Office's own on/off switch for direct citizen chat remains
// `OfficeInboxConfig.enabled`, via SettingsInboxConfigPanel.tsx — a
// separate, pre-existing concern this panel never touches.
export function SettingsBotConfigPanel() {
  const [subTab, setSubTab] = useState<SubTab>('config');
  const [state, setState] = useState<
    { status: 'loading' } | { status: 'error'; error: ApiError } | { status: 'success'; data: ScopedData } | null
  >(null);

  function refetch() {
    setState({ status: 'loading' });
    Promise.all([getBotConfig(undefined), getBotMenus(undefined), getBotTriggers(undefined)]).then(
      ([configResult, menusResult, triggersResult]) => {
        if (!configResult.ok) {
          setState({ status: 'error', error: configResult.error });
          return;
        }
        if (!menusResult.ok) {
          setState({ status: 'error', error: menusResult.error });
          return;
        }
        if (!triggersResult.ok) {
          setState({ status: 'error', error: triggersResult.error });
          return;
        }
        setState({
          status: 'success',
          data: { config: configResult.data, menus: menusResult.data, triggers: triggersResult.data },
        });
      },
    );
  }

  useEffect(() => {
    refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Card>
      <div className="wa-settings-panel__header">
        <span className="wa-settings-panel__title">Bot Configuration</span>
      </div>

      {state === null || state.status === 'loading' ? (
        <LoadingState label="Loading bot configuration…" />
      ) : state.status === 'error' ? (
        <ErrorState error={state.error} onRetry={refetch} />
      ) : (
        <>
          <div className="wa-settings-tabs" role="tablist" aria-label="Bot configuration sections">
            {(['config', 'menus', 'triggers'] as const).map((t) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={subTab === t}
                className={['wa-settings-tab', subTab === t ? 'wa-settings-tab--active' : ''].filter(Boolean).join(' ')}
                onClick={() => setSubTab(t)}
              >
                {t === 'config' ? 'Config' : t === 'menus' ? 'Menus' : 'Global Triggers'}
              </button>
            ))}
          </div>

          {subTab === 'config' ? (
            <BotConfigForm
              officeId={undefined}
              config={state.data.config}
              menus={state.data.menus}
              onSaved={(updated) => setState({ status: 'success', data: { ...state.data, config: updated } })}
            />
          ) : subTab === 'menus' ? (
            <BotMenusSection officeId={undefined} menus={state.data.menus} onChanged={refetch} />
          ) : (
            <BotTriggersSection officeId={undefined} menus={state.data.menus} triggers={state.data.triggers} onChanged={refetch} />
          )}
        </>
      )}
    </Card>
  );
}

function BotConfigForm({
  officeId,
  config,
  menus,
  onSaved,
}: {
  officeId: number | undefined;
  config: BotConfig;
  menus: BotMenu[];
  onSaved: (updated: BotConfig) => void;
}) {
  const [enabled, setEnabled] = useState(config.enabled);
  const [fallbackMessage, setFallbackMessage] = useState(config.fallback_message);
  const [sessionCompletedMessage, setSessionCompletedMessage] = useState(config.session_completed_message);
  const [rootMenu, setRootMenu] = useState<number | ''>(config.root_menu ?? '');
  const [listFooterText, setListFooterText] = useState(config.list_footer_text);
  const [listButtonText, setListButtonText] = useState(config.list_button_text);
  const [replyDelaySeconds, setReplyDelaySeconds] = useState(config.reply_delay_seconds);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState(false);

  async function handleSubmit() {
    if (busy) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    const result = await updateBotConfig(officeId, {
      enabled,
      fallback_message: fallbackMessage,
      session_completed_message: sessionCompletedMessage,
      root_menu: rootMenu === '' ? null : rootMenu,
      list_footer_text: listFooterText,
      list_button_text: listButtonText,
      reply_delay_seconds: replyDelaySeconds,
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
        <span>Bot enabled for this scope</span>
      </label>

      <div className="wa-settings-form__field">
        <label className="wa-settings-form__label" htmlFor="bot-config-root-menu">
          Main Menu (root)
        </label>
        <select
          id="bot-config-root-menu"
          className="wa-settings-form__select"
          value={rootMenu}
          onChange={(e) => setRootMenu(e.target.value ? Number(e.target.value) : '')}
          disabled={busy}
        >
          <option value="">None (bot inactive until a root menu is set)</option>
          {menus.map((menu) => (
            <option key={menu.id} value={menu.id}>
              {menu.name}
            </option>
          ))}
        </select>
      </div>

      <div className="wa-settings-form__field">
        <label className="wa-settings-form__label" htmlFor="bot-config-fallback">
          Fallback message
        </label>
        <textarea
          id="bot-config-fallback"
          className="wa-settings-form__textarea"
          rows={3}
          value={fallbackMessage}
          onChange={(e) => setFallbackMessage(e.target.value)}
          disabled={busy}
        />
        <p className="wa-settings-form__hint">
          Sent before the current menu is re-shown whenever a reply doesn't match anything.
        </p>
      </div>

      <div className="wa-settings-form__field">
        <label className="wa-settings-form__label" htmlFor="bot-config-completed">
          Session completed message
        </label>
        <textarea
          id="bot-config-completed"
          className="wa-settings-form__textarea"
          rows={3}
          value={sessionCompletedMessage}
          onChange={(e) => setSessionCompletedMessage(e.target.value)}
          disabled={busy}
        />
        <p className="wa-settings-form__hint">Sent when a flow completes, telling the user how to start again.</p>
      </div>

      <div className="wa-settings-form__field">
        <Input
          label="Reply delay (seconds)"
          type="number"
          min={0}
          value={String(replyDelaySeconds)}
          onChange={(e) => setReplyDelaySeconds(Math.max(0, Number(e.target.value) || 0))}
          disabled={busy}
        />
        <p className="wa-settings-form__hint">
          Waits this many seconds before each automated reply, showing WhatsApp's "typing…" indicator the whole
          time — 0 sends immediately with no typing indicator, same as before this setting existed.
        </p>
      </div>

      <div className="wa-settings-form__field">
        <Input
          label="List footer text"
          value={listFooterText}
          onChange={(e) => setListFooterText(e.target.value)}
          disabled={busy}
        />
        <p className="wa-settings-form__hint">
          Shown at the bottom of every interactive list menu the bot sends (may be left blank).
        </p>
      </div>

      <div className="wa-settings-form__field">
        <Input
          label="List button text"
          value={listButtonText}
          onChange={(e) => setListButtonText(e.target.value)}
          disabled={busy}
          maxLength={32}
        />
        <p className="wa-settings-form__hint">
          The tap-to-open label on every interactive list menu (defaults to "Pilih" if left blank).
        </p>
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

function BotMenusSection({
  officeId,
  menus,
  onChanged,
}: {
  officeId: number | undefined;
  menus: BotMenu[];
  onChanged: () => void;
}) {
  const [modalMenu, setModalMenu] = useState<BotMenu | 'new' | null>(null);
  const [itemsMenu, setItemsMenu] = useState<BotMenu | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<BotMenu | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<ApiError | null>(null);
  const [search, setSearch] = useState('');

  const filteredMenus = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return menus;
    return menus.filter((menu) => menu.name.toLowerCase().includes(term));
  }, [menus, search]);

  async function handleDeleteConfirmed() {
    if (!deleteTarget || deleteBusy) return;
    setDeleteBusy(true);
    setDeleteError(null);
    const result = await deleteBotMenu(deleteTarget.id);
    setDeleteBusy(false);
    if (!result.ok) {
      setDeleteError(result.error);
      return;
    }
    setDeleteTarget(null);
    onChanged();
  }

  return (
    <div>
      <div className="wa-settings-panel__header">
        <span className="wa-settings-panel__title">Menus</span>
        <Button variant="primary" onClick={() => setModalMenu('new')}>
          New Menu
        </Button>
      </div>

      {menus.length === 0 ? (
        <EmptyState icon={Bot} title="No menus yet" description="Create at least one menu, then set it as the Config tab's root menu." />
      ) : (
        <>
          <div className="wa-settings-toolbar">
            <label className="wa-settings-search">
              <Search size={16} strokeWidth={1.75} aria-hidden="true" />
              <input
                type="text"
                placeholder="Search menus…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="Search menus"
              />
            </label>
            {search ? (
              <Button variant="ghost" onClick={() => setSearch('')}>
                <X size={14} strokeWidth={1.75} aria-hidden="true" />
                Clear
              </Button>
            ) : null}
          </div>
          {filteredMenus.length === 0 ? (
            <EmptyState icon={Search} title="No matching menus" description="Try a different search term." />
          ) : (
        <div className="wa-settings-table-wrap">
          <table className="wa-settings-table wa-settings-table--responsive">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Enabled</th>
                <th>Items</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filteredMenus.map((menu) => (
                <tr key={menu.id}>
                  <td data-label="Name">{menu.name}</td>
                  <td data-label="Type">{menu.is_office_selector ? 'Office selector (dynamic)' : 'Ordinary'}</td>
                  <td data-label="Enabled">{menu.enabled ? 'Yes' : 'No'}</td>
                  <td data-label="Items">{menu.is_office_selector ? '—' : menu.items.length}</td>
                  <td data-label="">
                    <Button variant="ghost" onClick={() => setModalMenu(menu)}>
                      Edit
                    </Button>
                    {!menu.is_office_selector ? (
                      <Button variant="ghost" onClick={() => setItemsMenu(menu)}>
                        Items
                      </Button>
                    ) : null}
                    <Button variant="ghost" onClick={() => setDeleteTarget(menu)}>
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
          )}
        </>
      )}

      <BotMenuFormModal
        officeId={officeId}
        menu={modalMenu}
        menus={menus}
        onClose={() => setModalMenu(null)}
        onSaved={() => {
          setModalMenu(null);
          onChanged();
        }}
      />

      {itemsMenu ? (
        <BotMenuItemsModal
          menu={itemsMenu}
          menus={menus}
          onClose={() => setItemsMenu(null)}
          onChanged={onChanged}
        />
      ) : null}

      <ConfirmDialog
        open={deleteTarget !== null}
        title={deleteTarget ? `Delete "${deleteTarget.name}"?` : 'Delete menu?'}
        description="A menu still referenced by an item, trigger, bot config, or an in-progress conversation cannot be deleted — reassign or remove those first."
        confirmLabel="Delete"
        busy={deleteBusy}
        onCancel={() => {
          setDeleteTarget(null);
          setDeleteError(null);
        }}
        onConfirm={handleDeleteConfirmed}
      />
      {deleteError ? <ErrorState error={deleteError} /> : null}
    </div>
  );
}

function BotMenuFormModal({
  officeId,
  menu,
  menus,
  onClose,
  onSaved,
}: {
  officeId: number | undefined;
  menu: BotMenu | 'new' | null;
  menus: BotMenu[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const openKey = menu === null ? 'closed' : menu === 'new' ? 'new' : menu.id;
  const title = menu === 'new' ? 'New Menu' : menu ? `Edit ${menu.name}` : '';
  return (
    <Modal open={menu !== null} onClose={onClose} title={title}>
      <BotMenuForm key={openKey} officeId={officeId} menu={menu} menus={menus} onClose={onClose} onSaved={onSaved} />
    </Modal>
  );
}

function BotMenuForm({
  officeId,
  menu,
  menus,
  onClose,
  onSaved,
}: {
  officeId: number | undefined;
  menu: BotMenu | 'new' | null;
  menus: BotMenu[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = menu === 'new';
  const editing = menu !== null && menu !== 'new' ? menu : null;

  const [name, setName] = useState(editing?.name ?? '');
  const [introText, setIntroText] = useState(editing?.intro_text ?? '');
  const [isOfficeSelector, setIsOfficeSelector] = useState(editing?.is_office_selector ?? false);
  const [enabled, setEnabled] = useState(editing?.enabled ?? true);
  const [parentMenu, setParentMenu] = useState<number | ''>(editing?.parent_menu ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSubmit() {
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    if (/[^\x00-\x7F]/.test(introText)) {
      setError({ kind: 'validation', message: 'Intro text must not contain emoji or other non-ASCII characters.' });
      return;
    }
    setBusy(true);
    setError(null);
    const payload = {
      name: trimmed,
      office: officeId ?? null,
      intro_text: introText,
      is_office_selector: isOfficeSelector,
      enabled,
      parent_menu: parentMenu === '' ? null : parentMenu,
    };
    const result = isNew ? await createBotMenu(payload) : await updateBotMenu(editing!.id, payload);
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onSaved();
  }

  return (
    <div className="wa-settings-form">
      <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} disabled={busy} />

      <div className="wa-settings-form__field">
        <label className="wa-settings-form__label" htmlFor="bot-menu-parent">
          Parent menu
        </label>
        <select
          id="bot-menu-parent"
          className="wa-settings-form__select"
          value={parentMenu}
          onChange={(e) => setParentMenu(e.target.value ? Number(e.target.value) : '')}
          disabled={busy}
        >
          <option value="">None (top-level)</option>
          {menus.filter((m) => !editing || m.id !== editing.id).map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </div>

      <div className="wa-settings-form__field">
        <label className="wa-settings-form__label" htmlFor="bot-menu-intro">
          Intro text
        </label>
        <textarea
          id="bot-menu-intro"
          className="wa-settings-form__textarea"
          rows={3}
          value={introText}
          onChange={(e) => setIntroText(e.target.value)}
          disabled={busy}
        />
        <p className="wa-settings-form__hint">
          Shown every time this menu is displayed — not a one-time greeting. No emoji or other non-ASCII characters
          (the database cannot store them).
        </p>
      </div>

      <label className="wa-settings-checkbox-row">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} disabled={busy} />
        <span>Enabled</span>
      </label>

      <label className="wa-settings-checkbox-row">
        <input
          type="checkbox"
          checked={isOfficeSelector}
          onChange={(e) => setIsOfficeSelector(e.target.checked)}
          disabled={busy}
        />
        <span>
          Office selector — options are built dynamically from available Offices (reuses the existing "Hubungi
          Petugas" logic); leave this menu with no items.
        </span>
      </label>

      {error ? <ErrorState error={error} /> : null}

      <div className="wa-settings-form__actions">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant="primary" onClick={handleSubmit} disabled={busy || !name.trim()}>
          {busy ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  );
}

function BotMenuItemsModal({
  menu,
  menus,
  onClose,
  onChanged,
}: {
  menu: BotMenu;
  menus: BotMenu[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const [items, setItems] = useState(menu.items);
  const [modalItem, setModalItem] = useState<BotMenuItem | 'new' | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<BotMenuItem | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<ApiError | null>(null);

  function reload() {
    onChanged();
  }

  async function handleDeleteConfirmed() {
    if (!deleteTarget || deleteBusy) return;
    setDeleteBusy(true);
    setDeleteError(null);
    const result = await deleteBotMenuItem(deleteTarget.id);
    setDeleteBusy(false);
    if (!result.ok) {
      setDeleteError(result.error);
      return;
    }
    setItems((prev) => prev.filter((i) => i.id !== deleteTarget.id));
    setDeleteTarget(null);
    reload();
  }

  return (
    <Modal open onClose={onClose} title={`Items — ${menu.name}`}>
      <div className="wa-settings-panel__header">
        <span />
        <Button variant="primary" onClick={() => setModalItem('new')}>
          New Item
        </Button>
      </div>

      {items.length === 0 ? (
        <EmptyState icon={Bot} title="No items yet" description="Add at least one item so this menu has a reply users can select." />
      ) : (
        <div className="wa-settings-table-wrap">
          <table className="wa-settings-table wa-settings-table--responsive">
            <thead>
              <tr>
                <th>Order</th>
                <th>Trigger</th>
                <th>Label</th>
                <th>Action</th>
                <th>Enabled</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {[...items]
                .sort((a, b) => a.order - b.order || a.id - b.id)
                .map((item) => (
                  <tr key={item.id}>
                    <td data-label="Order">{item.order}</td>
                    <td data-label="Trigger">{item.trigger_value}</td>
                    <td data-label="Label">{item.label}</td>
                    <td data-label="Action">{ACTION_LABEL[item.action_type]}</td>
                    <td data-label="Enabled">{item.enabled ? 'Yes' : 'No'}</td>
                    <td data-label="">
                      <Button variant="ghost" onClick={() => setModalItem(item)}>
                        Edit
                      </Button>
                      <Button variant="ghost" onClick={() => setDeleteTarget(item)}>
                        Delete
                      </Button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}

      <BotMenuItemFormModal
        menuId={menu.id}
        item={modalItem}
        menus={menus}
        onClose={() => setModalItem(null)}
        onSaved={(saved) => {
          setModalItem(null);
          setItems((prev) => {
            const exists = prev.some((i) => i.id === saved.id);
            return exists ? prev.map((i) => (i.id === saved.id ? saved : i)) : [...prev, saved];
          });
          reload();
        }}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title={deleteTarget ? `Delete "${deleteTarget.label}"?` : 'Delete item?'}
        description="This cannot be undone."
        confirmLabel="Delete"
        busy={deleteBusy}
        onCancel={() => {
          setDeleteTarget(null);
          setDeleteError(null);
        }}
        onConfirm={handleDeleteConfirmed}
      />
      {deleteError ? <ErrorState error={deleteError} /> : null}
    </Modal>
  );
}

function BotMenuItemFormModal({
  menuId,
  item,
  menus,
  onClose,
  onSaved,
}: {
  menuId: number;
  item: BotMenuItem | 'new' | null;
  menus: BotMenu[];
  onClose: () => void;
  onSaved: (item: BotMenuItem) => void;
}) {
  const openKey = item === null ? 'closed' : item === 'new' ? 'new' : item.id;
  const title = item === 'new' ? 'New Item' : item ? `Edit ${item.label}` : '';
  return (
    <Modal open={item !== null} onClose={onClose} title={title}>
      <BotMenuItemForm key={openKey} menuId={menuId} item={item} menus={menus} onClose={onClose} onSaved={onSaved} />
    </Modal>
  );
}

function BotMenuItemForm({
  menuId,
  item,
  menus,
  onClose,
  onSaved,
}: {
  menuId: number;
  item: BotMenuItem | 'new' | null;
  menus: BotMenu[];
  onClose: () => void;
  onSaved: (item: BotMenuItem) => void;
}) {
  const isNew = item === 'new';
  const editing = item !== null && item !== 'new' ? item : null;

  const [label, setLabel] = useState(editing?.label ?? '');
  const [triggerValue, setTriggerValue] = useState(editing?.trigger_value ?? '');
  const [order, setOrder] = useState(editing?.order ?? 0);
  const [enabled, setEnabled] = useState(editing?.enabled ?? true);
  const [actionType, setActionType] = useState<BotMenuItemActionType>(editing?.action_type ?? BOT_ACTION_SEND_TEXT);
  const [text, setText] = useState(editing?.text ?? '');
  const [targetMenu, setTargetMenu] = useState<number | ''>(editing?.target_menu ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSubmit() {
    const trimmedLabel = label.trim();
    const trimmedTrigger = triggerValue.trim();
    if (!trimmedLabel || !trimmedTrigger || busy) return;
    if (actionType === BOT_ACTION_SHOW_MENU && targetMenu === '') {
      setError({ kind: 'validation', message: 'Target menu is required for "Show another menu".' });
      return;
    }
    setBusy(true);
    setError(null);
    const payload = {
      label: trimmedLabel,
      trigger_value: trimmedTrigger,
      order,
      enabled,
      action_type: actionType,
      text: actionType === BOT_ACTION_SEND_TEXT ? text : '',
      target_menu: actionType === BOT_ACTION_SHOW_MENU ? (targetMenu === '' ? null : targetMenu) : null,
    };
    const result = isNew ? await createBotMenuItem(menuId, payload) : await updateBotMenuItem(editing!.id, payload);
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onSaved(result.data);
  }

  return (
    <div className="wa-settings-form">
      <Input label="Label" value={label} onChange={(e) => setLabel(e.target.value)} disabled={busy} />
      <Input
        label="Trigger value (what the user must reply)"
        value={triggerValue}
        onChange={(e) => setTriggerValue(e.target.value)}
        disabled={busy}
      />
      <Input
        label="Order"
        type="number"
        value={String(order)}
        onChange={(e) => setOrder(Number(e.target.value) || 0)}
        disabled={busy}
      />

      <div className="wa-settings-form__field">
        <label className="wa-settings-form__label" htmlFor="bot-item-action">
          Action
        </label>
        <select
          id="bot-item-action"
          className="wa-settings-form__select"
          value={actionType}
          onChange={(e) => setActionType(e.target.value as BotMenuItemActionType)}
          disabled={busy}
        >
          {Object.entries(ACTION_LABEL).map(([value, labelText]) => (
            <option key={value} value={value}>
              {labelText}
            </option>
          ))}
        </select>
      </div>

      {actionType === BOT_ACTION_SEND_TEXT ? (
        <div className="wa-settings-form__field">
          <label className="wa-settings-form__label" htmlFor="bot-item-text">
            Text to send
          </label>
          <textarea
            id="bot-item-text"
            className="wa-settings-form__textarea"
            rows={3}
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={busy}
          />
        </div>
      ) : null}

      {actionType === BOT_ACTION_SHOW_MENU ? (
        <div className="wa-settings-form__field">
          <label className="wa-settings-form__label" htmlFor="bot-item-target-menu">
            Target menu
          </label>
          <select
            id="bot-item-target-menu"
            className="wa-settings-form__select"
            value={targetMenu}
            onChange={(e) => setTargetMenu(e.target.value ? Number(e.target.value) : '')}
            disabled={busy}
          >
            <option value="">Select a menu…</option>
            {menus.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {actionType === BOT_ACTION_HANDOFF_TO_OPERATOR ? (
        <p className="wa-settings-form__hint">
          Extension point only — this records a "waiting for operator" state; no assignment/queue logic exists yet.
        </p>
      ) : null}

      <label className="wa-settings-checkbox-row">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} disabled={busy} />
        <span>Enabled</span>
      </label>

      {error ? <ErrorState error={error} /> : null}

      <div className="wa-settings-form__actions">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant="primary" onClick={handleSubmit} disabled={busy || !label.trim() || !triggerValue.trim()}>
          {busy ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  );
}

function BotTriggersSection({
  officeId,
  menus,
  triggers,
  onChanged,
}: {
  officeId: number | undefined;
  menus: BotMenu[];
  triggers: BotTrigger[];
  onChanged: () => void;
}) {
  const [modalTrigger, setModalTrigger] = useState<BotTrigger | 'new' | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<BotTrigger | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<ApiError | null>(null);
  const [search, setSearch] = useState('');

  const filteredTriggers = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return triggers;
    return triggers.filter((trigger) => trigger.keyword.toLowerCase().includes(term));
  }, [triggers, search]);

  async function handleDeleteConfirmed() {
    if (!deleteTarget || deleteBusy) return;
    setDeleteBusy(true);
    setDeleteError(null);
    const result = await deleteBotTrigger(deleteTarget.id);
    setDeleteBusy(false);
    if (!result.ok) {
      setDeleteError(result.error);
      return;
    }
    setDeleteTarget(null);
    onChanged();
  }

  return (
    <div>
      <div className="wa-settings-panel__header">
        <span className="wa-settings-panel__title">Global Triggers</span>
        <Button variant="primary" onClick={() => setModalTrigger('new')}>
          New Trigger
        </Button>
      </div>
      <p className="wa-settings-form__hint">
        A trigger ALWAYS resets the conversation to its target menu, even mid-flow — e.g. "Halo", "Menu", "Mulai".
      </p>

      {triggers.length === 0 ? (
        <EmptyState icon={Bot} title="No triggers yet" description='Add keywords like "Halo" or "Menu" that always restart the flow.' />
      ) : (
        <>
          <div className="wa-settings-toolbar">
            <label className="wa-settings-search">
              <Search size={16} strokeWidth={1.75} aria-hidden="true" />
              <input
                type="text"
                placeholder="Search triggers…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="Search triggers"
              />
            </label>
            {search ? (
              <Button variant="ghost" onClick={() => setSearch('')}>
                <X size={14} strokeWidth={1.75} aria-hidden="true" />
                Clear
              </Button>
            ) : null}
          </div>
          {filteredTriggers.length === 0 ? (
            <EmptyState icon={Search} title="No matching triggers" description="Try a different search term." />
          ) : (
        <div className="wa-settings-table-wrap">
          <table className="wa-settings-table wa-settings-table--responsive">
            <thead>
              <tr>
                <th>Keyword</th>
                <th>Target menu</th>
                <th>Enabled</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filteredTriggers.map((trigger) => (
                <tr key={trigger.id}>
                  <td data-label="Keyword">{trigger.keyword}</td>
                  <td data-label="Target menu">{menus.find((m) => m.id === trigger.target_menu)?.name ?? '—'}</td>
                  <td data-label="Enabled">{trigger.enabled ? 'Yes' : 'No'}</td>
                  <td data-label="">
                    <Button variant="ghost" onClick={() => setModalTrigger(trigger)}>
                      Edit
                    </Button>
                    <Button variant="ghost" onClick={() => setDeleteTarget(trigger)}>
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
          )}
        </>
      )}

      <BotTriggerFormModal
        officeId={officeId}
        trigger={modalTrigger}
        menus={menus}
        onClose={() => setModalTrigger(null)}
        onSaved={() => {
          setModalTrigger(null);
          onChanged();
        }}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title={deleteTarget ? `Delete "${deleteTarget.keyword}"?` : 'Delete trigger?'}
        description="This cannot be undone."
        confirmLabel="Delete"
        busy={deleteBusy}
        onCancel={() => {
          setDeleteTarget(null);
          setDeleteError(null);
        }}
        onConfirm={handleDeleteConfirmed}
      />
      {deleteError ? <ErrorState error={deleteError} /> : null}
    </div>
  );
}

function BotTriggerFormModal({
  officeId,
  trigger,
  menus,
  onClose,
  onSaved,
}: {
  officeId: number | undefined;
  trigger: BotTrigger | 'new' | null;
  menus: BotMenu[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const openKey = trigger === null ? 'closed' : trigger === 'new' ? 'new' : trigger.id;
  const title = trigger === 'new' ? 'New Trigger' : trigger ? `Edit "${trigger.keyword}"` : '';
  return (
    <Modal open={trigger !== null} onClose={onClose} title={title}>
      <BotTriggerForm key={openKey} officeId={officeId} trigger={trigger} menus={menus} onClose={onClose} onSaved={onSaved} />
    </Modal>
  );
}

function BotTriggerForm({
  officeId,
  trigger,
  menus,
  onClose,
  onSaved,
}: {
  officeId: number | undefined;
  trigger: BotTrigger | 'new' | null;
  menus: BotMenu[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = trigger === 'new';
  const editing = trigger !== null && trigger !== 'new' ? trigger : null;

  const [keyword, setKeyword] = useState(editing?.keyword ?? '');
  const [targetMenu, setTargetMenu] = useState<number | ''>(editing?.target_menu ?? '');
  const [enabled, setEnabled] = useState(editing?.enabled ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function handleSubmit() {
    const trimmed = keyword.trim();
    if (!trimmed || targetMenu === '' || busy) return;
    setBusy(true);
    setError(null);
    const payload = { keyword: trimmed, office: officeId ?? null, target_menu: targetMenu, enabled };
    const result = isNew ? await createBotTrigger(payload) : await updateBotTrigger(editing!.id, payload);
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onSaved();
  }

  return (
    <div className="wa-settings-form">
      <Input label="Keyword" value={keyword} onChange={(e) => setKeyword(e.target.value)} disabled={busy} />

      <div className="wa-settings-form__field">
        <label className="wa-settings-form__label" htmlFor="bot-trigger-target-menu">
          Target menu
        </label>
        <select
          id="bot-trigger-target-menu"
          className="wa-settings-form__select"
          value={targetMenu}
          onChange={(e) => setTargetMenu(e.target.value ? Number(e.target.value) : '')}
          disabled={busy}
        >
          <option value="">Select a menu…</option>
          {menus.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>
      </div>

      <label className="wa-settings-checkbox-row">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} disabled={busy} />
        <span>Enabled</span>
      </label>

      {error ? <ErrorState error={error} /> : null}

      <div className="wa-settings-form__actions">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant="primary" onClick={handleSubmit} disabled={busy || !keyword.trim() || targetMenu === ''}>
          {busy ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  );
}
