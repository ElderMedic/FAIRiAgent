"""Bioinformatics-specialized agent for active metadata recovery from raw data."""

import json
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from .base import BaseAgent
from .react_loop import ReactLoopMixin
from .response_models import DocumentInfoResponse
from ..tools.bio_tools import create_bio_tools
from ..utils.llm_helper import get_llm_helper
from ..models import FAIRifierState
from ..config import config
from ..skills import load_skill_files, skills_catalog_seed_files

class BioMetadataAgent(ReactLoopMixin, BaseAgent):
    """Agent for probing raw biological data to recover missing metadata."""

    def __init__(self):
        super().__init__("BioMetadataAgent")
        self.logger = logging.getLogger(__name__)
        self.llm_helper = get_llm_helper()

    def _build_bio_inner_agent(self, *, science_cache: Optional[Dict[str, Any]] = None):
        """Create the deepagents-backed inner loop for bioinfo analysis."""
        bio_tools = create_bio_tools()

        system_prompt = (
            "You are the BioMetadataAgent for FAIRiAgent. "
            "Your ONLY task: use bioinformatics tools to inspect raw biological data "
            "files and extract metadata that is missing from documentation.\n\n"
            "## Available Tools\n"
            "- run_biocontainer_tool(image, command, host_path): run a tool inside Docker.\n"
            "  Use image=\"samtools\" for .bam, image=\"bcftools\" for .vcf.\n"
            "  host_path MUST be an exact path from the task message.\n"
            "  command example: [\"samtools\", \"stats\", \"/data/filename.bam\"]\n"
            "- decompress_gzip_tool(host_path): decompress .gz files.\n"
            "- extract_archive_tool(host_path): extract tar archives.\n\n"
            "## Critical Rules\n"
            "1. You MUST call at least one tool before responding. Do NOT respond "
            "without first calling a tool to inspect the data.\n"
            "2. Read /skills/bioinfo-analysis/SKILL.md first for exact commands.\n"
            "3. After collecting tool output, call the respond tool with a "
            "DocumentInfoResponse: at minimum provide title, abstract, and any "
            "extracted metadata fields like read_length_bp, paired_end, "
            "reference_genome, file_format, organism.\n"
            "4. Every field value must be grounded in the tool output you received. "
            "Do not invent or guess values."
        )

        return self._build_react_agent(
            tools=bio_tools,
            subagents=[],
            response_format=DocumentInfoResponse,
            system_prompt=system_prompt,
            memory_files=self._get_memory_files(),
        )

    def _build_bio_seed_files(self, state: FAIRifierState) -> Dict[str, Any]:
        """Build virtual files for the bioinfo analysis loop."""
        seed_files: Dict[str, Any] = {}

        # Include parsed document context as a seed file
        doc_info = state.get("document_info", {})
        if doc_info:
            context_text = "# Document Context (parsed by DocumentParser)\n\n"
            context_text += json.dumps(doc_info, indent=2, ensure_ascii=False)
            file_data = self._maybe_create_file_data(context_text)
            if file_data is not None:
                seed_files["/workspace/document_context.json"] = file_data

        evidence_packets = state.get("evidence_packets", []) or []
        if evidence_packets:
            pkt_lines = ["# Evidence Packets\n"]
            for pkt in evidence_packets[:20]:
                pkt_lines.append(f"- {pkt.get('field', '?')}: {str(pkt.get('value', ''))[:200]}")
            file_data = self._maybe_create_file_data("\n".join(pkt_lines))
            if file_data is not None:
                seed_files["/workspace/evidence_packets.md"] = file_data

        source_workspace = state.get("source_workspace", {})
        if source_workspace:
            summary_path = source_workspace.get("summary_path")
            if summary_path:
                try:
                    summary_text = Path(summary_path).read_text(encoding="utf-8")
                    file_data = self._maybe_create_file_data(summary_text)
                    if file_data is not None:
                        seed_files["/workspace/source_workspace.md"] = file_data
                except OSError:
                    self.logger.warning("Failed to read source workspace summary: %s", summary_path)

        seed_files.update(load_skill_files(*config.skill_roots))
        seed_files.update(
            skills_catalog_seed_files(
                *config.skill_roots,
                create_file_data=self._maybe_create_file_data,
            )
        )
        return seed_files

    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """Run the bio-metadata extraction loop."""
        self.logger.info("BioMetadataAgent: \U0001f9ec Starting active data analysis")

        inner_agent = self._build_bio_inner_agent()
        if not inner_agent:
            self.logger.warning("BioMetadataAgent: Deep agents disabled, skipping active analysis.")
            return state

        bio_file_paths: List[str] = state.get("bio_file_paths", []) or []
        if not bio_file_paths:
            self.logger.warning("BioMetadataAgent: No bio_file_paths in state, skipping.")
            return state

        self.logger.info("BioMetadataAgent: %d bio file(s) to analyze", len(bio_file_paths))
        for p in bio_file_paths:
            self.logger.info("  %s", p)

        # Build task with file paths and context
        doc_info = state.get("document_info", {})
        lines = [
            "Analyze the following biological data files and extract metadata "
            "that is missing from documentation.",
            "",
            "## Bio File Paths (use these as host_path in run_biocontainer_tool)",
        ]
        for p in bio_file_paths:
            fname = Path(p).name
            ext = fname.split(".")[-1] if "." in fname else ""
            tool_hint = {"bam": "samtools", "vcf": "bcftools"}.get(ext, "")
            lines.append(f"- {p}  (filename in container: /data/{fname})")
            if tool_hint:
                lines.append(f"  This is a {ext.upper()} file → use image=\"{tool_hint}\"")

        if doc_info and doc_info.get("abstract"):
            lines.append(f"\n## Document Context\nabstract: {doc_info['abstract']}")

        lines += [
            "",
            "## Required Actions (do these in order)",
            "1. Read /skills/bioinfo-analysis/SKILL.md for tool recipes and exact commands.",
            "2. For each file above, call run_biocontainer_tool ONCE with the specific "
            "host_path. For example, for a .bam file:",
            '  run_biocontainer_tool(image="samtools", command=["samtools", "stats", "/data/filename.bam"], host_path="<the host_path from above>")',
            "3. Parse the tool output. Look for metadata like: read length, paired-end status, "
            "reference genome, organism, sample names, sequencing platform.",
            "4. When you have extracted all available metadata, call the respond tool "
            "with a DocumentInfoResponse containing title, abstract, research_domain, "
            "and any other fields you discovered.",
        ]
        task = "\n".join(lines)

        seed_files = self._build_bio_seed_files(state)
        thread_id = state.get("session_id", "default")

        result = await self._invoke_react_agent(
            inner_agent,
            task_message=self._compose_task_message(state, task),
            seed_files=seed_files,
            thread_id=thread_id,
            state=state,
            scratchpad_name="BioMetadataAgent"
        )

        if result:
            # Merge findings into existing document_info
            existing_info = state.get("document_info", {})
            new_info = result.dict()
            for key, value in new_info.items():
                if value and (not isinstance(value, (str, list, dict)) or len(str(value).strip()) > 0):
                    if key not in existing_info or not existing_info.get(key):
                        existing_info[key] = value
            state["document_info"] = existing_info
            self.logger.info("BioMetadataAgent: Merged %d new fields into document_info", len(new_info))

        return state
