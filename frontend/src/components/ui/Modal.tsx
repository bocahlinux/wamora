import { useEffect, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';

import { IconButton } from './IconButton';
import './Modal.css';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}

const FOCUSABLE_SELECTOR = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

// wamora-design-assets design spec Section 8 names Modal/Dialog as a core
// UI primitive; none existed before Session Management (see
// docs/generated/SESSION-MANAGEMENT-IMPLEMENTATION-REPORT.md). No
// third-party modal library was added — this is the smallest primitive
// that satisfies spec Section 16's accessibility requirements (keyboard
// navigable, visible focus, dialogs trap focus correctly).
export function Modal({ open, onClose, title, children }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const dialog = dialogRef.current;
    dialog?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !dialog) return;
      const focusables = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="wa-modal-backdrop" onClick={onClose}>
      <div
        className="wa-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={dialogRef}
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="wa-modal__header">
          <h2 className="wa-modal__title">{title}</h2>
          <IconButton icon={X} label="Close" onClick={onClose} />
        </div>
        <div className="wa-modal__body">{children}</div>
      </div>
    </div>
  );
}
