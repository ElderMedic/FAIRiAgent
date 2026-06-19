from __future__ import annotations

from fairifier.agents.json_generator import JSONGeneratorAgent


def _make_json_generator_without_init() -> JSONGeneratorAgent:
    return object.__new__(JSONGeneratorAgent)


def test_field_search_queries_adds_petase_aliases():
    agent = _make_json_generator_without_init()

    queries = agent._field_search_queries(
        "reaction temperature",
        "Assay condition for enzymatic PET depolymerization.",
    )

    lowered = {q.lower() for q in queries}
    assert "reaction temperature" in lowered
    assert "assay temperature" in lowered
    assert "incubation temperature" in lowered
