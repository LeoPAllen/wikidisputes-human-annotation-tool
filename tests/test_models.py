import pytest

from wikidisputes_ui.models import (
    ANNOTATION_FIELDS,
    CURRENT_UTTERANCE_SCHEMA_FIELDS,
    KI_FIELDS,
    KS_FIELDS,
    applicable_fields,
    derived_ki_present,
    is_current_dispute_decision,
    is_current_submitted_utterance,
    is_structurally_compatible_utterance,
    normalize_and_validate,
)


def base(**changes):
    values = {
        "KS_present": 0,
        "KI_coordinating_edits": 0,
        "KI_compromise": 0,
        "C_off_topic_shift": 0,
        "C_interpersonal_attack_or_disrespect": 0,
        "C_formal_governance_action": 0,
        "coder_confidence": 3,
        "review_flag": 0,
        "coder_notes": None,
    }
    values.update(changes)
    return values


def test_ks_and_ki_are_independent_and_can_cooccur():
    values = base(KS_present=1, KI_coordinating_edits=1, KI_compromise=1, **{name: 0 for name in KS_FIELDS})
    result = normalize_and_validate(values, set(values))
    assert result.valid
    assert set(KS_FIELDS) - {"KS_new_evidence"} <= applicable_fields(values)
    assert "KS_new_evidence" not in applicable_fields(values)
    assert KI_FIELDS == ("KI_coordinating_edits", "KI_compromise")


@pytest.mark.parametrize(
    ("coordinating_edits", "compromise", "expected_ki"),
    [(0, 0, False), (1, 0, True), (0, 1, True), (1, 1, True)],
)
def test_ki_fields_are_independent_binary_dimensions(coordinating_edits, compromise, expected_ki):
    values = base(
        KS_present=0,
        KI_coordinating_edits=coordinating_edits,
        KI_compromise=compromise,
    )
    result = normalize_and_validate(values, set(values))
    assert result.valid
    assert result.payload["KI_coordinating_edits"] == coordinating_edits
    assert result.payload["KI_compromise"] == compromise
    assert derived_ki_present(result.payload) is expected_ki


@pytest.mark.parametrize("field", KI_FIELDS)
def test_both_ki_fields_are_required_for_normal_utterances(field):
    values = base()
    answered = set(values) - {field}
    result = normalize_and_validate(values, answered)
    assert result.errors[field] == "An explicit response is required."


def test_legacy_ki_present_only_payload_is_structurally_stale():
    legacy_payload = {name: None for name in CURRENT_UTTERANCE_SCHEMA_FIELDS if name not in KI_FIELDS}
    legacy_payload["KI_present"] = 1
    assert not is_structurally_compatible_utterance(legacy_payload)
    assert not is_current_submitted_utterance("submitted", legacy_payload)
    assert is_current_dispute_decision(
        {"C_primary_dispute_object": "uncertain", "DV_dispute_resolution": 3}, {"uncertain"}
    )


def test_current_schema_contains_only_the_two_persisted_ki_fields():
    assert set(KI_FIELDS) == {"KI_coordinating_edits", "KI_compromise"}
    assert set(KI_FIELDS) <= set(CURRENT_UTTERANCE_SCHEMA_FIELDS)
    assert "KI_present" not in CURRENT_UTTERANCE_SCHEMA_FIELDS
    assert "KI_present" not in ANNOTATION_FIELDS
    assert len(ANNOTATION_FIELDS) == len(set(ANNOTATION_FIELDS))


def test_malformed_utterance_keeps_construct_labels_optional():
    values = base(
        malformed_utterance=True,
        KS_present=None,
        KI_coordinating_edits=None,
        KI_compromise=None,
    )
    result = normalize_and_validate(values, {"coder_confidence", "review_flag"})
    assert result.valid
    assert result.payload["KI_coordinating_edits"] is None
    assert result.payload["KI_compromise"] is None


def test_ks_parent_no_clears_children_and_answered_state():
    values = base(KS_present=0, **{name: 1 for name in KS_FIELDS})
    answered = set(values)
    result = normalize_and_validate(values, answered)
    assert all(result.payload[name] is None for name in KS_FIELDS)
    assert not set(KS_FIELDS) & answered


def test_grounded_ks_requires_new_evidence_and_restaking_coexists():
    values = base(KS_present=1, KS_explicit_reasoning=1, KS_grounding=1, KS_bounding=0)
    result = normalize_and_validate(values, set(values))
    assert result.errors == {
        "KS_restaking": "An explicit response is required.",
        "KS_new_evidence": "An explicit response is required.",
    }
    values["KS_restaking"] = 1
    values["KS_new_evidence"] = 0
    result = normalize_and_validate(values, set(values))
    assert result.valid
    assert (
        result.payload["KS_restaking"] == result.payload["KS_explicit_reasoning"] == result.payload["KS_grounding"] == 1
    )


def test_new_evidence_is_null_without_grounding():
    values = base(KS_present=1, **{name: 1 for name in KS_FIELDS})
    values["KS_grounding"] = 0
    answered = set(values)
    result = normalize_and_validate(values, answered)
    assert result.valid
    assert result.payload["KS_new_evidence"] is None
    assert "KS_new_evidence" not in answered


@pytest.mark.parametrize("value", [None, 0, 6, 2.0, "3", True])
def test_dispute_requires_integer_resolution(value):
    assert not is_current_dispute_decision(
        {"C_primary_dispute_object": "uncertain", "DV_dispute_resolution": value}, {"uncertain"}
    )
    assert is_current_dispute_decision(
        {"C_primary_dispute_object": "uncertain", "DV_dispute_resolution": 3}, {"uncertain"}
    )


def test_structural_compatibility_requires_current_keys_not_hashes():
    payload = {name: None for name in CURRENT_UTTERANCE_SCHEMA_FIELDS}
    assert is_structurally_compatible_utterance(payload)
    payload.pop("KS_bounding")
    payload["KS_reasoning"] = 1
    assert not is_structurally_compatible_utterance(payload)


@pytest.mark.parametrize("value", [0, 6, 2.0, "3"])
def test_confidence_accepts_only_integer_one_through_five(value):
    assert "coder_confidence" in normalize_and_validate(base(coder_confidence=value), set(base())).errors


def test_review_is_explicit_and_comment_optional():
    values = base(review_flag=None, coder_notes="  ")
    result = normalize_and_validate(values, set(values) - {"review_flag"})
    assert "review_flag" in result.errors
    assert result.payload["coder_notes"] is None


def test_binary_values_reject_nonbinary_ks_child():
    values = base(KS_present=1, **{name: 0 for name in KS_FIELDS})
    values["KS_bounding"] = 2
    assert "KS_bounding" in normalize_and_validate(values, set(values)).errors
