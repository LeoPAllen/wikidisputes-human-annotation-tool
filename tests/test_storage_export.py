from io import BytesIO
import pandas as pd
import pytest

from wikidisputes_ui.codebook import load_codebook
from wikidisputes_ui.export import build_export
from wikidisputes_ui.ingest import Dataset, read_gold
from wikidisputes_ui.storage import MigrationError, Storage


def current_payload(**changes):
    payload = {
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
        "coder_confidence": 3,
        "review_flag": 0,
        "coder_notes": None,
    }
    payload.update(changes)
    return payload


def save(storage, coder="coder_1", uid="u1", payload=None):
    storage.set_active_coder(coder)
    return storage.save_utterance(
        coder=coder,
        utterance_id=uid,
        dispute_id="D1",
        payload=current_payload() if payload is None else payload,
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
    storage.register_schema("0.9.7", "changed", "codebook.xlsx")
    assert save(storage) == ("submit", 1)
    assert save(storage) == ("unchanged", 1)
    assert save(storage, payload={"KS_present": 1}) == ("revise", 2)
    events = storage.rows("utterance_annotation_events", "coder_1")
    assert [row["revision_number"] for row in events] == [1, 2]
    assert all(row["saved_at"].endswith("Z") and row["elapsed_wall_seconds"] >= 0 for row in events)


def test_identical_answers_are_revised_when_schema_changes(tmp_path):
    storage = Storage(tmp_path / "db.sqlite")
    payload = current_payload()
    assert save(storage, payload=payload) == ("submit", 1)

    utterance_event = storage.save_utterance(
        coder="coder_1",
        utterance_id="u1",
        dispute_id="D1",
        payload=payload,
        answered_fields={"KS_present"},
        submit=True,
        schema_version="1.0.0",
        schema_hash="new-schema",
        opened_at="2020-01-02T00:00:00Z",
        elapsed_wall_seconds=1,
    )
    assert utterance_event == ("revise", 2)
    assert storage.current_utterance("coder_1", "u1")["schema_hash"] == "new-schema"

    dispute_payload = {"C_primary_dispute_object": "wording_or_representation"}
    storage.save_dispute(
        coder="coder_1",
        dispute_id="D1",
        payload=dispute_payload,
        answered_fields={"C_primary_dispute_object"},
        schema_version="0.9.7",
        schema_hash="abc",
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )
    dispute_event = storage.save_dispute(
        coder="coder_1",
        dispute_id="D1",
        payload=dispute_payload,
        answered_fields={"C_primary_dispute_object"},
        schema_version="1.0.0",
        schema_hash="new-schema",
        opened_at="2020-01-02T00:00:00Z",
        elapsed_wall_seconds=1,
    )
    assert dispute_event == ("revise", 2)
    current_dispute = storage.rows("dispute_annotations", "coder_1")[0]
    assert current_dispute["schema_hash"] == "new-schema"


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
        payload={"C_primary_dispute_object": "wording_or_representation", "DV_dispute_resolution": 4},
        answered_fields={"C_primary_dispute_object", "DV_dispute_resolution"},
        schema_version="dispute-v2",
        schema_hash="dispute-hash",
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )
    book = load_codebook(synthetic_project.codebook_path)
    data = build_export(
        storage,
        read_gold(synthetic_project.gold_path),
        "coder_1",
        "0.9.7",
        "abc",
        tuple(book.fields),
        tuple(book.dispute_objects),
    )
    workbook = pd.ExcelFile(BytesIO(data))
    assert workbook.sheet_names == ["Gold_Annotations", "Dispute_Annotations"]
    frame = pd.read_excel(BytesIO(data), sheet_name="Gold_Annotations")
    row = frame[frame.utterance_id == "u1"].iloc[0]
    assert row.C_primary_dispute_object == "wording_or_representation"
    assert row.DV_dispute_resolution == 4
    assert pd.isna(row.KS_new_evidence)
    assert "KI_prior_knowledge_utterance_ids" not in frame.columns
    assert pd.isna(row.KS_explicit_reasoning)
    assert set(frame.utterance_id) == {"u1"}
    assert set(book.fields) <= set(frame.columns)
    assert set(frame.export_schema_id) == {"0.9.7"}
    assert set(frame.export_schema_hash) == {"abc"}
    dispute_row = pd.read_excel(BytesIO(data), sheet_name="Dispute_Annotations").iloc[0]
    saved_dispute = storage.rows("dispute_annotations", "coder_1")[0]
    assert dispute_row.dispute_id == "D1"
    assert dispute_row.C_primary_dispute_object == "wording_or_representation"
    assert dispute_row.DV_dispute_resolution == 4
    assert dispute_row.coder_id == "coder_1"
    assert dispute_row.schema_version == "dispute-v2"
    assert dispute_row.schema_hash == "dispute-hash"
    assert dispute_row.saved_at == saved_dispute["saved_at"]
    assert dispute_row.revision_number == 1
    assert row.schema_version == "0.9.7"
    assert row.schema_hash == "abc"
    for sheet in workbook.sheet_names:
        columns = {str(column).casefold() for column in pd.read_excel(BytesIO(data), sheet_name=sheet, nrows=0).columns}
        assert not columns & {"partition", "phase", "split", "dataset_key", "source_namespace"}


