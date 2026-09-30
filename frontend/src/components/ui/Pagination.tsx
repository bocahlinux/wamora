import { ChevronLeft, ChevronRight } from 'lucide-react';

import { Button } from './Button';
import './Pagination.css';

interface PaginationProps {
  page: number;
  hasPrevious: boolean;
  hasNext: boolean;
  onPrevious: () => void;
  onNext: () => void;
  /** Total row count across every page, when known (DRF's `count`) —
   * shown as "Page N of M" instead of a bare "Page N" when present. */
  totalCount?: number;
  pageSize?: number;
  disabled?: boolean;
}

// Shared server-side pagination control — Settings' admin tables
// (Users, and any future paginated table) all use this one component
// instead of each reimplementing its own Prev/Next markup.
export function Pagination({ page, hasPrevious, hasNext, onPrevious, onNext, totalCount, pageSize, disabled }: PaginationProps) {
  const totalPages = totalCount != null && pageSize ? Math.max(1, Math.ceil(totalCount / pageSize)) : null;
  return (
    <div className="wa-pagination">
      <span className="wa-pagination__summary">
        {totalPages ? `Page ${page} of ${totalPages}` : `Page ${page}`}
        {totalCount != null ? ` — ${totalCount} total` : ''}
      </span>
      <div className="wa-pagination__controls">
        <Button variant="secondary" onClick={onPrevious} disabled={disabled || !hasPrevious}>
          <ChevronLeft size={16} strokeWidth={1.75} aria-hidden="true" />
          Previous
        </Button>
        <Button variant="secondary" onClick={onNext} disabled={disabled || !hasNext}>
          Next
          <ChevronRight size={16} strokeWidth={1.75} aria-hidden="true" />
        </Button>
      </div>
    </div>
  );
}
