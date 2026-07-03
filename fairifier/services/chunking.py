"""Scientific document chunking: Block → Chunk → Section."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..config import config
from .mineru_paths import load_content_list_v2
from .source_workspace import SourceWorkspace, load_source_workspace


_CHARS_PER_TOKEN = 4


def _token_to_chars(tokens: int) -> int:
    return max(1, int(tokens)) * _CHARS_PER_TOKEN


_HEADING_RE = re.compile(
    r"^(#{1,6}\s+.+|[A-Z][A-Z0-9 ,\-]{3,})$",
    re.MULTILINE,
)
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")


_IMRAD_HINTS = {
    "abstract": "abstract",
    "introduction": "introduction",
    "background": "introduction",
    "methods": "methods",
    "materials": "methods",
    "methodology": "methods",
    "results": "results",
    "discussion": "discussion",
    "conclusion": "discussion",
    "conclusions": "discussion",
    "references": "references",
    "acknowledgment": "supplement",
    "acknowledgement": "supplement",
    "supplementary": "supplement",
}


@dataclass
class SourceBlock:
    source_id: str
    text: str
    char_start: int
    char_end: int
    block_type: str = "text"
    page_idx: Optional[int] = None
    text_level: Optional[int] = None
    heading: Optional[str] = None


@dataclass
class SourceChunk:
    chunk_id: str
    source_id: str
    text: str
    char_start: int
    char_end: int
    section_id: str
    section_title: str
    section_type: str = "unknown"
    block_types: List[str] = field(default_factory=list)
    token_estimate: int = 0


@dataclass
class SourceSection:
    section_id: str
    source_id: str
    title: str
    section_type: str
    char_start: int
    char_end: int
    text: str
    chunk_ids: List[str] = field(default_factory=list)
    token_estimate: int = 0


@dataclass
class ChunkingResult:
    chunks: List[SourceChunk]
    sections: List[SourceSection]
    chunks_manifest_path: Optional[Path] = None
    sections_manifest_path: Optional[Path] = None


def infer_section_type(title: str) -> str:
    lowered = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    for token, section_type in _IMRAD_HINTS.items():
        if token in lowered.split():
            return section_type
    for token, section_type in _IMRAD_HINTS.items():
        if token in lowered:
            return section_type
    return "unknown"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _ngram_set(text: str, n: int = 5) -> set:
    normalized = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if len(normalized) < n:
        return {normalized} if normalized else set()
    return {normalized[i : i + n] for i in range(len(normalized) - n + 1)}


def _is_near_duplicate(a: str, b: str, threshold: float) -> bool:
    if not a or not b:
        return False
    grams_a = _ngram_set(a)
    grams_b = _ngram_set(b)
    if not grams_a or not grams_b:
        return False
    overlap = len(grams_a & grams_b)
    union = len(grams_a | grams_b)
    return (overlap / union) >= threshold


def blocks_from_content_list_v2(
    source_id: str,
    source_text: str,
    blocks: Sequence[Dict[str, Any]],
) -> List[SourceBlock]:
    """Map MinerU content_list_v2 blocks to char-offset blocks."""
    if not blocks:
        return blocks_from_text(source_id, source_text)

    cursor = 0
    normalized: List[SourceBlock] = []
    for index, block in enumerate(blocks):
        text = str(block.get("text") or block.get("content") or "").strip()
        if not text:
            continue
        pos = source_text.find(text, cursor)
        if pos < 0:
            pos = source_text.lower().find(text.lower(), cursor)
        if pos < 0:
            pos = cursor
        char_start = pos
        char_end = pos + len(text)
        cursor = char_end
        heading = None
        text_level = block.get("text_level")
        block_type = str(block.get("type") or "text")
        if text_level or block_type in {"title", "heading"} or text.startswith("#"):
            heading = text.lstrip("# ").strip()
        normalized.append(
            SourceBlock(
                source_id=source_id,
                text=text,
                char_start=char_start,
                char_end=char_end,
                block_type=block_type,
                page_idx=block.get("page_idx"),
                text_level=text_level if isinstance(text_level, int) else None,
                heading=heading,
            )
        )
    return normalized or blocks_from_text(source_id, source_text)


def blocks_from_text(source_id: str, source_text: str) -> List[SourceBlock]:
    """Fallback paragraph + heading parser when MinerU blocks are unavailable."""
    blocks: List[SourceBlock] = []
    if not source_text:
        return blocks

    current_heading: Optional[str] = None
    cursor = 0
    for match in _HEADING_RE.finditer(source_text):
        start = match.start()
        if start > cursor:
            paragraph = source_text[cursor:start].strip()
            if paragraph:
                blocks.append(
                    SourceBlock(
                        source_id=source_id,
                        text=paragraph,
                        char_start=cursor,
                        char_end=start,
                        block_type="paragraph",
                        heading=current_heading,
                    )
                )
        heading = match.group(0).lstrip("# ").strip()
        blocks.append(
            SourceBlock(
                source_id=source_id,
                text=heading,
                char_start=match.start(),
                char_end=match.end(),
                block_type="heading",
                heading=heading,
            )
        )
        current_heading = heading
        cursor = match.end()

    tail = source_text[cursor:].strip()
    if tail:
        pos = source_text.find(tail, cursor)
        if pos < 0:
            pos = cursor
        blocks.append(
            SourceBlock(
                source_id=source_id,
                text=tail,
                char_start=pos,
                char_end=pos + len(tail),
                block_type="paragraph",
                heading=current_heading,
            )
        )

    if not blocks and source_text.strip():
        text = source_text.strip()
        blocks.append(
            SourceBlock(
                source_id=source_id,
                text=text,
                char_start=0,
                char_end=len(text),
                block_type="document",
            )
        )
    return blocks


def _merge_blocks_to_chunks(
    blocks: Sequence[SourceBlock],
    *,
    target_chars: int,
    hard_cap_chars: int,
    section_id: str,
    section_title: str,
    section_type: str,
    chunk_index_start: int,
) -> Tuple[List[SourceChunk], int]:
    chunks: List[SourceChunk] = []
    buffer: List[SourceBlock] = []
    buffer_chars = 0
    chunk_index = chunk_index_start

    def flush() -> None:
        nonlocal buffer, buffer_chars, chunk_index
        if not buffer:
            return
        text = "\n\n".join(block.text for block in buffer)
        char_start = buffer[0].char_start
        char_end = buffer[-1].char_end
        chunk_id = f"{section_id}_chunk_{chunk_index:03d}"
        chunks.append(
            SourceChunk(
                chunk_id=chunk_id,
                source_id=buffer[0].source_id,
                text=text,
                char_start=char_start,
                char_end=char_end,
                section_id=section_id,
                section_title=section_title,
                section_type=section_type,
                block_types=[block.block_type for block in buffer],
                token_estimate=_estimate_tokens(text),
            )
        )
        chunk_index += 1
        buffer = []
        buffer_chars = 0

    for block in blocks:
        block_len = len(block.text)
        if buffer and buffer_chars + block_len > hard_cap_chars:
            flush()
        buffer.append(block)
        buffer_chars += block_len
        if buffer_chars >= target_chars:
            flush()
    flush()
    return chunks, chunk_index


def chunk_source_text(
    source_id: str,
    source_text: str,
    blocks: Optional[Sequence[Dict[str, Any]]] = None,
) -> ChunkingResult:
    """Chunk one source into child chunks and parent sections."""
    target_chars = _token_to_chars(config.chunk_target_tokens)
    hard_cap_chars = _token_to_chars(config.chunk_hard_cap_tokens)
    section_target_chars = _token_to_chars(config.section_target_tokens)
    section_soft_cap_chars = _token_to_chars(config.section_soft_cap_tokens)
    dup_threshold = float(config.retrieval_near_duplicate_threshold)

    parsed_blocks = (
        blocks_from_content_list_v2(source_id, source_text, list(blocks or []))
        if blocks
        else blocks_from_text(source_id, source_text)
    )

    sections: List[SourceSection] = []
    all_chunks: List[SourceChunk] = []
    current_section_blocks: List[SourceBlock] = []
    current_title = "Document"
    current_type = "unknown"
    section_counter = 0
    chunk_counter = 0

    def finalize_section(blocks_for_section: List[SourceBlock]) -> None:
        nonlocal section_counter, chunk_counter
        if not blocks_for_section:
            return
        section_counter += 1
        section_id = f"{source_id}_section_{section_counter:03d}"
        section_text = "\n\n".join(block.text for block in blocks_for_section)
        if sections and _is_near_duplicate(sections[-1].text, section_text, dup_threshold):
            return
        section_chunks, chunk_counter = _merge_blocks_to_chunks(
            blocks_for_section,
            target_chars=target_chars,
            hard_cap_chars=hard_cap_chars,
            section_id=section_id,
            section_title=current_title,
            section_type=current_type,
            chunk_index_start=chunk_counter,
        )
        if not section_chunks:
            return
        char_start = blocks_for_section[0].char_start
        char_end = blocks_for_section[-1].char_end
        section = SourceSection(
            section_id=section_id,
            source_id=source_id,
            title=current_title,
            section_type=current_type,
            char_start=char_start,
            char_end=char_end,
            text=section_text[:section_soft_cap_chars],
            chunk_ids=[chunk.chunk_id for chunk in section_chunks],
            token_estimate=_estimate_tokens(section_text),
        )
        sections.append(section)
        all_chunks.extend(section_chunks)

    section_chars = 0
    for block in parsed_blocks:
        if block.heading and current_section_blocks:
            finalize_section(current_section_blocks)
            current_section_blocks = []
            section_chars = 0
            current_title = block.heading
            current_type = infer_section_type(current_title)

        current_section_blocks.append(block)
        section_chars += len(block.text)
        if section_chars >= section_target_chars:
            finalize_section(current_section_blocks)
            current_section_blocks = []
            section_chars = 0

    finalize_section(current_section_blocks)
    return ChunkingResult(chunks=all_chunks, sections=sections)


def chunk_workspace(
    workspace_meta: Dict[str, Any],
    *,
    max_sections: Optional[int] = None,
) -> ChunkingResult:
    """Chunk all sources in a materialized source workspace."""
    workspace = load_source_workspace(workspace_meta)
    all_chunks: List[SourceChunk] = []
    all_sections: List[SourceSection] = []
    section_limit = max_sections or config.mapreduce_max_sections

    structured_blocks = workspace_meta.get("mineru_structured_blocks") or {}
    content_list_path = workspace_meta.get("mineru_content_list_v2_path")

    for entry in workspace.manifest.get("sources", []):
        source_id = str(entry.get("source_id", ""))
        if source_id not in workspace.source_paths:
            continue
        source_text = workspace.source_paths[source_id].read_text(encoding="utf-8")
        blocks: Optional[List[Dict[str, Any]]] = structured_blocks.get(source_id)
        if blocks is None and content_list_path:
            try:
                blocks = load_content_list_v2(Path(content_list_path), max_blocks=None)
            except (OSError, json.JSONDecodeError, TypeError):
                blocks = None

        result = chunk_source_text(source_id, source_text, blocks=blocks)
        all_chunks.extend(result.chunks)
        all_sections.extend(result.sections)
        if len(all_sections) >= section_limit:
            all_sections = all_sections[:section_limit]
            allowed_chunk_ids = {chunk_id for section in all_sections for chunk_id in section.chunk_ids}
            all_chunks = [chunk for chunk in all_chunks if chunk.chunk_id in allowed_chunk_ids]
            break

    manifest_paths = write_chunk_manifests(workspace.root_dir, all_chunks, all_sections)
    return ChunkingResult(
        chunks=all_chunks,
        sections=all_sections,
        chunks_manifest_path=manifest_paths[0],
        sections_manifest_path=manifest_paths[1],
    )


def write_chunk_manifests(
    workspace_root: Path,
    chunks: Iterable[SourceChunk],
    sections: Iterable[SourceSection],
) -> Tuple[Optional[Path], Optional[Path]]:
    """Persist chunk/section manifests under source_workspace/chunks/."""
    chunks_dir = Path(workspace_root) / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = chunks_dir / "chunks.jsonl"
    sections_path = chunks_dir / "sections.jsonl"

    with chunks_path.open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(
                json.dumps(
                    {
                        "chunk_id": chunk.chunk_id,
                        "source_id": chunk.source_id,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "section_id": chunk.section_id,
                        "section_title": chunk.section_title,
                        "section_type": chunk.section_type,
                        "block_types": chunk.block_types,
                        "token_estimate": chunk.token_estimate,
                        "text": chunk.text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    with sections_path.open("w", encoding="utf-8") as fh:
        for section in sections:
            fh.write(
                json.dumps(
                    {
                        "section_id": section.section_id,
                        "source_id": section.source_id,
                        "title": section.title,
                        "section_type": section.section_type,
                        "char_start": section.char_start,
                        "char_end": section.char_end,
                        "chunk_ids": section.chunk_ids,
                        "token_estimate": section.token_estimate,
                        "text": section.text,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    return chunks_path, sections_path


def serialize_chunking_result(result: ChunkingResult) -> Dict[str, Any]:
    return {
        "chunk_count": len(result.chunks),
        "section_count": len(result.sections),
        "chunks_manifest_path": str(result.chunks_manifest_path) if result.chunks_manifest_path else None,
        "sections_manifest_path": str(result.sections_manifest_path) if result.sections_manifest_path else None,
        "chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "source_id": chunk.source_id,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "section_id": chunk.section_id,
                "section_title": chunk.section_title,
                "section_type": chunk.section_type,
            }
            for chunk in result.chunks
        ],
        "sections": [
            {
                "section_id": section.section_id,
                "source_id": section.source_id,
                "title": section.title,
                "section_type": section.section_type,
                "char_start": section.char_start,
                "char_end": section.char_end,
                "chunk_ids": section.chunk_ids,
            }
            for section in result.sections
        ],
    }
