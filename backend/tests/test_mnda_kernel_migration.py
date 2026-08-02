"""Tests for migrating legacy MNDA drafts onto the document-state kernel."""

from __future__ import annotations

import json

from app.db import get_conn
from app.draft_state import legacy_mnda_to_manifest_fields
from app.manifests import load_manifest


def _register(client, email: str, password: str = "secretpw1") -> str:
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert res.status_code == 201
    return res.json()["token"]


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_mnda(client, headers: dict, state: dict | None = None) -> dict:
    res = client.post(
        "/api/documents",
        headers=headers,
        json={
            "doc_id": "mutual-nda",
            "title": "MNDA draft",
            "state": state or {},
        },
    )
    assert res.status_code == 201
    return res.json()


def _patch(client, headers: dict, doc_id: int, body: dict):
    return client.post(
        f"/api/documents/{doc_id}/field-patches",
        headers=headers,
        json=body,
    )


def test_legacy_mnda_to_manifest_fields_maps_typed_state_to_strings():
    values = legacy_mnda_to_manifest_fields(
        {
            "purpose": "评估融资合作",
            "effectiveDate": "2026-08-01",
            "mndaTermMode": "expires",
            "mndaTermYears": 2,
            "confidentialityMode": "perpetual",
            "confidentialityYears": 3,
            "governingLaw": "中华人民共和国法律",
            "jurisdiction": "上海仲裁委员会按其仲裁规则进行仲裁",
            "modifications": "",
            "party1": {
                "company": "甲方科技有限公司",
                "signerName": "张三",
                "signerTitle": "法定代表人",
                "noticeAddress": "legal-a@example.cn",
            },
            "party2": {
                "company": "乙方科技有限公司",
                "signerName": "李四",
                "signerTitle": "总经理",
                "noticeAddress": "legal-b@example.cn",
            },
        },
    )

    assert values == {
        "保密用途": "评估融资合作",
        "生效日期": "2026-08-01",
        "协议期限": "自生效日期起 2 年",
        "保密期限": "永久",
        "适用法律": "中华人民共和国法律",
        "争议解决": "上海仲裁委员会按其仲裁规则进行仲裁",
        "甲方公司名称": "甲方科技有限公司",
        "甲方签字人姓名": "张三",
        "甲方签字人职务": "法定代表人",
        "甲方通知地址": "legal-a@example.cn",
        "乙方公司名称": "乙方科技有限公司",
        "乙方签字人姓名": "李四",
        "乙方签字人职务": "总经理",
        "乙方通知地址": "legal-b@example.cn",
    }


def test_legacy_mnda_continuing_and_years_terms_are_normalized():
    values = legacy_mnda_to_manifest_fields(
        {
            "mndaTermMode": "continues",
            "mndaTermYears": 1,
            "confidentialityMode": "years",
            "confidentialityYears": 5,
        },
    )

    assert values["协议期限"] == "持续有效，直至依约终止"
    assert values["保密期限"] == "自生效日期起 5 年"


def test_get_migrates_legacy_mnda_state_to_pending_kernel_fields(client):
    token = _register(client, "mnda-migrate@example.com")
    headers = _bearer(token)
    legacy_state = {
        "chat": [{"role": "user", "content": "甲方是甲方科技。"}],
        "mnda": {
            "purpose": "评估融资合作",
            "effectiveDate": "2026-08-01",
            "mndaTermMode": "expires",
            "mndaTermYears": 2,
            "confidentialityMode": "years",
            "confidentialityYears": 5,
            "governingLaw": "中华人民共和国法律",
            "jurisdiction": "上海仲裁委员会按其仲裁规则进行仲裁",
            "party1": {"company": "甲方科技有限公司"},
            "party2": {"company": "乙方科技有限公司"},
        },
    }
    doc = _create_mnda(client, headers, legacy_state)

    migrated = client.get(f"/api/documents/{doc['id']}", headers=headers)

    assert migrated.status_code == 200
    state = migrated.json()["state"]
    assert "mnda" not in state
    assert state["fields"]["保密用途"] == "评估融资合作"
    assert state["fields"]["协议期限"] == "自生效日期起 2 年"
    assert state["fields"]["甲方公司名称"] == "甲方科技有限公司"
    snapshot = state["draft_state"]
    assert snapshot["doc_id"] == "mutual-nda"
    assert snapshot["revision"] == 0
    field = snapshot["fields"]["保密用途"]
    assert field["status"] == "pending_confirmation"
    assert field["confirmed_at"] is None
    assert field["confirmed_by_user_id"] is None
    assert field["provenance"][0]["operation"] == "legacy_unverified"

    second_get = client.get(f"/api/documents/{doc['id']}", headers=headers)
    assert second_get.status_code == 200
    second_state = second_get.json()["state"]
    assert "mnda" not in second_state
    assert second_state["draft_state"]["revision"] == 0
    assert second_state["fields"]["保密用途"] == "评估融资合作"


