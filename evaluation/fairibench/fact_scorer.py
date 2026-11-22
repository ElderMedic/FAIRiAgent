"""Score an ISA-structured metadata record against expert facts.

Unit of scoring is one expert fact (see ``petase_facts.py``), never a
converter-made row. The scorer is layout-agnostic: it does not care how many
observation units, samples or assays a system creates, or whether a result
sits in a wide column (``enzyme melting temperature``) or in the long layout
(``measurement value`` + ``reported parameter name``). It asks three
deterministic questions per fact:

1. **Value**: does a field that the package designates for this slot hold
   the reported number (unit-aware) or category?  -> ``structured``.
   A wide result column belongs to one slot (a Km in the ``kcat`` column is
   misplaced); a long-layout value counts only when its parameter name
   matches the slot. Found only in some other field (notes, names,
   descriptions)? -> ``unstructured``. Otherwise ``missing``.
2. **Entity**: when the expert tied the value to a material (an enzyme
   variant or a substrate), is the row that holds it about that material?
   The closest row (the value's own row, then its parents) whose identity
   fields single out one of the paper's materials decides; study and
   investigation rows and rows listing several materials decide nothing.
   -> ``attached``.
3. **Unit**: numbers that match while the predicted unit is absent or not
   comparable get half credit (``unit_unverified``) in a designated field.
   Elsewhere a number without a comparable unit counts only next to the
   slot's parameter name (``kcat = 40.3``), never as a bare number.
4. **Error term**: when the expert value carries ``± x``, is ``x`` kept with
   the found value (same cell, or the row's uncertainty field)?
   -> ``uncertainty``; reported beside the score, not folded into it.

A change stated relative to another value ("Ca2+ raised Tm by 6.4 °C")
matches either the change itself or the resulting absolute value.

Two checks need no reference at all and are reported separately:
literal source support of predicted numbers (a precision proxy) and
values placed in slots the experts marked as not reported (``na_conflicts``).
"""

from __future__ import annotations

import hashlib
import random
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from evaluation.fairibench.materials import (
    TextInfo,
    _WT_RE,
    _alias_tokens,
    best_entities,
    expert_entities,
    mutations,
)
from evaluation.fairibench.petase_facts import (
    FIELD_TASK,
    HPLC_RE,
    LONG_PARAM_FALLBACK,
    LONG_PARAM_FIELDS,
    LONG_VALUE_FIELDS,
    _NUM,
    PRIMARY_KINDS,
    RESULT_FIELDS,
    SLOT_SPEC,
    _MUTATION_RE,
    _entity_tokens,
    categories_for,
    extract_quantities,
    informative_tokens,
    quantities_match,
    unit_signature,
)

SHEETS = ("investigation", "study", "observationunit", "sample", "assay")
PRIMARY_ID = {
    "investigation": "investigation identifier",
    "study": "study identifier",
    "observationunit": "observation unit identifier",
    "sample": "sample identifier",
    "assay": "assay identifier",
}
# Units implied by the package definition of a field.
FIELD_UNITS = {
    "reaction temperature": "°C",
    "agitation rate": "rpm",
    "enzyme melting temperature": "°C",
    "half inactivation temperature": "°C",
    "pet glass transition temperature": "°C",
    "pet crystallinity": "%",
    "pet depolymerisation percentage": "%",
    "uv detection wavelength": "nm",
    "fluorescence excitation wavelength": "nm",
    "fluorescence emission wavelength": "nm",
}
STATUS_SCORE = {"match": 1.0, "unit_unverified": 0.5, "none": 0.0}
WT_ALIASES = ("wt", "wild", "wildtype", "wild-type", "wild type")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _norm_field(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).replace("_", " ")).strip().lower()


def _norm_sheet(name: str) -> Optional[str]:
    key = re.sub(r"[^a-z]", "", str(name).lower())
    return key if key in SHEETS else None


