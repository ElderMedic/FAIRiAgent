"""Tests for deepagents integration helpers."""

from unittest.mock import Mock

from fairifier.config import config
from fairifier.agents.base import BaseAgent
from fairifier.agents.react_loop import ReactLoopMixin
from fairifier.skills import (
    build_skills_catalog_markdown,
    list_skill_virtual_paths,
    load_skill_files,
)


class DummyReactAgent(ReactLoopMixin, BaseAgent):
    """Minimal concrete agent for testing mixin helpers."""

    async def execute(self, state):
        return state


def test_compose_task_message_includes_planner_critic_and_memory():
    agent = DummyReactAgent("Dummy")
    state = {
        "context": {
            "critic_feedback": {
                "critique": "missing identifiers",
                "issues": ["project id absent"],
                "suggestions": ["extract identifiers explicitly"],
                "history": [],
            },
            "retrieved_memories": [{"memory": "proposal documents usually include grant ids"}],
            "critic_guidance_history": {"Dummy": ["previous retry asked for provenance"]},
        },
        "agent_guidance": {"Dummy": "prioritize identifiers"},
        "evidence_packets": [
            {
                "field_candidate": "methodology",
                "value": "RNA-seq",
                "evidence_text": "Methods section",
                "section": "Methods",
            }
        ],
    }

    message = agent._compose_task_message(state, "Base task")

    assert "Base task" in message
    assert "prioritize identifiers" in message
    assert "missing identifiers" in message
    assert "extract identifiers explicitly" in message
    assert "grant ids" in message
    assert "previous retry asked for provenance" in message
    assert "Evidence packets:" in message
    assert "max_iterations" in message


def test_record_react_result_updates_state_scratchpad():
    agent = DummyReactAgent("Dummy")
    state = {}

    agent._record_react_result(
        state,
        "Dummy",
        {
            "iterations": 3,
            "tool_calls": [{"name": "search_ontology_term"}, {"tool": "resolve_doi_metadata"}],
        },
    )

    assert state["react_scratchpad"]["Dummy"]["iterations"] == 3
    assert state["react_scratchpad"]["Dummy"]["tools_called"] == [
        "search_ontology_term",
        "resolve_doi_metadata",
    ]
    assert state["react_scratchpad"]["Dummy"]["budget"]["max_iterations"] > 0


def test_get_context_feedback_prefers_agent_scoped_critic_feedback():
    agent = DummyReactAgent("Dummy")
    state = {
        "context": {
            "critic_feedback": {
                "target_agent": "KnowledgeRetriever",
                "critique": "feedback for another agent",
            },
            "critic_feedback_by_agent": {
                "Dummy": {
                    "target_agent": "Dummy",
                    "critique": "dummy-specific feedback",
                    "issues": ["missing identifier"],
                    "suggestions": ["extract identifier"],
                }
            },
        },
        "agent_guidance": {},
    }

    feedback = agent.get_context_feedback(state)

    assert feedback["critic_feedback"]["critique"] == "dummy-specific feedback"
    assert feedback["critic_feedback"]["target_agent"] == "Dummy"


