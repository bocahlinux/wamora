import { type ButtonHTMLAttributes } from 'react';
import type { LucideIcon } from 'lucide-react';

import './IconButton.css';

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: LucideIcon;
  label: string; // required, not optional — spec Section 16: "aria labels for icon-only buttons"
}

export function IconButton({ icon: Icon, label, className, ...rest }: IconButtonProps) {
  return (
    <button className={['wa-icon-button', className].filter(Boolean).join(' ')} aria-label={label} title={label} {...rest}>
      <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
    </button>
  );
}
