"""Tests for execution_history record compaction (P0 §2.5 of refactor plan)."""

from fairifier.utils.execution_history import compact_execution_record


def _full_record():
    return {
        "agent_name": "JSONGenerator",
        "attempt": 2,
        "start_time": "2026-05-04T10:00:00",
        "end_time": "2026-05-04T10:00:30",
        "success": True,
        "critic_evaluation": {
            "decision": "RETRY",
            "score": 0.62,
            "critique": (
                "Output is partially correct. The investigation sheet is missing a "
                "title field and several mandatory sample fields are blank. The model "
                "has incorrectly inferred the assay type as 'metabolomics' when the "
                "evidence clearly indicates 'genomics'. Also, ..."
                * 5  # simulate verbose prose
            ),
            "issues": [
                "Missing investigation_title",
                "Missing sample.organism",
                "Missing sample.collection_date",
                "Wrong assay_type inference",
                "Confidence score too low for several fields",
            ],
            "improvement_ops": [
                "Re-extract investigation_title from doc_info",
                "Use evidence_packets for sample.organism",
            ],
            "suggestions": [
                "Try again with focus on sample sheet completeness",
            ],
        },
    }


class TestCompactionPreservesRequiredFields:
    def test_keeps_agent_name(self):
        assert compact_execution_record(_full_record())["agent_name"] == "JSONGenerator"

    def test_keeps_attempt(self):
        assert compact_execution_record(_full_record())["attempt"] == 2

    def test_keeps_start_and_end_time(self):
        compact = compact_execution_record(_full_record())
        assert compact["start_time"] == "2026-05-04T10:00:00"
        assert compact["end_time"] == "2026-05-04T10:00:30"

    def test_keeps_success_flag(self):
        assert compact_execution_record(_full_record())["success"] is True

    def test_preserves_error_field_when_present(self):
        record = _full_record()
        record["error"] = "Timeout"
        assert compact_execution_record(record)["error"] == "Timeout"


class TestCriticEvaluationCompaction:
    def test_keeps_score(self):
        compact = compact_execution_record(_full_record())
        assert compact["critic_evaluation"]["score"] == 0.62

    def test_keeps_decision(self):
        compact = compact_execution_record(_full_record())
        assert compact["critic_evaluation"]["decision"] == "RETRY"

    def test_drops_prose_critique(self):
        compact = compact_execution_record(_full_record())
        assert "critique" not in compact["critic_evaluation"]

    def test_replaces_full_issues_with_count(self):
        compact = compact_execution_record(_full_record())
        # Full issues list (verbose) should be dropped
        assert "issues" not in compact["critic_evaluation"]
        # An issues_count summary should remain
        assert compact["critic_evaluation"]["issues_count"] == 5

    def test_drops_full_improvement_ops_text(self):
        compact = compact_execution_record(_full_record())
        # The full ops list (with prose) is dropped
        assert "improvement_ops" not in compact["critic_evaluation"]

    def test_drops_full_suggestions_text(self):
        compact = compact_execution_record(_full_record())
        assert "suggestions" not in compact["critic_evaluation"]


class TestCompactionEdgeCases:
    def test_record_without_critic_evaluation(self):
        record = {
            "agent_name": "DocumentParser",
            "attempt": 1,
            "start_time": "2026-05-04T10:00:00",
            "end_time": "2026-05-04T10:00:05",
            "success": True,
        }
        # Should not raise; critic_evaluation absent -> stays absent or None
        compact = compact_execution_record(record)
        assert compact["agent_name"] == "DocumentParser"
        # critic_evaluation may be None or missing; both acceptable
        assert compact.get("critic_evaluation") in (None, {}, {"score": None})

    def test_record_with_none_critic_evaluation(self):
        record = _full_record()
        record["critic_evaluation"] = None
        compact = compact_execution_record(record)
        assert compact["agent_name"] == "JSONGenerator"

    def test_compaction_reduces_size(self):
        import json

        full = _full_record()
        full_size = len(json.dumps(full))
        compact_size = len(json.dumps(compact_execution_record(full)))
        # The compact form should be substantially smaller (verbose prose dropped).
        assert compact_size < full_size / 3, (
            f"Expected compact size < {full_size / 3:.0f}, got {compact_size}"
        )


class TestDownstreamConsumerCompatibility:
    def test_confidence_aggregator_pattern_still_works(self):
        """confidence_aggregator reads record['critic_evaluation']['score'].
        Compact records must still expose this field."""
        compact = compact_execution_record(_full_record())
        assert compact["critic_evaluation"].get("score") == 0.62

    def test_report_timeline_pattern_still_works(self):
        """report_generator's timeline uses agent_name, attempt, start/end_time, success."""
        compact = compact_execution_record(_full_record())
        for key in ("agent_name", "attempt", "start_time", "end_time", "success"):
            assert key in compact, f"Compact record missing required field: {key}"
