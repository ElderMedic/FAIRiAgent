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
            "You are the BioMetadataAgent for FAIRiAgent.\n"
            "Your ONLY purpose: call bioinformatics tools via Docker, then report "
            "what you found. You are NOT allowed to infer or guess metadata "
            "without running a tool first.\n\n"
            "## Available Tools (you MUST use these)\n"
            "- search_biocontainer_tags(tool_name): query quay.io for available image tags.\n"
            "- run_biocontainer_tool(image, command, host_path): run a tool in Docker.\n"
            "- decompress_gzip_tool(host_path): decompress .gz before analysis.\n"
            "- extract_archive_tool(host_path): extract archives before analysis.\n\n"
            "## Few-Shot Example\n"
            "User: Here is a file: /data/sample.bam\n"
            "Thought: I need to analyze this BAM file. I must check for the samtools image first.\n"
            "Action: search_biocontainer_tags(tool_name=\"samtools\")\n"
            "Observation: [quay.io/biocontainers/samtools:1.15--h1170115_1]\n"
            "Thought: Now I will run samtools stats on the file.\n"
            "Action: run_biocontainer_tool(image=\"samtools\", command=[\"samtools\", \"stats\", \"/data/sample.bam\"], host_path=\"/data/sample.bam\")\n"
            "Observation: [stats output showing 10000 reads, paired-end]\n"
            "Thought: I have the metadata. I will now respond.\n"
            "Action: [Respond with DocumentInfoResponse containing the facts]\n\n"
            "## Rules\n"
            "1. Identify file type by extension.\n"
            "2. Call search_biocontainer_tags BEFORE any run_biocontainer_tool call.\n"
            "3. NEVER respond before calling at least one tool."
        )

        return self._build_react_agent(
            tools=bio_tools,
            subagents=[],
            response_format=None,  # Let LLM free-explore with tools first
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

        context = state.setdefault("context", {})

        bio_file_paths: List[str] = state.get("bio_file_paths", []) or []
        if not bio_file_paths:
            self.logger.warning("BioMetadataAgent: No bio_file_paths in state, skipping.")
            return state

        self.logger.info("BioMetadataAgent: %d bio file(s) to analyze", len(bio_file_paths))
        for p in bio_file_paths:
            self.logger.info("  %s", p)

        # Build task — deliberately VAGUE about file types so the agent MUST
        # use tools to discover what each file contains.
        doc_info = state.get("document_info", {})
        lines = [
            "You have been given biological data files to analyze. You do NOT know "
            "what they contain yet. Your ONLY way to find out is by calling tools.",
            "",
            "## Rule: NO TOOL CALL = NO RESPONSE",
            "You are FORBIDDEN from responding with any metadata before you have "
            "called at least one tool per file and received its output.",
            "Do NOT guess. Do NOT infer from filenames. Use tools ONLY.",
            "",
            "## Files (you MUST call tools on these)",
        ]
        for p in bio_file_paths:
            fname = Path(p).name
            lines.append(f"- {p}  (in container at /data/{fname})")

        if doc_info and doc_info.get("abstract"):
            lines.append(f"\n## Context From Documents\n{doc_info['abstract']}")

        lines += [
            "",
            "## Available Tools",
            "- run_biocontainer_tool(image, command, host_path): run any bioinformatics tool in Docker",
            "  Valid images: \"samtools\" or \"bcftools\"",
            "  Example: run_biocontainer_tool(image=\"samtools\", command=[\"samtools\",\"stats\",\"/data/file.bam\"], host_path=\"<path>\")",
            "- decompress_gzip_tool(host_path): unzip .gz files first if needed",
            "- extract_archive_tool(host_path): extract archives if needed",
            "",
            "## Required Workflow",
            "1. For EVERY file above, call run_biocontainer_tool with image=\"samtools\"",
            "   OR image=\"bcftools\". Try samtools first — if it fails, try bcftools.",
            "2. Read the full tool output carefully.",
            "3. Extract facts: read count, length, paired-end status, reference genome,",
            "   organism, sample names, chromosome names, variant counts, etc.",
            "4. Summarize ALL findings in your final message.",
        ]
        task = "\n".join(lines)

        seed_files = self._build_bio_seed_files(state)
        thread_id = state.get("session_id", "default")

        # Use raw ainvoke (not _invoke_react_agent) to get full messages when
        # response_format is None — we parse the final LLM message for metadata.
        raw_result = await inner_agent.ainvoke(
            {
                "messages": [{"role": "user", "content": self._compose_task_message(state, task)}],
                "files": seed_files,
            },
            config={
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 120,
            },
        )
        self._record_react_result(state, "BioMetadataAgent", raw_result)

        # Extract metadata from the last assistant message
        final_text = ""
        messages = raw_result.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, "content") and msg.content:
                final_text = str(msg.content)
                break
            elif isinstance(msg, dict) and msg.get("content"):
                final_text = str(msg["content"])
                break

        if final_text:
            self.logger.info("BioMetadataAgent: got %d chars from agent loop, extracting metadata", len(final_text))
            extracted = await self.llm_helper.extract_document_info(
                final_text,
                critic_feedback=None,
                is_structured_markdown=False,
                planner_instruction="Extract all metadata fields discovered by bioinformatics tool analysis.",
                prior_memory_context=None,
            )
            if extracted:
                existing_info = state.get("document_info", {})
                for key, value in extracted.items():
                    if value and (not isinstance(value, (str, list, dict)) or len(str(value).strip()) > 0):
                        if key not in existing_info or not existing_info.get(key):
                            existing_info[key] = value
                state["document_info"] = existing_info
                self.logger.info("BioMetadataAgent: Merged %d new fields into document_info", len(extracted))

                # ============================================================
                # Inject bio discoveries into the context engineering pipeline
                # so downstream agents (JSONGenerator, ISAValueMapper) see them
                # in evidence_context and field_evidence_context.
                # ============================================================

                # -- 2. evidence_packets --
                evidence_packets = state.get("evidence_packets", []) or []
                base = len(evidence_packets)
                bio_paths = state.get("bio_file_paths", []) or []
                bio_src = Path(bio_paths[0]).name if bio_paths else "bio_raw_data"

                for idx, (fname, fval) in enumerate(extracted.items()):
                    if fname in {"confidence", "raw_text", "document_type"}:
                        continue
                    vs = str(fval)[:500] if fval else ""
                    if not vs:
                        continue
                    pos = final_text.lower().find(vs[:40].lower())
                    excerpt = (
                        final_text[max(0,pos-40):pos+len(vs)+40].strip()
                        if pos >= 0
                        else f"Bioinformatics tool output: {bio_src}"
                    )
                    evidence_packets.append({
                        "packet_id": f"bio-{base + idx + 1:03d}",
                        "field_candidate": fname,
                        "value": vs,
                        "evidence_text": excerpt[:300],
                        "section": f"bio_tool::{bio_src}",
                        "source_type": "bioinformatics_tool_output",
                        "confidence": 0.95,
                        "provenance": {
                            "agent": "BioMetadataAgent",
                            "strategy": "active_bioinformatics_recovery",
                            "source": bio_src,
                        },
                    })
                state["evidence_packets"] = evidence_packets
                self.logger.info(
                    "BioMetadataAgent: Injected %d evidence packets from bio discoveries",
                    len(evidence_packets) - base,
                )

                # -- 3. source_workspace --
                source_ws = state.get("source_workspace", {}) or {}
                bio_sid = f"bio_{bio_src.replace('.', '_')}"
                if bio_sid not in source_ws.get("source_paths", {}):
                    from ..services.source_workspace import SourceRecord, build_source_workspace
                    import tempfile
                    bio_tmp = Path(tempfile.mkdtemp(prefix="bio_ws_"))
                    bio_out = bio_tmp / f"{bio_src}.bio.txt"
                    bio_out.write_text(final_text[:50000], encoding="utf-8")
                    record = SourceRecord(
                        source_id=bio_sid,
                        path=str(bio_out),
                        method="bioinformatics_tool",
                        content=final_text[:50000],
                        content_type="text",
                    )
                    try:
                        new_ws = build_source_workspace([record], bio_tmp)
                        source_ws.setdefault("source_paths", {}).update(new_ws.source_paths)
                        source_ws.setdefault("table_paths", {}).update(new_ws.table_paths)
                        if hasattr(new_ws, "manifest") and new_ws.manifest:
                            em = source_ws.get("manifest", {})
                            em["sources"] = em.get("sources", []) + new_ws.manifest.get("sources", [])
                            em["source_count"] = len(em["sources"])
                            source_ws["manifest"] = em
                        source_ws.setdefault("root_dir", str(bio_tmp))
                        self.logger.info(
                            "BioMetadataAgent: Registered '%s' in source_workspace",
                            bio_sid,
                        )
                    except Exception as exc:
                        self.logger.warning(
                            "BioMetadataAgent: source_workspace merge failed: %s", exc
                        )
                    state["source_workspace"] = source_ws

        else:
            self.logger.warning("BioMetadataAgent: No text output from deep agent")

        return state
