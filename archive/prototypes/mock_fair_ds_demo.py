#!/usr/bin/env python3
"""
Mock FAIR Data Station API Demo
Demonstrates what the integration would look like with a real FAIR-DS instance
"""

import json
from fairifier_with_api import FAIRDataStationClient, FAIRDSConfig, EnhancedKnowledgeBase, MetadataField


class MockFAIRDataStationClient:
    """Mock client that simulates FAIR Data Station API responses."""
    
    def __init__(self, config):
        self.config = config
        
    def is_available(self):
        return True
    
    def get_terms(self):
        """Return mock terms that would come from FAIR-DS."""
        return [
            {
                "id": "FAIR_DS_001",
                "name": "soil_ph_measurement", 
                "description": "pH measurement of soil sample using standardized methods",
                "label": "Soil pH",
                "category": "chemical_property"
            },
            {
                "id": "FAIR_DS_002", 
                "name": "soil_organic_carbon",
                "description": "Organic carbon content in soil expressed as percentage",
                "label": "Soil Organic Carbon",
                "category": "chemical_property"
            },
            {
                "id": "FAIR_DS_003",
                "name": "microbial_biomass_carbon",
                "description": "Microbial biomass carbon content in soil sample", 
                "label": "Microbial Biomass C",
                "category": "biological_property"
            },
            {
                "id": "FAIR_DS_004",
                "name": "soil_texture_classification",
                "description": "Classification of soil texture based on particle size distribution",
                "label": "Soil Texture",
                "category": "physical_property"
            },
            {
                "id": "FAIR_DS_005",
                "name": "fertilizer_application_rate",
                "description": "Rate of fertilizer application in agricultural systems",
                "label": "Fertilizer Rate", 
                "category": "management_practice"
            },
            {
                "id": "FAIR_DS_006",
                "name": "dna_extraction_method",
                "description": "Method used for DNA extraction from environmental samples",
                "label": "DNA Extraction Method",
                "category": "laboratory_method"
            },
            {
                "id": "FAIR_DS_007",
                "name": "sequencing_platform",
                "description": "High-throughput sequencing platform used for analysis",
                "label": "Sequencing Platform",
                "category": "laboratory_method"
            }
        ]
    
    def get_packages(self):
        """Return mock packages."""
        return [
            {
                "name": "Soil Microbiome Package",
                "description": "Comprehensive metadata package for soil microbiome studies",
                "fields": [
                    {"name": "soil_ph_measurement", "required": True},
                    {"name": "soil_organic_carbon", "required": False},
                    {"name": "microbial_biomass_carbon", "required": False}
                ]
            },
            {
                "name": "Agricultural Metagenomics Package", 
                "description": "Metadata package for agricultural metagenomics research",
                "fields": [
                    {"name": "fertilizer_application_rate", "required": True},
                    {"name": "soil_texture_classification", "required": False}
                ]
            }
        ]
    
    def search_terms(self, query):
        """Search terms based on query."""
        terms = self.get_terms()
        query_lower = query.lower()
        
        matching_terms = []
        for term in terms:
            if (query_lower in term['name'].lower() or 
                query_lower in term['description'].lower() or
                query_lower in term['label'].lower()):
                matching_terms.append(term)
        
        return matching_terms


