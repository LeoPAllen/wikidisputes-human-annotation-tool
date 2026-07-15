"""Lossless workbook ingestion and context retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

PARTITION_SHEETS = {"calibration": "3_Calibration_Coder", "heldout": "4_Heldout_Coder"}
REQUIRED_COLUMNS = {
    "dispute_sequence",
    "dispute_id",
    "utterance_order",
    "utterance_id",
    "speaker_id",
    "timestamp",
    "reply_to_utterance_id",
    "utterance_type",
    "utterance_text",
}
ARTICLE_COLUMNS = ("article_title", "source_page_title", "dispute_label")
ANNOTATION_COLUMNS = {
    "coder_id",
    "KS_present",
    "KS_problem_claim_specified",
    "KS_evidence_present",
    "KS_evidence_type",
    "KS_warrant_explicit",
    "KS_acceptability_condition",
    "KS_repetition_or_restaking",
    "KS_derailment",
    "KI_present",
    "KI_propose_action",
    "KI_announce_enacted_action",
    "KI_solicit",
    "KI_iterate_on_candidate_action",
    "KI_explicit_feedback",
    "KI_prior_stake_reflection",
    "C_interpersonal_hostility",
    "C_formal_escalation_signal",
    "C_primary_dispute_object",
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


@dataclass
class Dataset:
    partitions: dict[str, pd.DataFrame]

    def frame(self, partition: str) -> pd.DataFrame:
        return self.partitions[partition]

    def prior_context(self, partition: str, dispute_id: str, utterance_order: int) -> pd.DataFrame:
        frame = self.frame(partition)
        return frame[
            (frame["dispute_id"].astype(str) == str(dispute_id)) & (frame["utterance_order"] < utterance_order)
        ].copy()

    def full_dispute(self, partition: str, dispute_id: str) -> pd.DataFrame:
        frame = self.frame(partition)
        return frame[frame["dispute_id"].astype(str) == str(dispute_id)].copy()


def read_gold(path: str | Path) -> Dataset:
    workbook = pd.ExcelFile(path)
    partitions = {}
    for partition, sheet in PARTITION_SHEETS.items():
        if sheet in workbook.sheet_names:
            frame = pd.read_excel(path, sheet_name=sheet, dtype=object)
            frame["utterance_order"] = pd.to_numeric(frame["utterance_order"], errors="raise").astype(int)
            frame["_source_row"] = range(2, len(frame) + 2)
            frame["_partition"] = partition
            partitions[partition] = frame
    return Dataset(partitions)


def source_metadata(row: pd.Series) -> dict[str, Any]:
    return {str(key): (None if pd.isna(value) else value) for key, value in row.items() if not str(key).startswith("_")}


def article_title(row: pd.Series) -> str:
    for column in ARTICLE_COLUMNS:
        if column in row and not pd.isna(row[column]):
            return str(row[column])
    return "Untitled article"
