from io import BytesIO
import pandas as pd
import pytest

from wikidisputes_ui.export import build_export
from wikidisputes_ui.ingest import read_gold
from wikidisputes_ui.storage import SchemaDriftError, Storage


def save(storage, coder="coder_1", uid="u1", payload=None):
    storage.set_active_coder(coder)
    return storage.save_utterance(
        coder=coder,
        partition="calibration",
        utterance_id=uid,
        dispute_id="D1",
        payload=payload or {"KS_present": 0, "KS_evidence_type": None, "KI_upstream_utterance_ids": ["prior", "a"]},
        answered_fields={"KS_present"},
        submit=True,
        schema_version="0.9.7",
        schema_hash="abc",
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=-3,
    )


def test_schema_drift_events_revisions_and_utc(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    storage.register_schema("0.9.7", "abc", "codebook.xlsx")
    with pytest.raises(SchemaDriftError):
        storage.register_schema("0.9.7", "changed", "codebook.xlsx")
    assert save(storage) == ("submit", 1)
    assert save(storage) == ("unchanged", 1)
    assert save(storage, payload={"KS_present": 1}) == ("revise", 2)
    events = storage.rows("utterance_annotation_events", "coder_1")
    assert [row["revision_number"] for row in events] == [1, 2]
    assert all(row["saved_at"].endswith("Z") and row["elapsed_wall_seconds"] >= 0 for row in events)


def test_revision_draft_is_not_exported_as_submitted(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    save(storage)
    storage.save_utterance(
        coder="coder_1",
        partition="calibration",
        utterance_id="u1",
        dispute_id="D1",
        payload={"KS_present": 1},
        answered_fields={"KS_present"},
        submit=False,
        schema_version="0.9.7",
        schema_hash="abc",
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )
    current = storage.current_utterance("coder_1", "calibration", "u1")
    assert current["status"] == "draft"
    assert current["revision_number"] == 2
    event, revision = storage.save_utterance(
        coder="coder_1",
        partition="calibration",
        utterance_id="u1",
        dispute_id="D1",
        payload={"KS_present": 1},
        answered_fields={"KS_present"},
        submit=True,
        schema_version="0.9.7",
        schema_hash="abc",
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )
    assert (event, revision) == ("revise", 3)


def test_dispute_completion_export_propagation_and_isolation(tmp_path, synthetic_project):
    storage = Storage(tmp_path / "db.sqlite")
    storage.register_schema("0.9.7", "abc", "codebook.xlsx")
    save(storage)
    save(storage, coder="other_1", uid="u2")
    storage.save_dispute(
        coder="coder_1",
        partition="calibration",
        dispute_id="D1",
        payload={"C_primary_dispute_object": "wording_framing", "review_flag": 0},
        answered_fields={"C_primary_dispute_object", "review_flag"},
        schema_version="0.9.7",
        schema_hash="abc",
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )
    data = build_export(storage, read_gold(synthetic_project.gold_path), "coder_1", "PASS")
    workbook = pd.ExcelFile(BytesIO(data))
    assert set(
        [
            "Calibration_Annotations",
            "Heldout_Annotations",
            "Dispute_Annotations",
            "Annotation_Events",
            "Dispute_Events",
            "Schema_Versions",
            "QC_Report",
        ]
    ) <= set(workbook.sheet_names)
    frame = pd.read_excel(BytesIO(data), sheet_name="Calibration_Annotations")
    row = frame[frame.utterance_id == "u1"].iloc[0]
    assert row.C_primary_dispute_object == "wording_framing"
    assert row.KI_upstream_utterance_ids == "a;prior"
    assert pd.isna(row.KS_evidence_type)
    events = pd.read_excel(BytesIO(data), sheet_name="Annotation_Events")
    assert set(events.coder_id) == {"coder_1"}


def test_backup_is_consistent(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    save(storage)
    assert storage.backup_bytes().startswith(b"SQLite format 3")
