"""Fact-level PETase scoring: reference building and layout-agnostic matching.

All fixtures are synthetic; no annotation or paper data is needed.
"""

import pytest

from evaluation.fairibench.fact_scorer import entity_in_text, score_record
from evaluation.fairibench.petase_facts import (
    PRIMARY_KINDS,
    build_facts,
    extract_quantities,
    quantities_match,
    split_entity_group,
)

ANNOTATION = {
    "doi": "10.0000/example",
    "substrate_property": {"type": ["PET textile fabric"], "crystallinity": "NA",
                           "Tg": "NA", "avg_molecular_weight": "NA"},
    "enzyme_property": {"type": ["Cutinase Tfu_0883 WT", "Tfu_0883 Q132A/T101A"]},
    "reaction_condition_lab_scale": {
        "reactor_volume": "100 mL",
        "enzyme_loading": "50 mg protein/L",
        "substrate_solid_loading": "NA",
        "buffer_type_and_concentration": "0.2 M Tris-HCl",
        "pH": "7.5",
        "temperature": "60 °C",
        "agitation_rate": "Shaking; exact rpm NA",
        "reaction_time": "48 h",
    },
    "kinetic_parameters_and_measurement_analytics": {
        "Tm": "NA", "T0.5": "NA", "kcat": "NA", "Km": "NA",
        "specific_activity": "NA",
        "initial_rate": {
            "definition": "Initial slope of TPA versus time",
            "k2": {"WT": "0.07 µmol/cm²/h", "Q132A_T101A": "0.63 µmol/cm²/h"},
        },
        "does_the_study_use_proxy_substrate_or_actual_PET_substrate": "Actual PET fabric",
        "does_the_product_analysis_use_HPLC_as_standard_quantification": "No",
        "how_are_degraded_PET_monomers_quantified_absorbance_or_fluorometric": "Fluorometric TPA assay",
        "what_are_the_units_of_activity": ["k2 in µmol/cm²/h"],
        "is_depolymerisation_efficacy_endpoint_or_time_resolved": "Time-resolved through 48 h",
    },
}


@pytest.fixture
def facts():
    return build_facts(ANNOTATION, "petase_example")


def _by_slot(doc, slot):
    return [f for f in doc["facts"] if f["slot"] == slot]


# ---------------------------------------------------------------- building

def test_na_and_not_reported_leaves_are_not_scored(facts):
    assert "kinetics.Tm" in facts["na_slots"]
    assert not _by_slot(facts, "reaction.substrate_solid_loading")
    agitation = _by_slot(facts, "reaction.agitation_rate")
    assert [f["kind"] for f in agitation] == ["not_reported"]


def test_results_keep_their_entity_and_drop_explanations(facts):
    rates = _by_slot(facts, "kinetics.initial_rate")
    scored = {f["raw"]: f for f in rates if f["kind"] == "result"}
    assert scored["0.07 µmol/cm²/h"]["entity_keys"] == ["WT"]
    assert scored["0.63 µmol/cm²/h"]["entity_keys"] == ["Q132A_T101A"]
    assert [f["kind"] for f in rates if f["path"] == ["definition"]] == ["note"]


def test_build_is_deterministic(facts):
    again = build_facts(ANNOTATION, "petase_example")
    assert [f["fact_id"] for f in again["facts"]] == [f["fact_id"] for f in facts["facts"]]


def test_identical_statements_count_once():
    annotation = dict(ANNOTATION)
    annotation["reaction_condition_lab_scale"] = dict(
        ANNOTATION["reaction_condition_lab_scale"],
        temperature={"assay_a": "60 °C", "assay_b": "60 °C"},
    )
    doc = build_facts(annotation, "petase_example")
    assert len(_by_slot(doc, "reaction.temperature")) == 1


