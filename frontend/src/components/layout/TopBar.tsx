import { Menu, Moon, Sun, SunMoon } from 'lucide-react';

import { useTheme } from '../../theme/ThemeContext';
import { IconButton } from '../ui/IconButton';
import './TopBar.css';

interface TopBarProps {
  onOpenMobileNav: () => void;
  title?: string;
}

const THEME_CYCLE = { light: 'dark', dark: 'system', system: 'light' } as const;
const THEME_ICON = { light: Sun, dark: Moon, system: SunMoon } as const;
const THEME_LABEL = { light: 'Light theme', dark: 'Dark theme', system: 'System theme' } as const;

// Spec Section 7: "The header should remain visually quiet so operational
// content dominates." No global search here yet — no search backend
// exists for Phase 7 to call, and a decorative, non-functional search box
// would be exactly the "fake successful API behavior" this phase's
// instructions forbid.
export function TopBar({ onOpenMobileNav, title }: TopBarProps) {
  const { preference, setPreference } = useTheme();
  const ThemeIcon = THEME_ICON[preference];

  return (
    <header className="wa-topbar">
      <div className="wa-topbar__left">
        <IconButton icon={Menu} label="Open navigation" onClick={onOpenMobileNav} className="wa-topbar__menu-toggle" />
        {title ? <span className="wa-topbar__title">{title}</span> : null}
      </div>
      <div className="wa-topbar__right">
        <IconButton
          icon={ThemeIcon}
          label={`Theme: ${THEME_LABEL[preference]} (click to change)`}
          onClick={() => setPreference(THEME_CYCLE[preference])}
        />
      </div>
    </header>
  );
}
