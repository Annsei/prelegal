"""Tests for the server-owned FieldPatch write path."""

from __future__ import annotations

import json

from app.db import get_conn
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


def _force_state_json(doc_id: int, state: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE documents SET state_json = ? WHERE id = ?",
            (json.dumps(state, ensure_ascii=False), doc_id),
        )


def _required_csa_keys() -> list[str]:
    manifest = load_manifest("cloud-service-agreement")
    assert manifest is not None
    return [
        field["key"]
        for field in manifest["fields"]
        if field.get("required") is True
    ]


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
            "source": "form",
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
    doc = _create_csa(client, headers)

    assert (
        _patch(
            client,
            headers,
            doc["id"],
            {
                "patch_id": "form-confirm-base",
                "base_revision": 0,
                "source": "form",
                "operations": [
                    {"op": "confirm", "key": "客户", "value": "原客户"},
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
            "patch_id": "llm-2",
            "base_revision": 1,
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


def test_repeated_pending_proposal_is_noop_success_without_revision(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)

    first = _patch(
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
    assert first.status_code == 200

    repeated = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "llm-repeat",
            "base_revision": 1,
            "source": "llm",
            "operations": [
                {"op": "propose", "key": "客户", "value": "示例科技"},
            ],
        },
    )

    assert repeated.status_code == 200
    snapshot = repeated.json()["snapshot"]
    assert repeated.json()["duplicate"] is False
    assert snapshot["revision"] == 1
    assert set(snapshot["applied_patches"]) == {"llm-1"}
    assert len(snapshot["fields"]["客户"]["provenance"]) == 1


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
        {"fields": {"Side Letter": "保留"}},
    )

    assert (
        _patch(
            client,
            headers,
            doc["id"],
            {
                "patch_id": "confirm-customer",
                "base_revision": 0,
                "source": "form",
                "operations": [
                    {"op": "confirm", "key": "客户", "value": "原客户"},
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
            "patch_id": "clear-customer",
            "base_revision": 1,
            "source": "form",
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


def test_public_patch_rejects_system_and_user_source_spoofing(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)

    system = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "system-spoof",
            "base_revision": 0,
            "source": "system",
            "operations": [
                {"op": "propose", "key": "客户", "value": "伪造客户"},
            ],
        },
    )
    assert system.status_code == 422
    assert system.json()["detail"]["validation_errors"][0]["kind"] == (
        "forbidden_source"
    )

    user = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "user-spoof",
            "base_revision": 0,
            "source": "user",
            "operations": [
                {"op": "confirm", "key": "客户", "value": "伪造客户"},
            ],
        },
    )
    assert user.status_code == 422
    assert user.json()["detail"]["validation_errors"][0]["kind"] == (
        "forbidden_source"
    )


def test_route_rejects_llm_reject_and_clear_without_persisting(client):
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
                    {"op": "propose", "key": "客户", "value": "候选客户"},
                ],
            },
        ).status_code
        == 200
    )

    reject = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "llm-reject",
            "base_revision": 1,
            "source": "llm",
            "operations": [{"op": "reject", "key": "客户"}],
        },
    )
    assert reject.status_code == 422
    assert reject.json()["detail"]["validation_errors"][0]["kind"] == (
        "llm_reject_forbidden"
    )

    clear = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "llm-clear",
            "base_revision": 1,
            "source": "llm",
            "operations": [{"op": "propose", "key": "客户", "value": ""}],
        },
    )
    assert clear.status_code == 422
    assert clear.json()["detail"]["validation_errors"][0]["kind"] == (
        "llm_clear_forbidden"
    )

    fetched = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert fetched["state"]["draft_state"]["revision"] == 1
    assert fetched["state"]["draft_state"]["fields"]["客户"]["status"] == (
        "pending_confirmation"
    )


def test_create_rejects_public_draft_state_injection(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)

    res = client.post(
        "/api/documents",
        headers=headers,
        json={
            "doc_id": "cloud-service-agreement",
            "title": "Injected",
            "state": {
                "draft_state": {
                    "schema_version": "draft-state.v1",
                    "doc_id": "cloud-service-agreement",
                    "revision": 99,
                    "fields": {},
                    "applied_patches": {},
                },
            },
        },
    )

    assert res.status_code == 422
    assert res.json()["detail"]["validation_errors"][0]["kind"] == (
        "draft_state_injection_forbidden"
    )


