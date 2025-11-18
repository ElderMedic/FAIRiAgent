"""
LLM methods for KnowledgeRetriever Agent

These methods use LLM to intelligently select FAIR-DS packages and fields
based on document content.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


async def llm_select_relevant_packages(
    llm_helper,
    doc_info: Dict[str, Any],
    all_packages: List[Dict[str, Any]],
    critic_feedback: Optional[Dict[str, Any]] = None,
    planner_instruction: Optional[str] = None,
) -> List[str]:
    """
    LLM determines which FAIR-DS packages are relevant for this document.
    
    Args:
        llm_helper: LLM helper instance
        doc_info: Extracted document information
        all_packages: List of all available packages with stats
        critic_feedback: Optional feedback from Critic
        
    Returns:
        List of relevant package names (e.g., ["soil", "GSC MIMAGS", "default"])
    """
    # Prepare package summary for LLM (show ALL packages - no sampling)
    pkg_summary = []
    for pkg in all_packages:  # Show ALL packages - complete information
        pkg_summary.append({
            "name": pkg["name"],
            "field_count": pkg["field_count"],
            "mandatory": pkg["mandatory_count"],
            "optional": pkg["optional_count"],
            "sheets": pkg["sheets"],
            "sample_fields": pkg.get("sample_fields", [])  # Show all sample fields
        })
    
    # Dynamically categorize packages based on API data (ALL packages)
    package_categories = {}
    for pkg in all_packages:
        name_lower = pkg["name"].lower()
        if any(x in name_lower for x in ["default", "core", "basic"]):
            package_categories.setdefault("universal", []).append(pkg["name"])
        elif any(x in name_lower for x in ["soil", "water", "air", "sediment", "marine"]):
            package_categories.setdefault("environmental", []).append(pkg["name"])
        elif any(x in name_lower for x in ["gsc", "mims", "mimag", "misag", "miuvig", "genome"]):
            package_categories.setdefault("genomics", []).append(pkg["name"])
        elif any(x in name_lower for x in ["plant", "miappe", "crop"]):
            package_categories.setdefault("plant_science", []).append(pkg["name"])
        else:
            package_categories.setdefault("other_domains", []).append(pkg["name"])
    
    # Build dynamic package overview (show ALL packages - no truncation)
    pkg_overview = f"**Available FAIR-DS Packages (from API - Total: {len(all_packages)}):**\n"
    for category, pkgs in package_categories.items():
        category_name = category.replace("_", " ").title()
        pkg_overview += f"• {category_name}: {', '.join(pkgs)}\n"  # Show ALL packages
    
    system_prompt = f"""You are an expert at selecting appropriate FAIR-DS metadata packages for research data.

**Your task:** Analyze the document and select the MOST RELEVANT metadata packages from the REAL packages available in FAIR-DS API.

{pkg_overview}

**Selection principles:**
1. Match packages to the research domain and sample type
2. Select domain-specific packages based on actual API data above
3. Select method-specific packages if applicable
4. Select at least 1 package. Choose as many as needed to fully cover the document's metadata requirements
5. There is no upper limit - use your judgment to determine the optimal number of packages
6. ONLY select from the packages listed above - these are real and current

**Think step by step:**
1. What is the research domain? (genomics, ecology, plant science, etc.)
2. What type of samples? (soil, water, organism, etc.)
3. What methods are used? (sequencing, phenotyping, etc.)
4. Which packages from the list above best match these characteristics?

**OUTPUT FORMAT - CRITICAL:**
Return ONLY valid JSON. Do NOT include:
- Markdown code blocks (no ```json or ```)
- Explanatory text before or after the JSON
- Comments or notes
- Any other content

Return ONLY the raw JSON object in this format:
{{
  "selected_packages": ["package1", "package2", ...],
  "reasoning": "why these specific packages from the API are relevant"
}}

Select at least 1 package. Choose as many as needed - there is no upper limit."""

    if critic_feedback:
        feedback_text = "\n\n**Address critic feedback:**\n"
        for issue in critic_feedback.get('issues', []):
            feedback_text += f"- {issue}\n"
        for suggestion in critic_feedback.get('suggestions', []):
            feedback_text += f"- {suggestion}\n"
        system_prompt += feedback_text
    
    if planner_instruction:
        system_prompt += f"\n\n**Planner guidance:**\n- {planner_instruction}\n"

    user_prompt = f"""Document information:
{json.dumps(doc_info, indent=2, ensure_ascii=False)}

