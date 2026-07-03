# Scientific Document Chunking & Sectioning Design

> **Status: PROPOSED — companion to
> [HYBRID_RETRIEVAL_AND_COVERAGE_UPGRADE_PLAN.md](HYBRID_RETRIEVAL_AND_COVERAGE_UPGRADE_PLAN.md)
> Workstream A.** This document replaces that plan's earlier, underspecified
> "heading-aware Markdown split" description with a concrete design grounded
> in what MinerU already produces, and in how scientific papers (plus their
> supplementary files, tables, and multi-file bundles) are actually
> structured.

---

## 1. Why the generic answer ("split Markdown by `#` headings, ~450 tokens,
15% overlap") is not good enough here

Two things are specific to this vertical and change the generic RAG
chunking playbook:

1. **MinerU already parses documents into typed, positioned blocks** — not
   just Markdown text. Re-deriving structure by regexing `#` characters out
   of the rendered Markdown throws that information away and rebuilds a
   worse version of it.
2. **Scientific papers have a well-known internal structure (IMRaD)** that
   correlates strongly with which FAIR-DS field types live where (Methods →
   assay conditions, Results → measured outcomes). A chunker that is blind
   to this forces every downstream ranking decision to rediscover it from
   scratch, or not at all.

There is also a real gap today: **tables embedded inside a PDF (not
supplied as a separate Excel/CSV file) are never extracted into structured
rows.** They exist only as Markdown table syntax inside the source `.md`
text, searchable by `grep_sources()` as noisy prose, invisible to
`search_table()`. This design fixes that as part of chunking, not as a
separate workstream, because the fix is "route MinerU's table blocks through
the same table-extraction code path," which is naturally a chunking-time
decision.

---

## 2. Three-tier structure: Block → Chunk → Section

These are **three different granularities for three different consumers**,
not one chunk size used everywhere:

| Tier | Size target | Consumer | Purpose |
|---|---|---|---|
| **Block** | Atomic (one paragraph / heading / table / figure / equation) | Internal only | Smallest structurally-typed unit; source of truth for everything else |
| **Chunk** | target 384 tokens, hard cap 448 tokens including contextual header (embedding-model tokenizer) | `hybrid_search_sources()` semantic index (Workstream B) | Retrieval precision — must fit the embedding model's sequence limit |
| **Section** | target 2,400 tokens, soft cap 3,200 tokens (LLM tokenizer approximation) | `Send()` map-reduce workers (Workstream D) | Coverage — one focused LLM call per section, cheap and parallel |

