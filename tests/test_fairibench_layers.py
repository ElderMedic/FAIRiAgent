"""Three-task PETase scoring (fields, structure, values) on synthetic records."""

import pytest

from evaluation.fairibench.layered_scorer import (
    TextInfo,
    best_entities,
    is_placeholder,
    load_sheets,
    score_layers,
)
from evaluation.fairibench.petase_facts import build_facts

ANNOTATION = {
    "doi": "10.0000/example",
    "substrate_property": {"type": ["Goodfellow amorphous PET film / Gf-PET"], "crystallinity": "NA",
                           "Tg": "NA", "avg_molecular_weight": "NA"},
    "enzyme_property": {"type": ["LCC", "LCC ICCG / F243I/D238C/S283C/Y127G"]},
    "reaction_condition_lab_scale": {
        "reactor_volume": "NA", "enzyme_loading": "NA", "substrate_solid_loading": "NA",
        "buffer_type_and_concentration": "100 mM potassium phosphate",
        "pH": "8", "temperature": "72 °C", "agitation_rate": "NA", "reaction_time": "10 h",
    },
    "kinetic_parameters_and_measurement_analytics": {
        "Tm": {"LCC": "84.7 °C", "ICCG": "94.5 °C"},
        "T0.5": "NA", "kcat": "NA", "Km": "NA", "specific_activity": "NA", "initial_rate": "NA",
        "does_the_study_use_proxy_substrate_or_actual_PET_substrate": "Actual PET",
        "does_the_product_analysis_use_HPLC_as_standard_quantification": "Yes, HPLC",
        "how_are_degraded_PET_monomers_quantified_absorbance_or_fluorometric": "HPLC with UV absorbance",
        "what_are_the_units_of_activity": "NA",
        "is_depolymerisation_efficacy_endpoint_or_time_resolved": "Time-resolved",
    },
}

LCC = "LCC"
ICCG = "LCC ICCG / F243I/D238C/S283C/Y127G"


@pytest.fixture
def facts():
    return build_facts(ANNOTATION, "petase_example")


def _record(sample_rows, assay_rows, ou_rows=()):
    return {"packages_used": ["petase_enzyme_engineering"],
            "isa_structure": {"observationunit": {"rows": list(ou_rows)},
                              "sample": {"rows": sample_rows}, "assay": {"rows": assay_rows}}}


GOOD = _record(
    [
        {"sample identifier": "S_LCC", "enzyme type": "Wild-type LCC", "enzyme melting temperature": "84.7 °C",
         "petase material type": "enzyme_variant"},
        {"sample identifier": "S_ICCG", "enzyme type": "Engineered LCC variant ICCG",
         "enzyme mutation": "F243I/D238C/S283C/Y127G", "enzyme melting temperature": "94.5 °C",
         "petase material type": "enzyme_variant"},
        {"sample identifier": "S_GF", "pet substrate type": "Amorphous Gf-PET film (Goodfellow)",
         "petase material type": "pet_substrate", "sample description": "used with LCC and ICCG"},
    ],
    [{"assay identifier": "A1", "sample identifier": "S_ICCG", "reaction temperature": "72",
      "reaction ph": "8.0", "buffer type": "potassium phosphate", "buffer concentration": "100 mM",
      "reaction time": "10 h", "actual pet vs proxy substrate": "actual_pet",
      "analytical separation method": "HPLC", "detection method": "UV absorbance 240 nm",
      "depolymerisation measurement design": "time_resolved"}],
    [{"observation unit identifier": "OU1", "enzyme sample identifier": "S_ICCG",
      "substrate sample identifier": "S_GF"}],
)


def test_placeholders_are_empty():
    assert is_placeholder("not specified")
    assert is_placeholder("Not specified (no sequencing performed)")
    assert not is_placeholder("72 °C")
    sheets = load_sheets(_record([{"enzyme type": "not specified", "sample name": "LCC"}], []))
    assert sheets["sample"][0] == {"sample name": "LCC"}


def test_family_name_does_not_tie_variants():
    names = [LCC, ICCG, "LCC ICCM / F243I/D238C/S283C/N246M"]
    assert best_entities(names, TextInfo("Wild-type LCC enzyme")) == [LCC]
    assert best_entities(names, TextInfo("Engineered LCC variant ICCG")) == [ICCG]
    # a named code outranks a wrongly reported mutation set
    assert best_entities([ICCG, "LCC D238C/S283C"], TextInfo("ICCG variant: D238C/S283C + I284C")) == [ICCG]
    # a row listing many materials is nobody's own row
    many = ["BTA1", "BTA2", "FsC", "Is-PETase"]
    assert best_entities(many, TextInfo("Panel BTA1, BTA2, FsC, Is-PETase")) == []


