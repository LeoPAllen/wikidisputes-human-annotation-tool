from io import BytesIO
import pandas as pd
import pytest

from wikidisputes_ui.export import build_export
from wikidisputes_ui.ingest import read_gold
from wikidisputes_ui.storage import MigrationError, SchemaDriftError, Storage


def save(storage, coder="coder_1", uid="u1", payload=None):
    storage.set_active_coder(coder)
    return storage.save_utterance(
        coder=coder,
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
    current = storage.current_utterance("coder_1", "u1")
    assert current["status"] == "draft"
    assert current["revision_number"] == 2
    event, revision = storage.save_utterance(
        coder="coder_1",
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
        dispute_id="D1",
        payload={"C_primary_dispute_object": "wording_or_framing", "review_flag": 0},
        answered_fields={"C_primary_dispute_object", "review_flag"},
        schema_version="0.9.7",
        schema_hash="abc",
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )
    data = build_export(storage, read_gold(synthetic_project.gold_path), "coder_1", "PASS", "0.9.7", "abc")
    workbook = pd.ExcelFile(BytesIO(data))
    assert set(
        [
            "Gold_Annotations",
            "Dispute_Annotations",
            "Annotation_Events",
            "Dispute_Events",
            "Schema_Versions",
            "QC_Report",
        ]
    ) <= set(workbook.sheet_names)
    frame = pd.read_excel(BytesIO(data), sheet_name="Gold_Annotations")
    row = frame[frame.utterance_id == "u1"].iloc[0]
    assert row.C_primary_dispute_object == "wording_or_framing"
    assert row.KI_upstream_utterance_ids == "a;prior"
    assert pd.isna(row.KS_evidence_type)
    context = frame[frame.utterance_role == "context"].iloc[0]
    assert pd.isna(context.coder_id) and pd.isna(context.KS_present)
    events = pd.read_excel(BytesIO(data), sheet_name="Annotation_Events")
    assert set(events.coder_id) == {"coder_1"}
    for sheet in workbook.sheet_names:
        columns = {str(column).casefold() for column in pd.read_excel(BytesIO(data), sheet_name=sheet, nrows=0).columns}
        assert not columns & {"partition", "phase", "split", "dataset_key", "source_namespace"}


def test_export_filters_current_projections_to_active_schema(tmp_path, synthetic_project):
    storage = Storage(tmp_path / "db.sqlite")
    save(storage)
    data = build_export(storage, read_gold(synthetic_project.gold_path), "coder_1", "PASS", "0.9.82", "new")
    annotations = pd.read_excel(BytesIO(data), sheet_name="Gold_Annotations")
    row = annotations[annotations.utterance_id == "u1"].iloc[0]
    assert pd.isna(row.coder_id)
    assert {"KS_argument_strength", "KI_prior_knowledge", "C_off_topic_shift"} <= set(annotations.columns)
    events = pd.read_excel(BytesIO(data), sheet_name="Annotation_Events")
    assert list(events.schema_version) == ["0.9.7"]


def test_backup_is_consistent(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    save(storage)
    assert storage.backup_bytes().startswith(b"SQLite format 3")


def test_schema_has_no_obsolete_column(tmp_path):
    import sqlite3

    storage = Storage(tmp_path / "db.sqlite")
    with sqlite3.connect(storage.path) as db:
        for table in (
            "utterance_annotations",
            "utterance_annotation_events",
            "dispute_annotations",
            "dispute_annotation_events",
        ):
            columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            assert "partition" not in columns


def test_populated_legacy_migration_preserves_rows_and_backs_up(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE coders(coder_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,active INTEGER NOT NULL);
        CREATE TABLE schema_versions(schema_version TEXT,file_hash TEXT,source_filename TEXT,registered_at TEXT,PRIMARY KEY(schema_version,file_hash));
        CREATE TABLE utterance_annotations(coder_id TEXT,partition TEXT,utterance_id TEXT,dispute_id TEXT,status TEXT,payload_json TEXT,answered_fields_json TEXT,schema_version TEXT,schema_hash TEXT,opened_at TEXT,saved_at TEXT,elapsed_wall_seconds REAL,revision_number INTEGER,PRIMARY KEY(coder_id,partition,utterance_id));
        CREATE TABLE utterance_annotation_events(event_id TEXT PRIMARY KEY,coder_id TEXT,partition TEXT,utterance_id TEXT,dispute_id TEXT,event_type TEXT,payload_json TEXT,answered_fields_json TEXT,schema_version TEXT,schema_hash TEXT,opened_at TEXT,saved_at TEXT,elapsed_wall_seconds REAL,revision_number INTEGER,app_version TEXT);
        CREATE TABLE dispute_annotations(coder_id TEXT,partition TEXT,dispute_id TEXT,payload_json TEXT,schema_version TEXT,schema_hash TEXT,opened_at TEXT,saved_at TEXT,elapsed_wall_seconds REAL,revision_number INTEGER,PRIMARY KEY(coder_id,partition,dispute_id));
        CREATE TABLE dispute_annotation_events(event_id TEXT PRIMARY KEY,coder_id TEXT,partition TEXT,dispute_id TEXT,event_type TEXT,payload_json TEXT,answered_fields_json TEXT,schema_version TEXT,schema_hash TEXT,opened_at TEXT,saved_at TEXT,elapsed_wall_seconds REAL,revision_number INTEGER,app_version TEXT);
        INSERT INTO coders VALUES('coder_1','2020-01-01T00:00:00Z',1);
        INSERT INTO utterance_annotations VALUES('coder_1','old','u1','D1','submitted','{}','[]','0.9.7','abc','2020-01-01T00:00:00Z','2020-01-01T00:00:01Z',1,1);
        INSERT INTO utterance_annotation_events VALUES('e1','coder_1','old','u1','D1','submit','{}','[]','0.9.7','abc','2020-01-01T00:00:00Z','2020-01-01T00:00:01Z',1,1,'0.1');
        """)
    storage = Storage(path)
    assert storage.current_utterance("coder_1", "u1")["revision_number"] == 1
    assert storage.rows("utterance_annotation_events")[0]["event_id"] == "e1"
    assert storage.migration_backup and storage.migration_backup.exists()


def test_legacy_migration_collision_is_non_destructive(tmp_path):
    import hashlib
    import sqlite3

    path = tmp_path / "collision.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE coders(coder_id TEXT PRIMARY KEY,created_at TEXT NOT NULL,active INTEGER NOT NULL);
        CREATE TABLE schema_versions(schema_version TEXT,file_hash TEXT,source_filename TEXT,registered_at TEXT,PRIMARY KEY(schema_version,file_hash));
        CREATE TABLE utterance_annotations(coder_id TEXT,partition TEXT,utterance_id TEXT,dispute_id TEXT,status TEXT,payload_json TEXT,answered_fields_json TEXT,schema_version TEXT,schema_hash TEXT,opened_at TEXT,saved_at TEXT,elapsed_wall_seconds REAL,revision_number INTEGER,PRIMARY KEY(coder_id,partition,utterance_id));
        CREATE TABLE utterance_annotation_events(event_id TEXT PRIMARY KEY,coder_id TEXT,partition TEXT,utterance_id TEXT,dispute_id TEXT,event_type TEXT,payload_json TEXT,answered_fields_json TEXT,schema_version TEXT,schema_hash TEXT,opened_at TEXT,saved_at TEXT,elapsed_wall_seconds REAL,revision_number INTEGER,app_version TEXT);
        CREATE TABLE dispute_annotations(coder_id TEXT,partition TEXT,dispute_id TEXT,payload_json TEXT,schema_version TEXT,schema_hash TEXT,opened_at TEXT,saved_at TEXT,elapsed_wall_seconds REAL,revision_number INTEGER,PRIMARY KEY(coder_id,partition,dispute_id));
        CREATE TABLE dispute_annotation_events(event_id TEXT PRIMARY KEY,coder_id TEXT,partition TEXT,dispute_id TEXT,event_type TEXT,payload_json TEXT,answered_fields_json TEXT,schema_version TEXT,schema_hash TEXT,opened_at TEXT,saved_at TEXT,elapsed_wall_seconds REAL,revision_number INTEGER,app_version TEXT);
        INSERT INTO utterance_annotations VALUES('coder_1','a','u1','D1','submitted','{}','[]','v','h','t','t',1,1);
        INSERT INTO utterance_annotations VALUES('coder_1','b','u1','D1','submitted','{}','[]','v','h','t','t',1,1);
        """)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(MigrationError, match="coder='coder_1'.*utterance_id='u1'"):
        Storage(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not list(tmp_path.glob("*.pre-unified-*.bak"))