def load_sheets(record: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
    """Accept a FAIRiAgent ``metadata.json``, a values-GT v3 file, or a bare
    ``{sheet: [rows]}`` mapping."""
    container = (record.get("isa_structure") or record.get("isa_sheets")
                 or record.get("isa_values") or record)
    sheets: Dict[str, List[Dict[str, str]]] = {s: [] for s in SHEETS}
    for raw_name, block in container.items():
        sheet = _norm_sheet(raw_name)
        if sheet is None:
            continue
        rows = block
        if isinstance(block, dict):
            rows = block.get("rows", block.get("expected_rows", []))
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            clean = {}
            for field, value in row.items():
                if value is None or isinstance(value, (dict, list)):
                    if isinstance(value, list):
                        value = "; ".join(str(v) for v in value if v not in (None, ""))
                    else:
                        continue
                text = str(value).strip()
                if text:
                    clean[_norm_field(field)] = text
            sheets[sheet].append(clean)
    return sheets


# ---------------------------------------------------------------------------
# Row context (the row plus its parents, for entity attachment)
# ---------------------------------------------------------------------------

class RecordIndex:
    def __init__(self, sheets: Dict[str, List[Dict[str, str]]]):
        self.sheets = sheets
        self.by_id: Dict[str, Tuple[str, int]] = {}
        for sheet, rows in sheets.items():
            pid = PRIMARY_ID[sheet]
            for i, row in enumerate(rows):
                if row.get(pid):
                    self.by_id.setdefault(row[pid], (sheet, i))
        self.cells: List[Tuple[str, int, str, str]] = [
            (sheet, i, field, value)
            for sheet, rows in sheets.items()
            for i, row in enumerate(rows)
            for field, value in row.items()
        ]
        # Parsed once per record: (cell, quantities, implied unit)
        self.quantity_cells = []
        for cell in self.cells:
            sheet, i, field, value = cell
            if field.endswith("identifier") and field != "result material identifier":
                continue
            qs = extract_quantities(value)
            if qs:
                self.quantity_cells.append((cell, qs, _implied_unit(self, sheet, i, field)))



# ---------------------------------------------------------------------------
# Which material a row is about (value attachment)
# ---------------------------------------------------------------------------

NAMING_FIELDS = (
    "enzyme type", "enzyme mutation", "enzyme identifier", "enzyme construct description",
    "pet substrate type", "substrate identifier", "substrate form factor", "pet substrate source",
    "material composition", "material preparation identifier", "sample name", "sample identifier",
    "experimental subject name", "observation unit name", "observation unit identifier",
)
# Fields that state what material a row is, before any free-text name.
IDENTITY_FIELDS = {
    "enzyme": ("enzyme type", "enzyme mutation", "enzyme identifier"),
    "substrate": ("pet substrate type", "substrate identifier", "pet substrate source",
                  "substrate form factor"),
}
MATERIAL_SHEETS = ("observationunit", "sample", "assay")
_SEVERAL = "<several>"


def _row_text(row: Dict[str, str], sheet: str, fields: Optional[Iterable[str]] = None) -> str:
    own_id = PRIMARY_ID[sheet]
    keep = set(fields) if fields is not None else None
    parts = []
    for f, v in row.items():
        if keep is not None and f not in keep:
            continue
        if f.endswith("identifier") and f != own_id and f not in NAMING_FIELDS:
            continue
        parts.append(v)
    return " ; ".join(parts)


def _lineage(index: "RecordIndex", sheet: str, i: int, max_depth: int = 4):
    """Rows reachable from (sheet, i) through identifier links, nearest first,
    as one list per distance. Study and investigation rows are left out: they
    describe the whole study, not one material."""
    seen, frontier = {(sheet, i)}, [(sheet, i)]
    for _depth in range(max_depth):
        if not frontier:
            return
        yield frontier
        nxt = []
        for s, j in frontier:
            for f, v in index.sheets[s][j].items():
                if f == PRIMARY_ID[s] or not f.endswith("identifier"):
                    continue
                for part in re.split(r"[;,]\s*", v):
                    target = index.by_id.get(part.strip())
                    if target and target not in seen and target[0] in MATERIAL_SHEETS:
                        seen.add(target)
                        nxt.append(target)
        frontier = nxt


def _sole_wild_type(names: Sequence[str]) -> Optional[str]:
    marked = [n for n in names if _WT_RE.search(n) and not mutations(n)]
    if len(marked) == 1:
        return marked[0]
    plain = [n for n in names if not mutations(n)]
    return plain[0] if len(plain) == 1 and len(names) > 1 else None


def resolve_key(key: str, entities: Dict[str, List[str]]) -> Optional[Tuple[str, str]]:
    """The expert material an annotation key (``Q132A_T101A``, ``WT``,
    ``GF-PET_initial``) stands for, as (kind, name); None if not one material."""
    text = key.replace("_", " ")
    info = TextInfo(text)
    for kind, names in entities.items():
        winners = best_entities(names, info, max_tied=1) if names else []
        if winners:
            return kind, winners[0]
    if _WT_RE.search(text) and not mutations(text):
        wild = _sole_wild_type(entities.get("enzyme", []))
        if wild:
            return "enzyme", wild
    return None


def row_material(row: Dict[str, str], sheet: str, kind: str, names: Sequence[str]) -> Optional[str]:
    """The one material of ``kind`` this row is about, ``_SEVERAL`` when it
    names more than one, None when it names none. Identity fields are read
    first, then naming fields, then the row without its notes."""
    wild = _sole_wild_type(names)
    # Free-text notes often list every material of the paper; they never say
    # which one the row is about.
    described = [f for f in row if not f.endswith("notes")]
    # Each identity field on its own first: the name "IsPETaseTM^K95N/F201I"
    # singles out a variant whose full mutation list (parent's plus its own)
    # would also fit the parent when the fields are read together.
    singles = [(f,) for f in IDENTITY_FIELDS[kind]]
    for fields in (*singles, IDENTITY_FIELDS[kind], NAMING_FIELDS, described):
        text = _row_text(row, sheet, fields)
        if not text:
            continue
        info = TextInfo(text)
        winners = best_entities(names, info, max_tied=len(names))
        if len(winners) == 1:
            return winners[0]
        if winners and fields in singles:
            continue  # one field alone is ambiguous: read the fields together
        if winners:
            return _SEVERAL
        # Wild type: stated as such, or the parent named without any mutation.
        if wild and not info.muts and (info.wt or (
                fields is not described and any(t in info.toks for t in _alias_tokens(wild)))):
            return wild
    return None


def attachment(entity_keys: Sequence[str], index: "RecordIndex", hits,
               entities: Dict[str, List[str]]) -> bool:
    """Whether some hit sits on a row about every material the expert tied
    the value to. The nearest row that singles out one material of the key's
    kind decides; keys that are not one expert material fall back to being
    named in the row or its material parents."""
    for sheet, i, _f, _v in hits:
        ok = True
        for key in entity_keys:
            resolved = resolve_key(key, entities)
            if resolved is None:
                text = " ".join(_row_text(index.sheets[s][j], s)
                                for level in _lineage(index, sheet, i) for s, j in level)
                ok = entity_in_text(key, text)
            else:
                kind, target = resolved
                ok = False
                for level in _lineage(index, sheet, i):
                    found = {row_material(index.sheets[s][j], s, kind, entities[kind]) for s, j in level}
                    found.discard(None)
                    found.discard(_SEVERAL)
                    if found:
                        ok = found == {target}
                        break
            if not ok:
                break
        if ok:
            return True
    return False


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower().replace("µ", "u"))


