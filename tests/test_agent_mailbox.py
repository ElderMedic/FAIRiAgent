"""Tests for the Agent-to-Agent (A2A) mailbox and AgentMessage model."""

from fairifier.models import AgentMessage, AgentMessageType
from fairifier.services.agent_mailbox import AgentMailbox


def _empty_state():
    return {"agent_messages": []}


class TestAgentMessage:
    """AgentMessage dataclass serialization."""

    def test_round_trip(self):
        msg = AgentMessage(
            id="msg-test1",
            from_agent="DocParser",
            to_agent="JSONGen",
            message_type=AgentMessageType.EVIDENCE_BUNDLE.value,
            payload={"packet_count": 3},
            refs={"source_path": "/tmp/doc.pdf"},
        )
        d = msg.to_dict()
        assert d["id"] == "msg-test1"
        assert d["from_agent"] == "DocParser"
        assert d["message_type"] == "evidence_bundle"

        restored = AgentMessage.from_dict(d)
        assert restored.id == msg.id
        assert restored.payload == msg.payload
        assert restored.to_agent == msg.to_agent

    def test_defaults(self):
        msg = AgentMessage(
            id="m1",
            from_agent="A",
            to_agent="B",
            message_type="ack",
        )
        assert msg.priority == 0
        assert msg.acked_by == []
        assert msg.payload == {}

    def test_message_types_enum(self):
        assert AgentMessageType.FIELD_GAP_REPORT.value == "field_gap_report"
        assert AgentMessageType.EVIDENCE_BUNDLE.value == "evidence_bundle"
        assert AgentMessageType.ACK.value == "ack"


class TestAgentMailbox:
    """AgentMailbox publish / inbox / ack tests."""

    def test_publish_appends_to_state(self):
        state = _empty_state()
        mailbox = AgentMailbox(state)
        msg = AgentMessage(
            id="msg-01",
            from_agent="A",
            to_agent="B",
            message_type="evidence_bundle",
        )
        mailbox.publish(msg)
        assert len(state["agent_messages"]) == 1
        assert state["agent_messages"][0]["id"] == "msg-01"

    def test_inbox_filters_by_agent(self):
        state = _empty_state()
        mailbox = AgentMailbox(state)
        mailbox.publish(AgentMessage(
            id="m1", from_agent="A",
            to_agent="B", message_type="x",
        ))
        mailbox.publish(AgentMessage(
            id="m2", from_agent="A",
            to_agent="C", message_type="x",
        ))

        inbox_b = mailbox.inbox("B")
        assert len(inbox_b) == 1
        assert inbox_b[0]["id"] == "m1"

    def test_inbox_includes_broadcast(self):
        state = _empty_state()
        mailbox = AgentMailbox(state)
        mailbox.publish(AgentMessage(
            id="m1", from_agent="A",
            to_agent="*", message_type="y",
        ))
        mailbox.publish(AgentMessage(
            id="m2", from_agent="A",
            to_agent="B", message_type="y",
        ))

        inbox_c = mailbox.inbox("C")
        assert len(inbox_c) == 1
        assert inbox_c[0]["id"] == "m1"

    def test_inbox_filters_by_type(self):
        state = _empty_state()
        mailbox = AgentMailbox(state)
        mailbox.publish(AgentMessage(
            id="m1", from_agent="A",
            to_agent="B", message_type="field_gap_report",
        ))
        mailbox.publish(AgentMessage(
            id="m2", from_agent="A",
            to_agent="B", message_type="evidence_bundle",
        ))

        gaps = mailbox.inbox("B", types=["field_gap_report"])
        assert len(gaps) == 1
        assert gaps[0]["message_type"] == "field_gap_report"

    def test_ack_marks_message(self):
        state = _empty_state()
        mailbox = AgentMailbox(state)
        mailbox.publish(AgentMessage(
            id="m1", from_agent="A",
            to_agent="B", message_type="x",
        ))

        assert mailbox.ack("m1", "B") is True
        assert "B" in state["agent_messages"][0]["acked_by"]

    def test_ack_idempotent(self):
        state = _empty_state()
        mailbox = AgentMailbox(state)
        mailbox.publish(AgentMessage(
            id="m1", from_agent="A",
            to_agent="B", message_type="x",
        ))

        mailbox.ack("m1", "B")
        mailbox.ack("m1", "B")
        acked = state["agent_messages"][0]["acked_by"]
        assert acked.count("B") == 1

    def test_ack_nonexistent_returns_false(self):
        state = _empty_state()
        mailbox = AgentMailbox(state)
        assert mailbox.ack("no-such-id", "B") is False

    def test_unacked_only_filter(self):
        state = _empty_state()
        mailbox = AgentMailbox(state)
        mailbox.publish(AgentMessage(
            id="m1", from_agent="A",
            to_agent="B", message_type="x",
        ))
        mailbox.publish(AgentMessage(
            id="m2", from_agent="A",
            to_agent="B", message_type="x",
        ))

        mailbox.ack("m1", "B")
        unacked = mailbox.inbox("B", unacked_only=True)
        assert len(unacked) == 1
        assert unacked[0]["id"] == "m2"


