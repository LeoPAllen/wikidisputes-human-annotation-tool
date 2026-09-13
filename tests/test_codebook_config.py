import pandas as pd
import pytest

from wikidisputes_ui.codebook import EXPECTED_DISPUTE_OBJECTS, EXPECTED_LABELS, load_codebook
from wikidisputes_ui.config import load_config


def write_codebook(path, frame):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Core_Schema", index=False)


def test_authoritative_one_sheet_codebook(tmp_path, codebook_frame):
    path = tmp_path / "codebook.xlsx"
    write_codebook(path, codebook_frame)
    book = load_codebook(path)
    assert tuple(book.fields) == EXPECTED_LABELS
    assert tuple(book.dispute_objects) == EXPECTED_DISPUTE_OBJECTS
    assert "binary {0,1}" in book.fields["KI_present"].indicator
    assert book.fields["KS_restaking"].definition
    assert book.fields["KS_restaking"].rule
    assert book.fields["KS_restaking"].question == "Does it restate an earlier position?"
    assert book.dispute_objects["uncertain"] == ""


def test_missing_duplicate_and_unexpected_labels_are_rejected(tmp_path, codebook_frame):
    source = codebook_frame
    for name, frame in {
        "missing": source.iloc[:-1],
        "duplicate": pd.concat([source, source.iloc[[0]]], ignore_index=True),
        "unexpected": source.assign(Label=[*source.Label.iloc[:-1], "unexpected"]),
    }.items():
        path = tmp_path / f"{name}.xlsx"
        write_codebook(path, frame)
        with pytest.raises(ValueError):
            load_codebook(path)


def test_unexpected_codebook_column_is_rejected(tmp_path, codebook_frame):
    path = tmp_path / "extra-column.xlsx"
    write_codebook(path, codebook_frame.assign(extra="unexpected"))
    with pytest.raises(ValueError, match="columns must exactly match"):
        load_codebook(path)


@pytest.mark.parametrize("question", [None, "   "])
def test_missing_or_blank_question_is_rejected(tmp_path, codebook_frame, question):
    frame = codebook_frame.copy()
    frame.loc[0, "Question"] = question
    path = tmp_path / "bad-question.xlsx"
    write_codebook(path, frame)
    with pytest.raises(ValueError, match="questions must be nonblank"):
        load_codebook(path)


def test_unknown_dispute_object_enum_and_bullet_keys_are_rejected(tmp_path, codebook_frame):
    object_row = codebook_frame.Label == "C_primary_dispute_object"
    for name, change in {
        "enum": ("Indicator", "single-label enum {claim_or_evidence_validity, bogus}"),
        "bullet": ("Coding rule", "• bogus: Not an allowed object."),
    }.items():
        frame = codebook_frame.copy()
        column, value = change
        frame.loc[object_row, column] = value
        path = tmp_path / f"bad-{name}.xlsx"
        write_codebook(path, frame)
        with pytest.raises(ValueError):
            load_codebook(path)


def test_config_uses_core_schema(tmp_path):
    path = tmp_path / "project.toml"
    path.write_text(
        'schema_sheet="Core_Schema"\nannotation_sheet="Gold_Annotation"\nschema_locked=false\n'
        'low_confidence_threshold=2\ngold_path="g.xlsx"\ncodebook_path="c.xlsx"\n'
        'database_path="d.sqlite"\nexport_directory="exports"\n'
    )
    assert load_config(path).schema_sheet == "Core_Schema"
