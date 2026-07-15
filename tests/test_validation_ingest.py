import pandas as pd

from wikidisputes_ui.ingest import read_gold
from wikidisputes_ui.validation import validate_inputs


def test_valid_fixture_and_strict_past(synthetic_project):
    result = validate_inputs(synthetic_project)
    assert not result.errors
    data = read_gold(synthetic_project.gold_path)
    past = data.prior_context("calibration", "D1", 2)
    assert list(past.utterance_id) == ["u1"]
    # Reopening an earlier turn never reveals already-coded future turns.
    assert list(data.prior_context("calibration", "D1", 1).utterance_id) == []


def test_qc_duplicate_order_reply_overlap_and_warning(synthetic_project, source_rows):
    calibration, heldout = source_rows
    calibration.loc[1, "utterance_id"] = "u1"
    calibration.loc[2, "utterance_order"] = 4
    calibration.loc[2, "reply_to_utterance_id"] = "missing"
    calibration.loc[2, "utterance_text"] = calibration.loc[0, "utterance_text"].upper()
    heldout.loc[0, "dispute_id"] = "D1"
    with pd.ExcelWriter(synthetic_project.gold_path, engine="openpyxl") as writer:
        calibration.to_excel(writer, sheet_name="3_Calibration_Coder", index=False)
        heldout.to_excel(writer, sheet_name="4_Heldout_Coder", index=False)
    result = validate_inputs(synthetic_project)
    joined = "\n".join(result.errors)
    assert "duplicate utterance_id" in joined
    assert "gap-free" in joined
    assert "not in dispute" in joined
    assert "overlap" in joined
    assert any("repeated text" in warning for warning in result.warnings)


def test_real_workbook_reports_missing_partition_sheets():
    from wikidisputes_ui.config import load_config

    result = validate_inputs(load_config())
    assert result.blocking
    assert any("3_Calibration_Coder" in error for error in result.errors)
    assert any("4_Heldout_Coder" in error for error in result.errors)
