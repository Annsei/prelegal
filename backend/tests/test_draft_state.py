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


def _confirmed_snapshot(value: str = "示例科技") -> DraftStateSnapshot:
    snapshot = snapshot_from_document_state(
        doc_id="example-doc",
        state={},
        manifest=MANIFEST,
    )
    pending = apply_field_patch(
        snapshot=snapshot,
        patch=_patch(
            "llm-seed",
            0,
            "llm",
            [{"op": "propose", "key": "客户", "value": value}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot
    return apply_field_patch(
        snapshot=pending,
        patch=_patch(
            "form-confirm-seed",
            1,
            "form",
            [{"op": "confirm", "key": "客户"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot


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
    snapshot = _confirmed_snapshot("原客户")

    result = apply_field_patch(
        snapshot=snapshot,
        patch=_patch(
            "llm-2",
            2,
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


def test_same_proposal_against_confirmed_value_keeps_confirmed_state():
    snapshot = _confirmed_snapshot("原客户")

    result = apply_field_patch(
        snapshot=snapshot,
        patch=_patch(
            "llm-same",
            2,
            "llm",
            [{"op": "propose", "key": "客户", "value": "原客户"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    )

    field = result.snapshot.fields["客户"]
    assert result.snapshot.revision == 3
    assert field.status == "confirmed"
    assert field.value == "原客户"
    assert field.confirmed_at is not None
    assert field.confirmed_by_user_id == 7


def test_blank_proposal_against_confirmed_value_is_rejected_without_mutation():
    snapshot = _confirmed_snapshot("原客户")
    before = snapshot.model_dump(mode="json")

    with pytest.raises(DraftPatchRejected) as info:
        apply_field_patch(
            snapshot=snapshot,
            patch=_patch(
                "llm-clear",
                2,
                "llm",
                [{"op": "propose", "key": "客户", "value": "   "}],
            ),
            manifest=MANIFEST,
            actor_user_id=7,
        )

    assert info.value.status_code == 422
    assert info.value.errors[0].kind == "llm_clear_forbidden"
    assert snapshot.model_dump(mode="json") == before


def test_conflict_candidate_can_update_without_losing_confirmed_base():
    snapshot = _confirmed_snapshot("原客户")
    conflict = apply_field_patch(
        snapshot=snapshot,
        patch=_patch(
            "llm-conflict-1",
            2,
            "llm",
            [{"op": "propose", "key": "客户", "value": "候选 B"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot

    updated = apply_field_patch(
        snapshot=conflict,
        patch=_patch(
            "llm-conflict-2",
            3,
            "llm",
            [{"op": "propose", "key": "客户", "value": "候选 C"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot

    field = updated.fields["客户"]
    assert field.status == "conflict"
    assert field.value == "原客户"
    assert field.conflict is not None
    assert field.conflict.base_value == "原客户"
    assert field.conflict.proposed_value == "候选 C"


def test_reject_pending_candidate_returns_to_missing_and_clears_candidate():
    snapshot = snapshot_from_document_state(
        doc_id="example-doc",
        state={},
        manifest=MANIFEST,
    )
    pending = apply_field_patch(
        snapshot=snapshot,
        patch=_patch(
            "llm-pending",
            0,
            "llm",
            [{"op": "propose", "key": "客户", "value": "候选客户"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot

    rejected = apply_field_patch(
        snapshot=pending,
        patch=_patch(
            "form-reject-pending",
            1,
            "form",
            [{"op": "reject", "key": "客户"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot

    field = rejected.fields["客户"]
    assert rejected.revision == 2
    assert field.status == "missing"
    assert field.value is None
    assert field.confirmed_at is None
    assert field.confirmed_by_user_id is None


def test_reject_confirmed_conflict_restores_base_and_preserves_audit_trail():
    snapshot = _confirmed_snapshot("原客户")
    conflict = apply_field_patch(
        snapshot=snapshot,
        patch=_patch(
            "llm-conflict",
            2,
            "llm",
            [{"op": "propose", "key": "客户", "value": "候选客户"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot

    rejected = apply_field_patch(
        snapshot=conflict,
        patch=_patch(
            "form-reject-conflict",
            3,
            "form",
            [{"op": "reject", "key": "客户"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot

    field = rejected.fields["客户"]
    assert field.status == "confirmed"
    assert field.value == "原客户"
    assert field.conflict is None
    assert field.confirmed_by_user_id == 7
    assert [(p.operation, p.value) for p in field.provenance[-2:]] == [
        ("propose", "候选客户"),
        ("reject", "候选客户"),
    ]


def test_llm_reject_and_clear_operations_are_forbidden():
    snapshot = snapshot_from_document_state(
        doc_id="example-doc",
        state={},
        manifest=MANIFEST,
    )
    pending = apply_field_patch(
        snapshot=snapshot,
        patch=_patch(
            "llm-pending",
            0,
            "llm",
            [{"op": "propose", "key": "客户", "value": "候选客户"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot

    with pytest.raises(DraftPatchRejected) as reject_info:
        apply_field_patch(
            snapshot=pending,
            patch=_patch(
                "llm-reject",
                1,
                "llm",
                [{"op": "reject", "key": "客户"}],
            ),
            manifest=MANIFEST,
            actor_user_id=7,
        )
    assert reject_info.value.errors[0].kind == "llm_reject_forbidden"

    with pytest.raises(DraftPatchRejected) as clear_info:
        apply_field_patch(
            snapshot=pending,
            patch=_patch(
                "llm-clear",
                1,
                "llm",
                [{"op": "propose", "key": "客户", "value": ""}],
            ),
            manifest=MANIFEST,
            actor_user_id=7,
        )
    assert clear_info.value.errors[0].kind == "llm_clear_forbidden"


def test_invalid_noop_transitions_do_not_increment_revision():
    snapshot = snapshot_from_document_state(
        doc_id="example-doc",
        state={},
        manifest=MANIFEST,
    )

    with pytest.raises(DraftPatchRejected) as reject_info:
        apply_field_patch(
            snapshot=snapshot,
            patch=_patch(
                "form-reject-missing",
                0,
                "form",
                [{"op": "reject", "key": "客户"}],
            ),
            manifest=MANIFEST,
            actor_user_id=7,
        )
    assert reject_info.value.errors[0].kind == "invalid_transition"
    assert snapshot.revision == 0

    with pytest.raises(DraftPatchRejected) as confirm_info:
        apply_field_patch(
            snapshot=snapshot,
            patch=_patch(
                "form-confirm-missing",
                0,
                "form",
                [{"op": "confirm", "key": "客户"}],
            ),
            manifest=MANIFEST,
            actor_user_id=7,
        )
    assert confirm_info.value.errors[0].kind == "invalid_transition"
    assert snapshot.revision == 0


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


def test_required_when_uses_confirmed_base_while_field_is_in_conflict():
    snapshot = snapshot_from_document_state(
        doc_id="example-doc",
        state={},
        manifest=MANIFEST,
    )
    confirmed = apply_field_patch(
        snapshot=snapshot,
        patch=_patch(
            "confirm-renewal",
            0,
            "form",
            [{"op": "confirm", "key": "是否自动续期", "value": "是"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot
    conflicted = apply_field_patch(
        snapshot=confirmed,
        patch=_patch(
            "llm-conflict-renewal",
            1,
            "llm",
            [{"op": "propose", "key": "是否自动续期", "value": "否"}],
        ),
        manifest=MANIFEST,
        actor_user_id=7,
    ).snapshot

    assert conflicted.fields["是否自动续期"].status == "conflict"
    assert required_field_keys(MANIFEST, conflicted) == [
        "客户",
        "订单日期",
        "不续约通知期",
    ]
    assert unresolved_required_field_keys(MANIFEST, conflicted) == [
        "客户",
        "订单日期",
        "不续约通知期",
    ]


def test_legacy_fields_require_explicit_migration_not_confirmed_bootstrap():
    with pytest.raises(DraftPatchRejected) as info:
        snapshot_from_document_state(
            doc_id="example-doc",
            state={"fields": {"客户": "旧客户"}},
            manifest=MANIFEST,
        )

    assert info.value.status_code == 409
    assert info.value.errors[0].kind == "migration_required"


def test_invalid_existing_snapshot_is_rejected_instead_of_bootstrapped():
    with pytest.raises(DraftPatchRejected) as info:
        snapshot_from_document_state(
            doc_id="example-doc",
            state={"draft_state": {"schema_version": "draft-state.v1"}},
            manifest=MANIFEST,
        )

    assert info.value.status_code == 409
    assert info.value.errors[0].kind == "invalid_draft_state"


def test_future_snapshot_schema_is_rejected_instead_of_resetting_revision():
    with pytest.raises(DraftPatchRejected) as info:
        snapshot_from_document_state(
            doc_id="example-doc",
            state={
                "draft_state": {
                    "schema_version": "draft-state.v99",
                    "doc_id": "example-doc",
                    "revision": 99,
                    "fields": {},
                    "applied_patches": {},
                },
            },
            manifest=MANIFEST,
        )

    assert info.value.status_code == 409
    assert info.value.errors[0].kind == "unsupported_draft_state_schema"


def test_manifest_version_mismatch_blocks_silent_field_deletion():
    with pytest.raises(DraftPatchRejected) as info:
        snapshot_from_document_state(
            doc_id="example-doc",
            state={
                "draft_state": {
                    "schema_version": "draft-state.v1",
                    "manifest_version": 1,
                    "doc_id": "example-doc",
                    "revision": 4,
                    "fields": {
                        "旧字段": {
                            "key": "旧字段",
                            "status": "confirmed",
                            "value": "旧值",
                            "revision": 4,
                        },
                    },
                    "applied_patches": {},
                },
            },
            manifest={**MANIFEST, "version": 2},
        )

    assert info.value.status_code == 409
    assert info.value.errors[0].kind == "manifest_version_mismatch"
