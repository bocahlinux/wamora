import { useMemo, useRef, useState } from 'react';
import { ArrowLeft, Info, Upload } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { Input } from '../components/ui/Input';
import { PageHeader } from '../components/ui/PageHeader';
import type { ApiError } from '../lib/api';
import { createBlastCampaign } from '../lib/djangoApi';
import { config } from '../lib/config';
import './BlastPage.css';

// Step 0 finding: backend/apps/blast/serializers.py's
// BlastCampaignCreateSerializer only accepts `recipients` as a JSON array
// of destination strings — there is no file-upload endpoint anywhere in
// apps/blast/urls.py. Per the task brief, this page lets the operator pick
// a local .csv/.txt file and parses it CLIENT-SIDE into that same
// destinations array (no backend change, no new dependency) rather than
// claiming real file-upload or binary .xlsx support. frontend/package.json
// was checked directly — no CSV/Excel parsing library is a dependency, so
// none was added; parsing is hand-rolled (one destination per line, and/or
// comma-separated within a line — the server's own de-dup/validation in
// validate_recipients() remains the real enforcement boundary either way).
// Binary Excel (.xlsx) import was explicitly NOT implemented — seeing it
// requires a parsing library this project doesn't already depend on, and
// the task instructs against adding one for this.
function parseRecipients(raw: string): string[] {
  const tokens = raw
    .split(/[\n,]/)
    .map((token) => token.trim())
    .filter((token) => token.length > 0);
  // Order-preserving de-dup — a client-side courtesy mirroring the same
  // logic backend/apps/blast/serializers.py's validate_recipients() already
  // performs authoritatively; this just avoids showing a misleadingly high
  // preview count before the server's own validation runs.
  return Array.from(new Set(tokens));
}

// Hardcoded, static UI copy — backend/config/settings.py:317-319 defines
// BLAST_MAX_RECIPIENTS_PER_CAMPAIGN/BLAST_MAX_RECIPIENTS_PER_SESSION_PER_DAY/
// BLAST_INTER_MESSAGE_DELAY_SECONDS as env-configurable Django settings,
// but no endpoint in apps/blast/urls.py (or anywhere else) exposes their
// current values to the frontend (no OPTIONS handler, no dedicated limits
// endpoint) — these are the project's own documented defaults
// (docs/11-DECISIONS-AND-OPEN-QUESTIONS.md item 12), shown here as static
// copy, not fetched dynamically. If a deployment overrides these env vars,
// this banner and the client-side cap check below would understate/
// overstate the real limit — the server's own validation
// (serializers.py:53-57, views.py:169-179) remains authoritative either
// way, same "client-side is a courtesy, not the boundary" discipline this
// codebase already applies elsewhere (see createBlastCampaign's own
// docstring in lib/djangoApi.ts).
const MAX_RECIPIENTS_PER_CAMPAIGN = 100;
const MAX_RECIPIENTS_PER_SESSION_PER_DAY = 500;
const INTER_MESSAGE_DELAY_SECONDS = 60;

