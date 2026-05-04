"""
Memory system compliance tests for FAIRiAgent.

Verifies that the mem0 memory layer adheres to five contracts inspired by
Claude Code, Codex, and ADK memory patterns:

1. Cold start    — first run has no global memories; system works gracefully
2. Read discipline — expired/invalid memories are filtered before use
3. Write discipline — write gate blocks low-quality outputs; dedup suppresses repeats
4. Scope isolation — session scope ≠ global scope; run-specific facts stay local
5. Expiration/validity — TTL and schema version gates work correctly
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_memory(
    text: str = "earthworm studies use ENVO ontology",
    schema_version: str | None = "v1",
    expires_delta_days: int | None = 10,
    memory_id: str = "mem-001",
) -> dict:
    """Build a mock mem0 memory dict with lifecycle metadata."""
    now = datetime.now(timezone.utc)
    metadata: dict = {}
    if schema_version is not None:
        metadata["schema_version"] = schema_version
    if expires_delta_days is not None:
        metadata["expires_at"] = (now + timedelta(days=expires_delta_days)).isoformat()
        metadata["written_at"] = now.isoformat()
    return {"id": memory_id, "memory": text, "score": 0.9, "metadata": metadata}


def _make_expired_memory(text: str = "stale fact") -> dict:
    return _make_memory(text=text, expires_delta_days=-1)


def _make_wrong_schema_memory(text: str = "old schema fact") -> dict:
    return _make_memory(text=text, schema_version="v0")


# ──────────────────────────────────────────────────────────────────────────────
# 1. Cold start compliance
# ──────────────────────────────────────────────────────────────────────────────

class TestColdStartCompliance:
    """Cold start: the service must work gracefully when no global memories exist."""

    def _get_service(self):
        from fairifier.services.mem0_service import Mem0Service, GLOBAL_MEMORY_SCOPE
        svc = MagicMock(spec=Mem0Service)
        svc.is_available.return_value = True
        return svc, GLOBAL_MEMORY_SCOPE

    def test_is_cold_start_true_when_no_global_memories(self):
        """is_cold_start() returns True when global scope has zero memories."""
        try:
            from fairifier.services.mem0_service import Mem0Service, GLOBAL_MEMORY_SCOPE
        except ImportError:
            pytest.skip("mem0 not installed")

        svc = MagicMock(spec=Mem0Service)
        svc.is_available.return_value = True
        svc.list_memories.return_value = []
        svc.is_cold_start = Mem0Service.is_cold_start.__get__(svc, Mem0Service)

        assert svc.is_cold_start() is True
        svc.list_memories.assert_called_once_with(session_id=GLOBAL_MEMORY_SCOPE)

    def test_is_cold_start_false_when_global_memories_exist(self):
        """is_cold_start() returns False when at least one global memory exists."""
        try:
            from fairifier.services.mem0_service import Mem0Service, GLOBAL_MEMORY_SCOPE
        except ImportError:
            pytest.skip("mem0 not installed")

        svc = MagicMock(spec=Mem0Service)
        svc.is_available.return_value = True
        svc.list_memories.return_value = [_make_memory()]
        svc.is_cold_start = Mem0Service.is_cold_start.__get__(svc, Mem0Service)

        assert svc.is_cold_start() is False

    def test_is_cold_start_true_when_service_unavailable(self):
        """is_cold_start() returns True (safe default) when service is down."""
        try:
            from fairifier.services.mem0_service import Mem0Service
        except ImportError:
            pytest.skip("mem0 not installed")

        svc = MagicMock(spec=Mem0Service)
        svc.is_available.return_value = False
        svc.is_cold_start = Mem0Service.is_cold_start.__get__(svc, Mem0Service)

        assert svc.is_cold_start() is True


# ──────────────────────────────────────────────────────────────────────────────
# 2. Validity gate compliance (TTL + schema version)
# ──────────────────────────────────────────────────────────────────────────────

class TestValidityCompliance:
    """Expired and wrong-schema memories must not pass is_memory_valid()."""

    @pytest.fixture(autouse=True)
    def _import(self):
        try:
            from fairifier.services.mem0_service import Mem0Service
            self.Mem0Service = Mem0Service
        except ImportError:
            pytest.skip("mem0 not installed")

    def _svc(self):
        svc = MagicMock(spec=self.Mem0Service)
        svc.is_memory_valid = self.Mem0Service.is_memory_valid.__get__(svc, self.Mem0Service)
        return svc

    def test_valid_memory_passes(self):
        svc = self._svc()
        mem = _make_memory(expires_delta_days=10, schema_version="v1")
        assert svc.is_memory_valid(mem) is True

    def test_expired_memory_fails(self):
        svc = self._svc()
        mem = _make_expired_memory()
        assert svc.is_memory_valid(mem) is False

    def test_wrong_schema_version_fails(self):
        svc = self._svc()
        mem = _make_wrong_schema_memory()
        assert svc.is_memory_valid(mem) is False

    def test_memory_without_metadata_passes(self):
        """Memories written before TTL support (no lifecycle metadata) must not be filtered."""
        svc = self._svc()
        mem = {"id": "legacy", "memory": "old fact", "metadata": {}}
        assert svc.is_memory_valid(mem) is True

    def test_non_dict_memory_passes(self):
        """Non-dict values are passed through unchanged."""
        svc = self._svc()
        assert svc.is_memory_valid("raw string") is True  # type: ignore[arg-type]


# ──────────────────────────────────────────────────────────────────────────────
# 3. Write discipline compliance
# ──────────────────────────────────────────────────────────────────────────────

class TestWriteDisciplineCompliance:
    """Write gate must only allow high-quality, non-duplicate writes."""

    @pytest.fixture(autouse=True)
    def _import(self):
        try:
            from fairifier.graph.langgraph_app import FAIRifierLangGraphApp
            self.App = FAIRifierLangGraphApp
        except ImportError:
            pytest.skip("langgraph app unavailable")

    def _app(self):
        app = MagicMock(spec=self.App)
        app._should_write_memory = self.App._should_write_memory.__get__(app, self.App)
        return app

    def _eval(self, decision: str, score: float, issues: list | None = None) -> dict:
        return {"decision": decision, "score": score, "issues": issues or []}

    def test_high_quality_accept_writes(self):
        app = self._app()
        assert app._should_write_memory("JSONGenerator", {}, self._eval("ACCEPT", 0.85), 1) is True

    def test_low_score_accept_does_not_write(self):
        """ACCEPT below threshold (e.g. 0.5) should not write unless repair."""
        app = self._app()
        # Score 0.5 < 0.75 threshold, attempt=1 (not a repair)
        assert app._should_write_memory("DocumentParser", {}, self._eval("ACCEPT", 0.50), 1) is False

    def test_successful_repair_writes(self):
        """Acceptance on attempt > 1 = learned repair → always write."""
        app = self._app()
        assert app._should_write_memory("JSONGenerator", {}, self._eval("ACCEPT", 0.50), 2) is True

    def test_reject_with_issues_writes_failure_pattern(self):
        app = self._app()
        assert app._should_write_memory(
            "JSONGenerator", {}, self._eval("REJECT", 0.30, ["wrong package"]), 1
        ) is True

    def test_reject_without_issues_does_not_write(self):
        app = self._app()
        assert app._should_write_memory("JSONGenerator", {}, self._eval("REJECT", 0.30), 1) is False

    def test_workflow_decision_agents_write_on_accept(self):
        """KnowledgeRetriever, JSONGenerator, ISAValueMapper always write on ACCEPT."""
        app = self._app()
        for agent in ("KnowledgeRetriever", "JSONGenerator", "ISAValueMapper"):
            assert app._should_write_memory(agent, {}, self._eval("ACCEPT", 0.5), 1) is True


# ──────────────────────────────────────────────────────────────────────────────
# 4. Scope isolation compliance
# ──────────────────────────────────────────────────────────────────────────────

class TestScopeIsolationCompliance:
    """Session scope must not contaminate global scope with run-specific facts."""

    @pytest.fixture(autouse=True)
    def _import(self):
        try:
            from fairifier.graph.langgraph_app import FAIRifierLangGraphApp
            self.App = FAIRifierLangGraphApp
        except ImportError:
            pytest.skip("langgraph app unavailable")

    def _app(self):
        app = MagicMock(spec=self.App)
        app._is_domain_general = self.App._is_domain_general.__get__(app, self.App)
        return app

    def test_domain_general_fact_is_promoted(self):
        app = self._app()
        general = "Nanotoxicology RNA-seq studies use Illumina and Genome packages."
        assert app._is_domain_general(general) is True

    def test_project_id_stays_in_session_scope(self):
        app = self._app()
        specific = "project_id=mem0_verify_run: DocumentParser accepted on attempt 1"
        assert app._is_domain_general(specific) is False

    def test_file_path_stays_in_session_scope(self):
        app = self._app()
        assert app._is_domain_general("/home/user/output/run123/metadata.json") is False

    def test_retry_count_stays_in_session_scope(self):
        app = self._app()
        assert app._is_domain_general("retry count is 2 for this session") is False

    def test_store_insight_skips_global_for_run_specific(self):
        """_store_memory_insight must not call mem0.add for global scope when insight is run-specific."""
        try:
            from fairifier.graph.langgraph_app import FAIRifierLangGraphApp
            from fairifier.services.mem0_service import GLOBAL_MEMORY_SCOPE
        except ImportError:
            pytest.skip("dependencies unavailable")

        mem0_svc = MagicMock()
        mem0_svc.add.return_value = {"results": [{"id": "x"}]}

        app = MagicMock(spec=FAIRifierLangGraphApp)
        app.mem0_service = mem0_svc
        app._memory_scope_ids = FAIRifierLangGraphApp._memory_scope_ids.__get__(app, FAIRifierLangGraphApp)
        app._is_domain_general = FAIRifierLangGraphApp._is_domain_general.__get__(app, FAIRifierLangGraphApp)
        app._store_memory_insight = FAIRifierLangGraphApp._store_memory_insight.__get__(app, FAIRifierLangGraphApp)

        run_specific = "project_id=abc retry count is 2"
        state = {"memory_scope_id": GLOBAL_MEMORY_SCOPE}
        app._store_memory_insight(
            state=state,
            session_id="abc",
            agent_id="DocumentParser",
            insight=run_specific,
            metadata={},
        )

        # Should only write to session scope (user_id="abc"), NOT to global scope
        calls = mem0_svc.add.call_args_list
        called_session_ids = [c.kwargs.get("session_id") for c in calls]
        assert GLOBAL_MEMORY_SCOPE not in called_session_ids, (
            f"Run-specific insight was promoted to global scope: {called_session_ids}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 5. Read discipline compliance
# ──────────────────────────────────────────────────────────────────────────────

class TestReadDisciplineCompliance:
    """Expired memories must be filtered from search results before agents see them."""

    @pytest.fixture(autouse=True)
    def _import(self):
        try:
            from fairifier.services.mem0_service import Mem0Service
            self.Mem0Service = Mem0Service
        except ImportError:
            pytest.skip("mem0 not installed")

    def test_search_filters_expired_memories(self):
        """search() must not return expired memories even if Qdrant returns them."""
        svc = MagicMock(spec=self.Mem0Service)
        svc.is_available.return_value = True
        svc.is_memory_valid = self.Mem0Service.is_memory_valid.__get__(svc, self.Mem0Service)

        valid = _make_memory("valid fact", expires_delta_days=10)
        expired = _make_expired_memory("stale fact")

        svc.memory = MagicMock()
        svc.memory.search.return_value = {"results": [valid, expired]}
        svc._seen_message_fingerprints = set()  # not used in search

        result = self.Mem0Service.search(svc, "FAIR packages", "session-1", limit=10)
        memory_texts = [m.get("memory") for m in result]
        assert "valid fact" in memory_texts
        assert "stale fact" not in memory_texts

    def test_search_filters_wrong_schema_memories(self):
        """search() must not return memories from an old schema version."""
        svc = MagicMock(spec=self.Mem0Service)
        svc.is_available.return_value = True
        svc.is_memory_valid = self.Mem0Service.is_memory_valid.__get__(svc, self.Mem0Service)

        current = _make_memory("current fact", schema_version="v1")
        old = _make_wrong_schema_memory("outdated fact")

        svc.memory = MagicMock()
        svc.memory.search.return_value = {"results": [current, old]}

        result = self.Mem0Service.search(svc, "packages", "session-1", limit=10)
        memory_texts = [m.get("memory") for m in result]
        assert "current fact" in memory_texts
        assert "outdated fact" not in memory_texts

    def test_search_returns_empty_on_unavailable(self):
        svc = MagicMock(spec=self.Mem0Service)
        svc.is_available.return_value = False
        result = self.Mem0Service.search(svc, "query", "session-1")
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# 6. TTL auto-injection compliance
# ──────────────────────────────────────────────────────────────────────────────

class TestTTLInjectionCompliance:
    """add() must auto-inject written_at, expires_at, schema_version into metadata."""

    @pytest.fixture(autouse=True)
    def _import(self):
        try:
            from fairifier.services.mem0_service import (
                Mem0Service,
                MEMORY_SCHEMA_VERSION,
                MEMORY_TTL_DAYS_SESSION,
                MEMORY_TTL_DAYS_GLOBAL,
            )
            self.Mem0Service = Mem0Service
            self.SCHEMA_VERSION = MEMORY_SCHEMA_VERSION
            self.TTL_SESSION = MEMORY_TTL_DAYS_SESSION
            self.TTL_GLOBAL = MEMORY_TTL_DAYS_GLOBAL
        except ImportError:
            pytest.skip("mem0 not installed")

    def _svc_with_mock_memory(self):
        svc = MagicMock(spec=self.Mem0Service)
        svc.is_available.return_value = True
        svc._seen_message_fingerprints = set()
        svc._fingerprint_messages = self.Mem0Service._fingerprint_messages.__get__(
            svc, self.Mem0Service
        )
        svc.memory = MagicMock()
        svc.memory.add.return_value = {"results": [{"id": "m1"}]}
        return svc

    def test_add_injects_schema_version(self):
        svc = self._svc_with_mock_memory()
        self.Mem0Service.add(
            svc, [{"role": "assistant", "content": "earthworm study facts"}], "session-x"
        )
        _, kwargs = svc.memory.add.call_args
        meta = kwargs.get("metadata", {})
        assert meta.get("schema_version") == self.SCHEMA_VERSION

    def test_add_injects_written_at(self):
        svc = self._svc_with_mock_memory()
        before = datetime.now(timezone.utc)
        self.Mem0Service.add(
            svc, [{"role": "assistant", "content": "some fact"}], "session-x"
        )
        after = datetime.now(timezone.utc)
        _, kwargs = svc.memory.add.call_args
        meta = kwargs.get("metadata", {})
        written_at = datetime.fromisoformat(meta["written_at"])
        if written_at.tzinfo is None:
            written_at = written_at.replace(tzinfo=timezone.utc)
        assert before <= written_at <= after

    def test_session_scope_gets_short_ttl(self):
        svc = self._svc_with_mock_memory()
        self.Mem0Service.add(
            svc,
            [{"role": "assistant", "content": "run-scoped fact"}],
            "session-x",
            metadata={"memory_scope_type": "session"},
        )
        _, kwargs = svc.memory.add.call_args
        meta = kwargs.get("metadata", {})
        expires_at = datetime.fromisoformat(meta["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        delta = expires_at - datetime.now(timezone.utc)
        assert self.TTL_SESSION - 1 <= delta.days <= self.TTL_SESSION + 1

    def test_global_scope_gets_long_ttl(self):
        svc = self._svc_with_mock_memory()
        self.Mem0Service.add(
            svc,
            [{"role": "assistant", "content": "cross-run domain pattern"}],
            "fairifier-global",
            metadata={"memory_scope_type": "long_term"},
        )
        _, kwargs = svc.memory.add.call_args
        meta = kwargs.get("metadata", {})
        expires_at = datetime.fromisoformat(meta["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        delta = expires_at - datetime.now(timezone.utc)
        assert self.TTL_GLOBAL - 1 <= delta.days <= self.TTL_GLOBAL + 1
