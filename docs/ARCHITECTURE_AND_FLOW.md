# FAIRiAgent System Architecture & Workflow

This document illustrates the high-level architecture and interaction flow of the **FAIRiAgent** system.

## 1. System Architecture Diagram

```mermaid
graph TD
    %% Define Styles
    classDef input fill:#f9f9f9,stroke:#333,stroke-width:2px,color:#333;
    classDef process fill:#e1f5fe,stroke:#0277bd,stroke-width:2px,color:#01579b;
    classDef decision fill:#fff9c4,stroke:#fbc02d,stroke-width:2px,color:#f57f17;
    classDef knowledge fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20;
    classDef output fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px,color:#4a148c;
    classDef agent fill:#ffebee,stroke:#c62828,stroke-width:2px,color:#b71c1c;

    %% Input Layer
    subgraph Input_Layer [📄 Input Processing]
        direction TB
        PDF["PDF Document"]:::input --> MinerU["MinerU Parser<br/>Layout Analysis & OCR"]:::process
        MinerU --> MD["Structured Markdown"]:::input
    end

    %% Knowledge Layer
    subgraph Knowledge_Layer [🧠 Knowledge Retrieval]
        direction TB
        Ontology["Ontology Database<br/>ENVO, NCBI, etc."]:::knowledge
        Schema["Schema Definitions<br/>MIxS Standards"]:::knowledge
        MD --> ContextRetriever["Context Retriever<br/>RAG System"]:::process
        Ontology -.-> ContextRetriever
        Schema -.-> ContextRetriever
    end

    %% Agentic Core
    subgraph Agentic_Core [🤖 FAIRiAgent Core Workflow]
        direction TB
        
        %% Extraction
        ContextRetriever --> Generator["Metadata Generator Agent<br/>LLM-based Extraction"]:::agent
        
        %% Validation Loop
        Generator --> JSON["Draft JSON Metadata"]:::process
        JSON --> Critic["Critic Agent<br/>Self-Reflection & Validation"]:::agent
        
        Critic --> Check{"Pass Threshold?<br/>Confidence > 0.75"}:::decision
        
        %% Feedback Loop
        Check --|No Retry| Feedback["Generate Critique &<br/>Refinement Instructions"]:::process
        Feedback --> Generator
        
        %% Finalization
        Check --|Yes| Finalizer["Format & Finalize"]:::process
    end

    %% Output Layer
    subgraph Output_Layer [💾 Standardized Output]
        direction TB
        Finalizer --> ISATab["ISA-Tab Format"]:::output
        Finalizer --> JSON_Out["Standardized JSON"]:::output
        Finalizer --> Report["Validation Report"]:::output
    end

    %% Data Flow
    Input_Layer --> Knowledge_Layer
    Knowledge_Layer --> Agentic_Core
    Agentic_Core --> Output_Layer

    %% Link Styles
    linkStyle default stroke:#666,stroke-width:2px;
```

## 2. Module Descriptions

### 📄 Input Processing (Grey)
Handles the ingestion of raw scientific documents.
*   **MinerU Parser:** A specialized tool for high-fidelity PDF-to-Markdown conversion. It preserves document structure, tables, and scientific notation, which is critical for accurate metadata extraction.

### 🧠 Knowledge Retrieval (Green)
Grounds the agent's generation in established scientific standards.
*   **Context Retriever:** Uses RAG (Retrieval-Augmented Generation) to fetch relevant schema definitions (e.g., "What is 'collection date' in MIxS?") and ontology terms (e.g., valid ENVO codes) based on the document's content.

### 🤖 FAIRiAgent Core Workflow (Red & Blue)
The "brain" of the system, implementing a reflective agentic loop.
*   **Metadata Generator Agent:** The primary LLM (e.g., GPT-4o, Claude Sonnet) that extracts metadata fields using the parsed text and retrieved knowledge.
*   **Critic Agent:** A secondary agent persona that acts as a quality gatekeeper. It evaluates the generated JSON against the schema and assigns confidence scores.
*   **Feedback Loop:** If the Critic's confidence is low (< 0.75) or validation fails, it generates specific feedback, prompting the Generator to re-evaluate and correct its output. This mimics a human "peer review" process.

### 💾 Standardized Output (Purple)
*   **Finalizer:** Converts the validated JSON into domain-specific formats like **ISA-Tab** (Investigation-Study-Assay) for direct repository submission.