def test_public_put_cannot_revive_legacy_mnda_after_kernel_migration(client):
    token = _register(client, "mnda-put-revive@example.com")
    headers = _bearer(token)
    legacy_mnda = {
        "purpose": "评估融资合作",
        "effectiveDate": "2026-08-01",
        "mndaTermMode": "expires",
        "mndaTermYears": 2,
        "confidentialityMode": "years",
        "confidentialityYears": 5,
        "governingLaw": "中华人民共和国法律",
        "jurisdiction": "上海仲裁委员会按其仲裁规则进行仲裁",
        "party1": {"company": "甲方科技有限公司"},
        "party2": {"company": "乙方科技有限公司"},
    }
    doc = _create_mnda(client, headers, {"mnda": legacy_mnda})
    migrated = client.get(f"/api/documents/{doc['id']}", headers=headers)
    assert migrated.status_code == 200
    assert "mnda" not in migrated.json()["state"]

    autosave = client.put(
        f"/api/documents/{doc['id']}",
        headers=headers,
        json={
            "state": {
                "chat": [{"role": "user", "content": "legacy client autosave"}],
                "mnda": {
                    **legacy_mnda,
                    "purpose": "旧客户端试图写回",
                },
                "fields": {},
            },
        },
    )

    assert autosave.status_code == 200
    state = autosave.json()["state"]
    assert "mnda" not in state
    assert state["chat"] == [
        {"role": "user", "content": "legacy client autosave"},
    ]
    assert state["draft_state"]["revision"] == 0
    assert state["fields"]["保密用途"] == "评估融资合作"


def test_get_cleans_dead_mnda_from_already_migrated_kernel_state(client):
    token = _register(client, "mnda-clean-dead@example.com")
    headers = _bearer(token)
    doc = _create_mnda(client, headers)

    patched = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "llm-mnda-purpose",
            "base_revision": 0,
            "source": "llm",
            "message_index": 0,
            "operations": [
                {"op": "propose", "key": "保密用途", "value": "评估融资合作"},
            ],
        },
    )
    assert patched.status_code == 200
    state_with_dead_mnda = client.get(
        f"/api/documents/{doc['id']}",
        headers=headers,
    ).json()["state"]
    state_with_dead_mnda["mnda"] = {"purpose": "旧 typed 状态"}
    with get_conn() as conn:
        conn.execute(
            "UPDATE documents SET state_json = ? WHERE id = ?",
            (json.dumps(state_with_dead_mnda, ensure_ascii=False), doc["id"]),
        )

    cleaned = client.get(f"/api/documents/{doc['id']}", headers=headers)

    assert cleaned.status_code == 200
    state = cleaned.json()["state"]
    assert "mnda" not in state
    assert state["draft_state"]["revision"] == 1
    assert state["draft_state"]["fields"]["保密用途"]["status"] == (
        "pending_confirmation"
    )

    second_get = client.get(f"/api/documents/{doc['id']}", headers=headers)
    assert second_get.status_code == 200
    assert "mnda" not in second_get.json()["state"]


def test_mnda_download_readiness_uses_kernel_required_fields(client):
    token = _register(client, "mnda-download@example.com")
    headers = _bearer(token)
    doc = _create_mnda(client, headers)

    blocked = client.get(
        f"/api/documents/{doc['id']}/download-readiness",
        headers=headers,
    )
    assert blocked.status_code == 409
    assert "保密用途" in blocked.json()["detail"]["unresolved_required_fields"]

    manifest = load_manifest("mutual-nda")
    assert manifest is not None
    operations = []
    for field in manifest["fields"]:
        if field.get("required") is not True:
            continue
        key = field["key"]
        value = "2026-08-01" if field.get("type") == "date" else f"{key}值"
        operations.append({"op": "confirm", "key": key, "value": value})

    confirmed = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "confirm-mnda-required",
            "base_revision": 0,
            "source": "form",
            "operations": operations,
        },
    )
    assert confirmed.status_code == 200

    ready = client.get(
        f"/api/documents/{doc['id']}/download-readiness",
        headers=headers,
    )
    assert ready.status_code == 200
    assert ready.json() == {
        "can_download": True,
        "unresolved_required_fields": [],
    }
