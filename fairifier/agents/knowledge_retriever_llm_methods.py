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
    critic_feedback: Optional[Dict[str, Any]] = None
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
    # Prepare package summary for LLM (show top packages by relevance)
    pkg_summary = []
    for pkg in all_packages[:30]:  # Show top 30 packages
        pkg_summary.append({
            "name": pkg["name"],
            "field_count": pkg["field_count"],
            "mandatory": pkg["mandatory_count"],
            "optional": pkg["optional_count"],
            "sheets": pkg["sheets"],
            "sample_fields": pkg.get("sample_fields", [])[:2]
        })
    
    # Dynamically categorize packages based on API data
    package_categories = {}
    for pkg in all_packages[:50]:
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
    
    # Build dynamic package overview
    pkg_overview = f"**Available FAIR-DS Packages (from API - Total: {len(all_packages)}):**\n"
    for category, pkgs in package_categories.items():
        category_name = category.replace("_", " ").title()
        pkg_overview += f"• {category_name}: {', '.join(pkgs[:8])}"
        if len(pkgs) > 8:
            pkg_overview += f" ...and {len(pkgs) - 8} more"
        pkg_overview += "\n"
    
    system_prompt = f"""You are an expert at selecting appropriate FAIR-DS metadata packages for research data.

**Your task:** Analyze the document and select the MOST RELEVANT metadata packages from the REAL packages available in FAIR-DS API.

{pkg_overview}

**Selection principles:**
1. Match packages to the research domain and sample type
2. Select domain-specific packages based on actual API data above
3. Select method-specific packages if applicable
4. Usually 1-3 packages is optimal (avoid over-selection)
5. ONLY select from the packages listed above - these are real and current

**Think step by step:**
1. What is the research domain? (genomics, ecology, plant science, etc.)
2. What type of samples? (soil, water, organism, etc.)
3. What methods are used? (sequencing, phenotyping, etc.)
4. Which packages from the list above best match these characteristics?

Return JSON:
{{
  "selected_packages": ["package1", "package2", ...],
  "reasoning": "why these specific packages from the API are relevant"
}}

Select 1-3 most relevant packages from the available packages."""

    if critic_feedback:
        feedback_text = "\n\n**Address critic feedback:**\n"
        for issue in critic_feedback.get('issues', []):
            feedback_text += f"- {issue}\n"
        for suggestion in critic_feedback.get('suggestions', []):
            feedback_text += f"- {suggestion}\n"
        system_prompt += feedback_text

    user_prompt = f"""Document information:
{json.dumps(doc_info, indent=2, ensure_ascii=False)}

Available FAIR-DS packages:
{json.dumps(pkg_summary, indent=2)}

Select the relevant packages for this document. Return JSON."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]
    
    try:
        logger.info("Calling LLM to select relevant packages...")
        response = await llm_helper.llm.ainvoke(messages)
        
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
        logger.warning(f"Error in LLM package selection (unexpected exception): {e}")
        logger.error(f"Exception details: {type(e).__name__}")
        # Return top 3 packages from API as fallback
        default_packages = [pkg["name"] for pkg in all_packages[:3]]
        logger.warning(f"Using default packages from API (fallback): {default_packages}")
        return default_packages


async def llm_select_fields_from_package(
    llm_helper,
    doc_info: Dict[str, Any],
    package_name: str,
    mandatory_fields: List[Dict[str, Any]],
    optional_fields: List[Dict[str, Any]],
    critic_feedback: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    LLM selects relevant optional fields from a package.
    Mandatory fields are always included.
    
    Args:
        llm_helper: LLM helper instance
        doc_info: Document information
        package_name: Name of the package
        mandatory_fields: Mandatory fields (always included)
        optional_fields: Optional fields to choose from
        critic_feedback: Optional feedback
        
    Returns:
        List of selected optional field dictionaries
    """
    # For sample package with 2411 fields, we need to be selective
    # Show LLM a sample of optional fields
    if len(optional_fields) > 50:
        # Sample optional fields for LLM context
        import random
        optional_sample = random.sample(optional_fields, min(50, len(optional_fields)))
    else:
        optional_sample = optional_fields
    
    # Prepare field summaries
    mandatory_summary = [
        {"label": f.get("label"), "definition": f.get("definition")[:100]}
        for f in mandatory_fields
    ]
    
    optional_summary = [
        {"label": f.get("label"), "definition": f.get("definition")[:100]}
        for f in optional_sample
    ]
    
    system_prompt = f"""You are an expert at selecting relevant metadata fields.

**Package:** {package_name}
**Total optional fields available:** {len(optional_fields)}
**Mandatory fields:** {len(mandatory_fields)} (automatically included)

**Your task:** Select 5-15 most relevant OPTIONAL fields for this document.

**Selection criteria:**
1. Field is relevant to the document's content
2. Information for this field is likely present in the document
3. Field adds value for FAIR data principles
4. Balance between general and specific fields

**Think step by step:**
1. What is the document about?
2. Which fields match the document's domain and content?
3. Which fields can actually be filled from this document?
4. What fields are most important for findability and reusability?

Return JSON:
{{
  "selected_fields": ["field_label1", "field_label2", ...],
  "reasoning": "explanation"
}}

Select 5-15 fields. Be selective - quality over quantity."""

    if critic_feedback:
        feedback_text = "\n\n**Improve based on feedback:**\n"
        for suggestion in critic_feedback.get('suggestions', []):
            feedback_text += f"- {suggestion}\n"
        system_prompt += feedback_text

    user_prompt = f"""Document context:
- Title: {doc_info.get('title', '')[:200]}
- Domain: {doc_info.get('research_domain', '')}
- Keywords: {', '.join(doc_info.get('keywords', [])[:5])}

Mandatory fields (auto-included):
{json.dumps(mandatory_summary, indent=2)}

Optional fields to choose from:
{json.dumps(optional_summary, indent=2)}

Select 5-15 most relevant optional fields. Return JSON."""

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


