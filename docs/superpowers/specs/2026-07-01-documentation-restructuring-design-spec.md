# Design Specification: FAIRiAgent Documentation Restructuring

**Author**: Antigravity  
**Date**: 2026-07-01  
**Status**: Draft  

---

## 1. Objectives & Scope

The purpose of this work is to:
1. **Simplify and compact the root `README.md`**: Reduce the visual and textual bloat, remove non-illustrative drawings while preserving the first two cartoons (`wide_greetings.png` and `manga_fair.png`), and simplify long technical details (advanced `.env` tables, agent lists, and JSON examples).
2. **Preserve technical details**: Move and merge all detailed agent workflows, retry parameters, SQLite checkpointer configurations, local provisional extension snippets, and output JSON templates into `docs/en/ARCHITECTURE_AND_FLOW.md` and a newly created `docs/zh/ARCHITECTURE_AND_FLOW.md`.
3. **Enhance Getting Started and Troubleshooting**: Provide a clear, quick-start guide and common troubleshooting sections in both English and Chinese.
4. **Ensure Confidentiality**: Explicitly ignore and untrack confidential evaluation results, local datasets, and API keys.

---

## 2. Proposed Changes

### A. Root `README.md` (Bilingual & Compact)
*   **Visual Assets**: Keep `wide_greetings.png` and `manga_fair.png`. Remove `biodata_robot_fair.png` and `robot_fairdata.png`.
*   **Bilingual Format**: Organize the page with side-by-side or alternating EN/ZH sections to keep it compact.
*   **Quick Start**: Provide a simplified 3-step setup block.
*   **Troubleshooting**: Include a concise troubleshooting table (covering API keys, Ollama models, Docker network, FAIR-DS connection).
*   **Security Notice**: Add a prominent disclaimer highlighting that `.env`, `api_keys.txt`, and evaluation results are kept strictly local and ignored in version control.

### B. `docs/en/ARCHITECTURE_AND_FLOW.md` (Technical Archive)
*   Update the existing document to house the full technical details removed from the root README, including:
    *   The complete 6-Agent workflow mermaid diagram.
    *   Detailed agent node descriptions and the Critic rubric.
    *   Cross-layer rollback (ρ mechanism) and recursive batch splitting.
    *   State checkpointer SQLite connection snippets and details.
    *   Quality metrics definitions and confidence aggregator formulas.
    *   Local provisional extension code sample.
    *   Full example JSON output structures.

### C. `docs/zh/ARCHITECTURE_AND_FLOW.md` (Chinese Technical Archive)
*   Create a new Chinese equivalent of the above architecture document, translating all technical details and mermaid diagrams for Chinese developers.

### D. Documentation Navigation & Indexes
*   Update `docs/README.md` (Bilingual Index) and `docs/INDEX.md` to reference the new structure correctly.

### E. Confidentiality Verification
*   Verify that `FINAL_EVALUATION_RESULTS.md`, `FINAL_ANALYSIS_RESULTS.md`, `EXPERIMENT_SUMMARY.md`, and any temporary run results are gitignored and untracked.

---

## 3. Review Checklist

1. [x] **Placeholder scan**: No "TODO" or "TBD".
2. [x] **Internal consistency**: Links map correctly.
3. [x] **Scope check**: Focuses purely on documentation reorganization and git ignores.
4. [x] **Ambiguity check**: Clear distinction between root README (user-facing, clean) and `docs/` (developer-facing, detailed).
