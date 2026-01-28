# FAIRiAgent Cleanup Plan - Post Tools Refactor

**Date**: 2026-01-29  
**Context**: After LangChain tools refactor completion

## Issues Identified

### 1. Duplicate Test Runners ⚠️
- **Problem**: `run_tests.py` and `run_tests.sh` provide identical functionality
- **Impact**: Maintenance burden, confusion for developers
- **Recommendation**: **Keep `run_tests.py`** (cross-platform), **remove `run_tests.sh`**
- **Rationale**: Python script works on all platforms (Windows/macOS/Linux)

### 2. Test Integration Script Location ⚠️
- **Problem**: `test_tools_integration.py` in root directory
- **Impact**: Inconsistent test organization
- **Recommendation**: **Move to `tests/test_tools_integration.py`**
- **Rationale**: All tests should be in `tests/` directory

### 3. Outdated Test Counts ⚠️
- **Problem**: `run_tests.py` line 136: says "67 tests", actually 107 tests
- **Impact**: Misleading documentation
- **Recommendation**: **Update to "107 tests"**

### 4. Test Scripts to Keep ✅
- **`quick_test.sh`** - Keep (unique end-to-end testing with env checks)
- **`run_tests.py`** - Keep (primary test runner)
- **`run_fairifier.py`** - Keep (main CLI entry point)
- **`start_*.sh`** - Keep (UI launch scripts)
- **`install_webui_deps.sh`** - Keep (setup script)

## Actions Required

### Phase 1: Test Script Cleanup
- [x] Identify duplicate functionality
- [ ] Update test counts in `run_tests.py`
- [ ] Move `test_tools_integration.py` to `tests/`
- [ ] Remove `run_tests.sh`
- [ ] Update any references to `run_tests.sh` in docs

### Phase 2: Code Quality Check
- [ ] Check for unused imports in modified files
- [ ] Verify all tools are properly exported in `__init__.py`
- [ ] Check CLI commands for tools-related updates
- [ ] Verify README documentation

### Phase 3: Documentation Updates
- [ ] Update README with tools information
- [ ] Update test documentation
- [ ] Verify ARCHITECTURE docs mention tools

## Detailed Actions

### Action 1: Update run_tests.py test count
```python
# Line 136
print_header("Running All Tests (107 tests)")  # Changed from 67
```

### Action 2: Move integration test
```bash
git mv test_tools_integration.py tests/test_tools_integration.py
```

### Action 3: Remove duplicate test runner
```bash
git rm run_tests.sh
```

### Action 4: Update .gitignore if needed
Check if any new patterns should be ignored (tool-related temp files)

## Files to Review

### Modified in Tools Refactor
- ✅ `fairifier/agents/knowledge_retriever.py` - Uses tools now
- ✅ `fairifier/agents/document_parser.py` - Uses MinerU tool
- ✅ `fairifier/graph/langgraph_app.py` - Uses MinerU tool
- ✅ `fairifier/tools/` - All new files

### May Need Updates
- [ ] `README.md` - Mention tools architecture?
- [ ] `docs/en/ARCHITECTURE_AND_FLOW.md` - Document tools layer?
- [ ] `fairifier/cli.py` - system-info command mention tools?

## Validation Checklist

After cleanup:
- [ ] All 107 tests still pass
- [ ] Integration test runs from new location
- [ ] No broken references to removed files
- [ ] Documentation is updated
- [ ] Git history is clean

## Migration Guide (for users)

### Before
```bash
# Old way
./run_tests.sh all
./run_tests.sh fast
```

### After
```bash
# New way (works on all platforms)
python run_tests.py all
python run_tests.py fast

# Or use pytest directly
pytest tests/ -v
```

## Benefits of Cleanup

1. **Reduced Maintenance**: One test runner instead of two
2. **Better Organization**: All tests in `tests/` directory
3. **Accurate Documentation**: Test counts match reality
4. **Cross-Platform**: Python script works everywhere
5. **Cleaner Root**: Fewer files in root directory

## Risk Assessment

- **Risk Level**: LOW
- **Reversible**: Yes (Git history preserved)
- **Testing Impact**: None (tests remain unchanged)
- **Breaking Changes**: None (old scripts can be kept for transition)
