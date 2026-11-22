"""Three separate PETase scoring tasks: fields, structure, values.

They answer different questions and are never folded into one number.

1. **Fields** — for every slot the experts filled (crystallinity, reaction
   temperature, kcat, ...), does the record hold a real value in a package
   field meant for that slot? Correctness of the value is not checked here.
   Slots the experts marked NA but the record fills are counted separately.
2. **Structure** — does every expert material (enzyme variant, substrate)
   get its own Sample/ObservationUnit row, named in a naming field? Are
   package fields on their package sheet, do child rows link to parents,
   and are rows holding results linked to an expert material?
3. **Values** — for expert values (material properties, conditions,
   results, method answers): is the reported value present in a designated
   field, present anywhere, and for results tied to a material, on that
   material's row?

Placeholder text such as ``not specified`` counts as empty everywhere.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from evaluation.fairibench.fact_scorer import (
    NAMING_FIELDS,
    PRIMARY_ID,
    _SEVERAL,
    SHEETS,
    _all_categories,
    attachment,
    designates,
    _lineage,
    _norm_field,
    _norm_sheet,
    _predicted_categories,
    _quantity_fact,
    RecordIndex,
    row_material,
    _row_text,
    structure_diagnostics,
    _text_fact,
    uncertainty_kept,
)
from evaluation.fairibench.materials import (
    TextInfo,  # noqa: F401  (imported by callers from here)
    best_entities,
    entity_score,
    expert_entities,
    token_frequency,
)
from evaluation.fairibench.petase_facts import FIELD_TASK, RESULT_FIELDS, SLOT_SPEC, extract_quantities

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_PATH = ROOT / "evaluation/config/packages/petase_enzyme_engineering_package.json"
PACKAGE_NAME = "petase_enzyme_engineering"

PLACEHOLDER_RE = re.compile(
    r"^\s*(?:not (?:specified|reported|available|applicable|provided|stated|mentioned|given|described|determined)"
    r"|unspecified|unknown|n/?a|none|null|nan|tbd|missing|n\.d\.?|-+|—|–)\b[^0-9]{0,60}$",
    re.I,
)


def is_placeholder(text: str) -> bool:
    return bool(PLACEHOLDER_RE.match(text)) or not text.strip()


# ---------------------------------------------------------------------------
# Loading (placeholders removed)
# ---------------------------------------------------------------------------

def load_sheets(record: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
    container = (record.get("isa_structure") or record.get("isa_sheets")
                 or record.get("isa_values") or record)
    sheets: Dict[str, List[Dict[str, str]]] = {s: [] for s in SHEETS}
    for raw_name, block in container.items():
        sheet = _norm_sheet(raw_name)
        if sheet is None:
            continue
        rows = block.get("rows", block.get("expected_rows", [])) if isinstance(block, dict) else block
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            clean = {}
            for field, value in row.items():
                if isinstance(value, list):
                    value = "; ".join(str(v) for v in value if v not in (None, ""))
                if value is None or isinstance(value, dict):
                    continue
                text = str(value).strip()
                if text and not is_placeholder(text):
                    clean[_norm_field(field)] = text
            sheets[sheet].append(clean)
    return sheets


def packages_used(record: Dict[str, Any]) -> List[str]:
    used = record.get("packages_used") or []
    if isinstance(used, dict):
        used = list(used)
    return [str(p if not isinstance(p, dict) else p.get("name", p)) for p in used]


@lru_cache(maxsize=1)
def package_sheets() -> Dict[str, str]:
    data = json.loads(PACKAGE_PATH.read_text())
    return {_norm_field(item["label"]): _norm_sheet(item["sheetName"]) for item in data["metadata"]}


# ---------------------------------------------------------------------------
# Task 1: fields
# ---------------------------------------------------------------------------

_GENERIC_MATERIAL_FIELDS = ("material composition",)
_LONG_PARAM_FIELDS = ("reported parameter name", "measurement quantity", "reported measurement")
_VALUE_FIELDS = ("measurement value", "reported measurement")



def slot_populated(slot: str, sheets: Dict[str, List[Dict[str, str]]]) -> Optional[Dict[str, str]]:
    """First cell that fills ``slot`` (wide field, or long-layout parameter + value)."""
    wide, long_re = FIELD_TASK[slot]
    numeric = SLOT_SPEC[slot]["kind"] in ("value", "result")
    for sheet, rows in sheets.items():
        for row in rows:
            for field in wide:
                value = row.get(field)
                if field in _GENERIC_MATERIAL_FIELDS and value:
                    # generic material field: counts only on a row of that material kind
                    mtype = row.get("petase material type", "").lower()
                    want = "enzym" if slot == "enzyme.type" else "substrate"
                    if mtype and want not in mtype and not (want == "substrate" and "pet" in mtype):
                        continue
                if value and (not numeric or extract_quantities(value) or field in (
                        "mixing method", "ph control", "buffer type", "reaction dosing schedule")):
                    return {"sheet": sheet, "field": field, "value": value[:120]}
            if long_re:
                param = " ".join(row.get(f, "") for f in _LONG_PARAM_FIELDS).lower().replace("_", " ")
                if param and designates(slot, param, shared=False):
                    for vf in _VALUE_FIELDS:
                        if row.get(vf) and extract_quantities(row[vf]):
                            return {"sheet": sheet, "field": f"{vf} [{param[:40]}]", "value": row[vf][:120]}
    return None


def score_fields(facts_doc: Dict[str, Any], sheets) -> Dict[str, Any]:
    expert_slots = sorted({f["slot"] for f in facts_doc["facts"] if f["kind"] in (
        "value", "result", "entity", "entity_group", "text", "category")})
    per_slot = {}
    for slot in expert_slots:
        hit = slot_populated(slot, sheets)
        per_slot[slot] = {"found": hit is not None, "evidence": hit}
    na_filled = {}
    for slot in facts_doc.get("na_slots", []):
        if slot not in FIELD_TASK or slot in expert_slots:
            continue
        hit = slot_populated(slot, sheets)
        if hit:
            na_filled[slot] = hit
    groups = {}
    for group in ("materials", "conditions", "results", "methods"):
        slots = [s for s in expert_slots if SLOT_SPEC[s]["group"] == group]
        groups[group] = {"n": len(slots),
                         "found": sum(per_slot[s]["found"] for s in slots),
                         "recall": round(sum(per_slot[s]["found"] for s in slots) / len(slots), 4) if slots else None}
    n = len(expert_slots)
    return {
        "n_expert_slots": n,
        "slot_recall": round(sum(v["found"] for v in per_slot.values()) / n, 4) if n else None,
        "by_group": groups,
        "n_na_slots": len(facts_doc.get("na_slots", [])),
        "na_slots_filled": na_filled,
        "slots": per_slot,
    }


# ---------------------------------------------------------------------------
# Task 2: structure
# ---------------------------------------------------------------------------

PARENT_ID_FIELDS = {
    "study": ("investigation identifier",),
    "observationunit": ("study identifier",),
    "sample": ("observation unit identifier",),
    "assay": ("sample identifier", "observation unit identifier"),
}


def score_structure(facts_doc: Dict[str, Any], sheets) -> Dict[str, Any]:
    entities = expert_entities(facts_doc)
    all_names = [n for names in entities.values() for n in names]
    material_rows = [(s, i, r) for s in ("observationunit", "sample") for i, r in enumerate(sheets[s]) if r]

    own_row, named, assigned_rows = set(), set(), {}
    for sheet, i, row in material_rows:
        naming = TextInfo(_row_text(row, sheet, NAMING_FIELDS))
        full = TextInfo(_row_text(row, sheet))
        # A row is identified by its naming fields; descriptions and notes are
        # used only when no naming field identifies any material.
        by_name = {kind: best_entities(names, naming) for kind, names in entities.items()}
        fallback = not any(by_name.values())
        for kind, names in entities.items():
            winners = by_name[kind] or (best_entities(names, full) if fallback else [])
            own_row.update(winners)
            named.update(by_name[kind])
            if winners:
                assigned_rows[(sheet, i)] = assigned_rows.get((sheet, i), []) + winners
    every_cell = TextInfo(" ; ".join(v for rows in sheets.values() for r in rows for v in r.values()))
    df_all = token_frequency(all_names)
    mentioned = {n for n in all_names if entity_score(n, every_cell, df_all) > 0}

    def share(found: set, names: List[str]) -> Optional[float]:
        return round(sum(1 for n in names if n in found) / len(names), 4) if names else None

    entity_block = {}
    for kind, names in entities.items():
        entity_block[kind] = {
            "n": len(names),
            "mentioned": share(mentioned, names),
            "own_row": share(own_row, names),
            "named_in_field": share(named & own_row, names),
            "missing": [n for n in names if n not in own_row][:12],
        }
    sample_rows = [(i, r) for i, r in enumerate(sheets["sample"]) if r]
    unassigned = sum(1 for i, _ in sample_rows if ("sample", i) not in assigned_rows)

    # Package fields on their package sheet.
    pkg = package_sheets()
    placed = misplaced = off_package = 0
    misplaced_examples = Counter()
    for sheet, rows in sheets.items():
        for row in rows:
            for field in row:
                if field in PARENT_ID_FIELDS.get(sheet, ()):
                    continue  # a reference to the parent row, not a misplaced field
                target = pkg.get(field)
                if target is None:
                    off_package += 1
                elif target == sheet:
                    placed += 1
                else:
                    misplaced += 1
                    misplaced_examples[f"{field}: {sheet} (package: {target})"] += 1

    # Links: a material sample is linked when an observation unit references it
    # (package direction) or it references an existing observation unit; an
    # assay is linked when it references an existing sample or observation unit.
    ids = {s: {r.get(PRIMARY_ID[s]) for r in sheets[s] if r.get(PRIMARY_ID[s])} for s in SHEETS}

    def refs(row: Dict[str, str], own: str) -> set:
        out = set()
        for f, v in row.items():
            if f.endswith("identifier") and f != own:
                out.update(p.strip() for p in re.split(r"[;,]\s*", v) if p.strip())
        return out

    ou_refs = set().union(*(refs(r, PRIMARY_ID["observationunit"]) for r in sheets["observationunit"])) \
        if sheets["observationunit"] else set()
    samples = [r for r in sheets["sample"] if r]
    assays = [r for r in sheets["assay"] if r]
    linkage = {
        "sample": round(sum(1 for r in samples if r.get("sample identifier") in ou_refs
                            or refs(r, "sample identifier") & ids["observationunit"]) / len(samples), 4)
        if samples else None,
        "assay": round(sum(1 for r in assays if refs(r, "assay identifier")
                           & (ids["sample"] | ids["observationunit"])) / len(assays), 4)
        if assays else None,
    }

    # Rows holding a result: is the row, or its nearest identifying parent,
    # about one expert material? (Same rule as value attachment.)
    index = RecordIndex(sheets)
    result_rows = [i for i, r in enumerate(sheets["assay"])
                   if any(r.get(f) and extract_quantities(r[f]) for f in RESULT_FIELDS)]
    linked = 0
    for i in result_rows:
        for level in _lineage(index, "assay", i):
            found = {row_material(index.sheets[s][j], s, kind, names)
                     for kind, names in entities.items() if names for s, j in level}
            if found - {None, _SEVERAL}:
                linked += 1
                break

    diag = structure_diagnostics(sheets)
    return {
        "entities": entity_block,
        "row_counts": diag["row_counts"],
        "duplicate_row_share": diag["duplicate_row_share"],
        "sample_rows_not_matching_expert_material": unassigned,
        "field_placement": {
            "on_package_sheet": round(placed / (placed + misplaced), 4) if placed + misplaced else None,
            "cells_package_fields": placed + misplaced,
            "cells_non_package_fields": off_package,
            "misplaced_examples": dict(misplaced_examples.most_common(6)),
        },
        "parent_link_rate": linkage,
        "result_rows": len(result_rows),
        "result_rows_linked_to_expert_material": round(linked / len(result_rows), 4) if result_rows else None,
    }


# ---------------------------------------------------------------------------
# Task 3: values
# ---------------------------------------------------------------------------

VALUE_GROUPS = ("material properties", "conditions", "results", "methods")


def _value_group(fact) -> Optional[str]:
    if fact["kind"] in ("entity", "entity_group"):
        return None  # material identity is scored under structure
    return "material properties" if fact["group"] == "materials" else fact["group"]


_NUMBER_RE = re.compile(r"(?<![\d.])\d+(?:\.\d+)?")


def source_numbers(text: str) -> set:
    """Every plain number in the parsed paper text, for telling text facts from figure-only facts."""
    return {float(x) for x in _NUMBER_RE.findall(text.replace(",", ""))}


def score_values(facts_doc: Dict[str, Any], sheets, source_text: Optional[str] = None) -> Dict[str, Any]:
    """``source_text`` is the parsed paper the run read. When given, each quantity fact
    records whether its value is in that text at all: values only drawn in a figure
    cannot be extracted from text and are reported apart from extraction misses."""
    index = RecordIndex(sheets)
    numbers = source_numbers(source_text) if source_text is not None else None
    entities = expert_entities(facts_doc)
    cat_cache: Dict[Tuple[str, str], set] = {}
    out = []
    for fact in facts_doc["facts"]:
        group = _value_group(fact)
        if group is None or fact["kind"] not in ("value", "result", "text", "category"):
            continue
        allowed = SLOT_SPEC[fact["slot"]]["fields"]
        if fact["kind"] in ("value", "result"):
            in_field, anywhere, hits = _quantity_fact(fact, index, allowed)
        elif fact["kind"] == "text":
            in_field, anywhere, hits = _text_fact(fact, index, allowed)
        else:
            if (fact["slot"], "s") not in cat_cache:
                cat_cache[(fact["slot"], "s")] = _predicted_categories(fact["slot"], index, allowed)
                cat_cache[(fact["slot"], "a")] = _all_categories(fact["slot"], index)
            want = set(fact["categories"])
            in_field = len(want & cat_cache[(fact["slot"], "s")]) / len(want)
            anywhere = len(want & cat_cache[(fact["slot"], "a")]) / len(want)
            hits = []
        attached = uncertainty = None
        if fact["kind"] in ("value", "result"):
            uncertainty = uncertainty_kept(fact, index, hits)
            if fact["entity_keys"] and in_field > 0:
                attached = attachment(fact["entity_keys"], index, hits, entities)
        in_source = None
        if numbers is not None and fact["kind"] in ("value", "result") and fact.get("quantities"):
            in_source = any(q["value"] in numbers for q in fact["quantities"])
        evidence = None
        if hits:
            s, i, f, v = hits[0]
            evidence = {"sheet": s, "row": i, "field": f, "value": v[:120]}
        out.append({"slot": fact["slot"], "group": group, "raw": fact["raw"][:120],
                    "entity_keys": fact["entity_keys"], "in_field": round(in_field, 3),
                    "anywhere": round(anywhere, 3), "attached": attached,
                    "uncertainty": uncertainty, "in_source": in_source, "evidence": evidence})
    groups = {}
    for group in VALUE_GROUPS:
        rows = [r for r in out if r["group"] == group]
        bound = [r for r in rows if r["attached"] is not None]
        with_error = [r for r in rows if r["uncertainty"] is not None]
        checked = [r for r in rows if r["in_source"] is not None]
        in_text = [r for r in checked if r["in_source"]]
        groups[group] = {
            "n": len(rows),
            "in_field": round(sum(r["in_field"] for r in rows) / len(rows), 4) if rows else None,
            "anywhere": round(sum(r["anywhere"] for r in rows) / len(rows), 4) if rows else None,
            "attached_of_found": round(sum(1 for r in bound if r["attached"]) / len(bound), 4) if bound else None,
            "n_entity_bound_found": len(bound),
            "uncertainty_kept_of_found": (round(sum(1 for r in with_error if r["uncertainty"]) / len(with_error), 4)
                                          if with_error else None),
            "n_with_uncertainty_found": len(with_error),
            "in_source_text": round(len(in_text) / len(checked), 4) if checked else None,
            "in_field_of_source_text": (round(sum(r["in_field"] for r in in_text) / len(in_text), 4)
                                        if in_text else None),
        }
    return {"by_group": groups, "facts": out}


# ---------------------------------------------------------------------------
# One record, all three tasks
# ---------------------------------------------------------------------------

def score_layers(facts_doc: Dict[str, Any], record: Optional[Dict[str, Any]],
                 source_text: Optional[str] = None) -> Dict[str, Any]:
    sheets = load_sheets(record) if record else {s: [] for s in SHEETS}
    used = packages_used(record) if record else []
    return {
        "document_id": facts_doc["document_id"],
        "output_present": record is not None,
        "packages_used": used,
        "petase_package_selected": any(PACKAGE_NAME in p for p in used),
        "fields": score_fields(facts_doc, sheets),
        "structure": score_structure(facts_doc, sheets),
        "values": score_values(facts_doc, sheets, source_text),
    }


def _mean(values: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Mean over papers (each paper weighs the same) for every metric of every task."""
    present = [r for r in results if r["output_present"]]
    fields = {
        "slot_recall": _mean([r["fields"]["slot_recall"] for r in results]),
        **{f"{g}_recall": _mean([r["fields"]["by_group"][g]["recall"] for r in results])
           for g in ("materials", "conditions", "results", "methods")},
        "na_slots_filled_per_paper": _mean([len(r["fields"]["na_slots_filled"]) for r in results]),
    }
    slot_recall = {}
    for slot in FIELD_TASK:
        hits = [r["fields"]["slots"][slot]["found"] for r in results if slot in r["fields"]["slots"]]
        if hits:
            slot_recall[slot] = {"n_papers": len(hits), "recall": round(sum(hits) / len(hits), 4)}
    st = [r["structure"] for r in results]
    structure = {}
    for kind in ("enzyme", "substrate"):
        for m in ("mentioned", "own_row", "named_in_field"):
            structure[f"{kind}_{m}"] = _mean([s["entities"][kind][m] for s in st])
    structure.update({
        "field_on_package_sheet": _mean([s["field_placement"]["on_package_sheet"] for s in st]),
        "sample_to_ou_link": _mean([s["parent_link_rate"]["sample"] for s in st]),
        "assay_to_sample_link": _mean([s["parent_link_rate"]["assay"] for s in st]),
        "result_rows_linked_to_material": _mean([s["result_rows_linked_to_expert_material"] for s in st]),
        "papers_with_result_rows": sum(1 for s in st if s["result_rows"]),
        "median_rows": {sh: sorted(s["row_counts"][sh] for s in st)[len(st) // 2] for sh in SHEETS} if st else {},
        "assay_duplicate_row_share": _mean([s["duplicate_row_share"]["assay"] for s in st]),
    })
    values = {}
    for g in VALUE_GROUPS:
        values[g] = {m: _mean([r["values"]["by_group"][g][m] for r in results])
                     for m in ("in_field", "anywhere", "attached_of_found", "uncertainty_kept_of_found",
                               "in_source_text", "in_field_of_source_text")}
    return {
        "n_documents": len(results),
        "n_outputs_present": len(present),
        "petase_package_selected": sum(1 for r in present if r["petase_package_selected"]),
        "fields": fields,
        "fields_by_slot": slot_recall,
        "structure": structure,
        "values": values,
    }
