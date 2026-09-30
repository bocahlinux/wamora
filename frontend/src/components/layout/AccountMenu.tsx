import { useEffect, useRef, useState } from 'react';
import { ChevronDown, LogOut, User } from 'lucide-react';
import { NavLink } from 'react-router-dom';

import { useAuth } from '../../lib/AuthContext';
import { getMe } from '../../lib/djangoApi';
import { useApiQuery } from '../../lib/useApiQuery';
import './AccountMenu.css';

function initialsFor(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

// Discussed requirement — Profile and Sign out move from the Sidebar
// footer into one dropdown anchored top-right (was previously the
// bottom of the Sidebar — Sidebar.tsx no longer renders an account
// section at all). Closes on an outside click, Escape, or navigating to
// Profile — this is an ordinary menu, not a CRUD modal, so it does not
// follow Modal.tsx's stricter "only X/Cancel" contract.
export function AccountMenu() {
  const { logout } = useAuth();
  const meQuery = useApiQuery(() => getMe(), []);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    function handlePointerDown(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false);
    }

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  const displayName = meQuery.status === 'success' ? meQuery.data.display_name : 'Signed in';

  return (
    <div className="wa-account-menu" ref={containerRef}>
      <button
        type="button"
        className="wa-account-menu__trigger"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className="wa-account-menu__avatar" aria-hidden="true">
          {meQuery.status === 'success' ? initialsFor(displayName) : <User size={16} strokeWidth={1.75} />}
        </span>
        <span className="wa-account-menu__name">{displayName}</span>
        <ChevronDown
          size={16}
          strokeWidth={1.75}
          aria-hidden="true"
          className={['wa-account-menu__chevron', open ? 'wa-account-menu__chevron--open' : ''].filter(Boolean).join(' ')}
        />
      </button>

      {open ? (
        <div className="wa-account-menu__panel" role="menu">
          <NavLink to="/profile" role="menuitem" className="wa-account-menu__item" onClick={() => setOpen(false)}>
            <User size={16} strokeWidth={1.75} aria-hidden="true" />
            Profile
          </NavLink>
          <button
            type="button"
            role="menuitem"
            className="wa-account-menu__item wa-account-menu__item--danger"
            onClick={logout}
          >
            <LogOut size={16} strokeWidth={1.75} aria-hidden="true" />
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}
