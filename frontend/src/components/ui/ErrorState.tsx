import { AlertTriangle } from 'lucide-react';

import type { ApiError } from '../../lib/api';
import { describeError } from '../../lib/api';
import { Button } from './Button';
import './ErrorState.css';

interface ErrorStateProps {
  error: ApiError;
  onRetry?: () => void;
}

// task Section 14: never a raw server stack trace or sensitive backend
// response — describeError() already maps every ApiError kind to a short,
// operator-appropriate sentence.
export function ErrorState({ error, onRetry }: ErrorStateProps) {
  return (
    <div className="wa-error-state" role="alert">
      <AlertTriangle size={28} strokeWidth={1.5} aria-hidden="true" className="wa-error-state__icon" />
      <p className="wa-error-state__message">{describeError(error)}</p>
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
