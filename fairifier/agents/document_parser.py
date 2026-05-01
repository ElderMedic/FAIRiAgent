"""Document parsing agent for extracting research information from PDFs and text."""

import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import fitz  # PyMuPDF
from langchain_core.tools import tool
from langsmith import traceable

from .base import BaseAgent
from .react_loop import ReactLoopMixin
from .response_models import DocumentInfoResponse
from ..models import FAIRifierState
from ..config import config
from ..skills import load_skill_files, skills_catalog_seed_files
from ..services.evidence_packets import build_evidence_packets
from ..services.retrieval_cache import get_cache_bucket
from ..tools.science_tools import create_science_tools
from ..utils.llm_helper import get_llm_helper
from ..services.mineru_client import MinerUClient, MinerUConversionError
from ..tools.mineru_tools import create_mineru_convert_tool


class DocumentParserAgent(ReactLoopMixin, BaseAgent):
    """Agent for parsing research documents and extracting key information."""
    
    def __init__(self):
        super().__init__("DocumentParser")
        self.logger = logging.getLogger(__name__)
        self.llm_helper = get_llm_helper()
        self._inner_dp_agent = None
        
        self.mineru_client: Optional[MinerUClient] = None
        self.mineru_tool = None
        if config.mineru_enabled and config.mineru_server_url:
            try:
                candidate = MinerUClient(
                    cli_path=config.mineru_cli_path,
                    server_url=config.mineru_server_url,
                    backend=config.mineru_backend,
                    timeout_seconds=config.mineru_timeout_seconds,
                )
                if candidate.is_available():
                    self.mineru_client = candidate
                    # Create MinerU tool for LangChain integration
                    self.mineru_tool = create_mineru_convert_tool(client=candidate)
                    self.logger.info("MinerU tool enabled for DocumentParser.")
                else:
                    self.logger.warning(
                        "MinerU CLI not available or misconfigured. Falling back to PyMuPDF."
                    )
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning("Failed to initialize MinerU client: %s", exc)
                self.mineru_client = None

    def _build_dp_inner_agent(
        self,
        *,
        critic_feedback: Optional[Dict[str, Any]] = None,
        planner_instruction: Optional[str] = None,
        prior_memory_context: Optional[str] = None,
        is_structured_markdown: bool = False,
        science_cache: Optional[Dict[str, Any]] = None,
    ):
        """Create the deepagents-backed inner loop for document parsing."""
        parser_science_tools = create_science_tools(cache_store=science_cache)

        @tool
        def analyze_document_outline(text: str) -> Dict[str, Any]:
            """Extract a lightweight section outline from the document text."""
            headings = []
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    headings.append(line.lstrip("# ").strip())
                elif len(line) < 120 and line.isupper():
                    headings.append(line)
            return {
                "section_count": len(headings),
                "sections": headings[:50],
            }

        @tool
        async def focused_field_extraction(
            section_text: str,
            focus_fields: str = "",
        ) -> Dict[str, Any]:
            """Extract targeted metadata from a selected section."""
            local_memory_context = prior_memory_context
            if focus_fields:
                extra_focus = f"Prioritize these fields if supported by the section: {focus_fields}"
                local_memory_context = (
                    f"{prior_memory_context}\n\n{extra_focus}"
                    if prior_memory_context else extra_focus
                )
            extracted = await self.llm_helper.extract_document_info(
                section_text,
                critic_feedback=critic_feedback,
                is_structured_markdown=is_structured_markdown,
                planner_instruction=planner_instruction,
                prior_memory_context=local_memory_context,
            )
            return extracted

        system_prompt = (
            "You are the internal DocumentParser loop for FAIRiAgent. "
            "Read /workspace/document.md, use tools to inspect structure, and return "
            "a concise structured metadata object that matches existing FAIRifier "
            "document_info conventions such as document_type, title, abstract, "
            "authors, keywords, research_domain, methodology, location, and coordinates. "
            "When /workspace/source_workspace.md exists, use it as the source inventory; "
            "read files under /workspace/sources/ only when you need more exact evidence. "
            "Skills (built-in and user-imported) follow the Anthropic pattern: YAML frontmatter on SKILL.md "
            "plus optional sibling .md files under /skills/. A summary lives at /workspace/skills_catalog.md. "
            "You MUST open /workspace/skills_catalog.md on the first tool-capable turn, select every skill whose "
            "when_to_use or description fits this document, read those SKILL.md files (and any referenced .md in the "
            "same skill folder), and let them drive terminology, field priorities, and extraction checklists before "
            "you return structured metadata."
        )
        subagents = [
            {
                "name": "section-analyst",
                "description": "Inspect a single section and extract section-specific metadata.",
                "system_prompt": (
                    "You analyze one document section at a time. "
                    "Honor skill playbooks from /workspace/skills_catalog.md when they match the section; "
                    "read the listed SKILL.md if you have file access. "
                    "Stay concise and return factual metadata only."
                ),
                "tools": [focused_field_extraction],
            }
        ]
        tools = [analyze_document_outline, focused_field_extraction, *parser_science_tools]
        return self._build_react_agent(
            tools=tools,
            subagents=subagents,
            response_format=DocumentInfoResponse,
            system_prompt=system_prompt,
            memory_files=self._get_memory_files(),
        )

    def _build_dp_seed_files(
        self,
        document_text: str,
        source_workspace: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build virtual files for the deepagents document parsing loop."""
        seed_files: Dict[str, Any] = {}
        document_file = self._maybe_create_file_data(document_text)
        if document_file is not None:
            seed_files["/workspace/document.md"] = document_file

        if source_workspace:
            summary_path = source_workspace.get("summary_path")
            if summary_path:
                try:
                    summary_file = self._maybe_create_file_data(
                        Path(summary_path).read_text(encoding="utf-8")
                    )
                    if summary_file is not None:
                        seed_files["/workspace/source_workspace.md"] = summary_file
                except OSError:
                    self.logger.warning("Failed to read source workspace summary: %s", summary_path)
            for source_id, source_path in (source_workspace.get("source_paths") or {}).items():
                try:
                    source_file = self._maybe_create_file_data(
                        Path(source_path).read_text(encoding="utf-8")
                    )
                    if source_file is not None:
                        seed_files[f"/workspace/sources/{source_id}.md"] = source_file
                except OSError:
                    self.logger.warning("Failed to read source workspace file: %s", source_path)

        agents_path = Path(config.project_root) / "AGENTS.md"
        if agents_path.exists():
            agent_file = self._maybe_create_file_data(agents_path.read_text(encoding="utf-8"))
            if agent_file is not None:
                seed_files["/AGENTS.md"] = agent_file

        seed_files.update(load_skill_files(*config.skill_roots))
        seed_files.update(
            skills_catalog_seed_files(
                *config.skill_roots,
                create_file_data=self._maybe_create_file_data,
            )
        )
        return seed_files

    def _structured_doc_info_to_dict(
        self,
        structured: DocumentInfoResponse,
    ) -> Dict[str, Any]:
        """Convert structured deepagents output into the repository state shape."""
        doc_info_dict = structured.model_dump(exclude={"confidence"}, exclude_none=True)
        return {
            key: value for key, value in doc_info_dict.items()
            if value not in (None, "", [], {})
        }

    def _count_non_empty_fields(self, doc_info_dict: Dict[str, Any]) -> int:
        """Count meaningful fields in extracted document metadata."""
        return sum(
            1 for value in doc_info_dict.values()
            if value and (
                (isinstance(value, str) and value.strip()) or
                (isinstance(value, (list, dict)) and len(value) > 0) or
                (not isinstance(value, (str, list, dict)))
            )
        )

    def _infer_document_source_type(
        self,
        is_mineru_content: bool,
        document_path: str,
    ) -> str:
        """Label the evidence packet source type for downstream context engineering."""
        if is_mineru_content:
            return "mineru_markdown"
        if document_path.endswith(".pdf"):
            return "pdf_text"
        return "text_file"
        
    @traceable(name="DocumentParser", tags=["agent", "parsing"])
    async def execute(self, state: FAIRifierState) -> FAIRifierState:
        """Parse document and extract research information."""
        self.log_execution(state, "📄 Starting document parsing")
        
        try:
            # Extract text from document
            document_path = state.get("document_path", "")
            text = state.get("document_content", "")
            if "document_conversion" not in state or not isinstance(state["document_conversion"], dict):
                state["document_conversion"] = {}
            
            if text:
                self.log_execution(
                    state,
                    f"📄 Using existing document content from state ({len(text)} characters)"
                )
            else:
                self.log_execution(state, f"📖 Reading document: {document_path}")
                text, conversion_info, source = self._load_document_content(document_path, state)
                state["document_content"] = text
                if conversion_info:
                    state["document_conversion"] = conversion_info
                source_label = "MinerU Markdown" if source == "mineru" else "PDF text extraction" if source == "pdf_text" else "text file"
                self.log_execution(
                    state,
                    f"✅ Loaded {len(text)} characters ({source_label})"
                )
            
            # Extract structured information using LLM
            feedback = self.get_context_feedback(state)
            critic_feedback = feedback.get("critic_feedback")
            planner_instruction = feedback.get("planner_instruction")
            guidance_history = feedback.get("guidance_history") or []
            prior_memory_context = self.format_retrieved_memories_for_prompt(
                feedback.get("retrieved_memories") or []
            )
            
            if critic_feedback:
                self.log_execution(state, "🔄 Retrying with Critic feedback...")
                critique = critic_feedback.get("critique")
                if critique:
                    self.log_execution(state, f"   Critique: {critique}")
                for idx, suggestion in enumerate(critic_feedback.get("suggestions", []), 1):
                    self.log_execution(state, f"   🔧 Suggestion {idx}: {suggestion}")
            if guidance_history:
                self.log_execution(state, f"🧾 Historical guidance: {guidance_history}")
            
            if planner_instruction:
                self.log_execution(state, f"🧭 Planner guidance: {planner_instruction}")
            
            # Detect if we have MinerU-converted content (Markdown with better structure)
            conversion_info = state.get("document_conversion", {})
            is_mineru_content = bool(conversion_info.get("markdown_path"))
            
            if is_mineru_content:
                self.log_execution(
                    state, 
                    "🪄 Using LLM with optimized prompting for MinerU Markdown (enhanced structure extraction)..."
                )
            else:
                self.log_execution(state, "🤖 Using LLM for intelligent, adaptive extraction...")

            doc_info_dict: Dict[str, Any] = {}
            evidence_packets: List[Dict[str, Any]] = []
            use_deep_parse = config.enable_deep_agents and (
                is_mineru_content or config.llm_provider != "qwen" or len(text) <= 40000
            )
            if config.enable_deep_agents and not use_deep_parse:
                self.log_execution(
                    state,
                    "⏭️ Skipping deep ReAct parser for long unstructured Qwen input; using direct extraction for stability."
                )

            if use_deep_parse:
                science_cache = get_cache_bucket(state, "science_tools")
                task_desc = (
                    "Parse /workspace/document.md and extract concise document metadata. "
                    "Use tools when needed, preserve exact identifiers, and return only "
                    "structured metadata compatible with FAIRifier downstream agents."
                )
                self._inner_dp_agent = self._build_dp_inner_agent(
                    critic_feedback=critic_feedback,
                    planner_instruction=planner_instruction,
                    prior_memory_context=prior_memory_context or None,
                    is_structured_markdown=is_mineru_content,
                    science_cache=science_cache,
                )
                structured = await self._invoke_react_agent(
                    self._inner_dp_agent,
                    task_message=self._compose_task_message(state, task_desc),
                    seed_files=self._build_dp_seed_files(
                        text,
                        source_workspace=state.get("source_workspace", {}) or {},
                    ),
                    thread_id=f"{state.get('session_id', 'default')}-dp-inner",
                    state=state,
                    scratchpad_name=self.name,
                )
                if structured:
                    doc_info_dict = self._structured_doc_info_to_dict(structured)
                    self.log_execution(
                        state,
                        f"🧠 Deep ReAct parser extracted {len(doc_info_dict)} fields"
                    )

            if self._count_non_empty_fields(doc_info_dict) < 3:
                doc_info_dict = await self.llm_helper.extract_document_info(
                    text,
                    critic_feedback,
                    is_structured_markdown=is_mineru_content,
                    planner_instruction=planner_instruction,
                    prior_memory_context=prior_memory_context or None
                )
            
            # Remove raw_text if LLM included it (to avoid passing large text to subsequent agents)
            if "raw_text" in doc_info_dict:
                del doc_info_dict["raw_text"]
            
            # Check if extraction actually returned meaningful content
            # Count non-empty fields (flexible - works for any document type)
            non_empty_fields = self._count_non_empty_fields(doc_info_dict)
            
            # Only consider extraction failed if we got almost nothing
            is_truly_empty = non_empty_fields < 3
            
            if is_truly_empty:
                # Preserve previous document_info if this is a retry and extraction failed
                previous_doc_info = state.get("document_info", {})
                if previous_doc_info and len(previous_doc_info) > 3:
                    self.log_execution(
                        state,
                        f"⚠️ LLM extraction returned minimal result ({non_empty_fields} fields). Preserving previous extraction.",
                        "warning"
                    )
                    # Merge new fields into previous extraction
                    for key, value in doc_info_dict.items():
                        if value and (
                            (isinstance(value, str) and value.strip()) or
                            (isinstance(value, list) and len(value) > 0) or
                            (isinstance(value, dict) and len(value) > 0) or
                            (not isinstance(value, (str, list, dict)))
                        ):
                            previous_doc_info[key] = value
                    doc_info_dict = previous_doc_info
                else:
                    self.log_execution(
                        state,
                        f"⚠️ LLM extraction returned minimal result ({non_empty_fields} fields) and no previous data available.",
                        "warning"
                    )
            
            self.log_execution(state, f"✅ LLM extracted: {list(doc_info_dict.keys())}")
            self.log_execution(state, f"📊 Extracted {len(doc_info_dict)} top-level fields")
            
            # Debug: Log first few fields to verify content
            if doc_info_dict:
                sample_fields = list(doc_info_dict.items())[:3]
                for key, value in sample_fields:
                    value_preview = str(value)[:100] if value else "None"
                    self.log_execution(state, f"   - {key}: {value_preview}...")
            
            # Store in state directly as dict (without raw_text - it's already in document_content)
            state["document_info"] = doc_info_dict
            evidence_packets = build_evidence_packets(
                doc_info_dict,
                text,
                source_type=self._infer_document_source_type(is_mineru_content, document_path),
                max_packets=max(config.react_loop_document_parser_target_packets * 2, 12),
            )
            state["evidence_packets"] = evidence_packets
            self.log_execution(state, f"✅ Stored document_info in state with {len(state['document_info'])} fields")
            self.log_execution(
                state,
                f"📦 Built {len(evidence_packets)} evidence packets for downstream agents"
            )
            confidence = self._calculate_llm_confidence(doc_info_dict)
            
            self.update_confidence(state, "document_parsing", confidence)
            
            # Log extracted info
            doc_info = state["document_info"]
            authors = doc_info.get('authors', [])
            keywords = doc_info.get('keywords', [])
            self.log_execution(
                state, 
                f"✅ Parsing completed!\n"
                f"   - Title: {bool(doc_info.get('title'))}\n"
                f"   - Abstract: {bool(doc_info.get('abstract'))}\n"
                f"   - Authors: {len(authors) if authors else 0}\n"
                f"   - Keywords: {len(keywords) if keywords else 0}\n"
                f"   - Location: {doc_info.get('location', 'N/A')}\n"
                f"   - Coordinates: {doc_info.get('coordinates', 'N/A')}\n"
                f"   - Confidence: {confidence:.2%}"
            )
            
        except Exception as e:
            self.log_execution(state, f"❌ Document parsing failed: {str(e)}", "error")
            if "errors" not in state:
                state["errors"] = []
            state["errors"].append(f"Document parsing error: {str(e)}")
            self.update_confidence(state, "document_parsing", 0.0)
            # Ensure document_info exists even on error
            if "document_info" not in state:
                state["document_info"] = {"title": "Unknown", "abstract": "", "authors": [], "keywords": []}
            if "evidence_packets" not in state:
                state["evidence_packets"] = []
        
        return state
    
    def _extract_pdf_text(self, pdf_path: str) -> str:
        """Extract text from PDF using PyMuPDF."""
        doc = fitz.open(pdf_path)
        text = ""
        
        for page in doc:
            text += page.get_text()
        
        doc.close()
        return text
    
    def _load_document_content(
        self, document_path: str, state: FAIRifierState
    ) -> Tuple[str, Dict[str, Any], str]:
        """
        Load document content, preferring MinerU conversion when available.
        
        Returns:
            tuple of (text, conversion_info, source) where source is one of
            {"mineru", "pdf_text", "text_file"}.
        """
        conversion_info: Dict[str, Any] = {}
        if document_path.endswith('.pdf'):
            if self.mineru_tool:
                # Use MinerU tool for conversion
                result = self.mineru_tool.invoke({
                    "input_path": document_path,
                    "output_dir": None
                })
                
                if result["success"]:
                    # Conversion successful
                    conversion_info = {
                        "markdown_path": result["markdown_path"],
                        "output_dir": result["output_dir"],
                        "images_dir": result["images_dir"],
                        "method": result["method"]
                    }
                    self.log_execution(
                        state,
                        f"🪄 MinerU converted PDF to Markdown at {result['markdown_path']}"
                    )
                    return result["markdown_text"], conversion_info, "mineru"
                else:
                    # Conversion failed, log and fallback
                    warning_msg = f"MinerU conversion failed: {result['error']}. Falling back to local PDF extraction."
                    self.log_execution(state, f"⚠️ {warning_msg}", "warning")
                    self.logger.warning(warning_msg)
            
            text = self._extract_pdf_text(document_path)
            return text, conversion_info, "pdf_text"
        
        with open(document_path, 'r', encoding='utf-8') as file:
            text = file.read()
        return text, conversion_info, "text_file"
    
    
    def _calculate_llm_confidence(self, doc_info_dict: Dict[str, Any]) -> float:
        """Calculate confidence score for LLM-based parsing.
        
        This is a flexible heuristic based on content richness, not tied to specific fields.
        The Critic will provide a more comprehensive quality assessment.
        """
        if not doc_info_dict:
            return 0.0
        
        # Count non-empty fields at all levels
        def count_content(obj, depth=0, max_depth=3):
            """Recursively count meaningful content."""
            if depth > max_depth:
                return 0
            
            count = 0
            if isinstance(obj, dict):
                for v in obj.values():
                    if v:
                        if isinstance(v, str) and len(v.strip()) > 5:
                            count += 1
                        elif isinstance(v, (list, dict)) and len(v) > 0:
                            count += 1 + count_content(v, depth + 1, max_depth)
                        elif not isinstance(v, (str, list, dict)):
                            count += 1
            elif isinstance(obj, list):
                for item in obj:
                    if item:
                        count += count_content(item, depth + 1, max_depth)
            return count
        
        total_content = count_content(doc_info_dict)
        
        # Score based on content richness (flexible for any document type)
        if total_content >= 50:
            return 1.0
        elif total_content >= 30:
            return 0.9
        elif total_content >= 20:
            return 0.8
        elif total_content >= 10:
            return 0.6
        elif total_content >= 5:
            return 0.4
        elif total_content >= 3:
            return 0.3
        else:
            return 0.1
    
    def get_memory_query_hint(self, state: FAIRifierState) -> Optional[str]:
        """
        Generate memory query hint for DocumentParser.
        
        Focuses on: similar document types' parsing strategies, quality patterns,
        and common issues (e.g., "PDF documents <500 words often lack sufficient metadata").
        
        Args:
            state: Current workflow state
            
        Returns:
            Query hint string for memory retrieval, or None for default
        """
        doc_info = state.get("document_info", {})
        doc_type = doc_info.get("document_type", "unknown")
        source = state.get("document_source", "")
        
        # Determine file format
        file_type = "PDF" if source.lower().endswith(".pdf") else "text"
        
        # Check if we have MinerU conversion info
        conversion_info = state.get("document_conversion", {})
        has_mineru = bool(conversion_info.get("markdown_path"))
        
        # Build query focusing on parsing strategies and quality patterns
        if has_mineru:
            return (
                f"Document parsing strategies, quality patterns, and metadata extraction "
                f"best practices for {doc_type} documents in {file_type} format with structured conversion"
            )
        else:
            return (
                f"Document parsing strategies, quality patterns, and common issues "
                f"for {doc_type} documents in {file_type} format"
            )
