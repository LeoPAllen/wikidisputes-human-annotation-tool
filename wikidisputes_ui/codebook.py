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
    "Example (verbatim excerpt + explanation)",
    "Example provenance (WikiDisputes; stable identifiers where available)",
    "question",
)
EXPECTED_LABELS = (
    "KS_present",
    "KS_explicit_reasoning",
    "KS_grounding",
    "KS_restaking",
    "KS_bounding",
    "KI_present",
    "C_off_topic_shift",
    "C_interpersonal_attack_or_disrespect",
    "C_formal_governance_action",
    "C_primary_dispute_object",
)
EXPECTED_DISPUTE_OBJECTS = (
    "claim_or_evidence_validity",
    "wording_or_representation",
    "inclusion_or_weight",
    "placement_or_structure",
    "mixed",
    "uncertain",
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
    question: str = ""


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


def _parse_dispute_objects(indicator: str, rule: str) -> dict[str, str]:
    enum = re.search(r"\{([^{}]+)\}", indicator)
    if enum is None:
        raise ValueError("C_primary_dispute_object Indicator must contain an enum in braces.")
    values = tuple(value.strip() for value in enum.group(1).split(","))
    if values != EXPECTED_DISPUTE_OBJECTS:
        raise ValueError(
            "C_primary_dispute_object Indicator must define exactly these values in order: "
            + ", ".join(EXPECTED_DISPUTE_OBJECTS)
        )
    descriptions: dict[str, str] = {}
    pattern = re.compile(r"^\s*[•*-]\s*([a-z][a-z0-9_]*)\s*:\s*(.+?)\s*$")
    for line in rule.splitlines():
        match = pattern.match(line)
        if match:
            key = match.group(1)
            if key not in values:
                raise ValueError(f"C_primary_dispute_object coding rule has unknown value: {key}")
            if key in descriptions:
                raise ValueError(f"C_primary_dispute_object coding rule repeats value: {key}")
            descriptions[key] = match.group(2).strip()
    return {value: descriptions.get(value, "") for value in values}


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
    if tuple(schema.columns) != CODEBOOK_COLUMNS:
        raise ValueError(f"{schema_sheet}: columns must exactly match the supported names and order.")
    labels = [_clean(value) for value in schema["Label"]]
    if any(not label for label in labels):
        raise ValueError("Codebook labels must be nonblank.")
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise ValueError(f"Duplicate codebook labels: {', '.join(duplicates)}")
    if tuple(labels) != EXPECTED_LABELS:
        raise ValueError("Codebook labels must exactly match the supported label set and display order.")
    questions = [_clean(value) for value in schema["question"]]
    if any(not question for question in questions):
        raise ValueError("Codebook questions must be nonblank for every schema row.")
    fields: dict[str, FieldGuide] = {}
    for _, row in schema.iterrows():
        label = _clean(row["Label"])
        fields[label] = FieldGuide(
            _clean(row["Family"]),
            label,
            _clean(row["Indicator"]),
            _clean(row["Definition"]),
            _clean(row["Coding rule"]),
            _clean(row["Example (verbatim excerpt + explanation)"]),
            _clean(row["Example provenance (WikiDisputes; stable identifiers where available)"]),
            _clean(row["question"]),
        )
    dispute_field = fields["C_primary_dispute_object"]
    objects = _parse_dispute_objects(dispute_field.indicator, dispute_field.rule)
    return Codebook(fields, objects, file_fingerprint(path), path.name)
