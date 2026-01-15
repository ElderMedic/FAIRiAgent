"""Unit tests for Critic agent utility functions."""

from fairifier.agents.critic import safe_json_parse


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

