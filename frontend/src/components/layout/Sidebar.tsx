import { BarChart3, Inbox, LayoutDashboard, Megaphone, MessageCircle, PanelLeftClose, PanelLeftOpen, Settings, Smartphone, User } from 'lucide-react';
import { NavLink } from 'react-router-dom';

import { Logo } from '../brand/Logo';
import { useAuth } from '../../lib/AuthContext';
import { getMe } from '../../lib/djangoApi';
import { useApiQuery } from '../../lib/useApiQuery';
import { IconButton } from '../ui/IconButton';
import './Sidebar.css';

// Navigation order and icon mapping taken directly from
// wamora-design-assets/docs/WAMORA-FRONTEND-DESIGN-SPEC.md Sections 6/7.
//
// Dynamic Role-based menu access — `requiredScope`, when present, must be
// one of the caller's JWT `scopes` (from the same Role-driven Group sync
// every backend/BFF check already reads — apps.offices.serializers's
// `_sync_role_groups`) for the item to render at all. `dashboard`/
// `sessions` -> 'reading' mirrors `HasReadingScope`/the BFF session-status
// route; `blast` -> 'blast' mirrors `HasBlastScope`. `whatsapp`/`reports`
// have no backing API at all yet (both are still placeholders — nothing
// to protect), so they stay unconditional. `inbox` isn't scope-gated at
// all backend-side (`HasOfficeAccess` checks Office
// role/membership instead, a deliberately separate axis — see
// apps/authn/permissions.py's own docstring) — its visibility below uses
// `me.has_global_access || me.role !== null` instead of `requiredScope`.
//
// This is UX only — hiding an item a caller's token doesn't cover never
// replaces the server-side check (`lib/auth.ts`'s own decodeToken()
// docstring: "the frontend must never make a security decision based on
// this decoded value alone"); every route still enforces itself
// regardless of what this Sidebar shows.
const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true, requiredScope: 'reading' },
  { to: '/whatsapp', label: 'WhatsApp', icon: MessageCircle, end: false, requiredScope: null },
  { to: '/inbox', label: 'Inbox', icon: Inbox, end: false, requiredScope: null, requiresOfficeAccess: true },
  { to: '/sessions', label: 'Sessions', icon: Smartphone, end: false, requiredScope: 'reading' },
  { to: '/blast', label: 'Blast', icon: Megaphone, end: false, requiredScope: 'blast' },
  { to: '/reports', label: 'Reports', icon: BarChart3, end: false, requiredScope: null },
  { to: '/settings', label: 'Settings', icon: Settings, end: false, requiredScope: null },
] as const;

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export function Sidebar({ collapsed, onToggleCollapsed, mobileOpen, onCloseMobile }: SidebarProps) {
  const { logout, claims } = useAuth();
  // GET /api/auth/me/ (docs/generated/PHASE-8-DASHBOARD-BACKEND-FOUNDATION-REPORT.md)
  // replaces the placeholder "Signed in" text with the real caller
  // identity. Loading/error both keep showing that same neutral label —
  // never a fabricated name — rather than adding a spinner to this
  // compact footer. Also feeds the Inbox item's Office-access check
  // below (`requiresOfficeAccess`) — this is the one already-fetched
  // query that has that data, no second call.
  const meQuery = useApiQuery(() => getMe(), []);
  const scopes = claims?.scopes ?? [];
  const hasOfficeAccess = meQuery.status === 'success' && (meQuery.data.has_global_access || meQuery.data.role !== null);
  const visibleNavItems = NAV_ITEMS.filter((item) => {
    if ('requiresOfficeAccess' in item && item.requiresOfficeAccess) return hasOfficeAccess;
    if (item.requiredScope !== null) return scopes.includes(item.requiredScope);
    return true;
  });

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
          {visibleNavItems.map(({ to, label, icon: Icon, end }) => (
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
          ))}
        </nav>

        <div className="wa-sidebar__account">
          {/* The Phase 6 JWT carries only `sub`/`scopes`, no display
              name (docs/generated/PHASE-6-FINAL-IMPLEMENTATION-CONTRACT.md
              Section 4) — real identity now comes from GET /api/auth/me/
              instead. Still a generic icon, not a fabricated avatar
              image: the API returns no avatar. */}
          <div className="wa-sidebar__account-avatar" aria-hidden="true">
            <User size={16} strokeWidth={1.75} />
          </div>
          {!collapsed && (
            <div className="wa-sidebar__account-info">
              <span className="wa-sidebar__account-name" title={meQuery.status === 'success' ? meQuery.data.display_name : undefined}>
                {meQuery.status === 'success' ? meQuery.data.display_name : 'Signed in'}
              </span>
              <button type="button" className="wa-sidebar__logout" onClick={logout}>
                Sign out
              </button>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