def test_export_preserves_compatible_annotation_from_older_schema(tmp_path, synthetic_project):
    storage = Storage(tmp_path / "db.sqlite")
    save(storage)
    book = load_codebook(synthetic_project.codebook_path)
    data = build_export(
        storage,
        read_gold(synthetic_project.gold_path),
        "coder_1",
        "0.9.82",
        "new-question-only-hash",
        tuple(book.fields),
        tuple(book.dispute_objects),
    )
    workbook = pd.ExcelFile(BytesIO(data))
    assert workbook.sheet_names == ["Gold_Annotations", "Dispute_Annotations"]
    annotations = pd.read_excel(BytesIO(data), sheet_name="Gold_Annotations")
    assert list(annotations["utterance_id"]) == ["u1"]
    assert {
        "KS_restaking",
        "KS_explicit_reasoning",
        "KS_grounding",
        "KS_bounding",
        "C_off_topic_shift",
    } <= set(annotations.columns)
    assert annotations.loc[0, "schema_hash"] == "abc"
    unannotated_dispute = pd.read_excel(BytesIO(data), sheet_name="Dispute_Annotations").iloc[0]
    assert unannotated_dispute.dispute_id == "D1"
    assert pd.isna(unannotated_dispute.schema_hash)
    assert "KI_evidence_span" not in annotations.columns
    assert "control_evidence_span" not in annotations.columns
    assert not any("candidate" in str(column).lower() for column in annotations.columns)


def test_dispute_sheet_has_one_row_per_source_dispute(tmp_path, synthetic_project, source_rows):
    storage = Storage(tmp_path / "db.sqlite")
    save(storage)
    second = source_rows[source_rows.utterance_id == "u2"].copy()
    second["dispute_id"] = "D2"
    second["utterance_id"] = "u3"
    dataset = Dataset(pd.concat([source_rows, second], ignore_index=True))
    book = load_codebook(synthetic_project.codebook_path)
    data = build_export(storage, dataset, "coder_1", "new", "new-hash", tuple(book.fields), tuple(book.dispute_objects))
    disputes = pd.read_excel(BytesIO(data), sheet_name="Dispute_Annotations")
    assert list(disputes.dispute_id) == ["D1", "D2"]
    assert disputes.schema_hash.isna().all()


def test_grounded_new_evidence_exports_as_integer(tmp_path, synthetic_project):
    storage = Storage(tmp_path / "db.sqlite")
    save(
        storage,
        payload=current_payload(
            KS_present=1,
            KS_explicit_reasoning=0,
            KS_grounding=1,
            KS_new_evidence=1,
            KS_restaking=0,
            KS_bounding=0,
        ),
    )
    book = load_codebook(synthetic_project.codebook_path)
    data = build_export(
        storage,
        read_gold(synthetic_project.gold_path),
        "coder_1",
        "new",
        "new-hash",
        tuple(book.fields),
        tuple(book.dispute_objects),
    )
    assert pd.read_excel(BytesIO(data)).iloc[0].KS_new_evidence == 1


def test_old_field_payload_is_preserved_but_not_exported(tmp_path, synthetic_project):
    storage = Storage(tmp_path / "db.sqlite")
    old_payload = {
        "KS_present": 1,
        "KS_claim_present": 1,
        "KS_evidence_reference": 0,
        "KS_reasoning": 1,
        "KS_restaking": 0,
        "KI_present": 0,
        "KI_solicit_feedback": None,
        "KI_compromise_position": None,
        "C_off_topic_shift": 0,
        "C_interpersonal_attack_or_disrespect": 0,
        "C_formal_governance_action": 0,
    }
    save(storage, payload=old_payload)
    book = load_codebook(synthetic_project.codebook_path)
    data = build_export(
        storage,
        read_gold(synthetic_project.gold_path),
        "coder_1",
        "current",
        "current-hash",
        tuple(book.fields),
        tuple(book.dispute_objects),
    )
    assert pd.read_excel(BytesIO(data), sheet_name="Gold_Annotations").empty
    assert storage.current_utterance("coder_1", "u1")["payload"] == old_payload


def test_obsolete_dispute_object_exports_blank(tmp_path, synthetic_project):
    storage = Storage(tmp_path / "db.sqlite")
    save(storage)
    storage.save_dispute(
        coder="coder_1",
        dispute_id="D1",
        payload={"C_primary_dispute_object": "wording_or_framing"},
        answered_fields={"C_primary_dispute_object"},
        schema_version="old",
        schema_hash="old",
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )
    book = load_codebook(synthetic_project.codebook_path)
    data = build_export(
        storage,
        read_gold(synthetic_project.gold_path),
        "coder_1",
        "current",
        "current-hash",
        tuple(book.fields),
        tuple(book.dispute_objects),
    )
    row = pd.read_excel(BytesIO(data), sheet_name="Gold_Annotations").iloc[0]
    assert pd.isna(row.C_primary_dispute_object)
    assert pd.isna(row.DV_dispute_resolution)


def test_old_dispute_record_requires_resolution_without_losing_event(tmp_path, synthetic_project):
    storage = Storage(tmp_path / "db.sqlite")
    save(storage)
    storage.save_dispute(
        coder="coder_1",
        dispute_id="D1",
        payload={"C_primary_dispute_object": "uncertain"},
        answered_fields={"C_primary_dispute_object"},
        schema_version="old",
        schema_hash="old",
        opened_at="2020-01-01T00:00:00Z",
        elapsed_wall_seconds=1,
    )
    book = load_codebook(synthetic_project.codebook_path)
    data = build_export(
        storage,
        read_gold(synthetic_project.gold_path),
        "coder_1",
        "new",
        "new-hash",
        tuple(book.fields),
        tuple(book.dispute_objects),
    )
    row = pd.read_excel(BytesIO(data)).iloc[0]
    assert pd.isna(row.C_primary_dispute_object)
    assert pd.isna(row.DV_dispute_resolution)
    saved_dispute = pd.read_excel(BytesIO(data), sheet_name="Dispute_Annotations").iloc[0]
    assert saved_dispute.C_primary_dispute_object == "uncertain"
    assert saved_dispute.schema_hash == "old"
    assert len(storage.rows("dispute_annotation_events", "coder_1")) == 1


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
