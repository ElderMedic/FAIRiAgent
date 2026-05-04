"""Tests for DocumentInfo canonicalization (P0 §1 of architecture refactor)."""

from fairifier.utils.doc_info_canonical import canonicalize_doc_info


class TestTitleCanonicalization:
    def test_passes_through_canonical_title(self):
        result = canonicalize_doc_info({"title": "My Paper"})
        assert result["title"] == "My Paper"

    def test_maps_investigation_title(self):
        assert canonicalize_doc_info({"investigation_title": "X"})["title"] == "X"

    def test_maps_project_title(self):
        assert canonicalize_doc_info({"project_title": "Y"})["title"] == "Y"

    def test_maps_study_title(self):
        assert canonicalize_doc_info({"study_title": "Z"})["title"] == "Z"

    def test_maps_document_title(self):
        assert canonicalize_doc_info({"document_title": "D"})["title"] == "D"

    def test_canonical_title_wins_over_alias(self):
        result = canonicalize_doc_info({"title": "A", "investigation_title": "B"})
        assert result["title"] == "A"

    def test_extracts_title_from_nested_metadata_for_fair_principles(self):
        result = canonicalize_doc_info(
            {"metadata_for_fair_principles": {"title": "Nested Title"}}
        )
        assert result["title"] == "Nested Title"


class TestAbstractCanonicalization:
    def test_passes_through_canonical_abstract(self):
        assert canonicalize_doc_info({"abstract": "abc"})["abstract"] == "abc"

    def test_maps_summary(self):
        assert canonicalize_doc_info({"summary": "s"})["abstract"] == "s"

    def test_maps_description(self):
        assert canonicalize_doc_info({"description": "d"})["abstract"] == "d"

    def test_maps_investigation_description(self):
        assert (
            canonicalize_doc_info({"investigation_description": "x"})["abstract"]
            == "x"
        )


class TestAuthorsCanonicalization:
    def test_passes_through_authors(self):
        assert canonicalize_doc_info({"authors": ["A", "B"]})["authors"] == ["A", "B"]

    def test_maps_investigators(self):
        assert canonicalize_doc_info({"investigators": ["A"]})["authors"] == ["A"]

    def test_maps_personnel(self):
        assert canonicalize_doc_info({"personnel": ["P"]})["authors"] == ["P"]

    def test_string_author_wrapped_in_list(self):
        assert canonicalize_doc_info({"authors": "Solo Author"})["authors"] == [
            "Solo Author"
        ]

    def test_filters_empty_authors(self):
        assert canonicalize_doc_info({"authors": ["A", "", None, "B"]})["authors"] == [
            "A",
            "B",
        ]


class TestKeywordsCanonicalization:
    def test_passes_through_keywords(self):
        assert canonicalize_doc_info({"keywords": ["k1"]})["keywords"] == ["k1"]

    def test_maps_tags(self):
        assert canonicalize_doc_info({"tags": ["t"]})["keywords"] == ["t"]

    def test_maps_topics(self):
        assert canonicalize_doc_info({"topics": ["t1", "t2"]})["keywords"] == [
            "t1",
            "t2",
        ]


class TestResearchDomainCanonicalization:
    def test_passes_through_research_domain(self):
        assert canonicalize_doc_info({"research_domain": "Genomics"})[
            "research_domain"
        ] == "Genomics"

    def test_maps_domain(self):
        assert canonicalize_doc_info({"domain": "X"})["research_domain"] == "X"

    def test_maps_field_of_study(self):
        assert canonicalize_doc_info({"field_of_study": "Y"})["research_domain"] == "Y"

    def test_collapses_dict_scientific_domain_with_primary(self):
        result = canonicalize_doc_info(
            {
                "scientific_domain": {
                    "primary_field": "Microbiology",
                    "subfields": ["soil", "rhizosphere"],
                }
            }
        )
        assert "Microbiology" in result["research_domain"]
        assert "soil" in result["research_domain"]

    def test_handles_string_scientific_domain(self):
        assert canonicalize_doc_info({"scientific_domain": "Genetics"})[
            "research_domain"
        ] == "Genetics"


class TestStructurePreservation:
    def test_preserves_unknown_canonical_fields(self):
        """DOIs, instruments, etc. — fields already canonical pass through."""
        input_doc = {
            "doi": "10.1234/abc",
            "instruments": ["sequencer"],
            "datasets_mentioned": ["dataset1"],
        }
        result = canonicalize_doc_info(input_doc)
        assert result["doi"] == "10.1234/abc"
        assert result["instruments"] == ["sequencer"]
        assert result["datasets_mentioned"] == ["dataset1"]

    def test_drops_unknown_aliases_silently(self):
        """Unknown fields that aren't in the alias map are dropped (not preserved)."""
        result = canonicalize_doc_info({"random_garbage_field": "x"})
        assert "random_garbage_field" not in result

    def test_empty_input(self):
        assert canonicalize_doc_info({}) == {}

    def test_none_input(self):
        assert canonicalize_doc_info(None) == {}

    def test_unwraps_nested_metadata_wrapper(self):
        """LLMs sometimes wrap output in {'metadata': {...}}."""
        result = canonicalize_doc_info(
            {"metadata": {"title": "T", "abstract": "A"}}
        )
        assert result["title"] == "T"
        assert result["abstract"] == "A"


class TestSchemaLockdown:
    """Test that the Pydantic DocumentInfoResponse schema is locked down."""

    def test_response_model_does_not_allow_extra(self):
        from fairifier.agents.response_models import DocumentInfoResponse

        # extra='ignore' is what we want — silently drop unknowns
        # 'allow' would let unknown fields through, which is what we are fixing
        config = DocumentInfoResponse.model_config
        extra = config.get("extra")
        assert extra in (
            "ignore",
            "forbid",
        ), f"DocumentInfoResponse should reject unknown fields, got extra={extra!r}"

    def test_response_model_drops_alias_fields(self):
        """When the LLM returns aliases like 'summary', the model ignores them.
        Canonicalization happens upstream of this validation."""
        from fairifier.agents.response_models import DocumentInfoResponse

        instance = DocumentInfoResponse(
            title="T",
            summary="this should be silently ignored or normalized upstream",
        )
        dumped = instance.model_dump(exclude_none=True)
        assert dumped.get("title") == "T"
        # 'summary' is not a canonical field — must not appear in output
        assert "summary" not in dumped
