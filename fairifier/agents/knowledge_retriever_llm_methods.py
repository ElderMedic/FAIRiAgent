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

**CRITICAL CONSTRAINTS:**
1. Maximum response size: 5,000 characters
2. Keep reasoning concise (< 200 characters)
3. Focus on essential package selection

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

**OUTPUT FORMAT - CRITICAL (STANDARD v1.0):**
Wrap your JSON in markdown code blocks EXACTLY like this:

```json
{{
  "selected_packages": ["package1", "package2"],
  "reasoning": "concise reason"
}}
```

REQUIREMENTS:
- Line 1: ```json (alone)
- Lines 2-N: Valid JSON only
- Line N+1: ``` (alone)
- NO text before the opening ```json
- NO text after the closing ```
- NO comments in JSON

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

**OUTPUT FORMAT - CRITICAL (STANDARD v1.0):**
Wrap your JSON in markdown code blocks:

```json
{{
  "selected_packages": ["pkg1", "pkg2"],
  "reasoning": "brief reason"
}}
```

REQUIREMENTS:
- Line 1: ```json (alone)
- Lines 2-N: Valid JSON only
- Line N+1: ``` (alone)
- NO text before/after block
- NO comments in JSON"""

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
        
        # Handle case where LLM returns a list directly instead of {"selected_packages": [...]}
        if isinstance(result, list):
            logger.warning("LLM returned a list instead of object format - extracting package names")
            selected_items = result
        else:
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
        logger.info(f"Reasoning: {(result.get('reasoning', '') if isinstance(result, dict) else '')[:200]}")
        
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
) -> Dict[str, Any]:
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
        Dict with:
        - "selected_fields": List of selected optional field dictionaries
        - "terms_to_search": List of term labels to search for additional fields
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

**CRITICAL CONSTRAINTS:**
1. Maximum response size: 10,000 characters
2. Keep reasoning concise (< 300 characters)
3. Focus on essential field selection

**ISA Sheet Level:** {isa_sheet.upper()}
**ISA Level Description:** {isa_description}
**Package:** {package_name}
**Total optional fields available:** {len(optional_fields)}
**Mandatory fields:** {len(mandatory_fields)} (automatically included)

**Your task:** Select at least 5 relevant OPTIONAL fields for the {isa_sheet} level based on document content.

**IMPORTANT - Term & Field Search Capabilities:**
The FAIR-DS API provides two search mechanisms:

1. **Term Search** (`/api/terms?label={{pattern}}`):
   - Search for metadata terms by label or definition
   - Supports partial matching (case-insensitive)
   - Returns term definitions, syntax, examples, and ontology URLs
   - Example: searching "temperature" returns "temperature", "air temperature", "water temperature", etc.

2. **Field Search** (client-side across packages):
   - Search for fields by label across all packages
   - Supports partial matching (case-insensitive)
   - Returns full field info including package, ISA sheet, and requirement level

**When to use term/field search:**
- If the document mentions a specific metadata term that is not in the current optional fields list
- If you need domain-specific fields that might be in other packages
- If you want to ensure comprehensive coverage by searching for related fields
- If you need to find the correct terminology for a concept (e.g., "sampling date" vs "collection date")

**Selection criteria:**
1. Field is relevant to the document's content at the {isa_sheet} level
2. Information for this field is likely present in the document
3. Field adds value for FAIR data principles (findability, accessibility, interoperability, reusability)
4. Balance between general and specific fields appropriate for {isa_sheet} level
5. If a needed field is missing, you can request it by name for the system to search

**Think step by step:**
1. What is the document about?
2. What {isa_sheet}-level information is present in the document?
3. Which fields match the document's domain and content at this ISA level?
4. Which fields can actually be filled from this document?
5. What fields are most important for findability and reusability at the {isa_sheet} level?
6. Are there any specific metadata terms mentioned in the document that are not in the optional fields list? If so, note them for field search.

**OUTPUT FORMAT - CRITICAL (STANDARD v1.0):**
Wrap your JSON in markdown code blocks EXACTLY like this:

```json
{{
  "selected_fields": ["field1", "field2"],
  "terms_to_search": ["term1"],
  "reasoning": "brief explanation"
}}
```

REQUIREMENTS:
- Line 1: ```json (alone)
- Lines 2-N: Valid JSON only
- Line N+1: ``` (alone)
- NO text before the opening ```json
- NO text after the closing ```
- NO comments in JSON
- Reasoning: < 300 characters

**Fields format:**
- `selected_fields`: List of field labels from the optional fields list above
- `terms_to_search`: (OPTIONAL) List of terms/field names to search for if not in the current list
- `reasoning`: Brief explanation (< 300 chars)

**Example:**
```json
{{
  "selected_fields": ["field1", "field2"],
  "terms_to_search": ["soil temperature"],
  "reasoning": "Fields match document's soil analysis focus at {isa_sheet} level"
}}
```

Select at least 5 fields. Choose as many as needed - there is no upper limit."""

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

**Term/Field Search Available:**
If you need a specific field that is NOT in the optional fields list above, you can request it in the `terms_to_search` array. The system will:
1. Search `/api/terms` for matching term definitions
2. Search across all packages for fields with matching labels

Examples of when to use term/field search:
- Document mentions "soil temperature" but it's not in the list → add to `terms_to_search`
- Document mentions "pH" or "acidity" but it's not in the list → add to `terms_to_search`
- You need domain-specific fields that might be in other packages → add to `terms_to_search`
- You want to find the standard FAIR-DS terminology for a concept → add to `terms_to_search`

Select at least 5 relevant optional fields for the {isa_sheet} level. There is no upper limit - choose as many as needed.

**OUTPUT FORMAT - CRITICAL (STANDARD v1.0):**
Wrap your JSON in markdown code blocks:

```json
{{
  "selected_fields": ["field1", "field2"],
  "terms_to_search": ["term1"],
  "reasoning": "brief reason"
}}
```

REQUIREMENTS:
- Line 1: ```json (alone)
- Lines 2-N: Valid JSON only
- Line N+1: ``` (alone)
- NO text before/after block
- NO comments in JSON
- Include `terms_to_search` array if needed"""

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
    # Handle LLM returning a list (e.g. phi4) instead of {"selected_fields": [...], "terms_to_search": [...]}
    if isinstance(result, list):
        logger.warning("LLM returned a list instead of object format - using as selected_fields")
        selected_items = result
        terms_to_search = []
    else:
        selected_items = result.get("selected_fields", [])
        terms_to_search = result.get("terms_to_search", [])
    
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
    
    if terms_to_search:
        logger.info(f"LLM requested term search for: {terms_to_search}")
    
    # Return both selected fields and terms to search
    return {
        "selected_fields": selected_optional,
        "terms_to_search": terms_to_search
    }
