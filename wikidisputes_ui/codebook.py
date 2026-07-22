"""Authoritative codebook parser."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class FieldGuide:
    family: str
    label: str
    indicator: str
    definition: str
    rule: str
    example: str


@dataclass(frozen=True)
class Codebook:
    fields: dict[str, FieldGuide]
    evidence_types: dict[str, dict[str, str]]
    dispute_objects: dict[str, dict[str, str]]
    file_hash: str
    source_filename: str


EXPECTED_LABELS = {
    "KS_present",
    "KS_claim_target_specified",
    "KS_evidence_present",
    "KS_evidence_type",
    "KS_warrant_reasoning",
    "KS_argument_strength",
    "KS_unelaborated_restaking",
    "KI_present",
    "KI_propose_edit",
    "KI_report_enacted_edit",
    "KI_solicit_feedback",
    "KI_iterate",
    "KI_explicit_feedback",
    "KI_prior_knowledge",
    "C_off_topic_shift",
    "C_interpersonal_attack_or_disrespect",
    "C_formal_governance_action",
    "C_primary_dispute_object",
}


def _clean(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip()


def file_fingerprint(path: str | Path) -> str:
    """Return the canonical identity of an input file."""
    return sha256(Path(path).read_bytes()).hexdigest()


def schema_id(file_hash: str) -> str:
    """Return a compact display/storage label derived from the canonical hash."""
    return f"schema-{file_hash[:12]}"


def load_codebook(path: str | Path, schema_sheet: str = "Core_Schema_SIMPLIFIED") -> Codebook:
    path = Path(path)
    schema = pd.read_excel(path, sheet_name=schema_sheet, dtype=object)
    evidence = pd.read_excel(path, sheet_name="Evidence_Types", dtype=object)
    objects = pd.read_excel(path, sheet_name="Primary_Dispute_Objects", dtype=object)
    example_column = "Example (raw text + explanation)"
    if example_column not in schema.columns:
        example_column = "Real example"
    fields = {}
    for _, row in schema.iterrows():
        label = _clean(row["Label"])
        fields[label] = FieldGuide(
            _clean(row["Family"]),
            label,
            _clean(row["Indicator"]),
            _clean(row["Definition"]),
            _clean(row["Coding rule"]),
            _clean(row[example_column]),
        )
    evidence_types = {
        _clean(row["Evidence type"]): {str(k): _clean(v) for k, v in row.items()}
        for _, row in evidence.iterrows()
        if _clean(row["Evidence type"])
    }
    dispute_objects = {
        _clean(row["Primary dispute object"]): {str(k): _clean(v) for k, v in row.items()}
        for _, row in objects.iterrows()
        if _clean(row["Primary dispute object"])
    }
    return Codebook(fields, evidence_types, dispute_objects, file_fingerprint(path), path.name)
