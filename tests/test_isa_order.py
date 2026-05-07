from fairifier.agents.json_generator import JSONGeneratorAgent
from fairifier.apps.api.routers import v1 as v1_router
from fairifier.models import MetadataField
from fairifier.services.fairds_api_parser import FAIRDSAPIParser


CANONICAL_ISA_ORDER = [
    "investigation",
    "study",
    "observationunit",
    "sample",
    "assay",
]


def test_fairds_api_parser_exposes_canonical_isa_order():
    assert FAIRDSAPIParser.ISA_SHEETS == CANONICAL_ISA_ORDER


def test_json_generator_outputs_isa_structure_in_canonical_order():
    agent = JSONGeneratorAgent()
    fields = [
        MetadataField(field_name="assay name", value="RNA-seq", isa_sheet="assay", confidence=0.95, status="confirmed"),
        MetadataField(field_name="sample name", value="Sample A", isa_sheet="sample", confidence=0.95, status="confirmed"),
        MetadataField(field_name="observation unit name", value="Plot 1", isa_sheet="observationunit", confidence=0.95, status="confirmed"),
        MetadataField(field_name="study title", value="Earthworm study", isa_sheet="study", confidence=0.95, status="confirmed"),
        MetadataField(field_name="investigation title", value="Earthworm metadata extraction", isa_sheet="investigation", confidence=0.95, status="confirmed"),
    ]

    output = agent._generate_json_output(fields, {}, {"document_path": "paper.md", "confidence_scores": {}})

    assert list(output["isa_structure"].keys()) == CANONICAL_ISA_ORDER


def test_json_generator_embeds_row_aware_isa_structure_and_isa_values():
    agent = JSONGeneratorAgent()
    fields = [
        MetadataField(
            field_name="study identifier",
            value="STUDY-1",
            isa_sheet="study",
            confidence=0.95,
            status="confirmed",
        ),
        MetadataField(
            field_name="sample name",
            value="Sample A",
            isa_sheet="sample",
            entity_id="sample-a",
            confidence=0.95,
            status="confirmed",
        ),
        MetadataField(
            field_name="sample name",
            value="Sample B",
            isa_sheet="sample",
            entity_id="sample-b",
            confidence=0.95,
            status="confirmed",
        ),
        MetadataField(
            field_name="observation unit identifier",
            value="OU-1",
            isa_sheet="sample",
            entity_id="sample-a",
            confidence=0.95,
            status="confirmed",
        ),
        MetadataField(
            field_name="observation unit identifier",
            value="OU-2",
            isa_sheet="sample",
            entity_id="sample-b",
            confidence=0.95,
            status="confirmed",
        ),
    ]

    output = agent._generate_json_output(fields, {}, {"document_path": "paper.md", "confidence_scores": {}})

    sample_sheet = output["isa_structure"]["sample"]
    assert sample_sheet["columns"] == ["observation unit identifier", "sample name"]
    assert len(sample_sheet["rows"]) == 2
    assert sample_sheet["rows"][0]["sample name"] == "Sample A"
    assert sample_sheet["rows"][1]["sample name"] == "Sample B"
    assert output["isa_values"]["sample"]["rows"] == sample_sheet["rows"]


class _OrderedISAClient:
    def __init__(self, base_url: str, timeout: int = 12):
        self.base_url = base_url
        self.timeout = timeout

    def is_available(self) -> bool:
        return True

    def get_available_packages(self, force_refresh: bool = False):
        return ["default"]

    def get_terms(self, force_refresh: bool = False):
        return {}

    def get_package(self, package_name: str, force_refresh: bool = False):
        return {
            "packageName": package_name,
            "metadata": [
                {"level": "Assay", "requirement": "OPTIONAL", "label": "assay name"},
                {"level": "Sample", "requirement": "OPTIONAL", "label": "sample name"},
                {"level": "ObservationUnit", "requirement": "OPTIONAL", "label": "observation unit name"},
                {"level": "Study", "requirement": "MANDATORY", "label": "study title"},
                {"level": "Investigation", "requirement": "MANDATORY", "label": "investigation title"},
            ],
        }


def test_fairds_statistics_orders_isa_levels_canonically(monkeypatch):
    monkeypatch.setattr(
        "fairifier.config.config.fair_ds_api_url",
        "http://fake-fairds.local",
        raising=False,
    )
    monkeypatch.setattr(
        "fairifier.services.fair_data_station.FAIRDataStationClient",
        _OrderedISAClient,
    )

    payload = v1_router._build_fairds_statistics().model_dump()

    assert [row["isa_level"] for row in payload["isa_levels"]] == CANONICAL_ISA_ORDER
