from wikidisputes_ui.codebook import EXPECTED_LABELS, file_fingerprint, load_codebook, schema_id
from wikidisputes_ui.config import load_config


def test_authoritative_codebook_and_controlled_values():
    book = load_codebook("data/source/codebook.xlsx")
    assert EXPECTED_LABELS == set(book.fields)
    assert "external_source_or_quote" in book.evidence_types
    assert "wording_or_framing" in book.dispute_objects
    assert "0,1,2" in book.fields["KS_argument_strength"].indicator.replace(" ", "")
    assert len(book.file_hash) == 64
    assert schema_id(book.file_hash) == f"schema-{book.file_hash[:12]}"


def test_config_uses_one_annotation_sheet(tmp_path):
    path = tmp_path / "project.toml"
    path.write_text(
        """schema_sheet="Core_Schema_SIMPLIFIED"\nannotation_sheet="Gold_Annotation"\nschema_locked=false\nlow_confidence_threshold=2\ngold_path="g.xlsx"\ncodebook_path="c.xlsx"\ndatabase_path="d.sqlite"\nexport_directory="exports"\n"""
    )
    assert load_config(path).annotation_sheet == "Gold_Annotation"


def test_file_fingerprint_changes_with_authoritative_input(tmp_path):
    path = tmp_path / "codebook.xlsx"
    path.write_bytes(b"first")
    first = file_fingerprint(path)
    path.write_bytes(b"second")
    assert file_fingerprint(path) != first
