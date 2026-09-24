import { type ButtonHTMLAttributes, type ReactNode } from 'react';

import './Button.css';

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  children: ReactNode;
}

// wamora-design-assets design spec Section 8: "Do not make every action a
// primary colored button." variant defaults to 'secondary' so callers make
// an explicit choice to escalate to 'primary'/'danger'.
export function Button({ variant = 'secondary', className, children, ...rest }: ButtonProps) {
  return (
    <button className={['wa-button', `wa-button--${variant}`, className].filter(Boolean).join(' ')} {...rest}>
      {children}
    </button>
  );
}
