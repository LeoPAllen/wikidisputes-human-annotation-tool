import pytest

from wikidisputes_ui.models import (
    CURRENT_UTTERANCE_SCHEMA_FIELDS,
    KI_FIELDS,
    KS_FIELDS,
    applicable_fields,
    is_current_dispute_decision,
    is_structurally_compatible_utterance,
    normalize_and_validate,
)


def base(**changes):
    values = {
        "KS_present": 0,
        "KI_present": 0,
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
    values = base(KS_present=1, KI_present=1, **{name: 0 for name in KS_FIELDS})
    result = normalize_and_validate(values, set(values))
    assert result.valid
    assert set(KS_FIELDS) - {"KS_new_evidence"} <= applicable_fields(values)
    assert "KS_new_evidence" not in applicable_fields(values)
    assert KI_FIELDS == ()


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
