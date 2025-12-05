#!/usr/bin/env python3
"""
Baseline evaluation using single-prompt LLM interaction.
This serves as a comparison against the multi-agent workflow.

This script calls the LLM once with a comprehensive prompt containing:
- The document content
- Schema requirements
- Output format instructions

No iterative refinement, no critique, no validation loops.
"""

import json
import sys
import time
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
import argparse

# Add project root to path
sys.path.insert(0, str(Path(__file__).parents[2]))

from dotenv import load_dotenv

# Import LLM helpers
from fairifier.utils.llm_helper import LLMHelper
from langchain_core.messages import HumanMessage

# Import PyMuPDF for PDF handling
try:
    import fitz  # PyMuPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


BASELINE_PROMPT_TEMPLATE = """You are a metadata extraction expert. Your task is to extract FAIR (Findable, Accessible, Interoperable, Reusable) metadata from a scientific document.

# Document Content

{document_content}

# Task

Extract metadata fields according to the MIxS (Minimum Information about any Sequence) standard. Focus on identifying:

1. **Investigation fields**: Study title, description, identifiers, contacts
2. **Study fields**: Study design, factors, protocols
3. **Sample fields**: Sample names, descriptions, collection details, environmental context
4. **Sequencing fields**: Sequencing methods, instruments, library details

# Output Format

You MUST respond with ONLY a valid JSON object (no markdown, no explanations) in this exact structure:

```json
{{
  "investigation": {{
    "investigation_identifier": "value",
    "investigation_title": "value",
    "investigation_description": "value",
    "investigation_type": "value"
  }},
  "studies": [
    {{
      "study_identifier": "value",
      "study_title": "value",
      "study_description": "value",
      "study_design_descriptors": ["value1", "value2"]
    }}
  ],
  "samples": [
    {{
      "sample_name": "value",
      "sample_description": "value",
      "collection_date": "value",
      "geographic_location": "value",
      "environment_biome": "value",
      "environment_feature": "value",
      "environment_material": "value"
    }}
  ],
  "sequencing_data": [
    {{
      "sequencing_method": "value",
      "instrument_model": "value",
      "library_strategy": "value",
      "target_gene": "value"
    }}
  ]
}}
```

# Important Instructions

1. Extract ONLY information explicitly stated in the document
2. Use "Not specified" for fields not found in the document
3. Maintain scientific accuracy
4. Use controlled vocabulary terms when possible
5. Return ONLY the JSON object, nothing else

Begin extraction now.
"""


class BaselineLLMExtractor:
    """Single-prompt baseline extractor."""
    
    def __init__(self, llm_helper: LLMHelper):
        self.llm_helper = llm_helper
        
    def extract(self, document_content: str) -> Dict[str, Any]:
        """
        Extract metadata using a single LLM call.
        
        Args:
            document_content: The document text
            
        Returns:
            Extracted metadata dict
        """
        prompt = BASELINE_PROMPT_TEMPLATE.format(
            document_content=document_content[:30000]  # Limit to ~30K chars
        )
        
        start_time = time.time()
        
        try:
            # Use asyncio to call the async _call_llm method
            # Create messages in the format expected by LLMHelper
            messages = [HumanMessage(content=prompt)]
            
            # Run async call synchronously
            response = asyncio.run(
                self.llm_helper._call_llm(
                    messages,
                    stream_to_streamlit=False,
                    operation_name="Baseline Extraction"
                )
            )
            
            # Extract content from response
            if hasattr(response, 'content'):
                raw_content = response.content
            else:
                raw_content = str(response)
            
            # Store raw response for logging
            raw_response = raw_content
            
            # Try to extract JSON from markdown code blocks if present
            if "```json" in raw_content:
                content = raw_content.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_content:
                content = raw_content.split("```")[1].split("```")[0].strip()
            else:
                content = raw_content.strip()
            
            metadata = json.loads(content)
            
            return {
                "success": True,
                "metadata": metadata,
                "raw_response": raw_response,  # Store raw response
                "duration": time.time() - start_time,
                "error": None
            }
            
        except json.JSONDecodeError as e:
            # Try to get raw response even if JSON parsing fails
            raw_response = ""
            try:
                if hasattr(response, 'content'):
                    raw_response = response.content
                else:
                    raw_response = str(response)
            except:
                pass
            
            return {
                "success": False,
                "metadata": {},
                "raw_response": raw_response,  # Store raw response even on error
                "duration": time.time() - start_time,
                "error": f"JSON parsing error: {str(e)}"
            }
        except Exception as e:
            # Try to get raw response even if extraction fails
            raw_response = ""
            try:
                if 'response' in locals() and hasattr(response, 'content'):
                    raw_response = response.content
                elif 'response' in locals():
                    raw_response = str(response)
            except:
                pass
            
            return {
                "success": False,
                "metadata": {},
                "raw_response": raw_response,  # Store raw response even on error
                "duration": time.time() - start_time,
                "error": f"Extraction error: {str(e)}"
            }