def test_cited_values_are_excluded():
    annotation = dict(ANNOTATION)
    annotation["kinetic_parameters_and_measurement_analytics"] = dict(
        ANNOTATION["kinetic_parameters_and_measurement_analytics"],
        Tm="94.5 °C (benchmark value cited in the paper)",
    )
    doc = build_facts(annotation, "petase_example")
    assert [f["kind"] for f in _by_slot(doc, "kinetics.Tm")] == ["cited"]


def test_entity_groups_are_split_into_members():
    assert split_entity_group("Other esterases screened: GoEST15, P8219 and EST1") == [
        "GoEST15", "P8219", "EST1"]
    assert split_entity_group("PETase variants M1, M2, M2-1") == ["M1", "M2", "M2-1"]
    assert split_entity_group("Amorphous PET films including NOACRYSTAL V, NOACRYSTAL R, and PET-GF") == [
        "NOACRYSTAL V", "NOACRYSTAL R", "PET-GF"]


@pytest.mark.parametrize("text", [
    "Goodfellow amorphous PET film, 0.25 mm",
    "PPET: Goodfellow PET powder, copolymer with 1 ppm acetaldehyde, 300 µm",
    "Post-consumer PET bottle pieces from neck, shoulder, body, and bottom",
])
def test_single_material_with_attributes_is_not_split(text):
    assert split_entity_group(text) == []


# ---------------------------------------------------------------- quantities

@pytest.mark.parametrize("text, expected", [
    ("426.3 ± 18.1 nmol g^-1 s^-1", [426.3]),
    ("(9.8 ± 3.5) × 10^-3 L/g", [0.0098]),
    ("1.5-4.5 days", [1.5, 4.5]),
    ("Tfu_0883 I218A", []),
    ("M2-1", []),
    ("approximately 3.4-fold higher", [3.4]),
])
def test_quantity_extraction(text, expected):
    assert [round(q["value"], 6) for q in extract_quantities(text)] == expected


@pytest.mark.parametrize("gt, pred, implied, status", [
    ("50 mg protein/L", "0.05 g/L", "", "match"),
    ("48 h", "2 days", "", "match"),
    ("60 °C", "60", "°C", "match"),
    ("60 °C", "60", "", "unit_unverified"),
    ("60 °C", "65 °C", "", "none"),
    ("10 mM", "10 °C", "", "none"),
])
def test_unit_aware_matching(gt, pred, implied, status):
    g, p = extract_quantities(gt)[0], extract_quantities(pred)[0]
    assert quantities_match(g, p, implied_unit=implied) == status


def test_entity_matching_requires_the_same_mutations():
    assert entity_in_text("Q132A_T101A", "Tfu_0883 Q132A/T101A double mutant")
    assert not entity_in_text("Q132A_T101A", "Tfu_0883 I218A")
    assert entity_in_text("WT", "wild-type Tfu_0883")
    assert not entity_in_text("WT", "Tfu_0883 I218A")


# ---------------------------------------------------------------- scoring

def _wide_record():
    """Results in wide columns, one sample per variant."""
    return {"isa_structure": {
        "observationunit": {"rows": [
            {"observation unit identifier": "OU1", "experimental subject name": "Tfu_0883 wild-type"},
            {"observation unit identifier": "OU2", "experimental subject name": "Tfu_0883 Q132A/T101A"},
        ]},
        "sample": {"rows": [
            {"sample identifier": "S1", "observation unit identifier": "OU1", "enzyme type": "Cutinase Tfu_0883 WT"},
            {"sample identifier": "S2", "observation unit identifier": "OU2", "enzyme type": "Tfu_0883 Q132A/T101A"},
            {"sample identifier": "S3", "pet substrate type": "PET textile fabric"},
        ]},
        "assay": {"rows": [
            {"assay identifier": "A1", "sample identifier": "S1", "initial reaction rate": "0.07 µmol/cm2/h",
             "reaction temperature": "60", "reactor volume": "100 mL", "enzyme loading": "50 mg/L",
             "buffer type": "Tris-HCl", "buffer concentration": "0.2 M", "reaction ph": "7.5",
             "reaction time": "48 h", "actual pet vs proxy substrate": "actual_pet",
             "fluorescence excitation wavelength": "315", "depolymerisation measurement design": "time_resolved",
             "activity unit": "µmol/cm2/h", "detection method": "fluorescence"},
            {"assay identifier": "A2", "sample identifier": "S2", "initial reaction rate": "0.63 µmol/cm2/h"},
        ]},
    }}


