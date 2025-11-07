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
            response = await self.llm.ainvoke(messages)
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
            logger.error(f"Response content: {content[:500]}")
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
            response = await self.llm.ainvoke(messages)
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
        
        # Prepare available fields summary
        fields_summary = []
        for field in available_fields[:50]:  # Limit for context
            fields_summary.append({
                "name": field.get("name", ""),
                "description": field.get("description", "")[:100],
                "package": field.get("metadata", {}).get("package", "")
            })
        
        system_prompt = """You are an expert at selecting appropriate metadata fields for scientific research data.

**Your task:** Analyze the document and intelligently select the MOST RELEVANT metadata fields from the available options.

**Principles:**
1. Match fields to actual document content - don't select fields for information that isn't present
2. Prioritize fields that capture the core information of this specific study
3. Consider the research domain and adapt field selection accordingly
4. Include both core bibliographic fields and domain-specific fields
5. Select 15-25 fields - enough for comprehensive metadata but not overwhelming

**Selection criteria:**
- Relevance to the document's content and domain
- Availability of information in the document
- FAIR principles - findability, accessibility, interoperability, reusability
- Balance between general and specific fields

Return JSON with:
{
  "selected_fields": [
    {"field_name": "...", "reason": "why this field is relevant"}
  ],
  "rationale": "overall selection strategy"
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

Available metadata fields:
{json.dumps(fields_summary, indent=2)}

Select the most appropriate 15-25 metadata fields for this document. Return JSON."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self.llm.ainvoke(messages)
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

**Your task:** For each metadata field, extract or generate an appropriate value from the document.

**Principles:**
1. Extract values directly from document when possible
2. Generate appropriate values when information is implicit
3. Provide clear evidence/provenance for each value
4. Assign realistic confidence scores (0.0-1.0)
5. Be honest - use null or "not specified" if information truly isn't available

**For each field, provide:**
- value: The actual metadata value (be specific and accurate)
- evidence: Where/how you determined this value (quote or describe)
- confidence: Float 0.0-1.0 (1.0 = explicitly stated, 0.5 = inferred, 0.0 = unknown)

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

        user_prompt = f"""Document information:
{json.dumps(document_info, indent=2, ensure_ascii=False)}

Document excerpt:
{document_text[:3000]}

Metadata fields to populate:
{json.dumps(field_descriptions, indent=2)}

**IMPORTANT:** Use the EXACT field_name from the list above. Do not modify or abbreviate field names.

For each field, extract or generate appropriate values. Return JSON array:
[
  {{
    "field_name": "...",  // MUST match exactly one of the field_name values above
    "value": "...",
    "evidence": "...",
    "confidence": 0.X
  }},
  ...
]"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self.llm.ainvoke(messages)
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
        system_prompt = """You are an expert quality evaluator.
Evaluate the provided content against the given criteria.

Return JSON with:
- overall_score: Float 0-1
- passed_criteria: List of criteria that passed
- failed_criteria: List of criteria that failed
- issues: List of specific issues found (empty list if none)
- suggestions: List of specific improvement suggestions (empty list if none)
- decision: "ACCEPT", "RETRY", or "ESCALATE"

IMPORTANT: Always include 'issues' and 'suggestions' as arrays (can be empty).

Return ONLY valid JSON."""

        criteria_text = "\n".join(f"- {c}" for c in criteria)
        
        user_prompt = f"""Evaluate this content:

{content}

Criteria:
{criteria_text}

{f"Context: {context}" if context else ""}

Provide detailed evaluation as JSON with issues and suggestions arrays."""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = await self.llm.ainvoke(messages)
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


def get_llm_helper() -> LLMHelper:
    """Get or create the global LLM helper instance."""
    global _llm_helper
    if _llm_helper is None:
        _llm_helper = LLMHelper()
    return _llm_helper


def save_llm_responses(output_path: Path, llm_helper: Optional[LLMHelper] = None):
    """Save LLM responses to file for debugging."""
    if llm_helper is None:
        llm_helper = get_llm_helper()
    
    responses_file = output_path / "llm_responses.json"
    with open(responses_file, 'w', encoding='utf-8') as f:
        json.dump(llm_helper.llm_responses, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Saved {len(llm_helper.llm_responses)} LLM responses to {responses_file}")