def _mutations(text: str) -> set:
    return {t.upper() for t in re.split(r"[^A-Za-z0-9]+", text) if _MUTATION_RE.match(t.upper())}


def entity_in_text(entity: str, text: str) -> bool:
    """Whether ``text`` names the material ``entity`` (deterministic)."""
    ent_toks = _entity_tokens(entity)
    muts = {t.upper() for t in ent_toks if _MUTATION_RE.match(t.upper())}
    text_muts = _mutations(text)
    if muts and not muts <= text_muts:
        return False
    low = text.lower()
    text_tokens = set(informative_tokens(text))
    is_wt = any(t in ("wt", "wild", "wildtype") for t in ent_toks)
    if is_wt and not any(re.search(rf"\b{re.escape(a)}\b", low) for a in WT_ALIASES):
        return False
    rest = [t for t in ent_toks if t.upper() not in muts and t not in ("wt", "wild", "wildtype", "type")]
    if not rest:
        return True
    flat = _alnum(text)
    hits = sum(1 for t in rest if (t in text_tokens) or (len(t) > 3 and _alnum(t) in flat))
    return hits / len(rest) >= 0.5 or (bool(muts) and hits >= 1) or (is_wt and hits >= 1)


# ---------------------------------------------------------------------------
# Matching one fact
# ---------------------------------------------------------------------------

