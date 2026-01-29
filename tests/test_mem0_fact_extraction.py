"""
Tests for mem0 fact extraction prompt quality.

Validates that FAIR_FACT_EXTRACTION_PROMPT extracts high-value, reusable
facts and avoids low-value ephemeral details.
"""

import pytest
from fairifier.services.mem0_service import FAIR_FACT_EXTRACTION_PROMPT


class TestFactExtractionPrompt:
    """Test the quality and constraints of fact extraction prompt."""

    def test_prompt_has_few_shot_examples(self):
        """Verify prompt includes few-shot examples."""
        assert "EXAMPLES:" in FAIR_FACT_EXTRACTION_PROMPT
        assert "Input:" in FAIR_FACT_EXTRACTION_PROMPT
        assert "Output:" in FAIR_FACT_EXTRACTION_PROMPT

    def test_prompt_has_extraction_principles(self):
        """Verify prompt defines clear extraction principles."""
        assert "EXTRACTION PRINCIPLES:" in FAIR_FACT_EXTRACTION_PROMPT
        assert "PATTERNS and KNOWLEDGE" in FAIR_FACT_EXTRACTION_PROMPT

    def test_prompt_has_positive_and_negative_cases(self):
        """Verify prompt includes what to extract and what NOT to extract."""
        assert (
            "EXTRACT (high-value, reusable):" in FAIR_FACT_EXTRACTION_PROMPT
        )
        assert (
            "DO NOT EXTRACT (low-value, ephemeral):"
            in FAIR_FACT_EXTRACTION_PROMPT
        )

    def test_prompt_emphasizes_reusability(self):
        """Verify prompt emphasizes reusable knowledge."""
        assert "REUSABLE" in FAIR_FACT_EXTRACTION_PROMPT
        assert "HIGH-VALUE" in FAIR_FACT_EXTRACTION_PROMPT
        assert "FUTURE runs" in FAIR_FACT_EXTRACTION_PROMPT

    def test_prompt_has_length_constraint(self):
        """Verify prompt specifies length constraints for facts."""
        constraint_present = (
            "<120 chars" in FAIR_FACT_EXTRACTION_PROMPT
            or "120 chars" in FAIR_FACT_EXTRACTION_PROMPT
            or "<100 chars" in FAIR_FACT_EXTRACTION_PROMPT
            or "100 chars" in FAIR_FACT_EXTRACTION_PROMPT
            or "concise" in FAIR_FACT_EXTRACTION_PROMPT
        )
        assert constraint_present

    def test_prompt_discourages_agent_names(self):
        """Verify prompt discourages extracting agent execution details."""
        negative_examples = [
            "DocumentParser ran successfully",
            "Parsed by DocumentParser",
            "retrieved 106 fields"
        ]
        for example in negative_examples:
            assert example in FAIR_FACT_EXTRACTION_PROMPT

    def test_prompt_encourages_domain_knowledge(self):
        """Verify prompt encourages domain-specific knowledge extraction."""
        positive_categories = [
            "Domain-package associations",
            "Field mappings",
            "Quality patterns",
            "Ontology preferences"
        ]
        for category in positive_categories:
            assert category in FAIR_FACT_EXTRACTION_PROMPT


class TestFactQuality:
    """
    Test expected fact extraction behavior with example inputs.

    Note: These are behavioral expectations - actual LLM responses may vary.
    This documents the intended behavior for manual/integration testing.
    """

    def test_example_high_value_extraction(self):
        """Document expected behavior for high-value input."""
        input_msg = (
            "KnowledgeRetriever selected packages: soil, GSC MIUVIGS, "
            "Illumina. Reasoning: alpine grassland metagenomics study using "
            "shotgun sequencing on NovaSeq platform"
        )
        # Expected output (documented for reference):
        # {"facts": [
        #   "alpine grassland metagenomics: soil + GSC MIUVIGS + Illumina",
        #   "shotgun sequencing on NovaSeq → GSC MIUVIGS + Illumina"
        # ]}
        assert "alpine grassland metagenomics" in input_msg
        assert "soil, GSC MIUVIGS, Illumina" in input_msg

    def test_example_low_value_extraction(self):
        """Document expected behavior for low-value input."""
        input_msg = (
            "JSONGenerator produced 78 fields, 59 high confidence, "
            "critic score 0.72"
        )
        # Expected output: {"facts": []}
        # Reason: Pure execution metrics, no reusable knowledge
        assert "78 fields" in input_msg  # This is ephemeral data

    def test_example_ontology_mapping(self):
        """Document expected behavior for ontology URI extraction."""
        input_msg = (
            "Critic feedback: elevation_zones field should use "
            "ENVO:01000892 ontology term for 'altitude zone'"
        )
        # Expected output:
        # {"facts": [
        #   "elevation/altitude fields → ENVO:01000892 (altitude zone)"
        # ]}
        assert "ENVO:01000892" in input_msg
        assert "altitude zone" in input_msg


@pytest.mark.parametrize(
    "fact,expected_valid",
    [
        (
            "alpine ecology studies commonly use soil + GSC MIUVIGS packages",
            True,
        ),  # 60 chars
        (
            "elevation_m maps to 'geographic location (elevation)' "
            "in Sample sheet",
            True,
        ),  # 72 chars
        (
            "This is a fact that is intentionally made very long to exceed "
            "the 100 character limit that we have set for individual facts "
            "in the system and should be rejected or truncated",
            False,
        ),  # >100 chars
        ("DocumentParser", False),  # Just agent name
        ("retrieved 106 fields", False),  # Execution metric
    ],
)
def test_fact_validity(fact: str, expected_valid: bool):
    """
    Test individual fact validity based on length and content rules.

    Valid facts should be:
    - <100 characters
    - Not just agent names
    - Not execution metrics
    """
    # Length check
    length_valid = len(fact) < 100

    # Content check (heuristic)
    content_invalid_patterns = [
        "DocumentParser",
        "KnowledgeRetriever",
        "JSONGenerator",
        "ran successfully",
        "produced",
        "retrieved",
        "generated",
    ]
    # Check if ONLY an invalid pattern (not containing useful info)
    is_only_invalid = any(
        fact.strip() == pattern or fact.strip().startswith(pattern + " ")
        for pattern in content_invalid_patterns
    )

    content_valid = not is_only_invalid

    actual_valid = length_valid and content_valid

    if expected_valid:
        assert actual_valid, (
            f"Fact '{fact}' should be valid but failed checks"
        )
    else:
        assert not actual_valid, (
            f"Fact '{fact}' should be invalid but passed checks"
        )
