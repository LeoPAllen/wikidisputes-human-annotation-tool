"""Annotation applicability and submission validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BASE_BINARY = ("KS_present", "KI_present", "C_interpersonal_hostility", "C_formal_escalation_signal")
KS_FIELDS = ("KS_problem_claim_specified", "KS_evidence_present", "KS_acceptability_condition", "KS_derailment")
KI_FIELDS = ("KI_propose_action", "KI_announce_enacted_action", "KI_solicit")
ALL_LABELS = set(
    BASE_BINARY
    + KS_FIELDS
    + KI_FIELDS
    + (
        "KS_evidence_type",
        "KS_warrant_explicit",
        "KS_repetition_or_restaking",
        "KI_iterate_on_candidate_action",
        "KI_explicit_feedback",
        "KI_prior_stake_reflection",
    )
)
AUDIT_FIELDS = {
    "KS_evidence_span",
    "KS_prior_utterance_ids",
    "KI_evidence_span",
    "KI_upstream_utterance_ids",
    "control_evidence_span",
    "coder_confidence",
    "short_justification",
    "review_flag",
    "coder_notes",
}


@dataclass(frozen=True)
class ContextState:
    earlier_ids: tuple[str, ...] = ()
    earlier_ks: bool = False
    earlier_candidate: bool = False


@dataclass
class ValidationResult:
    payload: dict[str, Any]
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not self.errors


def applicable_fields(values: dict[str, Any], context: ContextState) -> set[str]:
    applicable = set(BASE_BINARY) | {"coder_confidence", "review_flag"}
    if values.get("KS_present") == 1:
        applicable.update(KS_FIELDS)
        if context.earlier_ks:
            applicable.add("KS_repetition_or_restaking")
        if values.get("KS_evidence_present") == 1:
            applicable.update(("KS_evidence_type", "KS_warrant_explicit"))
    if values.get("KI_present") == 1:
        applicable.update(KI_FIELDS)
        if context.earlier_candidate:
            applicable.add("KI_iterate_on_candidate_action")
        if context.earlier_ks:
            applicable.add("KI_prior_stake_reflection")
    if context.earlier_candidate:
        applicable.add("KI_explicit_feedback")
    applicable.update(AUDIT_FIELDS - {"coder_confidence", "review_flag"})
    return applicable


def normalize_and_validate(
    values: dict[str, Any],
    answered_fields: set[str],
    context: ContextState,
    evidence_types: set[str],
    low_threshold: int = 2,
    require_complete: bool = True,
) -> ValidationResult:
    payload = dict(values)
    errors: dict[str, str] = {}
    applicable = applicable_fields(payload, context)
    for label in ALL_LABELS - applicable:
        payload[label] = None
    required = set(BASE_BINARY) | {"coder_confidence", "review_flag"}
    if payload.get("KS_present") == 1:
        required.update(KS_FIELDS)
        required.add("KS_evidence_span")
        if context.earlier_ks:
            required.add("KS_repetition_or_restaking")
        if payload.get("KS_evidence_present") == 1:
            required.update(("KS_evidence_type", "KS_warrant_explicit"))
    if payload.get("KI_present") == 1:
        required.update(set(KI_FIELDS) | {"KI_evidence_span"})
        if context.earlier_candidate:
            required.add("KI_iterate_on_candidate_action")
        if context.earlier_ks:
            required.add("KI_prior_stake_reflection")
    if context.earlier_candidate:
        required.add("KI_explicit_feedback")
    if payload.get("C_interpersonal_hostility") == 1 or payload.get("C_formal_escalation_signal") == 1:
        required.add("control_evidence_span")
    if payload.get("KS_repetition_or_restaking") == 1:
        required.add("KS_prior_utterance_ids")
    feedback = payload.get("KI_explicit_feedback")
    reflection = payload.get("KI_prior_stake_reflection")
    if (
        payload.get("KI_iterate_on_candidate_action") == 1
        or feedback in {"accept", "reject", "mixed_or_conditional"}
        or (isinstance(reflection, int) and reflection > 1)
    ):
        required.add("KI_upstream_utterance_ids")
    if (
        payload.get("review_flag") == 1
        or isinstance(payload.get("coder_confidence"), int)
        and payload["coder_confidence"] <= low_threshold
    ):
        required.add("short_justification")
    if require_complete:
        for name in required:
            if name not in answered_fields or (payload.get(name) in (None, "", []) and name != "KI_explicit_feedback"):
                errors[name] = "An explicit response is required."
    for name in BASE_BINARY + KS_FIELDS + KI_FIELDS + ("KS_repetition_or_restaking", "KI_iterate_on_candidate_action"):
        if payload.get(name) is not None and payload[name] not in (0, 1):
            errors[name] = "Choose No or Yes."
    for name in ("KS_warrant_explicit", "KI_prior_stake_reflection", "coder_confidence"):
        if payload.get(name) is not None and payload[name] not in range(1, 6):
            errors[name] = "Choose an integer from 1 through 5."
    selected = payload.get("KS_evidence_type")
    if selected is not None:
        unknown = set(selected) - evidence_types
        if unknown:
            errors["KS_evidence_type"] = f"Unknown evidence type(s): {', '.join(sorted(unknown))}"
        payload["KS_evidence_type"] = sorted(set(selected))
    for field_name in ("KS_prior_utterance_ids", "KI_upstream_utterance_ids"):
        ids = payload.get(field_name)
        if ids:
            invalid = set(ids) - set(context.earlier_ids)
            if invalid:
                errors[field_name] = f"Only earlier utterance IDs are allowed: {', '.join(sorted(invalid))}"
            payload[field_name] = sorted(set(ids))
    if feedback not in (None, "accept", "reject", "mixed_or_conditional"):
        errors["KI_explicit_feedback"] = "Choose a canonical feedback value."
    return ValidationResult(payload, errors)
