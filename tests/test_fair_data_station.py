"""Integration tests for FAIR Data Station API client.

These tests verify that the FAIR-DS API client can actually connect to
the API and retrieve data from the database.
"""

import pytest
from fairifier.services.fair_data_station import (
    FAIRDataStationClient,
    FAIRDataStationUnavailable,
)
from fairifier.config import config


@pytest.fixture
def fair_ds_client():
    """Create a FAIR-DS client instance."""
    api_url = config.fair_ds_api_url or "http://localhost:8083"
    return FAIRDataStationClient(base_url=api_url, timeout=15)


class TestFAIRDataStationConnection:
    """Test FAIR-DS API connectivity and availability."""

    @pytest.mark.integration
    def test_api_is_available(self, fair_ds_client):
        """Test that FAIR-DS API is reachable."""
        is_available = fair_ds_client.is_available()
        
        if not is_available:
            pytest.skip(
                f"FAIR-DS API not available at {fair_ds_client._base_url}. "
                "Ensure the API server is running."
            )
        
        assert is_available is True

    @pytest.mark.integration
    def test_api_overview_endpoint(self, fair_ds_client):
        """Test that API overview endpoint returns valid response."""
        if not fair_ds_client.is_available():
            pytest.skip("FAIR-DS API not available")
        
        try:
            import requests
            response = fair_ds_client._session.get(
                f"{fair_ds_client._base_url}/api",
                timeout=fair_ds_client._timeout
            )
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, dict)
        except Exception as e:
            pytest.fail(f"Failed to fetch API overview: {e}")


class TestFAIRDataStationTermsAPI:
    """Test FAIR-DS Terms API endpoints."""

    @pytest.mark.integration
    def test_get_all_terms(self, fair_ds_client):
        """Test fetching all terms from the database."""
        if not fair_ds_client.is_available():
            pytest.skip("FAIR-DS API not available")
        
        terms = fair_ds_client.get_terms()
        
        assert isinstance(terms, dict)
        assert len(terms) > 0, "Should have at least one term in database"
        
        # Verify term structure
        first_term_name = list(terms.keys())[0]
        first_term = terms[first_term_name]
        
        assert "label" in first_term or "definition" in first_term, \
            "Term should have at least label or definition"

    @pytest.mark.integration
    def test_search_terms_by_label(self, fair_ds_client):
        """Test searching terms by label pattern."""
        if not fair_ds_client.is_available():
            pytest.skip("FAIR-DS API not available")
        
        # Search for common terms
        results = fair_ds_client.search_terms(label="title")
        
        assert isinstance(results, dict)
        # Should find at least one term with "title" in the label
        assert len(results) > 0, "Should find at least one term with 'title' in label"
        
        # Verify results contain "title" in label (case-insensitive)
        for term_name, term_data in results.items():
            label = term_data.get("label", "").lower()
            assert "title" in label, f"Term '{term_name}' should contain 'title' in label"

    @pytest.mark.integration
    def test_search_terms_by_definition(self, fair_ds_client):
        """Test searching terms by definition pattern."""
        if not fair_ds_client.is_available():
            pytest.skip("FAIR-DS API not available")
        
        # Search for terms related to date/time
        results = fair_ds_client.search_terms(definition="date")
        
        assert isinstance(results, dict)
        # Should find at least one term with "date" in definition
        if len(results) > 0:
            # Verify results contain "date" in definition (case-insensitive)
            for term_name, term_data in results.items():
                definition = term_data.get("definition", "").lower()
                assert "date" in definition, \
                    f"Term '{term_name}' should contain 'date' in definition"

    @pytest.mark.integration
    def test_get_term_by_label(self, fair_ds_client):
        """Test fetching a specific term by label."""
        if not fair_ds_client.is_available():
            pytest.skip("FAIR-DS API not available")
        
        # First get all terms to find a valid term label
        all_terms = fair_ds_client.get_terms()
        if len(all_terms) == 0:
            pytest.skip("No terms available in database")
        
        # Get first term's label
        first_term = list(all_terms.values())[0]
        term_label = first_term.get("label", "")
        
        if not term_label:
            pytest.skip("No term with label found")
        
        term = fair_ds_client.get_term_by_label(term_label)
        
        assert term is not None
        assert isinstance(term, dict)
        assert "label" in term or "definition" in term


