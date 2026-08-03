"""Manifest-pipeline coverage for Prelegal v1.0 product baselines."""

from __future__ import annotations

import re

import pytest

from app.manifests import load_manifest, manifest_field_keys

PRELEGAL_MANIFEST_DOCUMENTS = {
    "service-level-agreement": {
        "title": "服务等级协议（SLA）",
        "required_keys": {"服务方", "客户", "可用率目标", "服务积分上限"},
        "body_marker": "服务可用性承诺",
        "field_count": 14,
        "required_count": 12,
        "conditional_count": 0,
    },
    "software-license-agreement": {
        "title": "软件许可协议",
        "required_keys": {"许可方", "被许可方", "许可范围", "许可费"},
        "body_marker": "许可范围与限制",
        "field_count": 18,
        "required_count": 18,
        "conditional_count": 0,
    },
    "pilot-agreement": {
        "title": "试点协议",
        "required_keys": {"服务方", "客户", "试点期限", "试点成功标准"},
        "body_marker": "试点内容与范围",
        "field_count": 14,
        "required_count": 11,
        "conditional_count": 2,
    },
    "design-partner-agreement": {
        "title": "设计合作伙伴协议",
        "required_keys": {"甲方", "乙方", "产品", "试用授权范围"},
        "body_marker": "合作内容",
        "field_count": 13,
        "required_count": 13,
        "conditional_count": 0,
    },
    "partnership-agreement": {
        "title": "渠道合作协议",
        "required_keys": {"供应商", "合作方", "合作产品", "合作模式"},
        "body_marker": "合作模式与授权范围",
        "field_count": 16,
        "required_count": 14,
        "conditional_count": 0,
    },
    "business-associate-agreement": {
        "title": "医疗健康数据合作协议",
        "required_keys": {"医疗机构", "技术服务方", "处理目的", "安全措施"},
        "body_marker": "合作范围与委托处理",
        "field_count": 16,
        "required_count": 16,
        "conditional_count": 0,
    },
    "ai-addendum": {
        "title": "人工智能服务附加条款",
        "required_keys": {"客户", "服务方", "主协议", "服务内容"},
        "body_marker": "训练数据使用限制",
        "field_count": 10,
        "required_count": 9,
        "conditional_count": 0,
    },
}

_TERM_REF_PATTERN = re.compile(
    r'<span class="(?:coverpage_link|orderform_link|keyterms_link)">([^<]+)</span>'
)


def _register(client, email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "secretpw1"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.mark.parametrize("doc_id", PRELEGAL_MANIFEST_DOCUMENTS)
def test_prelegal_template_loads_cover_page_and_manifest_with_declared_term_refs(
    client,
    doc_id: str,
):
    expected = PRELEGAL_MANIFEST_DOCUMENTS[doc_id]

    response = client.get(f"/api/templates/{doc_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == expected["title"]
    assert body["cover_page"] is not None
    assert expected["body_marker"] in body["standard_terms"]
    manifest = body["manifest"]
    assert manifest is not None
    assert manifest["doc_id"] == doc_id
    assert expected["required_keys"] <= set(manifest_field_keys(manifest))
    assert load_manifest(doc_id) == manifest
    assert len(manifest["fields"]) == expected["field_count"]
    assert sum(field["required"] for field in manifest["fields"]) == expected[
        "required_count"
    ]
    assert sum("required_when" in field for field in manifest["fields"]) == expected[
        "conditional_count"
    ]

    referenced_keys = set(
        _TERM_REF_PATTERN.findall(body["cover_page"] + body["standard_terms"])
    )
    assert referenced_keys <= set(manifest_field_keys(manifest))


@pytest.mark.parametrize("doc_id", PRELEGAL_MANIFEST_DOCUMENTS)
def test_prelegal_template_required_fields_gate_download_until_confirmed(
    client,
    doc_id: str,
):
    headers = _register(client, f"{doc_id}@example.com")
    created = client.post(
        "/api/documents",
        headers=headers,
        json={"doc_id": doc_id, "title": "batch template", "state": {}},
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


def test_paid_pilot_requires_fee_and_payment_arrangement_before_download(client):
    headers = _register(client, "paid-pilot@example.com")
    created = client.post(
        "/api/documents",
        headers=headers,
        json={"doc_id": "pilot-agreement", "title": "paid pilot", "state": {}},
    )
    assert created.status_code == 201
    document = created.json()

    manifest = load_manifest("pilot-agreement")
    assert manifest is not None
    static_operations = [
        {
            "op": "confirm",
            "key": field["key"],
            "value": (
                "2026-08-01"
                if field["type"] == "date"
                else "付费"
                if field["key"] == "试点收费方式"
                else "已确认测试值"
            ),
        }
        for field in manifest["fields"]
        if field["required"]
    ]
    confirmed = client.post(
        f"/api/documents/{document['id']}/field-patches",
        headers=headers,
        json={
            "patch_id": "confirm-paid-pilot-static-fields",
            "base_revision": 0,
            "source": "form",
            "operations": static_operations,
        },
    )
    assert confirmed.status_code == 200

    blocked = client.get(
        f"/api/documents/{document['id']}/download-readiness",
        headers=headers,
    )
    assert blocked.status_code == 409
    assert set(blocked.json()["detail"]["unresolved_required_fields"]) == {
        "试点费用",
        "付款安排",
    }

    conditional = client.post(
        f"/api/documents/{document['id']}/field-patches",
        headers=headers,
        json={
            "patch_id": "confirm-paid-pilot-commercial-fields",
            "base_revision": 1,
            "source": "form",
            "operations": [
                {"op": "confirm", "key": "试点费用", "value": "人民币30,000元"},
                {
                    "op": "confirm",
                    "key": "付款安排",
                    "value": "签署后10日内支付",
                },
            ],
        },
    )
    assert conditional.status_code == 200

    ready = client.get(
        f"/api/documents/{document['id']}/download-readiness",
        headers=headers,
    )
    assert ready.status_code == 200
