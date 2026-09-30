import { useState } from 'react';
import { FileText, Plus } from 'lucide-react';

import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorState } from '../components/ui/ErrorState';
import { Input } from '../components/ui/Input';
import { LoadingState } from '../components/ui/LoadingState';
import { Modal } from '../components/ui/Modal';
import type { ApiError } from '../lib/api';
import {
  createBlastTemplate,
  getBlastTemplates,
  updateBlastTemplate,
  type BlastTemplate,
  type OfficeChoice,
} from '../lib/djangoApi';
import { extractVariableNames } from '../lib/blastTemplateVariables';
import { useApiQuery } from '../lib/useApiQuery';
import '../pages/SettingsPage.css';

// Discussed requirement — Blast Templates. `variable_names` is always
// SERVER-derived (apps.blast.templating.extract_variable_names) — the
// live "detected variables" preview below mirrors that exact regex
// client-side (lib/blastTemplateVariables.ts, deliberately kept identical
// to the backend's own) purely for instant typing feedback; the actual
// value saved and validated against is always the server's own
// recomputation from `content`, never this client-side guess.
export function BlastTemplatesPanel({
  hasGlobalAccess,
  officeChoices,
}: {
  hasGlobalAccess: boolean;
  officeChoices: OfficeChoice[];
}) {
  const templatesQuery = useApiQuery(() => getBlastTemplates(), []);
  const [modalTemplate, setModalTemplate] = useState<BlastTemplate | 'new' | null>(null);

  return (
    <Card>
      <div className="wa-settings-panel__header">
        <span className="wa-settings-panel__title">Templates</span>
        <Button variant="primary" onClick={() => setModalTemplate('new')}>
          <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
          New template
        </Button>
      </div>

      {templatesQuery.status === 'loading' ? (
        <LoadingState label="Loading templates…" />
      ) : templatesQuery.status === 'error' ? (
        <ErrorState error={templatesQuery.error} onRetry={templatesQuery.refetch} />
      ) : templatesQuery.data.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No templates yet"
          description="Create a template with {{variables}} to reuse for personalized Blast campaigns."
        />
      ) : (
        <div className="wa-settings-table-wrap">
          <table className="wa-settings-table wa-settings-table--responsive">
            <thead>
              <tr>
                <th>Name</th>
                <th>Key</th>
                <th>Variables</th>
                <th>Office</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {templatesQuery.data.map((template) => (
                <tr key={template.id}>
                  <td data-label="Name">{template.name}</td>
                  <td data-label="Key">{template.key}</td>
                  <td data-label="Variables">
                    {template.variable_names.length === 0
                      ? '—'
                      : template.variable_names.map((v) => (
                          <Badge key={v} tone="info">
                            {`{{${v}}}`}
                          </Badge>
                        ))}
                  </td>
                  <td data-label="Office">
                    {officeChoices.find((o) => o.id === template.office)?.name ?? (template.office ? '—' : 'Global (shared)')}
                  </td>
                  <td data-label="Status">
                    <Badge tone={template.is_active ? 'success' : 'neutral'}>{template.is_active ? 'Active' : 'Inactive'}</Badge>
                  </td>
                  <td data-label="">
                    <Button variant="ghost" onClick={() => setModalTemplate(template)}>
                      Edit
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <TemplateFormModal
        template={modalTemplate}
        hasGlobalAccess={hasGlobalAccess}
        officeChoices={officeChoices}
        onClose={() => setModalTemplate(null)}
        onSaved={() => {
          setModalTemplate(null);
          templatesQuery.refetch();
        }}
      />
    </Card>
  );
}

function TemplateFormModal({
  template,
  hasGlobalAccess,
  officeChoices,
  onClose,
  onSaved,
}: {
  template: BlastTemplate | 'new' | null;
  hasGlobalAccess: boolean;
  officeChoices: OfficeChoice[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const openKey = template === null ? 'closed' : template === 'new' ? 'new' : template.id;
  const title = template === 'new' ? 'New template' : template ? `Edit ${template.name}` : '';
  return (
    <Modal open={template !== null} onClose={onClose} title={title}>
      <TemplateForm key={openKey} template={template} hasGlobalAccess={hasGlobalAccess} officeChoices={officeChoices} onClose={onClose} onSaved={onSaved} />
    </Modal>
  );
}

function TemplateForm({
  template,
  hasGlobalAccess,
  officeChoices,
  onClose,
  onSaved,
}: {
  template: BlastTemplate | 'new' | null;
  hasGlobalAccess: boolean;
  officeChoices: OfficeChoice[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = template === 'new';
  const editing = template !== null && template !== 'new' ? template : null;

  const [key, setKey] = useState(editing?.key ?? '');
  const [name, setName] = useState(editing?.name ?? '');
  const [content, setContent] = useState(editing?.content ?? '');
  const [officeId, setOfficeId] = useState<number | ''>(editing?.office ?? '');
  const [isActive, setIsActive] = useState(editing?.is_active ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const detectedVariables = extractVariableNames(content);

  async function handleSubmit() {
    if (busy || !key.trim() || !name.trim() || !content.trim()) return;
    setBusy(true);
    setError(null);
    const result = isNew
      ? await createBlastTemplate({
          key: key.trim(),
          name: name.trim(),
          content,
          ...(hasGlobalAccess ? { office: officeId === '' ? null : officeId } : {}),
        })
      : await updateBlastTemplate(editing!.id, { name: name.trim(), content, is_active: isActive });
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onSaved();
  }

  return (
    <div className="wa-settings-form">
      <Input
        label="Key (stable — used by the external API, never editable after creation)"
        value={key}
        onChange={(e) => setKey(e.target.value)}
        disabled={busy || !isNew}
      />
      <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} disabled={busy} />

      {hasGlobalAccess && isNew ? (
        <label className="wa-settings-checkbox-row" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 'var(--space-2)' }}>
          <span>Office (leave unset for a shared/global template every Office can use)</span>
          <select
            className="wa-blast-form__select"
            value={officeId}
            onChange={(e) => setOfficeId(e.target.value ? Number(e.target.value) : '')}
            disabled={busy}
          >
            <option value="">Global (shared)</option>
            {officeChoices.map((office) => (
              <option key={office.id} value={office.id}>
                {office.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <div className="wa-blast-form__field">
        <label className="wa-blast-form__label" htmlFor="template-content">
          Content — use <code>{'{{variable_name}}'}</code> for per-recipient values
        </label>
        <textarea
          id="template-content"
          className="wa-blast-form__textarea"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          disabled={busy}
          rows={6}
        />
        <div className="wa-blast-form__file-row">
          {detectedVariables.length === 0 ? (
            <span className="wa-blast-form__hint">No variables detected yet.</span>
          ) : (
            detectedVariables.map((v) => (
              <Badge key={v} tone="info">
                {`{{${v}}}`}
              </Badge>
            ))
          )}
        </div>
      </div>

      {!isNew ? (
        <label className="wa-settings-checkbox-row">
          <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} disabled={busy} />
          <span>Active (an inactive template cannot be picked for a new Blast campaign)</span>
        </label>
      ) : null}

      {error ? <ErrorState error={error} /> : null}
      <div className="wa-settings-form__actions">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant="primary" onClick={handleSubmit} disabled={busy || !key.trim() || !name.trim() || !content.trim()}>
          {busy ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  );
}
