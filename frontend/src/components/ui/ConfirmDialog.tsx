import { Button, type ButtonVariant } from './Button';
import { Modal } from './Modal';
import './ConfirmDialog.css';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  variant?: ButtonVariant;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

// wamora-design-assets design spec Section 8 names ConfirmDialog as a core
// primitive; Section 12: "Destructive actions must require appropriate
// confirmation." Used only for genuinely destructive session actions
// (Stop, Logout) — not added to Start/Restart, which aren't destructive.
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  variant = 'danger',
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Modal open={open} onClose={onCancel} title={title}>
      <p className="wa-confirm-dialog__description">{description}</p>
      <div className="wa-confirm-dialog__actions">
        <Button variant="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button variant={variant} onClick={onConfirm} disabled={busy}>
          {busy ? 'Working…' : confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
