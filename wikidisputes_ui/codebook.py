"""Authoritative one-sheet codebook parser."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

import pandas as pd

CODEBOOK_COLUMNS = (
    "Family",
    "Label",
    "Indicator",
    "Definition",
    "Coding rule",
    "Example (raw text + explanation)",
    "Example provenance",
)
EXPECTED_LABELS = (
    "KS_present",
    "KS_claim_present",
    "KS_evidence_reference",
    "KS_reasoning",
    "KS_restaking",
    "KI_present",
    "KI_solicit_feedback",
    "KI_compromise_position",
    "C_off_topic_shift",
    "C_interpersonal_attack_or_disrespect",
    "C_formal_governance_action",
    "C_primary_dispute_object",
)
EXPECTED_DISPUTE_OBJECTS = (
    "wording_or_framing",
    "source_or_evidence",
    "factual_accuracy",
    "neutrality_or_balance",
    "scope_relevance_or_due_weight",
    "article_structure_or_location",
    "visual_or_media_content",
    "mixed_or_unclear",
)


@dataclass(frozen=True)
class FieldGuide:
    family: str
    label: str
    indicator: str
    definition: str
    rule: str
    example: str
    example_provenance: str = ""


@dataclass(frozen=True)
class Codebook:
    fields: dict[str, FieldGuide]
    dispute_objects: dict[str, str]
    file_hash: str
    source_filename: str


def _clean(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip()


def file_fingerprint(path: str | Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def schema_id(file_hash: str) -> str:
    return f"schema-{file_hash[:12]}"


def _parse_dispute_objects(rule: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    pattern = re.compile(r"^\s*[•*-]\s*([a-z][a-z0-9_]*)\s*[—–-]\s*(.+?)\s*$")
    for line in rule.splitlines():
        match = pattern.match(line)
        if match:
            parsed[match.group(1)] = match.group(2).rstrip(".")
    if tuple(parsed) != EXPECTED_DISPUTE_OBJECTS:
        raise ValueError(
            "C_primary_dispute_object coding rule must define exactly these values in order: "
            + ", ".join(EXPECTED_DISPUTE_OBJECTS)
        )
    return parsed


def load_codebook(path: str | Path, schema_sheet: str = "Core_Schema") -> Codebook:
    path = Path(path)
    excel = pd.ExcelFile(path)
    if excel.sheet_names != [schema_sheet]:
        raise ValueError(
            f"Codebook must contain exactly one worksheet named {schema_sheet!r}; found {excel.sheet_names!r}."
        )
    schema = pd.read_excel(path, sheet_name=schema_sheet, dtype=object)
    missing = [column for column in CODEBOOK_COLUMNS if column not in schema.columns]
    if missing:
        raise ValueError(f"{schema_sheet}: missing columns: {', '.join(missing)}")
    labels = [_clean(value) for value in schema["Label"]]
    if any(not label for label in labels):
        raise ValueError("Codebook labels must be nonblank.")
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise ValueError(f"Duplicate codebook labels: {', '.join(duplicates)}")
    if tuple(labels) != EXPECTED_LABELS:
        raise ValueError("Codebook labels must exactly match the supported label set and display order.")
    fields: dict[str, FieldGuide] = {}
    for _, row in schema.iterrows():
        label = _clean(row["Label"])
        fields[label] = FieldGuide(
            _clean(row["Family"]),
            label,
            _clean(row["Indicator"]),
            _clean(row["Definition"]),
            _clean(row["Coding rule"]),
            _clean(row["Example (raw text + explanation)"]),
            _clean(row["Example provenance"]),
        )
    objects = _parse_dispute_objects(fields["C_primary_dispute_object"].rule)
    return Codebook(fields, objects, file_fingerprint(path), path.name)
