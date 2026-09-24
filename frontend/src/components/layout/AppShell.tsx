import { useState, type ReactNode } from 'react';

import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import './AppShell.css';

interface AppShellProps {
  children: ReactNode;
}

// The single reusable shell every authenticated page renders inside —
// task Section 9: "Do not duplicate shell markup across pages."
export function AppShell({ children }: AppShellProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="wa-app-shell">
      <Sidebar
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed((c) => !c)}
        mobileOpen={mobileOpen}
        onCloseMobile={() => setMobileOpen(false)}
      />
      <div className="wa-app-shell__main">
        <TopBar onOpenMobileNav={() => setMobileOpen(true)} />
        <main className="wa-app-shell__content">{children}</main>
      </div>
    </div>
  );
}