def _long_record():
    """The same content in long layout, several rows per variant."""
    rows = []
    for n, (variant, value) in enumerate([("WT", "0.07"), ("Q132A/T101A", "0.63")]):
        rows.append({"assay identifier": f"L{n}", "assay name": f"PET hydrolysis {variant}",
                     "reported parameter name": "k2", "measurement value": value,
                     "measurement unit": "µmol/cm²/h", "reaction temperature": "60 °C"})
        rows.append({"assay identifier": f"L{n}b", "assay name": f"PET hydrolysis {variant} repeat",
                     "reaction temperature": "60 °C"})
    return {"isa_structure": {"assay": {"rows": rows}}}


def test_perfect_wide_record_scores_high(facts):
    result = score_record(facts, _wide_record())
    rates = [f for f in result["facts"] if f["slot"] == "kinetics.initial_rate"]
    assert all(f["strict"] == 1.0 and f["attached"] for f in rates)
    assert result["scores"]["strict"] >= 0.9
    assert result["na_conflicts"] == []


def test_layout_does_not_change_result_credit(facts):
    wide = score_record(facts, _wide_record())
    long = score_record(facts, _long_record())
    for doc in (wide, long):
        rates = [f for f in doc["facts"] if f["slot"] == "kinetics.initial_rate"]
        assert [f["strict"] for f in rates] == [1.0, 1.0]
        temperature = [f for f in doc["facts"] if f["slot"] == "reaction.temperature"]
        assert temperature[0]["strict"] == 1.0


def test_value_on_wrong_variant_is_not_attached(facts):
    record = _wide_record()
    assay = record["isa_structure"]["assay"]["rows"]
    assay[0]["initial reaction rate"], assay[1]["initial reaction rate"] = (
        assay[1]["initial reaction rate"], assay[0]["initial reaction rate"])
    result = score_record(facts, record)
    rates = [f for f in result["facts"] if f["slot"] == "kinetics.initial_rate"]
    assert [f["attached"] for f in rates] == [False, False]
    assert [f["strict"] for f in rates] == [0.0, 0.0]
    assert all(f["structured"] == 1.0 for f in rates)


def test_value_only_in_notes_is_unstructured(facts):
    record = {"isa_structure": {"assay": {"rows": [
        {"assay identifier": "A", "reaction condition notes": "temperature: 60 °C"}]}}}
    result = score_record(facts, record)
    temperature = [f for f in result["facts"] if f["slot"] == "reaction.temperature"][0]
    assert temperature["status"] == "unstructured"
    assert temperature["strict"] == 0.0 and temperature["anywhere"] == 1.0


def test_missing_output_scores_zero_and_stays_counted(facts):
    result = score_record(facts, None)
    assert result["output_present"] is False
    assert result["n_facts"] > 0 and result["scores"]["strict"] == 0.0


def test_value_in_na_slot_is_flagged(facts):
    record = _wide_record()
    record["isa_structure"]["sample"]["rows"][0]["enzyme melting temperature"] = "71 °C"
    result = score_record(facts, record)
    assert result["na_conflicts"] and result["na_conflicts"][0]["slot"] == "kinetics.Tm"


def test_source_support_counts_literal_numbers(facts):
    result = score_record(facts, _wide_record(), source_text="k2 0.07 and 0.63 at 60 °C, 100 mL, 7.5, 48 h, 0.2 M")
    support = result["source_support"]
    assert support["checked_cells"] > 0
    # 50 mg/L is not in this source text
    assert any("50" in u["value"] for u in support["unsupported_examples"])


# ------------------------------------------------- placement, attachment, error terms

