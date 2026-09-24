import { Loader2 } from 'lucide-react';

import './LoadingState.css';

interface LoadingStateProps {
  label?: string;
}

// Never a permanent/unlabeled spinner (task Section 14: "Do not show a
// permanent spinner") — always paired with a text label so a stuck load
// state is diagnosable, and respects prefers-reduced-motion via the
// global.css rule that caps all animation durations.
export function LoadingState({ label = 'Loading…' }: LoadingStateProps) {
  return (
    <div className="wa-loading-state" role="status">
      <Loader2 className="wa-loading-state__spinner" size={20} aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
