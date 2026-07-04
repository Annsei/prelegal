"""Tests for /api/templates/{doc_id}.

The endpoint reads from the real templates/ directory at the repo root —
those files are committed CommonPaper templates so we exercise the real
load path rather than mocking it.
"""

from __future__ import annotations


def test_get_template_returns_mnda_with_cover_page(client):
    res = client.get("/api/templates/mutual-nda")
    assert res.status_code == 200
    body = res.json()
    assert body["doc_id"] == "mutual-nda"
    assert body["title"].startswith("Mutual Non-Disclosure Agreement")
    # MNDA is the only doc with a cover page in the index — should be present.
    assert body["cover_page"] is not None
    assert "Cover Page" in body["cover_page"]
    # Standard terms include the boilerplate clauses.
    assert "Confidential Information" in body["standard_terms"]


def test_get_template_returns_csa_without_cover_page(client):
    """Other catalog docs only have standard_terms — cover_page should be null."""
    res = client.get("/api/templates/cloud-service-agreement")
    assert res.status_code == 200
    body = res.json()
    assert body["doc_id"] == "cloud-service-agreement"
    assert body["cover_page"] is None
    assert "Cloud Service Agreement" in body["standard_terms"]


def test_get_template_404s_on_unknown_doc(client):
    res = client.get("/api/templates/no-such-doc")
    assert res.status_code == 404
    assert "unknown document id" in res.json()["detail"]


def test_csa_template_includes_manifest(client):
    res = client.get("/api/templates/cloud-service-agreement")
    assert res.status_code == 200
    manifest = res.json()["manifest"]
    assert manifest is not None
    assert manifest["doc_id"] == "cloud-service-agreement"
    keys = [f["key"] for f in manifest["fields"]]
    # Parties + the terms the template body actually references.
    for expected in (
        "Provider",
        "Customer",
        "Subscription Period",
        "Effective Date",
        "Governing Law",
        "General Cap Amount",
    ):
        assert expected in keys
    # Every field carries both label languages; required is boolean.
    for field in manifest["fields"]:
        assert field["label"]["zh"] and field["label"]["en"]
        assert isinstance(field["required"], bool)
    section_keys = {s["key"] for s in manifest["sections"]}
    assert {f["section"] for f in manifest["fields"]} <= section_keys


def test_docs_without_manifest_return_null_manifest(client):
    res = client.get("/api/templates/mutual-nda")
    assert res.status_code == 200
    assert res.json()["manifest"] is None
