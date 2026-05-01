import pytest
from fairifier.agents.json_generator import JSONGeneratorAgent, FieldCandidate

@pytest.mark.anyio
async def test_upstream_reconcile_candidates():
    agent = JSONGeneratorAgent()
    
    # Create candidates with normalized values
    candidates = [
        FieldCandidate(
            field_name="organism",
            value="Some irrelevant excerpt",
            source_id="source_001",
            source_role="supplement",
            relevance_score=0.4,
            evidence="...",
            normalized_value="human"
        ),
        FieldCandidate(
            field_name="organism",
            value="Main text excerpt",
            source_id="source_002",
            source_role="main_manuscript",
            relevance_score=0.9,
            evidence="...",
            normalized_value="Homo sapiens"
        ),
        FieldCandidate(
            field_name="organism",
            value="Another main text excerpt",
            source_id="source_002",
            source_role="main_manuscript",
            relevance_score=0.8,
            evidence="...",
            normalized_value="homo sapiens" # Should group with "Homo sapiens"
        ),
    ]
    
    all_candidates = {"organism": candidates}
    
    reconciled = agent._upstream_reconcile_candidates(all_candidates)
    
    assert "organism" in reconciled
    res = reconciled["organism"]
    
    # Primary should be "Homo sapiens" because it has 2 candidates and main_manuscript
    assert res[0].normalized_value == "Homo sapiens"
    assert res[0].source_id == "source_002"
    
    # Secondary should be the others
    assert len(res) == 3

@pytest.mark.anyio
async def test_normalize_candidates_with_llm(monkeypatch):
    agent = JSONGeneratorAgent()
    
    candidates = {
        "sampling site": [
            FieldCandidate(
                field_name="sampling site",
                value="We sampled at the Wadden Sea tidal flats during summer.",
                source_id="source_001",
                source_role="main_manuscript",
                relevance_score=0.9,
                evidence="source_001:10-50 [role=main_manuscript] (main.md): We sampled at the Wadden Sea tidal flats during summer."
            )
        ]
    }
    
    class MockLLMHelper:
        async def _call_llm(self, messages, operation_name=""):
            class MockResponse:
                content = '{"c_0": "Wadden Sea tidal flats"}'
            return MockResponse()
            
    agent.llm_helper = MockLLMHelper()
    
    await agent._normalize_candidates_with_llm(candidates)
    
    # Check if normalized_value was updated
    assert candidates["sampling site"][0].normalized_value == "Wadden Sea tidal flats"
