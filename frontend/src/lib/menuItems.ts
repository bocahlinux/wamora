// Discussed requirement — Menu Access. The canonical list of sidebar
// LEAF destinations, kept deliberately identical to backend/apps/offices/
// menu_items.py's own MENU_ITEM_KEYS (same "two implementations,
// deliberately kept in sync" precedent this project already established
// for apps.blast.templating.extract_variable_names/
// lib/blastTemplateVariables.ts). `Role.visible_menu_items` (a Superadmin-
// editable allowlist, `null` meaning "not customized") references these
// keys — see Sidebar.tsx's own `isMenuItemVisible` for how the override
// is applied.
//
// `group` is only used by the Menu Access editor UI to organize the
// checklist into sections — Sidebar.tsx itself derives a submenu GROUP's
// own visibility from whether any of its children are visible, so there
// is no separate "group" key to toggle here.
export interface MenuItemDefinition {
  key: string;
  label: string;
  group: string;
}

export const MENU_ITEMS: MenuItemDefinition[] = [
  { key: 'dashboard', label: 'Dashboard', group: 'General' },
  { key: 'whatsapp', label: 'WhatsApp', group: 'General' },
  { key: 'inbox', label: 'Inbox', group: 'General' },
  { key: 'sessions', label: 'Sessions', group: 'General' },
  { key: 'blast.campaigns', label: 'Campaigns', group: 'Blast' },
  { key: 'blast.templates', label: 'Templates', group: 'Blast' },
  { key: 'blast.history', label: 'History', group: 'Blast' },
  { key: 'manage_users.users', label: 'Users', group: 'Manage Users' },
  { key: 'manage_users.roles', label: 'Roles', group: 'Manage Users' },
  { key: 'reports', label: 'Reports', group: 'General' },
  { key: 'settings.offices', label: 'Offices', group: 'Settings' },
  { key: 'settings.inbox_config', label: 'Inbox Configuration', group: 'Settings' },
  { key: 'settings.bot_config', label: 'Bot Configuration', group: 'Settings' },
  { key: 'settings.blast_api', label: 'Blast API', group: 'Settings' },
  { key: 'settings.menu_access', label: 'Menu Access', group: 'Settings' },
];

export const MENU_ITEM_GROUPS: string[] = Array.from(new Set(MENU_ITEMS.map((item) => item.group)));