def test_good_record_on_all_three_tasks(facts):
    r = score_layers(facts, GOOD)
    assert r["fields"]["slot_recall"] == 1.0
    ent = r["structure"]["entities"]
    assert ent["enzyme"]["own_row"] == 1.0 and ent["enzyme"]["named_in_field"] == 1.0
    assert ent["substrate"]["own_row"] == 1.0
    assert r["structure"]["parent_link_rate"] == {"sample": pytest.approx(2 / 3, abs=1e-3), "assay": 1.0}
    tm = [f for f in r["values"]["facts"] if f["slot"] == "kinetics.Tm"]
    assert [f["in_field"] for f in tm] == [1.0, 1.0] and all(f["attached"] for f in tm)


def test_placeholder_fields_are_not_found_but_content_is_seen(facts):
    record = _record(
        [{"enzyme type": "not specified", "enzyme melting temperature": "not specified",
          "petase material type": "enzyme_variant", "sample description": "Engineered ICCG, Tm 94.5 °C"}],
        [{"reaction temperature": "not specified", "assay description": "72 °C, pH 8"}])
    r = score_layers(facts, record)
    assert r["fields"]["slots"]["kinetics.Tm"]["found"] is False
    assert r["fields"]["slots"]["reaction.temperature"]["found"] is False
    ent = r["structure"]["entities"]["enzyme"]
    assert ent["own_row"] == 0.5 and ent["named_in_field"] == 0.0
    tm = [f for f in r["values"]["facts"] if f["raw"] == "94.5 °C"][0]
    assert tm["in_field"] == 0.0 and tm["anywhere"] == 1.0


def test_long_layout_counts_as_field(facts):
    record = _record([], [{"assay identifier": "A", "reported parameter name": "Tm",
                           "measurement value": "94.5", "measurement unit": "°C"}])
    r = score_layers(facts, record)
    assert r["fields"]["slots"]["kinetics.Tm"]["found"] is True


def test_value_in_na_slot_is_reported(facts):
    record = _record([], [{"assay identifier": "A", "agitation rate": "150 rpm"}])
    r = score_layers(facts, record)
    assert "reaction.agitation_rate" in r["fields"]["na_slots_filled"]


def test_missing_output(facts):
    r = score_layers(facts, None)
    assert r["output_present"] is False and r["fields"]["slot_recall"] == 0.0
    assert r["structure"]["entities"]["enzyme"]["own_row"] == 0.0


def test_values_only_drawn_in_a_figure_are_reported_apart(facts):
    # The paper text gives LCC's Tm but ICCG's only appears on a figure.
    text = "LCC melted at 84.7 °C (Figure 2). Reactions ran at 72 °C, pH 8, for 10 h in 100 mM buffer."
    r = score_layers(facts, GOOD, source_text=text)
    tm = {f["raw"]: f["in_source"] for f in r["values"]["facts"] if f["slot"] == "kinetics.Tm"}
    assert tm == {"84.7 °C": True, "94.5 °C": False}
    results = r["values"]["by_group"]["results"]
    assert results["in_source_text"] == 0.5 and results["in_field_of_source_text"] == 1.0
    assert score_layers(facts, GOOD)["values"]["by_group"]["results"]["in_source_text"] is None


def test_same_conditions_on_different_samples_are_not_duplicate_assays():
    from evaluation.fairibench.fact_scorer import structure_diagnostics
    row = {"reaction temperature": "30 °C", "reaction ph": "8"}
    sheets = {"assay": [{"assay identifier": "A1", "sample identifier": "WT", **row},
                        {"assay identifier": "A2", "sample identifier": "M1", **row},
                        {"assay identifier": "A3", "sample identifier": "M1", **row}]}
    assert structure_diagnostics(sheets)["duplicate_row_share"]["assay"] == pytest.approx(1 / 3, abs=1e-3)


def test_superscript_and_flattened_variant_names_carry_the_same_mutations():
    from evaluation.fairibench.materials import mutations

    assert mutations("IsPETaseTM^K95N/F201I") == mutations("IsPETaseTMK95N/F201I") == {"K95N", "F201I"}
    assert mutations("IsPETaseTMQ119L") == {"Q119L"}
    assert mutations("Thc_Cut1") == frozenset() and mutations("PETase") == frozenset()


def test_variant_named_relative_to_its_parent_is_read_from_its_own_name():
    from evaluation.fairibench.fact_scorer import row_material

    names = ["IsPETaseTM / S121E/D186H/R280A", "IsPETaseTMK95N/F201I", "DuraPETaseK95N/S121E/F201I/R280A"]
    row = {"enzyme type": "IsPETaseTM^K95N/F201I", "enzyme mutation": "S121E/D186H/R280A/K95N/F201I"}
    assert row_material(row, "sample", "enzyme", names) == "IsPETaseTMK95N/F201I"
