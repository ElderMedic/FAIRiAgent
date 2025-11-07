"""
LLM Helper - Centralized LLM interaction utilities.

Provides a unified interface for working with different LLM providers
(Ollama, OpenAI, Anthropic) and common LLM operations.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langsmith import traceable

# Import providers conditionally
try:
    from langchain_ollama import ChatOllama
except ImportError:
    ChatOllama = None

try:
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None

try:
    from langchain_anthropic import ChatAnthropic
except ImportError:
    ChatAnthropic = None

from ..config import config

logger = logging.getLogger(__name__)


class LLMHelper:
    """Helper class for LLM interactions."""
    
    def __init__(self):
        self.provider = config.llm_provider
        self.model = config.llm_model
        self.llm = self._initialize_llm()
        self.llm_responses = []  # Store all LLM interactions for debugging
    
    async def _call_llm(self, messages, stream_to_streamlit=None, operation_name="LLM Call"):
        """Helper method to call LLM with proper parameters.
        
        Supports both thinking and non-thinking modes.
        For Qwen models, enable_thinking is passed via extra_body as per official docs.
        
        Args:
            messages: List of messages to send to LLM
            stream_to_streamlit: If True, stream output to Streamlit container (if available).
                                If None, auto-detect if Streamlit container is available.
            operation_name: Name of the operation for display purposes.
        """
        enable_thinking = config.llm_enable_thinking
        
        # Extract prompt preview for display
        prompt_preview = ""
        if messages:
            last_message = messages[-1]
            if hasattr(last_message, 'content'):
                prompt_preview = last_message.content[:500] if last_message.content else ""
        
        # Extract agent name from operation_name
        agent_name = "System"
        if "DocumentParser" in operation_name or "parse" in operation_name.lower():
            agent_name = "📄 Document Parser"
        elif "KnowledgeRetriever" in operation_name or "retrieve" in operation_name.lower() or "package" in operation_name.lower():
            agent_name = "🔍 Knowledge Retriever"
        elif "JSONGenerator" in operation_name or "generate" in operation_name.lower() or "json" in operation_name.lower():
            agent_name = "📝 JSON Generator"
        elif "Critic" in operation_name or "evaluate" in operation_name.lower() or "critic" in operation_name.lower():
            agent_name = "🎯 Critic"
        elif "Orchestrator" in operation_name or "plan" in operation_name.lower() or "workflow" in operation_name.lower():
            agent_name = "🎼 Orchestrator"
        
        # Auto-detect Streamlit chat container if stream_to_streamlit is None
        chat_container = None
        message_id = None
        if stream_to_streamlit is None:
            # Try to detect if we're in Streamlit mode
            try:
                from fairifier.apps.ui.streamlit_app import get_streamlit_chat_container
                chat_container = get_streamlit_chat_container()
                stream_to_streamlit = chat_container is not None
                if stream_to_streamlit:
                    # Create a new chat message
                    from fairifier.apps.ui.streamlit_app import create_chat_message
                    _, message_id = create_chat_message(agent_name, operation_name)
            except (ImportError, AttributeError):
                stream_to_streamlit = False
        elif stream_to_streamlit:
            # Explicitly requested streaming
            try:
                from fairifier.apps.ui.streamlit_app import get_streamlit_chat_container, create_chat_message
                chat_container = get_streamlit_chat_container()
                if chat_container:
                    # Create a new chat message
                    _, message_id = create_chat_message(agent_name, operation_name)
            except (ImportError, AttributeError):
                chat_container = None
                stream_to_streamlit = False
        
        # For Qwen provider, use extra_body as per official documentation
        if self.provider == "qwen":
            if enable_thinking or stream_to_streamlit:
                # Thinking mode or streaming mode: use streaming
                try:
                    # Use bind with extra_body for Qwen (as per official docs)
                    llm_with_params = self.llm.bind(
                        extra_body={"enable_thinking": True if enable_thinking else False},
                        stream=True
                    )
                    # Collect streaming response
                    content_parts = []
                    full_text = ""
                    
                    async for chunk in llm_with_params.astream(messages):
                        if hasattr(chunk, 'content') and chunk.content:
                            content = chunk.content
                            content_parts.append(content)
                            full_text += content
                            
                            # Stream to Streamlit chat if available
                            if message_id:
                                try:
                                    from fairifier.apps.ui.streamlit_app import update_chat_message
                                    update_chat_message(message_id, full_text, is_streaming=True)
                                except Exception:
                                    pass  # Ignore errors in Streamlit update
                    
                    # Finalize chat message (remove cursor)
                    if message_id:
                        try:
                            from fairifier.apps.ui.streamlit_app import finalize_chat_message
                            finalize_chat_message(message_id)
                        except Exception:
                            pass
                    
                    # Create a response-like object
                    result = AIMessage(content=full_text)
                    
                    # Add to Streamlit display if available
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        add_llm_response(operation_name, prompt_preview, full_text)
                    except (ImportError, AttributeError):
                        pass
                    
                    return result
                except Exception as e:
                    logger.warning(f"Streaming failed: {e}, trying non-streaming")
                    # If streaming doesn't work, try non-streaming
                    try:
                        llm_with_params = self.llm.bind(
                            extra_body={"enable_thinking": True if enable_thinking else False}
                        )
                        result = await llm_with_params.ainvoke(messages)
                        # Add to Streamlit display
                        try:
                            from fairifier.apps.ui.streamlit_app import add_llm_response
                            content = result.content if hasattr(result, 'content') else str(result)
                            add_llm_response(operation_name, prompt_preview, content)
                        except (ImportError, AttributeError):
                            pass
                        return result
                    except Exception as e2:
                        logger.warning(f"Non-streaming failed: {e2}, falling back to regular call")
                        result = await self.llm.ainvoke(messages)
                        # Add to Streamlit display
                        try:
                            from fairifier.apps.ui.streamlit_app import add_llm_response
                            content = result.content if hasattr(result, 'content') else str(result)
                            add_llm_response(operation_name, prompt_preview, content)
                        except (ImportError, AttributeError):
                            pass
                        return result
            else:
                # Non-thinking mode: ensure enable_thinking=False
                # Qwen3 open-source models require this for non-streaming calls
                try:
                    llm_with_params = self.llm.bind(
                        extra_body={"enable_thinking": False}
                    )
                    result = await llm_with_params.ainvoke(messages)
                    # Add to Streamlit display
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        content = result.content if hasattr(result, 'content') else str(result)
                        add_llm_response(operation_name, prompt_preview, content)
                    except (ImportError, AttributeError):
                        pass
                    return result
                except Exception as e:
                    logger.warning(f"Failed to set enable_thinking=False via extra_body: {e}, using regular call")
                    result = await self.llm.ainvoke(messages)
                    # Add to Streamlit display
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        content = result.content if hasattr(result, 'content') else str(result)
                        add_llm_response(operation_name, prompt_preview, content)
                    except (ImportError, AttributeError):
                        pass
                    return result
        elif self.provider == "openai":
            # For OpenAI provider, support streaming if requested
            if stream_to_streamlit:
                try:
                    llm_with_params = self.llm.bind(stream=True)
                    content_parts = []
                    full_text = ""
                    
                    async for chunk in llm_with_params.astream(messages):
                        if hasattr(chunk, 'content') and chunk.content:
                            content = chunk.content
                            content_parts.append(content)
                            full_text += content
                            
                            # Stream to Streamlit chat if available
                            if message_id:
                                try:
                                    from fairifier.apps.ui.streamlit_app import update_chat_message
                                    update_chat_message(message_id, full_text, is_streaming=True)
                                except Exception:
                                    pass
                    
                    # Finalize chat message (remove cursor)
                    if message_id:
                        try:
                            from fairifier.apps.ui.streamlit_app import finalize_chat_message
                            finalize_chat_message(message_id)
                        except Exception:
                            pass
                    
                    result = AIMessage(content=full_text)
                    # Add to Streamlit display
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        add_llm_response(operation_name, prompt_preview, full_text)
                    except (ImportError, AttributeError):
                        pass
                    return result
                except Exception as e:
                    logger.warning(f"OpenAI streaming failed: {e}, falling back to regular call")
                    result = await self.llm.ainvoke(messages)
                    # Add to Streamlit display
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        content = result.content if hasattr(result, 'content') else str(result)
                        add_llm_response(operation_name, prompt_preview, content)
                    except (ImportError, AttributeError):
                        pass
                    return result
            else:
                result = await self.llm.ainvoke(messages)
                # Add to Streamlit display
                try:
                    from fairifier.apps.ui.streamlit_app import add_llm_response
                    content = result.content if hasattr(result, 'content') else str(result)
                    add_llm_response(operation_name, prompt_preview, content)
                except (ImportError, AttributeError):
                    pass
                return result
        elif self.provider == "ollama":
            # Ollama supports streaming
            if stream_to_streamlit:
                try:
                    llm_with_params = self.llm.bind(stream=True)
                    content_parts = []
                    full_text = ""
                    
                    async for chunk in llm_with_params.astream(messages):
                        if hasattr(chunk, 'content') and chunk.content:
                            content = chunk.content
                            content_parts.append(content)
                            full_text += content
                            
                            # Stream to Streamlit chat if available
                            if message_id:
                                try:
                                    from fairifier.apps.ui.streamlit_app import update_chat_message
                                    update_chat_message(message_id, full_text, is_streaming=True)
                                except Exception:
                                    pass
                    
                    # Finalize chat message (remove cursor)
                    if message_id:
                        try:
                            from fairifier.apps.ui.streamlit_app import finalize_chat_message
                            finalize_chat_message(message_id)
                        except Exception:
                            pass
                    
                    result = AIMessage(content=full_text)
                    # Add to Streamlit display
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        add_llm_response(operation_name, prompt_preview, full_text)
                    except (ImportError, AttributeError):
                        pass
                    return result
                except Exception as e:
                    logger.warning(f"Ollama streaming failed: {e}, falling back to regular call")
                    result = await self.llm.ainvoke(messages)
                    # Add to Streamlit display
                    try:
                        from fairifier.apps.ui.streamlit_app import add_llm_response
                        content = result.content if hasattr(result, 'content') else str(result)
                        add_llm_response(operation_name, prompt_preview, content)
                    except (ImportError, AttributeError):
                        pass
                    return result
            else:
                result = await self.llm.ainvoke(messages)
                # Add to Streamlit display
                try:
                    from fairifier.apps.ui.streamlit_app import add_llm_response
                    content = result.content if hasattr(result, 'content') else str(result)
                    add_llm_response(operation_name, prompt_preview, content)
                except (ImportError, AttributeError):
                    pass
                return result
        else:
            # For other providers (anthropic), no special handling needed
            result = await self.llm.ainvoke(messages)
            
            # Add to Streamlit display if available
            try:
                from fairifier.apps.ui.streamlit_app import add_llm_response
                content = result.content if hasattr(result, 'content') else str(result)
                add_llm_response(operation_name, prompt_preview, content)
            except (ImportError, AttributeError):
                pass
            
            return result
        
    def _initialize_llm(self):
        """Initialize LLM based on provider configuration.
        
        Supported providers:
        - ollama: Local Ollama instance (default)
        - openai: OpenAI API (gpt-4, gpt-3.5-turbo, etc.)
        - qwen: Alibaba Cloud Qwen API (OpenAI-compatible)
        - anthropic: Anthropic Claude API
        """
        if self.provider == "ollama":
            if ChatOllama is None:
                raise ImportError("langchain_ollama not installed. Install with: pip install langchain-ollama")
            logger.info(f"Initializing Ollama LLM: {self.model} at {config.llm_base_url}")
            return ChatOllama(
                model=self.model,
                base_url=config.llm_base_url,
                temperature=config.llm_temperature,
            )
        elif self.provider == "openai":
            if ChatOpenAI is None:
                raise ImportError("langchain_openai not installed. Install with: pip install langchain-openai")
            if not config.llm_api_key:
                raise ValueError("LLM_API_KEY environment variable is required for OpenAI provider")
            base_url = config.llm_base_url if config.llm_base_url != "http://localhost:11434" else None
            logger.info(f"Initializing OpenAI LLM: {self.model}" + (f" at {base_url}" if base_url else ""))
            # Initialize ChatOpenAI
            # For OpenAI, enable_thinking is not a standard parameter
            return ChatOpenAI(
                model=self.model,
                api_key=config.llm_api_key,
                base_url=base_url,  # None uses default OpenAI API
                temperature=config.llm_temperature,
            )
        elif self.provider == "qwen":
            if ChatOpenAI is None:
                raise ImportError("langchain_openai not installed. Install with: pip install langchain-openai")
            if not config.llm_api_key:
                raise ValueError("LLM_API_KEY environment variable is required for Qwen provider")
            # Qwen uses OpenAI-compatible API
            base_url = config.llm_base_url
            logger.info(f"Initializing Qwen LLM: {self.model} at {base_url}")
            # Initialize ChatOpenAI for Qwen
            # Note: enable_thinking is passed via extra_body in _call_llm, not here
            # This is because extra_body needs to be set per-call, not at initialization
            return ChatOpenAI(
                model=self.model,
                api_key=config.llm_api_key,
                base_url=base_url,
                temperature=config.llm_temperature,
            )
        elif self.provider == "anthropic" or self.provider == "claude":
            if ChatAnthropic is None:
                raise ImportError("langchain_anthropic not installed. Install with: pip install langchain-anthropic")
            if not config.llm_api_key:
                raise ValueError("LLM_API_KEY environment variable is required for Anthropic provider")
            logger.info(f"Initializing Anthropic Claude LLM: {self.model}")
            return ChatAnthropic(
                model=self.model,
                api_key=config.llm_api_key,
                temperature=config.llm_temperature,
            )
        else:
            raise ValueError(
                f"Unsupported LLM provider: {self.provider}. "
                f"Supported providers: ollama, openai, qwen, anthropic (claude)"
            )
    
    @traceable(name="LLM.ExtractDocumentInfo")
    async def extract_document_info(self, text: str, critic_feedback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Extract structured information from document text using LLM.
        Self-adapts based on document content and critic feedback.
        
        Args:
            text: Document text content
            critic_feedback: Optional feedback from Critic agent for improvement
            
        Returns:
            Dictionary containing extracted information
        """
        # Truncate text if too long (keep first 8000 chars)
        if len(text) > 8000:
            text = text[:8000] + "\n\n[... text truncated ...]"
        
        # Build adaptive system prompt
        system_prompt = """You are an expert at extracting structured information from scientific research documents.

**Your task:** Analyze the document and extract ALL relevant information intelligently. DO NOT limit yourself to predefined fields - adapt to the document's content.

**Core principles:**
1. Read and understand the document type and domain
2. Identify what information is actually present and relevant
3. Extract information in appropriate categories
4. Use clear, descriptive field names that match the content
5. Be flexible - different documents contain different information

**Always include (if present):**
- Basic bibliographic info (title, authors, publication details)
- Research context (domain, objectives, questions)
- Methodology and approach
- Data and samples (what, where, when, how)
- Results and findings
- Any domain-specific details (sequences, chemicals, coordinates, etc.)

**Output format:**
Return a JSON object with descriptive field names. For example:
- Instead of just "location", use specific names like "sampling_location", "study_site", "geographic_region"
- For environmental data, create nested structures: "environmental_conditions": {"temperature": "...", "pH": "..."}
- Group related information logically

**Adapt to document content:** If it's a genomics study, extract sequencing details. If it's field ecology, extract environmental parameters. If it's a methods paper, focus on protocols.

Return ONLY valid JSON, no markdown formatting."""

        # Add critic feedback if available
        if critic_feedback:
            feedback_text = f"\n\n**Previous attempt feedback:**\n"
            for issue in critic_feedback.get('issues', []):
                feedback_text += f"- Issue: {issue}\n"
            for suggestion in critic_feedback.get('suggestions', []):
                feedback_text += f"- Suggestion: {suggestion}\n"
            system_prompt += feedback_text

        user_prompt = f"""Analyze and extract information from this research document:

{text}

Think step by step:
1. What type of document is this? (research paper, dataset description, protocol, etc.)
2. What scientific domain does it belong to?
3. What key information does it contain?
4. What metadata would be most valuable for FAIR data principles?

Extract all relevant information and return as JSON with clear, descriptive field names."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self._call_llm(messages, operation_name="Extract Document Info")
            content = response.content
            
            # Store interaction for debugging
            self.llm_responses.append({
                "operation": "extract_document_info",
                "prompt_length": len(text),
                "response": content
            })
            
            # Parse JSON response
            # Remove markdown code blocks if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            doc_info = json.loads(content)
            
            logger.info(f"Extracted document info with {len(doc_info)} fields")
            return doc_info
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Error position: {getattr(e, 'pos', 'unknown')}")
            logger.error(f"Response content (first 1000 chars): {content[:1000]}")
            
            # Try to extract partial JSON or fix common issues
            try:
                # Try to find JSON object start
                json_start = content.find('{')
                if json_start >= 0:
                    error_pos = getattr(e, 'pos', len(content))
                    
                    # Strategy 1: Try to extract complete JSON up to error
                    # Find the last complete key-value pair before error
                    partial_content = content[json_start:error_pos]
                    
                    # Try to find last complete property (ends with , or })
                    # Look for pattern: "key": value followed by comma or closing brace
                    import re
                    # Find all complete properties
                    property_pattern = r'"([^"]+)":\s*([^,}]+?)(?=,\s*"|})'
                    matches = list(re.finditer(property_pattern, partial_content))
                    
                    if matches:
                        # Get the last complete property
                        last_match = matches[-1]
                        # Extract up to and including this property
                        end_pos = last_match.end()
                        # Find the comma or closing brace after this property
                        remaining = partial_content[end_pos:]
                        if remaining.startswith(','):
                            end_pos += 1
                        elif remaining.startswith('}'):
                            end_pos += 1
                        
                        # Extract the partial JSON
                        partial_json = partial_content[:end_pos]
                        
                        # Close any open braces
                        open_braces = partial_json.count('{') - partial_json.count('}')
                        if open_braces > 0:
                            partial_json += '}' * open_braces
                        elif open_braces < 0:
                            # Too many closing braces, remove them
                            partial_json = partial_json.rstrip('}')
                            open_braces = partial_json.count('{') - partial_json.count('}')
                            partial_json += '}' * open_braces
                        
                        # Try parsing the fixed JSON
                        try:
                            fixed_doc_info = json.loads(partial_json)
                            logger.warning(
                                f"Successfully extracted partial JSON with "
                                f"{len(fixed_doc_info)} fields from truncated response"
                            )
                            return fixed_doc_info
                        except json.JSONDecodeError:
                            logger.warning("Partial JSON extraction still failed")
                    
                    # Strategy 2: Try to extract JSON from first complete object
                    # Find the first complete JSON object
                    brace_count = 0
                    complete_end = -1
                    for i, char in enumerate(partial_content):
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                complete_end = i + 1
                                break
                    
                    if complete_end > 0:
                        complete_json = partial_content[:complete_end]
                        try:
                            fixed_doc_info = json.loads(complete_json)
                            logger.warning(
                                f"Successfully extracted complete JSON object with "
                                f"{len(fixed_doc_info)} fields"
                            )
                            return fixed_doc_info
                        except json.JSONDecodeError:
                            logger.warning("Complete JSON object extraction failed")
                            
            except Exception as fix_error:
                logger.warning(f"Failed to fix JSON: {fix_error}")
            
            # If all fixes fail, return minimal structure but log the full response
            logger.error(f"Full response content (truncated to 2000 chars): {content[:2000]}")
            # Return minimal structure
            return {
                "title": "",
                "abstract": "",
                "authors": [],
                "keywords": [],
                "research_domain": None
            }
        except Exception as e:
            logger.error(f"Error during document info extraction: {e}")
            raise
    
    @traceable(name="LLM.GenerateMetadataValue")
    async def generate_metadata_value(
        self,
        field_name: str,
        field_description: str,
        document_info: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate a value for a metadata field based on document info.
        
        Args:
            field_name: Name of the metadata field
            field_description: Description of what the field should contain
            document_info: Extracted document information
            context: Additional context (retrieved knowledge, etc.)
            
        Returns:
            Dict with 'value', 'evidence', and 'confidence'
        """
        system_prompt = """You are an expert at generating FAIR metadata values from research documents.
Given a field description and document information, generate an appropriate value.

Return JSON with:
- value: The generated value
- evidence: Brief explanation of where/how you determined this value
- confidence: Float 0-1 indicating your confidence

Return ONLY valid JSON."""

        user_prompt = f"""Generate a value for this metadata field:

Field: {field_name}
Description: {field_description}

Document Information:
{json.dumps(document_info, indent=2)}

{"Context: " + json.dumps(context, indent=2) if context else ""}

Return JSON with value, evidence, and confidence."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self._call_llm(messages, operation_name="Generate Metadata Value")
            content = response.content
            
            # Store interaction
            self.llm_responses.append({
                "operation": "generate_metadata_value",
                "field": field_name,
                "response": content
            })
            
            # Parse JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            
            # Ensure required fields
            if "value" not in result:
                result["value"] = ""
            if "evidence" not in result:
                result["evidence"] = f"Generated from {field_name}"
            if "confidence" not in result:
                result["confidence"] = 0.5
            
            return result
            
        except Exception as e:
            logger.error(f"Error generating metadata value for {field_name}: {e}")
            return {
                "value": "",
                "evidence": f"Error: {str(e)}",
                "confidence": 0.0
            }
    
    @traceable(name="LLM.SelectRelevantFields")
    async def select_relevant_metadata_fields(
        self,
        document_info: Dict[str, Any],
        available_fields: List[Dict[str, Any]],
        critic_feedback: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Intelligently select relevant metadata fields based on document content.
        Adapts based on critic feedback.
        
        Args:
            document_info: Extracted document information
            available_fields: All available metadata fields from FAIR-DS
            critic_feedback: Optional feedback for improvement
            
        Returns:
            List of selected field dictionaries with rationale
        """
        # Prepare document summary
        doc_summary = {
            "title": document_info.get("title", "")[:200],
            "domain": document_info.get("research_domain", ""),
            "keywords": document_info.get("keywords", [])[:10],
            "type": document_info.get("document_type", "unknown")
        }
        
        # Group fields by ISA sheet to ensure balanced selection across ISA levels
        isa_sheets = ["investigation", "study", "assay", "sample", "observationunit"]
        fields_by_isa = {sheet: [] for sheet in isa_sheets}
        
        for field in available_fields:
            isa_sheet = field.get("isa_sheet", "study")
            if isa_sheet in fields_by_isa:
                fields_by_isa[isa_sheet].append(field)
            else:
                # Fallback to study if unknown
                fields_by_isa["study"].append(field)
        
        # Prepare available fields summary, grouped by ISA sheet
        fields_summary_by_isa = {}
        for sheet in isa_sheets:
            fields_summary_by_isa[sheet] = []
            # Show ALL fields for each ISA sheet (no truncation)
            for field in fields_by_isa[sheet]:
                fields_summary_by_isa[sheet].append({
                    "name": field.get("name", ""),
                    "description": field.get("description", "")[:200],  # Increased limit
                    "package": field.get("metadata", {}).get("package", ""),
                    "required": field.get("required", False)
                })
        
        # Count fields per ISA sheet
        field_counts = {sheet: len(fields_by_isa[sheet]) for sheet in isa_sheets}
        
        system_prompt = """You are an expert at selecting appropriate metadata fields for scientific research data.

**Your task:** Analyze the document and intelligently select the MOST RELEVANT metadata fields from the available options, ensuring balanced coverage across ISA hierarchy levels.

**ISA Hierarchy:**
- **Investigation**: Project/investigation-level metadata (e.g., investigation title, description, investigators)
- **Study**: Study-level metadata (e.g., study title, description, experimental design)
- **Assay**: Assay-level metadata (e.g., assay type, protocol, measurement technology)
- **Sample**: Sample-level metadata (e.g., sample description, collection method, biological material)
- **ObservationUnit**: ObservationUnit-level metadata (e.g., sampling sites, environmental context)

**Principles:**
1. Match fields to actual document content - don't select fields for information that isn't present
2. Prioritize fields that capture the core information of this specific study
3. Consider the research domain and adapt field selection accordingly
4. Include both core bibliographic fields and domain-specific fields
5. **IMPORTANT**: Ensure balanced selection across ISA hierarchy levels - select fields from multiple ISA sheets, not just one
6. Select 20-30 fields total - enough for comprehensive metadata but not overwhelming

**Selection criteria:**
- Relevance to the document's content and domain
- Availability of information in the document
- FAIR principles - findability, accessibility, interoperability, reusability
- Balance between general and specific fields
- **Balance across ISA hierarchy levels** - don't focus only on one ISA sheet

Return JSON with:
{
  "selected_fields": [
    {"field_name": "...", "reason": "why this field is relevant"}
  ],
  "rationale": "overall selection strategy, including ISA level balance"
}"""

        if critic_feedback:
            feedback_text = f"\n\n**Improve based on feedback:**\n"
            for issue in critic_feedback.get('issues', []):
                feedback_text += f"- {issue}\n"
            for suggestion in critic_feedback.get('suggestions', []):
                feedback_text += f"- {suggestion}\n"
            system_prompt += feedback_text

        user_prompt = f"""Document summary:
{json.dumps(doc_summary, indent=2)}

Available metadata fields by ISA sheet:
{json.dumps(fields_summary_by_isa, indent=2)}

Field counts per ISA sheet:
{json.dumps(field_counts, indent=2)}

**IMPORTANT**: Select fields from MULTIPLE ISA sheets to ensure balanced coverage. Don't focus only on one ISA level.

Select the most appropriate 20-30 metadata fields for this document, ensuring representation across ISA hierarchy levels. Return JSON."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self._call_llm(messages, operation_name="Select Relevant Fields")
            content = response.content
            
            self.llm_responses.append({
                "operation": "select_relevant_fields",
                "document": doc_summary,
                "response": content
            })
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
            selected = result.get("selected_fields", [])
            
            # Match selected field names back to full field objects
            selected_field_names = {f["field_name"] for f in selected}
            matched_fields = [f for f in available_fields if f.get("name") in selected_field_names]
            
            logger.info(f"Selected {len(matched_fields)} relevant fields out of {len(available_fields)}")
            return matched_fields
            
        except Exception as e:
            logger.error(f"Error selecting relevant fields: {e}")
            # Fallback: return first 20 fields
            return available_fields[:20]
    
    @traceable(name="LLM.GenerateMetadataJSON")
    async def generate_complete_metadata(
        self,
        document_info: Dict[str, Any],
        selected_fields: List[Dict[str, Any]],
        document_text: str,
        critic_feedback: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate complete metadata for all selected fields.
        Adapts based on document content and critic feedback.
        
        Args:
            document_info: Extracted document information
            selected_fields: Selected metadata fields
            document_text: Full document text (truncated)
            critic_feedback: Optional feedback for improvement
            
        Returns:
            List of metadata field dictionaries with values
        """
        # Truncate document text
        if len(document_text) > 6000:
            document_text = document_text[:6000] + "\n[... truncated ...]"
        
        system_prompt = """You are an expert at generating FAIR metadata from research documents.

**Your task:** For EACH AND EVERY metadata field in the list, extract or generate an appropriate value from the document.

**CRITICAL REQUIREMENTS:**
1. **MUST generate a value for ALL fields** - You must return a value for every single field in the provided list, no exceptions
2. **Investigation-level fields** (e.g., investigation title, investigation description) - These are project-level metadata. Extract from document title, abstract, or generate from research context
3. **Study-level fields** (e.g., study title, study description) - These describe the specific study. Extract from document title, abstract, methods, or results
4. **Assay-level fields** - These describe measurement methods. Extract from methods section
5. **Sample-level fields** - These describe biological material. Extract from methods or results
6. **ObservationUnit-level fields** - These describe sampling sites. Extract from methods or environmental context

**Principles:**
1. Extract values directly from document when possible
2. Generate appropriate values when information is implicit (e.g., investigation title can be derived from document title)
3. Provide clear evidence/provenance for each value
4. Assign realistic confidence scores (0.0-1.0)
5. If information truly isn't available, use "not specified" or null, but STILL include the field in your response

**For each field, provide:**
- field_name: MUST match exactly one of the field names in the provided list
- value: The actual metadata value (be specific and accurate, or "not specified" if unavailable)
- evidence: Where/how you determined this value (quote or describe the source)
- confidence: Float 0.0-1.0 (1.0 = explicitly stated, 0.7-0.9 = strongly inferred, 0.4-0.6 = reasonably inferred, 0.0-0.3 = not available)

**IMPORTANT:** 
- You MUST return a JSON array with exactly the same number of fields as provided in the input list
- Do NOT skip any fields, even if information is limited
- For investigation/study fields: If not explicitly stated, derive from document title, abstract, or research context
- For fields with limited information, use "not specified" as the value but still include the field

Return JSON array of metadata objects."""

        if critic_feedback:
            feedback_text = f"\n\n**Address these issues:**\n"
            for issue in critic_feedback.get('issues', []):
                feedback_text += f"- {issue}\n"
            for suggestion in critic_feedback.get('suggestions', []):
                feedback_text += f"- {suggestion}\n"
            system_prompt += feedback_text

        # Prepare field descriptions
        field_descriptions = []
        for field in selected_fields:
            field_descriptions.append({
                "field_name": field.get("name", ""),  # Use exact field name from FAIR-DS
                "description": field.get("description", ""),
                "required": field.get("required", False)
            })

        # Group fields by ISA sheet for better context
        isa_sheets = ["investigation", "study", "assay", "sample", "observationunit"]
        fields_by_isa = {sheet: [] for sheet in isa_sheets}
        for field in selected_fields:
            isa_sheet = field.get("isa_sheet", "study")
            if isa_sheet in fields_by_isa:
                fields_by_isa[isa_sheet].append(field)
            else:
                fields_by_isa["study"].append(field)
        
        # Count fields per ISA sheet
        field_counts = {sheet: len(fields_by_isa[sheet]) for sheet in isa_sheets}
        
        user_prompt = f"""Document information:
{json.dumps(document_info, indent=2, ensure_ascii=False)}

Document excerpt:
{document_text[:3000]}

Metadata fields to populate (TOTAL: {len(selected_fields)} fields):
{json.dumps(field_descriptions, indent=2)}

Fields by ISA hierarchy:
{json.dumps(field_counts, indent=2)}

**CRITICAL REQUIREMENTS:**
1. You MUST return a JSON array with EXACTLY {len(selected_fields)} fields - one for each field in the list above
2. Use the EXACT field_name from the list above. Do not modify or abbreviate field names
3. **Investigation-level fields** ({field_counts.get('investigation', 0)} fields): Must generate values from document title, abstract, or research context
4. **Study-level fields** ({field_counts.get('study', 0)} fields): Must generate values from document title, abstract, methods, or results
5. **Assay-level fields** ({field_counts.get('assay', 0)} fields): Must generate values from methods section
6. **Sample-level fields** ({field_counts.get('sample', 0)} fields): Must generate values from methods or results
7. **ObservationUnit-level fields** ({field_counts.get('observationunit', 0)} fields): Must generate values from methods or environmental context

**For fields where information is not explicitly stated:**
- Investigation/Study fields: Derive from document title, abstract, or research context (e.g., investigation title = document title, study title = document title)
- Other fields: Use "not specified" as value but STILL include the field in your response

Return JSON array with EXACTLY {len(selected_fields)} fields:
[
  {{
    "field_name": "...",  // MUST match exactly one of the field_name values above
    "value": "...",  // Actual value or "not specified" if unavailable
    "evidence": "...",  // Where/how you determined this value
    "confidence": 0.X  // Float 0.0-1.0
  }},
  ...  // MUST include ALL {len(selected_fields)} fields
]"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self._call_llm(messages, operation_name="Generate Complete Metadata")
            content = response.content
            
            self.llm_responses.append({
                "operation": "generate_metadata",
                "field_count": len(selected_fields),
                "response": content
            })
            
            if not content or not content.strip():
                logger.warning("LLM returned empty response for generate_complete_metadata")
                return [
                    {
                        "field_name": f.get("name", ""),
                        "value": "",
                        "evidence": "LLM returned empty response",
                        "confidence": 0.0
                    }
                    for f in selected_fields[:10]
                ]
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            metadata = json.loads(content)
            
            logger.info(f"Generated metadata for {len(metadata)} fields")
            return metadata if isinstance(metadata, list) else [metadata]
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Response content: {content[:500]}")
            # Return basic structure
            return [
                {
                    "field_name": f.get("name", ""),
                    "value": "",
                    "evidence": f"JSON parsing error: {str(e)}",
                    "confidence": 0.0
                }
                for f in selected_fields[:10]
            ]
        except Exception as e:
            logger.error(f"Error generating metadata: {e}")
            # Return basic structure
            return [
                {
                    "field_name": f.get("name", ""),
                    "value": "",
                    "evidence": f"Error during generation: {str(e)}",
                    "confidence": 0.0
                }
                for f in selected_fields[:10]
            ]
    
    @traceable(name="LLM.EvaluateQuality")
    async def evaluate_quality(
        self,
        content: str,
        criteria: List[str],
        context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluate quality of content against criteria.
        
        Args:
            content: Content to evaluate
            criteria: List of quality criteria
            context: Additional context for evaluation
            
        Returns:
            Dict with evaluation results (always includes issues and suggestions)
        """
        # Get thresholds from config
        accept_threshold = config.critic_accept_threshold_general
        retry_min = config.critic_retry_min_threshold
        retry_max = config.critic_retry_max_threshold
        
        system_prompt = f"""You are an expert quality evaluator for scientific metadata extraction.
Evaluate the provided content against the given criteria.

**Evaluation Principles:**
1. Assess what IS present, not what is missing - focus on the quality of extracted information
2. Be realistic - if information is not in the source document, don't penalize heavily
3. Consider the extraction quality: Are extracted fields accurate and complete based on available source?
4. Distinguish between:
   - Missing information that was never in the source (minor issue)
   - Incorrect or incomplete extraction from available source (major issue)
   - Poor quality or truncated values (major issue)

**Scoring Guidelines:**
- overall_score: 0.8-1.0 = Excellent extraction quality, all available information captured well
- overall_score: 0.6-0.79 = Good extraction, minor gaps or issues
- overall_score: 0.4-0.59 = Acceptable but needs improvement
- overall_score: 0.0-0.39 = Poor quality, significant issues

**Decision Guidelines:**
- ACCEPT: overall_score >= {accept_threshold} AND extraction quality is good (even if some info missing from source)
- RETRY: overall_score {retry_min}-{retry_max} OR extraction quality can be improved
- ESCALATE: overall_score < {retry_min} OR critical errors in extraction

Return JSON with:
- overall_score: Float 0-1 (based on extraction quality, not completeness of source)
- passed_criteria: List of criteria that passed
- failed_criteria: List of criteria that failed
- issues: List of specific issues found (empty list if none)
- suggestions: List of specific improvement suggestions (empty list if none)
- decision: "ACCEPT", "RETRY", or "ESCALATE"

IMPORTANT: Always include 'issues' and 'suggestions' as arrays (can be empty).

Return ONLY valid JSON."""

        criteria_text = "\n".join(f"- {c}" for c in criteria)
        
        user_prompt = f"""Evaluate this extracted content:

{content}

Criteria to evaluate:
{criteria_text}

{f"Context: {context}" if context else ""}

**Important:** Evaluate the QUALITY of extraction, not whether the source document contains all ideal information.
- If information is missing because it's not in the source document, note it but don't heavily penalize
- If information is incorrectly extracted or truncated, this is a quality issue
- Focus on: Are the extracted fields accurate, complete, and well-structured based on what was available?

Provide detailed evaluation as JSON with issues and suggestions arrays."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self._call_llm(messages, operation_name="Evaluate Quality")
            response_content = getattr(response, 'content', None)
            
            # Store interaction
            self.llm_responses.append({
                "operation": "evaluate_quality",
                "criteria_count": len(criteria),
                "response": response_content
            })
            
            # Check if response is empty
            if not response_content or not response_content.strip():
                logger.warning("LLM returned empty response for evaluate_quality, using default")
                return {
                    "overall_score": 0.5,
                    "passed_criteria": [],
                    "failed_criteria": criteria,
                    "issues": ["LLM returned empty response"],
                    "suggestions": ["Retry evaluation"],
                    "decision": "RETRY"
                }
        except Exception as e:
            logger.error(f"Error during LLM evaluation: {e}")
            return {
                "overall_score": 0.3,
                "passed_criteria": [],
                "failed_criteria": criteria,
                "issues": [f"LLM call failed: {str(e)}"],
                "suggestions": ["LLM service error, retry needed"],
                "decision": "RETRY"
            }
        
        # Parse JSON
        try:
            if "```json" in response_content:
                response_content = response_content.split("```json")[1].split("```")[0].strip()
            elif "```" in response_content:
                response_content = response_content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(response_content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Response content: {response_content[:500]}")
            # Return default structure
            return {
                "overall_score": 0.5,
                "passed_criteria": [],
                "failed_criteria": criteria,
                "issues": [f"JSON parsing error: {str(e)}"],
                "suggestions": ["LLM response format invalid, retry needed"],
                "decision": "RETRY"
            }
        
        # Ensure required fields always exist
        if "issues" not in result:
            result["issues"] = result.get("failed_criteria", [])
        if "suggestions" not in result:
            result["suggestions"] = []
        if "decision" not in result:
            result["decision"] = "ACCEPT"
        if "overall_score" not in result:
            result["overall_score"] = 0.5
        
        return result


# Global instance
_llm_helper = None
_last_provider = None
_last_model = None
_last_base_url = None


def get_llm_helper(force_reinit=False) -> LLMHelper:
    """Get or create the global LLM helper instance.
    
    Args:
        force_reinit: If True, force reinitialization even if instance exists.
                     This is useful when configuration has changed.
    """
    global _llm_helper, _last_provider, _last_model, _last_base_url
    
    # Check if we need to reinitialize due to config changes
    current_provider = config.llm_provider
    current_model = config.llm_model
    current_base_url = config.llm_base_url
    
    needs_reinit = (
        force_reinit or
        _llm_helper is None or
        _last_provider != current_provider or
        _last_model != current_model or
        _last_base_url != current_base_url
    )
    
    if needs_reinit:
        _llm_helper = LLMHelper()
        _last_provider = current_provider
        _last_model = current_model
        _last_base_url = current_base_url
        logger.info(f"🔄 Reinitialized LLMHelper: provider={current_provider}, model={current_model}, base_url={current_base_url}")
    
    return _llm_helper


def reset_llm_helper():
    """Reset the global LLM helper instance (force reinitialization on next call)."""
    global _llm_helper, _last_provider, _last_model, _last_base_url
    _llm_helper = None
    _last_provider = None
    _last_model = None
    _last_base_url = None


def save_llm_responses(output_path: Path, llm_helper: Optional[LLMHelper] = None):
    """Save LLM responses to file for debugging."""
    if llm_helper is None:
        llm_helper = get_llm_helper()
    
    responses_file = output_path / "llm_responses.json"
    with open(responses_file, 'w', encoding='utf-8') as f:
        json.dump(llm_helper.llm_responses, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Saved {len(llm_helper.llm_responses)} LLM responses to {responses_file}")

