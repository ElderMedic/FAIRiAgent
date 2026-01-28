"""Unit tests for FAIR-DS LangChain tools."""

import pytest
from unittest.mock import MagicMock, patch
from fairifier.tools.fair_ds_tools import create_fair_ds_tools, FAIRDSToolResult


@pytest.fixture
def mock_client():
    """Create a mock FAIR-DS client."""
    client = MagicMock()
    client.is_available.return_value = True
    return client


@pytest.fixture
def fair_ds_tools(mock_client):
    """Create FAIR-DS tools with mock client."""
    return create_fair_ds_tools(client=mock_client)


class TestFAIRDSToolsCreation:
    """Test FAIR-DS tools creation and structure."""
    
    def test_creates_five_tools(self, fair_ds_tools):
        """Test that factory creates exactly 5 tools."""
        assert len(fair_ds_tools) == 5
    
    def test_tool_names(self, fair_ds_tools):
        """Test that all expected tools are created."""
        tool_names = [tool.name for tool in fair_ds_tools]
        
        expected_names = [
            "get_available_packages",
            "get_package",
            "get_terms",
            "search_terms_for_fields",
            "search_fields_in_packages",
        ]
        
        assert tool_names == expected_names
    
    def test_tools_have_descriptions(self, fair_ds_tools):
        """Test that all tools have non-empty descriptions."""
        for tool in fair_ds_tools:
            assert tool.description
            assert len(tool.description) > 10


class TestGetAvailablePackagesTool:
    """Test get_available_packages tool."""
    
    def test_successful_retrieval(self, fair_ds_tools, mock_client):
        """Test successful package retrieval."""
        mock_client.get_available_packages.return_value = ["miappe", "soil", "default"]
        
        tool = fair_ds_tools[0]  # get_available_packages
        result = tool.invoke({"force_refresh": False})
        
        assert result["success"] is True
        assert result["data"] == ["miappe", "soil", "default"]
        assert result["error"] is None
        mock_client.get_available_packages.assert_called_once_with(force_refresh=False)
    
    def test_handles_exception(self, fair_ds_tools, mock_client):
        """Test error handling when API call fails."""
        mock_client.get_available_packages.side_effect = Exception("API Error")
        
        tool = fair_ds_tools[0]
        result = tool.invoke({"force_refresh": False})
        
        assert result["success"] is False
        assert result["data"] == []
        assert "API Error" in result["error"]
    
    def test_force_refresh_parameter(self, fair_ds_tools, mock_client):
        """Test that force_refresh parameter is passed correctly."""
        mock_client.get_available_packages.return_value = []
        
        tool = fair_ds_tools[0]
        tool.invoke({"force_refresh": True})
        
        mock_client.get_available_packages.assert_called_once_with(force_refresh=True)


class TestGetPackageTool:
    """Test get_package tool."""
    
    def test_successful_retrieval(self, fair_ds_tools, mock_client):
        """Test successful package retrieval."""
        package_data = {
            "packageName": "miappe",
            "itemCount": 63,
            "metadata": [{"label": "test"}]
        }
        mock_client.get_package.return_value = package_data
        
        tool = fair_ds_tools[1]  # get_package
        result = tool.invoke({"package_name": "miappe"})
        
        assert result["success"] is True
        assert result["data"] == package_data
        assert result["error"] is None
        mock_client.get_package.assert_called_once_with("miappe")
    
    def test_package_not_found(self, fair_ds_tools, mock_client):
        """Test handling when package is not found."""
        mock_client.get_package.return_value = None
        
        tool = fair_ds_tools[1]
        result = tool.invoke({"package_name": "nonexistent"})
        
        assert result["success"] is False
        assert result["data"] is None
        assert "not found" in result["error"]
    
    def test_handles_exception(self, fair_ds_tools, mock_client):
        """Test error handling."""
        mock_client.get_package.side_effect = Exception("Network error")
        
        tool = fair_ds_tools[1]
        result = tool.invoke({"package_name": "miappe"})
        
        assert result["success"] is False
        assert "Network error" in result["error"]


class TestGetTermsTool:
    """Test get_terms tool."""
    
    def test_successful_retrieval(self, fair_ds_tools, mock_client):
        """Test successful terms retrieval."""
        terms_data = {
            "temperature": {"label": "Temperature", "definition": "..."},
            "humidity": {"label": "Humidity", "definition": "..."}
        }
        mock_client.get_terms.return_value = terms_data
        
        tool = fair_ds_tools[2]  # get_terms
        result = tool.invoke({"force_refresh": False})
        
        assert result["success"] is True
        assert result["data"] == terms_data
        assert result["error"] is None
    
    def test_handles_exception(self, fair_ds_tools, mock_client):
        """Test error handling."""
        mock_client.get_terms.side_effect = Exception("Database error")
        
        tool = fair_ds_tools[2]
        result = tool.invoke({"force_refresh": False})
        
        assert result["success"] is False
        assert result["data"] == {}
        assert "Database error" in result["error"]


