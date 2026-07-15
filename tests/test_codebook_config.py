from wikidisputes_ui.codebook import EXPECTED_LABELS, load_codebook
from wikidisputes_ui.config import load_config


def test_authoritative_codebook_and_controlled_values():
    book = load_codebook("data/source/codebook.xlsx")
    assert EXPECTED_LABELS <= set(book.fields)
    assert "external_source_or_quote" in book.evidence_types
    assert "wording_framing" in book.dispute_objects
    for name in ("KS_warrant_explicit", "KI_prior_stake_reflection"):
        assert "1,2,3,4,5" in book.fields[name].indicator.replace(" ", "")
    assert len(book.file_hash) == 64


def test_config_uses_one_annotation_sheet(tmp_path):
    path = tmp_path / "project.toml"
    path.write_text(
        """schema_version="0.9.7"\nschema_sheet="Core_Schema_SIMPLIFIED"\nannotation_sheet="Gold_Annotation"\nschema_locked=false\nlow_confidence_threshold=2\ngold_path="g.xlsx"\ncodebook_path="c.xlsx"\ndatabase_path="d.sqlite"\nexport_directory="exports"\n"""
    )
    assert load_config(path).annotation_sheet == "Gold_Annotation"
