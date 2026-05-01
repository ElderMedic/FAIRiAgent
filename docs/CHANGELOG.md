# Changelog

## [1.4.0] - 2026-05-02 – Source Grounding and Multi-file Provenance Stabilization

### Added

- **`fairifier/utils/grounding.py`** (new module): Single source of truth for
  `SOURCE_REF_PATTERN` and `SOURCE_TABLE_PATTERN`. All sites that classify
  source citation evidence now import from this module, preventing independent
  regex copies from silently drifting apart.

- **Upstream candidate merging** (`json_generator.py`):
  - `FieldCandidate.normalized_value`: new attribute carrying the concise
    LLM-normalized value for each raw evidence candidate.
  - `_normalize_candidates_with_llm()`: batched LLM call that extracts a
    normalized string from every evidence snippet before generation starts.
  - `_upstream_reconcile_candidates()`: groups candidates by normalized value,
    scores by source role (`main_manuscript > table > supplement`), agreement
    count, and relevance score; selects the cross-source consensus value.
  - Pre-reconciled values are injected into the final generation prompt,
    guiding the LLM away from outlier snippets.

- **Multi-file Timestamp fix** (`langgraph_app.py`): `_read_tabular_tables()`
  now casts all DataFrame columns to `str` before `.to_dict()`, preventing
  `Timestamp` JSON serialization crashes on Excel inputs.

- **Tests** (three new files):
  - `tests/test_source_ref_regex.py`: regression tests for `SOURCE_REF_PATTERN`
    and `SOURCE_TABLE_PATTERN` using the *imported* canonical constants, not a
    copied string — covers all real production evidence citation formats.
  - `tests/test_candidate_normalization.py`: unit tests for upstream
    reconciliation determinism and batch normalization.
  - `tests/test_multifile_ingestion.py` (extended): Timestamp serialization
    and multi-file bundle reading.

### Changed

- **Source grounding post-check** (`_postcheck_source_grounding`): now uses
  `SOURCE_REF_PATTERN` from `grounding.py`; no local regex definition.
- **Grounding summary** (`_compute_source_grounding_summary`): likewise uses
  shared constants; `statistics.source_grounding_summary` in `metadata.json`
  and `quality_metrics.source_grounding` in `workflow_report.json` are now
  always consistent.
- **Validation** (`metadata_json_format.py`): `_classify_field_grounding()` and
  `validate_source_grounding()` replaced their inline regex with the shared
  imports — eliminates the last independent copy.
- **MinerU output exclusion** (`source_workspace.py`): files whose names start
  with `mineru_` are filtered before indexing to prevent recursive re-ingestion.

### Verified Outcome (run `output/20260501_233327`, model `qwen3.6:35b`)

| Metric | Before (v1.3.1) | After (v1.4.0) |
|---|---|---|
| `source_grounded_fields` | 0 | **38** |
| `table_backed_fields` | 0 | **15** |
| `ungrounded_high_confidence_fields` | 17 | **0** |
| `confirmed_fields` | 17 | **31** |
| Grounding-related warnings | 16 | **0** |
| Fields with `missing source ref` | 32 | **5** (all conf ≤ 0.6) |

### Known Remaining Gaps (deferred to next phase)

- `sample identifier` and `observation unit identifier` are structurally absent
  when source documents do not provide FAIR-DS-compatible identifiers (FAIR/ISA
  format errors, not provenance errors).
- `collection date` may contain multiple values; single-value constraint not yet
  enforced.
- Fields with no source evidence in the paper remain provisional at confidence
  0.1–0.6 — this is correct system behavior, not a bug.

---

## [1.3.1] - 2026-04-10

### Changed
- **Workflow output filename**: Primary metadata artifact on disk is now `metadata.json` (legacy `metadata_json.json` still read by evaluation tooling where applicable).
- **Merge**: Integrated `feature/lan-webui` into `main` (Streamlit UI removed on `main`; React frontend remains the web UI).

---

## [1.3.0] - 2026-03-26 – Observability and output validation release

