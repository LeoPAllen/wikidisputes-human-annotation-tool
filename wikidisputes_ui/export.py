"""Auditable coder-isolated XLSX export."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from .ingest import ANNOTATION_COLUMNS, LEGACY_SOURCE_ANNOTATION_COLUMNS, Dataset
from .storage import Storage

INTEGER_COLUMNS = {
    "KS_present",
    "KS_claim_target_specified",
    "KS_evidence_present",
    "KS_warrant_reasoning",
    "KS_argument_strength",
    "KS_unelaborated_restaking",
    "KI_present",
    "KI_propose_edit",
    "KI_report_enacted_edit",
    "KI_solicit_feedback",
    "KI_iterate",
    "KI_prior_knowledge",
    "C_off_topic_shift",
    "C_interpersonal_attack_or_disrespect",
    "C_formal_governance_action",
    "coder_confidence",
    "review_flag",
    "revision_number",
}

AUDIT_EXPORT_COLUMNS = (
    "KS_prior_utterance_ids",
    "KI_evidence_span",
    "KI_upstream_utterance_ids",
    "control_evidence_span",
    "coder_confidence",
    "review_flag",
    "coder_notes",
)
PROVENANCE_COLUMNS = (
    "coder_id",
    "schema_version",
    "schema_hash",
    "annotation_saved_at",
    "revision_number",
    "export_schema_id",
    "export_schema_hash",
)


def _flatten(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return ";".join(sorted(dict.fromkeys(str(item) for item in value))) or None
    return value


def build_export(
    storage: Storage,
    dataset: Dataset,
    coder: str,
    active_schema_id: str,
    active_schema_hash: str,
    schema_fields: Sequence[str],
) -> bytes:
    current = [row for row in storage.rows("utterance_annotations", coder) if row["schema_hash"] == active_schema_hash]
    disputes = [row for row in storage.rows("dispute_annotations", coder) if row["schema_hash"] == active_schema_hash]
    current_by_id = {str(row["utterance_id"]): row for row in current}
    dispute_by_id = {str(row["dispute_id"]): json.loads(row["payload_json"]) for row in disputes}
    schema_columns = list(dict.fromkeys(schema_fields))
    source_columns = [
        key
        for key in dataset.source_rows.columns
        if not str(key).startswith("_")
        and key not in LEGACY_SOURCE_ANNOTATION_COLUMNS
        and key not in ANNOTATION_COLUMNS
    ]
    output_columns = list(
        dict.fromkeys(source_columns + schema_columns + list(AUDIT_EXPORT_COLUMNS) + list(PROVENANCE_COLUMNS))
    )
    output_rows = []
    for _, source_row in dataset.annotatable_rows.iterrows():
        annotation = current_by_id.get(str(source_row["utterance_id"]))
        if not annotation or annotation["status"] != "submitted":
            continue
        row = {key: (None if pd.isna(value) else value) for key, value in source_row.items() if key in source_columns}
        row["export_schema_id"] = active_schema_id
        row["export_schema_hash"] = active_schema_hash
        payload = json.loads(annotation["payload_json"])
        for key in schema_columns + list(AUDIT_EXPORT_COLUMNS):
            row[key] = _flatten(payload.get(key))
        decision = dispute_by_id.get(str(source_row["dispute_id"]), {})
        if "C_primary_dispute_object" in schema_columns:
            row["C_primary_dispute_object"] = decision.get("C_primary_dispute_object")
        row.update(
            {
                "coder_id": coder,
                "schema_version": annotation["schema_version"],
                "schema_hash": annotation["schema_hash"],
                "annotation_saved_at": annotation["saved_at"],
                "revision_number": annotation["revision_number"],
            }
        )
        output_rows.append(row)
    frame = pd.DataFrame(output_rows, columns=output_columns)
    for column in INTEGER_COLUMNS & set(frame.columns):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Gold_Annotations", index=False)
    return stream.getvalue()


def safe_export_name(coder: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"wikidisputes_{coder}_{stamp}.xlsx"


def write_export(
    storage: Storage,
    dataset: Dataset,
    coder: str,
    directory: str | Path,
    active_schema_id: str,
    active_schema_hash: str,
    schema_fields: Sequence[str],
) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / safe_export_name(coder)
    path.write_bytes(build_export(storage, dataset, coder, active_schema_id, active_schema_hash, schema_fields))
    return path
