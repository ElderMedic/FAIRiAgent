"""Regression tests for the canonical source-grounding regex patterns.

Both ``fairifier.agents.json_generator`` and
``fairifier.validation.metadata_json_format`` use the shared constants
imported here.  This test proves the *deployed* pattern (not a copy) matches
all known evidence citation formats that appeared in real production runs.
"""

from __future__ import annotations

# Import the canonical constants so this test covers the same pattern
# that is actually used at runtime.
from fairifier.utils.grounding import SOURCE_REF_PATTERN, SOURCE_TABLE_PATTERN


# ---------------------------------------------------------------------------
# Positive cases: real LLM evidence strings that MUST be recognised
# ---------------------------------------------------------------------------

POSITIVE_CASES = [
    "source_001: title section",
    "source_001: abstract section",
    "source_001: Methods section describes soil mesocosm setup",
    "source_001: Results section highlights differential gene expression",
    "source_001: Discussion paragraph 2",
    "source_001: Conclusion states the main findings",
    "source_001: author affiliations section",
    "source_001: intro paragraph",
    "source_001:250-310 main.md: Sampling site: Wadden Sea tidal flats",
    "source_002: investigation sheet row 1",
    "source_002 table row 1, column 'orcid'",
    "source_002 table column 'investigation identifier' row 1",
    "source_002: table file name",
    "source_002 table row 1, column 'orcid' for Henk van Lingen",
]

# ---------------------------------------------------------------------------
# Negative cases: vague or non-grounded strings that MUST NOT be recognised
# ---------------------------------------------------------------------------

NEGATIVE_CASES = [
    "source_002: no sample IDs in preview",
    "source_001: biosafety not mentioned",
    "source_001: taxonomy not mentioned",
    "source_002: no evidence of assay extension",
    "missing source reference",
    "The methods section states...",   # no source_NNN prefix
]

# ---------------------------------------------------------------------------
# Table-specific cases for SOURCE_TABLE_PATTERN
# ---------------------------------------------------------------------------

TABLE_POSITIVE_CASES = [
    "source_002 table row 1, column 'orcid'",
    "source_002: investigation sheet row 1",
    "source_002 table column 'investigation identifier' row 1",
    "source_002: table file name",
]

TABLE_NEGATIVE_CASES = [
    "source_001: title section",
    "source_001: abstract section",
    "source_001: Methods section describes mesocosm",
]


def test_positive_source_grounding_matches():
    """Canonical SOURCE_REF_PATTERN recognises all known valid evidence strings."""
    for case in POSITIVE_CASES:
        assert SOURCE_REF_PATTERN.search(case) is not None, (
            f"Expected SOURCE_REF_PATTERN to match, but it did not: {case!r}"
        )


def test_negative_source_grounding_matches():
    """Canonical SOURCE_REF_PATTERN does not over-match vague non-citations."""
    for case in NEGATIVE_CASES:
        assert SOURCE_REF_PATTERN.search(case) is None, (
            f"SOURCE_REF_PATTERN unexpectedly matched negative case: {case!r}"
        )


def test_table_pattern_matches():
    """SOURCE_TABLE_PATTERN recognises table/sheet/column citations."""
    for case in TABLE_POSITIVE_CASES:
        assert SOURCE_TABLE_PATTERN.search(case) is not None, (
            f"Expected SOURCE_TABLE_PATTERN to match, but it did not: {case!r}"
        )


def test_table_pattern_does_not_over_match():
    """SOURCE_TABLE_PATTERN does not trigger on non-table text citations."""
    for case in TABLE_NEGATIVE_CASES:
        assert SOURCE_TABLE_PATTERN.search(case) is None, (
            f"SOURCE_TABLE_PATTERN unexpectedly matched: {case!r}"
        )
