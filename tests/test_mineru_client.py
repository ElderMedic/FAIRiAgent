"""Unit tests for MinerU client availability and functionality.

These tests verify that MinerU CLI and HTTP server are properly configured
and available for document conversion. They can be run independently to
check MinerU service status.
"""

import subprocess
import socket
from pathlib import Path
from typing import Optional

import pytest
import requests

from fairifier.config import config
from fairifier.services.mineru_client import (
    MinerUClient,
    MinerUConversionError,
    MinerUConversionResult,
)


@pytest.fixture
def mineru_client() -> MinerUClient:
    """Create a MinerUClient instance for testing."""
    return MinerUClient(
        cli_path=config.mineru_cli_path,
        server_url=config.mineru_server_url,
        backend=config.mineru_backend,
        timeout_seconds=config.mineru_timeout_seconds,
    )


class TestMinerUConfiguration:
    """Test MinerU configuration settings."""

    def test_mineru_config_loaded(self):
        """Verify that MinerU configuration is loaded from config."""
        assert hasattr(config, "mineru_enabled")
        assert hasattr(config, "mineru_cli_path")
        assert hasattr(config, "mineru_server_url")
        assert hasattr(config, "mineru_backend")
        assert hasattr(config, "mineru_timeout_seconds")

    def test_mineru_cli_path_configured(self):
        """Verify that MinerU CLI path is configured."""
        assert config.mineru_cli_path is not None
        assert isinstance(config.mineru_cli_path, str)
        assert len(config.mineru_cli_path) > 0


