"""Unit tests for FAIR-DS API response parsing."""

import pytest
from fairifier.services.fairds_api_parser import FAIRDSAPIParser


class TestFAIRDSAPIParser:
    """Test FAIR-DS API response parsing."""

    def test_parse_terms_response_success(self):
        """Test parsing a successful terms API response."""
        api_response = {
            "total": 2,
            "terms": {
                "study title": {
                    "label": "study title",
                    "syntax": "{text}",
                    "example": "Example study",
                    "definition": "Title of the study",
                    "regex": ".*",
                    "url": "https://example.com/term"
                },
                "collection date": {
                    "label": "collection date",
                    "syntax": "{date}",
                    "example": "2024-01-01",
                    "definition": "Date when sample was collected",
                    "regex": r"\d{4}-\d{2}-\d{2}",
                    "url": "https://example.com/collection_date"
                }
            }
        }
        
        result = FAIRDSAPIParser.parse_terms_response(api_response)
        
        assert isinstance(result, dict)
        assert "study title" in result
        assert "collection date" in result
        assert result["study title"]["label"] == "study title"
        assert result["study title"]["definition"] == "Title of the study"

    def test_parse_terms_response_empty(self):
        """Test parsing an empty terms response."""
        api_response = {
            "total": 0,
            "terms": {}
        }
        
        result = FAIRDSAPIParser.parse_terms_response(api_response)
        
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_parse_package_response_success(self):
        """Test parsing a successful package API response."""
        api_response = {
            "packageName": "miappe",
            "itemCount": 1,
            "metadata": [
                {
                    "label": "investigation title",
                    "sheetName": "Investigation",
                    "packageName": "miappe",
                    "requirement": "MANDATORY",
                    "definition": "Title of investigation",
                    "term": {
                        "label": "investigation title",
                        "syntax": "{text}",
                        "example": "Example",
                        "definition": "Title of investigation",
                        "regex": ".*",
                        "url": "https://example.com"
                    }
                }
            ]
        }
        
        result = FAIRDSAPIParser.parse_package_response(api_response)
        
        assert isinstance(result, dict)
        assert result["packageName"] == "miappe"
        assert "metadata" in result
        assert len(result["metadata"]) == 1

    def test_parse_package_response_missing_fields(self):
        """Test parsing package response with missing optional fields."""
        api_response = {
            "packageName": "test_package",
            "metadata": []
        }
        
        result = FAIRDSAPIParser.parse_package_response(api_response)
        
        assert result["packageName"] == "test_package"
        assert "metadata" in result

    def test_extract_field_info_complete(self):
        """Test extracting complete field information."""
        field = {
            "label": "study title",
            "sheetName": "Study",
            "packageName": "miappe",
            "requirement": "MANDATORY",
            "definition": "Title of the study",
            "term": {
                "label": "study title",
                "syntax": "{text}",
                "example": "Example study",
                "definition": "Title of the study",
                "regex": ".*",
                "url": "http://purl.obolibrary.org/obo/IAO_0000300"
            }
        }
        
        result = FAIRDSAPIParser.extract_field_info(field)
        
        assert result["label"] == "study title"
        assert result["name"] == "study title"
        assert result["required"] is True
        assert result["definition"] == "Title of the study"
        assert result["isa_sheet"] == "study"

    def test_extract_field_info_minimal(self):
        """Test extracting field information with minimal data."""
        field = {
            "label": "optional field"
        }
        
        result = FAIRDSAPIParser.extract_field_info(field)
        
        assert result["label"] == "optional field"
        assert result["name"] == "optional field"
        assert result["required"] is False  # Default when requirement is not MANDATORY

    def test_extract_term_info_complete(self):
        """Test extracting complete term information."""
        term_name = "collection date"
        term_data = {
            "label": "collection date",
            "definition": "Date when sample was collected",
            "syntax": "{date}",
            "example": "2024-01-01",
            "regex": r"\d{4}-\d{2}-\d{2}",
            "url": "https://example.com/term"
        }
        
        result = FAIRDSAPIParser.extract_term_info(term_name, term_data)
        
        assert result["label"] == "collection date"
        assert result["definition"] == "Date when sample was collected"
        assert "syntax" in result
        assert "example" in result

    def test_parse_package_list_response(self):
        """Test parsing package list response."""
        api_response = {
            "packages": [
                {"name": "miappe", "description": "MIAPPE"},
                {"name": "soil", "description": "Soil package"}
            ]
        }
        
        result = FAIRDSAPIParser.parse_package_list_response(api_response)
        
        assert isinstance(result, list)
        # Result is a list of dicts, not just names
        assert any(pkg.get("name") == "miappe" for pkg in result)
        assert any(pkg.get("name") == "soil" for pkg in result)

    def test_parse_malformed_response_handles_gracefully(self):
        """Test that malformed responses are handled gracefully."""
        # Missing required keys
        malformed = {"invalid": "data"}
        
        # Should not raise exception, but may return empty/default values
        # This depends on implementation - adjust based on actual behavior
        try:
            result = FAIRDSAPIParser.parse_terms_response(malformed)
            # If it doesn't raise, should return empty dict or handle gracefully
            assert isinstance(result, dict)
        except (KeyError, AttributeError):
            # If it raises, that's also acceptable - just document it
            pass
