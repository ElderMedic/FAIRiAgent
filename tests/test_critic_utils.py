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