def _implied_unit(index: RecordIndex, sheet: str, i: int, field: str) -> str:
    row = index.sheets[sheet][i]
    if field in FIELD_UNITS:
        return FIELD_UNITS[field]
    if field in RESULT_FIELDS or field.startswith("measurement"):
        return row.get("measurement unit", "") or row.get("activity unit", "")
    return ""


def _param_text(row: Dict[str, str], field: str) -> str:
    text = " ".join(row.get(f, "") for f in LONG_PARAM_FIELDS).strip()
    if field == "reported measurement":
        text = f"{text} {row.get(field, '')}"
    return (text.strip() or row.get(LONG_PARAM_FALLBACK, "")).lower().replace("_", " ")


# Experts file activity outputs (TPA released, % depolymerised, rates) under
# either slot; for values the two share their fields. The fields task keeps
# them apart.
_SHARED_SLOTS = {"kinetics.specific_activity": "kinetics.initial_rate",
                 "kinetics.initial_rate": "kinetics.specific_activity"}


def named_parameters(param: str) -> set:
    """Kinetic slots a long-layout parameter name refers to; the two activity
    slots count as one."""
    slots = {s for s, (_wide, regex) in FIELD_TASK.items()
             if s.startswith("kinetics.") and regex and re.search(regex, param)}
    return {"kinetics.initial_rate" if s in _SHARED_SLOTS else s for s in slots}


def designates(slot: str, param: str, shared: bool = True) -> bool:
    """Whether a long-layout parameter name designates ``slot``. A row listing
    several kinetic parameters at once ("Km, Vmax, kcat") designates none; one
    name that happens to match two patterns ("turnover rate") still does."""
    slots = (slot, _SHARED_SLOTS.get(slot)) if shared else (slot,)
    regexes = [FIELD_TASK[s][1] for s in slots if s in FIELD_TASK and FIELD_TASK[s][1]]
    if not any(re.search(r, param) for r in regexes):
        return False
    listed = re.search(r"[,;/]|\band\b", param)
    return not (slot.startswith("kinetics.") and listed and len(named_parameters(param)) > 1)


def slot_accepts(slot: str, allowed: Iterable[str], row: Dict[str, str], field: str) -> bool:
    """Whether ``field`` of ``row`` is a designated place for a value of ``slot``."""
    specs = [FIELD_TASK[s] for s in (slot, _SHARED_SLOTS.get(slot)) if s in FIELD_TASK]
    if field in LONG_VALUE_FIELDS:
        if field not in allowed:
            return False
        return designates(slot, _param_text(row, field))
    if field in RESULT_FIELDS:  # a wide result column belongs to one slot
        return any(field in wide for wide, _regex in specs)
    return field in allowed


_DELTA_RE = re.compile(
    r"\b(?P<verb>increas|rais|improv|enhanc|elevat|shift|decreas|reduc|lower|drop)\w*"
    r"[^;.]{0,40}?\bby\s*(?:~|about|approximately|approx\.?)?\s*$", re.I)
_NEGATIVE_VERBS = ("decreas", "reduc", "lower", "drop")


