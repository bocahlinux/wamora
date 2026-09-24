import { MessageCircle } from 'lucide-react';

import { PlaceholderPage } from './PlaceholderPage';

// The design spec's sidebar order (Section 7) names a "WhatsApp" nav item
// between Dashboard and Inbox, but neither the visual spec nor any
// functional doc (docs/00-MASTER-SPEC.md, docs/03-UI-UX-SPEC.md) defines
// what content this screen shows beyond the Dashboard/Inbox/Sessions
// pages that already exist separately. Kept as a placeholder rather than
// guessing at its content — see the implementation report.
export function WhatsAppPage() {
  return (
    <PlaceholderPage
      title="WhatsApp"
      icon={MessageCircle}
      description="WhatsApp overview."
      dependencyNote="This screen's exact scope isn't defined by any functional specification yet, separately from Dashboard/Sessions/Inbox — flagged for product clarification rather than guessed at."
    />
  );
}
