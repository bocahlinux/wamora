import { BarChart3 } from 'lucide-react';

import { PlaceholderPage } from './PlaceholderPage';

// No coding phase has yet defined a reports/metrics API — not assigned to
// Phase 7 by docs/15-CODING-PHASES.md or the Phase 7 task's own scope.
export function ReportsPage() {
  return (
    <PlaceholderPage
      title="Reports"
      icon={BarChart3}
      description="Operational metrics and trends."
      dependencyNote="Reports has no backing API yet in any coding phase completed so far."
    />
  );
}
