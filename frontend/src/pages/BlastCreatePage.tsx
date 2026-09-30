import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, Info, MessageSquare, Send, Upload, Users } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { Input } from '../components/ui/Input';
import { PageHeader } from '../components/ui/PageHeader';
import type { ApiError } from '../lib/api';
import {
  createBlastCampaign,
  getBlastTemplates,
  getMe,
  listOffices,
  type BlastRecipientInput,
  type BlastRecipientValidationDetail,
  type BlastTemplate,
  type OfficeChoice,
} from '../lib/djangoApi';
import { config } from '../lib/config';
import { useApiQuery, type QueryState } from '../lib/useApiQuery';
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

// Discussed requirement — Blast Templates + per-recipient variables. Once
// a template is chosen, the freeform recipients textarea above is
// replaced by a CSV paste/upload whose expected header is
// `destination,<var1>,<var2>,...` (exactly the template's own detected
// variable names, in any order) — parsed and shape-checked here, client-
// side, purely for fast feedback; the server (serializers.py's validate())
// remains the authoritative, re-checked boundary, same "client-side is a
// courtesy, not the boundary" discipline this page already applies to the
// freeform path's own recipient cap.
interface ParsedTemplateRecipients {
  recipients: BlastRecipientInput[];
  headerError?: string;
}

function parseTemplateRecipientsCsv(raw: string, variableNames: string[]): ParsedTemplateRecipients {
  const lines = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  if (lines.length === 0) return { recipients: [] };

  const header = lines[0].split(',').map((cell) => cell.trim());
  if (header[0] !== 'destination') {
    return { recipients: [], headerError: 'The first column must be "destination".' };
  }
  const headerVars = header.slice(1);
  const missingCols = variableNames.filter((v) => !headerVars.includes(v));
  const extraCols = headerVars.filter((v) => !variableNames.includes(v));
  if (missingCols.length > 0 || extraCols.length > 0) {
    const parts: string[] = [`Header must be: destination,${variableNames.join(',')}`];
    if (missingCols.length > 0) parts.push(`missing column(s): ${missingCols.join(', ')}`);
    if (extraCols.length > 0) parts.push(`unexpected column(s): ${extraCols.join(', ')}`);
    return { recipients: [], headerError: parts.join(' — ') };
  }

  const byDestination = new Map<string, BlastRecipientInput>();
  for (const line of lines.slice(1)) {
    const cells = line.split(',').map((cell) => cell.trim());
    const destination = cells[0];
    if (!destination) continue;
    const variables: Record<string, string> = {};
    headerVars.forEach((name, index) => {
      variables[name] = cells[index + 1] ?? '';
    });
    byDestination.set(destination, { destination, variables });
  }
  return { recipients: Array.from(byDestination.values()) };
}

// Hardcoded, static UI copy — backend/config/settings.py:317-319 defines
// BLAST_MAX_RECIPIENTS_PER_CAMPAIGN/BLAST_MAX_RECIPIENTS_PER_SESSION_PER_DAY
// as env-configurable Django settings, but no endpoint exposes their
// current values to the frontend — the project's own documented defaults,
// shown as static copy. The inter-message delay is now a dynamic,
// admin-editable value (BlastSettings, Settings > Blast API) rather than a
// fixed number, so it is deliberately NOT restated here as a hardcoded
// figure anymore.
const MAX_RECIPIENTS_PER_CAMPAIGN = 100;
const MAX_RECIPIENTS_PER_SESSION_PER_DAY = 500;

