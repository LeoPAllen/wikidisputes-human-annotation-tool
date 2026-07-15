"""Auditable coder-isolated XLSX export."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .ingest import Dataset
from .storage import Storage

INTEGER_COLUMNS = {
    "KS_present",
    "KS_problem_claim_specified",
    "KS_evidence_present",
    "KS_warrant_explicit",
    "KS_acceptability_condition",
    "KS_repetition_or_restaking",
    "KS_derailment",
    "KI_present",
    "KI_propose_action",
    "KI_announce_enacted_action",
    "KI_solicit",
    "KI_iterate_on_candidate_action",
    "KI_prior_stake_reflection",
    "C_interpersonal_hostility",
    "C_formal_escalation_signal",
    "coder_confidence",
    "review_flag",
    "revision_number",
}


def _flatten(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        return ";".join(sorted(dict.fromkeys(str(item) for item in value))) or None
    return value


def _records(rows: list[dict[str, Any]]) -> pd.DataFrame:
    output = []
    for row in rows:
        item = dict(row)
        for key in ("payload_json", "answered_fields_json"):
            if key in item:
                parsed = json.loads(item.pop(key))
                if key == "payload_json":
                    item.update({name: _flatten(value) for name, value in parsed.items()})
                else:
                    item["answered_fields"] = ";".join(parsed)
        output.append(item)
    return pd.DataFrame(output)


def build_export(storage: Storage, dataset: Dataset, coder: str, qc_report: str) -> bytes:
    current = storage.rows("utterance_annotations", coder)
    disputes = storage.rows("dispute_annotations", coder)
    current_by_id = {str(row["utterance_id"]): row for row in current}
    dispute_by_id = {str(row["dispute_id"]): json.loads(row["payload_json"]) for row in disputes}
    output_rows = []
    for _, source_row in dataset.source_rows.iterrows():
        row = {
            key: (None if pd.isna(value) else value)
            for key, value in source_row.items()
            if not str(key).startswith("_")
        }
        is_utterance = source_row["utterance_role"] == "utterance"
        annotation = current_by_id.get(str(source_row["utterance_id"])) if is_utterance else None
        if annotation and annotation["status"] == "submitted":
            row.update({key: _flatten(value) for key, value in json.loads(annotation["payload_json"]).items()})
            row.update(
                {
                    "coder_id": coder,
                    "schema_version": annotation["schema_version"],
                    "schema_hash": annotation["schema_hash"],
                    "annotation_saved_at": annotation["saved_at"],
                    "revision_number": annotation["revision_number"],
                }
            )
        if is_utterance:
            decision = dispute_by_id.get(str(source_row["dispute_id"]), {})
            row["C_primary_dispute_object"] = decision.get("C_primary_dispute_object")
        output_rows.append(row)
    sheets: dict[str, pd.DataFrame] = {"Gold_Annotations": pd.DataFrame(output_rows)}
    for column in INTEGER_COLUMNS & set(sheets["Gold_Annotations"].columns):
        sheets["Gold_Annotations"][column] = pd.to_numeric(sheets["Gold_Annotations"][column], errors="coerce").astype(
            "Int64"
        )
    sheets["Dispute_Annotations"] = _records(disputes)
    sheets["Annotation_Events"] = _records(storage.rows("utterance_annotation_events", coder))
    sheets["Dispute_Events"] = _records(storage.rows("dispute_annotation_events", coder))
    sheets["Schema_Versions"] = pd.DataFrame(storage.rows("schema_versions"))
    sheets["QC_Report"] = pd.DataFrame({"report_line": qc_report.splitlines()})
    stream = BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    return stream.getvalue()


def safe_export_name(coder: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"wikidisputes_{coder}_{stamp}.xlsx"


def write_export(storage: Storage, dataset: Dataset, coder: str, qc_report: str, directory: str | Path) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / safe_export_name(coder)
    path.write_bytes(build_export(storage, dataset, coder, qc_report))
    return path
