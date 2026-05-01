"""Shared source-grounding regex constants.

A single module that defines the canonical patterns for identifying
source-backed evidence strings in FAIR-DS metadata fields.

Both ``fairifier.agents.json_generator`` and
``fairifier.validation.metadata_json_format`` import from here, so all three
sites stay in sync automatically.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Canonical source-reference pattern
# ---------------------------------------------------------------------------
# Matches any evidence string that contains a source citation of the form:
#   source_001: title section
#   source_001: abstract section
#   source_001:250-310 main.md: ...
#   source_002: investigation sheet row 1
#   source_002 table row 1, column 'orcid'
#   source_002 table column 'investigation identifier' row 1
# Does NOT match vague non-citations like:
#   source_002: no sample IDs in preview
#   source_001: biosafety not mentioned
SOURCE_REF_PATTERN = re.compile(
    r"source_\d+(?:\s*[:,-]?\s*.{0,100}?(?:"
    r"row|line|table|section|column|\d+-\d+|sheet|abstract|title|method|"
    r"intro|result|discuss|conclu))",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Table-backed sub-pattern
# ---------------------------------------------------------------------------
# Narrower variant that specifically recognises tabular provenance:
#   source_002 table row 1, column 'orcid'
#   source_002: investigation sheet row 1
SOURCE_TABLE_PATTERN = re.compile(
    r"source_\d+(?:\s*[:,-]?\s*.{0,50}?(?:table|sheet|column))",
    re.IGNORECASE,
)
