"""`{{variable}}` placeholder handling for `BlastTemplate.content`.

Single source of truth for what a template's variables are — both
`apps.blast.serializers`' recipient validation and the external API's
recipient validation call `extract_variable_names` directly rather than
each keeping their own copy of the regex, so the two can never drift
apart from each other.
"""

import re

_VARIABLE_PATTERN = re.compile(r'\{\{\s*(\w+)\s*\}\}')


def extract_variable_names(content: str) -> set[str]:
    return set(_VARIABLE_PATTERN.findall(content))


def render_template(content: str, variables: dict) -> str:
    """Substitutes every `{{name}}` in `content` with `variables[name]`
    (stringified). Called only at dispatch/send time
    (`apps.blast.tasks.dispatch_blast_recipient_task`) — never at
    campaign-creation time, so `BlastCampaign.message_template` always
    stays the literal template, placeholders and all."""

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        return str(variables.get(name, match.group(0)))

    return _VARIABLE_PATTERN.sub(_replace, content)
