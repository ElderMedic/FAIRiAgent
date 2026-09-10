"""Thin deepagents integration layer for agent-local ReAct loops."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel

from ..config import config
from ..models import FAIRifierState
from ..services.evidence_packets import build_evidence_context
from ..skills import format_skills_catalog_for_task, list_skill_virtual_paths

QWEN_MAX_TOKENS_LIMIT = 65536


class _DeepAgentHandle:
    """Wrap a deep agent when structured output is parsed manually."""

    def __init__(self, agent: Any, response_format: Type[BaseModel]):
        self.agent = agent
        self.response_format = response_format


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

    @staticmethod
    def _react_recursion_limit(contract: Dict[str, Any]) -> int:
        """Translate the advertised inner-loop budget into a real graph bound.

        Deepagents counts several graph transitions per reasoning/tool cycle,
        so the limit needs modest headroom.  It must nevertheless remain tied
        to the configured iteration and tool budgets; the former ``max(50,
        iterations * 20)`` allowed a six-iteration contract to run roughly a
        hundred graph steps.
        """
        iterations = max(int(contract.get("max_iterations") or 1), 1)
        tool_calls = max(int(contract.get("max_tool_calls") or 1), 1)
        return max(12, min(64, iterations * 4 + 4, tool_calls * 2 + 6))

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
        # K3 counts always-on reasoning in the same completion budget. A full
        # 131k budget on every inner tool turn is both expensive and prone to
        # long stalls; the outer extraction calls retain their configured cap.
        if "kimi-k3" in (config.llm_model or "").lower().replace("_", "-"):
            return min(max_tokens, 32768)
        return max_tokens

    def _get_react_model(self):
        """Return a deepagents-safe model instance for the current provider."""
        base_model = self.llm_helper.llm
        # Providers where thinking mode breaks deep agents tool calling:
        # - Qwen (DashScope): rejects tool_choice with thinking enabled
        # - DeepSeek: reasoning_content must be passed back across turns,
        #   which deepagents does not support
        # - Zhipu (GLM-4.5+): OpenAI-compatible endpoint with the same
        #   "thinking" extra_body contract and multi-turn reasoning_content
        #   propagation gap as DeepSeek
        # - OpenAI (official): function tools + reasoning_effort require the
        #   Responses API (/v1/responses), not Chat Completions
        if config.llm_provider == "openai":
            return self._get_openai_react_model(base_model)
        if config.llm_provider not in ("qwen", "deepseek", "zhipu"):
            return base_model

        try:
            from langchain_openai import ChatOpenAI
        except Exception as exc:  # pragma: no cover - optional dependency
            self.logger.warning(
                "Unable to create deepagents model wrapper, using base model: %s",
                exc,
            )
            return base_model

        # Deep agents use multi-turn tool calling which is incompatible
        # with thinking/reasoning modes. Disable per-provider:
        if config.llm_provider in ("deepseek", "zhipu"):
            extra_body = {"thinking": {"type": "disabled"}}
        else:
            extra_body = {"enable_thinking": False}

        return ChatOpenAI(
            model=config.llm_model,
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            temperature=config.llm_temperature,
            max_tokens=self._resolved_react_max_tokens(),
            extra_body=extra_body,
            timeout=180,
            max_retries=3,
        )

    def _get_openai_react_model(self, base_model: Any):
        """Ensure Deep ReAct OpenAI models can use tools with reasoning_effort."""
        from fairifier.utils.llm_helper import resolve_openai_use_responses_api

        base_url = config.llm_base_url
        if base_url == "http://localhost:11434":
            base_url = None
        effort = (config.llm_reasoning_effort or "").strip().lower() or None
        use_responses = resolve_openai_use_responses_api(
            base_url=base_url,
            model=config.llm_model,
            reasoning_effort=effort,
            explicit=getattr(config, "llm_use_responses_api", None),
        )
        if not use_responses:
            return base_model
        if getattr(base_model, "use_responses_api", None) is True:
            return base_model

        try:
            from langchain_openai import ChatOpenAI
        except Exception as exc:  # pragma: no cover - optional dependency
            self.logger.warning(
                "Unable to create OpenAI Responses deepagents model, "
                "using base model: %s",
                exc,
            )
            return base_model

        from fairifier.utils.llm_helper import _openai_omits_sampling_params

        kwargs: Dict[str, Any] = {
            "model": config.llm_model,
            "api_key": config.llm_api_key,
            "base_url": base_url,
            "max_tokens": self._resolved_react_max_tokens(),
            "timeout": 180,
            "max_retries": 3,
            "use_responses_api": True,
        }
        if not _openai_omits_sampling_params(config.llm_model):
            kwargs["temperature"] = config.llm_temperature
            if config.llm_top_p is not None:
                kwargs["top_p"] = config.llm_top_p
        if effort and effort != "none":
            kwargs["reasoning_effort"] = effort
        self.logger.info(
            "Deep ReAct OpenAI model using Responses API "
            "(reasoning_effort=%s)",
            effort or "provider-default",
        )
        return ChatOpenAI(**kwargs)

    def _openai_responses_manual_structured(self) -> bool:
        """OpenAI Responses rejects many optional-field JSON Schemas as text.format.

        Prefer tools+reasoning via Responses, then parse the final JSON message
        into the expected Pydantic model instead of binding response_format.
        """
        if config.llm_provider != "openai":
            return False
        from fairifier.utils.llm_helper import resolve_openai_use_responses_api

        base_url = config.llm_base_url
        if base_url == "http://localhost:11434":
            base_url = None
        effort = (config.llm_reasoning_effort or "").strip().lower() or None
        return resolve_openai_use_responses_api(
            base_url=base_url,
            model=config.llm_model,
            reasoning_effort=effort,
            explicit=getattr(config, "llm_use_responses_api", None),
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

        manual_structured = self._openai_responses_manual_structured()
        prompt = system_prompt
        if manual_structured:
            try:
                import json

                schema_hint = json.dumps(
                    response_format.model_json_schema(), indent=2
                )
            except Exception:
                schema_hint = response_format.__name__
            prompt = (
                f"{system_prompt}\n\n"
                "After tool use, finish with a single JSON object that matches this "
                "schema (no markdown fences, no commentary):\n"
                f"{schema_hint}"
            )

        kwargs: Dict[str, Any] = {
            "model": self._get_react_model(),
            "tools": tools,
            "subagents": subagents,
            "system_prompt": prompt,
        }
        if not manual_structured:
            kwargs["response_format"] = response_format

        if memory_files:
            kwargs["memory"] = memory_files

        # Only register the skills mount when at least one SKILL.md exists; otherwise
        # deepagents would expose an empty /skills tree and models may waste turns probing it.
        if list_skill_virtual_paths(*config.skill_roots):
            kwargs["skills"] = ["/skills"]

        agent = create_deep_agent(**kwargs)
        if manual_structured:
            return _DeepAgentHandle(agent, response_format=response_format)
        return agent

    def _parse_structured_from_result(
        self,
        result: Dict[str, Any],
        response_format: Type[BaseModel],
    ) -> Optional[BaseModel]:
        """Parse a Pydantic payload from deep-agent messages when response_format is unbound."""
        import json
        from fairifier.utils.llm_helper import (
            normalize_llm_response_content,
            _extract_json_from_markdown,
        )

        structured = result.get("structured_response")
        if isinstance(structured, response_format):
            return structured
        if isinstance(structured, BaseModel):
            try:
                return response_format.model_validate(structured.model_dump())
            except Exception:
                pass

        messages = list(result.get("messages") or [])
        for message in reversed(messages):
            content = normalize_llm_response_content(
                getattr(message, "content", None)
                if not isinstance(message, dict)
                else message.get("content")
            )
            if not content:
                continue
            try:
                payload = json.loads(_extract_json_from_markdown(content))
            except Exception:
                continue
            if isinstance(payload, dict):
                try:
                    return response_format.model_validate(payload)
                except Exception:
                    continue
        return None

    async def _invoke_react_agent(
        self,
        agent: Any,
        task_message: str,
        seed_files: Dict[str, Any],
        thread_id: str,
        state: FAIRifierState,
        scratchpad_name: Optional[str] = None,
        *,
        timeout_seconds: int = 900,
    ) -> Optional[BaseModel]:
        """Invoke a deep agent with a hard timeout (default 900s = 15 min).

        A stuck deep-agent LLM call can block the entire pipeline for
        the outer timeout duration (up to 2 h).  The inner timeout here
        catches those stalls early so the deterministic fallback can
        take over instead.
        """
        if agent is None:
            return None

        if isinstance(agent, _DeepAgentHandle):
            response_format = agent.response_format
            runnable = agent.agent
        else:
            response_format = None
            runnable = agent

        try:
            contract = self._get_react_contract(scratchpad_name or getattr(self, "name", None))
            operation_prefix = scratchpad_name or getattr(self, "name", "react")
            run_config = {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": self._react_recursion_limit(contract),
            }
            callbacks = list(
                (self.llm_helper._build_run_config() or {}).get("callbacks", [])
            )
            callbacks.append(
                self.llm_helper.build_usage_callback(operation_prefix)
            )
            run_config["callbacks"] = callbacks
            result = await asyncio.wait_for(
                runnable.ainvoke(
                    {
                        "messages": [{"role": "user", "content": task_message}],
                        "files": seed_files,
                    },
                    config=run_config,
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            self.logger.warning(
                "Deep ReAct agent timed out after %ds — using deterministic fallback",
                timeout_seconds,
            )
            return None
        except Exception as exc:  # pragma: no cover - network/model/runtime dependent
            self.logger.warning("Deep ReAct path failed, using fallback: %s", exc)
            return None

        self._record_react_result(
            state,
            scratchpad_name or getattr(self, "name", "unknown"),
            result,
        )
        structured = result.get("structured_response")
        if structured is None and response_format is not None:
            structured = self._parse_structured_from_result(result, response_format)
            if structured is None:
                self.logger.warning(
                    "Deep ReAct finished without parseable %s JSON — using fallback",
                    getattr(response_format, "__name__", "structured_response"),
                )
                return None
        return structured

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

        # Critic feedback view is already echo-chamber-isolated in
        # base.get_context_feedback (refactor §2): no `critique` prose, no
        # `previous_attempt` snapshot. Only structured issues + suggestions.
        critic_feedback = feedback.get("critic_feedback")
        if critic_feedback:
            issues = critic_feedback.get("issues", [])
            suggestions = critic_feedback.get("suggestions", [])
            critic_lines = ["Critic feedback from previous attempt:"]
            for issue in issues:
                critic_lines.append(f"- issue: {issue}")
            for suggestion in suggestions:
                critic_lines.append(f"- suggestion: {suggestion}")
            retry_contract = critic_feedback.get("retry_contract") or {}
            for item in retry_contract.get("must_change", [])[:10]:
                critic_lines.append(f"- must_change: {item}")
            for item in retry_contract.get("must_not_repeat", [])[:10]:
                critic_lines.append(f"- must_not_repeat: {item}")
            for item in retry_contract.get("verification", [])[:5]:
                critic_lines.append(f"- verification: {item}")
            if len(critic_lines) > 1:  # at least one issue or suggestion
                sections.append("\n".join(critic_lines))

        history = feedback.get("guidance_history") or []
        if history:
            sections.append(
                "Guidance history:\n" + "\n".join(f"- {item}" for item in history)
            )

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
