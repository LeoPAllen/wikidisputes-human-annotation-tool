"""Simplified annotation applicability and submission validation."""

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
KS_FIELDS = ("KS_claim_present", "KS_evidence_reference", "KS_reasoning", "KS_restaking")
KI_FIELDS = ("KI_solicit_feedback", "KI_compromise_position")
ANNOTATION_FIELDS = (
    BASE_BINARY
    + KS_FIELDS
    + KI_FIELDS
    + (
        "malformed_utterance",
        "coder_confidence",
        "review_flag",
        "coder_notes",
    )
)


@dataclass(frozen=True)
class ContextState:
    """Retained as a compatibility marker; applicability no longer depends on prior coding."""


@dataclass
class ValidationResult:
    payload: dict[str, Any]
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not self.errors


def applicable_fields(values: dict[str, Any], context: ContextState | None = None, low_threshold: int = 2) -> set[str]:
    del context, low_threshold
    applicable = set(BASE_BINARY) | {"malformed_utterance", "coder_confidence", "review_flag", "coder_notes"}
    if values.get("malformed_utterance") is True:
        applicable.update(KS_FIELDS + KI_FIELDS)
        return applicable
    if values.get("KS_present") == 1:
        applicable.update(KS_FIELDS)
    if values.get("KI_present") == 1:
        applicable.update(KI_FIELDS)
    return applicable


def normalize_and_validate(
    values: dict[str, Any],
    answered_fields: set[str],
    context: ContextState | None = None,
    evidence_types: set[str] | None = None,
    low_threshold: int = 2,
    require_complete: bool = True,
) -> ValidationResult:
    del evidence_types
    applicable = applicable_fields(values, context, low_threshold)
    payload = {name: values.get(name) if name in applicable else None for name in ANNOTATION_FIELDS}
    payload["malformed_utterance"] = values.get("malformed_utterance") is True
    answered_fields.intersection_update(applicable)
    errors: dict[str, str] = {}
    required = {"coder_confidence", "review_flag"}
    if payload["malformed_utterance"] is not True:
        required.update(BASE_BINARY)
    if payload["malformed_utterance"] is not True and payload["KS_present"] == 1:
        required.update(KS_FIELDS)
    if payload["malformed_utterance"] is not True and payload["KI_present"] == 1:
        required.update(KI_FIELDS)
    if require_complete:
        for name in required:
            if name not in answered_fields or payload.get(name) is None:
                errors[name] = "An explicit response is required."
    for name in BASE_BINARY + KS_FIELDS + KI_FIELDS + ("review_flag",):
        if payload.get(name) is not None and payload[name] not in (0, 1):
            errors[name] = "Choose No or Yes."
    if type(payload.get("malformed_utterance")) is not bool:
        errors["malformed_utterance"] = "Choose whether the utterance is malformed."
    confidence = payload.get("coder_confidence")
    if confidence is not None and (type(confidence) is not int or confidence not in range(1, 6)):
        errors["coder_confidence"] = "Choose an integer from 1 through 5."
    note = payload.get("coder_notes")
    payload["coder_notes"] = note.strip() if isinstance(note, str) and note.strip() else None
    return ValidationResult(payload, errors)