A **Section owns an ordered list of Chunk IDs**, and a **Chunk owns an
ordered list of Block IDs** — retrieving a chunk can always be expanded to
its parent section for more context (standard "small-chunk-retrieve,
larger-chunk-generate" pattern), and every chunk still resolves to exact
character offsets in the original source file, so citations stay
`source_id:char_start-char_end` regardless of which tier found the evidence.
This parent-child design follows the common production RAG lesson that small
chunks retrieve precisely, but the reranker/LLM often needs the larger parent
to avoid missing the decisive line just outside the retrieved child.

```python
@dataclass
class DocBlock:
    block_id: str
    source_id: str
    block_type: Literal["title", "text", "table", "image", "equation", "caption"]
    text: str
    char_start: int
    char_end: int
    page_idx: Optional[int]
    heading_level: Optional[int]        # only for block_type == "title"

@dataclass
class SourceChunk:
    chunk_id: str
    source_id: str
    block_ids: list[str]
    char_start: int
    char_end: int
    text: str                            # raw text, WITHOUT the contextual header (§6)
    breadcrumb: list[str]                # e.g. ["2. Materials and Methods", "2.3 Enzymatic Assay"]
    section_type: str                    # canonical IMRaD-ish type, see §4
    source_role: str                     # existing _infer_role() output
    associated_table_id: Optional[str]   # set when this chunk is a table caption (§5)
    references: list[str]                # e.g. ["table_2"] — cross-reference mentions (§5)

@dataclass
class DocSection:
    section_id: str
    source_id: str
    chunk_ids: list[str]
    section_type: str
    source_role: str
    char_start: int
    char_end: int
```

---

## 3. Block extraction: MinerU `content_list_v2` as the primary source of truth

`fairifier/services/mineru_paths.py::load_content_list_v2()` already parses
MinerU's structured output into blocks with `type`, `text`, `page_idx`,
`bbox` — this already exists and is already loaded into
`MinerUConversionResult.structured_blocks`, but today it is only used
truncated to **200 blocks** for prompt-context metadata
(`structured_output_metadata()` in `mineru_client.py`), not for chunking.

**Required change:** add an unrestricted loader path (`max_blocks=None`) used
specifically by the chunker — the existing 200-block cap stays exactly as-is
for its current prompt-context use, it just should not also be the input to
chunking (a full paper is routinely 300–800+ blocks).

**Required change:** `load_content_list_v2()` currently drops MinerU's
`text_level` field (which marks *heading depth* for `type == "title"`
blocks — MinerU's schema provides this, it's just not read today). Capture
it as `DocBlock.heading_level` — this is what lets the chunker build an
exact heading hierarchy (the `breadcrumb` field) without guessing from
Markdown `#` counts or ALL-CAPS heuristics.

**When MinerU structured output is unavailable** (MinerU disabled, plain
`.txt` input, non-PDF sources, `structured_blocks` empty): fall back to a
lightweight blank-line paragraph splitter + heading regex (Markdown `#`,
numbered headings like `^\d+(\.\d+)*\s+[A-Z]`, ALL-CAPS short lines — this
subsumes and replaces `DocumentParser`'s existing, weaker
`analyze_document_outline` tool, which used exactly this heuristic
ad hoc and only when a model chose to call it). One shared function computes
section type (§4) for both paths so there is a single classification
implementation, not two.

**Structured, non-prose sources** (Excel/CSV/ISA-Tab files, already
extracted into `tables/*.jsonl`; raw bio files handled by
`BioMetadataAgent`) are **not chunked as prose at all** — they become a
single `DocSection` of `section_type="tabular_data"` whose content for
map-reduce purposes is a compact structured summary (column names + a few
sample rows), reusing the existing table-extraction path untouched.

### 3.1 Parameter defaults

| Parameter | Default | Notes |
|---|---:|---|
| child chunk target | 384 embedder tokens | Leaves headroom for contextual header under bge-small's ~512-token limit |
| child chunk hard cap | 448 embedder tokens | Split oversized paragraph/table-caption blocks if exceeded |
| fallback overlap | 64 tokens (~15%) | Used only when a single block must be split by tokens; natural block boundaries otherwise do not need overlap |
| section target | 2,400 approximate LLM tokens | Good size for one Methods/Results subsection |
| section soft cap | 3,200 approximate LLM tokens | Over cap: split at nearest paragraph/block boundary |
| max sections per run | 80 initial default | Prevents runaway cost on huge zip bundles; after prioritization/dedup (§7), not before |
| map-reduce worker concurrency | 5 initial default | Matches existing batch-evaluation concurrency pattern; tune with provider rate limits |

These are starting values, not magic constants. Tune them against
section-coverage recall and token cost, not against subjective prompt length.

---

## 4. Section-type canonicalization (IMRaD-aware, deterministic, skill-extensible)

A cheap keyword lookup, not a model call — this is a solved, closed
vocabulary problem for scientific papers, and it must stay debuggable and
free:

```python
_SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "abstract":               ("abstract",),
    "introduction":           ("introduction", "background"),
    "methods":                ("material", "method", "experimental section", "methodology", "protocol"),
    "results":                ("result",),
    "discussion":             ("discussion",),
    "results_and_discussion": ("results and discussion",),   # checked before results/discussion individually
    "conclusion":             ("conclusion", "summary"),
    "acknowledgments":        ("acknowledg",),
    "references":             ("reference", "bibliograph", "literature cited", "works cited"),
    "data_availability":      ("data availability", "code availability"),
    "supplementary":          ("supplement", "appendix", "additional file", "supporting information"),
}

def classify_section_type(heading_text: str) -> str:
    normalized = re.sub(r"^[\divxIVX]+[\.\)]\s*", "", heading_text.strip().lower())
    for canonical, keywords in _SECTION_KEYWORDS.items():
        if any(kw in normalized for kw in keywords):
            return canonical
    return "unknown"
```

- Checked in dict-insertion order so `"results_and_discussion"` is matched
  before the individual `"results"` / `"discussion"` entries fire on the
  same heading text — order matters, not just membership.
- **`references` sections are chunked (so their boundary is known and can be
  excluded) but never indexed for retrieval or map-reduce extraction** —
  same "strip references" intent as today's `extract_document_info()`
  truncation, now applied consistently across the map-reduce path too,
  which the current character-truncation approach does not reach.
- **Supplementary files get IMRaD classification recursively** — `role =
  "supplement"` (existing, file-level, from `_infer_role()`) and
  `section_type = "methods"` (new, heading-level, from this classifier) are
  **orthogonal axes**, not one replacing the other. A supplementary PDF can
  itself have an Abstract/Methods/Results structure; today's file-role-only
  ranking cannot express "this is supplementary, but it's specifically the
  Methods section, which matters for assay fields."
- **Skill-extensible**: domain skills (`fairifier/skills/`) may contribute
  additional keyword entries (e.g. a clinical-trial skill adding "consort
  flow diagram", "randomization"), loaded into `_SECTION_KEYWORDS` at
  startup — same principle as replacing the hardcoded PETase alias map with
  skill-provided vocabulary in the main plan's §9.3: domain vocabulary is
  data the skill system owns, not a special case hardcoded once for one
  dataset.

This classification feeds directly into the main plan's §9.4
(section-type-aware ranking boost) — `hybrid_search_sources()` looks up
`section_type` from each chunk's metadata to apply the boost, rather than
deriving it ad hoc per call site.

---

## 5. Tables, captions, and cross-references

### 5.1 In-PDF tables get the same structured path as standalone Excel/CSV (fixes the gap in §1)

When a block has `block_type == "table"` (from `content_list_v2`), route its
parsed rows through the **same** table-extraction code that already handles
Excel/CSV `record.tables` → `tables/*.jsonl`
(`fairifier/services/source_workspace.py`), tagged
`{source_id}_{table_index:02d}.jsonl` exactly like today — no new file
format, no new query path. `search_table()` then works identically whether
the table came from a supplementary spreadsheet or was embedded in the PDF's
page 5.

Fallback: if MinerU gives a table block as plain text/Markdown rather than
structured rows, store the raw table text as a normal chunk and log
`table_parse_status="raw_text_only"`. Do not invent rows with an LLM in the
first implementation; table-row synthesis is high-risk because it can create
false data. Add deterministic Markdown-table parsing first, and only add
LLM-assisted table repair if evaluation shows many important tables remain
unusable.

### 5.2 Caption linking

The block immediately preceding or following a `table`/`image` block is
checked against a caption pattern:

```python
_CAPTION_PATTERN = re.compile(r"^(Table|Figure|Fig\.)\s*S?\d+", re.IGNORECASE)
```

A match sets `SourceChunk.associated_table_id` /
`associated_figure_id`, so a hybrid-search hit on the caption text can pull
the associated table's structured rows into the same `FieldCandidate` group
— narrative and tabular evidence bundled, not competing.

### 5.3 Cross-reference resolution

Any chunk whose text matches
`\((?:Table|Fig(?:ure)?)\.?\s*S?\d+\)` or
`(?:Table|Fig(?:ure)?)\.?\s*S?\d+\s+(?:shows|depicts|presents|summarizes)`
gets `references: ["table_2", ...]` populated. This is used as a **retrieval
boost**, not a hard join: a field whose best textual match references Table
2 should have Table 2's rows surfaced alongside it, in case the actual
number lives in the table and the narrative only points at it (a very common
pattern — "reaction conditions are summarized in Table 2" with zero numbers
in the sentence itself).

---

## 6. Contextual chunk headers (zero extra LLM cost)

Isolated chunks lose meaning out of context — "Reactions were run at 37 °C
for 24 h" means nothing without knowing which experiment. Rather than
Anthropic's original Contextual Retrieval technique (one LLM call per chunk
to generate a context blurb — too expensive at the scale of an entire
multi-file bundle), use a **deterministic** header built from metadata
already computed above:

```
[Doc: {doc_title} | Source: {source_id} ({source_role}) | Section: {breadcrumb_joined} | Type: {section_type}]
{chunk.text}
```

- This header is part of the **embedding input only**. The stored citation
  span (`char_start`/`char_end`) still points to the original text in the
  source file, excluding the synthetic header — grounding format is
  unaffected.
- Zero marginal LLM cost since every field in the header is already known
  from block/chunk metadata, not generated.

---

## 7. Multi-document / multi-file bundle handling

- Each `source_id` runs the block → chunk → section pipeline
  **independently** — no cross-file blending at extraction time.
- The `Send()` map-reduce fan-out (main plan §8.2) flattens `DocSection`s
  from **all** source_ids into one `pending_sections` list, each tagged with
  `(source_id, source_role, section_type)`.
- **Dual-axis prioritization** in `_upstream_reconcile_candidates()`: today's
  `source_role_priority()` (main manuscript > protocol > table > metadata
  table > supplement) is joined with a `section_type` relevance bonus (e.g.
  boost `methods`-typed evidence for `assay`-sheet fields even when it comes
  from a lower-priority supplement, if the main manuscript's own Methods
  section is thin or absent). Role answers "which file do I trust more,"
  section type answers "does this text even talk about what I'm looking
  for" — both matter, independently.
- **Near-duplicate section detection** (cost optimization, not correctness):
  a preprint and its supplementary methods file often restate the same
  protocol nearly verbatim. Before dispatching `Send()` workers, compute a
  cheap 5-gram shingle signature per section; if a lower-priority section's
  signature is >92% similar to an already-queued higher-priority section,
  skip a second LLM call for it and instead attach its `source_id` as
  additional provenance on the original section's result — this still lets
  `_upstream_reconcile_candidates()`'s multi-source-agreement scoring see
  "confirmed in 2 sources" without paying for a duplicate extraction call.
- **Section-count cap applies after prioritization, not before**: when a
  directory/zip bundle produces more sections than
  `FAIRIFIER_MAPREDUCE_MAX_SECTIONS`, keep the highest-ranked sections by
  `(source_role_priority, section_type relevance)` first, not simply the
  first N encountered in file-scan order.

---

## 8. Token budgets and tokenizers (be exact, not approximate-everywhere)

- **Chunk sizing** uses the actual embedding model's tokenizer
  (`bge-small-en-v1.5` via `sentence-transformers`, max sequence length
  ~512 tokens) — target 384 tokens per chunk, hard cap 448 tokens including
  the deterministic contextual header, leaving headroom for the
  contextual header (§6). Getting this wrong silently truncates the
  embedding input, which degrades retrieval without any visible error.
- **Section sizing** uses a provider-agnostic approximation (prefer
  `tiktoken` when installed, fall back to a 4 chars/token heuristic)
  targeting 2,400 tokens with a 3,200-token soft cap —
  large enough for one Methods subsection's full detail, small enough to
  keep `Send()` workers cheap and fast.
- **Overlap**: primary splitting is on natural block/paragraph boundaries —
  no arbitrary sliding-window overlap needed between chunks in the same
  section. A fixed ~15% token-overlap sliding window is only a fallback for
  a single block that itself exceeds the chunk budget (long unbroken prose
  in poorly-structured OCR'd legacy PDFs).

---

## 9. Interaction with existing code and fallback policy

| Existing component | Change |
|---|---|
| `load_content_list_v2()` (`mineru_paths.py`) | Add `max_blocks=None` unrestricted variant for chunking; capture `text_level` into the normalized block dict |
| `structured_output_metadata()` (`mineru_client.py`) | Unchanged — still uses the 200-block cap for prompt context, a separate concern from chunking |
| `DocumentParser`'s `analyze_document_outline` tool | Deprecated, not immediately deleted — superseded by the deterministic chunker's block-derived (or fallback-regex) outline once tests cover MinerU, PyMuPDF, Markdown, and plain text inputs |
| `_infer_role()` / `source_role_priority()` (`source_workspace.py`) | Unchanged — file-level role stays exactly as-is; `section_type` is a new, additional, orthogonal signal |
| `record.tables` / `tables/*.jsonl` extraction | Extended to also receive rows parsed from MinerU `type=="table"` blocks, using the identical file-writing code path |
| `grep_sources()` | Unchanged — still the lexical half of `hybrid_search_sources()` (main plan §6) |

Fallback rules:

1. If MinerU structured blocks are present, use them as the primary block
   source.
2. If MinerU blocks are absent but Markdown/text exists, use fallback
   paragraph/heading parsing and record `chunking_source="fallback_text"`.
3. If chunking fails for a source, keep the source in the workspace and fall
   back to current lexical grep over the full source text for that source,
   with a warning in `workflow_report.json`.
4. Never silently drop a source because chunking failed. A failed chunker
   reduces semantic/map-reduce coverage, but it must not reduce today's
   baseline lexical accessibility.

---

## 10. Artifacts consumed by the agent harness and evaluation

Chunking/indexing must write deterministic run artifacts, not only transient
Qdrant state. Required files under `source_workspace/`:

| Artifact | Purpose |
|---|---|
| `chunks/block_manifest.jsonl` | One `DocBlock` per line; debug MinerU/fallback parsing and page/heading metadata |
| `chunks/chunk_manifest.jsonl` | One `SourceChunk` per line; used by evaluation to count chunks/section types without querying Qdrant |
| `chunks/section_manifest.jsonl` | One `DocSection` per line; source of section coverage denominators |
| `evidence_store.jsonl` | Evidence items exported from Qdrant for audit, tests, and Qdrant-outage fallback |
| `tables/*.jsonl` | Existing table path, extended to include parsed in-PDF tables |

`workflow_report.json` should store counts and status only (paths, counts,
fallback flags), not duplicate large manifests. Evaluation reads the manifests
when it needs detailed coverage analysis.

The section manifest is the denominator for `section_coverage_ratio`:

```text
processed_sections / planned_sections
```

where `planned_sections` excludes references sections and duplicate-skipped
sections, but includes any section skipped because a worker timed out (timeout
is a coverage failure, duplicate skip is not).

---

## 11. Explicit non-goals

- **Not building a general-purpose scientific-document parser** (no GROBID,
  no PubLayNet/layout model integration) — MinerU already does PDF layout
  parsing; this design consumes its output, it does not replace it.
- **Not attempting perfect cross-reference NLP** (entity linking, coreference
  resolution) — the caption/cross-reference rules in §5 are intentionally
  simple regex heuristics, cheap and debuggable, not a research project.
- **Not deduplicating at the chunk level** — near-duplicate detection (§7)
  operates at the section level, right before the expensive `Send()` fan-out,
  where it actually saves cost; chunk-level dedup would add complexity for
  a much smaller payoff.