Available FAIR-DS packages:
{json.dumps(pkg_summary, indent=2)}

Select the relevant packages for this document.

**OUTPUT FORMAT - CRITICAL:**
Return ONLY valid JSON. Prefer raw JSON without markdown code blocks.
- DO NOT include explanatory text before or after the JSON
- DO NOT include comments or notes
- If you must use markdown, use ```json code blocks (but raw JSON is preferred)
- Return ONLY the JSON content, nothing else."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]
    
    try:
        logger.info("Calling LLM to select relevant packages...")
        response = await llm_helper._call_llm(messages, operation_name="Extract Package Terms")
        
        # Defensive checks
        if response is None:
            logger.warning("LLM returned None response for package selection")
            default_packages = [pkg["name"] for pkg in all_packages[:3]]
            logger.warning(f"Using default packages from API (fallback): {default_packages}")
            return default_packages
        
        content = getattr(response, 'content', None)
        
        # Check if response is empty or None
        if not content or (isinstance(content, str) and not content.strip()):
            logger.warning(f"LLM returned empty response for package selection (content={repr(content)})")
            # Return top 3 packages from API (based on field count - already sorted)
            default_packages = [pkg["name"] for pkg in all_packages[:3]]
            logger.warning(f"Using default packages from API (fallback): {default_packages}")
            return default_packages
        
        # Parse response
        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM package selection response (JSON error): {e}")
            logger.error(f"Response content: {content[:500]}")
            # Return top 3 packages from API as fallback
            default_packages = [pkg["name"] for pkg in all_packages[:3]]
            logger.warning(f"Using default packages from API (fallback): {default_packages}")
            return default_packages
        
        selected_items = result.get("selected_packages", [])
        
        # Extract package names (could be strings or dicts)
        selected_package_names = []
        for item in selected_items:
            if isinstance(item, str):
                selected_package_names.append(item)
            elif isinstance(item, dict):
                # LLM might return {"name": "pkg", "reason": "..."} format
                pkg_name = item.get("name") or item.get("package") or item.get("package_name")
                if pkg_name:
                    selected_package_names.append(pkg_name)
        
        # If nothing selected, use top packages from API
        if not selected_package_names:
            logger.warning("LLM selected no packages, using top packages from API")
            default_packages = [pkg["name"] for pkg in all_packages[:3]]
            logger.info(f"Using default packages from API: {default_packages}")
            selected_package_names = default_packages
        
        logger.info(f"LLM selected packages: {selected_package_names}")
        logger.info(f"Reasoning: {result.get('reasoning', '')[:200]}")
        
        return selected_package_names
        
    except Exception as e:
        logger.error(f"Error in LLM package selection: {e}")
        logger.error(f"Exception details: {type(e).__name__}")
        raise  # Re-raise to trigger retry mechanism


async def llm_select_fields_from_package(
    llm_helper,
    doc_info: Dict[str, Any],
    isa_sheet: str,
    package_name: str,
    mandatory_fields: List[Dict[str, Any]],
    optional_fields: List[Dict[str, Any]],
    critic_feedback: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    LLM selects relevant optional fields from a package for a specific ISA sheet.
    Mandatory fields are always included.
    
    Args:
        llm_helper: LLM helper instance
        doc_info: Document information
        isa_sheet: ISA sheet level (investigation, study, assay, sample, observationunit)
        package_name: Name of the package
        mandatory_fields: Mandatory fields (always included)
        optional_fields: Optional fields to choose from
        critic_feedback: Optional feedback
        
    Returns:
        List of selected optional field dictionaries
    """
    # Show ALL optional fields - no sampling (complete information)
    optional_sample = optional_fields
    
    # Prepare field summaries (complete definitions - no truncation)
    mandatory_summary = [
        {"label": f.get("label"), "definition": f.get("definition")}  # Full definition
        for f in mandatory_fields
    ]
    
    optional_summary = [
        {"label": f.get("label"), "definition": f.get("definition")}  # Full definition
        for f in optional_sample
    ]
    
    # ISA sheet descriptions
    isa_descriptions = {
        "investigation": "Project/investigation-level metadata (e.g., investigation title, description, personnel, organization, funding)",
        "study": "Study-level metadata (e.g., study title, description, experimental design, objectives)",
        "assay": "Assay-level metadata (e.g., assay type, protocol, measurement technology, facility)",
        "sample": "Sample-level metadata (e.g., sample description, collection method, biological material, geographic location)",
        "observationunit": "ObservationUnit-level metadata (e.g., sampling sites, environmental context, observation units)"
    }
    
    isa_description = isa_descriptions.get(isa_sheet.lower(), f"Metadata for {isa_sheet} level")
    
    system_prompt = f"""You are an expert at selecting relevant metadata fields.

**ISA Sheet Level:** {isa_sheet.upper()}
**ISA Level Description:** {isa_description}
**Package:** {package_name}
**Total optional fields available:** {len(optional_fields)}
**Mandatory fields:** {len(mandatory_fields)} (automatically included)

**Your task:** Select at least 5 relevant OPTIONAL fields for the {isa_sheet} level based on document content.

**Selection criteria:**
1. Field is relevant to the document's content at the {isa_sheet} level
2. Information for this field is likely present in the document
3. Field adds value for FAIR data principles (findability, accessibility, interoperability, reusability)
4. Balance between general and specific fields appropriate for {isa_sheet} level

**Think step by step:**
1. What is the document about?
2. What {isa_sheet}-level information is present in the document?
3. Which fields match the document's domain and content at this ISA level?
4. Which fields can actually be filled from this document?
5. What fields are most important for findability and reusability at the {isa_sheet} level?

**OUTPUT FORMAT - CRITICAL:**
Return ONLY valid JSON. Do NOT include:
- Markdown code blocks (no ```json or ```)
- Explanatory text before or after the JSON
- Comments or notes
- Any other content

Return ONLY the raw JSON object in this format:
{{
  "selected_fields": ["field_label1", "field_label2", ...],
  "reasoning": "explanation focusing on {isa_sheet} level relevance"
}}

Select at least 5 fields. Choose as many as needed based on document content and metadata requirements. There is no upper limit - use your judgment to ensure comprehensive coverage for the {isa_sheet} level."""

    if critic_feedback:
        feedback_text = "\n\n**Improve based on feedback:**\n"
        for suggestion in critic_feedback.get('suggestions', []):
            feedback_text += f"- {suggestion}\n"
        system_prompt += feedback_text

    user_prompt = f"""Document context:
- Title: {doc_info.get('title', '')}  # Full title - no truncation
- Domain: {doc_info.get('research_domain', '')}
- Keywords: {', '.join(doc_info.get('keywords', []))}  # All keywords - no truncation

Mandatory fields (auto-included):
{json.dumps(mandatory_summary, indent=2)}

Optional fields to choose from:
{json.dumps(optional_summary, indent=2)}

Select at least 5 relevant optional fields for the {isa_sheet} level. There is no upper limit - choose as many as needed.

**OUTPUT FORMAT - CRITICAL:**
Return ONLY valid JSON. Prefer raw JSON without markdown code blocks.
- DO NOT include explanatory text before or after the JSON
- DO NOT include comments or notes
- If you must use markdown, use ```json code blocks (but raw JSON is preferred)
- Return ONLY the JSON content, nothing else."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]
    
    response = await llm_helper.llm.ainvoke(messages)
    content = response.content
    
    # Parse response
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    
    result = json.loads(content)
    selected_items = result.get("selected_fields", [])
    
    # Extract labels (could be strings or dicts)
    selected_labels = set()
    for item in selected_items:
        if isinstance(item, str):
            selected_labels.add(item)
        elif isinstance(item, dict) and "field_name" in item:
            selected_labels.add(item["field_name"])
        elif isinstance(item, dict) and "label" in item:
            selected_labels.add(item["label"])
    
    # Match labels back to full field objects
    selected_optional = [
        f for f in optional_fields
        if f.get("label") in selected_labels
    ]
    
    logger.info(f"LLM selected {len(selected_optional)} optional fields from {package_name}")
    
    return selected_optional
