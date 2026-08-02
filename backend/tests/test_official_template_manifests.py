"""Official-template manifest loading and kernel readiness coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.manifests import load_manifest

OFFICIAL_DOCUMENTS = {
    "professional-services-agreement": {
        "title": "专业服务协议",
        "source_code": "GF-2025-1001",
        "required_keys": {"委托方名称", "受托方名称", "委托事务", "争议解决方式"},
        "body_marker": "第一条 委托事务",
    },
    "data-processing-agreement": {
        "title": "数据/个人信息委托处理协议",
        "source_code": "GF-2025-2616",
        "required_keys": {"委托方名称", "受托方名称", "原始数据名称", "争议解决方式"},
        "body_marker": "第一条 原始数据描述",
    },
}
_TEMPLATE_INDEX_PATH = (
    Path(__file__).resolve().parents[2] / "templates" / "templates.json"
)


def _register(client, email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "secretpw1"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _template_entry(doc_id: str) -> dict:
    raw = json.loads(_TEMPLATE_INDEX_PATH.read_text())
    return next(entry for entry in raw["templates"] if entry["id"] == doc_id)


@pytest.mark.parametrize("doc_id", OFFICIAL_DOCUMENTS)
def test_official_template_loads_with_cover_page_and_manifest(client, doc_id: str):
    expected = OFFICIAL_DOCUMENTS[doc_id]

    response = client.get(f"/api/templates/{doc_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == expected["title"]
    assert body["cover_page"] is not None
    assert expected["body_marker"] in body["standard_terms"]
    source = _template_entry(doc_id)["source"]
    assert source["origin"] == "official-contract-model"
    assert source["code"] == expected["source_code"]
    manifest = body["manifest"]
    assert manifest is not None
    assert manifest["doc_id"] == doc_id
    assert expected["required_keys"] <= {
        field["key"] for field in manifest["fields"]
    }
    assert load_manifest(doc_id) == manifest


@pytest.mark.parametrize("doc_id", OFFICIAL_DOCUMENTS)
def test_official_template_required_fields_gate_download_until_confirmed(
    client,
    doc_id: str,
):
    headers = _register(client, f"{doc_id}@example.com")
    created = client.post(
        "/api/documents",
        headers=headers,
        json={"doc_id": doc_id, "title": "official template", "state": {}},
    )
    assert created.status_code == 201
    document = created.json()

    blocked = client.get(
        f"/api/documents/{document['id']}/download-readiness",
        headers=headers,
    )
    assert blocked.status_code == 409

    manifest = load_manifest(doc_id)
    assert manifest is not None
    operations = [
        {
            "op": "confirm",
            "key": field["key"],
            "value": "2026-08-01" if field["type"] == "date" else "已确认测试值",
        }
        for field in manifest["fields"]
        if field["required"]
    ]
    confirmed = client.post(
        f"/api/documents/{document['id']}/field-patches",
        headers=headers,
        json={
            "patch_id": f"confirm-{doc_id}",
            "base_revision": 0,
            "source": "form",
            "operations": operations,
        },
    )
    assert confirmed.status_code == 200

    ready = client.get(
        f"/api/documents/{document['id']}/download-readiness",
        headers=headers,
    )
    assert ready.status_code == 200
