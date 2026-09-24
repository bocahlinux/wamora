import { FileQuestion } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Button } from '../components/ui/Button';
import { EmptyState } from '../components/ui/EmptyState';

export function NotFoundPage() {
  return (
    <div style={{ display: 'flex', minHeight: '100%', alignItems: 'center', justifyContent: 'center', padding: 'var(--space-6)' }}>
      <EmptyState
        icon={FileQuestion}
        title="Page not found"
        description="The page you're looking for doesn't exist."
        action={
          <Link to="/">
            <Button variant="primary">Back to Dashboard</Button>
          </Link>
        }
      />
    </div>
  );
}
