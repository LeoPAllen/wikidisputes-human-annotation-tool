import pandas as pd

from wikidisputes_ui.ingest import read_gold
from wikidisputes_ui.validation import validate_inputs


def test_valid_fixture_roles_and_strict_past(synthetic_project):
    result = validate_inputs(synthetic_project)
    assert not result.errors
    assert any("later display order" in warning for warning in result.warnings)
    data = read_gold(synthetic_project.gold_path)
    assert list(data.annotatable_rows.utterance_id) == ["u1", "u2"]
    assert list(data.context_rows.utterance_id) == ["ctx1"]
    assert list(data.displayable_prior_context("D1", 2).utterance_id) == ["ctx1"]
    assert list(data.earlier_annotatable_turns("D1", 2).utterance_id) == []
    assert "Reply" not in " ".join(data.displayable_prior_context("D1", 2).utterance_text)


def test_qc_missing_reply_warns_while_role_error_blocks(synthetic_project, source_rows):
    frame = source_rows.copy()
    frame.loc[2, "reply_to_utterance_id"] = "missing"
    frame.loc[0, "utterance_role"] = "heading"
    with pd.ExcelWriter(synthetic_project.gold_path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Gold_Annotation", index=False)
    result = validate_inputs(synthetic_project)
    assert any("not available in this dispute" in warning for warning in result.warnings)
    assert any("exactly context or utterance" in error for error in result.errors)


def test_cross_dispute_reply_warns_and_never_exposes_target_text(synthetic_project, source_rows):
    other = source_rows.iloc[[0, 1]].copy()
    other["dispute_sequence"] = 2
    other["dispute_id"] = "D2"
    other["utterance_id"] = ["ctx2", "d2u1"]
    other["reply_to_utterance_id"] = None
    other.loc[other["utterance_id"] == "d2u1", "utterance_text"] = "OUTSIDE DISPUTE TEXT"
    frame = pd.concat([source_rows, other], ignore_index=True)
    frame.loc[1, "reply_to_utterance_id"] = "d2u1"
    frame["reply_to_utterance_id_raw"] = frame["reply_to_utterance_id"]
    with pd.ExcelWriter(synthetic_project.gold_path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Gold_Annotation", index=False)
    result = validate_inputs(synthetic_project)
    assert not result.blocking
    assert any("reply target 'd2u1' is not available in this dispute" in warning for warning in result.warnings)
    data = read_gold(synthetic_project.gold_path)
    focal = data.source_rows[data.source_rows["utterance_id"] == "u1"].iloc[0]
    assert focal["reply_to_utterance_id"] == "d2u1"
    assert focal["reply_to_utterance_id_raw"] == "d2u1"
    visible = " ".join(data.displayable_prior_context("D1", 2)["utterance_text"].astype(str))
    assert "OUTSIDE DISPUTE TEXT" not in visible


def test_substantive_order_is_canonical_and_zero_context_rows_are_valid(synthetic_project, source_rows):
    frame = source_rows[source_rows["utterance_role"] == "utterance"].copy()
    frame["utterance_order"] = None
    frame["substantive_order"] = [1, 2]
    with pd.ExcelWriter(synthetic_project.gold_path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Gold_Annotation", index=False)

    result = validate_inputs(synthetic_project)
    assert not result.blocking
    data = read_gold(synthetic_project.gold_path)
    assert data.annotatable_rows["_display_order"].tolist() == [1, 2]
    assert list(data.displayable_prior_context("D1", 2)["utterance_id"]) == ["u1"]


def test_partial_substantive_order_uses_the_complete_legacy_sequence(synthetic_project, source_rows):
    frame = source_rows.copy()
    frame["substantive_order"] = [None, 1, 2]
    with pd.ExcelWriter(synthetic_project.gold_path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Gold_Annotation", index=False)

    result = validate_inputs(synthetic_project)
    assert not result.blocking
    assert read_gold(synthetic_project.gold_path).source_rows["_display_order"].tolist() == [1, 2, 3]