export function BlastCreatePage() {
  const navigate = useNavigate();
  const sessionName = config.wahaSessionName;

  const [name, setName] = useState('');
  const [messageTemplate, setMessageTemplate] = useState('');
  const [recipientsText, setRecipientsText] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Discussed requirement — optional template picker.
  const templatesQuery = useApiQuery(() => getBlastTemplates(), []);
  const [templateId, setTemplateId] = useState<number | ''>('');
  const selectedTemplate: BlastTemplate | undefined =
    templatesQuery.status === 'success' && templateId !== ''
      ? templatesQuery.data.find((t) => t.id === templateId)
      : undefined;
  // `selectedTemplate?.variable_names ?? []` would build a brand-new
  // array on every render even when the selected template hasn't
  // changed, which would in turn re-run every hook below that depends on
  // it — memoized directly on that same array reference (stable for as
  // long as the fetched template list itself doesn't change).
  const variableNames = useMemo(() => selectedTemplate?.variable_names ?? [], [selectedTemplate?.variable_names]);
  const [templateRecipientsText, setTemplateRecipientsText] = useState('');
  const templateFileInputRef = useRef<HTMLInputElement>(null);

  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<ApiError | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ name?: string; messageTemplate?: string; recipients?: string; office?: string }>({});

  // Step 4 (Blast <-> Office integration) — a globally-accessing user
  // (Superadmin/Global Admin) must pick an Office explicitly; everyone
  // else's Office is fixed by their own membership and assigned
  // server-side (serializers.py's validate()), so no picker is shown.
  const meQuery = useApiQuery(() => getMe(), []);
  const hasGlobalAccess = meQuery.status === 'success' && meQuery.data.has_global_access;
  const [officeId, setOfficeId] = useState<number | ''>('');
  const [officeChoices, setOfficeChoices] = useState<QueryState<OfficeChoice[]>>({ status: 'loading' });

  useEffect(() => {
    if (!hasGlobalAccess) return;
    let cancelled = false;
    setOfficeChoices({ status: 'loading' });
    listOffices().then((result) => {
      if (cancelled) return;
      setOfficeChoices(result.ok ? { status: 'success', data: result.data } : { status: 'error', error: result.error });
    });
    return () => {
      cancelled = true;
    };
  }, [hasGlobalAccess]);

  const freeformRecipients = useMemo(() => parseRecipients(recipientsText), [recipientsText]);
  const templateParsed = useMemo(
    () => parseTemplateRecipientsCsv(templateRecipientsText, variableNames),
    [templateRecipientsText, variableNames],
  );

  const recipients: string[] | BlastRecipientInput[] = selectedTemplate ? templateParsed.recipients : freeformRecipients;
  const overCap = recipients.length > MAX_RECIPIENTS_PER_CAMPAIGN;

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ''; // allow re-selecting the same file later
    if (!file) return;
    const text = await file.text();
    setRecipientsText((prev) => (prev.trim() ? `${prev}\n${text}` : text));
  }

  async function handleTemplateFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    const text = await file.text();
    setTemplateRecipientsText(text);
  }

  function validate(): boolean {
    const errors: typeof fieldErrors = {};
    if (!name.trim()) errors.name = 'Campaign name is required.';
    if (!selectedTemplate && !messageTemplate.trim()) errors.messageTemplate = 'Message template is required.';
    if (recipients.length === 0) {
      errors.recipients = selectedTemplate
        ? 'At least one recipient is required. Paste destination + variable columns below.'
        : 'At least one recipient is required.';
    } else if (overCap) {
      errors.recipients = `A campaign may have at most ${MAX_RECIPIENTS_PER_CAMPAIGN} recipients (currently ${recipients.length}).`;
    } else if (selectedTemplate && templateParsed.headerError) {
      errors.recipients = templateParsed.headerError;
    }
    if (hasGlobalAccess && officeId === '') errors.office = 'An Office is required.';
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
      recipients,
      ...(selectedTemplate ? { template: selectedTemplate.id } : { message_template: messageTemplate }),
      ...(hasGlobalAccess && officeId !== '' ? { office: officeId } : {}),
    });
    setBusy(false);
    if (!result.ok) {
      setSubmitError(result.error);
      return;
    }
    navigate(`/blast/${result.data.id}`);
  }

  // Discussed requirement — the all-or-nothing per-row validation error
  // (serializers.py's validate(): ANY recipient row with a missing/extra
  // variable rejects the whole request) is surfaced with the offending
  // rows named, not just a generic "could not be processed" line.
  const validationDetails: BlastRecipientValidationDetail[] | undefined =
    submitError?.kind === 'validation' && Array.isArray(submitError.details)
      ? (submitError.details as BlastRecipientValidationDetail[])
      : undefined;

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
              session per day. An admin-configurable delay is enforced between each message (Settings &gt; Blast
              API). The server checks these limits when the campaign is created and approved — this is shown for
              planning purposes and is not fetched dynamically.
            </span>
          </p>

          <div className="wa-blast-form-body">
            <Card className="wa-blast-section">
              <div className="wa-blast-section__header">
                <Info size={18} strokeWidth={1.75} aria-hidden="true" />
                <div>
                  <h2 className="wa-blast-section__title">Campaign details</h2>
                  <p className="wa-blast-section__description">Session, Office, template, and a name to identify this campaign.</p>
                </div>
              </div>
              <div className="wa-blast-form">
                <div className="wa-blast-form__field">
                  <span className="wa-blast-form__label">WhatsApp session</span>
                  <span className="wa-blast-form__hint">{sessionName} (the only session configured for this deployment)</span>
                </div>

                {hasGlobalAccess ? (
                  <div className="wa-blast-form__field">
                    <label className="wa-blast-form__label" htmlFor="blast-office">
                      Office
                    </label>
                    {officeChoices.status === 'loading' ? (
                      <span className="wa-blast-form__hint">Loading offices…</span>
                    ) : officeChoices.status === 'error' ? (
                      <ErrorState error={officeChoices.error} />
                    ) : (
                      <select
                        id="blast-office"
                        className="wa-blast-form__select"
                        value={officeId}
                        onChange={(e) => setOfficeId(e.target.value ? Number(e.target.value) : '')}
                        disabled={busy}
                      >
                        <option value="">Select an Office…</option>
                        {officeChoices.data.map((office) => (
                          <option key={office.id} value={office.id}>
                            {office.name}
                          </option>
                        ))}
                      </select>
                    )}
                    {fieldErrors.office ? <p className="wa-blast-form__error">{fieldErrors.office}</p> : null}
                  </div>
                ) : meQuery.status === 'success' ? (
                  <div className="wa-blast-form__field">
                    <span className="wa-blast-form__label">Office</span>
                    <span className="wa-blast-form__hint">
                      {meQuery.data.office
                        ? `${meQuery.data.office.name} (assigned automatically)`
                        : 'You are not assigned to any Office; contact an administrator before creating a campaign.'}
                    </span>
                  </div>
                ) : null}

                <Input
                  label="Campaign name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  errorMessage={fieldErrors.name}
                  disabled={busy}
                />

                <div className="wa-blast-form__field">
                  <label className="wa-blast-form__label" htmlFor="blast-template">
                    Template (optional)
                  </label>
                  {templatesQuery.status === 'loading' ? (
                    <span className="wa-blast-form__hint">Loading templates…</span>
                  ) : templatesQuery.status === 'error' ? (
                    <ErrorState error={templatesQuery.error} />
                  ) : (
                    <select
                      id="blast-template"
                      className="wa-blast-form__select"
                      value={templateId}
                      onChange={(e) => {
                        setTemplateId(e.target.value ? Number(e.target.value) : '');
                        setTemplateRecipientsText('');
                      }}
                      disabled={busy}
                    >
                      <option value="">No template — freeform message</option>
                      {templatesQuery.data
                        .filter((t) => t.is_active)
                        .map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.name} ({t.key})
                          </option>
                        ))}
                    </select>
                  )}
                  <span className="wa-blast-form__hint">
                    Choosing a template replaces the freeform message and recipients below with the template's own
                    content and a per-recipient variable list.
                  </span>
                </div>
              </div>
            </Card>

            <Card className="wa-blast-section">
              <div className="wa-blast-section__header">
                <MessageSquare size={18} strokeWidth={1.75} aria-hidden="true" />
                <div>
                  <h2 className="wa-blast-section__title">Message</h2>
                  <p className="wa-blast-section__description">
                    {selectedTemplate
                      ? "This campaign's message comes from the selected template — fill in each recipient's variables below."
                      : 'The text template sent to every recipient below.'}
                  </p>
                </div>
              </div>
              <div className="wa-blast-form">
                {selectedTemplate ? (
                  <div className="wa-blast-form__field">
                    <span className="wa-blast-form__label">Template content</span>
                    <pre className="wa-blast-detail__template">{selectedTemplate.content}</pre>
                    {variableNames.length > 0 ? (
                      <div className="wa-blast-form__file-row">
                        {variableNames.map((v) => (
                          <Badge key={v} tone="info">
                            {`{{${v}}}`}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <span className="wa-blast-form__hint">This template has no variables.</span>
                    )}
                  </div>
                ) : (
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
                )}
              </div>
            </Card>

            <Card className="wa-blast-section">
              <div className="wa-blast-section__header">
                <Users size={18} strokeWidth={1.75} aria-hidden="true" />
                <div>
                  <h2 className="wa-blast-section__title">Recipients</h2>
                  <p className="wa-blast-section__description">
                    {selectedTemplate
                      ? 'Paste CSV with a header row, or import a .csv file.'
                      : 'Paste numbers, or import a .csv/.txt file.'}
                  </p>
                </div>
              </div>
              <div className="wa-blast-form">
                {selectedTemplate ? (
                  <div className="wa-blast-form__field">
                    <label className="wa-blast-form__label" htmlFor="blast-template-recipients">
                      Recipients CSV — header: destination,{variableNames.join(',')}
                    </label>
                    <textarea
                      id="blast-template-recipients"
                      className={[
                        'wa-blast-form__textarea',
                        'wa-blast-form__recipients',
                        fieldErrors.recipients ? 'wa-blast-form__textarea--error' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      value={templateRecipientsText}
                      onChange={(e) => setTemplateRecipientsText(e.target.value)}
                      disabled={busy}
                      rows={6}
                      placeholder={`destination,${variableNames.join(',')}\n628123456789,${variableNames.map(() => '...').join(',')}`}
                    />
                    <div className="wa-blast-form__file-row">
                      <Button variant="secondary" type="button" onClick={() => templateFileInputRef.current?.click()} disabled={busy}>
                        <Upload size={16} strokeWidth={1.75} aria-hidden="true" />
                        Import .csv
                      </Button>
                      <input
                        ref={templateFileInputRef}
                        type="file"
                        accept=".csv,text/csv"
                        style={{ display: 'none' }}
                        onChange={handleTemplateFileChange}
                      />
                      <span
                        className={['wa-blast-form__preview', overCap ? 'wa-blast-form__preview--over-cap' : ''].filter(Boolean).join(' ')}
                      >
                        {templateParsed.recipients.length} unique recipient{templateParsed.recipients.length === 1 ? '' : 's'} parsed
                        {overCap ? ` — exceeds the ${MAX_RECIPIENTS_PER_CAMPAIGN} cap` : ''}
                      </span>
                    </div>
                    {fieldErrors.recipients ? <p className="wa-blast-form__error">{fieldErrors.recipients}</p> : null}
                    {templateParsed.recipients.length > 0 ? (
                      <div className="wa-blast-recipients__wrap">
                        <table className="wa-blast-recipients">
                          <thead>
                            <tr>
                              <th>Destination</th>
                              {variableNames.map((v) => (
                                <th key={v}>{v}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {templateParsed.recipients.map((r) => (
                              <tr key={r.destination}>
                                <td>{r.destination}</td>
                                {variableNames.map((v) => (
                                  <td key={v}>{r.variables[v] || '—'}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : null}
                  </div>
                ) : (
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
                        {freeformRecipients.length} unique recipient{freeformRecipients.length === 1 ? '' : 's'} parsed
                        {overCap ? ` — exceeds the ${MAX_RECIPIENTS_PER_CAMPAIGN} cap` : ''}
                      </span>
                    </div>
                    {fieldErrors.recipients ? <p className="wa-blast-form__error">{fieldErrors.recipients}</p> : null}
                    {freeformRecipients.length > 0 ? (
                      <pre className="wa-blast-form__preview-list">{freeformRecipients.join('\n')}</pre>
                    ) : null}
                  </div>
                )}
              </div>
            </Card>

            {submitError ? (
              <>
                <ErrorState error={submitError} />
                {validationDetails ? (
                  <div className="wa-blast-form__field">
                    <span className="wa-blast-form__label">Rows with missing or unexpected variables</span>
                    <ul className="wa-blast-form__preview-list">
                      {validationDetails.map((d) => (
                        <li key={d.index}>
                          #{d.index + 1} {d.destination}
                          {d.missing.length > 0 ? ` — missing: ${d.missing.join(', ')}` : ''}
                          {d.extra.length > 0 ? ` — unexpected: ${d.extra.join(', ')}` : ''}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </>
            ) : null}

            <div className="wa-blast-form__actions">
              <Button variant="primary" onClick={handleSubmit} disabled={busy}>
                <Send size={16} strokeWidth={1.75} aria-hidden="true" />
                {busy ? 'Creating…' : 'Create draft campaign'}
              </Button>
              <Button variant="ghost" onClick={() => navigate('/blast')} disabled={busy}>
                Cancel
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
