import type { LucideIcon } from 'lucide-react';

import { Card } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { PageHeader } from '../components/ui/PageHeader';

interface PlaceholderPageProps {
  title: string;
  icon: LucideIcon;
  description: string;
  dependencyNote: string;
}

// Used for nav destinations whose real functionality is explicitly
// assigned to a later coding phase (docs/15-CODING-PHASES.md) and has no
// backend to call yet — task Section 10: "Do not fake successful API
// behavior" / "clearly separate UI shell/state from actual functional
// integration." The route and shell exist (satisfying "application
// shell must be reusable by subsequent phases"); the page content is an
// honest EmptyState, not a mocked table/list.
export function PlaceholderPage({ title, icon, description, dependencyNote }: PlaceholderPageProps) {
  return (
    <div>
      <PageHeader title={title} description={description} />
      <Card>
        <EmptyState icon={icon} title="Not yet available" description={dependencyNote} />
      </Card>
    </div>
  );
}