export function BlastCreatePage() {
  const navigate = useNavigate();
  const sessionName = config.wahaSessionName;

  const [name, setName] = useState('');
  const [messageTemplate, setMessageTemplate] = useState('');
  const [recipientsText, setRecipientsText] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<ApiError | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ name?: string; messageTemplate?: string; recipients?: string }>({});

  const recipients = useMemo(() => parseRecipients(recipientsText), [recipientsText]);
  const overCap = recipients.length > MAX_RECIPIENTS_PER_CAMPAIGN;

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ''; // allow re-selecting the same file later
    if (!file) return;
    const text = await file.text();
    setRecipientsText((prev) => (prev.trim() ? `${prev}\n${text}` : text));
  }

  function validate(): boolean {
    const errors: typeof fieldErrors = {};
    if (!name.trim()) errors.name = 'Campaign name is required.';
    if (!messageTemplate.trim()) errors.messageTemplate = 'Message template is required.';
    if (recipients.length === 0) errors.recipients = 'At least one recipient is required.';
    else if (overCap) errors.recipients = `A campaign may have at most ${MAX_RECIPIENTS_PER_CAMPAIGN} recipients (currently ${recipients.length}).`;
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function handleSubmit() {
    if (busy || !sessionName) return;
    if (!validate()) return;
    setBusy(true);
    setSubmitError(null);
    const result = await createBlastCampaign({
      session: sessionName,
      name: name.trim(),
      message_template: messageTemplate,
      recipients,
    });
    setBusy(false);
    if (!result.ok) {
      setSubmitError(result.error);
      return;
    }
    navigate(`/blast/${result.data.id}`);
  }

  return (
    <div>
      <Button variant="ghost" className="wa-blast-back" onClick={() => navigate('/blast')}>
        <ArrowLeft size={16} strokeWidth={1.75} aria-hidden="true" />
        Back to campaigns
      </Button>

      <PageHeader title="New campaign" description="Draft a controlled bulk WhatsApp send for approval." />

      {!sessionName ? (
        <EmptyState
          icon={Info}
          title="No session configured"
          description="Set VITE_WAHA_SESSION_NAME to create a blast campaign."
        />
      ) : (
        <>
          <p className="wa-blast-limits">
            <Info size={16} strokeWidth={1.75} aria-hidden="true" className="wa-blast-limits__icon" />
            <span>
              Up to {MAX_RECIPIENTS_PER_CAMPAIGN} recipients per campaign, {MAX_RECIPIENTS_PER_SESSION_PER_DAY} per
              session per day, with a {INTER_MESSAGE_DELAY_SECONDS}-second delay enforced between each message. The
              server checks these limits when the campaign is created and approved — this is shown for planning
              purposes and is not fetched dynamically.
            </span>
          </p>

          <Card>
            <div className="wa-blast-form">
              <div className="wa-blast-form__field">
                <span className="wa-blast-form__label">WhatsApp session</span>
                <span className="wa-blast-form__hint">{sessionName} (the only session configured for this deployment)</span>
              </div>

              <Input
                label="Campaign name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                errorMessage={fieldErrors.name}
                disabled={busy}
              />

              <div className="wa-blast-form__field">
                <label className="wa-blast-form__label" htmlFor="blast-message-template">
                  Message template
                </label>
                <textarea
                  id="blast-message-template"
                  className={['wa-blast-form__textarea', fieldErrors.messageTemplate ? 'wa-blast-form__textarea--error' : '']
                    .filter(Boolean)
                    .join(' ')}
                  value={messageTemplate}
                  onChange={(e) => setMessageTemplate(e.target.value)}
                  disabled={busy}
                  rows={4}
                />
                {fieldErrors.messageTemplate ? <p className="wa-blast-form__error">{fieldErrors.messageTemplate}</p> : null}
              </div>

              <div className="wa-blast-form__field">
                <label className="wa-blast-form__label" htmlFor="blast-recipients">
                  Recipients — one per line, or comma-separated
                </label>
                <textarea
                  id="blast-recipients"
                  className={[
                    'wa-blast-form__textarea',
                    'wa-blast-form__recipients',
                    fieldErrors.recipients ? 'wa-blast-form__textarea--error' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  value={recipientsText}
                  onChange={(e) => setRecipientsText(e.target.value)}
                  disabled={busy}
                  rows={6}
                  placeholder={'628123456789\n628987654321'}
                />
                <div className="wa-blast-form__file-row">
                  <Button variant="secondary" type="button" onClick={() => fileInputRef.current?.click()} disabled={busy}>
                    <Upload size={16} strokeWidth={1.75} aria-hidden="true" />
                    Import .csv/.txt
                  </Button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".csv,.txt,text/csv,text/plain"
                    style={{ display: 'none' }}
                    onChange={handleFileChange}
                  />
                  <span
                    className={['wa-blast-form__preview', overCap ? 'wa-blast-form__preview--over-cap' : ''].filter(Boolean).join(' ')}
                  >
                    {recipients.length} unique recipient{recipients.length === 1 ? '' : 's'} parsed
                    {overCap ? ` — exceeds the ${MAX_RECIPIENTS_PER_CAMPAIGN} cap` : ''}
                  </span>
                </div>
                {fieldErrors.recipients ? <p className="wa-blast-form__error">{fieldErrors.recipients}</p> : null}
                {recipients.length > 0 ? (
                  <pre className="wa-blast-form__preview-list">{recipients.join('\n')}</pre>
                ) : null}
              </div>

              {submitError ? <ErrorState error={submitError} /> : null}

              <div className="wa-blast-form__actions">
                <Button variant="primary" onClick={handleSubmit} disabled={busy}>
                  {busy ? 'Creating…' : 'Create draft campaign'}
                </Button>
                <Button variant="ghost" onClick={() => navigate('/blast')} disabled={busy}>
                  Cancel
                </Button>
              </div>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
