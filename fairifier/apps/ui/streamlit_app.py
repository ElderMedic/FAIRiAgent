"""Streamlit app for FAIRifier human-in-the-loop interface."""

import streamlit as st
import json
import tempfile
import os
from pathlib import Path
import asyncio
from datetime import datetime

# Add parent directories to path
import sys
sys.path.append(str(Path(__file__).parent.parent.parent.parent))

from fairifier.graph.workflow import FAIRifierWorkflow
from fairifier.config import config

st.set_page_config(
    page_title="FAIRifier - FAIR Metadata Generator",
    page_icon="🧬",
    layout="wide"
)

def main():
    st.title("🧬 FAIRifier - FAIR Metadata Generator")
    st.markdown("Automated generation of FAIR metadata from research documents")
    
    # Sidebar for navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.selectbox("Choose a page", ["Upload & Process", "Review Results", "About"])
    
    if page == "Upload & Process":
        upload_and_process_page()
    elif page == "Review Results":
        review_results_page()
    else:
        about_page()

def upload_and_process_page():
    st.header("📄 Document Upload & Processing")
    
    # File upload
    uploaded_file = st.file_uploader(
        "Upload a research document",
        type=['pdf', 'txt', 'md'],
        help="Upload a PDF, text, or markdown file containing your research information"
    )
    
    # Project name
    project_name = st.text_input(
        "Project Name (optional)",
        placeholder="Enter a name for this project"
    )
    
    if uploaded_file is not None:
        # Display file info
        st.info(f"📁 File: {uploaded_file.name} ({uploaded_file.size} bytes)")
        
        if st.button("🚀 Process Document", type="primary"):
            process_document(uploaded_file, project_name)

def process_document(uploaded_file, project_name):
    """Process the uploaded document."""
    
    with st.spinner("Processing document..."):
        try:
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = tmp_file.name
            
            # Generate project ID
            project_id = f"fairifier_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Run workflow
            workflow = FAIRifierWorkflow()
            result = asyncio.run(workflow.run(tmp_path, project_id))
            
            # Store result in session state
            st.session_state.last_result = result
            st.session_state.project_id = project_id
            st.session_state.project_name = project_name or uploaded_file.name
            
            # Display results
            display_results(result)
            
        except Exception as e:
            st.error(f"❌ Processing failed: {str(e)}")
        finally:
            # Clean up temporary file
            try:
                os.unlink(tmp_path)
            except:
                pass

def display_results(result):
    """Display processing results."""
    
    st.success("✅ Processing completed!")
    
    # Overall status
    status = result.get("status", "unknown")
    st.metric("Status", status)
    
    # Confidence scores
    confidence_scores = result.get("confidence_scores", {})
    if confidence_scores:
        st.subheader("🎯 Confidence Scores")
        cols = st.columns(len(confidence_scores))
        
        for i, (component, score) in enumerate(confidence_scores.items()):
            with cols[i % len(cols)]:
                color = "normal" if score > 0.8 else "inverse" if score < 0.6 else "off"
                st.metric(component.replace("_", " ").title(), f"{score:.2f}", delta_color=color)
    
    # Document info
    doc_info = result.get("document_info", {})
    if doc_info:
        st.subheader("📋 Extracted Information")
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("**Title:**", doc_info.get("title", "N/A"))
            st.write("**Authors:**", len(doc_info.get("authors", [])))
            st.write("**Keywords:**", len(doc_info.get("keywords", [])))
        
        with col2:
            st.write("**Research Domain:**", doc_info.get("research_domain", "N/A"))
            st.write("**Methodology:**", doc_info.get("methodology", "N/A")[:100] + "..." if doc_info.get("methodology") else "N/A")
    
    # Metadata fields
    metadata_fields = result.get("metadata_fields", [])
    if metadata_fields:
        st.subheader("🏷️ Generated Metadata Fields")
        
        required_fields = [f for f in metadata_fields if f.get("required", False)]
        optional_fields = [f for f in metadata_fields if not f.get("required", False)]
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Required Fields", len(required_fields))
        with col2:
            st.metric("Optional Fields", len(optional_fields))
        
        # Display fields in expandable sections
        if required_fields:
            with st.expander("Required Fields", expanded=True):
                for field in required_fields:
                    st.write(f"**{field['name']}** ({field['data_type']})")
                    st.write(field['description'])
                    if field.get('example_value'):
                        st.code(field['example_value'])
                    st.write("---")
        
        if optional_fields:
            with st.expander("Optional Fields"):
                for field in optional_fields[:10]:  # Show first 10
                    st.write(f"**{field['name']}** ({field['data_type']})")
                    st.write(field['description'])
                    if field.get('example_value'):
                        st.code(field['example_value'])
                    st.write("---")
    
    # Validation results
    validation = result.get("validation_results", {})
    if validation:
        st.subheader("✅ Validation Results")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            is_valid = validation.get("is_valid", False)
            st.metric("Valid", "Yes" if is_valid else "No")
        with col2:
            score = validation.get("score", 0)
            st.metric("Quality Score", f"{score:.2f}")
        with col3:
            error_count = len(validation.get("errors", []))
            st.metric("Errors", error_count)
        
        if validation.get("errors"):
            with st.expander("Validation Errors"):
                for error in validation["errors"]:
                    st.error(error)
    
    # Human review flag
    needs_review = result.get("needs_human_review", False)
    if needs_review:
        st.warning("🔍 This result requires human review before use")
    
    # Download artifacts
    artifacts = result.get("artifacts", {})
    if artifacts:
        st.subheader("📦 Download Artifacts")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if "template_yaml" in artifacts:
                st.download_button(
                    "📄 YAML Template",
                    artifacts["template_yaml"],
                    file_name="metadata_template.yaml",
                    mime="application/yaml"
                )
        
        with col2:
            if "template_schema" in artifacts:
                st.download_button(
                    "📋 JSON Schema",
                    artifacts["template_schema"],
                    file_name="metadata_schema.json",
                    mime="application/json"
                )
        
        with col3:
            if "rdf_turtle" in artifacts:
                st.download_button(
                    "🔗 RDF (Turtle)",
                    artifacts["rdf_turtle"],
                    file_name="metadata.ttl",
                    mime="text/turtle"
                )

