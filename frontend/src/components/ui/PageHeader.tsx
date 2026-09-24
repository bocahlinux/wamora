import type { ReactNode } from 'react';

import './PageHeader.css';

interface PageHeaderProps {
  title: string;
  description?: string;
  actions?: ReactNode;
}

export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <div className="wa-page-header">
      <div>
        <h1 className="wa-page-header__title">{title}</h1>
        {description ? <p className="wa-page-header__description">{description}</p> : null}
      </div>
      {actions ? <div className="wa-page-header__actions">{actions}</div> : null}
    </div>
  );
}
