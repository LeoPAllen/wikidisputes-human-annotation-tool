from wikidisputes_ui.models import ContextState, applicable_fields, normalize_and_validate


EVIDENCE = {"external_source_or_quote"}


def complete_base(**updates):
    values = {
        "KS_present": 0,
        "KI_present": 0,
        "C_off_topic_shift": 0,
        "C_interpersonal_attack_or_disrespect": 0,
        "C_formal_governance_action": 0,
        "coder_confidence": 5,
        "review_flag": 0,
    }
    values.update(updates)
    return values


def test_feedback_is_inapplicable_and_normalized_when_ki_is_absent():
    context = ContextState(("u1",), earlier_candidate=True)
    values = complete_base(KI_explicit_feedback="accept")
    answered = set(values)
    result = normalize_and_validate(values, answered, context, EVIDENCE)
    assert result.valid
    assert result.payload["KI_explicit_feedback"] is None
    assert result.payload["KS_argument_strength"] is None
    assert "KI_explicit_feedback" not in applicable_fields(values, context)


def test_answered_null_feedback_is_required_when_ki_and_candidate_apply():
    context = ContextState(("u1",), earlier_candidate=True)
    values = complete_base(
        KI_present=1,
        KI_propose_edit=0,
        KI_report_enacted_edit=0,
        KI_solicit_candidate_feedback=0,
        KI_iterate_on_candidate_edit=0,
        KI_explicit_feedback=None,
        KI_evidence_span="integration language",
    )
    answered = set(values)
    assert normalize_and_validate(values, answered, context, EVIDENCE).valid
    unanswered = normalize_and_validate(values, answered - {"KI_explicit_feedback"}, context, EVIDENCE)
    assert "KI_explicit_feedback" in unanswered.errors


def test_conditional_audit_applicability():
    context = ContextState(("u1",), earlier_ks=True, earlier_candidate=True)
    base = complete_base()
    assert applicable_fields(base, context) == {
        "KS_present",
        "KI_present",
        "C_off_topic_shift",
        "C_interpersonal_attack_or_disrespect",
        "C_formal_governance_action",
        "coder_confidence",
        "short_justification",
        "review_flag",
        "coder_notes",
    }
    ks = complete_base(KS_present=1, KS_evidence_present=0, KS_unelaborated_restaking=1)
    assert {"KS_evidence_span", "KS_prior_utterance_ids"} <= applicable_fields(ks, context)
    supported_ks = complete_base(KS_present=1, KS_claim_target_specified=1, KS_evidence_present=0, KS_reasoning=1)
    assert "KS_argument_strength" in applicable_fields(supported_ks, context)
    controls = complete_base(C_interpersonal_attack_or_disrespect=1)
    assert "control_evidence_span" in applicable_fields(controls, context)
    assert "KI_evidence_span" not in applicable_fields(controls, context)


def test_optional_short_justification_is_preserved():
    values = complete_base(short_justification="Optional context")
    result = normalize_and_validate(values, set(values), ContextState(), EVIDENCE)
    assert result.valid
    assert result.payload["short_justification"] == "Optional context"


def test_control_evidence_is_optional():
    values = complete_base(C_interpersonal_attack_or_disrespect=1)
    result = normalize_and_validate(values, set(values), ContextState(), EVIDENCE)
    assert result.valid
    assert result.payload.get("control_evidence_span") is None


def test_dependencies_upstream_and_justification():
    context = ContextState(("u1",), earlier_ks=True, earlier_candidate=True)
    values = complete_base(
        KI_present=1,
        KI_propose_edit=1,
        KI_report_enacted_edit=0,
        KI_solicit_candidate_feedback=0,
        KI_iterate_on_candidate_edit=1,
        KI_prior_knowledge=1,
        KI_explicit_feedback="accept",
        KI_evidence_span="proposal",
        KI_upstream_utterance_ids=["future"],
        coder_confidence=2,
    )
    result = normalize_and_validate(values, set(values), context, EVIDENCE)
    assert "KI_upstream_utterance_ids" in result.errors
    assert "short_justification" in result.errors
    values["KI_upstream_utterance_ids"] = ["u1"]
    values["short_justification"] = "uncertain referent"
    result = normalize_and_validate(values, set(values), context, EVIDENCE)
    assert result.valid


def test_audit_utterance_links_are_optional_when_dependencies_are_positive():
    context = ContextState(("u1",), earlier_ks=True, earlier_candidate=True)
    values = complete_base(
        KS_present=1,
        KS_claim_target_specified=0,
        KS_evidence_present=0,
        KS_reasoning=0,
        KS_unelaborated_restaking=1,
        KI_present=1,
        KI_propose_edit=0,
        KI_report_enacted_edit=0,
        KI_solicit_candidate_feedback=0,
        KI_iterate_on_candidate_edit=1,
        KI_explicit_feedback=None,
        KI_prior_knowledge=0,
    )
    result = normalize_and_validate(values, set(values), context, EVIDENCE)
    assert result.valid
    assert result.payload.get("KS_prior_utterance_ids") is None
    assert result.payload.get("KI_upstream_utterance_ids") is None


def test_ordinal_and_evidence_values():
    context = ContextState()
    values = complete_base(
        KS_present=1,
        KS_claim_target_specified=1,
        KS_evidence_present=1,
        KS_reasoning=1,
        KS_evidence_type=["bad"],
        KS_argument_strength=3,
        KS_evidence_span="quote",
    )
    result = normalize_and_validate(values, set(values), context, EVIDENCE)
    assert "KS_argument_strength" in result.errors
    assert "KS_evidence_type" in result.errors


def test_positive_ks_and_ki_allow_optional_evidence_spans():
    values = complete_base(
        KS_present=1,
        KS_claim_target_specified=1,
        KS_evidence_present=0,
        KS_reasoning=0,
        KI_present=1,
        KI_propose_edit=0,
        KI_report_enacted_edit=0,
        KI_solicit_candidate_feedback=0,
    )
    result = normalize_and_validate(values, set(values), ContextState(), EVIDENCE)
    assert result.valid
    assert result.payload.get("KS_evidence_span") is None
    assert result.payload.get("KI_evidence_span") is None
