import { useState } from 'react';
import {
  BarChart3,
  ChevronDown,
  ChevronRight,
  Inbox,
  LayoutDashboard,
  Megaphone,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Smartphone,
  Users,
  type LucideIcon,
} from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';

import { Logo } from '../brand/Logo';
import { useAuth } from '../../lib/AuthContext';
import { getMe } from '../../lib/djangoApi';
import { useApiQuery } from '../../lib/useApiQuery';
import { IconButton } from '../ui/IconButton';
import './Sidebar.css';

// Discussed requirement — Menu Access: sidebar visibility now has TWO
// layers, evaluated per leaf item:
//   1. `defaultVisible(ctx)` — this project's existing hardcoded rule
//      (JWT scope / has_global_access / is_office_admin / is_superuser),
//      UNCHANGED from before this feature existed.
//   2. A Superadmin-editable override (`Role.visible_menu_items`,
//      `lib/menuItems.ts`'s own key vocabulary) — when the current
//      user's Role has been explicitly customized (`!== null`), it
//      REPLACES rule 1 entirely for that Role: `[]` shows nothing, a
//      non-empty list is a strict allowlist. `null` (the default, and
//      every Role's value until a Superadmin customizes it) means rule 1
//      still applies unchanged — so this feature changes NOTHING for any
//      existing Role until explicitly configured (Settings > Menu
//      Access).
// This is STILL UX only — hiding an item a caller's token doesn't cover
// (or that Menu Access hides) never replaces the server-side check
// (`lib/auth.ts`'s own decodeToken() docstring: "the frontend must never
// make a security decision based on this decoded value alone"); every
// route still enforces itself regardless of what this Sidebar shows.
interface VisibilityContext {
  scopes: string[];
  hasGlobalAccess: boolean;
  hasOfficeAccess: boolean;
  isOfficeAdminOrGlobal: boolean;
  isSuperuser: boolean;
}

interface LeafItem {
  /** Matches `lib/menuItems.ts`'s `MENU_ITEMS[].key` — the identity a
   * Menu Access override references. */
  key: string;
  to: string;
  label: string;
  defaultVisible: (ctx: VisibilityContext) => boolean;
}

interface TopLevelLeaf extends LeafItem {
  icon: LucideIcon;
  end: boolean;
}

interface TopLevelGroup {
  key: null;
  to: string;
  label: string;
  icon: LucideIcon;
  children: LeafItem[];
}

type TopLevelItem = TopLevelLeaf | TopLevelGroup;

