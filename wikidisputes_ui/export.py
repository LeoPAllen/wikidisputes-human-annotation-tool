"""Auditable coder-isolated XLSX export."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from .ingest import (
    ANNOTATION_COLUMNS,
    CODER_HIDDEN_SOURCE_COLUMNS,
    LEGACY_SOURCE_ANNOTATION_COLUMNS,
    Dataset,
)
from .models import is_current_dispute_decision, is_structurally_compatible_utterance
from .storage import Storage

INTEGER_COLUMNS = {
    "KS_present",
    "KS_explicit_reasoning",
    "KS_grounding",
    "KS_new_evidence",
    "KS_restaking",
    "KS_bounding",
    "KI_present",
    "C_off_topic_shift",
    "C_interpersonal_attack_or_disrespect",
    "C_formal_governance_action",
    "coder_confidence",
    "review_flag",
    "DV_dispute_resolution",
    "revision_number",
}

AUDIT_EXPORT_COLUMNS = (
    "malformed_utterance",
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
DISPUTE_EXPORT_COLUMNS = (
    "dispute_id",
    "C_primary_dispute_object",
    "DV_dispute_resolution",
    "is_current",
    "coder_id",
    "schema_version",
    "schema_hash",
    "opened_at",
    "saved_at",
    "elapsed_wall_seconds",
    "revision_number",
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
    dispute_objects: Sequence[str],
) -> bytes:
    current = storage.rows("utterance_annotations", coder)
    disputes = storage.rows("dispute_annotations", coder)
    current_by_id = {str(row["utterance_id"]): row for row in current}
    dispute_by_id = {str(row["dispute_id"]): row for row in disputes}
    schema_columns = list(dict.fromkeys(schema_fields))
    source_columns = [
        key
        for key in dataset.source_rows.columns
        if not str(key).startswith("_")
        and key not in LEGACY_SOURCE_ANNOTATION_COLUMNS
        and key not in ANNOTATION_COLUMNS
        and key not in CODER_HIDDEN_SOURCE_COLUMNS
    ]
    output_columns = list(
        dict.fromkeys(source_columns + schema_columns + list(AUDIT_EXPORT_COLUMNS) + list(PROVENANCE_COLUMNS))
    )
    output_rows = []
    for _, source_row in dataset.annotatable_rows.iterrows():
        annotation = current_by_id.get(str(source_row["_annotation_key"]))
        if not annotation or annotation["status"] != "submitted":
            continue
        payload = json.loads(annotation["payload_json"])
        if not is_structurally_compatible_utterance(payload):
            continue
        row = {key: (None if pd.isna(value) else value) for key, value in source_row.items() if key in source_columns}
        row["export_schema_id"] = active_schema_id
        row["export_schema_hash"] = active_schema_hash
        for key in schema_columns + list(AUDIT_EXPORT_COLUMNS):
            row[key] = _flatten(payload.get(key))
        dispute_record = dispute_by_id.get(str(source_row["dispute_id"]))
        decision = {} if dispute_record is None else json.loads(dispute_record["payload_json"])
        current_decision = is_current_dispute_decision(decision, set(dispute_objects))
        for field in ("C_primary_dispute_object", "DV_dispute_resolution"):
            if field in schema_columns:
                row[field] = decision.get(field) if current_decision else None
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
    dispute_output_rows = []
    for did in dataset.annotatable_rows["dispute_id"].drop_duplicates().astype(str):
        record = dispute_by_id.get(did)
        payload = {} if record is None else json.loads(record["payload_json"])
        dispute_output_rows.append(
            {
                "dispute_id": did,
                "C_primary_dispute_object": payload.get("C_primary_dispute_object"),
                "DV_dispute_resolution": payload.get("DV_dispute_resolution"),
                "is_current": is_current_dispute_decision(payload, set(dispute_objects)),
                "coder_id": None if record is None else record["coder_id"],
                "schema_version": None if record is None else record["schema_version"],
                "schema_hash": None if record is None else record["schema_hash"],
                "opened_at": None if record is None else record["opened_at"],
                "saved_at": None if record is None else record["saved_at"],
                "elapsed_wall_seconds": None if record is None else record["elapsed_wall_seconds"],
                "revision_number": None if record is None else record["revision_number"],
            }
        )
    dispute_frame = pd.DataFrame(dispute_output_rows, columns=DISPUTE_EXPORT_COLUMNS)
    for column in ("DV_dispute_resolution", "revision_number"):
        dispute_frame[column] = pd.to_numeric(dispute_frame[column], errors="coerce").astype("Int64")
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Gold_Annotations", index=False)
        dispute_frame.to_excel(writer, sheet_name="Dispute_Annotations", index=False)
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
    dispute_objects: Sequence[str],
) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / safe_export_name(coder)
    path.write_bytes(
        build_export(
            storage,
            dataset,
            coder,
            active_schema_id,
            active_schema_hash,
            schema_fields,
            dispute_objects,
        )
    )
    return path
