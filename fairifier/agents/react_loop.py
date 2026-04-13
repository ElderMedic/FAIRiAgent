"""Thin deepagents integration layer for agent-local ReAct loops."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from ..config import config
from ..models import FAIRifierState
from ..services.evidence_packets import build_evidence_context
from ..skills import format_skills_catalog_for_task, list_skill_virtual_paths

QWEN_MAX_TOKENS_LIMIT = 65536


class ReactLoopMixin:
    """Small bridge from FAIRifier agents to deepagents."""

    def _get_react_contract(self, agent_name: Optional[str] = None) -> Dict[str, Any]:
        """Return stop conditions and budgets for the current inner-loop agent."""
        name = (agent_name or getattr(self, "name", "")).lower()
        contract = {
            "max_iterations": config.react_loop_max_iterations,
            "max_tool_calls": config.react_loop_max_tool_calls,
            "success_criteria": ["Return a structured response accepted by the outer FAIRifier agent."],
            "fallback_criteria": [
                "If you are not making progress after repeated tool use, return the best structured answer you have."
            ],
        }
        if name == "documentparser":
            contract["success_criteria"] = [
                f"Extract at least {config.react_loop_document_parser_target_fields} meaningful metadata fields.",
                f"Produce enough grounding for at least {config.react_loop_document_parser_target_packets} evidence packets downstream.",
            ]
        elif name == "knowledgeretriever":
            contract["success_criteria"] = [
                f"Select around {config.react_loop_knowledge_retriever_target_packages} or fewer high-value FAIR-DS packages unless more are clearly required.",
                f"Identify up to {config.react_loop_knowledge_retriever_target_optional_fields} high-signal optional FAIR-DS fields total.",
            ]
        return contract

    def _get_deepagents_helpers(self):
        """Lazily import deepagents helpers so fallback mode remains available."""
        try:
            from deepagents import create_deep_agent
            from deepagents.backends.utils import create_file_data
        except Exception as exc:  # pragma: no cover - optional dependency
            self.logger.warning("deepagents unavailable, falling back: %s", exc)
            return None, None
        return create_deep_agent, create_file_data

    def _maybe_create_file_data(self, content: str):
        """Convert text content to a deepagents file payload when available."""
        _, create_file_data = self._get_deepagents_helpers()
        if create_file_data is None:
            return None
        return create_file_data(content)

    def _resolved_react_max_tokens(self) -> Optional[int]:
        """Normalize provider-specific max_tokens for deepagents model instances."""
        max_tokens = getattr(config, "llm_max_tokens", None)
        if max_tokens is None or max_tokens <= 0:
            return None
        if config.llm_provider == "qwen":
            return min(max_tokens, QWEN_MAX_TOKENS_LIMIT)
        return max_tokens

    def _get_react_model(self):
        """Return a deepagents-safe model instance for the current provider."""
        base_model = self.llm_helper.llm
        if config.llm_provider != "qwen":
            return base_model

        try:
            from langchain_openai import ChatOpenAI
        except Exception as exc:  # pragma: no cover - optional dependency
            self.logger.warning(
                "Unable to create Qwen deepagents model wrapper, using base model: %s",
                exc,
            )
            return base_model

        return ChatOpenAI(
            model=config.llm_model,
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            temperature=config.llm_temperature,
            max_tokens=self._resolved_react_max_tokens(),
            # DashScope Qwen rejects tool_choice=required/object when thinking mode
            # is active. deepagents uses tool calling heavily, so force it off here.
            extra_body={"enable_thinking": False},
        )

    def _build_react_agent(
        self,
        tools: List[Any],
        subagents: List[Dict[str, Any]],
        response_format: Type[BaseModel],
        system_prompt: str,
        *,
        memory_files: Optional[List[str]] = None,
    ):
        """Build a deep agent using the repository's configured LLM."""
        if not config.enable_deep_agents:
            return None

        create_deep_agent, _ = self._get_deepagents_helpers()
        if create_deep_agent is None:
            return None

        kwargs: Dict[str, Any] = {
            "model": self._get_react_model(),
            "tools": tools,
            "subagents": subagents,
            "response_format": response_format,
            "system_prompt": system_prompt,
        }

        if memory_files:
            kwargs["memory"] = memory_files

        # Only register the skills mount when at least one SKILL.md exists; otherwise
        # deepagents would expose an empty /skills tree and models may waste turns probing it.
        if list_skill_virtual_paths(*config.skill_roots):
            kwargs["skills"] = ["/skills"]

        return create_deep_agent(**kwargs)

    async def _invoke_react_agent(
        self,
        agent: Any,
        task_message: str,
        seed_files: Dict[str, Any],
        thread_id: str,
        state: FAIRifierState,
        scratchpad_name: Optional[str] = None,
    ) -> Optional[BaseModel]:
        """Invoke a deep agent and record lightweight telemetry."""
        if agent is None:
            return None

        try:
            contract = self._get_react_contract(scratchpad_name or getattr(self, "name", None))
            result = await agent.ainvoke(
                {
                    "messages": [{"role": "user", "content": task_message}],
                    "files": seed_files,
                },
                config={
                    "configurable": {"thread_id": thread_id},
                    "recursion_limit": max(50, contract["max_iterations"] * 20),
                },
            )
        except Exception as exc:  # pragma: no cover - network/model/runtime dependent
            self.logger.warning("Deep ReAct path failed, using fallback: %s", exc)
            return None

        self._record_react_result(
            state,
            scratchpad_name or getattr(self, "name", "unknown"),
            result,
        )
        return result.get("structured_response")

    def _record_react_result(
        self,
        state: FAIRifierState,
        agent_name: str,
        result: Dict[str, Any],
    ) -> None:
        """Persist minimal inner-loop telemetry for debugging and transparency."""
        scratchpad = state.setdefault("react_scratchpad", {}) or {}
        tools_called: List[str] = []
        for key in ("tool_calls", "tools_called"):
            raw = result.get(key, [])
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        name = item.get("name") or item.get("tool")
                        if name:
                            tools_called.append(str(name))
                    elif item:
                        tools_called.append(str(item))
        scratchpad[agent_name] = {
            "iterations": result.get("iterations") or result.get("step_count") or 0,
            "tools_called": list(dict.fromkeys(tools_called)),
            "budget": self._get_react_contract(agent_name),
        }
        state["react_scratchpad"] = scratchpad

    def _compose_task_message(self, state: FAIRifierState, base_task: str) -> str:
        """Merge planner, critic, and memory context into the first deepagents turn."""
        feedback = self.get_context_feedback(state)
        sections = [base_task.strip()]

        contract = self._get_react_contract()
        sections.append(
            "Inner-loop contract:\n"
            + f"- max_iterations: {contract['max_iterations']}\n"
            + f"- max_tool_calls: {contract['max_tool_calls']}\n"
            + "\n".join(f"- success: {item}" for item in contract["success_criteria"])
            + "\n"
            + "\n".join(f"- fallback: {item}" for item in contract["fallback_criteria"])
        )

        planner_instruction = feedback.get("planner_instruction")
        if planner_instruction:
            sections.append(f"Planner guidance:\n- {planner_instruction}")

        evidence_context = build_evidence_context(state.get("evidence_packets", []) or [])
        if evidence_context:
            sections.append(evidence_context)

        memories = self.format_retrieved_memories_for_prompt(
            feedback.get("retrieved_memories") or []
        )
        if memories:
            sections.append(memories)

        critic_feedback = feedback.get("critic_feedback")
        if critic_feedback:
            issues = critic_feedback.get("issues", [])
            suggestions = critic_feedback.get("suggestions", [])
            critique = critic_feedback.get("critique")
            critic_lines = ["Critic feedback from previous attempt:"]
            if critique:
                critic_lines.append(f"- critique: {critique}")
            for issue in issues:
                critic_lines.append(f"- issue: {issue}")
            for suggestion in suggestions:
                critic_lines.append(f"- suggestion: {suggestion}")
            sections.append("\n".join(critic_lines))

        history = feedback.get("guidance_history") or []
        if history:
            sections.append(
                "Guidance history:\n" + "\n".join(f"- {item}" for item in history)
            )

        previous_attempt = feedback.get("previous_attempt")
        if previous_attempt:
            sections.append(f"Previous attempt snapshot:\n{previous_attempt}")

        skill_paths = list_skill_virtual_paths(*config.skill_roots)
        if skill_paths:
            catalog = format_skills_catalog_for_task(*config.skill_roots)
            if catalog:
                sections.append(catalog)

        return "\n\n".join(section for section in sections if section)

    def _get_memory_files(self) -> List[str]:
        """Expose optional local memory files to deepagents when present."""
        memory_files: List[str] = []
        agents_file = Path(config.project_root) / "AGENTS.md"
        if agents_file.exists():
            memory_files.append("/AGENTS.md")
        return memory_files
