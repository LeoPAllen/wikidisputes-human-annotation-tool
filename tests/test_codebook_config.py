import pandas as pd
import pytest

from wikidisputes_ui.codebook import EXPECTED_DISPUTE_OBJECTS, EXPECTED_LABELS, load_codebook
from wikidisputes_ui.config import load_config


def test_authoritative_one_sheet_codebook():
    book = load_codebook("data/source/codebook.xlsx")
    assert tuple(book.fields) == EXPECTED_LABELS
    assert tuple(book.dispute_objects) == EXPECTED_DISPUTE_OBJECTS
    assert "binary {0,1}" in book.fields["KI_compromise_position"].indicator
    assert book.fields["KS_restaking"].example_provenance


def test_missing_duplicate_and_unexpected_labels_are_rejected(tmp_path):
    source = pd.read_excel("data/source/codebook.xlsx", sheet_name="Core_Schema")
    for name, frame in {
        "missing": source.iloc[:-1],
        "duplicate": pd.concat([source, source.iloc[[0]]], ignore_index=True),
        "unexpected": source.assign(Label=[*source.Label.iloc[:-1], "unexpected"]),
    }.items():
        path = tmp_path / f"{name}.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            frame.to_excel(writer, sheet_name="Core_Schema", index=False)
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