def reference_alternatives(fact: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    """Per reference quantity, the quantities that count as reporting it."""
    qs = fact["quantities"]
    raw = fact["raw"]
    out = []
    for k, q in enumerate(qs):
        alts = [q]
        number = re.match(r"-?\d+(?:\.\d+)?", q["raw"])
        if k > 0 and number:
            for m in re.finditer(re.escape(number.group(0)), raw):
                delta = _DELTA_RE.search(raw[max(0, m.start() - 80):m.start()])
                if delta:
                    sign = -1.0 if delta.group("verb").lower() in _NEGATIVE_VERBS else 1.0
                    base = qs[0]
                    alts.append({"value": base["value"] + sign * q["value"], "unit": base["unit"],
                                 "raw": f"{base['raw']} {'-' if sign < 0 else '+'} {q['raw']}"})
                    break
        out.append(alts)
    return out


def _labelled(text: str, quantities, param_re: str) -> bool:
    """Whether a number in free text carries the slot's parameter name just
    before it ("kcat = 40.3", "Km of 16.78")."""
    if not param_re:
        return False
    low = text.lower()
    for q in quantities:
        number = re.match(r"-?\d+(?:\.\d+)?", q["raw"])
        if not number:
            continue
        for m in re.finditer(rf"(?<![\w.]){re.escape(number.group(0))}(?![\d.]\d)", low):
            if re.search(param_re, low[max(0, m.start() - 30):m.start()]):
                return True
    return False


def _quantity_fact(fact, index: RecordIndex, allowed: Sequence[str]):
    """Best match per reference quantity: in a designated field, and anywhere."""
    allowed_set = set(allowed)
    slot = fact["slot"]
    param_re = "|".join(FIELD_TASK[s][1] for s in (slot, _SHARED_SLOTS.get(slot))
                        if s in FIELD_TASK and FIELD_TASK[s][1])
    structured, anywhere = [], []
    hits: List[Tuple[str, int, str, str]] = []
    for refs in reference_alternatives(fact):
        s_best, a_best = 0.0, 0.0
        for cell, qs, implied in index.quantity_cells:
            sheet, i, field, value = cell
            status, matched = "none", None
            for pq in qs:
                for ref in refs:
                    st = quantities_match(ref, pq, implied_unit=implied)
                    if STATUS_SCORE[st] > STATUS_SCORE[status]:
                        status, matched = st, pq
            if status == "none":
                continue
            placed = slot_accepts(slot, allowed_set, index.sheets[sheet][i], field)
            if status != "match" and not placed and not _labelled(value, [matched], param_re):
                continue  # a bare number outside the slot's fields is no evidence
            score = STATUS_SCORE[status]
            a_best = max(a_best, score)
            if placed:
                s_best = max(s_best, score)
                hits.append(cell)
        structured.append(s_best)
        anywhere.append(a_best)
    n = max(1, len(fact["quantities"]))
    return sum(structured) / n, sum(anywhere) / n, hits


# ---------------------------------------------------------------------------
# Error terms
# ---------------------------------------------------------------------------

_PLUS_MINUS_RE = re.compile(rf"(?<![\d.])({_NUM})\s*(?:±|\+/-|\+-)\s*\(?({_NUM})\)?")
UNCERTAINTY_FIELDS = ("measurement uncertainty value", "measurement uncertainty")


def plus_minus(text: str) -> Dict[float, float]:
    """``{value: error}`` for every ``value ± error`` in ``text``."""
    return {float(a): float(b) for a, b in _PLUS_MINUS_RE.findall(str(text).replace("−", "-"))}


def _close(a: float, b: float, rel_tol: float = 0.02) -> bool:
    return a == b or (a and b and abs(a - b) / max(abs(a), abs(b)) <= rel_tol)


def uncertainty_kept(fact: Dict[str, Any], index: "RecordIndex", hits) -> Optional[bool]:
    """None when the expert value has no error term or the value was not found
    in a designated field; otherwise whether every error term is kept with it."""
    reference = plus_minus(fact["raw"])
    if not reference or not hits:
        return None
    for sheet, i, _field, value in hits:
        row = index.sheets[sheet][i]
        stated = plus_minus(value)
        separate = [q["value"] for f in UNCERTAINTY_FIELDS for q in extract_quantities(row.get(f, ""))]
        if all(any(_close(v, sv) and _close(err, se) for sv, se in stated.items())
               or any(_close(err, x) for x in separate)
               for v, err in reference.items()):
            return True
    return False


def _entity_fact(name: str, index: RecordIndex, allowed: Sequence[str]):
    allowed_set = set(allowed)
    structured, anywhere, hits = 0.0, 0.0, []
    for cell in index.cells:
        sheet, i, field, value = cell
        if sheet not in ("observationunit", "sample", "assay"):
            continue
        if not entity_in_text(name, value):
            continue
        anywhere = 1.0
        if field in allowed_set:
            structured = 1.0
            hits.append(cell)
    return structured, anywhere, hits


def _text_fact(fact, index: RecordIndex, allowed: Sequence[str]):
    allowed_set = set(allowed)
    sig = unit_signature(fact["raw"]) if fact["slot"] == "methods.activity_units" else None
    ref = informative_tokens(fact["raw"])
    structured = anywhere = 0.0
    hits = []
    for cell in index.cells:
        sheet, i, field, value = cell
        if field.endswith("identifier"):
            continue
        score = 0.0
        if sig and unit_signature(value) and unit_signature(value)[0] == sig[0]:
            score = 1.0
        elif ref:
            flat = _alnum(value)
            got = sum(1 for t in ref if _alnum(t) and _alnum(t) in flat)
            ratio = got / len(ref)
            score = 1.0 if ratio >= 0.5 else (0.5 if ratio >= 0.25 else 0.0)
        if not score:
            continue
        anywhere = max(anywhere, score)
        if field in allowed_set:
            if score > structured:
                structured = score
            hits.append(cell)
    return structured, anywhere, hits


def _predicted_categories(slot: str, index: RecordIndex, fields: Iterable[str]) -> set:
    cats = set()
    fields = set(fields)
    for sheet, i, field, value in index.cells:
        if field not in fields:
            continue
        if slot == "methods.quantification":
            if field.startswith("fluorescence"):
                cats.add("fluorescence")
                continue
            if field == "uv detection wavelength":
                cats.add("absorbance")
                continue
        if slot == "methods.substrate_kind":
            low = value.lower()
            if "proxy" in low:
                cats.add("proxy_substrate")
            if "actual" in low or low in ("pet", "actual_pet"):
                cats.add("actual_pet")
            continue
        if slot == "methods.hplc":
            if HPLC_RE.search(value.lower()):
                cats.add("hplc_yes")
            continue
        cats.update(categories_for(slot, value))
    if slot == "methods.hplc" and "hplc_yes" not in cats:
        has_method = any(f in fields for _s, _i, f, _v in index.cells)
        if has_method:
            cats.add("hplc_no")
    return cats


def _all_categories(slot: str, index: RecordIndex) -> set:
    every = {f for _s, _i, f, _v in index.cells}
    return _predicted_categories(slot, index, every)


def score_record(facts_doc: Dict[str, Any], record: Optional[Dict[str, Any]],
                 source_text: Optional[str] = None) -> Dict[str, Any]:
    """Score one record. ``record=None`` scores a missing output (all zero)."""
    sheets = load_sheets(record) if record else {s: [] for s in SHEETS}
    index = RecordIndex(sheets)
    entities = expert_entities(facts_doc)
    cat_cache: Dict[Tuple[str, str], set] = {}
    results = []
    for fact in facts_doc["facts"]:
        if fact["kind"] not in PRIMARY_KINDS:
            continue
        spec = SLOT_SPEC[fact["slot"]]
        allowed = spec["fields"]
        attached: Optional[bool] = None
        uncertainty: Optional[bool] = None
        if fact["kind"] in ("value", "result"):
            structured, anywhere, hits = _quantity_fact(fact, index, allowed)
        elif fact["kind"] == "entity":
            structured, anywhere, hits = _entity_fact(fact["raw"], index, allowed)
        elif fact["kind"] == "entity_group":
            found = [_entity_fact(m, index, allowed) for m in fact["members"]]
            structured = sum(f[0] for f in found) / len(found)
            anywhere = sum(f[1] for f in found) / len(found)
            hits = [h for f in found for h in f[2]]
        elif fact["kind"] == "text":
            structured, anywhere, hits = _text_fact(fact, index, allowed)
        else:  # category
            key_s, key_a = (fact["slot"], "s"), (fact["slot"], "a")
            if key_s not in cat_cache:
                cat_cache[key_s] = _predicted_categories(fact["slot"], index, allowed)
                cat_cache[key_a] = _all_categories(fact["slot"], index)
            want = set(fact["categories"])
            structured = len(want & cat_cache[key_s]) / len(want)
            anywhere = len(want & cat_cache[key_a]) / len(want)
            hits = []
        if fact["kind"] in ("value", "result"):
            uncertainty = uncertainty_kept(fact, index, hits)
            if fact["entity_keys"]:
                attached = attachment(fact["entity_keys"], index, hits, entities) if structured > 0 else False
        strict = structured * (1.0 if attached in (None, True) else 0.0)
        status = "structured" if structured > 0 else ("unstructured" if anywhere > 0 else "missing")
        evidence = None
        if hits:
            s, i, f, v = hits[0]
            evidence = {"sheet": s, "row": i, "field": f, "value": v[:160]}
        results.append({
            "fact_id": fact["fact_id"], "slot": fact["slot"], "group": fact["group"],
            "kind": fact["kind"], "raw": fact["raw"][:160],
            "entity_keys": fact["entity_keys"], "status": status,
            "structured": round(structured, 3), "anywhere": round(anywhere, 3),
            "attached": attached, "uncertainty": uncertainty,
            "strict": round(strict, 3), "evidence": evidence,
        })

    def mean(values: List[float]) -> Optional[float]:
        return round(sum(values) / len(values), 4) if values else None

    by_group = {}
    for group in ("materials", "conditions", "results", "methods"):
        rows = [r for r in results if r["group"] == group]
        by_group[group] = {
            "n": len(rows),
            "strict": mean([r["strict"] for r in rows]),
            "structured": mean([r["structured"] for r in rows]),
            "anywhere": mean([r["anywhere"] for r in rows]),
        }
    bound = [r for r in results if r["attached"] is not None]
    found_bound = [r for r in bound if r["structured"] > 0]
    with_error = [r for r in results if r["uncertainty"] is not None]

    na_conflicts = []
    for slot in facts_doc.get("na_slots", []):
        for field in SLOT_SPEC.get(slot, {}).get("na_fields", ()):
            for sheet, i, f, v in index.cells:
                if f == field and extract_quantities(v):
                    na_conflicts.append({"slot": slot, "field": f, "value": v[:80]})

    return {
        "document_id": facts_doc["document_id"],
        "output_present": record is not None,
        "n_facts": len(results),
        "scores": {
            "strict": mean([r["strict"] for r in results]),
            "structured": mean([r["structured"] for r in results]),
            "anywhere": mean([r["anywhere"] for r in results]),
            "entity_attachment_rate": (
                round(sum(1 for r in found_bound if r["attached"]) / len(found_bound), 4)
                if found_bound else None),
            "n_entity_bound": len(bound),
            # of found values whose expert value carries ± x: share keeping x
            "uncertainty_kept_rate": (
                round(sum(1 for r in with_error if r["uncertainty"]) / len(with_error), 4)
                if with_error else None),
            "n_with_uncertainty_found": len(with_error),
        },
        "by_group": by_group,
        "na_conflicts": na_conflicts,
        "diagnostics": structure_diagnostics(sheets),
        "source_support": source_support(sheets, source_text) if source_text else None,
        "facts": results,
    }


# ---------------------------------------------------------------------------
# Reference-free checks
# ---------------------------------------------------------------------------

_SOURCE_NUM_RE = re.compile(r"(?<![\d.])\d+(?:\.\d+)?")


def _numbers_in(text: str) -> set:
    return {round(float(m), 6) for m in _SOURCE_NUM_RE.findall(text.replace(",", ""))}


def source_support(sheets: Dict[str, List[Dict[str, str]]], source_text: str) -> Dict[str, Any]:
    """Share of predicted numeric condition/result cells whose numbers occur
    literally in the source (tables included). Conversions count as
    unsupported, so this is a lower bound on grounding."""
    fields = set(RESULT_FIELDS)
    for spec in SLOT_SPEC.values():
        if spec["kind"] in ("value", "result"):
            fields.update(spec["fields"])
    available = _numbers_in(source_text)
    checked = supported = 0
    unsupported = []
    for sheet, rows in sheets.items():
        for row in rows:
            for field, value in row.items():
                if field not in fields:
                    continue
                qs = extract_quantities(value)
                if not qs:
                    continue
                checked += 1
                if all(round(q["value"], 6) in available or round(abs(q["value"]), 6) in available
                       for q in qs):
                    supported += 1
                elif len(unsupported) < 25:
                    unsupported.append({"sheet": sheet, "field": field, "value": value[:80]})
    return {
        "checked_cells": checked,
        "supported_cells": supported,
        "support_rate": round(supported / checked, 4) if checked else None,
        "unsupported_examples": unsupported,
    }


def structure_diagnostics(sheets: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    counts = {s: len(rows) for s, rows in sheets.items()}
    dup = {}
    for sheet, rows in sheets.items():
        # Ignore the row's own identifier and free-text labels, but keep its
        # parent link: the same conditions on two different samples are two
        # assays, not a duplicate.
        own = {"observationunit": "observation unit identifier"}.get(sheet, f"{sheet} identifier")
        keys = [
            tuple(sorted((f, v) for f, v in row.items()
                         if f != own and f not in ("assay name", "sample name",
                                                                       "observation unit name",
                                                                       "assay description",
                                                                       "sample description",
                                                                       "observation unit description")))
            for row in rows
        ]
        c = Counter(keys)
        dup[sheet] = round(sum(n - 1 for n in c.values()) / len(rows), 4) if rows else 0.0
    return {"row_counts": counts, "duplicate_row_share": dup}


# ---------------------------------------------------------------------------
# Corpus aggregation
# ---------------------------------------------------------------------------

# Headline groups carry paper-specific values. Method questions are near
# binary (actual PET or proxy, endpoint or time-resolved), so chance agreement
# is high; they are reported on their own, never in the headline.
HEADLINE_GROUPS = ("materials", "conditions", "results")


def _doc_mean(doc: Dict[str, Any], metric: str, groups: Sequence[str]) -> Optional[float]:
    values = [f[metric] for f in doc["facts"] if f["group"] in groups]
    return sum(values) / len(values) if values else None


def aggregate(doc_results: List[Dict[str, Any]], n_boot: int = 2000, seed: int = 20261117) -> Dict[str, Any]:
    """Headline: mean over papers of the per-paper strict fact recall on
    materials, conditions and results (each paper weighs the same), with a
    paper-level bootstrap 95% interval. Micro means over facts, per-group and
    per-slot breakdowns follow."""
    out: Dict[str, Any] = {"n_documents": len(doc_results),
                           "n_outputs_present": sum(1 for d in doc_results if d["output_present"]),
                           "n_facts": sum(d["n_facts"] for d in doc_results),
                           "headline_groups": list(HEADLINE_GROUPS)}
    for metric in ("strict", "structured", "anywhere"):
        per_doc = [m for m in (_doc_mean(d, metric, HEADLINE_GROUPS) for d in doc_results) if m is not None]
        facts = [f[metric] for d in doc_results for f in d["facts"] if f["group"] in HEADLINE_GROUPS]
        rng = random.Random(seed)
        boots = []
        for _ in range(n_boot if len(per_doc) > 1 else 0):
            sample = [per_doc[rng.randrange(len(per_doc))] for _ in per_doc]
            boots.append(sum(sample) / len(sample))
        boots.sort()
        out[metric] = {
            "macro": round(sum(per_doc) / len(per_doc), 4) if per_doc else None,
            "micro": round(sum(facts) / len(facts), 4) if facts else None,
            "macro_ci95": [round(boots[int(0.025 * len(boots))], 4),
                           round(boots[int(0.975 * len(boots)) - 1], 4)] if boots else None,
        }
    groups = defaultdict(list)
    for d in doc_results:
        for f in d["facts"]:
            groups[f["group"]].append(f)
    out["by_group_micro"] = {
        g: {"n": len(fs),
            "strict": round(sum(f["strict"] for f in fs) / len(fs), 4),
            "structured": round(sum(f["structured"] for f in fs) / len(fs), 4),
            "anywhere": round(sum(f["anywhere"] for f in fs) / len(fs), 4)}
        for g, fs in sorted(groups.items())
    }
    slots = defaultdict(list)
    for d in doc_results:
        for f in d["facts"]:
            slots[f["slot"]].append(f)
    out["by_slot_micro"] = {
        s: {"n": len(fs), "strict": round(sum(f["strict"] for f in fs) / len(fs), 4),
            "structured": round(sum(f["structured"] for f in fs) / len(fs), 4),
            "anywhere": round(sum(f["anywhere"] for f in fs) / len(fs), 4)}
        for s, fs in sorted(slots.items())
    }
    bound = [f for d in doc_results for f in d["facts"] if f["attached"] is not None and f["structured"] > 0]
    out["entity_attachment_rate"] = (round(sum(1 for f in bound if f["attached"]) / len(bound), 4)
                                     if bound else None)
    with_error = [f for d in doc_results for f in d["facts"] if f.get("uncertainty") is not None]
    out["uncertainty_kept_rate"] = (round(sum(1 for f in with_error if f["uncertainty"]) / len(with_error), 4)
                                    if with_error else None)
    support = [d["source_support"] for d in doc_results if d.get("source_support")]
    if support:
        checked = sum(s["checked_cells"] for s in support)
        out["source_support_rate"] = round(sum(s["supported_cells"] for s in support) / checked, 4) if checked else None
    out["na_conflicts"] = sum(len(d["na_conflicts"]) for d in doc_results)
    return out


def file_sha256(path) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()
