import os
import glob

def patch_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # The string to replace varies slightly (b1 has comments, b2/b3 don't)
    # So we replace the whole def extract_json... until the next def
    import re
    
    new_func = '''def extract_json(content: str) -> dict:
    """Extract and parse JSON from LLM response text."""
    from fairifier.utils.llm_helper import _parse_json_with_fallback
    parsed = _parse_json_with_fallback(content)
    if parsed is not None:
        return parsed
    raise ValueError("Failed to extract valid JSON from LLM response.")
'''
    
    content = re.sub(
        r'def extract_json\(content: str\) -> dict:.*?(?=\n\n\ndef normalize_to_metadata_json)',
        new_func.strip(),
        content,
        flags=re.DOTALL
    )
    
    content = re.sub(
        r'timeout: int = 1800',
        r'timeout: int = 3600',
        content
    )

    with open(filepath, 'w') as f:
        f.write(content)

    print(f"Patched {filepath}")

for script in glob.glob("evaluation/paper_experiments_v1/run_baseline_b*.py"):
    patch_file(script)

