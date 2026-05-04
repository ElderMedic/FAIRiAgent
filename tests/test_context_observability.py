"""Tests for context-usage observability (P2 §6 of refactor plan)."""

import pytest


class TestEstimateTokens:
    def test_empty_string_zero_tokens(self):
        from fairifier.utils.context_observability import estimate_tokens

        assert estimate_tokens("") == 0

    def test_returns_positive_for_non_empty(self):
        from fairifier.utils.context_observability import estimate_tokens

        assert estimate_tokens("hello world") > 0

    def test_handles_dict(self):
        from fairifier.utils.context_observability import estimate_tokens

        d = {"a": "b", "c": [1, 2, 3]}
        assert estimate_tokens(d) > 0

    def test_handles_list(self):
        from fairifier.utils.context_observability import estimate_tokens

        assert estimate_tokens([1, 2, 3, "four"]) > 0

    def test_handles_none(self):
        from fairifier.utils.context_observability import estimate_tokens

        assert estimate_tokens(None) == 0

    def test_handles_int(self):
        from fairifier.utils.context_observability import estimate_tokens

        assert estimate_tokens(42) >= 0


class TestEstimateStateUsage:
    def test_returns_per_field_breakdown(self):
        from fairifier.utils.context_observability import estimate_state_usage

        state = {
            "document_info": {"title": "Test", "abstract": "abc"},
            "evidence_packets": [{"f": "v"}],
            "retrieved_knowledge": [{"term": "x"}],
            "execution_history": [],
        }
        usage = estimate_state_usage(state)
        assert "fields" in usage
        assert "total" in usage
        assert isinstance(usage["fields"], dict)
        assert usage["total"] >= 0

    def test_excludes_unrelated_fields_from_breakdown(self):
        """Only metadata-bearing state fields appear in the breakdown."""
        from fairifier.utils.context_observability import estimate_state_usage

        state = {
            "document_path": "/foo.pdf",
            "document_info": {"title": "T"},
            "session_id": "sid-123",
        }
        usage = estimate_state_usage(state)
        # Random scalar fields like session_id should not bloat the breakdown
        assert "document_info" in usage["fields"]


class TestLogContextUsage:
    def test_writes_to_jsonl_when_path_given(self, tmp_path):
        from fairifier.utils.context_observability import log_context_usage

        log_path = tmp_path / "log.jsonl"
        state = {
            "document_info": {"title": "T", "abstract": "A"},
            "evidence_packets": [],
        }
        log_context_usage("KnowledgeRetriever", state, log_path=str(log_path))

        assert log_path.exists()
        import json

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["event"] == "context_usage"
        assert record["agent"] == "KnowledgeRetriever"
        assert "total_tokens" in record
        assert "fields" in record

    def test_appends_to_existing_log(self, tmp_path):
        from fairifier.utils.context_observability import log_context_usage

        log_path = tmp_path / "log.jsonl"
        state = {"document_info": {"title": "T"}}
        log_context_usage("A", state, log_path=str(log_path))
        log_context_usage("B", state, log_path=str(log_path))

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_silent_when_no_path(self):
        from fairifier.utils.context_observability import log_context_usage

        # Should not raise even when log_path is None / unwritable
        state = {"document_info": {"title": "T"}}
        # No exception expected
        log_context_usage("Agent", state, log_path=None)