def load_document(document_path: Path) -> str:
    """Load document content, handling both PDF and text files."""
    if document_path.suffix.lower() == '.pdf':
        if not PDF_AVAILABLE:
            raise ImportError(
                "PyMuPDF (fitz) is required to read PDF files. "
                "Install it with: pip install PyMuPDF"
            )
        # Extract text from PDF using PyMuPDF
        doc = fitz.open(str(document_path))
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    else:
        # Read text files as UTF-8
        with open(document_path, 'r', encoding='utf-8') as f:
            return f.read()


def run_baseline_extraction(
    document_path: Path,
    output_dir: Path,
    config_file: Path,
    run_idx: int
) -> Dict[str, Any]:
    """
    Run a single baseline extraction.
    
    Args:
        document_path: Path to input document
        output_dir: Output directory for results
        config_file: Model configuration file
        run_idx: Run index number
        
    Returns:
        Evaluation result dict
    """
    # Load environment
    load_dotenv(config_file)
    
    # Initialize LLM helper
    llm_helper = LLMHelper()
    extractor = BaselineLLMExtractor(llm_helper)
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load document
    print(f"📄 Loading document: {document_path.name}")
    document_content = load_document(document_path)
    
    # Run extraction
    print(f"🤖 Running baseline extraction (run {run_idx})...")
    start_time = datetime.now()
    result = extractor.extract(document_content)
    end_time = datetime.now()
    
    # Save metadata JSON
    metadata_json_path = output_dir / "metadata_json.json"
    with open(metadata_json_path, 'w', encoding='utf-8') as f:
        json.dump(result["metadata"], f, indent=2, ensure_ascii=False)
    
    # Count extracted fields
    n_fields = 0
    for section in result["metadata"].values():
        if isinstance(section, dict):
            n_fields += len([v for v in section.values() if v and v != "Not specified"])
        elif isinstance(section, list):
            for item in section:
                if isinstance(item, dict):
                    n_fields += len([v for v in item.values() if v and v != "Not specified"])
    
    # Save evaluation result
    eval_result = {
        "success": result["success"],
        "document_id": document_path.stem.split("_")[0] if "_" in document_path.stem else document_path.stem,
        "config_name": config_file.stem,
        "run_idx": run_idx,
        "runtime_seconds": (end_time - start_time).total_seconds(),
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "output_dir": str(output_dir),
        "metadata_json_path": str(metadata_json_path),
        "n_fields_extracted": n_fields,
        "confidence_scores": {},
        "error": result["error"],
        "baseline_method": "single_prompt"
    }
    
    eval_result_path = output_dir / "eval_result.json"
    with open(eval_result_path, 'w', encoding='utf-8') as f:
        json.dump(eval_result, f, indent=2)
    
    # Save LLM interaction log with actual response content
    llm_responses_path = output_dir / "llm_responses.json"
    prompt_text = BASELINE_PROMPT_TEMPLATE.format(document_content=document_content[:30000])
    raw_response = result.get("raw_response", "")
    
    llm_log = {
        "interactions": [{
            "timestamp": start_time.isoformat(),
            "prompt": prompt_text,  # Save actual prompt
            "prompt_length": len(prompt_text),
            "response": raw_response,  # Save actual response
            "response_length": len(raw_response),
            "duration": result["duration"]
        }]
    }
    
    with open(llm_responses_path, 'w', encoding='utf-8') as f:
        json.dump(llm_log, f, indent=2, ensure_ascii=False)
    
    print(f"{'✅' if result['success'] else '❌'} Extraction {'succeeded' if result['success'] else 'failed'}")
    print(f"   Fields extracted: {n_fields}")
    print(f"   Duration: {result['duration']:.1f}s")
    if result["error"]:
        print(f"   Error: {result['error']}")
    
    return eval_result


def main():
    parser = argparse.ArgumentParser(
        description="Run baseline single-prompt extraction"
    )
    parser.add_argument(
        "document_path",
        type=Path,
        help="Path to input document (markdown)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory"
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        required=True,
        help="Model configuration file"
    )
    parser.add_argument(
        "--run-idx",
        type=int,
        default=1,
        help="Run index number"
    )
    
    args = parser.parse_args()
    
    result = run_baseline_extraction(
        args.document_path,
        args.output_dir,
        args.config_file,
        args.run_idx
    )
    
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()