class TestConveniencePublishers:
    """Test publish_evidence_bundle and publish_field_gap_report helpers."""

    def test_publish_evidence_bundle(self):
        state = _empty_state()
        mailbox = AgentMailbox(state)
        result = mailbox.publish_evidence_bundle(
            from_agent="DocumentParser",
            packets=[{"packet_id": "ep-001", "value": "test"}],
            source_path="/tmp/doc.pdf",
            source_type="pdf",
        )
        assert result["message_type"] == "evidence_bundle"
        assert result["from_agent"] == "DocumentParser"
        assert result["to_agent"] == "*"
        assert result["payload"]["packet_count"] == 1
        assert len(result["payload"]["packets"]) == 1
        assert result["refs"]["source_path"] == "/tmp/doc.pdf"

    def test_publish_field_gap_report(self):
        state = _empty_state()
        mailbox = AgentMailbox(state)
        gaps = [
            {"field": "enzyme type",
             "isa_sheet": "sample", "reason": "n/a"},
            {"field": "organism",
             "isa_sheet": "study", "reason": "no match"},
        ]
        result = mailbox.publish_field_gap_report(
            from_agent="KnowledgeRetriever",
            gaps=gaps,
            selected_packages=["Genome"],
        )
        assert result["message_type"] == "field_gap_report"
        assert result["to_agent"] == "JSONGenerator"
        assert result["payload"]["gap_count"] == 2
        assert result["payload"]["selected_packages"] == ["Genome"]

    def test_field_gap_report_caps_at_50(self):
        state = _empty_state()
        mailbox = AgentMailbox(state)
        many_gaps = [{"field": f"f{i}", "reason": "x"} for i in range(80)]
        result = mailbox.publish_field_gap_report(
            from_agent="KR",
            gaps=many_gaps,
        )
        assert len(result["payload"]["gaps"]) == 50


class TestHandoffSummary:
    """Test AgentMailbox.handoff_summary static method."""

    def test_empty_state(self):
        summary = AgentMailbox.handoff_summary({})
        assert summary["total_messages"] == 0
        assert summary["by_type"] == {}

    def test_counts_types_and_acks(self):
        state = {
            "agent_messages": [
                {"message_type": "evidence_bundle", "acked_by": ["JSONGen"]},
                {"message_type": "field_gap_report", "acked_by": []},
                {"message_type": "evidence_bundle", "acked_by": ["ISAMapper"]},
            ]
        }
        summary = AgentMailbox.handoff_summary(state)
        assert summary["total_messages"] == 3
        assert summary["by_type"]["evidence_bundle"] == 2
        assert summary["by_type"]["field_gap_report"] == 1
        assert summary["acked"] == 2
        assert summary["unacked"] == 1


class TestStateInitialization:
    """Verify agent_messages is initialized correctly."""

    def test_ensure_message_list_creates_key(self):
        state: dict = {}
        AgentMailbox(state)
        assert "agent_messages" in state
        assert state["agent_messages"] == []

    def test_ensure_message_list_preserves_existing(self):
        existing = [{"id": "old", "message_type": "x"}]
        state = {"agent_messages": existing}
        AgentMailbox(state)
        assert len(state["agent_messages"]) == 1
