"""Frontmatter parser.

VERBATIM lift of mahavishnu/scripts/regenerate_plan_index.py:200-230
(`extract_frontmatter` — line-anchored, no regex truncation bug).
Validates against the schema in oneiric/schemas/document-frontmatter-v1.md;
the parser itself doesn't enforce the schema (caller does), it just
returns the parsed YAML mapping or None for malformed input.
"""
from __future__ import annotations
from typing import Any

_FRONTMATTER_OPEN = "---"


def extract_frontmatter(text: str, yaml_module: Any) -> dict[str, Any] | None:
    """Return the parsed YAML mapping from `text`, or None for malformed."""
    if not text:
        return None
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != _FRONTMATTER_OPEN:
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == _FRONTMATTER_OPEN:
            raw = "\n".join(lines[1:i])
            try:
                parsed = yaml_module.safe_load(raw)
            except yaml_module.YAMLError:
                return None
            if parsed is None:
                return {}
            return parsed if isinstance(parsed, dict) else None
    return None  # no closing fence
