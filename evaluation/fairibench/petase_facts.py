"""Fact-level reference records built directly from PETase expert annotations.

The expert annotation is a paper-level fact sheet: five sections, 24 fixed
slots, values nested under context keys (assay name, enzyme variant,
condition). It records *what the paper reports*, not how a FAIR-DS record
should be cut into ISA rows. Scoring against an ISA layout invented by a
converter therefore measures agreement with the converter, not with the
experts.

This module turns each annotation into a flat list of facts, one per expert
leaf value, without inventing structure, identifiers or labels:

* NA leaves are not facts. Top-level NA slots are kept in ``na_slots`` so a
  scorer can flag values the experts said were not reported.
* Identical statements (same slot, same entity, same value) are kept once,
  so a condition shared by four assays counts once, not four times.
* Keys such as ``note`` or ``method`` are explanations, not values, and are
  kept with ``kind="note"`` outside the primary score.

The build is deterministic: the same annotation file always yields the same
facts and fact IDs.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "fairibench.petase_facts.v1"

# Kinds that enter the primary score. ``note`` (explanations), ``cited``
# (values quoted from earlier work), ``relative`` (a fold change, not the
# slot's absolute quantity) and ``not_reported`` are kept in the file for
# review but never scored.
PRIMARY_KINDS = ("value", "result", "entity", "entity_group", "text", "category")

# Fields that can hold a reported result in either the wide layout
# (one column per parameter) or the long layout (parameter name + value).
RESULT_FIELDS = (
    "measurement value",
    "reported measurement",
    "measurement lower bound",
    "measurement upper bound",
    "specific activity",
    "initial reaction rate",
    "catalytic rate constant kcat",
    "michaelis constant km",
    "enzyme melting temperature",
    "half inactivation temperature",
    "pet depolymerisation percentage",
    "product concentration",
    "space-time yield",
)

MATERIAL_ENZYME_FIELDS = (
    "enzyme type",
    "enzyme mutation",
    "enzyme construct description",
    "enzyme identifier",
    "experimental subject name",
    "sample name",
    "observation unit name",
    "material preparation identifier",
)

MATERIAL_SUBSTRATE_FIELDS = (
    "pet substrate type",
    "substrate form factor",
    "pet substrate source",
    "pet substrate preprocessing",
    "material composition",
    "substrate identifier",
    "experimental subject name",
    "sample name",
    "observation unit name",
)

# slot -> (group, kind, package fields that legitimately hold this fact,
#          wide-only fields used for the NA-conflict check)
SLOT_SPEC: Dict[str, Dict[str, Any]] = {
    "substrate.type": {"group": "materials", "kind": "entity",
                       "fields": MATERIAL_SUBSTRATE_FIELDS},
    "substrate.crystallinity": {"group": "materials", "kind": "value",
                                "fields": ("pet crystallinity",) + RESULT_FIELDS,
                                "na_fields": ("pet crystallinity",)},
    "substrate.Tg": {"group": "materials", "kind": "value",
                     "fields": ("pet glass transition temperature",) + RESULT_FIELDS,
                     "na_fields": ("pet glass transition temperature",)},
    "substrate.avg_molecular_weight": {"group": "materials", "kind": "value",
                                       "fields": ("pet molecular weight",) + RESULT_FIELDS,
                                       "na_fields": ("pet molecular weight",)},
    "enzyme.type": {"group": "materials", "kind": "entity",
                    "fields": MATERIAL_ENZYME_FIELDS},
    "reaction.reactor_volume": {"group": "conditions", "kind": "value",
                                "fields": ("reactor volume", "reaction working volume",
                                           "reaction scale")},
    "reaction.enzyme_loading": {"group": "conditions", "kind": "value",
                                "fields": ("enzyme loading", "reaction dosing schedule")},
    "reaction.substrate_solid_loading": {"group": "conditions", "kind": "value",
                                         "fields": ("substrate solid loading",)},
    "reaction.buffer_type_and_concentration": {
        "group": "conditions", "kind": "value",
        "fields": ("buffer type", "buffer concentration", "reaction additives")},
    "reaction.pH": {"group": "conditions", "kind": "value",
                    "fields": ("reaction ph", "ph control")},
    "reaction.temperature": {"group": "conditions", "kind": "value",
                             "fields": ("reaction temperature",)},
    "reaction.agitation_rate": {"group": "conditions", "kind": "value",
                                "fields": ("agitation rate", "mixing method")},
    "reaction.reaction_time": {"group": "conditions", "kind": "value",
                               "fields": ("reaction time", "measurement time point")},
    "kinetics.Tm": {"group": "results", "kind": "result",
                    "fields": RESULT_FIELDS,
                    "na_fields": ("enzyme melting temperature",)},
    "kinetics.T0.5": {"group": "results", "kind": "result",
                      "fields": RESULT_FIELDS,
                      "na_fields": ("half inactivation temperature",)},
    "kinetics.kcat": {"group": "results", "kind": "result",
                      "fields": RESULT_FIELDS,
                      "na_fields": ("catalytic rate constant kcat",)},
    "kinetics.Km": {"group": "results", "kind": "result",
                    "fields": RESULT_FIELDS,
                    "na_fields": ("michaelis constant km",)},
    "kinetics.specific_activity": {"group": "results", "kind": "result",
                                   "fields": RESULT_FIELDS},
    "kinetics.initial_rate": {"group": "results", "kind": "result",
                              "fields": RESULT_FIELDS},
    "methods.substrate_kind": {"group": "methods", "kind": "category",
                               "fields": ("actual pet vs proxy substrate",)},
    "methods.hplc": {"group": "methods", "kind": "category",
                     "fields": ("analytical separation method", "detection method",
                                "quantification calibration")},
    "methods.quantification": {"group": "methods", "kind": "category",
                               "fields": ("detection method", "analytical separation method",
                                          "uv detection wavelength",
                                          "fluorescence excitation wavelength",
                                          "fluorescence emission wavelength",
                                          "quantification calibration")},
    "methods.activity_units": {"group": "methods", "kind": "text",
                               "fields": ("activity unit", "measurement unit",
                                          "reported measurement")},
    "methods.design": {"group": "methods", "kind": "category",
                       "fields": ("depolymerisation measurement design",)},
}

_SECTION_SLOTS = {
    ("substrate_property", "type"): "substrate.type",
    ("substrate_property", "crystallinity"): "substrate.crystallinity",
    ("substrate_property", "Tg"): "substrate.Tg",
    ("substrate_property", "avg_molecular_weight"): "substrate.avg_molecular_weight",
    ("enzyme_property", "type"): "enzyme.type",
    ("reaction_condition_lab_scale", "reactor_volume"): "reaction.reactor_volume",
    ("reaction_condition_lab_scale", "enzyme_loading"): "reaction.enzyme_loading",
    ("reaction_condition_lab_scale", "substrate_solid_loading"):
        "reaction.substrate_solid_loading",
    ("reaction_condition_lab_scale", "buffer_type_and_concentration"):
        "reaction.buffer_type_and_concentration",
    ("reaction_condition_lab_scale", "pH"): "reaction.pH",
    ("reaction_condition_lab_scale", "temperature"): "reaction.temperature",
    ("reaction_condition_lab_scale", "agitation_rate"): "reaction.agitation_rate",
    ("reaction_condition_lab_scale", "reaction_time"): "reaction.reaction_time",
    ("kinetic_parameters_and_measurement_analytics", "Tm"): "kinetics.Tm",
    ("kinetic_parameters_and_measurement_analytics", "T0.5"): "kinetics.T0.5",
    ("kinetic_parameters_and_measurement_analytics", "kcat"): "kinetics.kcat",
    ("kinetic_parameters_and_measurement_analytics", "Km"): "kinetics.Km",
    ("kinetic_parameters_and_measurement_analytics", "specific_activity"):
        "kinetics.specific_activity",
    ("kinetic_parameters_and_measurement_analytics", "initial_rate"):
        "kinetics.initial_rate",
    ("kinetic_parameters_and_measurement_analytics",
     "does_the_study_use_proxy_substrate_or_actual_PET_substrate"): "methods.substrate_kind",
    ("kinetic_parameters_and_measurement_analytics",
     "does_the_product_analysis_use_HPLC_as_standard_quantification"): "methods.hplc",
    ("kinetic_parameters_and_measurement_analytics",
     "how_are_degraded_PET_monomers_quantified_absorbance_or_fluorometric"):
        "methods.quantification",
    ("kinetic_parameters_and_measurement_analytics", "what_are_the_units_of_activity"):
        "methods.activity_units",
    ("kinetic_parameters_and_measurement_analytics",
     "is_depolymerisation_efficacy_endpoint_or_time_resolved"): "methods.design",
}

HPLC_RE = re.compile(r"hplc|uplc|uhplc|lc-ms|liquid chromatograph")
# Values the paper cites from earlier work are not results of this study.
CITED_RE = re.compile(r"cited|prior[- ]work|prior literature|previous(ly)? reported|from (the )?literature"
                      r"|reproduced for comparison|taken from prior|benchmark value", re.I)
# "approximately 3.4-fold higher activity": a ratio to a reference, not a
# specific activity, Tm or rate in the slot's own unit.
RELATIVE_RE = re.compile(r"\d\s*-?\s*fold\b|\bfold[- ](?:change|increase|decrease|higher|lower)", re.I)
# Statements that something was not done or not given are not values.
NEGATIVE_RE = re.compile(r"^\s*no\b|not (performed|measured|reported|given|stated)|\bNA\b", re.I)
# "One unit of activity is defined as 1 µmol ... per min" defines a unit; it
# is not a reported value (the unit itself is scored under methods.activity_units).
# Such clauses are dropped from a result leaf; a leaf with nothing else is a note.
DEFINITION_RE = re.compile(r"\bunits?\b[^.;]{0,40}\bdefined\b|\bdefined as\b", re.I)
GROUP_HINT_RE = re.compile(r"\b(other|library|variants|mutants|screened)\b", re.I)

# slot -> (wide package fields, regex on parameter name in the long layout)
FIELD_TASK: Dict[str, Tuple[Tuple[str, ...], Optional[str]]] = {
    "substrate.type": (("pet substrate type", "substrate form factor", "pet substrate source",
                        "pet substrate preprocessing", "material composition"), None),
    "substrate.crystallinity": (("pet crystallinity",), r"crystallin"),
    "substrate.Tg": (("pet glass transition temperature",), r"glass transition|\btg\b"),
    "substrate.avg_molecular_weight": (("pet molecular weight",), r"molecular weight|\bm[wn]\b"),
    "enzyme.type": (("enzyme type", "enzyme mutation", "enzyme construct description",
                     "enzyme organism source", "enzyme identifier", "material composition"), None),
    "reaction.reactor_volume": (("reactor volume", "reaction working volume"), None),
    "reaction.enzyme_loading": (("enzyme loading", "reaction dosing schedule"), None),
    "reaction.substrate_solid_loading": (("substrate solid loading",), None),
    "reaction.buffer_type_and_concentration": (("buffer type", "buffer concentration"), None),
    "reaction.pH": (("reaction ph", "ph control"), None),
    "reaction.temperature": (("reaction temperature",), None),
    "reaction.agitation_rate": (("agitation rate", "mixing method"), None),
    "reaction.reaction_time": (("reaction time", "measurement time point"), None),
    "kinetics.Tm": (("enzyme melting temperature",), r"\btm\b|melting"),
    "kinetics.T0.5": (("half inactivation temperature",), r"t\s?0\.5|t50|half[- ]?inactivation"),
    "kinetics.kcat": (("catalytic rate constant kcat",), r"k\s?cat|turnover"),
    "kinetics.Km": (("michaelis constant km",), r"\bk\s?m\b|michaelis"),
    "kinetics.specific_activity": (("specific activity",), r"specific activity|\bv\s?max\b|maximum (?:rate|velocity)"),
    "kinetics.initial_rate": (("initial reaction rate", "pet depolymerisation percentage",
                               "product concentration", "space-time yield"),
                              r"\brates?\b|velocity|\bk(?:\d|obs|app)?\b|depolymeri|conversion|yield|release|product|degradation"
                              r"|weight loss|tpa|mhet|activation energy|\bea\b|pre-?exponential|arrhenius"),
    "methods.substrate_kind": (("actual pet vs proxy substrate", "proxy substrate identity"), None),
    "methods.hplc": (("analytical separation method",), None),
    "methods.quantification": (("detection method", "uv detection wavelength",
                                "fluorescence excitation wavelength", "fluorescence emission wavelength",
                                "quantification calibration"), None),
    "methods.activity_units": (("activity unit", "measurement unit"), None),
    "methods.design": (("depolymerisation measurement design",), None),
}

# Long layout: one row per reported number, named by a parameter field.
LONG_VALUE_FIELDS = ("measurement value", "reported measurement", "measurement lower bound",
                     "measurement upper bound")
LONG_PARAM_FIELDS = ("reported parameter name", "measurement quantity")
LONG_PARAM_FALLBACK = "measurement context"  # free text; used only when no parameter field is filled

NOTE_KEYS = {
    "note", "notes", "method", "basis", "definition", "units", "comment",
    "initial_rate_units", "unit", "assay", "description",
}

# ---------------------------------------------------------------------------
# Quantities
# ---------------------------------------------------------------------------

_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
_NUM = r"\d+(?:\.\d+)?"
# A number is a quantity only when it does not sit inside a name such as
# I218A, M2-1, PET-1, H2O2 or Tfu_0883, and is not an exponent (g^-1).
_QUANTITY_RE = re.compile(
    rf"(?<![A-Za-z0-9_.\-\^])(?P<sign>-(?=\d))?(?P<num>{_NUM})"
    rf"(?:\s*(?:-|–|to)\s*(?P<num2>{_NUM}))?"
    rf"(?:\s*(?:×|x|\*)\s*10\^?(?P<exp>[-+]?\d+))?"
    rf"(?P<unit>(?:[^;,()\d]|(?<=[A-Za-z\^\-])\d){{0,48}})"
)
_UNCERTAINTY_RE = re.compile(rf"(±|\+/-)\s*\(?{_NUM}\)?")
_MUTATION_RE = re.compile(r"^[A-Z]\d{1,4}[A-Z]$")

# Unit bases: symbol -> (dimension, factor). Case-sensitive first, so that
# mM (molar) and mm (length) stay apart; words that are not units (TPA,
# protein, enzyme, PET, for, in ...) are dropped from the signature.
_UNIT_BASES_CS = {
    "M": ("molar", 1.0), "mM": ("molar", 1e-3), "uM": ("molar", 1e-6),
    "nM": ("molar", 1e-9), "pM": ("molar", 1e-12),
    "m": ("length", 1.0), "mm": ("length", 1e-3), "cm": ("length", 1e-2),
    "um": ("length", 1e-6), "nm": ("length", 1e-9),
    "U": ("activity", 1.0), "mU": ("activity", 1e-3),
}
_UNIT_BASES_CI = {
    "g": ("mass", 1.0), "mg": ("mass", 1e-3), "ug": ("mass", 1e-6),
    "ng": ("mass", 1e-9), "kg": ("mass", 1e3),
    "l": ("volume", 1.0), "ml": ("volume", 1e-3), "ul": ("volume", 1e-6),
    "mol": ("amount", 1.0), "mmol": ("amount", 1e-3), "umol": ("amount", 1e-6),
    "nmol": ("amount", 1e-9), "pmol": ("amount", 1e-12),
    "s": ("time", 1.0), "sec": ("time", 1.0), "min": ("time", 60.0),
    "mins": ("time", 60.0), "minute": ("time", 60.0), "minutes": ("time", 60.0),
    "h": ("time", 3600.0), "hr": ("time", 3600.0), "hrs": ("time", 3600.0),
    "hour": ("time", 3600.0), "hours": ("time", 3600.0),
    "d": ("time", 86400.0), "day": ("time", 86400.0), "days": ("time", 86400.0),
    "week": ("time", 604800.0), "weeks": ("time", 604800.0),
    "°c": ("celsius", 1.0), "rpm": ("rotation", 1.0), "%": ("percent", 1.0),
    "fold": ("fold", 1.0), "kda": ("molar_mass", 1e3), "da": ("molar_mass", 1.0),
    "g/mol": ("molar_mass", 1.0), "cm2": ("area", 1e-4), "mm2": ("area", 1e-6),
    "m2": ("area", 1.0),
}
_UNIT_PART_RE = re.compile(r"^([A-Za-z°%]+)(\^?-?\d+)?$")


def canonical_unit(unit: str) -> str:
    text = (unit or "").translate(_SUPERSCRIPTS)
    text = text.replace("µ", "u").replace("μ", "u").replace("−", "-").replace("·", " ")
    text = re.sub(r"°\s*C\b", "°C", text).replace("ºC", "°C")
    text = re.sub(r"\bdegrees? C\b", "°C", text)
    return re.sub(r"\s+", " ", text).strip(" .;:-")


@lru_cache(maxsize=65536)
def unit_signature(unit: str) -> Optional[Tuple[Tuple[Tuple[str, int], ...], float]]:
    """Dimension signature of a unit phrase, or None when nothing is a unit.

    ``"mg protein/L for treatment"`` -> mass/volume; ``"nmol g^-1 s^-1"`` ->
    amount/(mass*time). Unknown words are ignored rather than guessed.
    """
    text = canonical_unit(unit)
    if not text:
        return None
    dims: Dict[str, int] = {}
    scale, found = 1.0, False
    text = re.sub(r"\s*/\s*", " / ", text)
    denominator = False
    for token in text.split(" "):
        if token == "/":
            denominator = True
            continue
        if token.lower() in ("per",):
            denominator = True
            continue
        token = token.strip("-")
        match = _UNIT_PART_RE.match(token)
        if not match:
            denominator = False
            continue
        symbol, exponent = match.group(1), match.group(2)
        base = _UNIT_BASES_CS.get(symbol) or _UNIT_BASES_CI.get(symbol.lower())
        if symbol.lower() == "c" and not found:
            base = None
        if base is None and symbol.lower().endswith("2"):
            base = _UNIT_BASES_CI.get(symbol.lower())
        if base is None:
            # cm2 written as cm^2 or cm2
            if exponent and exponent.lstrip("^").lstrip("-") == "2" and symbol.lower() in ("cm", "mm", "m"):
                base = _UNIT_BASES_CI.get(symbol.lower() + "2")
                exponent = "-1" if exponent.lstrip("^").startswith("-") else None
        if base is None:
            denominator = False
            continue
        power = int(exponent.lstrip("^")) if exponent else 1
        if abs(power) > 4:
            # "s4000" or a catalogue number glued to a unit is not a unit power
            denominator = False
            continue
        if denominator:
            power = -abs(power)
        denominator = False
        dim, factor = base
        dims[dim] = dims.get(dim, 0) + power
        scale *= factor ** power
        found = True
    if not found:
        return None
    return tuple(sorted((k, v) for k, v in dims.items() if v)), scale


def extract_quantities(text: Any) -> List[Dict[str, Any]]:
    """Return numeric quantities in ``text``; uncertainties are dropped.

    A range ``a-b unit`` yields both ends. Numbers that are part of names
    (mutations, variant labels, identifiers) or exponents are ignored.
    """
    if text is None:
        return []
    raw = str(text).translate(_SUPERSCRIPTS).replace("−", "-")
    raw = _UNCERTAINTY_RE.sub(" ", raw)
    out: List[Dict[str, Any]] = []
    for match in _QUANTITY_RE.finditer(raw):
        unit_text = (match.group("unit") or "").strip()
        signature = unit_signature(unit_text)
        unit = canonical_unit(unit_text) if signature else ""
        if unit_text.lower().startswith(("-fold", "fold")):
            unit, signature = "fold", ((("fold", 1),), 1.0)
        factor = 10.0 ** int(match.group("exp")) if match.group("exp") else 1.0
        sign = -1.0 if match.group("sign") else 1.0
        for key in ("num", "num2"):
            number = match.group(key)
            if number is None:
                continue
            value = float(number) * factor * (sign if key == "num" else 1.0)
            out.append({"value": value, "unit": unit,
                        "raw": (match.group(0) or "").strip()[:60]})
    return out


def quantities_match(gt: Dict[str, Any], pred: Dict[str, Any], rel_tol: float = 0.02,
                     implied_unit: str = "") -> str:
    """Compare two quantities: ``match``, ``unit_unverified`` or ``none``.

    Equal numbers with the same unit dimensions (after prefix conversion)
    match. Equal numbers where the predicted side states no unit, or where
    the unit phrases cannot be compared, are ``unit_unverified``.
    ``implied_unit`` is a unit stated elsewhere in the predicted row
    (for example a ``measurement unit`` column).
    """
    g_sig = unit_signature(gt.get("unit", ""))
    p_sig = unit_signature(pred.get("unit", "")) or unit_signature(implied_unit)

    def close(a: float, b: float) -> bool:
        if a == b:
            return True
        if a == 0 or b == 0:
            return False
        return abs(a - b) / max(abs(a), abs(b)) <= rel_tol

    if g_sig and p_sig and g_sig[0] == p_sig[0]:
        return "match" if close(gt["value"] * g_sig[1], pred["value"] * p_sig[1]) else "none"
    if not close(gt["value"], pred["value"]):
        return "none"
    if g_sig is None:
        return "match"
    if p_sig:
        # Both units parsed and their dimensions differ (mM vs °C, µmol vs g/L):
        # a different quantity.
        return "none"
    return "unit_unverified"



# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

_TOKEN_SPLIT = re.compile(r"[\s_/,;:()\[\]{}|+]+")
_GENERIC_TOKENS = {
    "the", "and", "of", "for", "in", "with", "a", "an", "to", "by", "on",
    "assay", "assays", "initial", "rate", "rates", "invkm", "invkcat", "percent",
    "enzyme", "enzymes", "variant", "variants", "mutant", "mutants", "type",
    "value", "values", "reported", "kcat", "km", "tm", "or", "vs",
}


def tokens(text: Any) -> List[str]:
    raw = str(text or "").replace("µ", "u").replace("μ", "u")
    parts = [p.strip(".-").lower() for p in _TOKEN_SPLIT.split(raw)]
    return [p for p in parts if p]


def informative_tokens(text: Any) -> List[str]:
    out = []
    for tok in tokens(text):
        if tok in _GENERIC_TOKENS:
            continue
        if re.fullmatch(r"\d+(\.\d+)?", tok):
            continue
        out.append(tok)
    return out


def is_na(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (dict, list)):
        return False
    text = str(value).strip()
    return text == "" or bool(re.match(r"^(NA|N/A|n\.a\.|not reported)\b", text, re.I))


def _entity_tokens(key: str) -> List[str]:
    """Informative tokens of a name; ``G62A-L90F`` splits into mutations."""
    out: List[str] = []
    for tok in informative_tokens(key):
        parts = [p for p in tok.split("-") if p]
        if len(parts) > 1 and all(_MUTATION_RE.match(p.upper()) for p in parts):
            out.extend(parts)
        else:
            out.append(tok)
    return out


def classify_key(key: str, entity_names: Sequence[str]) -> str:
    """``entity`` if a path key names a material listed by the experts."""
    if key.lower() in NOTE_KEYS:
        return "note"
    key_toks = set(_entity_tokens(key))
    if not key_toks:
        return "context"
    if any(_MUTATION_RE.match(t.upper()) for t in key_toks):
        return "entity"
    if key_toks & {"wt", "wild", "wildtype"}:
        return "entity"
    for name in entity_names:
        name_toks = set(_entity_tokens(name))
        if not name_toks:
            continue
        overlap = len(key_toks & name_toks) / len(key_toks)
        if overlap >= 0.5:
            return "entity"
    return "context"


# ---------------------------------------------------------------------------
# Categories for the method questions
# ---------------------------------------------------------------------------

def categories_for(slot: str, text: str) -> List[str]:
    low = text.lower()
    cats: List[str] = []
    if slot == "methods.substrate_kind":
        if re.search(r"\bproxy\b|bhet|pnp|p-nitrophenyl|model substrate|triolein", low):
            cats.append("proxy_substrate")
        if re.search(r"actual|\bpet\b(?! *-? *proxy)", low) and "proxy pet" not in low:
            if re.search(r"actual|real|pet (film|powder|fabric|bottle|flake|nanoparticle)|\bpet\b", low):
                cats.append("actual_pet")
    elif slot == "methods.hplc":
        if re.match(r"\s*(yes|y)\b", low) or (HPLC_RE.search(low) and not re.match(r"\s*no\b", low)):
            cats.append("hplc_yes")
        elif re.match(r"\s*no\b", low):
            cats.append("hplc_no")
    elif slot == "methods.quantification":
        if re.search(r"absorb|uv|spectrophotomet|\b2[34]\d ?nm|od\b", low):
            cats.append("absorbance")
        if re.search(r"fluor", low):
            cats.append("fluorescence")
        if HPLC_RE.search(low):
            cats.append("hplc")
        if re.search(r"ph[- ]?stat|titrat|base consumption", low):
            cats.append("ph_stat")
    elif slot == "methods.design":
        if re.search(r"time[-_ ]?resolved|time[-_ ]?course|kinetic", low):
            cats.append("time_resolved")
        if re.search(r"end[-_ ]?point|single time|final", low):
            cats.append("endpoint")
    return sorted(set(cats))


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def kind_is_entity(slot: str) -> bool:
    return SLOT_SPEC[slot]["kind"] == "entity"


def split_entity_group(raw: str) -> List[str]:
    """``"Other esterases screened: A, B and C"`` -> ``["A", "B", "C"]``.

    A shared head word before the first member (``"PETase variants M1, M2"``)
    is dropped; members must carry at least one informative token.
    """
    head, sep, tail = raw.partition(":")
    if sep and len(head.split()) >= 2:
        body = tail                                   # "Other esterases screened: A, B"
    elif re.search(r"\bincluding\b", raw):
        body = re.split(r"\bincluding\b", raw, maxsplit=1)[1]
    elif re.search(r"\b(variants|mutants)\s+(?=\S+\s*,)", raw):
        body = re.split(r"\b(?:variants|mutants)\s+", raw, maxsplit=1)[1]
    else:
        # A single material with attributes ("PET film, 0.25 mm") is not a list.
        return []
    parts = [p.strip(" .") for p in re.split(r",|;|\band\b", body)]
    members = [p for p in parts if p and informative_tokens(p)]
    if any(extract_quantities(m) for m in members):
        return []
    return members if len(members) > 1 else []


def _walk(value: Any, path: Tuple[str, ...]) -> Iterable[Tuple[Tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, path + (str(key),))
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child, path)
    else:
        yield path, value


def _fact_id(doc_id: str, slot: str, entity_keys: Sequence[str], raw: str) -> str:
    digest = hashlib.sha1(
        json.dumps([doc_id, slot, list(entity_keys), raw], ensure_ascii=False).encode()
    ).hexdigest()[:10]
    return f"{slot}:{digest}"


def build_facts(annotation: Dict[str, Any], document_id: str,
                source_path: Optional[str] = None) -> Dict[str, Any]:
    enzymes = annotation.get("enzyme_property", {}).get("type", [])
    enzymes = [enzymes] if isinstance(enzymes, str) else list(enzymes or [])
    substrates = annotation.get("substrate_property", {}).get("type", [])
    substrates = [substrates] if isinstance(substrates, str) else list(substrates or [])
    entity_names = [str(x) for x in enzymes + substrates if not is_na(x)]

    facts: List[Dict[str, Any]] = []
    na_slots: List[str] = []
    seen = set()
    for section, block in annotation.items():
        if not isinstance(block, dict):
            continue
        for key, value in block.items():
            slot = _SECTION_SLOTS.get((section, key))
            if slot is None:
                continue
            spec = SLOT_SPEC[slot]
            if is_na(value) and not isinstance(value, (dict, list)):
                na_slots.append(slot)
                continue
            for path, leaf in _walk(value, ()):
                if is_na(leaf):
                    continue
                raw = str(leaf).strip()
                if kind_is_entity(slot) and "," in raw or (kind_is_entity(slot) and ":" in raw):
                    members = split_entity_group(raw)
                else:
                    members = None
                key_kinds = [classify_key(k, entity_names) for k in path]
                entity_keys = [k for k, kind in zip(path, key_kinds) if kind == "entity"]
                context_keys = [k for k, kind in zip(path, key_kinds) if kind == "context"]
                is_note = any(kind == "note" for kind in key_kinds)
                kind = spec["kind"]
                if kind in ("result", "value") and DEFINITION_RE.search(raw):
                    # keep only the clauses that report something
                    kept = "; ".join(c for c in re.split(r"\s*;\s*", raw) if not DEFINITION_RE.search(c))
                    if kept:
                        raw = kept
                    else:
                        is_note = True
                quantities = extract_quantities(raw)
                categories: List[str] = []
                if is_note:
                    kind = "note"
                elif CITED_RE.search(raw):
                    kind = "cited"
                elif kind in ("result", "value") and RELATIVE_RE.search(raw):
                    kind = "relative"
                elif kind in ("entity", "text", "value") and NEGATIVE_RE.search(raw) and not any(
                        q["unit"] for q in quantities):
                    kind = "not_reported"
                elif kind == "entity" and members:
                    kind = "entity_group"
                elif kind == "entity" and GROUP_HINT_RE.search(raw):
                    kind = "note"
                elif kind == "category":
                    categories = categories_for(slot, raw)
                    if not categories:
                        kind = "note"
                elif kind == "result" and not quantities:
                    kind = "note"
                elif kind == "value" and not quantities:
                    kind = "text"
                dedupe_key = (slot, tuple(entity_keys), re.sub(r"\s+", " ", raw.lower()),
                              tuple(categories))
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                facts.append({
                    "fact_id": _fact_id(document_id, slot, entity_keys, raw),
                    "slot": slot,
                    "group": spec["group"],
                    "kind": kind,
                    "path": list(path),
                    "entity_keys": entity_keys,
                    "context_keys": context_keys,
                    "raw": raw,
                    "quantities": quantities if kind in ("value", "result") else [],
                    "categories": categories,
                    "members": members if kind == "entity_group" else [],
                })

    source = {}
    if source_path:
        data = Path(source_path).read_bytes()
        source = {"path": str(source_path), "sha256": hashlib.sha256(data).hexdigest()}
    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": document_id,
        "doi": annotation.get("doi"),
        "reference_authority": "expert_annotation",
        "generated_by": "evaluation/benchmark/petase_facts.py (deterministic, no model calls)",
        "source_annotation": source,
        "entities": {"enzymes": enzymes, "substrates": substrates},
        "na_slots": sorted(set(na_slots)),
        "facts": facts,
    }
