"""Tests for structured Planner output (P1 §4 of architecture refactor).

Replaces free-text ``special_instructions`` with a structured ``plan_tasks``
list so downstream agents (KnowledgeRetriever in particular) consume
machine-readable fields instead of regex-parsing prose.
"""

from fairifier.models import PlannerTask
from fairifier.utils.planner_tasks import (
    extract_plan_task,
    parse_plan_tasks_from_llm_output,
)


class TestPlannerTaskDataclass:
    def test_default_construction(self):
        t = PlannerTask(agent_name="KnowledgeRetriever")
        assert t.agent_name == "KnowledgeRetriever"
        assert t.priority_packages == []
        assert t.search_terms == []
        assert t.focus_sheets == []
        assert t.skip_if is None
        assert t.notes == ""

    def test_with_packages(self):
        t = PlannerTask(
            agent_name="KnowledgeRetriever",
            priority_packages=["Genome", "Nanopore"],
            search_terms=["assembly", "BGC"],
        )
        assert t.priority_packages == ["Genome", "Nanopore"]
        assert t.search_terms == ["assembly", "BGC"]


class TestExtractPlanTask:
    def test_finds_task_by_agent_name(self):
        tasks = [
            PlannerTask(agent_name="DocumentParser", notes="focus on identifiers"),
            PlannerTask(
                agent_name="KnowledgeRetriever", priority_packages=["Genome"]
            ),
        ]
        kr_task = extract_plan_task(tasks, "KnowledgeRetriever")
        assert kr_task is not None
        assert kr_task.priority_packages == ["Genome"]

    def test_returns_none_when_missing(self):
        tasks = [PlannerTask(agent_name="DocumentParser")]
        assert extract_plan_task(tasks, "JSONGenerator") is None

    def test_handles_empty_list(self):
        assert extract_plan_task([], "KnowledgeRetriever") is None

    def test_handles_none(self):
        assert extract_plan_task(None, "KnowledgeRetriever") is None

    def test_accepts_dict_form_for_serialized_state(self):
        """plan_tasks may be stored as dicts after JSON serialization."""
        tasks = [
            {
                "agent_name": "KnowledgeRetriever",
                "priority_packages": ["Genome"],
                "search_terms": ["BGC"],
            }
        ]
        kr_task = extract_plan_task(tasks, "KnowledgeRetriever")
        assert kr_task is not None
        assert kr_task.priority_packages == ["Genome"]
        assert kr_task.search_terms == ["BGC"]


class TestParsePlanTasksFromLLMOutput:
    def test_parses_structured_plan(self):
        llm_output = {
            "plan_tasks": [
                {
                    "agent_name": "KnowledgeRetriever",
                    "priority_packages": ["Genome", "Nanopore"],
                    "search_terms": ["assembly", "BGC"],
                    "focus_sheets": ["assay"],
                    "notes": "Focus on bacterial genome assembly fields.",
                },
                {
                    "agent_name": "JSONGenerator",
                    "focus_sheets": ["assay", "sample"],
                    "notes": "Ensure assay sheet is fully populated.",
                },
            ]
        }
        tasks = parse_plan_tasks_from_llm_output(llm_output)
        assert len(tasks) == 2
        assert tasks[0].agent_name == "KnowledgeRetriever"
        assert tasks[0].priority_packages == ["Genome", "Nanopore"]
        assert tasks[1].agent_name == "JSONGenerator"

    def test_skips_invalid_entries(self):
        llm_output = {
            "plan_tasks": [
                {"agent_name": "KnowledgeRetriever", "priority_packages": ["X"]},
                {"missing_agent_name": "yes"},
                "not a dict",
                {"agent_name": ""},  # empty agent name dropped
            ]
        }
        tasks = parse_plan_tasks_from_llm_output(llm_output)
        assert len(tasks) == 1
        assert tasks[0].agent_name == "KnowledgeRetriever"

    def test_handles_missing_plan_tasks_key(self):
        assert parse_plan_tasks_from_llm_output({}) == []
        assert parse_plan_tasks_from_llm_output({"other": "stuff"}) == []

    def test_handles_none(self):
        assert parse_plan_tasks_from_llm_output(None) == []

    def test_normalizes_string_lists(self):
        """Sometimes the LLM returns a single string instead of a list."""
        llm_output = {
            "plan_tasks": [
                {
                    "agent_name": "KnowledgeRetriever",
                    "priority_packages": "Genome",  # not a list
                    "search_terms": "BGC,assembly",  # not a list
                }
            ]
        }
        tasks = parse_plan_tasks_from_llm_output(llm_output)
        assert tasks[0].priority_packages == ["Genome"]
        # Comma-separated string is split
        assert "BGC" in tasks[0].search_terms
        assert "assembly" in tasks[0].search_terms

    def test_drops_empty_string_items(self):
        llm_output = {
            "plan_tasks": [
                {
                    "agent_name": "KnowledgeRetriever",
                    "priority_packages": ["Genome", "", None, "Nanopore"],
                }
            ]
        }
        tasks = parse_plan_tasks_from_llm_output(llm_output)
        assert tasks[0].priority_packages == ["Genome", "Nanopore"]