// Navigation order and icon mapping taken directly from
// wamora-design-assets/docs/WAMORA-FRONTEND-DESIGN-SPEC.md Sections 6/7,
// extended with the Blast/Manage Users/Settings submenus (Discussed
// requirement). Every `defaultVisible` below reproduces this project's
// PRE-EXISTING gating exactly (same scopes/flags this file already
// checked before Menu Access existed) — see each item's own comment for
// which backend check it mirrors.
const NAV_ITEMS: TopLevelItem[] = [
  { key: 'dashboard', to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true, defaultVisible: (ctx) => ctx.scopes.includes('reading') },
  { key: 'whatsapp', to: '/whatsapp', label: 'WhatsApp', icon: MessageCircle, end: false, defaultVisible: () => true },
  // Not scope-gated backend-side (`HasOfficeAccess` checks Office
  // role/membership instead, a deliberately separate axis — see
  // apps/authn/permissions.py's own docstring).
  { key: 'inbox', to: '/inbox', label: 'Inbox', icon: Inbox, end: false, defaultVisible: (ctx) => ctx.hasOfficeAccess },
  { key: 'sessions', to: '/sessions', label: 'Sessions', icon: Smartphone, end: false, defaultVisible: (ctx) => ctx.scopes.includes('reading') },
  {
    key: null,
    to: '/blast/campaigns',
    label: 'Blast',
    icon: Megaphone,
    children: [
      { key: 'blast.campaigns', to: '/blast/campaigns', label: 'Campaigns', defaultVisible: (ctx) => ctx.scopes.includes('blast') },
      // Discussed requirement — Superadmin/Global-Admin-only
      // (apps.blast.views.BlastTemplateListCreateView's own
      // has_global_access gate, narrowed from the rest of Blast's
      // 'blast'-scope gating).
      { key: 'blast.templates', to: '/blast/templates', label: 'Templates', defaultVisible: (ctx) => ctx.hasGlobalAccess },
      { key: 'blast.history', to: '/blast/history', label: 'History', defaultVisible: (ctx) => ctx.scopes.includes('blast') },
    ],
  },
  {
    key: null,
    to: '/manage-users/users',
    label: 'Manage Users',
    icon: Users,
    children: [
      // Mirrors HasUserAdministrationScope's own gate (apps/offices/views.py).
      { key: 'manage_users.users', to: '/manage-users/users', label: 'Users', defaultVisible: (ctx) => ctx.isOfficeAdminOrGlobal },
      // Role CRUD is Superuser-only server-side (RoleListCreateView.post/
      // RoleDetailView.patch/delete check request.user.is_superuser
      // directly, not a scope) — mirrored here exactly.
      { key: 'manage_users.roles', to: '/manage-users/roles', label: 'Roles', defaultVisible: (ctx) => ctx.isSuperuser },
    ],
  },
  { key: 'reports', to: '/reports', label: 'Reports', icon: BarChart3, end: false, defaultVisible: () => true },
  {
    key: null,
    to: '/settings/offices',
    label: 'Settings',
    icon: Settings,
    children: [
      { key: 'settings.offices', to: '/settings/offices', label: 'Offices', defaultVisible: (ctx) => ctx.hasGlobalAccess },
      { key: 'settings.inbox_config', to: '/settings/inbox-config', label: 'Inbox Configuration', defaultVisible: (ctx) => ctx.isOfficeAdminOrGlobal },
      { key: 'settings.bot_config', to: '/settings/bot-config', label: 'Bot Configuration', defaultVisible: (ctx) => ctx.hasGlobalAccess },
      { key: 'settings.blast_api', to: '/settings/blast-api', label: 'Blast API', defaultVisible: (ctx) => ctx.hasGlobalAccess },
      // Editing Menu Access itself is as sensitive as editing a Role's
      // scopes/organizational flags — same Superuser-only gate as Roles.
      { key: 'settings.menu_access', to: '/settings/menu-access', label: 'Menu Access', defaultVisible: (ctx) => ctx.isSuperuser },
    ],
  },
];

