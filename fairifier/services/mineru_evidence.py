"""Separate MinerU chart reconstructions from reported document evidence.

This transformation applies only to verified MinerU output. Original Markdown,
images and structured artifacts remain unchanged. The working text retains
figure links and captions while replacing generated chart-data details with
references that cannot authenticate reconstructed numerical values.
"""

from __future__ import annotations

import hashlib
import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


_CHART_SUMMARIES = frozenset({
    "chart", "line chart", "bar chart", "pie chart", "scatter chart",
    "area chart", "radar chart", "bubble chart", "scatter plot",
    "box plot", "histogram", "heatmap",
})
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]\n]*\]\(\s*(?:<([^>\n]+)>|([^\s)]+))[^\n)]*\)")


class MinerUEvidenceError(ValueError):
    """Raw conversion exists, but a safe working evidence view cannot be built."""


class _ChartDetails(HTMLParser):
    """Locate generated chart details using offsets into the unchanged text."""

    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.text = text
        self.line_offsets = [0, *(match.end() for match in re.finditer("\n", text))]
        self.stack: List[Dict[str, Any]] = []
        self.regions: List[Dict[str, Any]] = []
        self.table_stack: List[int] = []
        self.closed_tables: List[Tuple[int, int]] = []

    def _char_offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag == "details":
            self.stack.append({
                "raw_start": self._char_offset(), "summary_parts": [],
                "in_summary": False,
            })
        elif tag == "summary" and self.stack:
            self.stack[-1]["in_summary"] = True
        elif tag == "table":
            self.table_stack.append(self._char_offset())

    def handle_data(self, data):
        if self.stack and self.stack[-1]["in_summary"]:
            self.stack[-1]["summary_parts"].append(data)

    def _finish_region(self, detail: Dict[str, Any], end: int, *, closed: bool) -> None:
        summary = " ".join("".join(detail["summary_parts"]).split())
        normalized = " ".join(summary.lower().replace("_", " ").replace("-", " ").split())
        if normalized in _CHART_SUMMARIES:
            if not closed:
                end = self._bounded_table_end(detail)
            self.regions.append({
                "kind": "chart_reconstruction", "status": "unverified",
                "summary": summary, "raw_start": detail["raw_start"],
                "raw_end": end, "boundary_status": "closed" if closed else "recovered_table",
            })

    def _bounded_table_end(self, detail: Dict[str, Any]) -> int:
        """Recover only an explicit table body, never the remaining article."""
        start = detail.get("body_start")
        if start is not None:
            start += len(self.text[start:]) - len(self.text[start:].lstrip())
            for table_start, table_end in self.closed_tables:
                if table_start == start:
                    return table_end
            markdown_end = _markdown_table_end(self.text, start)
            if markdown_end is not None:
                return markdown_end
        raise MinerUEvidenceError(
            "Unterminated chart reconstruction has no unambiguous table boundary; "
            "the raw MinerU artifact is retained."
        )

    def handle_endtag(self, tag):
        if tag == "summary" and self.stack:
            self.stack[-1]["in_summary"] = False
            end = self.text.find(">", self._char_offset())
            if end >= 0:
                self.stack[-1]["body_start"] = end + 1
        elif tag == "details" and self.stack:
            detail = self.stack.pop()
            end = self.text.find(">", self._char_offset())
            self._finish_region(detail, end + 1 if end >= 0 else len(self.text), closed=True)
        elif tag == "table" and self.table_stack:
            start = self.table_stack.pop()
            end = self.text.find(">", self._char_offset())
            if not self.table_stack and end >= 0:
                self.closed_tables.append((start, end + 1))

    def finish(self) -> List[Dict[str, Any]]:
        for detail in self.stack:
            self._finish_region(detail, len(self.text), closed=False)
        # A nested chart block belongs to the outer chart's excluded span.
        regions: List[Dict[str, Any]] = []
        for item in sorted(self.regions, key=lambda region: (region["raw_start"], -region["raw_end"])):
            if regions and item["raw_start"] < regions[-1]["raw_end"]:
                continue
            regions.append(item)
        return regions


