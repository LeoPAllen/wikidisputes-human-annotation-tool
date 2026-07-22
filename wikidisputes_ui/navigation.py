"""Pure chronology-safe navigation decisions for the annotation UI."""

from __future__ import annotations

from dataclasses import dataclass

from .ingest import Dataset


@dataclass(frozen=True)
class Destination:
    page: str
    unit_id: str | None = None
    dispute_id: str | None = None


def previous_utterance(dataset: Dataset, dispute_id: str, utterance_order: int) -> str | None:
    earlier = dataset.earlier_annotatable_turns(dispute_id, utterance_order)
    return None if earlier.empty else str(earlier.iloc[-1]["utterance_id"])


def dispute_destination(
    dataset: Dataset,
    dispute_id: str,
    submitted_ids: set[str],
    completed_disputes: set[str],
) -> Destination:
    """Choose the only chronology-safe default destination for a dispute."""
    turns = dataset.annotatable_in_dispute(dispute_id)
    pending = turns[~turns["utterance_id"].astype(str).isin(submitted_ids)]
    if not pending.empty:
        return Destination("utterance", str(pending.iloc[0]["utterance_id"]), dispute_id)
    if dispute_id not in completed_disputes:
        return Destination("dispute", dispute_id=dispute_id)
    return Destination("utterance", str(turns.iloc[0]["utterance_id"]), dispute_id)


def is_reviewable_without_gap(
    dataset: Dataset,
    dispute_id: str,
    utterance_order: int,
    submitted_ids: set[str],
) -> bool:
    """A submitted turn is reviewable only when all earlier substantive turns remain submitted."""
    earlier = dataset.earlier_annotatable_turns(dispute_id, utterance_order)
    return set(earlier["utterance_id"].astype(str)) <= submitted_ids


def dispute_progress(dataset: Dataset, dispute_id: str, submitted_ids: set[str]) -> tuple[int, int]:
    turns = dataset.annotatable_in_dispute(dispute_id)
    ids = set(turns["utterance_id"].astype(str))
    return len(ids & submitted_ids), len(ids)