def test_get_react_model_wraps_qwen_with_thinking_disabled(monkeypatch):
    agent = DummyReactAgent("Dummy")
    agent.llm_helper = Mock(llm="base-llm")

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChatOpenAI)
    monkeypatch.setattr(config, "llm_provider", "qwen")
    monkeypatch.setattr(config, "llm_model", "qwen-flash")
    monkeypatch.setattr(config, "llm_api_key", "test-key")
    monkeypatch.setattr(
        config,
        "llm_base_url",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setattr(config, "llm_temperature", 0.2)
    monkeypatch.setattr(config, "llm_max_tokens", 100000)

    model = agent._get_react_model()

    assert isinstance(model, FakeChatOpenAI)
    assert captured["model"] == "qwen-flash"
    assert captured["extra_body"] == {"enable_thinking": False}
    assert captured["max_tokens"] == 65536


def test_get_react_model_keeps_existing_non_qwen_model(monkeypatch):
    agent = DummyReactAgent("Dummy")
    agent.llm_helper = Mock(llm="base-llm")

    monkeypatch.setattr(config, "llm_provider", "ollama")

    assert agent._get_react_model() == "base-llm"


def test_list_skill_virtual_paths_finds_repo_skills():
    paths = list_skill_virtual_paths(config.skills_dir)
    assert paths
    assert any("domain/genomics/SKILL.md" in p for p in paths)


def test_compose_task_message_lists_skill_paths():
    agent = DummyReactAgent("Dummy")
    state = {"context": {}, "agent_guidance": {}, "evidence_packets": []}
    msg = agent._compose_task_message(state, "Parse the document")
    assert "/skills/domain/" in msg
    assert "/workspace/skills_catalog.md" in msg
    assert "genomics-metadata" in msg or "genomics" in msg


def test_list_skill_virtual_paths_later_root_wins(tmp_path):
    r1 = tmp_path / "r1"
    r2 = tmp_path / "r2"
    (r1 / "dup" / "SKILL.md").parent.mkdir(parents=True)
    (r1 / "dup" / "SKILL.md").write_text("A", encoding="utf-8")
    (r2 / "dup" / "SKILL.md").parent.mkdir(parents=True)
    (r2 / "dup" / "SKILL.md").write_text("B", encoding="utf-8")
    assert list_skill_virtual_paths(r1, r2) == ["/skills/dup/SKILL.md"]


def test_build_skills_catalog_includes_yaml_name():
    cat = build_skills_catalog_markdown(config.skills_dir)
    assert "SKILL.md" in cat
    assert "genomics-metadata" in cat or "genomics" in cat.lower()


def test_skill_pack_excludes_nested_subskill_markdown(tmp_path):
    root = tmp_path / "s"
    (root / "parent" / "SKILL.md").parent.mkdir(parents=True)
    (root / "parent" / "SKILL.md").write_text("parent", encoding="utf-8")
    (root / "parent" / "overview.md").write_text("overview-body", encoding="utf-8")
    (root / "parent" / "child" / "SKILL.md").parent.mkdir(parents=True)
    (root / "parent" / "child" / "SKILL.md").write_text("child", encoding="utf-8")
    (root / "parent" / "child" / "child_only.md").write_text("nested-secret", encoding="utf-8")
    loaded = load_skill_files(root)
    assert "/skills/parent/overview.md" in loaded
    ov = "".join(loaded["/skills/parent/overview.md"]["content"])
    assert "overview-body" in ov
    nested = "".join(loaded["/skills/parent/child/child_only.md"]["content"])
    assert "nested-secret" in nested


def test_load_skill_files_includes_sibling_markdown(tmp_path):
    root = tmp_path / "skills"
    pack = root / "my_skill"
    pack.mkdir(parents=True)
    (pack / "SKILL.md").write_text("---\nname: my-skill\n---\nbody\n", encoding="utf-8")
    (pack / "REFERENCE.md").write_text("# Ref\nextra\n", encoding="utf-8")
    loaded = load_skill_files(root)
    assert "/skills/my_skill/SKILL.md" in loaded
    assert "/skills/my_skill/REFERENCE.md" in loaded
    ref_body = "".join(loaded["/skills/my_skill/REFERENCE.md"]["content"])
    assert "extra" in ref_body


def test_load_skill_files_prefers_later_root(tmp_path):
    r1 = tmp_path / "r1"
    r2 = tmp_path / "r2"
    (r1 / "dup" / "SKILL.md").parent.mkdir(parents=True)
    (r1 / "dup" / "SKILL.md").write_text("first-only", encoding="utf-8")
    (r2 / "dup" / "SKILL.md").parent.mkdir(parents=True)
    (r2 / "dup" / "SKILL.md").write_text("second-wins", encoding="utf-8")
    loaded = load_skill_files(r1, r2)
    body = "".join(loaded["/skills/dup/SKILL.md"]["content"])
    assert "second-wins" in body
    assert "first-only" not in body


def test_fairifier_config_skill_roots_includes_extra(tmp_path):
    from fairifier.config import FAIRifierConfig

    extra = tmp_path / "user_skills"
    (extra / "custom" / "SKILL.md").parent.mkdir(parents=True)
    (extra / "custom" / "SKILL.md").write_text("---\nname: c\n---\n", encoding="utf-8")
    cfg = FAIRifierConfig()
    cfg.skills_extra_dirs = (extra,)
    paths = list_skill_virtual_paths(*cfg.skill_roots)
    assert any(p.endswith("/custom/SKILL.md") for p in paths)
