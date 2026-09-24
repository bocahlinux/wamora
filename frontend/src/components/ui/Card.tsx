import type { HTMLAttributes, ReactNode } from 'react';

import './Card.css';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function Card({ className, children, ...rest }: CardProps) {
  return (
    <div className={['wa-card', className].filter(Boolean).join(' ')} {...rest}>
      {children}
    </div>
  );
}
