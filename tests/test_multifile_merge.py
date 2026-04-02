from fairifier.graph.langgraph_app import FAIRifierLangGraphApp


def _make_app_without_init() -> FAIRifierLangGraphApp:
    return object.__new__(FAIRifierLangGraphApp)


def test_merge_document_info_entries_preserves_lists_and_conflicts():
    app = _make_app_without_init()
    merged, conflicts = app._merge_document_info_entries(
        [
            {
                "source_path": "paper.pdf",
                "document_info": {
                    "title": "Primary Study",
                    "keywords": ["soil", "earthworm"],
                    "research_domain": "ecotoxicology",
                },
            },
            {
                "source_path": "history.xlsx",
                "document_info": {
                    "keywords": ["earthworm", "time-series"],
                    "research_domain": "environmental toxicology",
                    "methodology": "longitudinal measurements",
                },
            },
        ]
    )

    assert merged["title"] == "Primary Study"
    assert merged["methodology"] == "longitudinal measurements"
    assert merged["keywords"] == ["soil", "earthworm", "time-series"]
    assert "research_domain" in conflicts
    assert "ecotoxicology" in conflicts["research_domain"]
    assert "environmental toxicology" in conflicts["research_domain"]
