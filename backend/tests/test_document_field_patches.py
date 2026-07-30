"""Tests for the server-owned FieldPatch write path."""

from __future__ import annotations


def _register(client, email: str, password: str = "secretpw1") -> str:
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert res.status_code == 201
    return res.json()["token"]


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_csa(client, headers: dict, state: dict | None = None) -> dict:
    res = client.post(
        "/api/documents",
        headers=headers,
        json={
            "doc_id": "cloud-service-agreement",
            "title": "CSA draft",
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


def test_llm_patch_creates_pending_state_without_touching_legacy_fields(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)

    res = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "llm-1",
            "base_revision": 0,
            "source": "llm",
            "message_index": 0,
            "operations": [
                {"op": "propose", "key": "客户", "value": "示例科技"},
            ],
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["duplicate"] is False
    snapshot = body["snapshot"]
    assert snapshot["revision"] == 1
    assert snapshot["fields"]["客户"]["status"] == "pending_confirmation"
    assert snapshot["fields"]["客户"]["value"] == "示例科技"
    assert snapshot["fields"]["客户"]["provenance"][0]["source"] == "llm"
    assert snapshot["fields"]["客户"]["provenance"][0]["message_index"] == 0

    fetched = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert fetched["state"]["fields"] == {}
    assert fetched["state"]["draft_state"]["revision"] == 1


def test_user_confirmation_syncs_confirmed_value_to_legacy_fields(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)

    _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "llm-1",
            "base_revision": 0,
            "source": "llm",
            "operations": [
                {"op": "propose", "key": "客户", "value": "示例科技"},
            ],
        },
    )
    res = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "user-1",
            "base_revision": 1,
            "source": "user",
            "operations": [{"op": "confirm", "key": "客户"}],
        },
    )

    assert res.status_code == 200
    field = res.json()["snapshot"]["fields"]["客户"]
    assert field["status"] == "confirmed"
    assert field["confirmed_by_user_id"] == 1

    fetched = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert fetched["state"]["fields"]["客户"] == "示例科技"


def test_new_llm_value_conflicts_with_confirmed_value_without_overwriting(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers, {"fields": {"客户": "原客户"}})

    res = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "llm-2",
            "base_revision": 0,
            "source": "llm",
            "operations": [
                {"op": "propose", "key": "客户", "value": "新客户"},
            ],
        },
    )

    assert res.status_code == 200
    field = res.json()["snapshot"]["fields"]["客户"]
    assert field["status"] == "conflict"
    assert field["value"] == "原客户"
    assert field["conflict"]["proposed_value"] == "新客户"

    fetched = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert fetched["state"]["fields"]["客户"] == "原客户"


def test_invalid_batch_patch_is_rejected_atomically(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)

    res = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "bad-1",
            "base_revision": 0,
            "source": "llm",
            "operations": [
                {"op": "propose", "key": "客户", "value": "示例科技"},
                {"op": "propose", "key": "不存在", "value": "x"},
            ],
        },
    )

    assert res.status_code == 422
    assert res.json()["detail"]["validation_errors"][0]["kind"] == "unknown_field"

    fetched = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert "draft_state" not in fetched["state"]
    assert fetched["state"] == {}


def test_revision_conflict_and_duplicate_patch_behavior(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)
    body = {
        "patch_id": "llm-1",
        "base_revision": 0,
        "source": "llm",
        "operations": [
            {"op": "propose", "key": "客户", "value": "示例科技"},
        ],
    }

    assert _patch(client, headers, doc["id"], body).status_code == 200

    duplicate = _patch(client, headers, doc["id"], body)
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["snapshot"]["revision"] == 1
    assert (
        len(duplicate.json()["snapshot"]["fields"]["客户"]["provenance"])
        == 1
    )

    stale = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "llm-2",
            "base_revision": 0,
            "source": "llm",
            "operations": [
                {"op": "propose", "key": "服务方", "value": "云服务商"},
            ],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["validation_errors"][0]["kind"] == (
        "revision_conflict"
    )


def test_same_patch_id_with_different_body_is_rejected(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)

    assert (
        _patch(
            client,
            headers,
            doc["id"],
            {
                "patch_id": "llm-1",
                "base_revision": 0,
                "source": "llm",
                "operations": [
                    {"op": "propose", "key": "客户", "value": "示例科技"},
                ],
            },
        ).status_code
        == 200
    )

    res = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "llm-1",
            "base_revision": 1,
            "source": "llm",
            "operations": [
                {"op": "propose", "key": "客户", "value": "另一家公司"},
            ],
        },
    )

    assert res.status_code == 409
    assert res.json()["detail"]["validation_errors"][0]["kind"] == (
        "patch_id_conflict"
    )


def test_clearing_confirmed_field_removes_legacy_manifest_value(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(
        client,
        headers,
        {"fields": {"客户": "原客户", "Side Letter": "保留"}},
    )

    res = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "clear-customer",
            "base_revision": 0,
            "source": "user",
            "operations": [{"op": "confirm", "key": "客户", "value": ""}],
        },
    )

    assert res.status_code == 200
    assert res.json()["snapshot"]["fields"]["客户"]["status"] == "missing"

    fetched = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert "客户" not in fetched["state"]["fields"]
    assert fetched["state"]["fields"]["Side Letter"] == "保留"


def test_field_patch_requires_document_ownership(client):
    alice = _bearer(_register(client, "alice@example.com"))
    bob = _bearer(_register(client, "bob@example.com"))
    doc = _create_csa(client, alice)

    res = _patch(
        client,
        bob,
        doc["id"],
        {
            "patch_id": "bob-1",
            "base_revision": 0,
            "source": "llm",
            "operations": [
                {"op": "propose", "key": "客户", "value": "Bob Co"},
            ],
        },
    )

    assert res.status_code == 404


def test_field_patch_rejects_docs_without_manifest_but_mnda_crud_still_works(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    created = client.post(
        "/api/documents",
        headers=headers,
        json={
            "doc_id": "mutual-nda",
            "title": "MNDA draft",
            "state": {"mnda": {"purpose": "合作评估"}},
        },
    ).json()

    patch = _patch(
        client,
        headers,
        created["id"],
        {
            "patch_id": "mnda-1",
            "base_revision": 0,
            "source": "llm",
            "operations": [
                {"op": "propose", "key": "purpose", "value": "合作评估"},
            ],
        },
    )
    assert patch.status_code == 422
    assert patch.json()["detail"]["validation_errors"][0]["kind"] == (
        "unsupported_document_schema"
    )

    update = client.put(
        f"/api/documents/{created['id']}",
        headers=headers,
        json={"state": {"mnda": {"purpose": "更新后的用途"}}},
    )
    assert update.status_code == 200
    assert update.json()["state"]["mnda"]["purpose"] == "更新后的用途"