def demo_enhanced_processing():
    """Demonstrate enhanced processing with mock FAIR-DS data."""
    print("🧬 FAIR Data Station Integration Demo")
    print("=" * 60)
    print("📡 Simulating connection to FAIR Data Station...")
    
    # Create mock client
    config = FAIRDSConfig(base_url="http://mock-fair-ds:8083")
    mock_client = MockFAIRDataStationClient(config)
    
    print("✅ Connected to FAIR Data Station (simulated)")
    
    # Test API endpoints
    print(f"\n🏷️  Available terms: {len(mock_client.get_terms())}")
    print(f"📦 Available packages: {len(mock_client.get_packages())}")
    
    # Show sample terms
    print(f"\n📋 Sample FAIR-DS terms:")
    for term in mock_client.get_terms()[:4]:
        print(f"   • {term['label']}: {term['description'][:60]}...")
    
    # Demonstrate search
    print(f"\n🔍 Searching for 'soil' terms:")
    soil_terms = mock_client.search_terms("soil")
    for term in soil_terms:
        print(f"   • {term['label']} [{term['id']}]")
    
    # Create enhanced knowledge base
    kb = EnhancedKnowledgeBase(mock_client)
    
    # Generate enhanced fields for soil research
    print(f"\n🧬 Generating enhanced metadata fields for soil research:")
    enhanced_fields = kb.get_enhanced_fields("soil")
    
    print(f"   📊 Total fields: {len(enhanced_fields)}")
    
    # Show local vs FAIR-DS fields
    local_fields = [f for f in enhanced_fields if not f.fair_ds_term]
    fair_ds_fields = [f for f in enhanced_fields if f.fair_ds_term]
    
    print(f"   📋 Local fields: {len(local_fields)}")
    print(f"   🌐 FAIR-DS enhanced fields: {len(fair_ds_fields)}")
    
    if fair_ds_fields:
        print(f"\n🏷️  FAIR-DS enhanced fields:")
        for field in fair_ds_fields:
            print(f"   • {field.name} [{field.fair_ds_term}]")
            print(f"     {field.description[:80]}...")
    
    # Generate sample YAML with FAIR-DS integration
    print(f"\n📄 Sample enhanced YAML template:")
    yaml_sample = generate_mock_yaml(enhanced_fields)
    print(yaml_sample[:800] + "..." if len(yaml_sample) > 800 else yaml_sample)


def generate_mock_yaml(fields):
    """Generate mock YAML showing FAIR-DS integration."""
    yaml_lines = [
        "# Enhanced Metadata Template with FAIR Data Station Integration",
        "# Generated: 2025-09-26",
        "# FAIR-DS terms are marked with [FAIR-DS: ID]",
        "",
        "# REQUIRED FIELDS",
        "project_name: 'Soil Microbiome Agricultural Study'",
        "investigation_type: 'metagenome'",
        "collection_date: 'July 15-20, 2023'",
        "",
        "# STANDARD FIELDS", 
        "geo_loc_name: 'USA:Iowa'",
        "lat_lon: '42.0308 -93.6319'",
        "env_biome: 'terrestrial biome'",
        "env_material: 'soil'",
        "",
        "# FAIR DATA STATION ENHANCED FIELDS"
    ]
    
    # Add FAIR-DS fields
    fair_ds_fields = [f for f in fields if f.fair_ds_term]
    for field in fair_ds_fields[:5]:  # Show first 5
        yaml_lines.append(f"{field.name} [FAIR-DS: {field.fair_ds_term}]: # {field.description}")
    
    return "\n".join(yaml_lines)


def show_integration_benefits():
    """Show the benefits of FAIR Data Station integration."""
    print(f"\n🎯 Benefits of FAIR Data Station Integration:")
    print("=" * 60)
    
    benefits = [
        "🏷️  **Standardized Terms**: Access to curated, community-approved metadata terms",
        "🔍 **Intelligent Search**: Find relevant terms based on research context",
        "📦 **Domain Packages**: Pre-configured metadata packages for specific research areas", 
        "🌐 **Interoperability**: Terms linked to established ontologies and vocabularies",
        "📊 **Quality Assurance**: Validated field definitions and data types",
        "🔄 **Live Updates**: Access to the latest metadata standards and best practices",
        "👥 **Community Driven**: Benefit from collective knowledge and expertise",
        "📈 **FAIR Compliance**: Enhanced adherence to FAIR data principles"
    ]
    
    for benefit in benefits:
        print(f"   {benefit}")
    
    print(f"\n💡 Implementation Features:")
    print("   ✅ Graceful degradation when FAIR-DS unavailable")
    print("   ✅ Caching for improved performance") 
    print("   ✅ Configurable timeout and retry logic")
    print("   ✅ Hybrid local + remote knowledge base")
    print("   ✅ Clear marking of FAIR-DS enhanced fields")


def main():
    """Main demo function."""
    demo_enhanced_processing()
    show_integration_benefits()
    
    print(f"\n🚀 Next Steps:")
    print("   1. Start FAIR Data Station: java -jar fairds-latest.jar")
    print("   2. Run: python fairifier_with_api.py your_document.pdf")
    print("   3. Enjoy enhanced metadata generation!")


if __name__ == "__main__":
    main()