class TestSearchTermsForFieldsTool:
    """Test search_terms_for_fields tool."""
    
    def test_successful_search(self, fair_ds_tools, mock_client):
        """Test successful term search."""
        search_results = [
            {"term_name": "temperature", "label": "Temperature"},
            {"term_name": "air_temperature", "label": "Air Temperature"}
        ]
        mock_client.search_terms_for_fields.return_value = search_results
        
        tool = fair_ds_tools[3]  # search_terms_for_fields
        result = tool.invoke({"term_label": "temperature", "definition": None})
        
        assert result["success"] is True
        assert result["data"] == search_results
        mock_client.search_terms_for_fields.assert_called_once_with("temperature", None)
    
    def test_with_definition_filter(self, fair_ds_tools, mock_client):
        """Test search with definition parameter."""
        mock_client.search_terms_for_fields.return_value = []
        
        tool = fair_ds_tools[3]
        tool.invoke({"term_label": "temp", "definition": "measure"})
        
        mock_client.search_terms_for_fields.assert_called_once_with("temp", "measure")
    
    def test_handles_exception(self, fair_ds_tools, mock_client):
        """Test error handling."""
        mock_client.search_terms_for_fields.side_effect = Exception("Search failed")
        
        tool = fair_ds_tools[3]
        result = tool.invoke({"term_label": "test", "definition": None})
        
        assert result["success"] is False
        assert result["data"] == []


class TestSearchFieldsInPackagesTool:
    """Test search_fields_in_packages tool."""
    
    def test_successful_search(self, fair_ds_tools, mock_client):
        """Test successful field search."""
        search_results = [
            {"label": "temperature", "packageName": "miappe"},
            {"label": "air_temperature", "packageName": "soil"}
        ]
        mock_client.search_fields_in_packages.return_value = search_results
        
        tool = fair_ds_tools[4]  # search_fields_in_packages
        result = tool.invoke({"field_label": "temperature", "package_names": None})
        
        assert result["success"] is True
        assert result["data"] == search_results
        mock_client.search_fields_in_packages.assert_called_once_with("temperature", None)
    
    def test_with_package_names_string(self, fair_ds_tools, mock_client):
        """Test search with comma-separated package names."""
        mock_client.search_fields_in_packages.return_value = []
        
        tool = fair_ds_tools[4]
        tool.invoke({"field_label": "temp", "package_names": "miappe,soil,default"})
        
        # Verify it was called with list
        mock_client.search_fields_in_packages.assert_called_once()
        call_args = mock_client.search_fields_in_packages.call_args
        assert call_args[0][0] == "temp"
        assert call_args[0][1] == ["miappe", "soil", "default"]
    
    def test_handles_exception(self, fair_ds_tools, mock_client):
        """Test error handling."""
        mock_client.search_fields_in_packages.side_effect = Exception("Search error")
        
        tool = fair_ds_tools[4]
        result = tool.invoke({"field_label": "test", "package_names": None})
        
        assert result["success"] is False
        assert result["data"] == []


class TestToolsWithoutClient:
    """Test tools creation when client is not available."""
    
    @patch('fairifier.config.config')
    def test_creates_tools_with_unavailable_client(self, mock_config):
        """Test that tools are created even if client is unavailable."""
        mock_config.fair_ds_api_url = None
        
        tools = create_fair_ds_tools(client=None)
        
        assert len(tools) == 5
    
    @patch('fairifier.config.config')
    def test_tools_return_error_when_client_unavailable(self, mock_config):
        """Test that tools return appropriate error when client is None."""
        # Set config to fail client creation
        mock_config.fair_ds_api_url = None
        
        tools = create_fair_ds_tools(client=None)
        
        # Test each tool returns error for unavailable client
        for tool in tools:
            # Create appropriate input for each tool
            if tool.name == "get_available_packages":
                result = tool.invoke({"force_refresh": False})
            elif tool.name == "get_package":
                result = tool.invoke({"package_name": "test"})
            elif tool.name == "get_terms":
                result = tool.invoke({"force_refresh": False})
            elif tool.name == "search_terms_for_fields":
                result = tool.invoke({"term_label": "test", "definition": None})
            elif tool.name == "search_fields_in_packages":
                result = tool.invoke({"field_label": "test", "package_names": None})
            
            assert result["success"] is False
            assert "not available" in result["error"].lower()


class TestToolIntegrationWithLangChain:
    """Test that tools work correctly with LangChain framework."""
    
    def test_tools_are_langchain_tools(self, fair_ds_tools):
        """Test that created objects are valid LangChain tools."""
        from langchain_core.tools import BaseTool
        
        for tool in fair_ds_tools:
            # Check it has LangChain tool interface
            assert hasattr(tool, "name")
            assert hasattr(tool, "description")
            assert hasattr(tool, "invoke")
            assert callable(tool.invoke)
    
    def test_tool_invoke_returns_dict(self, fair_ds_tools, mock_client):
        """Test that all tools return dictionaries."""
        mock_client.get_available_packages.return_value = []
        mock_client.get_package.return_value = None
        mock_client.get_terms.return_value = {}
        mock_client.search_terms_for_fields.return_value = []
        mock_client.search_fields_in_packages.return_value = []
        
        for i, tool in enumerate(fair_ds_tools):
            # Invoke with appropriate parameters
            if i == 0:  # get_available_packages
                result = tool.invoke({"force_refresh": False})
            elif i == 1:  # get_package
                result = tool.invoke({"package_name": "test"})
            elif i == 2:  # get_terms
                result = tool.invoke({"force_refresh": False})
            elif i == 3:  # search_terms_for_fields
                result = tool.invoke({"term_label": "test", "definition": None})
            elif i == 4:  # search_fields_in_packages
                result = tool.invoke({"field_label": "test", "package_names": None})
            
            assert isinstance(result, dict)
            assert "success" in result
            assert "data" in result
            assert "error" in result
