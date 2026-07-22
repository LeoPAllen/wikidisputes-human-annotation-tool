import pandas as pd
from hashlib import sha256
from pathlib import Path

from wikidisputes_ui.config import load_config
from wikidisputes_ui.ingest import read_gold
from wikidisputes_ui.validation import validate_inputs


def test_valid_fixture_roles_and_strict_past(synthetic_project):
    result = validate_inputs(synthetic_project)
    assert not result.errors
    assert any("later utterance_order" in warning for warning in result.warnings)
    data = read_gold(synthetic_project.gold_path)
    assert list(data.annotatable_rows.utterance_id) == ["u1", "u2"]
    assert list(data.context_rows.utterance_id) == ["ctx1"]
    assert list(data.displayable_prior_context("D1", 2).utterance_id) == ["ctx1"]
    assert list(data.earlier_annotatable_turns("D1", 2).utterance_id) == []
    assert "Reply" not in " ".join(data.displayable_prior_context("D1", 2).utterance_text)


def test_qc_missing_reply_and_role_errors_block(synthetic_project, source_rows):
    frame = source_rows.copy()
    frame.loc[2, "reply_to_utterance_id"] = "missing"
    frame.loc[0, "utterance_role"] = "heading"
    with pd.ExcelWriter(synthetic_project.gold_path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Gold_Annotation", index=False)
    result = validate_inputs(synthetic_project)
    joined = "\n".join(result.errors)
    assert "not in dispute" in joined
    assert "exactly context or utterance" in joined


def test_cross_dispute_reply_blocks(synthetic_project, source_rows):
    other = source_rows.iloc[[0, 1]].copy()
    other["dispute_sequence"] = 2
    other["dispute_id"] = "D2"
    other["utterance_id"] = ["ctx2", "d2u1"]
    other["reply_to_utterance_id"] = None
    frame = pd.concat([source_rows, other], ignore_index=True)
    frame.loc[1, "reply_to_utterance_id"] = "d2u1"
    with pd.ExcelWriter(synthetic_project.gold_path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Gold_Annotation", index=False)
    result = validate_inputs(synthetic_project)
    assert result.blocking
    assert any("not in dispute D1" in error for error in result.errors)


def test_real_workbook_passes_and_has_authoritative_counts():
    result = validate_inputs(load_config())
    assert not result.blocking
    data = read_gold("data/source/gold_input.xlsx")
    assert (len(data.source_rows), len(data.annotatable_rows), len(data.context_rows)) == (438, 404, 34)
    assert data.source_rows.dispute_id.nunique() == 34
    assert any("later utterance_order" in warning for warning in result.warnings)
    assert sha256(Path("data/source/gold_input.xlsx").read_bytes()).hexdigest() == (
        "2dc07f98ac7832a4099adad0866e68d82fb3cb2f76400760a9305799884ec9d6"
    )