def test_stale_put_after_patch_cannot_reset_snapshot_revision(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers, {"chat": []})

    patch = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "form-confirm",
            "base_revision": 0,
            "source": "form",
            "operations": [
                {"op": "confirm", "key": "客户", "value": "示例科技"},
            ],
        },
    )
    assert patch.status_code == 200

    stale_put = client.put(
        f"/api/documents/{doc['id']}",
        headers=headers,
        json={"state": {"chat": [{"role": "user", "content": "stale"}]}},
    )
    assert stale_put.status_code == 200
    state = stale_put.json()["state"]
    assert state["chat"] == [{"role": "user", "content": "stale"}]
    assert state["draft_state"]["revision"] == 1
    assert state["fields"]["客户"] == "示例科技"


def test_put_cannot_delete_replace_or_rollback_existing_snapshot(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)

    assert (
        _patch(
            client,
            headers,
            doc["id"],
            {
                "patch_id": "form-confirm",
                "base_revision": 0,
                "source": "form",
                "operations": [
                    {"op": "confirm", "key": "客户", "value": "示例科技"},
                ],
            },
        ).status_code
        == 200
    )

    rollback = client.put(
        f"/api/documents/{doc['id']}",
        headers=headers,
        json={
            "state": {
                "fields": {"客户": "被篡改"},
                "draft_state": {
                    "schema_version": "draft-state.v1",
                    "doc_id": "cloud-service-agreement",
                    "revision": 0,
                    "fields": {},
                    "applied_patches": {},
                },
            },
        },
    )
    assert rollback.status_code == 200
    state = rollback.json()["state"]
    assert state["draft_state"]["revision"] == 1
    assert state["fields"]["客户"] == "示例科技"

    deleted = client.put(
        f"/api/documents/{doc['id']}",
        headers=headers,
        json={"state": {"fields": {}}},
    )
    assert deleted.status_code == 200
    state = deleted.json()["state"]
    assert state["draft_state"]["revision"] == 1
    assert state["fields"]["客户"] == "示例科技"


def test_non_field_autosave_does_not_drop_concurrent_patch(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers, {"chat": [{"role": "user", "content": "old"}]})

    snapshot_update = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "form-confirm",
            "base_revision": 0,
            "source": "form",
            "operations": [
                {"op": "confirm", "key": "客户", "value": "示例科技"},
            ],
        },
    )
    assert snapshot_update.status_code == 200

    stale_autosave = client.put(
        f"/api/documents/{doc['id']}",
        headers=headers,
        json={"state": {"chat": [{"role": "assistant", "content": "new"}]}},
    )
    assert stale_autosave.status_code == 200
    state = stale_autosave.json()["state"]
    assert state["chat"] == [{"role": "assistant", "content": "new"}]
    assert state["draft_state"]["revision"] == 1
    assert state["fields"]["客户"] == "示例科技"


def test_download_readiness_uses_server_unresolved_required_fields(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)

    blocked = client.get(
        f"/api/documents/{doc['id']}/download-readiness",
        headers=headers,
    )
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["validation_errors"][0]["kind"] == "download_blocked"
    assert "客户" in detail["unresolved_required_fields"]

    operations = []
    for key in _required_csa_keys():
        value = "2026-07-01" if "日期" in key else f"{key}值"
        operations.append({"op": "confirm", "key": key, "value": value})
    confirm_all = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "confirm-all-required",
            "base_revision": 0,
            "source": "form",
            "operations": operations,
        },
    )
    assert confirm_all.status_code == 200

    ready = client.get(
        f"/api/documents/{doc['id']}/download-readiness",
        headers=headers,
    )
    assert ready.status_code == 200
    assert ready.json() == {
        "can_download": True,
        "unresolved_required_fields": [],
    }


def test_same_base_revision_patches_leave_exactly_one_success(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)

    first = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "patch-a",
            "base_revision": 0,
            "source": "llm",
            "operations": [
                {"op": "propose", "key": "客户", "value": "客户 A"},
            ],
        },
    )
    second = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "patch-b",
            "base_revision": 0,
            "source": "llm",
            "operations": [
                {"op": "propose", "key": "服务方", "value": "服务方 B"},
            ],
        },
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["validation_errors"][0]["kind"] == (
        "revision_conflict"
    )
    fetched = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert fetched["state"]["draft_state"]["revision"] == 1


def test_existing_invalid_draft_state_blocks_patch_without_mutation(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)
    bad_state = {
        "fields": {"客户": "保留原文"},
        "draft_state": {
            "schema_version": "draft-state.v1",
            "doc_id": "wrong-doc",
            "revision": 7,
            "fields": {},
            "applied_patches": {},
        },
    }
    _force_state_json(doc["id"], bad_state)

    res = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "patch-after-corruption",
            "base_revision": 7,
            "source": "llm",
            "operations": [
                {"op": "propose", "key": "客户", "value": "新客户"},
            ],
        },
    )

    assert res.status_code == 409
    assert res.json()["detail"]["validation_errors"][0]["kind"] == (
        "draft_state_doc_mismatch"
    )
    fetched = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert fetched["state"] == bad_state


