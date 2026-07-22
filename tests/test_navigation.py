from wikidisputes_ui.ingest import Dataset
from wikidisputes_ui.navigation import (
    dispute_destination,
    dispute_progress,
    is_reviewable_without_gap,
    previous_utterance,
)


def test_previous_utterance_is_immediately_preceding_substantive_turn(source_rows):
    dataset = Dataset(source_rows)
    assert previous_utterance(dataset, "D1", 3) == "u1"
    assert previous_utterance(dataset, "D1", 2) is None


def test_incomplete_dispute_destination_cannot_skip_earliest_gap(source_rows):
    dataset = Dataset(source_rows)
    destination = dispute_destination(dataset, "D1", {"u2"}, set())
    assert destination.page == "utterance"
    assert destination.unit_id == "u1"
    assert not is_reviewable_without_gap(dataset, "D1", 3, {"u2"})


def test_dispute_destination_moves_to_decision_then_allows_completed_review(source_rows):
    dataset = Dataset(source_rows)
    submitted = {"u1", "u2"}
    assert dispute_progress(dataset, "D1", submitted) == (2, 2)
    pending_decision = dispute_destination(dataset, "D1", submitted, set())
    assert pending_decision.page == "dispute"
    completed = dispute_destination(dataset, "D1", submitted, {"D1"})
    assert completed.page == "utterance"
    assert completed.unit_id == "u1"
    assert is_reviewable_without_gap(dataset, "D1", 3, submitted)
