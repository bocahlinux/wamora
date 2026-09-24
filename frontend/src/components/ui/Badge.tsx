import type { ReactNode } from 'react';

import './Badge.css';

export type BadgeTone = 'success' | 'warning' | 'error' | 'info' | 'offline' | 'neutral';

interface BadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
}

export function Badge({ tone = 'neutral', children }: BadgeProps) {
  return <span className={`wa-badge wa-badge--${tone}`}>{children}</span>;
}