async def llm_select_optional_fields(
    llm_helper,
    doc_info: Dict[str, Any],
    mandatory_fields: List[Dict[str, Any]],
    optional_fields: List[Dict[str, Any]],
    critic_feedback: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    LLM selects relevant optional fields from all collected optional fields.
    All mandatory fields are already included.
    
    Args:
        llm_helper: LLM helper instance
        doc_info: Document information
        mandatory_fields: Mandatory fields (already included)
        optional_fields: Optional fields to choose from
        critic_feedback: Optional feedback
        
    Returns:
        List of selected optional field dictionaries
    """
    # If too many optional fields, sample for LLM context
    if len(optional_fields) > 50:
        import random
        optional_sample = random.sample(optional_fields, min(50, len(optional_fields)))
    else:
        optional_sample = optional_fields
    
    # Prepare summaries
    mandatory_summary = [
        {" label": f.get("label"), "package": f.get("packageName")}
        for f in mandatory_fields[:20]
    ]
    
    optional_summary = [
        {
            "label": f.get("label"),
            "definition": f.get("definition", "")[:80],
            "package": f.get("packageName")
        }
        for f in optional_sample
    ]
    
    system_prompt = f"""You are an expert at selecting relevant metadata fields.

**Context:**
- Total mandatory fields: {len(mandatory_fields)} (already included)
- Total optional fields: {len(optional_fields)} (choose from these)
- Document domain: {doc_info.get('research_domain', 'unknown')}

**Your task:** Select 10-20 most relevant OPTIONAL fields for this document.

**Selection criteria:**
1. Field is relevant to the document's research domain
2. Information for this field is likely present in the document
3. Field adds value for FAIR data principles (findability, accessibility, etc.)
4. Balance between general and specific fields

**Think step by step:**
1. What is this research about?
2. Which optional fields match the research type?
3. Which fields can actually be filled from this document?
4. What metadata is most valuable for data reuse?

Return JSON:
{{
  "selected_fields": ["field_label1", "field_label2", ...],
  "reasoning": "explanation"
}}

Select 10-20 fields. Be selective - quality over quantity."""

    if critic_feedback:
        feedback_text = "\n\n**Address critic feedback:**\n"
        for suggestion in critic_feedback.get('suggestions', []):
            feedback_text += f"- {suggestion}\n"
        system_prompt += feedback_text

    user_prompt = f"""Document information:
{json.dumps(doc_info, indent=2, ensure_ascii=False)[:1000]}

Mandatory fields (auto-included):
{json.dumps(mandatory_summary, indent=2)}

Optional fields to choose from:
{json.dumps(optional_summary, indent=2)}

Select 10-20 most relevant optional fields. Return JSON."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]
    
    try:
        logger.info("Calling LLM to select optional fields...")
        response = await llm_helper.llm.ainvoke(messages)
        
        # Defensive checks
        if response is None:
            logger.warning("LLM returned None response for optional field selection")
            target_count = max(len(mandatory_fields), len(optional_fields) // 4)
            default_optional = optional_fields[:target_count]
            logger.warning(f"Using {len(default_optional)} optional fields from API (fallback)")
            return default_optional
        
        content = getattr(response, 'content', None)
        
        # Check if response is empty or None
        if not content or (isinstance(content, str) and not content.strip()):
            logger.warning(f"LLM returned empty response for optional field selection (content={repr(content)})")
            # Use API data directly: select enough fields to balance with mandatory
            # Calculate percentage: try to get similar number as mandatory fields
            target_count = max(len(mandatory_fields), len(optional_fields) // 4)
            default_optional = optional_fields[:target_count]
            logger.warning(f"Using {len(default_optional)} optional fields from API (fallback)")
            return default_optional
        
        # Parse response
        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM optional field selection response (JSON error): {e}")
            logger.error(f"Response content: {content[:500]}")
            # Use API data directly as fallback
            target_count = max(len(mandatory_fields), len(optional_fields) // 4)
            default_optional = optional_fields[:target_count]
            logger.warning(f"Using {len(default_optional)} optional fields from API (fallback)")
            return default_optional
        
        selected_items = result.get("selected_fields", [])
        
        # Extract labels
        selected_labels = set()
        for item in selected_items:
            if isinstance(item, str):
                selected_labels.add(item)
            elif isinstance(item, dict):
                selected_labels.add(item.get("label") or item.get("field_name") or item.get("name"))
        
        # Match back to full field objects
        selected_optional = [
            f for f in optional_fields
            if f.get("label") in selected_labels
        ]
        
        # If nothing selected, use API data
        if not selected_optional:
            logger.warning("LLM selected no optional fields, using API data")
            target_count = max(len(mandatory_fields), len(optional_fields) // 4)
            selected_optional = optional_fields[:target_count]
            logger.info(f"Using {len(selected_optional)} optional fields from API")
        
        logger.info(f"LLM selected {len(selected_optional)} optional fields from {len(optional_fields)} available")
        logger.info(f"Reasoning: {result.get('reasoning', '')[:200]}")
        
        return selected_optional
        
    except Exception as e:
        logger.warning(f"Error in LLM optional field selection (unexpected exception): {e}")
        logger.error(f"Exception details: {type(e).__name__}")
        # Use API data directly: adaptive count based on mandatory fields
        target_count = max(len(mandatory_fields), len(optional_fields) // 4)
        default_optional = optional_fields[:target_count]
        logger.warning(f"Using {len(default_optional)} optional fields from API (fallback)")
        return default_optional