def test_get_migrates_legacy_fields_to_pending_without_forged_confirmation(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(
        client,
        headers,
        {"fields": {"客户": "旧客户", "Side Letter": "保留"}},
    )

    first = client.get(f"/api/documents/{doc['id']}", headers=headers)
    assert first.status_code == 200
    state = first.json()["state"]
    assert state["fields"]["客户"] == "旧客户"
    assert state["fields"]["Side Letter"] == "保留"
    snapshot = state["draft_state"]
    field = snapshot["fields"]["客户"]
    assert snapshot["revision"] == 0
    assert field["status"] == "pending_confirmation"
    assert field["value"] == "旧客户"
    assert field["confirmed_at"] is None
    assert field["confirmed_by_user_id"] is None
    assert field["provenance"] == [
        {
            "patch_id": "legacy-migration",
            "source": "system",
            "actor_user_id": None,
            "operation": "legacy_unverified",
            "value": "旧客户",
            "client_source": None,
            "message_index": None,
            "message_index_trust": "none",
            "at": None,
        },
    ]

    second = client.get(f"/api/documents/{doc['id']}", headers=headers)
    assert second.status_code == 200
    assert second.json()["state"]["draft_state"] == snapshot


def test_patch_auto_migrates_legacy_fields_before_applying_operations(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers, {"fields": {"客户": "旧客户"}})

    res = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "patch-legacy",
            "base_revision": 0,
            "source": "llm",
            "operations": [
                {"op": "propose", "key": "服务方", "value": "新服务方"},
            ],
        },
    )

    assert res.status_code == 200
    snapshot = res.json()["snapshot"]
    assert snapshot["revision"] == 1
    assert snapshot["fields"]["客户"]["status"] == "pending_confirmation"
    assert snapshot["fields"]["客户"]["value"] == "旧客户"
    assert snapshot["fields"]["客户"]["provenance"][0]["operation"] == (
        "legacy_unverified"
    )
    assert snapshot["fields"]["服务方"]["status"] == "pending_confirmation"
    fetched = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert fetched["state"]["fields"]["客户"] == "旧客户"
    assert fetched["state"]["draft_state"]["revision"] == 1


def test_snapshot_with_missing_manifest_version_is_migrated_not_reset(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)

    assert (
        _patch(
            client,
            headers,
            doc["id"],
            {
                "patch_id": "form-confirm",
                "base_revision": 0,
                "source": "form",
                "operations": [
                    {"op": "confirm", "key": "客户", "value": "示例科技"},
                ],
            },
        ).status_code
        == 200
    )
    state = client.get(f"/api/documents/{doc['id']}", headers=headers).json()[
        "state"
    ]
    state["draft_state"]["manifest_version"] = None
    _force_state_json(doc["id"], state)

    migrated = client.get(f"/api/documents/{doc['id']}", headers=headers)

    assert migrated.status_code == 200
    snapshot = migrated.json()["state"]["draft_state"]
    assert snapshot["manifest_version"] == 2
    assert snapshot["revision"] == 1
    assert snapshot["fields"]["客户"]["status"] == "confirmed"


def test_patch_rejects_single_large_field_when_final_state_exceeds_limit(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)

    res = _patch(
        client,
        headers,
        doc["id"],
        {
            "patch_id": "large-field",
            "base_revision": 0,
            "source": "form",
            "operations": [
                {"op": "confirm", "key": "技术支持", "value": "x" * (520 * 1024)},
            ],
        },
    )

    assert res.status_code == 422
    assert res.json()["detail"]["validation_errors"][0]["kind"] == (
        "state_too_large"
    )
    fetched = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert "draft_state" not in fetched["state"]


def test_patch_rejects_accumulated_snapshot_over_size_limit_atomically(client):
    token = _register(client, "alice@example.com")
    headers = _bearer(token)
    doc = _create_csa(client, headers)
    last_revision = 0
    rejected = None

    for index in range(40):
        res = _patch(
            client,
            headers,
            doc["id"],
            {
                "patch_id": f"accumulate-{index}",
                "base_revision": last_revision,
                "source": "form",
                "operations": [
                    {
                        "op": "confirm",
                        "key": "技术支持",
                        "value": f"{index}-" + ("x" * (18 * 1024)),
                    },
                ],
            },
        )
        if res.status_code == 422:
            rejected = res
            break
        assert res.status_code == 200
        last_revision = res.json()["snapshot"]["revision"]

    assert rejected is not None
    assert rejected.json()["detail"]["validation_errors"][0]["kind"] == (
        "state_too_large"
    )
    fetched = client.get(f"/api/documents/{doc['id']}", headers=headers).json()
    assert fetched["state"]["draft_state"]["revision"] == last_revision
