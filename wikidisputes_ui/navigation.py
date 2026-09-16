"""Pure chronology-safe navigation decisions for the annotation UI."""

from __future__ import annotations

from dataclasses import dataclass

from .ingest import Dataset


@dataclass(frozen=True)
class Destination:
    page: str
    unit_id: str | None = None
    dispute_id: str | None = None


def previous_utterance(dataset: Dataset, dispute_id: str, display_order: int) -> str | None:
    earlier = dataset.earlier_annotatable_turns(dispute_id, display_order)
    return None if earlier.empty else str(earlier.iloc[-1]["_annotation_key"])


def dispute_destination(
    dataset: Dataset,
    dispute_id: str,
    submitted_ids: set[str],
    completed_disputes: set[str],
) -> Destination:
    """Choose the only chronology-safe default destination for a dispute."""
    turns = dataset.annotatable_in_dispute(dispute_id)
    pending = turns[~turns["_annotation_key"].astype(str).isin(submitted_ids)]
    if not pending.empty:
        return Destination("utterance", str(pending.iloc[0]["_annotation_key"]), dispute_id)
    if dispute_id not in completed_disputes:
        return Destination("dispute", dispute_id=dispute_id)
    return Destination("utterance", str(turns.iloc[0]["_annotation_key"]), dispute_id)


def is_reviewable_without_gap(
    dataset: Dataset,
    dispute_id: str,
    display_order: int,
    submitted_ids: set[str],
) -> bool:
    """A submitted turn is reviewable only when all earlier substantive turns remain submitted."""
    earlier = dataset.earlier_annotatable_turns(dispute_id, display_order)
    return set(earlier["_annotation_key"].astype(str)) <= submitted_ids


def dispute_progress(dataset: Dataset, dispute_id: str, submitted_ids: set[str]) -> tuple[int, int]:
    turns = dataset.annotatable_in_dispute(dispute_id)
    ids = set(turns["_annotation_key"].astype(str))
    return len(ids & submitted_ids), len(ids)
