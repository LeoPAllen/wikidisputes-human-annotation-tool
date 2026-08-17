import pytest

from wikidisputes_ui.models import KI_FIELDS, KS_FIELDS, applicable_fields, normalize_and_validate


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
    values = base(KS_present=1, KI_present=1, **{name: 0 for name in KS_FIELDS + KI_FIELDS})
    result = normalize_and_validate(values, set(values))
    assert result.valid
    assert set(KS_FIELDS + KI_FIELDS) <= applicable_fields(values)


@pytest.mark.parametrize("parent,children", [("KS_present", KS_FIELDS), ("KI_present", KI_FIELDS)])
def test_parent_no_clears_children_and_answered_state(parent, children):
    values = base(**{parent: 0}, **{name: 1 for name in children})
    answered = set(values)
    result = normalize_and_validate(values, answered)
    assert all(result.payload[name] is None for name in children)
    assert not set(children) & answered


def test_ks_restaking_is_required_and_not_derived():
    values = base(KS_present=1, KS_claim_present=1, KS_evidence_reference=0, KS_reasoning=0)
    result = normalize_and_validate(values, set(values))
    assert result.errors == {"KS_restaking": "An explicit response is required."}
    values["KS_restaking"] = 0
    assert normalize_and_validate(values, set(values)).payload["KS_restaking"] == 0


@pytest.mark.parametrize("value", [0, 6, 2.0, "3"])
def test_confidence_accepts_only_integer_one_through_five(value):
    assert "coder_confidence" in normalize_and_validate(base(coder_confidence=value), set(base())).errors


def test_review_is_explicit_and_comment_optional():
    values = base(review_flag=None, coder_notes="  ")
    result = normalize_and_validate(values, set(values) - {"review_flag"})
    assert "review_flag" in result.errors
    assert result.payload["coder_notes"] is None


def test_binary_values_reject_nonbinary_compromise():
    values = base(KI_present=1, KI_solicit_feedback=0, KI_compromise_position=2)
    assert "KI_compromise_position" in normalize_and_validate(values, set(values)).errors
