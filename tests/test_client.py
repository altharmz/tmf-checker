import pytest

from tests.stub import serve
from tmf_checker.client import Client, TransportError, redact
from tmf_checker.spec import Spec


def test_credentials_are_redacted():
    out = redact(
        {
            "Cookie": "s=1",
            "Authorization": "Bearer x",
            "X-Api-Key": "k",
            "X-Session-Token": "t",
            "Accept": "application/json",
        }
    )
    assert out == {
        "Cookie": "<redacted>",
        "Authorization": "<redacted>",
        "X-Api-Key": "<redacted>",
        "X-Session-Token": "<redacted>",
        "Accept": "application/json",
    }


def test_base_url_must_be_http():
    with pytest.raises(ValueError, match="http"):
        Client("file:///etc/passwd")


def test_url_joins_the_api_root_and_spec_path():
    client = Client("https://h/tmf-api/productCatalogManagement/v5/")
    assert client.url("/productOffering", {"limit": 1}) == (
        "https://h/tmf-api/productCatalogManagement/v5/productOffering?limit=1"
    )
    assert client.resolve("/other/1") == "https://h/other/1"
    assert client.resolve("https://x/1") == "https://x/1"


def test_non_2xx_is_an_answer_and_evidence_is_redacted():
    with serve(Spec.bundled("TMF620", 5)) as stub:
        client = Client(stub.base_url, {"Cookie": "secret"})
        response = client.get("/productOffering/nope")
    assert response.status == 404 and response.json()["@type"] == "Error"
    assert response.evidence()["request_headers"]["Cookie"] == "<redacted>"
    assert client.log == [response]


def test_unreachable_is_a_transport_error():
    with pytest.raises(TransportError):
        Client("http://127.0.0.1:9", timeout=2).get("/x")
