"""Tests for external science API tools."""

import requests

from fairifier.tools.science_tools import create_science_tools


class _FakeResponse:
    """Simple fake requests response."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_search_ontology_term_parses_ols_response(monkeypatch):
    def fake_get(url, params=None, timeout=0):
        return _FakeResponse(
            {
                "response": {
                    "docs": [
                        {
                            "label": "leaf",
                            "iri": "http://example.org/leaf",
                            "ontology_name": "envo",
                            "description": ["leaf description"],
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr(requests, "get", fake_get)
    tools = {tool.name: tool for tool in create_science_tools()}

    result = tools["search_ontology_term"].invoke({"term": "leaf"})

    assert result["success"] is True
    assert result["data"][0]["label"] == "leaf"
    assert result["data"][0]["ontology_name"] == "envo"


def test_resolve_doi_metadata_graceful_failure(monkeypatch):
    def fake_get(url, params=None, timeout=0):
        raise requests.RequestException("offline")

    monkeypatch.setattr(requests, "get", fake_get)
    tools = {tool.name: tool for tool in create_science_tools()}

    result = tools["resolve_doi_metadata"].invoke({"doi": "10.1000/test"})

    assert result["success"] is False
    assert "Crossref unavailable" in result["error"]


def test_science_tools_use_cache(monkeypatch):
    calls = {"count": 0}

    def fake_get(url, params=None, timeout=0):
        calls["count"] += 1
        return _FakeResponse(
            {
                "response": {
                    "docs": [
                        {
                            "label": "earthworm",
                            "iri": "http://example.org/earthworm",
                            "ontology_name": "ncbitaxon",
                            "description": ["earthworm"],
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr(requests, "get", fake_get)
    cache_store = {}
    tools = {tool.name: tool for tool in create_science_tools(cache_store=cache_store)}

    result1 = tools["search_ontology_term"].invoke({"term": "earthworm"})
    result2 = tools["search_ontology_term"].invoke({"term": "earthworm"})

    assert result1["success"] is True
    assert result2["success"] is True
    assert calls["count"] == 1