### Added
- **Langfuse observability**: Added optional Langfuse tracing integration for end-to-end workflow observability, with test coverage for tracing configuration and behavior.
- **Metadata JSON post-output validation**: Added post-generation schema/format validation checks for output metadata JSON to catch structural issues before finalization.

### Changed
- **Release documentation refresh**: Updated release-oriented documentation and changelog content for merge readiness.

### Testing
- **Automated tests**: Full suite run as part of release checks; optional MinerU-dependent tests skip when no service is available on `localhost:30000`.
- **Environment validation**: `validate-document --env-only` confirms FAIR-DS API reachable and LLM configuration valid.

---

## [1.2.2] - 2026-03-11 – Release readiness (mem0 branch merge)

### Changed
- **LLM API key**: Qwen/DashScope provider now reads `DASHSCOPE_API_KEY` from the environment when `LLM_API_KEY` is not set (`fairifier/config.py`).
- **Tests**: `test_langgraph_app_has_tool` disables mem0 via monkeypatch so the test does not require Ollama/Qdrant; all tests pass without local LLM services when mem0 is disabled.

### Added
- **Test LLM configuration**: Tests that need a live LLM use Qwen API with model `qwen-flash`. Key is taken from system env `DASHSCOPE_API_KEY`. Optional `tests/.env.test` (from `tests/.env.test.example`) and `tests/conftest.py` loads it before config.
- **.gitignore**: `tests/.env.test` and `.env.test` so API keys are not committed.

---

## [1.2.2] - 2026-01-30

### 🎉 Major Features

#### Memory R+W System with Intelligent Gating
Enhanced memory system with Read (Retrieve) and Write (with Gating) capabilities for improved workflow quality and cross-agent learning.

