"""Unit tests for Critic agent utility functions."""

from fairifier.agents.critic import safe_json_parse
from fairifier.utils.llm_helper import normalize_llm_response_content


class TestSafeJsonParse:
    """Test safe JSON parsing with various formats."""

    def test_safe_json_parse_handles_code_fence(self):
        """Test parsing JSON wrapped in markdown code fences."""
        payload = """```json
    {
      "score": 0.82,
      "decision": "accept",
      "issues": [],
      "improvement_ops": []
    }
    ```"""
        parsed = safe_json_parse(payload)
        assert parsed is not None
        assert parsed["score"] == 0.82
        assert parsed["decision"] == "accept"
        assert parsed["issues"] == []
        assert parsed["improvement_ops"] == []

    def test_safe_json_parse_handles_generic_code_fence(self):
        """Test parsing JSON wrapped in generic code fences."""
        payload = """```
    {
      "score": 0.75,
      "decision": "retry"
    }
    ```"""
        parsed = safe_json_parse(payload)
        assert parsed is not None
        assert parsed["score"] == 0.75
        assert parsed["decision"] == "retry"

    def test_safe_json_parse_handles_plain_json(self):
        """Test parsing plain JSON without code fences."""
        payload = '{"score": 0.9, "decision": "accept"}'
        parsed = safe_json_parse(payload)
        assert parsed is not None
        assert parsed["score"] == 0.9
        assert parsed["decision"] == "accept"

    def test_safe_json_parse_handles_json_with_extra_text(self):
        """Test parsing JSON when there's extra text before/after."""
        payload = """Some text before
    {
      "score": 0.8,
      "decision": "accept"
    }
    Some text after"""
        parsed = safe_json_parse(payload)
        assert parsed is not None
        assert parsed["score"] == 0.8
        assert parsed["decision"] == "accept"

    def test_safe_json_parse_handles_empty_string(self):
        """Test parsing empty string returns None."""
        assert safe_json_parse("") is None
        assert safe_json_parse("   ") is None

    def test_safe_json_parse_handles_invalid_json(self):
        """Test parsing invalid JSON returns None."""
        assert safe_json_parse("not json at all") is None
        assert safe_json_parse("{ invalid json }") is None
        assert safe_json_parse('{"incomplete":') is None

    def test_safe_json_parse_handles_nested_objects(self):
        """Test parsing JSON with nested objects."""
        payload = """```json
    {
      "score": 0.85,
      "decision": "accept",
      "details": {
        "issues": ["minor"],
        "confidence": 0.9
      }
    }
    ```"""
        parsed = safe_json_parse(payload)
        assert parsed is not None
        assert parsed["score"] == 0.85
        assert isinstance(parsed["details"], dict)
        assert parsed["details"]["issues"] == ["minor"]
        assert parsed["details"]["confidence"] == 0.9

    def test_safe_json_parse_handles_isa_style_matrix_fence(self):
        """Nested ISA matrix JSON must not truncate at first inner brace (regex bug)."""
        payload = """```json
{
  "investigation": {"columns": ["a"], "rows": [{"a": "1"}]},
  "study": {"columns": ["b", "c"], "rows": [{"b": "x", "c": "y"}]},
  "assay": {"columns": [], "rows": []},
  "sample": {"columns": ["s"], "rows": [{"s": "z"}]},
  "observationunit": {"columns": [], "rows": []}
}
```"""
        parsed = safe_json_parse(payload)
        assert parsed is not None
        assert parsed["study"]["rows"][0]["c"] == "y"
        assert len(parsed["investigation"]["columns"]) == 1

    def test_safe_json_parse_handles_anthropic_content_blocks(self):
        """Anthropic-style content lists should normalize before JSON parsing."""
        payload = [
            {"type": "text", "text": "```json\n{\"score\": 0.88, \"issues\": []}\n```"},
        ]
        parsed = safe_json_parse(payload)
        assert parsed is not None
        assert parsed["score"] == 0.88
        assert parsed["issues"] == []


def test_normalize_llm_response_content_handles_block_list():
    """Normalize list-based LLM outputs into plain text."""
    payload = [
        {"type": "text", "text": "hello"},
        {"type": "thinking", "text": ""},
        {"type": "text", "text": "world"},
    ]
    assert normalize_llm_response_content(payload) == "hello\nworld"


