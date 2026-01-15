"""Unit tests for runtime configuration saving functionality."""

import json
import tempfile
from pathlib import Path
from datetime import datetime

import pytest

from fairifier.utils.config_saver import (
    collect_runtime_config,
    save_runtime_config,
)
from fairifier.config import config


class TestCollectRuntimeConfig:
    """Test runtime configuration collection."""

    def test_collect_runtime_config_basic(self):
        """Test basic configuration collection."""
        result = collect_runtime_config(
            document_path="test.pdf",
            project_id="test_project_123"
        )
        
        assert isinstance(result, dict)
        assert "runtime_info" in result
        assert "config" in result
        assert "environment_variables" in result
        assert "env_file" in result

    def test_collect_runtime_config_runtime_info(self):
        """Test that runtime info is correctly collected."""
        result = collect_runtime_config(
            document_path="/path/to/test.pdf",
            project_id="test_project_123",
            output_path=Path("/tmp/output")
        )
        
        runtime_info = result["runtime_info"]
        assert runtime_info["project_id"] == "test_project_123"
        assert runtime_info["document_path"] == "/path/to/test.pdf"
        assert runtime_info["document_name"] == "test.pdf"
        assert runtime_info["output_path"] == "/tmp/output"
        assert "timestamp" in runtime_info
        assert runtime_info["workflow_version"] == "langgraph"
        
        # Verify timestamp is valid ISO format
        datetime.fromisoformat(runtime_info["timestamp"])

    def test_collect_runtime_config_includes_config(self):
        """Test that config object values are included."""
        result = collect_runtime_config(
            document_path="test.pdf",
            project_id="test_project"
        )
        
        config_dict = result["config"]
        assert config_dict["llm_provider"] == config.llm_provider
        assert config_dict["llm_model"] == config.llm_model
        assert config_dict["llm_base_url"] == config.llm_base_url
        assert config_dict["fair_ds_api_url"] == config.fair_ds_api_url

    def test_collect_runtime_config_masks_sensitive_data(self):
        """Test that sensitive data is masked."""
        result = collect_runtime_config(
            document_path="test.pdf",
            project_id="test_project"
        )
        
        config_dict = result["config"]
        
        # API keys should be masked
        if config.llm_api_key:
            assert config_dict["llm_api_key"] == "***MASKED***"
        if config.langsmith_api_key:
            assert config_dict["langsmith_api_key"] == "***MASKED***"

    def test_collect_runtime_config_env_variables(self):
        """Test that environment variables are collected."""
        result = collect_runtime_config(
            document_path="test.pdf",
            project_id="test_project"
        )
        
        env_vars = result["environment_variables"]
        assert isinstance(env_vars, dict)
        assert len(env_vars) > 0, "Should have at least some environment variables"

    def test_collect_runtime_config_env_file_handling(self):
        """Test .env file handling."""
        result = collect_runtime_config(
            document_path="test.pdf",
            project_id="test_project"
        )
        
        env_file_info = result["env_file"]
        assert isinstance(env_file_info, dict)
        assert "path" in env_file_info
        assert "content" in env_file_info
        assert "exists" in env_file_info
        assert isinstance(env_file_info["exists"], bool)

    def test_collect_runtime_config_env_file_masks_sensitive(self):
        """Test that .env file content masks sensitive data."""
        result = collect_runtime_config(
            document_path="test.pdf",
            project_id="test_project"
        )
        
        env_file_info = result["env_file"]
        if env_file_info["content"]:
            content = env_file_info["content"]
            # Check that sensitive keys are masked
            sensitive_keywords = ["api_key", "password", "secret", "token"]
            for keyword in sensitive_keywords:
                if keyword in content.lower():
                    # Should contain masked value
                    assert "***MASKED***" in content or keyword not in content.lower()


class TestSaveRuntimeConfig:
    """Test runtime configuration saving."""

    def test_save_runtime_config_creates_file(self, tmp_path):
        """Test that save_runtime_config creates a JSON file."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        config_file = save_runtime_config(
            document_path="test.pdf",
            project_id="test_project_123",
            output_path=output_dir
        )
        
        assert config_file.exists()
        assert config_file.name == "runtime_config.json"
        assert config_file.parent == output_dir

    def test_save_runtime_config_valid_json(self, tmp_path):
        """Test that saved config is valid JSON."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        config_file = save_runtime_config(
            document_path="test.pdf",
            project_id="test_project",
            output_path=output_dir
        )
        
        # Verify it's valid JSON
        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        assert isinstance(data, dict)
        assert "runtime_info" in data
        assert "config" in data

    def test_save_runtime_config_complete_structure(self, tmp_path):
        """Test that saved config has complete structure."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        config_file = save_runtime_config(
            document_path="/path/to/document.pdf",
            project_id="test_project_456",
            output_path=output_dir
        )
        
        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Verify all sections exist
        assert "runtime_info" in data
        assert "config" in data
        assert "environment_variables" in data
        assert "env_file" in data
        
        # Verify runtime_info structure
        runtime_info = data["runtime_info"]
        assert runtime_info["project_id"] == "test_project_456"
        assert runtime_info["document_path"] == "/path/to/document.pdf"
        assert runtime_info["document_name"] == "document.pdf"
        
        # Verify config structure
        config_dict = data["config"]
        assert "llm_provider" in config_dict
        assert "llm_model" in config_dict
        assert "fair_ds_api_url" in config_dict

    def test_save_runtime_config_handles_missing_output_dir(self, tmp_path):
        """Test that save_runtime_config creates output directory if needed."""
        output_dir = tmp_path / "new_output"
        # Don't create the directory
        
        config_file = save_runtime_config(
            document_path="test.pdf",
            project_id="test_project",
            output_path=output_dir
        )
        
        # Directory should be created
        assert output_dir.exists()
        assert config_file.exists()

    def test_save_runtime_config_returns_correct_path(self, tmp_path):
        """Test that save_runtime_config returns correct file path."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        config_file = save_runtime_config(
            document_path="test.pdf",
            project_id="test_project",
            output_path=output_dir
        )
        
        expected_path = output_dir / "runtime_config.json"
        assert config_file == expected_path
        assert str(config_file) == str(expected_path)

    def test_save_runtime_config_preserves_all_data(self, tmp_path):
        """Test that all collected data is preserved in saved file."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        
        # Collect config first
        collected = collect_runtime_config(
            document_path="test.pdf",
            project_id="test_project",
            output_path=output_dir
        )
        
        # Save config
        config_file = save_runtime_config(
            document_path="test.pdf",
            project_id="test_project",
            output_path=output_dir
        )
        
        # Load saved config
        with open(config_file, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        
        # Verify all keys match
        assert set(saved.keys()) == set(collected.keys())
        
        # Verify runtime_info matches (except timestamp which may differ slightly)
        for key in ["project_id", "document_path", "document_name"]:
            assert saved["runtime_info"][key] == collected["runtime_info"][key]
        
        # Verify config matches
        assert saved["config"]["llm_provider"] == collected["config"]["llm_provider"]
        assert saved["config"]["llm_model"] == collected["config"]["llm_model"]
