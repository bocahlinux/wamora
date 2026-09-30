// Mirrors backend/apps/blast/templating.py's `extract_variable_names`
// regex exactly (`\{\{\s*(\w+)\s*\}\}`) — used ONLY for the "detected
// variables" live preview while typing a template's content
// (BlastTemplatesPanel.tsx). The server always recomputes this itself
// from the saved `content` (BlastTemplateSerializer's `variable_names`
// field) and is the sole source of truth for what a template actually
// requires — this is a UX convenience, never trusted for validation.

const VARIABLE_PATTERN = /\{\{\s*(\w+)\s*\}\}/g;

export function extractVariableNames(content: string): string[] {
  const names = new Set<string>();
  for (const match of content.matchAll(VARIABLE_PATTERN)) {
    names.add(match[1]);
  }
  return Array.from(names).sort();
}
