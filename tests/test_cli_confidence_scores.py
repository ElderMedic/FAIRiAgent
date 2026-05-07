from fairifier.cli import _iter_display_confidence_scores


def test_iter_display_confidence_scores_flattens_nested_numeric_scores():
    scores = {
        "document_parsing": 0.6,
        "_aggregate": {
            "critic": 0.5,
            "structural": 0.7,
            "validation": 0.8,
            "overall": 0.66,
        },
        "non_numeric": {"note": "skip"},
    }

    assert list(_iter_display_confidence_scores(scores)) == [
        ("document_parsing", 0.6),
        ("aggregate.critic", 0.5),
        ("aggregate.structural", 0.7),
        ("aggregate.validation", 0.8),
        ("aggregate.overall", 0.66),
    ]
