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
const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/whatsapp', label: 'WhatsApp', icon: MessageCircle, end: false },
  { to: '/inbox', label: 'Inbox', icon: Inbox, end: false },
  { to: '/sessions', label: 'Sessions', icon: Smartphone, end: false },
  { to: '/blast', label: 'Blast', icon: Megaphone, end: false },
  { to: '/reports', label: 'Reports', icon: BarChart3, end: false },
  { to: '/settings', label: 'Settings', icon: Settings, end: false },
] as const;

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export function Sidebar({ collapsed, onToggleCollapsed, mobileOpen, onCloseMobile }: SidebarProps) {
  const { logout } = useAuth();
  // GET /api/auth/me/ (docs/generated/PHASE-8-DASHBOARD-BACKEND-FOUNDATION-REPORT.md)
  // replaces the placeholder "Signed in" text with the real caller
  // identity. Loading/error both keep showing that same neutral label —
  // never a fabricated name — rather than adding a spinner to this
  // compact footer.
  const meQuery = useApiQuery(() => getMe(), []);

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
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
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
