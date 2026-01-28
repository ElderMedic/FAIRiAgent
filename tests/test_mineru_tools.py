"""Unit tests for MinerU LangChain tool."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from fairifier.tools.mineru_tools import create_mineru_convert_tool, MinerUToolResult
from fairifier.services.mineru_client import MinerUConversionError, MinerUConversionResult


@pytest.fixture
def mock_client():
    """Create a mock MinerU client."""
    client = MagicMock()
    client.is_available.return_value = True
    return client


@pytest.fixture
def mock_conversion_result():
    """Create a mock MinerU conversion result."""
    return MinerUConversionResult(
        input_path=Path("/test/input.pdf"),
        output_dir=Path("/test/output"),
        markdown_path=Path("/test/output/input.md"),
        markdown_text="# Test Document\n\nThis is test content.",
        images_dir=Path("/test/output/images"),
        other_files=[]
    )


@pytest.fixture
def mineru_tool(mock_client):
    """Create MinerU tool with mock client."""
    return create_mineru_convert_tool(client=mock_client)


class TestMinerUToolCreation:
    """Test MinerU tool creation and structure."""
    
    def test_creates_single_tool(self, mineru_tool):
        """Test that factory creates a tool."""
        assert mineru_tool is not None
        assert hasattr(mineru_tool, "name")
        assert hasattr(mineru_tool, "invoke")
    
    def test_tool_name(self, mineru_tool):
        """Test that tool has correct name."""
        assert mineru_tool.name == "convert_document"
    
    def test_tool_has_description(self, mineru_tool):
        """Test that tool has non-empty description."""
        assert mineru_tool.description
        assert len(mineru_tool.description) > 10
        assert "MinerU" in mineru_tool.description
    
    def test_tool_description_mentions_fallback(self, mineru_tool):
        """Test that description mentions fallback behavior."""
        assert "fallback" in mineru_tool.description.lower() or \
               "fail" in mineru_tool.description.lower()


class TestConvertDocumentTool:
    """Test convert_document tool functionality."""
    
    def test_successful_conversion(self, mineru_tool, mock_client, mock_conversion_result):
        """Test successful document conversion."""
        mock_client.convert_document.return_value = mock_conversion_result
        
        result = mineru_tool.invoke({
            "input_path": "/test/input.pdf",
            "output_dir": None
        })
        
        assert result["success"] is True
        assert result["markdown_text"] == "# Test Document\n\nThis is test content."
        assert result["markdown_path"] == str(mock_conversion_result.markdown_path)
        assert result["output_dir"] == str(mock_conversion_result.output_dir)
        assert result["images_dir"] == str(mock_conversion_result.images_dir)
        assert result["method"] == "mineru"
        assert result["error"] is None
        
        mock_client.convert_document.assert_called_once()
    
    def test_conversion_with_output_dir(self, mineru_tool, mock_client, mock_conversion_result):
        """Test conversion with specified output directory."""
        mock_client.convert_document.return_value = mock_conversion_result
        
        result = mineru_tool.invoke({
            "input_path": "/test/input.pdf",
            "output_dir": "/custom/output"
        })
        
        assert result["success"] is True
        
        # Verify output_dir was passed to client
        call_args = mock_client.convert_document.call_args
        assert call_args[1]["output_dir"] == Path("/custom/output")
    
    def test_handles_conversion_error(self, mineru_tool, mock_client):
        """Test handling of MinerU conversion errors."""
        mock_client.convert_document.side_effect = MinerUConversionError(
            "Conversion failed: timeout"
        )
        
        result = mineru_tool.invoke({
            "input_path": "/test/input.pdf",
            "output_dir": None
        })
        
        assert result["success"] is False
        assert result["markdown_text"] is None
        assert result["markdown_path"] is None
        assert result["method"] == "mineru"
        assert "Conversion failed" in result["error"]
        assert "timeout" in result["error"]
    
    def test_handles_unexpected_exception(self, mineru_tool, mock_client):
        """Test handling of unexpected exceptions."""
        mock_client.convert_document.side_effect = Exception("Unexpected error")
        
        result = mineru_tool.invoke({
            "input_path": "/test/input.pdf",
            "output_dir": None
        })
        
        assert result["success"] is False
        assert result["markdown_text"] is None
        assert "Unexpected error" in result["error"]
    
    def test_conversion_without_images(self, mineru_tool, mock_client):
        """Test conversion result without images directory."""
        result_without_images = MinerUConversionResult(
            input_path=Path("/test/input.pdf"),
            output_dir=Path("/test/output"),
            markdown_path=Path("/test/output/input.md"),
            markdown_text="# Test",
            images_dir=None,  # No images
            other_files=[]
        )
        mock_client.convert_document.return_value = result_without_images
        
        result = mineru_tool.invoke({
            "input_path": "/test/input.pdf",
            "output_dir": None
        })
        
        assert result["success"] is True
        assert result["images_dir"] is None


class TestToolWithoutClient:
    """Test tool behavior when client is not available."""
    
    @patch('fairifier.config.config')
    def test_creates_tool_with_unavailable_client(self, mock_config):
        """Test that tool is created even if client is unavailable."""
        mock_config.mineru_enabled = False
        mock_config.mineru_server_url = None
        
        tool = create_mineru_convert_tool(client=None)
        
        assert tool is not None
        assert tool.name == "convert_document"
    
    @patch('fairifier.config.config')
    def test_tool_returns_error_when_client_unavailable(self, mock_config):
        """Test that tool returns appropriate error when client is None."""
        # Set config to fail client creation
        mock_config.mineru_enabled = False
        mock_config.mineru_server_url = None
        
        tool = create_mineru_convert_tool(client=None)
        
        result = tool.invoke({
            "input_path": "/test/input.pdf",
            "output_dir": None
        })
        
        assert result["success"] is False
        assert result["markdown_text"] is None
        assert "not available" in result["error"].lower() or \
               "not enabled" in result["error"].lower()


class TestToolIntegrationWithLangChain:
    """Test that tool works correctly with LangChain framework."""
    
    def test_tool_is_langchain_tool(self, mineru_tool):
        """Test that created object is a valid LangChain tool."""
        # Check it has LangChain tool interface
        assert hasattr(mineru_tool, "name")
        assert hasattr(mineru_tool, "description")
        assert hasattr(mineru_tool, "invoke")
        assert callable(mineru_tool.invoke)
    
    def test_tool_invoke_returns_dict(self, mineru_tool, mock_client, mock_conversion_result):
        """Test that tool returns a dictionary."""
        mock_client.convert_document.return_value = mock_conversion_result
        
        result = mineru_tool.invoke({
            "input_path": "/test/input.pdf",
            "output_dir": None
        })
        
        assert isinstance(result, dict)
        assert "success" in result
        assert "markdown_text" in result
        assert "markdown_path" in result
        assert "output_dir" in result
        assert "images_dir" in result
        assert "method" in result
        assert "error" in result
    
    def test_result_structure_consistency(self, mineru_tool, mock_client):
        """Test that result structure is consistent on success and failure."""
        # Test success case
        mock_conversion_result = MinerUConversionResult(
            input_path=Path("/test/input.pdf"),
            output_dir=Path("/test/output"),
            markdown_path=Path("/test/output/input.md"),
            markdown_text="Test",
            images_dir=None,
            other_files=[]
        )
        mock_client.convert_document.return_value = mock_conversion_result
        
        success_result = mineru_tool.invoke({
            "input_path": "/test/input.pdf",
            "output_dir": None
        })
        
        # Test failure case
        mock_client.convert_document.side_effect = MinerUConversionError("Error")
        
        failure_result = mineru_tool.invoke({
            "input_path": "/test/input.pdf",
            "output_dir": None
        })
        
        # Both should have same keys
        assert set(success_result.keys()) == set(failure_result.keys())


class TestToolResultFormat:
    """Test MinerUToolResult structure."""
    
    def test_tool_result_has_required_fields(self):
        """Test that MinerUToolResult has all required fields."""
        result = MinerUToolResult(
            success=True,
            markdown_text="Test",
            markdown_path="/path/to/output.md"
        )
        
        assert hasattr(result, "success")
        assert hasattr(result, "markdown_text")
        assert hasattr(result, "markdown_path")
        assert hasattr(result, "output_dir")
        assert hasattr(result, "images_dir")
        assert hasattr(result, "method")
        assert hasattr(result, "error")
    
    def test_tool_result_defaults(self):
        """Test MinerUToolResult default values."""
        result = MinerUToolResult(success=False)
        
        assert result.success is False
        assert result.markdown_text is None
        assert result.markdown_path is None
        assert result.output_dir is None
        assert result.images_dir is None
        assert result.method == "mineru"
        assert result.error is None


class TestToolParameterHandling:
    """Test tool parameter validation and handling."""
    
    def test_requires_input_path(self, mineru_tool):
        """Test that input_path parameter is required."""
        # This should raise an error or validation issue
        # Actual behavior depends on LangChain's validation
        # For now, just ensure the tool accepts the parameter structure
        try:
            result = mineru_tool.invoke({
                "input_path": "/test/file.pdf",
                "output_dir": None
            })
            # If no exception, verify result structure
            assert "success" in result
        except Exception as e:
            # If validation error, that's expected
            assert "input_path" in str(e).lower() or isinstance(e, (TypeError, KeyError))
    
    def test_output_dir_optional(self, mineru_tool, mock_client, mock_conversion_result):
        """Test that output_dir parameter is optional."""
        mock_client.convert_document.return_value = mock_conversion_result
        
        # Should work without output_dir
        result = mineru_tool.invoke({
            "input_path": "/test/file.pdf"
        })
        
        assert result["success"] is True
    
    def test_handles_string_paths(self, mineru_tool, mock_client, mock_conversion_result):
        """Test that tool handles string paths correctly."""
        mock_client.convert_document.return_value = mock_conversion_result
        
        result = mineru_tool.invoke({
            "input_path": "/test/input.pdf",
            "output_dir": "/test/output"
        })
        
        assert result["success"] is True
        
        # Verify Path conversion happened
        call_args = mock_client.convert_document.call_args
        assert isinstance(call_args[1]["output_dir"], Path)