KINETICS = {
    "doi": "10.0000/kinetics",
    "substrate_property": {"type": ["Amorphous PET film"], "crystallinity": "NA", "Tg": "NA",
                           "avg_molecular_weight": "NA"},
    "enzyme_property": {"type": ["BhrPETase", "IsPETase", "LCC"]},
    "kinetic_parameters_and_measurement_analytics": {
        "Tm": {"BhrPETase": "101 °C without added Ca2+; Ca2+ increased Tm by 6.4 °C"},
        "Km": {"BHET": {"BhrPETase": "16.78 ± 2.95 mM", "LCC": "25.82 ± 2.31 mM"}},
        "specific_activity": {"proxy_pNPB": "One unit defined as 1 µmol p-nitrophenol produced per minute"},
    },
}


def _kinetics_record(bhr_extra=None, study_text="BhrPETase, IsPETase and LCC compared"):
    bhr = {"sample identifier": "S1", "observation unit identifier": "OU1", "enzyme type": "BhrPETase",
           "sample name": "Secretory expression of BhrPETase, LCC and IsPETase"}
    bhr.update(bhr_extra or {})
    return {"isa_structure": {
        "study": {"rows": [{"study identifier": "ST", "study description": study_text}]},
        "observationunit": {"rows": [{"observation unit identifier": "OU1", "study identifier": "ST"},
                                     {"observation unit identifier": "OU2", "study identifier": "ST"}]},
        "sample": {"rows": [bhr, {"sample identifier": "S2", "observation unit identifier": "OU2",
                                  "enzyme type": "LCC"}]},
        "assay": {"rows": [
            {"assay identifier": "A1", "sample identifier": "S1", "michaelis constant km": "16.78 ± 2.95 mM"},
            {"assay identifier": "A2", "sample identifier": "S2", "michaelis constant km": "25.82 mM"},
        ]},
    }}


@pytest.fixture
def kinetics():
    return build_facts(KINETICS, "petase_kinetics")


def _fact(result, slot, entity=None):
    return [f for f in result["facts"] if f["slot"] == slot
            and (entity is None or f["entity_keys"] == [entity])]


def test_unit_definition_is_not_a_result(kinetics):
    defined = _by_slot(kinetics, "kinetics.specific_activity")
    assert [f["kind"] for f in defined] == ["note"]


def test_wide_result_column_belongs_to_its_slot(kinetics):
    record = _kinetics_record()
    assay = record["isa_structure"]["assay"]["rows"][0]
    assay["catalytic rate constant kcat"] = assay.pop("michaelis constant km")
    km = _fact(score_record(kinetics, record), "kinetics.Km", "BhrPETase")[0]
    assert km["structured"] == 0.0 and km["anywhere"] == 1.0


def test_long_layout_value_needs_the_slot_parameter(kinetics):
    record = _kinetics_record()
    assay = record["isa_structure"]["assay"]["rows"][0]
    assay.pop("michaelis constant km")
    assay.update({"measurement value": "16.78", "measurement unit": "mM", "reported parameter name": "kcat"})
    assert _fact(score_record(kinetics, record), "kinetics.Km", "BhrPETase")[0]["structured"] == 0.0
    assay["reported parameter name"] = "Km (BHET)"
    assert _fact(score_record(kinetics, record), "kinetics.Km", "BhrPETase")[0]["strict"] == 1.0


def test_value_on_collective_or_study_text_is_not_attached(kinetics):
    record = _kinetics_record()
    rows = record["isa_structure"]["assay"]["rows"]
    rows[0]["michaelis constant km"], rows[1]["michaelis constant km"] = "25.82 mM", "16.78 mM"
    result = score_record(kinetics, record)
    # BhrPETase's Km sits on LCC's assay; the study row and the sample name
    # listing all three enzymes must not rescue it.
    assert _fact(result, "kinetics.Km", "BhrPETase")[0]["attached"] is False
    assert _fact(result, "kinetics.Km", "LCC")[0]["attached"] is False


