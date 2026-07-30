from __future__ import annotations

import pytest

from app.draft_state import (
    DraftPatchRejected,
    DraftStateSnapshot,
    FieldPatchOperation,
    FieldPatchRequest,
    apply_field_patch,
    required_field_keys,
    snapshot_from_document_state,
    unresolved_required_field_keys,
)

MANIFEST = {
    "doc_id": "example-doc",
    "fields": [
        {"key": "客户", "type": "string", "required": True},
        {"key": "订单日期", "type": "date", "required": True},
        {
            "key": "是否自动续期",
            "type": "string",
            "required": False,
            "enum": ["是", "否"],
        },
        {
            "key": "不续约通知期",
            "type": "string",
            "required": False,
            "required_when": {"field": "是否自动续期", "op": "equals", "value": "是"},
        },
    ],
}


def _patch(
    patch_id: str,
    base_revision: int,
    source: str,
    operations: list[dict],
) -> FieldPatchRequest:
    return FieldPatchRequest(
        patch_id=patch_id,
        base_revision=base_revision,
        source=source,
        operations=[FieldPatchOperation(**op) for op in operations],
    )


def test_llm_proposal_cannot_skip_user_confirmation():
    snapshot = snapshot_from_document_state(
        doc_id="example-doc",
        state={},
        manifest=MANIFEST,
    )

    result = apply_field_patch(
        snapshot=snapshot,
        patch=_patch(
            "llm-1",
            0,
            "llm",
            [{"op": "propose", "key": "客户", "value": "示例科技"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
        now="2026-07-29T00:00:00+00:00",
    )

    field = result.snapshot.fields["客户"]
    assert result.snapshot.revision == 1
    assert field.status == "pending_confirmation"
    assert field.value == "示例科技"
    assert field.confirmed_at is None


def test_user_confirmation_promotes_pending_field_to_confirmed():
    snapshot = snapshot_from_document_state(
        doc_id="example-doc",
        state={},
        manifest=MANIFEST,
    )
    pending = apply_field_patch(
        snapshot=snapshot,
        patch=_patch(
            "llm-1",
            0,
            "llm",
            [{"op": "propose", "key": "客户", "value": "示例科技"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
        now="2026-07-29T00:00:00+00:00",
    ).snapshot

    confirmed = apply_field_patch(
        snapshot=pending,
        patch=_patch(
            "user-1",
            1,
            "user",
            [{"op": "confirm", "key": "客户"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
        now="2026-07-29T00:01:00+00:00",
    ).snapshot

    field = confirmed.fields["客户"]
    assert confirmed.revision == 2
    assert field.status == "confirmed"
    assert field.value == "示例科技"
    assert field.confirmed_by_user_id == 7
    assert field.confirmed_at == "2026-07-29T00:01:00+00:00"


def test_llm_confirm_operation_is_rejected():
    snapshot = snapshot_from_document_state(
        doc_id="example-doc",
        state={},
        manifest=MANIFEST,
    )

    with pytest.raises(DraftPatchRejected) as info:
        apply_field_patch(
            snapshot=snapshot,
            patch=_patch(
                "llm-confirm",
                0,
                "llm",
                [{"op": "confirm", "key": "客户", "value": "示例科技"}],
            ),
            manifest=MANIFEST,
            actor_user_id=7,
        )

    assert info.value.status_code == 422
    assert [err.kind for err in info.value.errors] == ["llm_confirm_forbidden"]


def test_new_proposal_against_confirmed_value_records_conflict():
    snapshot = snapshot_from_document_state(
        doc_id="example-doc",
        state={"fields": {"客户": "原客户"}},
        manifest=MANIFEST,
    )

    result = apply_field_patch(
        snapshot=snapshot,
        patch=_patch(
            "llm-2",
            0,
            "llm",
            [{"op": "propose", "key": "客户", "value": "新客户"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
        now="2026-07-29T00:02:00+00:00",
    )

    field = result.snapshot.fields["客户"]
    assert field.status == "conflict"
    assert field.value == "原客户"
    assert field.conflict is not None
    assert field.conflict.proposed_value == "新客户"


def test_invalid_values_are_structured_validation_errors():
    snapshot = snapshot_from_document_state(
        doc_id="example-doc",
        state={},
        manifest=MANIFEST,
    )

    with pytest.raises(DraftPatchRejected) as info:
        apply_field_patch(
            snapshot=snapshot,
            patch=_patch(
                "bad-values",
                0,
                "llm",
                [
                    {"op": "propose", "key": "未知字段", "value": "x"},
                    {"op": "propose", "key": "订单日期", "value": "2026/07/29"},
                    {"op": "propose", "key": "是否自动续期", "value": "maybe"},
                ],
            ),
            manifest=MANIFEST,
            actor_user_id=7,
        )

    assert info.value.status_code == 422
    assert [err.kind for err in info.value.errors] == [
        "unknown_field",
        "invalid_date",
        "invalid_enum",
    ]


def test_revision_conflicts_and_duplicate_patches_are_explicit():
    snapshot = snapshot_from_document_state(
        doc_id="example-doc",
        state={},
        manifest=MANIFEST,
    )
    first_patch = _patch(
        "llm-1",
        0,
        "llm",
        [{"op": "propose", "key": "客户", "value": "示例科技"}],
    )
    first = apply_field_patch(
        snapshot=snapshot,
        patch=first_patch,
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot

    duplicate = apply_field_patch(
        snapshot=first,
        patch=first_patch,
        manifest=MANIFEST,
        actor_user_id=7,
    )
    assert duplicate.duplicate is True
    assert duplicate.snapshot.revision == 1
    assert len(duplicate.snapshot.fields["客户"].provenance) == 1

    with pytest.raises(DraftPatchRejected) as info:
        apply_field_patch(
            snapshot=first,
            patch=_patch(
                "llm-2",
                0,
                "llm",
                [{"op": "propose", "key": "订单日期", "value": "2026-07-29"}],
            ),
            manifest=MANIFEST,
            actor_user_id=7,
        )
    assert info.value.status_code == 409
    assert info.value.errors[0].kind == "revision_conflict"


def test_reusing_patch_id_with_different_operations_is_rejected():
    snapshot = snapshot_from_document_state(
        doc_id="example-doc",
        state={},
        manifest=MANIFEST,
    )
    first = apply_field_patch(
        snapshot=snapshot,
        patch=_patch(
            "patch-1",
            0,
            "llm",
            [{"op": "propose", "key": "客户", "value": "示例科技"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot

    with pytest.raises(DraftPatchRejected) as info:
        apply_field_patch(
            snapshot=first,
            patch=_patch(
                "patch-1",
                1,
                "llm",
                [{"op": "propose", "key": "客户", "value": "另一家公司"}],
            ),
            manifest=MANIFEST,
            actor_user_id=7,
        )

    assert info.value.status_code == 409
    assert info.value.errors[0].kind == "patch_id_conflict"


def test_old_applied_patch_records_are_upgraded_when_snapshot_loads():
    snapshot = DraftStateSnapshot.model_validate(
        {
            "schema_version": "draft-state.v1",
            "doc_id": "example-doc",
            "revision": 1,
            "fields": {},
            "applied_patches": {"old": 1},
        },
    )

    assert snapshot.applied_patches["old"].revision == 1
    assert snapshot.applied_patches["old"].fingerprint == ""


def test_required_fields_use_declarative_conditions_only():
    snapshot = snapshot_from_document_state(
        doc_id="example-doc",
        state={},
        manifest=MANIFEST,
    )
    assert required_field_keys(MANIFEST, snapshot) == ["客户", "订单日期"]

    renewed = apply_field_patch(
        snapshot=snapshot,
        patch=_patch(
            "confirm-renewal",
            0,
            "user",
            [{"op": "confirm", "key": "是否自动续期", "value": "是"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot

    assert required_field_keys(MANIFEST, renewed) == [
        "客户",
        "订单日期",
        "不续约通知期",
    ]
    assert unresolved_required_field_keys(MANIFEST, renewed) == [
        "客户",
        "订单日期",
        "不续约通知期",
    ]
