"""Preserve publication-table structure from MinerU artifacts and Markdown HTML.

The searchable row projection is derived from the physical HTML grid. Header
semantics are accepted only from explicit HTML headers; raw HTML, merged-cell
origins and source locations remain available independently of that projection.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _text(value: Any) -> str:
    return " ".join(str(value if value is not None else "").split())


# A body value: a number, optionally signed, with ± error, %, or a short unit.
def _unwrap_number(text: str) -> str:
    """A cell without math delimiters and footnote marks:
    ``\\( 8.6 ± 0.8^{\\text{ab}} \\)`` is the number ``8.6 ± 0.8``."""
    text = re.sub(r"\\[()]|\$", " ", text or "")
    text = re.sub(r"\^\{\s*(?:\\text\{)?[a-z*†‡§]{1,3}\}?\s*\}|\^[a-z*†‡§](?![a-z])", "", text)
    return " ".join(text.split())


_BARE_NUMBER_RE = re.compile(r"^\s*[<>≤≥~≈]?\s*[+−-]?\d[\d.,]*(?:\s*(?:±|\+/-)\s*\d[\d.,]*)?\s*\*?\s*$")
_NUMERIC_CELL_RE = re.compile(
    r"^\s*[<>≤≥~≈]?\s*[+−-]?\d[\d.,]*(?:\s*(?:±|\+/-)\s*\d[\d.,]*)?"
    r"(?:\s*(?:%|[a-zA-Zµμ°/·^\-{}0-9]{1,12}))?\s*\*?\s*$"
)


def _fragments(value: Any) -> List[str]:
    """Read legacy strings and v2 typed caption/footnote fragments."""
    if isinstance(value, str):
        return [_text(value)] if value.strip() else []
    if isinstance(value, list):
        return [text for item in value for text in _fragments(item)]
    if isinstance(value, dict):
        return _fragments(value.get("content") or value.get("text"))
    return []


class _HTMLTables(HTMLParser):
    """Locate complete outer tables without changing source character offsets."""

    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.text = text
        self.line_offsets = [0]
        self.line_offsets.extend(match.end() for match in re.finditer("\n", text))
        self.depth = 0
        self.start = 0
        self.spans: List[Tuple[int, int]] = []

    def _char_offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.depth == 0:
                self.start = self._char_offset()
            self.depth += 1

    def handle_endtag(self, tag):
        if tag == "table" and self.depth:
            self.depth -= 1
            if self.depth == 0:
                end = self.text.find(">", self._char_offset())
                if end >= 0:
                    self.spans.append((self.start, end + 1))


class _TableGrid(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.html = html
        self.line_offsets = [0]
        self.line_offsets.extend(match.end() for match in re.finditer("\n", html))
        self.depth = 0
        self.section = ""
        self.rows: List[Dict[str, Any]] = []
        self.cell: Optional[Dict[str, Any]] = None
        self.caption_parts: List[str] = []
        self.in_caption = False
        self.issues: List[str] = []

    def _char_offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def _close_cell(self, end: int):
        if self.cell is not None:
            self.cell["text"] = _text("".join(self.cell.pop("parts")))
            self.cell["html"] = self.html[self.cell.pop("start"):end]
            self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.depth += 1
            if self.depth > 1:
                self.issues.append("Nested table retained as raw HTML; headers unresolved.")
            return
        if self.depth != 1:
            return
        if tag in {"thead", "tbody", "tfoot"}:
            self.section = tag
        elif tag == "caption":
            self.in_caption = True
        elif tag == "tr":
            self._close_cell(self._char_offset())
            self.rows.append({"section": self.section, "cells": []})
        elif tag in {"td", "th"}:
            self._close_cell(self._char_offset())
            if not self.rows:
                self.rows.append({"section": self.section, "cells": []})
            attributes = dict(attrs)
            cell: Dict[str, Any] = {
                "tag": tag, "scope": attributes.get("scope", ""),
                "parts": [], "start": self._char_offset(),
            }
            for span in ("rowspan", "colspan"):
                try:
                    count = int(attributes.get(span) or "1")
                    if not 1 <= count <= 1000:
                        raise ValueError("unsupported cell span")
                except (TypeError, ValueError):
                    count = 1
                    self.issues.append("Invalid cell span; raw HTML retained.")
                cell[span] = count
            self.rows[-1]["cells"].append(cell)
            self.cell = cell
        elif self.cell is not None:
            if tag == "br":
                self.cell["parts"].append(" ")
            elif tag in {"sup", "sub"}:
                self.cell["parts"].append("^{" if tag == "sup" else "_{")

    def handle_endtag(self, tag):
        if tag == "table":
            if self.depth == 1:
                self._close_cell(self._char_offset())
            self.depth = max(0, self.depth - 1)
            return
        if self.depth != 1:
            return
        if tag in {"td", "th"}:
            end = self.html.find(">", self._char_offset())
            self._close_cell(end + 1 if end >= 0 else len(self.html))
        elif tag == "tr":
            self._close_cell(self._char_offset())
        elif tag == "caption":
            self.in_caption = False
        elif tag in {"thead", "tbody", "tfoot"}:
            self.section = ""
        elif tag in {"sup", "sub"} and self.cell is not None:
            self.cell["parts"].append("}")

    def handle_data(self, data):
        if self.in_caption:
            self.caption_parts.append(data)
        elif self.cell is not None:
            self.cell["parts"].append(data)

    def _infer_td_header_rows(
        self,
        occupied: Dict[Tuple[int, int], Dict[str, Any]],
        width: int,
    ) -> List[int]:
        """Infer column headers of an all-<td> grid (MinerU emits no <th>).

        Only the unambiguous case is inferred: a top-row cell spanning rows or
        columns marks a header block (e.g. "Km (mM)" spanning one column per
        enzyme), every header cell is text, and numeric values lie beneath.
        A plain single top row stays unresolved: it may be a data row.
        """
        if not self.rows or width < 2:
            return []
        if any(row["section"] in {"thead", "tfoot"} for row in self.rows):
            return []

        def numeric(text: str) -> bool:
            return bool(_NUMERIC_CELL_RE.match(_unwrap_number(text)))

        def bare(text: str) -> bool:
            return bool(_BARE_NUMBER_RE.match(_unwrap_number(text)))

        def text_only(r: int) -> bool:
            return all(not numeric(cell["text"]) for cell in self.rows[r]["cells"])

        top = self.rows[0]["cells"]
        depth = max((cell["rowspan"] for cell in top), default=1)
        spans = any(cell["colspan"] > 1 or cell["rowspan"] > 1 for cell in top)
        if not spans:
            # A plain top row is a header when its labels sit over numbers
            # ("Enzyme | Km (mM)" over "LCC | 1.15 ± 0.01"). A text row over
            # text rows, or a top row of plain numbers, may be data and stays
            # unresolved.
            labels = [cell["text"] for cell in top]
            if len(self.rows) < 2 or sum(1 for text in labels if text) < 2 or numeric(labels[0]):
                return []
            for c in range(1, width):
                label = (occupied.get((0, c)) or {}).get("text", "")
                if not numeric(label):
                    continue
                # A condition level as a column label ("55 °C") carries a unit
                # its unit-less cells ("3.93 ± 0.57") do not; otherwise the top
                # row may be data.
                cells = [(occupied.get((r, c)) or {}).get("text", "") for r in range(1, len(self.rows))]
                if bare(label) or "±" in label or any(numeric(cell) and not bare(cell) for cell in cells):
                    return []
            labelled_numbers = any(
                numeric((occupied.get((r, c)) or {}).get("text", ""))
                and (occupied.get((0, c)) or {}).get("text")
                for r in range(1, len(self.rows)) for c in range(1, width)
            )
            return [0] if labelled_numbers else []
        header = list(range(min(depth, len(self.rows))))
        if any(not text_only(r) for r in header) or len(header) >= len(self.rows):
            return []
        body = [r for r in range(len(self.rows)) if r not in header]
        value_columns = [
            c for c in range(1, width)
            if any(numeric((occupied.get((r, c)) or {}).get("text", "")) for r in body)
        ]
        return header if value_columns else []

    def project(self) -> Dict[str, Any]:
        self._close_cell(len(self.html))
        occupied: Dict[Tuple[int, int], Dict[str, Any]] = {}
        cells: List[Dict[str, Any]] = []
        width = 0
        for row_index, row in enumerate(self.rows):
            column_index = 0
            for cell in row["cells"]:
                while (row_index, column_index) in occupied:
                    column_index += 1
                cell["row_index"] = row_index
                cell["column_index"] = column_index
                cell["section"] = row["section"]
                cells.append(cell)
                for r in range(row_index, min(len(self.rows), row_index + cell["rowspan"])):
                    for c in range(column_index, column_index + cell["colspan"]):
                        if (r, c) in occupied:
                            self.issues.append("Overlapping cell spans; headers unresolved.")
                        occupied[(r, c)] = cell
                column_index += cell["colspan"]
                width = max(width, column_index)

        header_rows = [i for i, row in enumerate(self.rows) if row["section"] == "thead"]
        if not header_rows:
            for i, row in enumerate(self.rows):
                explicit = any(
                    cell["tag"] == "th" and cell["scope"] != "row"
                    for cell in row["cells"]
                )
                # A th cell can identify a BODY row. Without thead/scope, a
                # mixed th/td row containing values is not a column header.
                explicit = explicit and all(
                    cell["tag"] == "th" or not cell["text"]
                    for cell in row["cells"]
                )
                if row["section"] in {"tbody", "tfoot"} or not explicit:
                    break
                header_rows.append(i)
        body_rows = [
            i for i, row in enumerate(self.rows)
            if i not in header_rows and row["section"] != "tfoot"
        ]
        resolved = bool(header_rows) and bool(body_rows) and not self.issues
        inferred = False
        if not resolved:
            header_rows = []
            if not self.issues:
                header_rows = self._infer_td_header_rows(occupied, width)
                inferred = bool(header_rows)
                body_rows = [
                    i for i, row in enumerate(self.rows)
                    if i not in header_rows and row["section"] != "tfoot"
                ]

        columns: List[str] = []
        used: Counter[str] = Counter()
        for c in range(width):
            parts, origins = [], set()
            for r in header_rows:
                cell = occupied.get((r, c))
                if cell and (cell["row_index"], cell["column_index"]) not in origins:
                    origins.add((cell["row_index"], cell["column_index"]))
                    if cell["text"]:
                        parts.append(cell["text"])
            label = " | ".join(parts) if parts else f"column_{c + 1}"
            used[label] += 1
            candidate = label if used[label] == 1 else f"{label} [{used[label]}]"
            while candidate in columns:
                used[label] += 1
                candidate = f"{label} [{used[label]}]"
            columns.append(candidate)

        rows, row_indices, grid_origins, footnotes = [], [], [], []
        for r, row in enumerate(self.rows):
            grid_origins.append([
                [occupied[(r, c)]["row_index"], occupied[(r, c)]["column_index"]]
                if (r, c) in occupied else None
                for c in range(width)
            ])
            if row["section"] == "tfoot":
                footnotes.extend(cell["text"] for cell in row["cells"] if cell["text"])
                continue
            if r not in header_rows:
                rows.append({
                    column: occupied.get((r, c), {}).get("text", "")
                    for c, column in enumerate(columns)
                })
                row_indices.append(r)
        caption = _text("".join(self.caption_parts))
        return {
            "rows": rows, "columns": columns,
            "header_status": (
                "resolved" if resolved else "inferred" if inferred else "unresolved"
            ),
            "header_rows": header_rows, "row_indices": row_indices,
            "cells": cells, "grid_origins": grid_origins,
            "leading_rows": [
                {"source_row_index": r, "cells": list(row.values())}
                for r, row in zip(row_indices[:3], rows[:3])
            ] if not resolved else [],
            "captions": [caption] if caption else [],
            "footnotes": footnotes, "raw_html": self.html,
            "issues": list(dict.fromkeys(self.issues)),
        }


def _blocks(
    payload: Any, page: Optional[int] = None, pointer: str = "",
) -> Iterable[Tuple[Dict[str, Any], Optional[int], str]]:
    if isinstance(payload, list):
        page_lists = any(isinstance(item, list) for item in payload)
        for index, item in enumerate(payload):
            yield from _blocks(item, index if page_lists else page, f"{pointer}/{index}")
    elif isinstance(payload, dict):
        if payload.get("type"):
            yield payload, payload.get("page_idx", page), pointer
        else:
            for key in ("pages", "blocks", "content"):
                if isinstance(payload.get(key), (list, dict)):
                    yield from _blocks(payload[key], page, f"{pointer}/{key}")
                    break


def _parse_table(
    html: str, provenance: Dict[str, Any], block: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    parser = _TableGrid(html)
    parser.feed(html)
    parser.close()
    table = parser.project()
    content = (block or {}).get("content")
    content = content if isinstance(content, dict) else (block or {})
    for key, source_key in (("captions", "table_caption"), ("footnotes", "table_footnote")):
        values = _fragments(content.get(source_key)) or _fragments((block or {}).get(source_key))
        table[key] = list(dict.fromkeys(values + table[key]))
    table["provenance"] = provenance
    return table


def _cell_signature(table: Dict[str, Any]) -> Tuple:
    return tuple(
        (cell["row_index"], cell["column_index"], cell["rowspan"], cell["colspan"], cell["text"])
        for cell in table["cells"] if cell.get("section") != "tfoot"
    )


def _same_occurrence(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
    left, right = first["provenance"], second["provenance"]
    if left.get("page_idx") is not None and right.get("page_idx") is not None:
        if left["page_idx"] != right["page_idx"]:
            return False
        if left.get("bbox") is not None and right.get("bbox") is not None:
            return left["bbox"] == right["bbox"]
    # Locationless renderings can only be paired by physical cell content,
    # one occurrence at a time. Caption placement/HTML header tags may differ.
    return bool(first["cells"]) and _cell_signature(first) == _cell_signature(second)


def _representation(table: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "raw_html": table["raw_html"], "provenance": dict(table["provenance"]),
        "captions": list(table["captions"]), "footnotes": list(table["footnotes"]),
        "header_status": table["header_status"], "header_rows": list(table["header_rows"]),
        "columns": list(table["columns"]),
    }


def _merge_context(current: Dict[str, Any], incoming: Dict[str, Any]) -> None:
    representations = current.get("representations") or [_representation(current)]
    representations.append(_representation(incoming))
    captions = list(dict.fromkeys(current["captions"] + incoming["captions"]))
    footnotes = list(dict.fromkeys(current["footnotes"] + incoming["footnotes"]))
    compatible = _cell_signature(current) == _cell_signature(incoming)
    if (
        compatible
        and current["header_status"] in {"unresolved", "inferred"}
        and incoming["header_status"] == "resolved"
    ):
        # Replace the entire projection and its provenance together. Raw HTML
        # must never be attributed to the other artifact's source location.
        current.update(incoming)
    elif not compatible:
        current["issues"].append(
            "Located representations disagree on cells; primary values retained, alternatives preserved."
        )
    current["captions"], current["footnotes"] = captions, footnotes
    current["representations"] = representations


def _source_order(table: Dict[str, Any]) -> Tuple:
    provenance = table["provenance"]
    page = provenance.get("page_idx")
    if isinstance(page, (int, float)):
        return (0, page, provenance.get("block_index", 0))
    return (1, provenance.get("start", 0), provenance.get("block_index", 0))


def extract_publication_tables(
    markdown_text: str, markdown_path: Optional[Path] = None,
    *, excluded_markdown_spans: Iterable[Tuple[int, int]] = (),
) -> List[Dict[str, Any]]:
    """Read complete v2/legacy artifacts, with occurrence-aware HTML fallback.

    Artifact paths are resolved beside the actual Markdown stem, including when
    the original document was renamed on checksum-cache reuse. No files change.
    Exclusions apply only to HTML tables wholly contained in the given raw
    Markdown character intervals; structured publication-table blocks remain.
    """
    excluded_spans = tuple(excluded_markdown_spans)
    sources: List[List[Dict[str, Any]]] = []
    if markdown_path is not None:
        markdown_path = Path(markdown_path)
        for suffix in ("_content_list_v2.json", "_content_list.json"):
            path = markdown_path.with_name(markdown_path.stem + suffix)
            if not path.is_file():
                continue
            try:
                raw = path.read_bytes()
                payload = json.loads(raw)
                digest = hashlib.sha256(raw).hexdigest()
                tables = []
                for index, (block, page, pointer) in enumerate(_blocks(payload)):
                    if str(block.get("type") or "").lower() != "table":
                        continue
                    content = block.get("content")
                    content = content if isinstance(content, dict) else {}
                    html = content.get("html") or block.get("table_body") or block.get("html")
                    if not isinstance(html, str) or not html.strip():
                        continue
                    tables.append(_parse_table(html, {
                        "artifact_path": str(path), "artifact_sha256": digest,
                        "block_index": index, "json_pointer": pointer,
                        "page_idx": page, "bbox": block.get("bbox"),
                    }, block))
                sources.append(tables)
            except (OSError, ValueError, TypeError) as exc:
                logger.warning("Unable to read publication tables from %s: %s", path, exc)

    scanner = _HTMLTables(markdown_text)
    scanner.feed(markdown_text)
    scanner.close()
    sources.append([
        _parse_table(markdown_text[start:end], {
            "artifact_path": str(markdown_path) if markdown_path is not None else None,
            "artifact_sha256": hashlib.sha256(markdown_text.encode("utf-8")).hexdigest(),
            "start": start, "end": end,
        })
        for start, end in scanner.spans
        if not any(
            excluded_start <= start and end <= excluded_end
            for excluded_start, excluded_end in excluded_spans
        )
    ])

    result: List[Dict[str, Any]] = []
    for source_tables in sources:
        # Partial v2 coverage may be completed by an earlier-page legacy table.
        # Restore document order before pairing locationless Markdown occurrences.
        result.sort(key=_source_order)
        prior_count = len(result)
        matched: set[int] = set()
        for table in source_tables:
            match = next((
                index for index in range(prior_count)
                if index not in matched and _same_occurrence(result[index], table)
            ), None)
            if match is None:
                result.append(table)
            else:
                matched.add(match)
                _merge_context(result[match], table)
    result.sort(key=_source_order)
    for index, table in enumerate(result):
        table["name"] = f"table_{index + 1:03d}"
        table["provenance"]["table_index"] = index
        for representation in table.get("representations", []):
            representation["provenance"]["table_index"] = index
    return result


_HTML_TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
DERIVED_TABLE_ROWS_HEADER = "[Derived table rows: each cell labelled by its column header]"


def render_table_rows(html: str) -> List[str]:
    """Render a table with resolved/inferred headers as one line per body row.

    Each cell is written as ``<column header> = <cell>``, so a row line names
    the row label, the column (e.g. parameter and enzyme of a pivoted table)
    and the value together. Lines are deterministic derivations of the source
    grid, never generated text. Unresolved grids yield nothing.
    """
    return [line for _, line in rendered_table_rows(html)]


def rendered_table_rows(html: str) -> List[Tuple[int, str]]:
    """``render_table_rows`` lines with the index of their ``<tr>`` in ``html``."""
    grid = _TableGrid(html)
    try:
        grid.feed(html)
        grid.close()
        table = grid.project()
    except Exception:  # malformed HTML stays available as raw text only
        return []
    if table["header_status"] == "unresolved":
        return []
    lines = []
    section = ""
    for index, row in zip(table["row_indices"], table["rows"]):
        cells = [f"{column} = {value}" for column, value in row.items() if _text(value)]
        values = [value for value in row.values() if _text(value)]
        if len(values) == 1 and len(row) > 2 and not _NUMERIC_CELL_RE.match(values[0]):
            # A lone label row ("Thc_Cut1") names the material of the rows below.
            section = _text(values[0])
            continue
        if len(cells) > 1:
            # A number keeps its value, not its math markup or footnote mark.
            cells = [f"{column} = {_unwrap_number(value)}"
                     if _NUMERIC_CELL_RE.match(_unwrap_number(value)) else f"{column} = {value}"
                     for column, value in row.items() if _text(value)]
            lines.append((index, "; ".join(([f"section = {section}"] if section else []) + cells)))
    return lines


def with_derived_table_rows(text: str) -> str:
    """Append header-labelled rows of every source HTML table to ``text``."""
    if not text or "<table" not in text.lower():
        return text
    blocks = []
    for index, match in enumerate(_HTML_TABLE_RE.finditer(text), start=1):
        lines = render_table_rows(match.group(0))
        if lines:
            blocks.append(f"[table {index}]\n" + "\n".join(lines))
    if not blocks:
        return text
    return text.rstrip() + "\n\n" + DERIVED_TABLE_ROWS_HEADER + "\n" + "\n\n".join(blocks) + "\n"


_BARE_QUANTITY_RE = re.compile(
    r"^\s*[<>≤≥~]?\s*[+−-]?\d[\d.,]*(?:[eE][+−-]?\d+)?(?:\s*(?:±|\+/-)\s*\d[\d.,]*)?\s*$"
)


def _header_unit(header: str) -> Optional[str]:
    """Unit in the trailing parentheses of a column header's top-level label.

    ``"\\( K_m \\) (mM) | BhrPETase"`` -> ``"mM"``; LaTeX delimiters, braces and
    ``\\mu`` are rendered plainly. Returns None when no unit is declared.
    """
    top = header.split(" | ", 1)[0]
    plain = top.replace("\\(", " ").replace("\\)", " ")
    match = re.search(r"\(([^()]*)\)\s*$", plain)
    if not match:
        return None
    unit = match.group(1).replace("\\mu", "µ").replace("{", "").replace("}", "")
    unit = " ".join(unit.replace("\\", "").split()).replace(" ", "")
    return unit or None


def header_unit_for_value(text: str, value: Any) -> Optional[str]:
    """The single unit declared by every table header above ``value``.

    Looks the bare quantity up in the derived header-labelled rows. Returns
    None when the value is not bare, not found, or found under headers that
    declare no unit or different units (ambiguous).
    """
    value = _text(value)
    if not value or not _BARE_QUANTITY_RE.match(value):
        return None
    _, marker, derived = (text or "").partition(DERIVED_TABLE_ROWS_HEADER)
    if not marker:
        return None
    units = set()
    for line in derived.splitlines():
        for cell in line.split("; "):
            header, sep, cell_value = cell.rpartition(" = ")
            if sep and _text(cell_value) == value:
                units.add(_header_unit(header))
    if len(units) == 1:
        return next(iter(units))
    return None


def unit_key(text: Any) -> str:
    """Compare unit spellings across LaTeX, superscript and plain forms."""
    text = _text(text).lower().replace("\\mu", "µ").replace("μ", "µ")
    text = text.translate(str.maketrans("⁻¹²³−", "-123-"))
    text = re.sub(r"\bsec\b", "s", re.sub(r"\\[a-z]+", " ", text))
    # ASCII micro prefix (umol, ug, uL, uM) and solidus division (/min/mg =
    # min^-1 mg^-1) are the same units as their typeset forms.
    text = re.sub(r"\bu(?=(?:mol|g|l|m)\b)", "µ", text)
    text = re.sub(r"\s*/\s*([a-zµ]+)", r" \1-1", text)
    return re.sub(r"[\\{}()\s·⋅*^]", "", text)
