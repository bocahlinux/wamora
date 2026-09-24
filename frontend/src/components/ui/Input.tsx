import { forwardRef, useId, type InputHTMLAttributes } from 'react';

import './Input.css';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  errorMessage?: string;
}

// Spec Section 16: "form labels" — every Input renders a real <label>
// associated by id, never a placeholder-only field.
export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, errorMessage, id, className, ...rest },
  ref,
) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  return (
    <div className="wa-field">
      <label htmlFor={inputId} className="wa-field__label">
        {label}
      </label>
      <input
        id={inputId}
        ref={ref}
        className={['wa-field__input', errorMessage ? 'wa-field__input--error' : '', className].filter(Boolean).join(' ')}
        aria-invalid={errorMessage ? true : undefined}
        aria-describedby={errorMessage ? `${inputId}-error` : undefined}
        {...rest}
      />
      {errorMessage ? (
        <p id={`${inputId}-error`} className="wa-field__error" role="alert">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
});