function isLeafVisible(item: LeafItem, ctx: VisibilityContext, override: string[] | null): boolean {
  if (override !== null) return override.includes(item.key);
  return item.defaultVisible(ctx);
}

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export function Sidebar({ collapsed, onToggleCollapsed, mobileOpen, onCloseMobile }: SidebarProps) {
  const { claims } = useAuth();
  const location = useLocation();
  // GET /api/auth/me/ — feeds the Inbox item's Office-access check below,
  // plus has_global_access/is_office_admin/visible_menu_items. Identity
  // display/Sign out moved to AccountMenu.tsx (TopBar, top-right) — this
  // Sidebar no longer renders an account section at all.
  const meQuery = useApiQuery(() => getMe(), []);
  const scopes = claims?.scopes ?? [];
  const hasOfficeAccess = meQuery.status === 'success' && (meQuery.data.has_global_access || meQuery.data.role !== null);
  const hasGlobalAccess = meQuery.status === 'success' && meQuery.data.has_global_access;
  const isOfficeAdminOrGlobal = meQuery.status === 'success' && (hasGlobalAccess || (meQuery.data.role?.is_office_admin ?? false));
  const isSuperuser = meQuery.status === 'success' && meQuery.data.is_superuser;
  // `null` (not customized) for a Superadmin (Me's own docstring: `role`
  // is always null for one) and for anyone without a membership row —
  // both correctly fall back to defaultVisible below.
  const menuOverride: string[] | null = meQuery.status === 'success' ? meQuery.data.role?.visible_menu_items ?? null : null;
  const ctx: VisibilityContext = { scopes, hasGlobalAccess, hasOfficeAccess, isOfficeAdminOrGlobal, isSuperuser };

  const visibleNavItems = NAV_ITEMS.map((item) => {
    if (item.key !== null) {
      return isLeafVisible(item, ctx, menuOverride) ? item : null;
    }
    const visibleChildren = item.children.filter((child) => isLeafVisible(child, ctx, menuOverride));
    return visibleChildren.length > 0 ? { ...item, children: visibleChildren } : null;
  }).filter((item): item is TopLevelItem => item !== null);

  // One expand/collapse flag per group, auto-expanded whenever the
  // current route is already under that group's own path prefix —
  // collapsed by default otherwise. Manual toggling (below) overrides
  // this for the rest of the session. Keyed by the group's own `to`
  // (unique per NAV_ITEMS entry), not by label.
  const groupPrefix = (to: string) => `/${to.split('/')[1]}`;
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      NAV_ITEMS.filter((item): item is TopLevelGroup => item.key === null).map((item) => [
        item.to,
        location.pathname.startsWith(groupPrefix(item.to)),
      ]),
    ),
  );

  return (
    <>
      {mobileOpen ? <div className="wa-sidebar-backdrop" onClick={onCloseMobile} /> : null}
      <aside className={['wa-sidebar', collapsed ? 'wa-sidebar--collapsed' : '', mobileOpen ? 'wa-sidebar--mobile-open' : ''].filter(Boolean).join(' ')}>
        <div className="wa-sidebar__brand">
          <Logo variant={collapsed ? 'mark' : 'horizontal'} height={28} />
          <IconButton
            icon={collapsed ? PanelLeftOpen : PanelLeftClose}
            label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            onClick={onToggleCollapsed}
            className="wa-sidebar__collapse-toggle"
          />
        </div>

        <nav className="wa-sidebar__nav" aria-label="Primary">
          {visibleNavItems.map((item) => {
            // Collapsed (icon-rail) mode: every item, including a group,
            // stays a single plain link — no room for a submenu, and
            // clicking it still reaches the section (its first child).
            if (item.key !== null || collapsed) {
              const to = item.to;
              const label = item.label;
              const Icon = item.icon;
              const end = item.key !== null ? item.end : false;
              return (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  onClick={onCloseMobile}
                  className={({ isActive }) => ['wa-sidebar__link', isActive ? 'wa-sidebar__link--active' : ''].filter(Boolean).join(' ')}
                  title={collapsed ? label : undefined}
                >
                  <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
                  {!collapsed && <span>{label}</span>}
                </NavLink>
              );
            }

            const { to, label, icon: Icon, children } = item;
            const expanded = expandedGroups[to] ?? false;
            const sectionActive = location.pathname.startsWith(groupPrefix(to));
            return (
              <div key={to} className="wa-sidebar__group">
                <button
                  type="button"
                  className={['wa-sidebar__link', 'wa-sidebar__group-toggle', sectionActive ? 'wa-sidebar__link--active' : '']
                    .filter(Boolean)
                    .join(' ')}
                  onClick={() => setExpandedGroups((prev) => ({ ...prev, [to]: !expanded }))}
                  aria-expanded={expanded}
                >
                  <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
                  <span>{label}</span>
                  {expanded ? (
                    <ChevronDown size={16} strokeWidth={1.75} aria-hidden="true" className="wa-sidebar__group-chevron" />
                  ) : (
                    <ChevronRight size={16} strokeWidth={1.75} aria-hidden="true" className="wa-sidebar__group-chevron" />
                  )}
                </button>
                {expanded ? (
                  <div className="wa-sidebar__submenu">
                    {children.map((child) => (
                      <NavLink
                        key={child.to}
                        to={child.to}
                        onClick={onCloseMobile}
                        className={({ isActive }) =>
                          ['wa-sidebar__sublink', isActive ? 'wa-sidebar__sublink--active' : ''].filter(Boolean).join(' ')
                        }
                      >
                        <span>{child.label}</span>
                      </NavLink>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </nav>
      </aside>
    </>
  );
}
