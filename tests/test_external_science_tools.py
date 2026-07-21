import socket
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fairifier.tools.science_tools import create_science_tools


PUBLIC_DNS = [
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
]


def _response(
    body: bytes = b"<html><body><p>Hello World</p></body></html>",
    *,
    status: int = 200,
    headers: dict | None = None,
    peer: str | None = None,
) -> Mock:
    response = Mock()
    response.status_code = status
    response.headers = headers or {"content-type": "text/html"}
    response.encoding = "utf-8"
    response.iter_content.return_value = [body]
    connection = None
    if peer is not None:
        sock = Mock()
        sock.getpeername.return_value = (peer, 443)
        connection = SimpleNamespace(sock=sock)
    response.raw = SimpleNamespace(_connection=connection)
    return response

def test_science_tools_registration():
    tools = create_science_tools()
    names = [t.name for t in tools]
    assert "fetch_external_url" in names
    assert "query_ncbi_accession" in names
    assert "query_ena_accession" in names

@patch("socket.getaddrinfo", return_value=PUBLIC_DNS)
@patch("requests.get")
def test_fetch_external_url(mock_get, _mock_dns):
    mock_get.return_value = _response()
    
    tools = create_science_tools()
    fetch_url_tool = [t for t in tools if t.name == "fetch_external_url"][0]
    
    res = fetch_url_tool.invoke("https://example.com")
    assert res["success"] is True
    assert "Hello World" in res["data"]
    mock_get.assert_called_once_with(
        "https://example.com",
        timeout=10,
        headers={"User-Agent": "FAIRiAgent/2.2.0"},
        allow_redirects=False,
        stream=True,
    )


@patch("requests.get")
def test_fetch_external_url_rejects_localhost_without_request(mock_get):
    fetch_url_tool = [
        tool for tool in create_science_tools() if tool.name == "fetch_external_url"
    ][0]

    result = fetch_url_tool.invoke("http://localhost:8000/private")

    assert result["success"] is False
    assert "not public" in result["error"]
    mock_get.assert_not_called()


@patch(
    "socket.getaddrinfo",
    return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443)),
    ],
)
@patch("requests.get")
def test_fetch_external_url_rejects_private_dns_resolution(mock_get, _mock_dns):
    fetch_url_tool = [
        tool for tool in create_science_tools() if tool.name == "fetch_external_url"
    ][0]

    result = fetch_url_tool.invoke("https://metadata.example.test/secret")

    assert result["success"] is False
    assert "non-public" in result["error"]
    mock_get.assert_not_called()


@patch("socket.getaddrinfo", return_value=PUBLIC_DNS)
@patch("requests.get")
def test_fetch_external_url_rejects_private_connected_peer(mock_get, _mock_dns):
    mock_get.return_value = _response(peer="127.0.0.1")
    fetch_url_tool = [
        tool for tool in create_science_tools() if tool.name == "fetch_external_url"
    ][0]

    result = fetch_url_tool.invoke("https://example.com")

    assert result["success"] is False
    assert "non-public" in result["error"]


@patch("socket.getaddrinfo", return_value=PUBLIC_DNS)
@patch("requests.get")
def test_fetch_external_url_validates_redirect_target(mock_get, _mock_dns):
    mock_get.return_value = _response(
        b"",
        status=302,
        headers={"location": "http://127.0.0.1/admin"},
    )
    fetch_url_tool = [
        tool for tool in create_science_tools() if tool.name == "fetch_external_url"
    ][0]

    result = fetch_url_tool.invoke("https://example.com/start")

    assert result["success"] is False
    assert "non-public" in result["error"]
    assert mock_get.call_count == 1


@patch("socket.getaddrinfo", return_value=PUBLIC_DNS)
@patch("requests.get")
def test_fetch_external_url_rejects_oversized_response(mock_get, _mock_dns):
    response = _response()
    response.iter_content.return_value = [b"x" * (2 * 1024 * 1024), b"y"]
    mock_get.return_value = response
    fetch_url_tool = [
        tool for tool in create_science_tools() if tool.name == "fetch_external_url"
    ][0]

    result = fetch_url_tool.invoke("https://example.com/large")

    assert result["success"] is False
    assert "2 MiB" in result["error"]

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