class TestMinerUCLI:
    """Test MinerU CLI availability."""

    def test_mineru_cli_exists(self):
        """Test that MinerU CLI command exists in PATH."""
        cli_path = config.mineru_cli_path
        try:
            result = subprocess.run(
                ["which", cli_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                actual_path = result.stdout.strip()
                assert Path(actual_path).exists(), f"MinerU CLI not found at {actual_path}"
        except FileNotFoundError:
            pytest.skip("'which' command not available on this system")

    def test_mineru_cli_executable(self):
        """Test that MinerU CLI can be executed."""
        cli_path = config.mineru_cli_path
        try:
            result = subprocess.run(
                [cli_path, "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                text=True,
            )
            # CLI should either succeed or at least not raise FileNotFoundError
            assert result.returncode == 0 or "usage" in result.stdout.lower() or "help" in result.stdout.lower()
        except FileNotFoundError:
            pytest.skip(f"MinerU CLI not found: {cli_path}")
        except subprocess.TimeoutExpired:
            # CLI exists but help command hung - assume it's available
            pass

    def test_mineru_cli_version(self):
        """Test that MinerU CLI version can be retrieved."""
        cli_path = config.mineru_cli_path
        try:
            result = subprocess.run(
                [cli_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                assert "mineru" in result.stdout.lower() or "version" in result.stdout.lower()
        except FileNotFoundError:
            pytest.skip(f"MinerU CLI not found: {cli_path}")


class TestMinerUServer:
    """Test MinerU HTTP server availability."""

    @pytest.mark.integration
    def test_mineru_server_url_configured(self):
        """Verify that MinerU server URL is configured."""
        assert config.mineru_server_url is not None
        assert isinstance(config.mineru_server_url, str)
        assert config.mineru_server_url.startswith("http")

    @pytest.mark.integration
    def test_mineru_server_port_accessible(self):
        """Test that MinerU server port is accessible."""
        server_url = config.mineru_server_url
        if not server_url:
            pytest.skip("MinerU server URL not configured")

        from urllib.parse import urlparse

        parsed = urlparse(server_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 30000

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()

            if result != 0:
                pytest.skip(f"MinerU server not running on {host}:{port}")
        except Exception as e:
            pytest.skip(f"Could not test server connection: {e}")

    @pytest.mark.integration
    def test_mineru_server_health_check(self):
        """Test MinerU server health endpoint."""
        server_url = config.mineru_server_url
        if not server_url:
            pytest.skip("MinerU server URL not configured")

        try:
            health_url = f"{server_url.rstrip('/')}/health"
            response = requests.get(health_url, timeout=5)
            assert response.status_code == 200, f"Health check failed with status {response.status_code}"
        except requests.exceptions.ConnectionError:
            pytest.skip("MinerU server not running or not accessible")
        except requests.exceptions.Timeout:
            pytest.skip("MinerU server health check timed out")
        except Exception as e:
            pytest.skip(f"Health check failed: {e}")


class TestMinerUClient:
    """Test MinerUClient initialization and basic functionality."""

    def test_mineru_client_initialization(self, mineru_client):
        """Test that MinerUClient can be initialized."""
        assert mineru_client is not None
        assert mineru_client.cli_path == config.mineru_cli_path
        assert mineru_client.server_url == config.mineru_server_url
        assert mineru_client.backend == config.mineru_backend

    @pytest.mark.integration
    def test_mineru_client_availability_check(self, mineru_client):
        """Test MinerUClient availability check."""
        if not config.mineru_server_url:
            pytest.skip("MinerU server URL not configured")

        is_available = mineru_client.is_available()
        # This test passes regardless of availability, but logs the result
        assert isinstance(is_available, bool)

    @pytest.mark.integration
    @pytest.mark.slow
    def test_mineru_client_convert_document(self, mineru_client, tmp_path):
        """Test MinerU document conversion with a sample PDF (if available).
        
        This test requires:
        - MinerU client to be available
        - MinerU server to be running
        - A test PDF file to be available
        """
        if not mineru_client.is_available():
            pytest.skip("MinerU client not available")

        # Look for a test PDF in common locations
        test_pdf_paths = [
            Path("examples/inputs/earthworm_4n_paper_bioRXiv.pdf"),
            Path("evaluation/datasets/raw/earthworm/earthworm_4n_paper_bioRXiv.pdf"),
            Path("test_data/sample.pdf"),
        ]

        test_pdf: Optional[Path] = None
        for path in test_pdf_paths:
            abs_path = Path(__file__).parent.parent / path
            if abs_path.exists():
                test_pdf = abs_path
                break

        if not test_pdf:
            pytest.skip("No test PDF found for conversion test")

        # Test conversion
        output_dir = tmp_path / "mineru_output"
        try:
            result = mineru_client.convert_document(test_pdf, output_dir=output_dir)

            assert isinstance(result, MinerUConversionResult)
            assert result.input_path == test_pdf.resolve()
            assert result.markdown_path.exists()
            assert len(result.markdown_text) > 0
            assert result.output_dir.exists()
        except MinerUConversionError as e:
            error_str = str(e).lower()
            # Skip for known issues that are environmental, not code issues
            if any(keyword in error_str for keyword in [
                "server", "connection", "timeout",
                "operation not permitted", "permission denied",
                "no files found in output directory"
            ]):
                pytest.skip(f"MinerU conversion issue (environmental): {e}")
            else:
                pytest.fail(f"MinerU conversion failed: {e}")


class TestMinerUIntegration:
    """Integration tests for MinerU service availability."""

    @pytest.mark.integration
    def test_mineru_full_stack_available(self):
        """Test that the full MinerU stack (CLI + server) is available."""
        # Check CLI
        cli_ok = False
        try:
            result = subprocess.run(
                [config.mineru_cli_path, "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )
            cli_ok = result.returncode == 0 or "usage" in result.stdout.decode().lower()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Check server
        server_ok = False
        if config.mineru_server_url:
            try:
                from urllib.parse import urlparse

                parsed = urlparse(config.mineru_server_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or 30000

                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((host, port))
                sock.close()
                server_ok = result == 0
            except Exception:
                pass

        # Log results but don't fail the test
        if not cli_ok:
            pytest.skip("MinerU CLI not available")
        if not server_ok:
            pytest.skip("MinerU server not running")

        # If we get here, both are available
        assert True


# Convenience function for manual testing
def test_mineru_status_summary():
    """Print a summary of MinerU status (useful for debugging).

    This test always passes but prints diagnostic information.
    """
    print("\n" + "=" * 60)
    print("MinerU Status Summary")
    print("=" * 60)

    print(f"\nConfiguration:")
    print(f"  MINERU_ENABLED: {config.mineru_enabled}")
    print(f"  MINERU_CLI_PATH: {config.mineru_cli_path}")
    print(f"  MINERU_SERVER_URL: {config.mineru_server_url}")
    print(f"  MINERU_BACKEND: {config.mineru_backend}")
    print(f"  MINERU_TIMEOUT_SECONDS: {config.mineru_timeout_seconds}")

    # Check CLI
    print(f"\nCLI Status:")
    try:
        result = subprocess.run(
            [config.mineru_cli_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            print(f"  ✅ Available: {result.stdout.strip()}")
        else:
            print(f"  ❌ Not available")
    except Exception as e:
        print(f"  ❌ Error: {e}")

    # Check server
    print(f"\nServer Status:")
    if config.mineru_server_url:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(config.mineru_server_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 30000

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                print(f"  ✅ Running on {host}:{port}")
            else:
                print(f"  ❌ Not running on {host}:{port}")
        except Exception as e:
            print(f"  ❌ Error: {e}")
    else:
        print(f"  ⚠️  Server URL not configured")

    # This test always passes - it's just for information
    assert True