class TestFAIRDataStationPackageAPI:
    """Test FAIR-DS Package API endpoints."""

    @pytest.mark.integration
    def test_get_available_packages(self, fair_ds_client):
        """Test fetching list of available packages."""
        if not fair_ds_client.is_available():
            pytest.skip("FAIR-DS API not available")
        
        packages = fair_ds_client.get_available_packages()
        
        assert isinstance(packages, list)
        assert len(packages) > 0, "Should have at least one package in database"
        
        # Verify package names are strings
        for pkg in packages:
            assert isinstance(pkg, str), "Package names should be strings"

    @pytest.mark.integration
    def test_get_package_by_name(self, fair_ds_client):
        """Test fetching a specific package by name."""
        if not fair_ds_client.is_available():
            pytest.skip("FAIR-DS API not available")
        
        # First get available packages
        available_packages = fair_ds_client.get_available_packages()
        if len(available_packages) == 0:
            pytest.skip("No packages available in database")
        
        # Try to get the first package
        package_name = available_packages[0]
        package = fair_ds_client.get_package(package_name)
        
        assert package is not None
        assert isinstance(package, dict)
        assert "packageName" in package or "metadata" in package, \
            "Package should have packageName or metadata field"
        
        # Verify package contains metadata fields
        if "metadata" in package:
            assert isinstance(package["metadata"], list), \
                "Package metadata should be a list"

    @pytest.mark.integration
    def test_get_package_nonexistent(self, fair_ds_client):
        """Test fetching a non-existent package."""
        if not fair_ds_client.is_available():
            pytest.skip("FAIR-DS API not available")
        
        # Try to get a package that doesn't exist
        package = fair_ds_client.get_package("nonexistent_package_xyz123")
        
        # Should return None or empty dict, not raise exception
        assert package is None or package == {} or len(package) == 0


class TestFAIRDataStationDataIntegrity:
    """Test data integrity and structure from FAIR-DS API."""

    @pytest.mark.integration
    def test_package_contains_valid_fields(self, fair_ds_client):
        """Test that packages contain valid field structures."""
        if not fair_ds_client.is_available():
            pytest.skip("FAIR-DS API not available")
        
        packages = fair_ds_client.get_available_packages()
        if len(packages) == 0:
            pytest.skip("No packages available")
        
        package_name = packages[0]
        package = fair_ds_client.get_package(package_name)
        
        if not package or "metadata" not in package:
            pytest.skip(f"Package '{package_name}' has no metadata")
        
        metadata = package["metadata"]
        assert len(metadata) > 0, "Package should have at least one field"
        
        # Check first field structure
        first_field = metadata[0]
        assert "label" in first_field or "term" in first_field, \
            "Field should have label or term"
        
        # If field has term, verify term structure
        if "term" in first_field:
            term = first_field["term"]
            assert isinstance(term, dict), "Term should be a dictionary"

    @pytest.mark.integration
    def test_terms_have_required_fields(self, fair_ds_client):
        """Test that terms have required fields."""
        if not fair_ds_client.is_available():
            pytest.skip("FAIR-DS API not available")
        
        terms = fair_ds_client.get_terms()
        if len(terms) == 0:
            pytest.skip("No terms available")
        
        # Check first few terms
        for i, (term_name, term_data) in enumerate(list(terms.items())[:5]):
            assert isinstance(term_data, dict), \
                f"Term '{term_name}' should be a dictionary"
            assert "label" in term_data or "definition" in term_data, \
                f"Term '{term_name}' should have label or definition"


class TestFAIRDataStationErrorHandling:
    """Test error handling for FAIR-DS API client."""

    @pytest.mark.integration
    def test_invalid_url_handling(self):
        """Test that invalid URL is handled gracefully."""
        # Create client with invalid URL
        invalid_client = FAIRDataStationClient(
            base_url="http://invalid-url-that-does-not-exist:9999",
            timeout=2
        )
        
        # Should return False for availability, not raise exception
        is_available = invalid_client.is_available()
        assert is_available is False
        
        # get_terms should return empty dict, not raise exception
        terms = invalid_client.get_terms()
        assert isinstance(terms, dict)
        assert len(terms) == 0

    @pytest.mark.integration
    def test_timeout_handling(self, fair_ds_client):
        """Test that timeout is handled gracefully."""
        if not fair_ds_client.is_available():
            pytest.skip("FAIR-DS API not available")
        
        # Create client with very short timeout
        short_timeout_client = FAIRDataStationClient(
            base_url=fair_ds_client._base_url,
            timeout=0.001  # Very short timeout
        )
        
        # Should handle timeout gracefully
        terms = short_timeout_client.get_terms()
        assert isinstance(terms, dict)
        # May be empty due to timeout, but should not raise exception
