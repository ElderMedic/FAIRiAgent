from unittest.mock import patch, Mock
from fairifier.tools.science_tools import create_science_tools

def test_science_tools_registration():
    tools = create_science_tools()
    names = [t.name for t in tools]
    assert "fetch_external_url" in names
    assert "query_ncbi_accession" in names
    assert "query_ena_accession" in names

@patch("requests.get")
def test_fetch_external_url(mock_get):
    mock_response = Mock()
    mock_response.headers = {"content-type": "text/html"}
    mock_response.content = b"<html><body><p>Hello World</p></body></html>"
    mock_response.status_code = 200
    mock_get.return_value = mock_response
    
    tools = create_science_tools()
    fetch_url_tool = [t for t in tools if t.name == "fetch_external_url"][0]
    
    res = fetch_url_tool.invoke("https://example.com")
    assert res["success"] is True
    assert "Hello World" in res["data"]

@patch("requests.get")
def test_query_ncbi_accession(mock_get):
    # Mock esearch and esummary
    mock_response = Mock()
    mock_response.json.side_effect = [
        {"esearchresult": {"idlist": ["123456"]}},
        {"result": {"123456": {"title": "Test Biosample"}}}
    ]
    mock_response.status_code = 200
    mock_get.return_value = mock_response
    
    tools = create_science_tools()
    ncbi_tool = [t for t in tools if t.name == "query_ncbi_accession"][0]
    
    res = ncbi_tool.invoke({"accession_id": "SAMN123456"})
    assert res["success"] is True
    assert res["data"]["title"] == "Test Biosample"

@patch("requests.get")
def test_query_ena_accession(mock_get):
    mock_response = Mock()
    mock_response.json.return_value = [{"run_accession": "ERR123"}]
    mock_response.status_code = 200
    mock_get.return_value = mock_response
    
    tools = create_science_tools()
    ena_tool = [t for t in tools if t.name == "query_ena_accession"][0]
    
    res = ena_tool.invoke({"accession_id": "ERR123"})
    assert res["success"] is True
    assert res["data"][0]["run_accession"] == "ERR123"
