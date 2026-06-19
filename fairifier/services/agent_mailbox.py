"""In-process Agent-to-Agent mailbox for structured inter-agent handoff.

Provides typed, auditable message passing between FAIRiAgent agents without
introducing HTTP or external protocols. Messages are appended to the shared
``FAIRifierState["agent_messages"]`` list (append-only log) and can be
filtered by recipient and type.

Usage inside an agent's ``execute()``:

    from fairifier.services.agent_mailbox import AgentMailbox

    mailbox = AgentMailbox(state)
    # Read messages addressed to this agent
    gap_reports = mailbox.inbox("JSONGenerator", types=["field_gap_report"])
    # Publish a message
    mailbox.publish_field_gap_report(
        from_agent="KnowledgeRetriever",
        gaps=[{"field": "enzyme type", "isa_sheet": "sample", ...}],
    )
    # Acknowledge a message
    mailbox.ack(gap_reports[0]["id"], "JSONGenerator")
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Sequence

from ..models import AgentMessage, AgentMessageType

logger = logging.getLogger(__name__)


def _ensure_message_list(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "agent_messages" not in state or state["agent_messages"] is None:
        state["agent_messages"] = []
    return state["agent_messages"]


def _new_id() -> str:
    return f"msg-{uuid.uuid4().hex[:12]}"


class AgentMailbox:
    """Lightweight mailbox backed by ``state["agent_messages"]``."""

    def __init__(self, state: Dict[str, Any]):
        self._state = state
        self._messages = _ensure_message_list(state)

    def inbox(
        self,
        agent_name: str,
        *,
        types: Optional[Sequence[str]] = None,
        unacked_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return messages addressed to *agent_name* (or broadcast ``"*"``).

        Args:
            agent_name: The receiving agent's name.
            types: Optional filter on ``message_type``.
            unacked_only: If True, exclude already-acked messages.
        """
        results: List[Dict[str, Any]] = []
        for msg in self._messages:
            target = msg.get("to_agent", "")
            if target not in (agent_name, "*"):
                continue
            if types and msg.get("message_type") not in types:
                continue
            if unacked_only and agent_name in (msg.get("acked_by") or []):
                continue
            results.append(msg)
        return results

    def publish(self, message: AgentMessage) -> Dict[str, Any]:
        """Append a message to the state log and return its dict form."""
        msg_dict = message.to_dict()
        self._messages.append(msg_dict)
        logger.info(
            "📨 A2A %s → %s [%s] id=%s",
            message.from_agent,
            message.to_agent,
            message.message_type,
            message.id,
        )
        return msg_dict

    def ack(self, message_id: str, agent_name: str) -> bool:
        """Mark a message as acked. Returns True if found."""
        for msg in self._messages:
            if msg.get("id") == message_id:
                acked = msg.setdefault("acked_by", [])
                if agent_name not in acked:
                    acked.append(agent_name)
                return True
        return False

    def publish_evidence_bundle(
        self,
        *,
        from_agent: str,
        to_agent: str = "*",
        packets: List[Dict[str, Any]],
        source_path: Optional[str] = None,
        source_type: str = "document",
    ) -> Dict[str, Any]:
        """Convenience: publish an EvidenceBundle message."""
        msg = AgentMessage(
            id=_new_id(),
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=AgentMessageType.EVIDENCE_BUNDLE.value,
            payload={
                "packet_count": len(packets),
                "packets": packets[:30],
                "source_type": source_type,
            },
            refs={"source_path": source_path or ""},
            priority=1,
        )
        return self.publish(msg)

    def publish_field_gap_report(
        self,
        *,
        from_agent: str,
        to_agent: str = "JSONGenerator",
        gaps: List[Dict[str, Any]],
        selected_packages: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Convenience: publish a FieldGapReport with structured gap entries.

        Each gap entry should contain at minimum:
            {"field": "...", "isa_sheet": "...", "reason": "..."}
        Optionally: ``package_source``, ``entity_id``, ``suggestion``.
        """
        msg = AgentMessage(
            id=_new_id(),
            from_agent=from_agent,
            to_agent=to_agent,
            message_type=AgentMessageType.FIELD_GAP_REPORT.value,
            payload={
                "gap_count": len(gaps),
                "gaps": gaps[:50],
                "selected_packages": selected_packages or [],
            },
            priority=2,
        )
        return self.publish(msg)

    @staticmethod
    def handoff_summary(state: Dict[str, Any]) -> Dict[str, Any]:
        """Compute summary stats for processing_log / eval."""
        messages = state.get("agent_messages") or []
        by_type: Dict[str, int] = {}
        acked = 0
        total = len(messages)
        for msg in messages:
            mt = msg.get("message_type", "unknown")
            by_type[mt] = by_type.get(mt, 0) + 1
            if msg.get("acked_by"):
                acked += 1
        return {
            "total_messages": total,
            "by_type": by_type,
            "acked": acked,
            "unacked": total - acked,
        }
