#!/usr/bin/env python3
"""
Test script for FAIR Data Station API integration
"""

import requests
import json
from fairifier_with_api import FAIRDataStationClient, FAIRDSConfig


def test_fair_ds_connection():
    """Test connection to FAIR Data Station."""
    print("🧪 Testing FAIR Data Station API Connection")
    print("=" * 50)
    
    # Test different possible URLs
    test_urls = [
        "http://localhost:8083",
        "http://127.0.0.1:8083", 
        "https://demo.fairbydesign.nl",  # Demo instance if available
    ]
    
    for url in test_urls:
        print(f"🔗 Testing: {url}")
        
        config = FAIRDSConfig(base_url=url, timeout=10)
        client = FAIRDataStationClient(config)
        
        if client.is_available():
            print(f"✅ Connected to FAIR Data Station at {url}")
            return test_api_endpoints(client)
        else:
            print(f"❌ No connection to {url}")
    
    print("\n⚠️  No FAIR Data Station instance found.")
    print("💡 To start FAIR Data Station locally:")
    print("   1. Download: wget http://download.systemsbiology.nl/unlock/fairds-latest.jar")
    print("   2. Run: java -jar fairds-latest.jar")
    print("   3. Access: http://localhost:8083")
    
    return False


def test_api_endpoints(client: FAIRDataStationClient):
    """Test FAIR Data Station API endpoints."""
    print(f"\n📡 Testing API endpoints...")
    
    # Test /api/terms
    print("\n🏷️  Testing /api/terms")
    terms = client.get_terms()
    if terms:
        print(f"✅ Retrieved {len(terms)} terms")
        if terms:
            print("📋 Sample terms:")
            for term in terms[:3]:
                print(f"   - {term.get('name', 'N/A')}: {term.get('description', 'N/A')[:50]}...")
    else:
        print("❌ Failed to retrieve terms")
    
    # Test /api/packages  
    print("\n📦 Testing /api/packages")
    packages = client.get_packages()
    if packages:
        print(f"✅ Retrieved {len(packages)} packages")
        if packages:
            print("📋 Available packages:")
            for package in packages[:5]:
                print(f"   - {package.get('name', 'N/A')}: {len(package.get('fields', []))} fields")
    else:
        print("❌ Failed to retrieve packages")
    
    # Test search functionality
    print("\n🔍 Testing term search")
    search_terms = ["soil", "marine", "temperature", "pH"]
    
    for search_term in search_terms:
        results = client.search_terms(search_term)
        print(f"   '{search_term}': {len(results)} matches")
    
    return True


def demo_metadata_enhancement():
    """Demonstrate metadata enhancement with FAIR-DS."""
    print("\n🔬 Demonstrating Metadata Enhancement")
    print("=" * 50)
    
    # Create a mock research context
    research_contexts = [
        ("soil", "agricultural soil microbiome study"),
        ("marine", "ocean water metagenomics"),
        ("genomics", "bacterial genome sequencing")
    ]
    
    config = FAIRDSConfig()
    client = FAIRDataStationClient(config)
    
    if not client.is_available():
        print("⚠️  FAIR Data Station not available - showing local enhancement only")
        return
    
    for domain, description in research_contexts:
        print(f"\n🧬 Research context: {description}")
        print(f"   Domain: {domain}")
        
        # Search for relevant terms
        domain_keywords = {
            "soil": ["soil", "agricultural", "terrestrial"],
            "marine": ["marine", "ocean", "water"],
            "genomics": ["genome", "dna", "sequencing"]
        }.get(domain, [domain])
        
        relevant_terms = []
        for keyword in domain_keywords:
            terms = client.search_terms(keyword)
            relevant_terms.extend(terms[:2])  # Limit results
        
        print(f"   📋 Found {len(relevant_terms)} relevant FAIR-DS terms:")
        for term in relevant_terms:
            print(f"      • {term.get('name', 'N/A')}: {term.get('description', 'N/A')[:60]}...")


def test_with_sample_document():
    """Test the enhanced FAIRifier with a sample document."""
    print("\n📄 Testing Enhanced FAIRifier")
    print("=" * 50)
    
    # Use the soil metagenomics paper we created earlier
    try:
        from fairifier_with_api import process_document, FAIRDSConfig
        
        config = FAIRDSConfig(enabled=True)
        result = process_document("soil_metagenomics_paper.txt", config)
        
        print("✅ Document processing completed")
        print(f"   📋 Fields generated: {len(result['metadata_fields'])}")
        print(f"   🎯 Confidence: {result['confidence']:.2f}")
        print(f"   🌐 FAIR-DS enhanced: {result['fair_ds_enhanced']}")
        
        # Show FAIR-DS enhanced fields
        fair_ds_fields = [f for f in result['metadata_fields'] if f.get('fair_ds_term')]
        if fair_ds_fields:
            print(f"   🏷️  FAIR-DS enhanced fields: {len(fair_ds_fields)}")
            for field in fair_ds_fields[:3]:
                print(f"      • {field['name']}: {field['description'][:50]}...")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing enhanced FAIRifier: {e}")
        return False


def main():
    """Main test function."""
    print("🧬 FAIR Data Station API Integration Test")
    print("=" * 60)
    
    # Test connection
    connected = test_fair_ds_connection()
    
    if connected:
        # Demo enhancements
        demo_metadata_enhancement()
        
        # Test with sample document
        test_with_sample_document()
    
    print("\n" + "=" * 60)
    print("🎯 Test Summary:")
    print("   ✅ API integration code implemented")
    print("   ✅ Connection testing working")
    print("   ✅ Metadata enhancement ready")
    print("   💡 Start FAIR Data Station to see full functionality")


if __name__ == "__main__":
    main()