def _markdown_table_end(text: str, start: int) -> int | None:
    """Return the end of a contiguous pipe table beginning exactly at start."""
    lines = text[start:].splitlines(keepends=True)
    if len(lines) < 2:
        return None

    def cells(line: str) -> List[str]:
        stripped = line.strip()
        if "|" not in stripped:
            return []
        parts = re.split(r"(?<!\\)\|", stripped)
        if stripped.startswith("|"):
            parts.pop(0)
        if stripped.endswith("|"):
            parts.pop()
        return [part.strip() for part in parts]

    header, separator = cells(lines[0]), cells(lines[1])
    if (
        not header
        or len(header) != len(separator)
        or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator)
    ):
        return None
    cursor = start + len(lines[0])
    end = cursor + len(lines[1].rstrip("\r\n"))
    cursor += len(lines[1])
    for line in lines[2:]:
        if len(cells(line)) != len(header):
            break
        end = cursor + len(line.rstrip("\r\n"))
        cursor += len(line)
    return end


def _chart_images(text: str, region: Dict[str, Any], markdown_path: Path) -> List[str]:
    start, end = region["raw_start"], region["raw_end"]
    matches = list(_MARKDOWN_IMAGE.finditer(text[start:end]))
    preceding = list(_MARKDOWN_IMAGE.finditer(text[:start]))
    if preceding:
        last = preceding[-1]
        between = text[last.end():start]
        if len(between) <= 2000 and "</details>" not in between.lower():
            matches.insert(0, last)
    paths: List[str] = []
    for match in matches:
        target = match.group(1) or match.group(2)
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, flags=re.IGNORECASE):
            path = target
        else:
            path = str((markdown_path.parent / target).resolve())
        if path not in paths:
            paths.append(path)
    return paths


def prepare_mineru_evidence(
    markdown_text: str, markdown_path: Path,
) -> Tuple[str, Dict[str, Any]]:
    """Return factual working text and provenance for excluded chart estimates.

    The caller establishes MinerU provenance. This helper must not be applied
    indiscriminately to author-written Markdown. Raw span offsets are Unicode
    character offsets in ``markdown_text``; the digest identifies the raw file.
    """
    markdown_path = Path(markdown_path)
    parser = _ChartDetails(markdown_text)
    parser.feed(markdown_text)
    parser.close()
    regions = parser.finish()
    if not regions:
        return markdown_text, {}
    for region in regions:
        region["image_paths"] = _chart_images(markdown_text, region, markdown_path)
    evidence = {
        "raw_markdown_path": str(markdown_path),
        "raw_markdown_sha256": hashlib.sha256(markdown_path.read_bytes()).hexdigest(),
        "derived_regions": regions,
    }
    working = markdown_text
    for region in reversed(regions):
        images = " ".join(f"[Original figure]({path})" for path in region["image_paths"])
        replacement = (
            f"[Unverified chart reconstruction: {region['summary']}. "
            "Generated values and chart rows are excluded from source measurements. "
            "The raw reconstruction is retained in source_evidence references.]"
            + (f"\n{images}" if images else "")
        )
        working = working[:region["raw_start"]] + replacement + working[region["raw_end"]:]
    return working, evidence


def supplement_pdf_first_page(
    working_text: str, pdf_path: Path,
) -> Tuple[str, Dict[str, Any]]:
    """Retain native first-page text that layout conversion omitted.

    Publication headers can contain identifiers and dates absent from MinerU's
    body text. These blocks come directly from the same PDF, with page and
    bounding-box provenance. They do not assert field meanings or add values
    from PDF metadata, filenames, or model predictions.
    """
    pdf_path = Path(pdf_path)
    if pdf_path.suffix.lower() != ".pdf":
        return working_text, {}
    try:
        import fitz

        with fitz.open(pdf_path) as document:
            blocks = document[0].get_text("blocks") if len(document) else []
    except Exception as exc:
        logger.warning("Native PDF first-page text unavailable for %s: %s", pdf_path, exc)
        return working_text, {}

    normalized = " ".join(working_text.split())
    regions: List[Dict[str, Any]] = []
    for block in blocks:
        if len(block) < 7 or block[6] != 0:
            continue
        text = str(block[4]).strip()
        normalized_block = " ".join(text.split())
        if not normalized_block or normalized_block in normalized:
            continue
        working_text += "\n\n[Native text from the same PDF, page 1]\n"
        start = len(working_text)
        working_text += text
        regions.append({
            "source_path": str(pdf_path), "page_number": 1,
            "bbox": list(block[:4]), "method": "pymupdf_text",
            "text": text, "working_start": start, "working_end": len(working_text),
        })
        normalized += " " + normalized_block
    if not regions:
        return working_text, {}
    return working_text, {
        "native_pdf_sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        "native_pdf_regions": regions,
    }


__all__ = ["MinerUEvidenceError", "prepare_mineru_evidence", "supplement_pdf_first_page"]