def review_results_page():
    st.header("🔍 Review Results")
    
    if "last_result" not in st.session_state:
        st.info("No results to review. Please process a document first.")
        return
    
    result = st.session_state.last_result
    project_name = st.session_state.get("project_name", "Unknown Project")
    
    st.subheader(f"Project: {project_name}")
    
    # Show validation report
    validation_report = result.get("artifacts", {}).get("validation_report", "")
    if validation_report:
        st.subheader("📊 Validation Report")
        st.text(validation_report)
    
    # Allow editing of metadata fields
    metadata_fields = result.get("metadata_fields", [])
    if metadata_fields:
        st.subheader("✏️ Edit Metadata Fields")
        
        edited_fields = []
        for i, field in enumerate(metadata_fields):
            with st.expander(f"{field['name']} ({'Required' if field.get('required') else 'Optional'})"):
                col1, col2 = st.columns(2)
                
                with col1:
                    new_name = st.text_input(f"Field Name", value=field['name'], key=f"name_{i}")
                    new_type = st.selectbox(
                        "Data Type", 
                        ["string", "number", "datetime", "boolean"],
                        index=["string", "number", "datetime", "boolean"].index(field.get('data_type', 'string')),
                        key=f"type_{i}"
                    )
                
                with col2:
                    new_required = st.checkbox("Required", value=field.get('required', False), key=f"req_{i}")
                    new_value = st.text_input(f"Example Value", value=field.get('example_value', ''), key=f"val_{i}")
                
                new_desc = st.text_area(f"Description", value=field['description'], key=f"desc_{i}")
                
                edited_field = {
                    "name": new_name,
                    "description": new_desc,
                    "data_type": new_type,
                    "required": new_required,
                    "example_value": new_value,
                    "confidence": field.get('confidence', 0.5)
                }
                edited_fields.append(edited_field)
        
        if st.button("💾 Save Changes"):
            st.session_state.last_result["metadata_fields"] = edited_fields
            st.success("Changes saved!")

def about_page():
    st.header("ℹ️ About FAIRifier")
    
    st.markdown("""
    ## What is FAIRifier?
    
    FAIRifier is an agentic framework that automatically generates FAIR (Findable, Accessible, 
    Interoperable, Reusable) metadata from research documents.
    
    ## Features
    
    - 📄 **Document Analysis**: Extracts key information from research papers and proposals
    - 🧠 **Knowledge Enrichment**: Uses FAIR standards and ontologies to enhance metadata
    - 🏷️ **Template Generation**: Creates structured metadata templates (JSON Schema, YAML)
    - 🔗 **RDF Output**: Generates semantic web-compatible RDF graphs and RO-Crate packages
    - ✅ **Validation**: Performs SHACL validation and quality assessment
    - 👥 **Human-in-the-Loop**: Supports human review and editing of results
    
    ## Architecture
    
    FAIRifier uses a multi-agent architecture built on LangGraph:
    
    1. **Document Parser**: Extracts structured information from documents
    2. **Knowledge Retriever**: Enriches with FAIR standards and ontology terms
    3. **Template Generator**: Creates metadata templates
    4. **RDF Builder**: Generates RDF graphs and RO-Crate metadata
    5. **Validator**: Performs quality assessment and validation
    
    ## Supported Standards
    
    - MIxS (Minimum Information about any Sequence)
    - PROV-O (Provenance Ontology)
    - Schema.org
    - RO-Crate (Research Object Crate)
    - SHACL (Shapes Constraint Language)
    """)
    
    st.subheader("🛠️ Configuration")
    st.json({
        "LLM Model": config.llm_model,
        "Min Confidence": config.min_confidence_threshold,
        "Default MIxS Package": config.default_mixs_package,
        "Max Document Size": f"{config.max_document_size_mb}MB"
    })

if __name__ == "__main__":
    main()