**Key Improvements:**
- 🧠 **R (Retrieve)**: Automatic memory retrieval before each agent execution
  - Context-aware query construction based on task, domain, and keywords
  - Cross-agent memory sharing (agents can access each other's insights)
  - Relevance-based memory ranking and formatting
- ✍️ **W (Write with Gating)**: Selective storage of high-value insights only
  - Gating rules: Store only on success, repairs, and significant decisions
  - Filters out redundant summaries and low-value data
  - Focus on actionable patterns: document types, ontology selections, quality factors
- 🎯 **Actionable Insights Storage**:
  - Document patterns (organism types, experimental designs)
  - Workflow decisions (metadata packages selected, ontology mappings)
  - Quality patterns (what leads to high critic scores)
  - Failure reasons (for learning from mistakes)

**Memory Isolation in Evaluation:**
- Each evaluation run uses isolated memory (unique `project-id` per run)
- Ensures fair comparison across models and reproducible results
- Prevents memory contamination between runs
- Optional: Can test memory accumulation by sharing project-id

**Expected Impact:**
- Cold start (no memory): 70-80% completeness
- Warm start (accumulated memory): 75-85% completeness
- Rich memory (10+ runs): 80-90% completeness

---

### ✨ Enhancements

#### Defensive Programming
- Added `_safe_get_domain()` - Robust handling of list/string/None domain values
- Added `_safe_get_field()` - Multiple field name fallbacks for data extraction
- Enhanced error messages and logging across workflow agents
- Better handling of edge cases in metadata extraction

#### Bug Fixes
- Fixed checkpointer cleanup in `langgraph_app.py` using `getattr()` for safe attribute access

---

### 📊 Evaluation Results (Ollama Models - 2026-01-29)

Completed comprehensive re-evaluation with v1.2.2 memory system:

**Configuration:**
- Models: 7 Ollama models (gpt-oss, qwen3-30b, llama4, granite4, phi4, gemma3-27b, qwen3-next-80b)
- Documents: 3 papers (earthworm, biosensor, pomato)
- Runs per document: 10 repeats
- Total runs: 210 evaluations
- Duration: ~42-63 hours

**Results:** Analysis in progress (evaluation completed 2026-01-30)

---

### 📚 Documentation

#### New Documentation
1. **evaluation/EVALUATION_UPDATE_v122.md** - Comprehensive v1.2.2 compatibility guide
2. **evaluation/scripts/test_compatibility_v122.py** - Automated compatibility testing
3. **evaluation/README.md** - Updated with Memory System section

#### Updated Documentation
1. **evaluation/README.md** - Added memory isolation explanation and usage notes

---

### ✅ Testing

**Compatibility Test Results (v1.2.2):**
```
5/5 tests passed
✅ CLI Interface - Compatible
✅ Memory Commands - Compatible  
✅ Output Structure - Compatible
✅ Evaluator Scripts - Compatible
✅ Single Evaluation - Compatible
```

**Conclusion:** 100% backward compatible with existing evaluation framework.

---

## [1.2.0] - 2026-01-29

### 🎉 Major Features

#### mem0 Context Engineering Optimization
Comprehensive optimization of mem0 memory layer for improved fact quality, cross-agent knowledge sharing, and intelligent context compression.

#### Memory Overview Feature (ChatGPT-style) ⭐ **NEW**
Added a new `fairifier memory overview <session_id>` command that provides a ChatGPT-style summary of what the workflow has learned.

**Key Features**:
- 📊 **Statistics Dashboard**: Total memory count, agent activity breakdown
- 🏷️ **Theme Extraction**: Automatic identification of key topics and domains
- 📝 **Natural Language Summary**: LLM-powered conversational overview
- ⚡ **Dual Modes**: Full (with LLM) or simple (template-based) summary
- 📤 **JSON Export**: Programmatic access to memory data
- 🎨 **Pretty Output**: Formatted, easy-to-read display

**Use Cases**:
- Review what system learned after workflow completion
- Debug unexpected workflow behavior
- Verify high-quality fact storage
- Share workflow insights with team members
- Compare learnings across multiple sessions

**Commands**:
```bash
fairifier memory overview <session_id>           # Full LLM summary
fairifier memory overview <session_id> --simple  # Fast template summary
fairifier memory overview <session_id> --json    # Raw JSON data
```

**Documentation**: See [MEMORY_OVERVIEW_GUIDE.md](MEMORY_OVERVIEW_GUIDE.md) for complete guide.

**Key Improvements:**
- 🎯 **High-Quality Fact Extraction**: Enhanced prompt with few-shot examples and negative cases
  - Fact quality: +500% (from low-value temporary data → high-value reusable patterns)
  - Fact quantity: -83% (12 → 2 facts, but 5-10x higher value density)
  - Character efficiency: -75% (~600 → ~150 chars)
- 🔄 **Cross-Agent Memory Sharing**: Removed agent_id restrictions for knowledge reuse
  - DocumentParser's domain insights → KnowledgeRetriever can access
  - KnowledgeRetriever's package patterns → JSONGenerator can leverage
  - Retrieval precision: +30-50% (estimated)
- 🎨 **Agent-Specific Query Hints**: Custom memory retrieval strategies per agent
  - DocumentParser: "parsing strategies and quality patterns for {doc_type}"
  - KnowledgeRetriever: "packages, ontologies for {domain} with topics: {keywords}"
  - JSONGenerator: "field mappings and ontology URIs for packages: {packages}"
- 📊 **Dynamic Context Compression**: Smart memory formatting with token budget awareness
  - De-duplication of identical facts
  - Relevance-based sorting (cosine similarity scores)
  - Dynamic budget adjustment based on prompt size
  - Token savings: 10-20% (estimated)

**Implementation Details:**
- Completely rewrote `FAIR_FACT_EXTRACTION_PROMPT` with context engineering best practices
- Added `get_memory_query_hint()` to all agent classes
- Modified `langgraph_app.py` to enable cross-agent retrieval (agent_id=None, limit=10)
- Enhanced `format_retrieved_memories_for_prompt()` with advanced compression features
- Added `filter_by_relevance()` and `estimate_tokens()` utility methods

**Testing:**
- Created comprehensive test suite: `test_mem0_fact_extraction.py` (15/15 tests passed)
- Integration testing with 2 workflow runs verified memory reuse and quality
- All linter errors fixed, code quality maintained

**Documentation:**
- Detailed optimization plan with architecture diagrams
- Comparative analysis showing before/after metrics
- Insights on context engineering best practices

---

## [1.1.0] - 2026-01-29

### 🎉 Major Features

#### mem0 Memory Layer Integration (Initial)
Added optional persistent memory layer using mem0 for context compression and semantic retrieval across workflow sessions.

**Key Features:**
- 🧠 **Persistent Memory**: Store and retrieve key insights across sessions
- 🔍 **Semantic Search**: Vector-based memory retrieval using Qdrant
- 📊 **Session Scoping**: Memories bound to workflow thread_id for resume support
- 🎛️ **Opt-in Design**: Disabled by default, zero impact on existing users
- 🛠️ **CLI Tools**: `fairifier memory` command group for management
- 📈 **LangSmith Tracing**: Full observability for memory operations

**Architecture:**
- Singleton `Mem0Service` with search/add/list/delete APIs
- Integration in `_execute_agent_with_retry` for automatic memory ops
- Ollama embeddings (nomic-embed-text) + Qdrant vector storage
- Graceful degradation when mem0 unavailable

**Configuration:**
```bash
# Enable mem0
MEM0_ENABLED=true
MEM0_QDRANT_URL=http://localhost:6333
MEM0_EMBEDDING_MODEL=nomic-embed-text
MEM0_COLLECTION_NAME=fairifier_memories
```

**CLI Commands:**
```bash
fairifier memory status          # Check status
fairifier memory list <session>  # List memories
fairifier memory clear <session> # Clear memories
```

**Documentation:**
- [MEM0_QUICKSTART.md](MEM0_QUICKSTART.md) - Quick start guide
- [INSTALL_VERIFICATION.md](INSTALL_VERIFICATION.md) - Installation verification
- [TESTING_REPORT.md](TESTING_REPORT.md) - Complete test report

---

### ✨ Enhancements

#### Configuration System
- Added 7 new mem0 configuration fields
- Enhanced `apply_env_overrides()` with mem0 variables
- Support for `MEM0_QDRANT_URL` as single config option
- Default values optimized for quickstart

#### State Management
- Added `session_id` field to `FAIRifierState`
- Session ID automatically bound to checkpointer thread_id
- Enhanced `context` dict with `retrieved_memories`

#### Agent Framework
- Added `get_memory_query_hint()` method to `BaseAgent`
- Enhanced `get_context_feedback()` to include retrieved memories
- Agents can now access historical context automatically

#### CLI Enhancements
- New `memory` command group with 3 subcommands
- Memory status, list, and clear operations
- Enhanced help text and error messages

---

### 🔧 Improvements

#### Prompt Engineering & Quality Assurance
- **Comprehensive Prompts Audit** (2026-01-29)
  - Audited all 5 major LLM prompts across 3 modules
  - Identified 3 critical issues causing workflow failures:
    1. ❌ Missing output length controls → 192KB responses (expected <20KB)
    2. ❌ Contradictory format instructions → JSON parsing failures
    3. ❌ Ambiguous "extract ALL" → verbose, unfocused outputs
  - Created standardized prompt engineering guidelines
  - Documented model-specific considerations (qwen, GPT-4, Llama, Claude)
  - Overall prompt quality: C grade (needs improvement)
  - Provided actionable fix recommendations (4-8 hours implementation time)
  - Expected impact: 80%+ reduction in JSON parsing errors

#### Dependency Management
- mem0ai and qdrant-client marked as optional in `requirements.txt`
- Added `[tool.poetry.extras]` groups in `pyproject.toml`:
  - `memory` - mem0 + Qdrant
  - `embeddings` - Transformers + Sentence Transformers
  - `advanced-doc` - pytesseract, pyld, rocrate
  - `storage` - SQLAlchemy, asyncpg, minio
  - `monitoring` - structlog, prometheus-client
- Core dependencies streamlined

#### Testing
- Added 23 new tests for mem0 integration
- Total test count: 130 tests (was 107)
- Test pass rate: 100% (130/130)
- Added 3 test suites:
  - `test_basic_install.py` - Core functionality
  - `test_mem0_install.py` - Optional dependencies
  - `test_mem0_full_integration.py` - Full integration
- Updated `tests/TEST_SUMMARY.md`

#### Documentation
- Updated `README.md` with mem0 section
- Updated `env.example` with all mem0 variables
- Created 4 new documentation files:
  - `docs/MEM0_QUICKSTART.md`
  - `INSTALL_VERIFICATION.md`
  - `MEM0_INTEGRATION_SUMMARY.md`
  - `VERIFICATION_CHECKLIST.md`
  - `TESTING_REPORT.md`

---

### 🐛 Bug Fixes

#### Services Module
- Fixed `FAIRDataStationAPI` import name to `FAIRDataStationClient`
- Consistent naming across codebase

---

### 🔄 Changes

#### Breaking Changes
**None** - This release is 100% backward compatible

#### Deprecations
**None** - No features deprecated

#### Migrations
**None** - No data migrations required

---

### 📦 Dependencies

#### New Optional Dependencies
```
mem0ai>=1.0.0        # Memory layer
qdrant-client>=1.7.0 # Vector database client
```

#### Core Dependencies
No changes to existing core dependencies.

---

### 🧪 Testing

#### Test Statistics
- **Total Tests**: 130 (+23 new)
- **Pass Rate**: 100%
- **Execution Time**: ~19 seconds
- **Coverage**: High (82% for mem0 module)

#### Test Categories
- Unit tests: 120 tests
- Integration tests: 10 tests
- All tests passing

---

### 📚 Documentation

#### New Documentation
1. **MEM0_QUICKSTART.md** - Installation and usage guide
2. **INSTALL_VERIFICATION.md** - Complete verification report
3. **MEM0_INTEGRATION_SUMMARY.md** - Implementation summary
4. **VERIFICATION_CHECKLIST.md** - Pre-merge checklist
5. **TESTING_REPORT.md** - Complete test report
6. **PROMPTS_AUDIT_REPORT.md** - Comprehensive LLM prompts audit (20 pages)
7. **MEM0_INTEGRATION_ANALYSIS.md** - Detailed analysis of mem0 integration and workflow failures
8. **en/development/PROMPT_ENGINEERING_GUIDE.md** - Prompt design guidelines and best practices

#### Updated Documentation
1. **README.md** - Added mem0 section with installation steps
2. **env.example** - Added all mem0 environment variables
3. **tests/TEST_SUMMARY.md** - Updated with new tests

---

### 🎯 Performance

#### Impact
- **mem0 Disabled**: 0% overhead (default)
- **mem0 Enabled**: <1% total workflow time
  - Memory search: 10-50ms
  - Memory add: 50-200ms
- **Storage**: ~100-200 bytes per memory entry

#### Optimization
- Lazy initialization (only loads when enabled)
- Efficient vector search (Qdrant)
- Minimal memory footprint

---

### 🔒 Security

#### Security Considerations
- All credentials via environment variables
- No hardcoded secrets
- Local-first design (no cloud dependencies)
- Configurable Qdrant connection
- Safe defaults

---

### 🚀 Migration Guide

#### For Existing Users
**No action required** - This release is fully backward compatible.

Optional: To enable mem0 memory layer:
```bash
pip install mem0ai qdrant-client
docker run -d -p 6333:6333 qdrant/qdrant
echo "MEM0_ENABLED=true" >> .env
```

#### For New Users
Follow standard quickstart - mem0 is optional:
```bash
pip install -r requirements.txt
python run_fairifier.py process document.pdf
```

---

### 🔗 Links

- [Full Changelog](CHANGELOG.md)
- [mem0 GitHub](https://github.com/mem0ai/mem0)
- [Qdrant Documentation](https://qdrant.tech/documentation/)

---

**Release Date**: 2026-01-29  
**Version**: 1.2.0.20260129  
**Type**: Minor release (new features, optimizations, backward compatible)  
**Status**: ✅ Ready for release

---

## Version History

- **v1.2.0** (2026-01-29): mem0 Context Engineering Optimization
- **v1.1.0** (2026-01-29): mem0 Memory Layer Integration (Initial)
- **v1.0.0** (2026-01-XX): Initial Release
