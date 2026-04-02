from fairifier.apps.api.routers import v1 as v1_router


class _FakeFAIRDSClient:
    def __init__(self, base_url: str, timeout: int = 12):
        self.base_url = base_url
        self.timeout = timeout

    def is_available(self) -> bool:
        return True

    def get_available_packages(self, force_refresh: bool = False):
        return ["soil", "default"]

    def get_terms(self, force_refresh: bool = False):
        return {
            "study title": {
                "label": "study title",
                "definition": "Title of a study",
                "example": "Earthworm study",
                "regex": ".+",
                "url": "https://example.org/study-title",
            },
            "investigation title": {
                "label": "investigation title",
                "definition": "Title of investigation",
            },
            "soil type": {
                "label": "soil type",
                "definition": "Type of soil",
            },
        }

    def get_package(
        self, package_name: str, force_refresh: bool = False
    ):
        if package_name == "default":
            return {
                "packageName": "default",
                "metadata": [
                    {
                        "level": "Investigation",
                        "requirement": "MANDATORY",
                        "label": "investigation title",
                        "term": {"label": "investigation title"},
                    },
                    {
                        "level": "Sample",
                        "requirement": "OPTIONAL",
                        "label": "sample id",
                        "term": {"label": "sample id"},
                    },
                ],
            }
        if package_name == "soil":
            return {
                "packageName": "soil",
                "metadata": [
                    {
                        "level": "Study",
                        "requirement": "MANDATORY",
                        "label": "study title",
                        "term": {"label": "study title"},
                    },
                    {
                        "level": "Sample",
                        "requirement": "OPTIONAL",
                        "label": "soil type",
                        "term": {"label": "soil type"},
                    },
                    {
                        "level": "Assay",
                        "requirement": "RECOMMENDED",
                        "label": "sequencing platform",
                        "term": {"label": "sequencing platform"},
                    },
                ],
            }
        return {"packageName": package_name, "metadata": []}


class _FakeUnavailableFAIRDSClient:
    def __init__(self, base_url: str, timeout: int = 12):
        self.base_url = base_url
        self.timeout = timeout

    def is_available(self) -> bool:
        return False


def test_fairds_statistics_endpoint_aggregates_data(
    monkeypatch,
):
    monkeypatch.setattr(
        "fairifier.config.config.fair_ds_api_url",
        "http://fake-fairds.local",
        raising=False,
    )
    monkeypatch.setattr(
        "fairifier.services.fair_data_station.FAIRDataStationClient",
        _FakeFAIRDSClient,
    )

    payload = v1_router._build_fairds_statistics().model_dump()

    assert payload["available"] is True
    assert payload["totals"]["packages"] == 2
    assert payload["totals"]["fields"] == 5
    assert payload["totals"]["mandatory_fields"] == 2
    assert payload["totals"]["recommended_fields"] == 1
    assert payload["totals"]["optional_fields"] == 2
    assert payload["totals"]["terms"] == 3
    assert payload["totals"]["terms_referenced_in_packages"] == 3
    assert payload["totals"]["mandatory_ratio"] == 0.4

    isa_counts = {
        row["isa_level"]: row["fields"]
        for row in payload["isa_levels"]
    }
    assert isa_counts["investigation"] == 1
    assert isa_counts["study"] == 1
    assert isa_counts["sample"] == 2
    assert isa_counts["assay"] == 1

    top_package = payload["package_leaderboard"][0]
    assert top_package["package_name"] == "soil"
    assert top_package["fields"] == 3


def test_fairds_statistics_endpoint_handles_unavailable_api(
    monkeypatch,
):
    monkeypatch.setattr(
        "fairifier.config.config.fair_ds_api_url",
        "http://fake-fairds.local",
        raising=False,
    )
    monkeypatch.setattr(
        "fairifier.services.fair_data_station.FAIRDataStationClient",
        _FakeUnavailableFAIRDSClient,
    )

    payload = v1_router._build_fairds_statistics().model_dump()

    assert payload["available"] is False
    assert payload["totals"]["fields"] == 0
    assert payload["totals"]["packages"] == 0
    assert "unreachable" in payload["message"].lower()
