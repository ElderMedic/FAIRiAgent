"""External science API tools used by deepagents inner loops."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import requests
from langchain_core.tools import tool

from ..config import config
from ..services.retrieval_cache import get_cached_value, make_cache_key, store_cached_value

logger = logging.getLogger(__name__)
_SCIENCE_FAILURE_SENTINEL = "__science_error__"


def _safe_get_json(
    url: str,
    *,
    params: Dict[str, Any] | None = None,
    timeout: int = 8,
    cache_store: Dict[str, Any] | None = None,
):
    """Fetch JSON from an external API with predictable failure semantics."""
    cache_key = None
    if cache_store is not None:
        cache_key = make_cache_key("http_get_json", {"url": url, "params": params or {}})
        cached = get_cached_value(cache_store, cache_key)
        if cached is not None:
            if isinstance(cached, dict) and _SCIENCE_FAILURE_SENTINEL in cached:
                return False, None, str(cached.get(_SCIENCE_FAILURE_SENTINEL))
            return True, cached, None

    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if cache_store is not None and cache_key is not None:
            store_cached_value(cache_store, cache_key, payload)
        return True, payload, None
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("Science API request failed: %s", exc)
        if cache_store is not None and cache_key is not None:
            store_cached_value(
                cache_store,
                cache_key,
                {_SCIENCE_FAILURE_SENTINEL: str(exc)},
            )
        return False, None, str(exc)


def create_science_tools(
    *,
    cache_store: Dict[str, Any] | None = None,
    crossref_mailto: str | None = None,
) -> List:
    """Create zero-auth science enrichment tools."""

    @tool
    def search_ontology_term(term: str, ontology: str = "go,efo,obi,envo,ncbitaxon") -> Dict[str, Any]:
        """Search EBI OLS4 for ontology matches."""
        success, payload, error = _safe_get_json(
            "https://www.ebi.ac.uk/ols4/api/search",
            params={"q": term, "ontology": ontology, "rows": 5},
            cache_store=cache_store,
        )
        if not success:
            return {"success": False, "data": [], "error": f"OLS4 unavailable: {error}"}

        docs = payload.get("response", {}).get("docs", [])
        results = [
            {
                "label": doc.get("label"),
                "iri": doc.get("iri"),
                "ontology_name": doc.get("ontology_name"),
                "description": (doc.get("description") or [None])[0],
            }
            for doc in docs
        ]
        return {"success": True, "data": results, "error": None}

    @tool
    def resolve_doi_metadata(doi: str) -> Dict[str, Any]:
        """Resolve DOI metadata from Crossref."""
        doi = doi.strip().removeprefix("https://doi.org/")
        success, payload, error = _safe_get_json(
            f"https://api.crossref.org/works/{doi}",
            params={"mailto": crossref_mailto or config.crossref_mailto or "fairiagent@example.invalid"},
            cache_store=cache_store,
        )
        if not success:
            return {"success": False, "data": None, "error": f"Crossref unavailable: {error}"}

        message = payload.get("message", {})
        data = {
            "DOI": message.get("DOI"),
            "title": (message.get("title") or [None])[0],
            "publisher": message.get("publisher"),
            "published": message.get("published", {}),
            "license": message.get("license", []),
            "funder": message.get("funder", []),
            "author": message.get("author", []),
        }
        return {"success": True, "data": data, "error": None}

    @tool
    def search_literature(query: str, n_results: int = 5) -> Dict[str, Any]:
        """Search Europe PMC for related papers and extracted terms."""
        success, payload, error = _safe_get_json(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={"query": query, "format": "json", "pageSize": max(1, min(n_results, 10))},
            cache_store=cache_store,
        )
        if not success:
            return {"success": False, "data": [], "error": f"Europe PMC unavailable: {error}"}

        results = payload.get("resultList", {}).get("result", [])
        data = [
            {
                "title": item.get("title"),
                "doi": item.get("doi"),
                "journal": item.get("journalTitle"),
                "pubYear": item.get("pubYear"),
                "authorString": item.get("authorString"),
            }
            for item in results
        ]
        return {"success": True, "data": data, "error": None}

    @tool
    def search_similar_papers(query: str, n_results: int = 5) -> Dict[str, Any]:
        """Search OpenAlex for related papers and topic hints."""
        success, payload, error = _safe_get_json(
            "https://api.openalex.org/works",
            params={
                "search": query,
                "per-page": max(1, min(n_results, 10)),
                "select": "display_name,doi,publication_year,primary_topic,authorships",
            },
            cache_store=cache_store,
        )
        if not success:
            return {"success": False, "data": [], "error": f"OpenAlex unavailable: {error}"}

        results = payload.get("results", [])
        data = [
            {
                "title": item.get("display_name"),
                "doi": item.get("doi"),
                "publication_year": item.get("publication_year"),
                "primary_topic": (item.get("primary_topic") or {}).get("display_name"),
                "authors": [
                    authorship.get("author", {}).get("display_name")
                    for authorship in item.get("authorships", [])[:5]
                ],
            }
            for item in results
        ]
        return {"success": True, "data": data, "error": None}

    @tool
    def fetch_external_url(url: str) -> Dict[str, Any]:
        """Fetch content of a web link or URL and extract readable text."""
        if not url.startswith(("http://", "https://")):
            return {"success": False, "data": None, "error": "Invalid URL protocol"}
        try:
            response = requests.get(url, timeout=10, headers={"User-Agent": "FAIRiAgent/2.1.0"})
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    return {"success": True, "data": response.json(), "error": None}
                except Exception:
                    pass
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, "html.parser")
            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text(separator="\n")
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            clean_text = "\n".join(chunk for chunk in chunks if chunk)
            max_len = 15000
            if len(clean_text) > max_len:
                clean_text = clean_text[:max_len] + "\n\n[... content truncated due to size limit ...]"
            return {"success": True, "data": clean_text, "error": None}
        except Exception as e:
            return {"success": False, "data": None, "error": str(e)}

    @tool
    def query_ncbi_accession(accession_id: str, db: str = "biosample") -> Dict[str, Any]:
        """Query NCBI Entrez API for metadata associated with an accession ID (e.g. biosample, sra, gds, nucleotide)."""
        term = accession_id.strip()
        search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        success, payload, error = _safe_get_json(
            search_url,
            params={"db": db, "term": term, "retmode": "json"},
            cache_store=cache_store,
        )
        if not success:
            return {"success": False, "data": None, "error": f"NCBI Search failed: {error}"}
        id_list = payload.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            return {"success": False, "data": None, "error": f"No NCBI records found for term '{term}' in db '{db}'"}
        uid = id_list[0]
        summary_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
        success_sum, payload_sum, error_sum = _safe_get_json(
            summary_url,
            params={"db": db, "id": uid, "retmode": "json"},
            cache_store=cache_store,
        )
        if not success_sum:
            return {"success": False, "data": None, "error": f"NCBI Summary failed: {error_sum}"}
        result = payload_sum.get("result", {}).get(uid, {})
        return {"success": True, "data": result, "error": None}

    @tool
    def query_ena_accession(accession_id: str) -> Dict[str, Any]:
        """Query EBI ENA (European Nucleotide Archive) portal API for run/sample details by accession ID."""
        term = accession_id.strip()
        success, payload, error = _safe_get_json(
            "https://www.ebi.ac.uk/ena/portal/api/search",
            params={
                "result": "read_run",
                "query": f'run_accession="{term}" OR sample_accession="{term}" OR study_accession="{term}" OR experiment_accession="{term}"',
                "format": "json",
                "fields": "run_accession,sample_accession,experiment_accession,study_accession,scientific_name,instrument_model,library_layout,fastq_ftp,fastq_galaxy,submitted_ftp,library_name,library_source,library_selection,library_strategy"
            },
            cache_store=cache_store,
        )
        if not success or not payload:
            success, payload, error = _safe_get_json(
                "https://www.ebi.ac.uk/ena/portal/api/search",
                params={
                    "result": "sample",
                    "query": f'sample_accession="{term}" OR secondary_sample_accession="{term}"',
                    "format": "json",
                    "fields": "sample_accession,scientific_name,tax_id,country,location"
                },
                cache_store=cache_store,
            )
        if not success:
            return {"success": False, "data": None, "error": f"ENA Search failed: {error}"}
        if not payload:
            return {"success": False, "data": None, "error": f"No ENA records found for '{term}'"}
        return {"success": True, "data": payload, "error": None}

    return [
        search_ontology_term,
        resolve_doi_metadata,
        search_literature,
        search_similar_papers,
        fetch_external_url,
        query_ncbi_accession,
        query_ena_accession,
    ]
