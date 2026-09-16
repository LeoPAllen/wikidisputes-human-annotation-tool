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
DISPLAY_ORDER_COLUMNS = ("substantive_order", "utterance_order")
ARTICLE_COLUMNS = ("article_title", "source_page_title", "dispute_label")
ANNOTATION_COLUMNS = {
    "coder_id",
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
    "C_primary_dispute_object",
    "DV_dispute_resolution",
    "coder_confidence",
    "review_flag",
    "coder_notes",
    "malformed_utterance",
}

# The immutable source workbook may retain blank columns from earlier schemas.
LEGACY_ANNOTATION_COLUMNS = {
    "KS_claim_present",
    "KS_evidence_reference",
    "KS_reasoning",
    "KI_solicit_feedback",
    "KI_compromise_position",
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
    "KS_claim_target_specified",
    "KS_evidence_present",
    "KS_evidence_type",
    "KS_warrant_reasoning",
    "KS_argument_strength",
    "KS_unelaborated_restaking",
    "KS_no_elaboration",
    "KS_prior_utterance_ids",
    "KI_propose_edit",
    "KI_report_enacted_edit",
    "KI_iterate",
    "KI_explicit_feedback",
    "KI_prior_knowledge",
    "KI_prior_knowledge_utterance_ids",
    "KI_iteration_utterance_ids",
    "KI_feedback_utterance_ids",
    "KS_evidence_span",
    "KI_evidence_span",
    "KI_upstream_utterance_ids",
    "control_evidence_span",
    "short_justification",
}
LEGACY_SOURCE_ANNOTATION_COLUMNS = ANNOTATION_COLUMNS | LEGACY_ANNOTATION_COLUMNS

# Retained in the authoritative source, but intentionally hidden from coders.
CODER_HIDDEN_SOURCE_COLUMNS = {
    "escalated",
    "dispute_resolution_url",
}


@dataclass
class Dataset:
    source_rows: pd.DataFrame

    def __post_init__(self) -> None:
        self.source_rows = self.source_rows.copy()
        if "_source_row" not in self.source_rows:
            self.source_rows["_source_row"] = range(2, len(self.source_rows) + 2)
        if "_annotation_key" not in self.source_rows:
            self.source_rows["_annotation_key"] = self.source_rows.apply(stable_annotation_key, axis=1)
        # Global navigation retains the workbook's first dispute appearance; only
        # rows within one dispute are reordered by the canonical display sequence.
        self.source_rows["_dispute_rank"] = pd.factorize(self.source_rows["dispute_id"], sort=False)[0]
        self.source_rows["_display_order"] = display_order_values(self.source_rows)

    @staticmethod
    def _ordered(rows: pd.DataFrame) -> pd.DataFrame:
        return rows.sort_values(["_dispute_rank", "_display_order", "_source_row"], kind="stable").copy()

    @property
    def annotatable_rows(self) -> pd.DataFrame:
        return self._ordered(self.source_rows[self.source_rows["utterance_role"] == "utterance"])

    @property
    def context_rows(self) -> pd.DataFrame:
        return self._ordered(self.source_rows[self.source_rows["utterance_role"] == "context"])

    def rows_in_dispute(self, dispute_id: str) -> pd.DataFrame:
        return self._ordered(self.source_rows[self.source_rows["dispute_id"].astype(str) == str(dispute_id)])

    def annotatable_in_dispute(self, dispute_id: str) -> pd.DataFrame:
        rows = self.rows_in_dispute(dispute_id)
        return rows[rows["utterance_role"] == "utterance"].copy()

    def displayable_prior_context(self, dispute_id: str, display_order: int) -> pd.DataFrame:
        rows = self.rows_in_dispute(dispute_id)
        return rows[rows["_display_order"] < display_order].copy()

    def earlier_annotatable_turns(self, dispute_id: str, display_order: int) -> pd.DataFrame:
        rows = self.displayable_prior_context(dispute_id, display_order)
        return rows[rows["utterance_role"] == "utterance"].copy()

    def prior_context(self, dispute_id: str, display_order: int) -> pd.DataFrame:
        return self.displayable_prior_context(dispute_id, display_order)

    def full_dispute(self, dispute_id: str) -> pd.DataFrame:
        return self.rows_in_dispute(dispute_id)


def read_gold(path: str | Path, annotation_sheet: str = "Gold_Annotation") -> Dataset:
    frame = pd.read_excel(path, sheet_name=annotation_sheet, dtype=object)
    frame["_source_row"] = range(2, len(frame) + 2)
    frame["_annotation_key"] = frame.apply(stable_annotation_key, axis=1)
    return Dataset(frame)


def _blank_to_na(values: pd.Series) -> pd.Series:
    return values.map(
        lambda value: pd.NA if pd.isna(value) or (isinstance(value, str) and not value.strip()) else value
    )


def display_order_values(frame: pd.DataFrame) -> pd.Series:
    """Return the source-supplied display order, preferring substantive_order.

    ``utterance_order`` remains a compatibility fallback for legacy Gold files.  This
    fallback is selected for a whole dispute, never mixed row by row: a legacy
    context heading may have no substantive order while its utterances do. This
    deliberately does not invent an order for a missing value; input QC reports it.
    """
    substantive = (
        _blank_to_na(frame["substantive_order"])
        if "substantive_order" in frame
        else pd.Series(pd.NA, index=frame.index, dtype=object)
    )
    legacy = (
        _blank_to_na(frame["utterance_order"])
        if "utterance_order" in frame
        else pd.Series(pd.NA, index=frame.index, dtype=object)
    )
    result = pd.Series(pd.NA, index=frame.index, dtype=object)
    groups = frame.groupby("dispute_id", sort=False, dropna=False) if "dispute_id" in frame else [(None, frame)]
    for _, group in groups:
        indices = group.index
        # A complete substantive sequence is canonical. Otherwise use the complete
        # legacy sequence (or leave missing values for validation to report).
        result.loc[indices] = (
            substantive.loc[indices] if substantive.loc[indices].notna().all() else legacy.loc[indices]
        )
    return result


def display_order(row: pd.Series) -> int:
    """Read a validated canonical display order for labels and chronology."""
    value = row.get("_display_order")
    if value is None or pd.isna(value):
        raise ValueError("Gold row has no complete display order.")
    return int(value)


def stable_annotation_key(row: pd.Series) -> str:
    for name in ("logical_utterance_uid", "original_utterance_id", "utterance_id"):
        value = row.get(name)
        if value is not None and not pd.isna(value) and str(value).strip():
            return str(value).strip()
    raise ValueError("Gold row has no stable annotation key.")


def source_metadata(row: pd.Series) -> dict[str, Any]:
    return {
        str(key): (None if pd.isna(value) else value)
        for key, value in row.items()
        if not str(key).startswith("_") and str(key) not in CODER_HIDDEN_SOURCE_COLUMNS
    }


def article_title(row: pd.Series) -> str:
    for column in ARTICLE_COLUMNS:
        if column in row and not pd.isna(row[column]):
            return str(row[column])
    return "Untitled article"
