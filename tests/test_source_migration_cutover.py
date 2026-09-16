from __future__ import annotations

from pathlib import Path

import pandas as pd

from wikidisputes_ui.ingest import Dataset
from wikidisputes_ui.models import is_current_submitted_utterance
from wikidisputes_ui.source_migration import migrate_gold_change, reconcile_annotation_keys
from wikidisputes_ui.storage import Storage


def _dataset(*, role: str, utterance_id: str = "same", text: str = "text") -> Dataset:
    frame = pd.DataFrame(
        [
            {
                "dispute_sequence": 1,
                "dispute_id": "D1",
                "utterance_order": 1,
                "substantive_order": 1 if role == "utterance" else None,
                "utterance_role": role,
                "utterance_id": utterance_id,
                "original_utterance_id": "stable",
                "speaker_id": "A",
                "timestamp": "2026-01-01",
                "reply_to_utterance_id": None,
                "utterance_type": "talk",
                "article_title": "Article",
                "utterance_text": text,
            }
        ]
    )
    return Dataset(frame)


def _save(storage: Storage, utterance_id: str) -> None:
    storage.set_active_coder("coder_1")
    storage.save_utterance(
        coder="coder_1",
        utterance_id=utterance_id,
        dispute_id="D1",
        payload={
            "KS_present": 0,
            "KS_explicit_reasoning": None,
            "KS_grounding": None,
            "KS_new_evidence": None,
            "KS_restaking": None,
            "KS_bounding": None,
            "KI_present": 0,
            "C_off_topic_shift": 0,
            "C_interpersonal_attack_or_disrespect": 0,
            "C_formal_governance_action": 0,
            "malformed_utterance": False,
        },
        answered_fields={
            "KS_present",
            "KI_present",
            "C_off_topic_shift",
            "C_interpersonal_attack_or_disrespect",
            "C_formal_governance_action",
            "malformed_utterance",
        },
        submit=True,
        schema_version="old",
        schema_hash="old-hash",
        opened_at="2026-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )


def test_legacy_order_fallback_is_dispute_wide_and_new_order_handles_nullable_legacy() -> None:
    legacy = pd.DataFrame(
        [
            {
                "dispute_id": "D1",
                "dispute_sequence": 1,
                "utterance_order": 1,
                "substantive_order": None,
                "utterance_role": "context",
                "utterance_id": "ctx",
                "speaker_id": "",
                "timestamp": "2026-01-01",
                "reply_to_utterance_id": None,
                "utterance_type": "context",
                "utterance_text": "heading",
            },
            {
                "dispute_id": "D1",
                "dispute_sequence": 1,
                "utterance_order": 2,
                "substantive_order": 1,
                "utterance_role": "utterance",
                "utterance_id": "u1",
                "speaker_id": "A",
                "timestamp": "2026-01-02",
                "reply_to_utterance_id": None,
                "utterance_type": "talk",
                "utterance_text": "first",
            },
        ]
    )
    legacy_data = Dataset(legacy)
    assert legacy_data.source_rows["_display_order"].tolist() == [1, 2]
    assert legacy_data.displayable_prior_context("D1", 2)["utterance_id"].tolist() == ["ctx"]

    new = legacy.copy()
    new["utterance_order"] = None
    new["substantive_order"] = [0, 1]
    new_data = Dataset(new)
    assert new_data.source_rows["_display_order"].tolist() == [0, 1]


def test_former_context_projection_is_not_submitted_when_newly_annotatable(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "annotations.sqlite3")
    old = _dataset(role="context")
    _save(storage, "same")
    reconcile_annotation_keys(storage, old)

    report = migrate_gold_change(storage, old, _dataset(role="utterance", text="now annotatable"))
    current = storage.current_utterance("coder_1", "stable")

    assert report.source_newly_annotatable == 1
    assert current is None or not is_current_submitted_utterance(current["status"], current["payload"])


def test_rereview_report_counts_alias_rekey_mutation(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "annotations.sqlite3")
    old = _dataset(role="utterance", utterance_id="old-current")
    _save(storage, "old-current")
    reconcile_annotation_keys(storage, old)

    # Simulate a legacy current projection that still uses the retired ID while
    # the source snapshot already contains the stable key.
    with storage.connect() as db:
        db.execute("UPDATE utterance_annotations SET utterance_id=?", ("old-current",))
    replacement = _dataset(role="utterance", utterance_id="old-current", text="changed")
    report = reconcile_annotation_keys(storage, replacement)

    assert report.db_rows_rekeyed == 1
    assert report.db_rows_marked_needs_rereview == 1


def test_direct_cutover_rerun_does_not_delete_new_annotation(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "annotations.sqlite3")
    old = _dataset(role="context")
    new = _dataset(role="utterance", text="now annotatable")
    _save(storage, "same")
    migrate_gold_change(storage, old, new)

    _save(storage, "stable")
    migrate_gold_change(storage, old, new)

    current = storage.current_utterance("coder_1", "stable")
    assert current is not None
    assert current["status"] == "submitted"
