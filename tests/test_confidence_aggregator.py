from fairifier.services.confidence_aggregator import aggregate_confidence
from fairifier.config import FAIRifierConfig


def test_aggregate_confidence_combines_components():
    state = {
        "execution_history": [
            {"critic_evaluation": {"score": 0.8}},
            {"critic_evaluation": {"score": 0.6}},
        ],
        "metadata_fields": [
            {
                "field_name": "title",
                "value": "Sample project",
                "evidence": "Title section",
                "confidence": 0.95,
            },
            {
                "field_name": "description",
                "value": "Demo abstract",
                "evidence": "Abstract",
                "confidence": 0.9,
            },
        ],
        "validation_results": {"errors": [], "warnings": []},
    }
    cfg = FAIRifierConfig()
    breakdown = aggregate_confidence(state, cfg)
    
    assert round(breakdown.critic, 2) == 0.7
    assert 0.9 <= breakdown.validation <= 1.0
    assert breakdown.structural > 0
    assert 0.0 <= breakdown.overall <= 1.0

