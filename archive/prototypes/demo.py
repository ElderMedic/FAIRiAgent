#!/usr/bin/env python3
"""
FAIRifier Demo - Ultra Simple Version
Just the core concept in ~50 lines of code
"""

import re
import json
from datetime import datetime


def extract_info(text):
    """Extract basic info from text."""
    # Title (first line)
    title = text.split('\n')[0].strip()
    
    # Authors (simple pattern)
    authors_match = re.search(r'Authors?[:\s]*(.+?)(?:\n\n|\nAbstract)', text, re.IGNORECASE)
    authors = []
    if authors_match:
        authors = [a.strip() for a in re.split(r'[,&]|\sand\s', authors_match.group(1))]
    
    # Keywords  
    keywords_match = re.search(r'Keywords?[:\s]*(.+?)(?:\n\n|\nMethods)', text, re.IGNORECASE)
    keywords = []
    if keywords_match:
        keywords = [k.strip() for k in keywords_match.group(1).split(',')]
    
    # Determine domain
    text_lower = text.lower()
    domain = 'unknown'
    if any(w in text_lower for w in ['soil', 'agricultural', 'terrestrial', 'field']):
        domain = 'soil'
    elif any(w in text_lower for w in ['marine', 'ocean', 'sea', 'coastal']):
        domain = 'marine'
    elif any(w in text_lower for w in ['metagenome', 'metagenomic', 'microbiome']):
        domain = 'metagenomics'
    
    return {
        'title': title,
        'authors': authors,
        'keywords': keywords,
        'domain': domain
    }


def generate_metadata(info):
    """Generate FAIR metadata fields."""
    # Adapt fields based on domain
    if info['domain'] == 'soil':
        geo_loc = 'USA:Iowa'
        env_biome = 'terrestrial biome'
        env_material = 'soil'
    elif info['domain'] == 'marine':
        geo_loc = 'North Sea'
        env_biome = 'marine biome'
        env_material = 'sea water'
    else:
        geo_loc = 'Unknown location'
        env_biome = 'unknown biome'
        env_material = 'unknown'
    
    investigation_type = 'metagenome' if 'metagenom' in info['domain'] else 'genome'
    
    fields = [
        {'name': 'project_name', 'value': info['title'], 'required': True},
        {'name': 'investigation_type', 'value': investigation_type, 'required': True},
        {'name': 'collection_date', 'value': 'July 15-20, 2023', 'required': True},
        {'name': 'geo_loc_name', 'value': geo_loc, 'required': False},
        {'name': 'env_biome', 'value': env_biome, 'required': False},
        {'name': 'env_material', 'value': env_material, 'required': False},
    ]
    return fields


def generate_outputs(info, fields):
    """Generate JSON Schema and YAML."""
    # JSON Schema
    schema = {
        'title': info['title'],
        'type': 'object',
        'properties': {f['name']: {'type': 'string', 'description': f['name']} for f in fields},
        'required': [f['name'] for f in fields if f['required']]
    }
    
    # Simple YAML-like output
    yaml_lines = [f"# Metadata for: {info['title']}", f"# Generated: {datetime.now().strftime('%Y-%m-%d')}"]
    for field in fields:
        status = " (REQUIRED)" if field['required'] else ""
        yaml_lines.append(f"{field['name']}{status}: {field['value']}")
    
    return schema, '\n'.join(yaml_lines)


def main():
    """Demo main function."""
    # Read test document
    with open('test_document.txt', 'r') as f:
        text = f.read()
    
    print("🧬 FAIRifier Demo")
    print("=" * 30)
    
    # Process
    info = extract_info(text)
    print(f"📄 Title: {info['title'][:50]}...")
    print(f"👥 Authors: {len(info['authors'])}")
    print(f"🏷️  Keywords: {len(info['keywords'])}")
    print(f"🔬 Domain: {info['domain']}")
    
    # Generate metadata
    fields = generate_metadata(info)
    print(f"📋 Generated {len(fields)} metadata fields")
    
    # Generate outputs
    schema, yaml_output = generate_outputs(info, fields)
    
    # Save
    with open('demo_schema.json', 'w') as f:
        json.dump(schema, f, indent=2)
    
    with open('demo_template.yaml', 'w') as f:
        f.write(yaml_output)
    
    print("💾 Saved: demo_schema.json, demo_template.yaml")
    print("\n📝 Sample output:")
    print(yaml_output)


if __name__ == '__main__':
    main()
