"""Prompt template renderer.

Substitutes ``{UPPER_CASE}`` placeholders in prompt ``.md`` files with the
values supplied in the ``substitutions`` dict. Same convention the validated
test harness (``chorus-test-harness``) uses, so existing tuned prompts drop in
unchanged.

Unfilled placeholders are an error: leaving ``{CAST_JSON}`` in a rendered
prompt would send Claude a literal brace string and waste a round trip.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping

PROMPTS_DIR = Path(__file__).parent / "prompts"

_PLACEHOLDER_RE = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")


class PromptError(RuntimeError):
    """Raised on render failures (missing file, unfilled placeholder, etc.)."""


def placeholders_in(text: str) -> set[str]:
    """Return every ``{UPPER_CASE}`` placeholder referenced in ``text``."""
    return set(_PLACEHOLDER_RE.findall(text))


def load_prompt(name_or_path: str | Path, substitutions: Mapping[str, str]) -> str:
    """Render a prompt file with the given substitutions.

    Parameters
    ----------
    name_or_path
        Either a bare filename (resolved against ``backend/nlp/prompts/``) or a
        full path.
    substitutions
        Mapping of ``UPPER_CASE`` placeholder names (no braces) to string
        values. Every placeholder present in the prompt must have a mapping.

    Raises
    ------
    PromptError
        If the file can't be read or any placeholder is unfilled.
    """
    path = Path(name_or_path)
    if not path.is_absolute() and not path.exists():
        path = PROMPTS_DIR / path.name
    if not path.exists():
        raise PromptError(f"prompt file not found: {path}")

    try:
        template = path.read_text(encoding="utf-8")
    except OSError as e:
        raise PromptError(f"failed to read prompt {path}: {e}") from e

    needed = placeholders_in(template)
    provided = {k for k, v in substitutions.items() if v is not None}
    missing = needed - provided
    if missing:
        raise PromptError(
            f"prompt {path.name} references placeholders not provided: "
            f"{sorted(missing)}"
        )

    # Do the substitution with a single regex pass so string values containing
    # ``{FOO}``-style substrings (JSON, chapter text, etc.) don't get
    # recursively expanded.
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in substitutions:
            # Leave it alone — not in the "needed" set doesn't happen here
            # because we checked above, but defensively returning the match
            # avoids silent corruption if a caller lies about placeholders.
            return match.group(0)
        return str(substitutions[key])

    return _PLACEHOLDER_RE.sub(_replace, template)
