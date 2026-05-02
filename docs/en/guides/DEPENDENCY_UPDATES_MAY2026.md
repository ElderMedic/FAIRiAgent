# May 2026 Dependency Updates & Compatibility Analysis

## 1. Overview of Upgrades
The project's core dependencies have been brought up to date with their latest stable releases to ensure long-term security, better performance, and access to new features (such as Mem0's v3 memory algorithm and BioContainers integrations).

**Key Version Bumps:**
- `mem0ai`: `1.0.9` ➔ `2.0.1` (Major v3 API upgrade)
- `fastapi`: `0.117.1` ➔ `0.136.1`
- `uvicorn`: `0.40.0` ➔ `0.46.0`
- `pydantic`: `2.12.5` ➔ `2.13.3`
- `langchain-core`: `1.2.24` ➔ `1.3.2`
- `langgraph`: `1.1.4` ➔ `1.1.10`
- `langsmith`: `0.6.4` ➔ `0.8.0`

## 2. Compatibility Analysis & Resolutions

### 2.1 Mem0 v3 Migration
**Concern:** Mem0 released a major update (v2 to v3 architecture) that completely overhauled the retrieval algorithm (hybrid search, entity extraction) and unified the API.
**Resolution:**
- Refactored `Mem0Service` (`fairifier/services/mem0_service.py`) to align with the new API signatures.
- **Filters Migration:** Moved top-level `user_id` and `agent_id` parameters in `.search()` and `.get_all()` into the new `filters={"user_id": ..., "agent_id": ...}` dictionary schema.
- **Top-K Argument:** Migrated the legacy `limit` keyword to `top_k`.
- **Health Checks:** Preserved backward compatibility by setting `threshold=0.0` for semantic search, ensuring the system still retrieves broader contexts as designed.
- **Impact:** `100%` of the memory tests passed post-migration. The `Mem0Service` wrapper successfully abstracted the breaking changes, requiring zero changes in downstream Agents (`DocumentParser`, `Planner`, etc.).

### 2.2 FastAPI Unpinning
**Concern:** `requirements.txt` previously pinned FastAPI to `<0.118`. Bypassing this ceiling could break middleware, Pydantic model validation, or artifact downloading endpoints.
**Resolution:**
- Lifted the constraint (`>=0.104.0`) and upgraded to `0.136.1`.
- **Impact:** All API integration tests (`tests/test_api_*.py`) pass. The `MinerU` server mocks and `open_webui` forwarding endpoints remain perfectly stable. No structural routing changes were required.

### 2.3 Pydantic V2 & LangSmith Warnings
**Concern:** Upgrading Pydantic to the latest V2 release triggered massive waves of `PydanticDeprecatedSince20` warnings because LangSmith's internal telemetry was still calling `.dict()` instead of the new `.model_dump()`. This flooded the CLI and obscured Agent output.
**Resolution:**
- Implemented a targeted, global warning suppression filter in the framework's entry point (`fairifier/__init__.py`) to ignore `PydanticDeprecatedSince20`.
- **Impact:** Clean logs are restored without needing to wait for a LangSmith upstream patch.

### 2.4 Pandas Timestamp Serialization
**Concern:** The combination of new environment dependencies led to `pd.read_excel` returning timestamps in a format that broke strict ISO 8601 JSON assertions (e.g., `"2024-01-02 03:04:05"` instead of `"2024-01-02T03:04:05"`).
**Resolution:**
- Added explicit normalization in `langgraph_app.py::_read_tabular_tables()` to format all `datetime64` columns with `.dt.strftime('%Y-%m-%dT%H:%M:%S')`.

### 2.5 Conda / C++ ABI Links
**Concern:** The `mambaforge` environment exhibited `libstdc++.so.6` (CXXABI_1.3.15) symbol mismatches during runtime, breaking `sqlite3` and `mem0` initializations when spawned in background shells.
**Resolution:**
- Enforced running execution scripts with the explicit `LD_LIBRARY_PATH=/home/WUR/ke003/mambaforge/envs/FAIRiAgent/lib` to bind the correct environment libraries dynamically.

## 3. Impact on Scripts and Resources
- **Scripts:** `evaluation/scripts/run_ollama_evaluation.py` and `run_batch_evaluation.py` were audited. Nesting bugs in the output directories were squashed (no more `outputs/outputs/` nesting). 
- **Resources:** The new `mem0ai[nlp]` installation adds `spaCy`'s `en_core_web_sm` model to the environment payload, requiring slightly more disk space but unlocking Mem0's automatic entity linking.
- **Docker:** `docker/DOCKER_VERSION_1.1.0-mem0.md` was updated to reflect the `mem0ai>=2.0.1` requirement constraint.

## 4. Conclusion
The environment is exceptionally stable. The combination of targeted `Mem0` API rewrites, selective warning suppression, and path formatting ensures that the underlying FAIRiAgent logic operates without regression while fully capitalizing on the speed and reliability improvements of the 2026 Q2 ecosystem.