def test_identity_field_beats_a_collective_sample_name(kinetics):
    result = score_record(kinetics, _kinetics_record())
    assert _fact(result, "kinetics.Km", "BhrPETase")[0]["attached"] is True
    assert _fact(result, "kinetics.Km", "LCC")[0]["attached"] is True


def test_error_term_is_reported_separately(kinetics):
    result = score_record(kinetics, _kinetics_record())
    bhr, lcc = _fact(result, "kinetics.Km", "BhrPETase")[0], _fact(result, "kinetics.Km", "LCC")[0]
    assert bhr["uncertainty"] is True and bhr["strict"] == 1.0
    assert lcc["uncertainty"] is False and lcc["strict"] == 1.0
    assert result["scores"]["uncertainty_kept_rate"] == 0.5
    record = _kinetics_record()
    record["isa_structure"]["assay"]["rows"][1]["measurement uncertainty value"] = "2.31"
    assert _fact(score_record(kinetics, record), "kinetics.Km", "LCC")[0]["uncertainty"] is True


def test_change_matches_delta_or_absolute_value(kinetics):
    absolute = _kinetics_record({"enzyme melting temperature": "101 °C; 107.4 °C with Ca2+"})
    delta = _kinetics_record({"enzyme melting temperature": "101 °C; +6.4 °C with Ca2+"})
    only_base = _kinetics_record({"enzyme melting temperature": "101 °C"})
    scores = [_fact(score_record(kinetics, r), "kinetics.Tm")[0]["strict"] for r in (absolute, delta, only_base)]
    assert scores == [1.0, 1.0, 0.5]


def test_bare_number_in_free_text_is_not_evidence(kinetics):
    record = _kinetics_record({"enzyme preparation": "purified on HiPrep Phenyl FF 16/10"})
    record["isa_structure"]["assay"]["rows"][0]["michaelis constant km"] = "n.d."
    km = _fact(score_record(kinetics, record), "kinetics.Km", "BhrPETase")[0]
    assert km["anywhere"] == 0.0
    record["isa_structure"]["assay"]["rows"][0]["measurement notes"] = "Km = 16.78"
    km = _fact(score_record(kinetics, record), "kinetics.Km", "BhrPETase")[0]
    assert km["anywhere"] == 0.5 and km["structured"] == 0.0


def test_row_naming_several_parameters_designates_none(kinetics):
    record = _kinetics_record()
    assay = record["isa_structure"]["assay"]["rows"][0]
    assay.pop("michaelis constant km")
    assay.update({"measurement value": "16.78", "measurement unit": "mM",
                  "reported parameter name": "Km, Vmax, kcat (Michaelis-Menten fit)"})
    km = _fact(score_record(kinetics, record), "kinetics.Km", "BhrPETase")[0]
    assert km["structured"] == 0.0


def test_numbers_with_different_unit_dimensions_do_not_match():
    gt = {"value": 1.0, "unit": "umol"}
    assert quantities_match(gt, extract_quantities("1 g/L Lutensol AT25")[0]) == "none"
    assert quantities_match(gt, extract_quantities("1 µmol")[0]) == "match"
    assert quantities_match(gt, {"value": 1.0, "unit": ""}) == "unit_unverified"


def test_fold_change_is_kept_but_not_scored_as_the_slot_quantity():
    import copy

    annotation = copy.deepcopy(ANNOTATION)
    annotation["kinetic_parameters_and_measurement_analytics"]["specific_activity"] = {
        "LCC": "approximately 3.4-fold higher activity against PET than wild type",
        "ICCG": "12.5 U/mg",
    }
    activity = _by_slot(build_facts(annotation, "petase_example"), "kinetics.specific_activity")
    kinds = {f["raw"][:22]: f["kind"] for f in activity}
    assert kinds == {"approximately 3.4-fold": "relative", "12.5 U/mg": "result"}
    assert "relative" not in PRIMARY_KINDS
