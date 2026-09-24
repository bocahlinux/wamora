import type { LucideIcon } from 'lucide-react';
import { Inbox } from 'lucide-react';
import type { ReactNode } from 'react';

import './EmptyState.css';

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon: Icon = Inbox, title, description, action }: EmptyStateProps) {
  return (
    <div className="wa-empty-state">
      <Icon size={32} strokeWidth={1.5} aria-hidden="true" className="wa-empty-state__icon" />
      <p className="wa-empty-state__title">{title}</p>
      {description ? <p className="wa-empty-state__description">{description}</p> : null}
      {action}
    </div>
  );
}
