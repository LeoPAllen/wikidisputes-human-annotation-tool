"""Lossless workbook ingestion and context retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

REQUIRED_COLUMNS = {
    "dispute_sequence",
    "dispute_id",
    "utterance_order",
    "utterance_role",
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
    "KS_claim_target_specified",
    "KS_evidence_present",
    "KS_evidence_type",
    "KS_reasoning",
    "KS_argument_strength",
    "KS_unelaborated_restaking",
    "KI_present",
    "KI_propose_edit",
    "KI_report_enacted_edit",
    "KI_solicit_candidate_feedback",
    "KI_iterate_on_candidate_edit",
    "KI_explicit_feedback",
    "KI_prior_knowledge",
    "C_off_topic_shift",
    "C_interpersonal_attack_or_disrespect",
    "C_formal_governance_action",
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

# The immutable source workbook may retain blank columns from earlier schemas.
LEGACY_ANNOTATION_COLUMNS = {
    "KS_problem_claim_specified",
    "KS_warrant_explicit",
    "KS_acceptability_condition",
    "KS_repetition_or_restaking",
    "KS_derailment",
    "KI_propose_action",
    "KI_announce_enacted_action",
    "KI_solicit",
    "KI_iterate_on_candidate_action",
    "KI_prior_stake_reflection",
    "C_interpersonal_hostility",
    "C_formal_escalation_signal",
}
NEW_SCHEMA_COLUMNS = {
    "KS_claim_target_specified",
    "KS_reasoning",
    "KS_argument_strength",
    "KS_unelaborated_restaking",
    "KI_propose_edit",
    "KI_report_enacted_edit",
    "KI_solicit_candidate_feedback",
    "KI_iterate_on_candidate_edit",
    "KI_prior_knowledge",
    "C_off_topic_shift",
    "C_interpersonal_attack_or_disrespect",
    "C_formal_governance_action",
}
LEGACY_SOURCE_ANNOTATION_COLUMNS = (ANNOTATION_COLUMNS - NEW_SCHEMA_COLUMNS) | LEGACY_ANNOTATION_COLUMNS


@dataclass
class Dataset:
    source_rows: pd.DataFrame

    @property
    def annotatable_rows(self) -> pd.DataFrame:
        return self.source_rows[self.source_rows["utterance_role"] == "utterance"].copy()

    @property
    def context_rows(self) -> pd.DataFrame:
        return self.source_rows[self.source_rows["utterance_role"] == "context"].copy()

    def rows_in_dispute(self, dispute_id: str) -> pd.DataFrame:
        return self.source_rows[self.source_rows["dispute_id"].astype(str) == str(dispute_id)].copy()

    def annotatable_in_dispute(self, dispute_id: str) -> pd.DataFrame:
        rows = self.rows_in_dispute(dispute_id)
        return rows[rows["utterance_role"] == "utterance"].copy()

    def displayable_prior_context(self, dispute_id: str, utterance_order: int) -> pd.DataFrame:
        rows = self.rows_in_dispute(dispute_id)
        return rows[rows["utterance_order"] < utterance_order].copy()

    def earlier_annotatable_turns(self, dispute_id: str, utterance_order: int) -> pd.DataFrame:
        rows = self.displayable_prior_context(dispute_id, utterance_order)
        return rows[rows["utterance_role"] == "utterance"].copy()

    def prior_context(self, dispute_id: str, utterance_order: int) -> pd.DataFrame:
        return self.displayable_prior_context(dispute_id, utterance_order)

    def full_dispute(self, dispute_id: str) -> pd.DataFrame:
        return self.rows_in_dispute(dispute_id)


def read_gold(path: str | Path, annotation_sheet: str = "Gold_Annotation") -> Dataset:
    frame = pd.read_excel(path, sheet_name=annotation_sheet, dtype=object)
    frame["utterance_order"] = pd.to_numeric(frame["utterance_order"], errors="raise").astype(int)
    frame["_source_row"] = range(2, len(frame) + 2)
    return Dataset(frame)


def source_metadata(row: pd.Series) -> dict[str, Any]:
    return {str(key): (None if pd.isna(value) else value) for key, value in row.items() if not str(key).startswith("_")}


def article_title(row: pd.Series) -> str:
    for column in ARTICLE_COLUMNS:
        if column in row and not pd.isna(row[column]):
            return str(row[column])
    return "Untitled article"