class TestBuildIsaMapperContext:
    """Test _build_isa_mapper_context row counting and content."""

    def _make_state(self, isa_values_json):
        import json
        return {
            "artifacts": {"isa_values_json": json.dumps(isa_values_json)},
            "metadata_fields": [],
            "retrieved_knowledge": [],
        }

    def test_counts_rows_from_columns_rows_structure(self):
        """Fixed: nested {columns, rows} structure must count rows correctly."""
        from fairifier.agents.critic import CriticAgent
        import json
        agent = CriticAgent.__new__(CriticAgent)
        isa = {
            "investigation": {"columns": ["col1"], "rows": [["val1"]]},
            "study": {"columns": ["col2"], "rows": [["v1"], ["v2"]]},
            "assay": {"columns": [], "rows": []},
        }
        state = self._make_state(isa)
        ctx = json.loads(agent._build_isa_mapper_context(state))
        assert ctx["total_rows"] == 3

    def test_counts_rows_from_flat_list_structure(self):
        """Legacy flat-list structure still counted correctly."""
        from fairifier.agents.critic import CriticAgent
        import json
        agent = CriticAgent.__new__(CriticAgent)
        isa = {
            "investigation": [{"field": "val"}],
            "study": [{"a": 1}, {"b": 2}],
        }
        state = self._make_state(isa)
        ctx = json.loads(agent._build_isa_mapper_context(state))
        assert ctx["total_rows"] == 3

    def test_sheets_populated_includes_all_keys(self):
        from fairifier.agents.critic import CriticAgent
        import json
        agent = CriticAgent.__new__(CriticAgent)
        isa = {
            "investigation": {"columns": [], "rows": []},
            "sample": {"columns": [], "rows": [["r1"]]},
            "assay": {"columns": [], "rows": []},
        }
        state = self._make_state(isa)
        ctx = json.loads(agent._build_isa_mapper_context(state))
        assert set(ctx["sheets_populated"]) == {"investigation", "sample", "assay"}

    def test_sheet_summaries_included_for_columns_rows_structure(self):
        from fairifier.agents.critic import CriticAgent
        import json
        agent = CriticAgent.__new__(CriticAgent)
        isa = {
            "investigation": {"columns": ["title", "desc"], "rows": [["My Study", "Desc"]]},
        }
        state = self._make_state(isa)
        ctx = json.loads(agent._build_isa_mapper_context(state))
        assert "sheet_summaries" in ctx
        assert ctx["sheet_summaries"]["investigation"]["row_count"] == 1
        assert "title" in ctx["sheet_summaries"]["investigation"]["columns"]

    def test_empty_isa_values_returns_zero_rows(self):
        from fairifier.agents.critic import CriticAgent
        import json
        agent = CriticAgent.__new__(CriticAgent)
        state = {"artifacts": {}, "metadata_fields": [], "retrieved_knowledge": []}
        ctx = json.loads(agent._build_isa_mapper_context(state))
        assert ctx["total_rows"] == 0
        assert ctx["sheets_populated"] == []


class TestBuildBioMetadataContext:
    """Critic must receive structured BioMetadata signals (not 'No context available')."""

    @staticmethod
    def _bare_critic():
        from fairifier.agents.critic import CriticAgent

        agent = CriticAgent.__new__(CriticAgent)
        agent.max_retries_per_step = 3
        return agent

    def test_context_includes_bio_packets_tools_and_contract(self):
        import json

        agent = self._bare_critic()
        state = {
            "context": {"retry_count": 0},
            "bio_file_paths": ["/data/run1.bam"],
            "agent_guidance": {"BioMetadataAgent": "Use samtools stats"},
            "react_scratchpad": {
                "BioMetadataAgent": {
                    "iterations": 5,
                    "tools_called": [
                        "run_biocontainer_tool",
                        "search_biocontainer_tags",
                    ],
                },
            },
            "confidence_scores": {"bio_metadata": 0.95},
            "evidence_packets": [
                {
                    "field_candidate": "total_reads",
                    "value": "1000",
                    "evidence_text": "samtools stats output ...",
                    "section": "bio_tool::run1.bam",
                    "source_type": "bioinformatics_tool_output",
                    "provenance": {"agent": "BioMetadataAgent"},
                },
                {
                    "field_candidate": "title",
                    "provenance": {"agent": "DocumentParser"},
                },
            ],
            "source_workspace": {"source_paths": {"bio_run1_bam": "/tmp/out.txt"}},
            "document_info": {"title": "T", "research_domain": "genomics"},
        }
        ctx = json.loads(agent._build_bio_metadata_context(state))
        assert "samtools" in ctx["bio_metadata_contract"]
        assert ctx["attempt"] == "1/3"
        assert ctx["planner_guidance"] == "Use samtools stats"
        assert ctx["input_files"][0].endswith("run1.bam")
        assert ctx["reported_bio_metadata_confidence"] == 0.95
        assert ctx["bio_evidence_packets"]["count"] == 1
        assert ctx["bio_evidence_packets"]["samples"][0]["field_candidate"] == "total_reads"
        assert "run_biocontainer_tool" in ctx["inner_loop_telemetry"]["tools_called"]
        assert "bio_run1_bam" in ctx["bio_source_workspace_entries"]

    def test_bio_metadata_evidence_packets_filtered_by_agent(self):
        from fairifier.agents.critic import CriticAgent

        agent = CriticAgent.__new__(CriticAgent)
        state = {
            "evidence_packets": [
                {"provenance": {"agent": "BioMetadataAgent"}, "field_candidate": "a"},
                {"provenance": {"agent": "DocumentParser"}, "field_candidate": "b"},
            ]
        }
        bio = agent._bio_metadata_evidence_packets(state)
        assert len(bio) == 1
        assert bio[0]["field_candidate"] == "a"
