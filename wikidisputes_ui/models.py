"""Annotation applicability and submission validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BASE_BINARY = (
    "KS_present",
    "KI_present",
    "C_off_topic_shift",
    "C_interpersonal_attack_or_disrespect",
    "C_formal_governance_action",
)
KS_FIELDS = ("KS_claim_target_specified", "KS_evidence_present", "KS_reasoning")
KI_FIELDS = ("KI_propose_edit", "KI_report_enacted_edit", "KI_solicit_candidate_feedback")
ALL_LABELS = set(
    BASE_BINARY
    + KS_FIELDS
    + KI_FIELDS
    + (
        "KS_evidence_type",
        "KS_argument_strength",
        "KS_unelaborated_restaking",
        "KI_iterate_on_candidate_edit",
        "KI_explicit_feedback",
        "KI_prior_knowledge",
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
ALL_FIELDS = ALL_LABELS | AUDIT_FIELDS


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


def applicable_fields(values: dict[str, Any], context: ContextState, low_threshold: int = 2) -> set[str]:
    applicable = set(BASE_BINARY) | {
        "coder_confidence",
        "short_justification",
        "review_flag",
        "coder_notes",
    }
    if values.get("KS_present") == 1:
        applicable.update(KS_FIELDS + ("KS_evidence_span",))
        if context.earlier_ks:
            applicable.add("KS_unelaborated_restaking")
            if values.get("KS_unelaborated_restaking") == 1:
                applicable.add("KS_prior_utterance_ids")
        if values.get("KS_evidence_present") == 1:
            applicable.add("KS_evidence_type")
        if values.get("KS_claim_target_specified") == 1 and (
            values.get("KS_evidence_present") == 1 or values.get("KS_reasoning") == 1
        ):
            applicable.add("KS_argument_strength")
    if values.get("KI_present") == 1:
        applicable.update(KI_FIELDS + ("KI_evidence_span",))
        if context.earlier_candidate:
            applicable.update(("KI_iterate_on_candidate_edit", "KI_explicit_feedback"))
        if context.earlier_ks:
            applicable.add("KI_prior_knowledge")
        feedback = values.get("KI_explicit_feedback")
        if (
            values.get("KI_iterate_on_candidate_edit") == 1
            or feedback in {"accept", "reject", "mixed_or_conditional"}
            or values.get("KI_prior_knowledge") == 1
        ):
            applicable.add("KI_upstream_utterance_ids")
    if any(values.get(name) == 1 for name in BASE_BINARY[2:]):
        applicable.add("control_evidence_span")
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
    applicable = applicable_fields(payload, context, low_threshold)
    for label in ALL_FIELDS - applicable:
        payload[label] = None
    required = set(BASE_BINARY) | {"coder_confidence", "review_flag"}
    if payload.get("KS_present") == 1:
        required.update(KS_FIELDS)
        if context.earlier_ks:
            required.add("KS_unelaborated_restaking")
        if payload.get("KS_evidence_present") == 1:
            required.add("KS_evidence_type")
        if payload.get("KS_claim_target_specified") == 1 and (
            payload.get("KS_evidence_present") == 1 or payload.get("KS_reasoning") == 1
        ):
            required.add("KS_argument_strength")
    if payload.get("KI_present") == 1:
        required.update(KI_FIELDS)
        if context.earlier_candidate:
            required.add("KI_iterate_on_candidate_edit")
        if context.earlier_ks:
            required.add("KI_prior_knowledge")
    if payload.get("KI_present") == 1 and context.earlier_candidate:
        required.add("KI_explicit_feedback")
    feedback = payload.get("KI_explicit_feedback")
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
    for name in (
        BASE_BINARY
        + KS_FIELDS
        + KI_FIELDS
        + (
            "KS_unelaborated_restaking",
            "KI_iterate_on_candidate_edit",
            "KI_prior_knowledge",
        )
    ):
        if payload.get(name) is not None and payload[name] not in (0, 1):
            errors[name] = "Choose No or Yes."
    if payload.get("KS_argument_strength") is not None and payload["KS_argument_strength"] not in range(3):
        errors["KS_argument_strength"] = "Choose 0, 1, or 2."
    for name in ("coder_confidence",):
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
