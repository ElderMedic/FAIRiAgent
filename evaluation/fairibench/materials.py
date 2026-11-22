"""Which expert material (enzyme variant, substrate) a piece of text names.

Shared by the structure task (does a material get its own row) and value
attachment (is a result on its material's row). Deterministic: mutation sets
must agree, wild type must be named as such, and a name token shared by
several of a paper's materials (``LCC`` in ``LCC ICCG``) identifies none.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

_TOKEN_SPLIT = re.compile(r"[\s,;:()\[\]{}/|]+")
_MUT_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]\d{1,4}[A-Z])(?![A-Za-z0-9])")
_WT_RE = re.compile(r"\b(wt|wild[- ]?type|wildtype|wild)\b", re.I)
_STOP = {
    "pet", "variant", "variants", "enzyme", "protein", "mutant", "mutants", "the", "of", "from",
    "and", "with", "in", "a", "an", "by", "expressed", "commercial", "sample", "substrate",
    "material", "type", "wt", "wild", "wildtype", "wild-type", "or", "for", "on", "as", "used",
}


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower().replace("µ", "u"))


def mutations(text: str) -> frozenset:
    return frozenset(_MUT_RE.findall(text.replace("_", " ")))


def entity_aliases(name: str) -> List[str]:
    out = []
    for part in re.split(r"\s+/\s+|\s*;\s*", name):
        part = part.strip()
        if not part:
            continue
        head, sep, tail = part.partition(":")
        if sep and len(head.split()) <= 3:
            out.extend([head.strip(), tail.strip()])
        else:
            out.append(part)
        for code in re.findall(r"\(([^()]{2,20})\)", part):
            out.append(code.strip())
        if "," in part:
            out.append(part.split(",", 1)[0].strip())
    return [a for a in dict.fromkeys(out) if a]


class TextInfo:
    __slots__ = ("muts", "toks", "flat", "wt")

    def __init__(self, text: str):
        self.muts = mutations(text)
        self.toks = {_alnum(t) for t in _TOKEN_SPLIT.split(text) if _alnum(t)}
        self.flat = _alnum(text)
        self.wt = bool(_WT_RE.search(text))


def _alias_tokens(alias: str) -> List[str]:
    toks = [_alnum(t) for t in _TOKEN_SPLIT.split(_WT_RE.sub(" ", alias))]
    return [t for t in dict.fromkeys(toks) if t and t not in _STOP and not t.isdigit()]


def token_frequency(names: Sequence[str]) -> Counter:
    """In how many of a paper's materials each name token occurs; a token
    shared by several materials (``LCC`` in ``LCC ICCG``) does not identify one."""
    df: Counter = Counter()
    for name in names:
        df.update({t for a in entity_aliases(name) if not mutations(a) for t in _alias_tokens(a)})
    return df


def _alias_score(alias: str, info: TextInfo, df: Optional[Counter] = None) -> float:
    a_muts = mutations(alias)
    if a_muts:
        if a_muts == info.muts:
            return 20.0 + len(a_muts)
        return 10.0 + len(a_muts) if a_muts <= info.muts else 0.0
    is_wt = bool(_WT_RE.search(alias))
    if is_wt and not info.wt:
        return 0.0
    toks = _alias_tokens(alias)
    if not toks:
        return 1.0 if is_wt else 0.0
    hit = [t for t in toks if t in info.toks or (len(t) >= 4 and t in info.flat)]
    distinctive = [t for t in toks if not df or df[t] <= 1]
    hit_d = [t for t in hit if t in distinctive]
    hit_s = len(hit) - len(hit_d)
    if distinctive:
        if not hit_d:
            return 0.0
        if len(toks) > 2 and len(hit) < 2:
            return 0.0
        return 15.0 * len(hit_d) + hit_s
    # only family tokens (the bare parent, e.g. "LCC"): all must be present
    return float(hit_s) if hit_s == len(toks) else 0.0


def entity_score(name: str, info: TextInfo, df: Optional[Counter] = None) -> float:
    return max((_alias_score(a, info, df) for a in entity_aliases(name)), default=0.0)


def best_entities(names: Sequence[str], info: TextInfo, max_tied: int = 2) -> List[str]:
    """Names the text points to most specifically; empty when it names none or
    lists many materials at once (a collective row is not a material's own row)."""
    df = token_frequency(names)
    scores = [(entity_score(n, info, df), n) for n in names]
    top = max((s for s, _ in scores), default=0.0)
    if top <= 0:
        return []
    winners = [n for s, n in scores if s == top]
    return winners if len(winners) <= max_tied else []


def expert_entities(facts_doc: Dict[str, Any]) -> Dict[str, List[str]]:
    out = {"enzyme": [], "substrate": []}
    for f in facts_doc["facts"]:
        if f["slot"] not in ("enzyme.type", "substrate.type"):
            continue
        kind = "enzyme" if f["slot"] == "enzyme.type" else "substrate"
        if f["kind"] == "entity":
            out[kind].append(f["raw"])
        elif f["kind"] == "entity_group":
            out[kind].extend(f["members"])
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}
