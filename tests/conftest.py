from pathlib import Path

import pandas as pd
import pytest

from wikidisputes_ui.config import ProjectConfig
from wikidisputes_ui.codebook import EXPECTED_DISPUTE_OBJECTS, EXPECTED_LABELS
from wikidisputes_ui.ingest import ANNOTATION_COLUMNS

QUESTIONS = {
    "KS_present": "Does this utterance stake knowledge?",
    "KS_explicit_reasoning": "Does it make its reasoning explicit?",
    "KS_grounding": "Does it ground its position?",
    "KS_new_evidence": "Does it introduce new evidence?",
    "KS_restaking": "Does it restate an earlier position?",
    "KS_bounding": "Does it bound the claim?",
    "KI_present": "Does this utterance integrate knowledge?",
    "C_off_topic_shift": "Does this shift off topic?",
    "C_interpersonal_attack_or_disrespect": "Does this attack or disrespect a contributor?",
    "C_formal_governance_action": "Does this invoke formal governance?",
    "C_primary_dispute_object": "Which object primarily organizes this dispute?",
    "DV_dispute_resolution": "How resolved is this dispute?",
}


@pytest.fixture
def codebook_frame():
    rows = []
    for label in EXPECTED_LABELS:
        indicator = "binary {0,1}"
        rule = f"Coding rule for {label}."
        if label in {"KS_explicit_reasoning", "KS_grounding", "KS_restaking", "KS_bounding"}:
            indicator += "; null if KS_present=0"
        if label == "KS_new_evidence":
            indicator += "; null if KS_grounding=0"
        if label == "C_primary_dispute_object":
            indicator = "single-label enum {" + ", ".join(EXPECTED_DISPUTE_OBJECTS) + "}; dispute-level"
            rule = "\n".join(f"• {value}: Description for {value}." for value in EXPECTED_DISPUTE_OBJECTS[:-1])
        if label == "DV_dispute_resolution":
            indicator = "ordinal {1,2,3,4,5}; dispute-level"
        rows.append(
            {
                "Family": "Dispute Context" if label == "C_primary_dispute_object" else "Synthetic",
                "Label": label,
                "Indicator": indicator,
                "Definition": f"Definition for {label}.",
                "Coding rule": rule,
                "Example (verbatim excerpt + explanation)": f"Example for {label}.",
                "Example provenance (WikiDisputes; stable identifiers where available)": "Synthetic fixture",
                "Question": QUESTIONS[label],
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def source_rows():
    columns = [
        "dispute_sequence",
        "dispute_id",
        "utterance_order",
        "utterance_id",
        "speaker_id",
        "timestamp",
        "reply_to_utterance_id",
        "utterance_type",
        "article_title",
        "utterance_text",
        "KS_present",
        "KI_present",
        "C_primary_dispute_object",
    ]
    unified = pd.DataFrame(
        [
            [
                1,
                "D1",
                1,
                "ctx1",
                "",
                "2020-01-01",
                None,
                "context",
                "Article",
                "Conversation heading",
                None,
                None,
                None,
            ],
            [1, "D1", 2, "u1", "A", "2020-01-02", "u2", "utterance", "Article", "First proposal", None, None, None],
            [1, "D1", 3, "u2", "B", "2020-01-03", "u1", "utterance", "Article", "Reply", None, None, None],
        ],
        columns=columns,
    )
    unified.insert(3, "utterance_role", unified.pop("utterance_type"))
    unified["utterance_type"] = "talk"
    for column in ANNOTATION_COLUMNS - set(unified.columns):
        unified[column] = None
    return unified


@pytest.fixture
def synthetic_project(tmp_path: Path, source_rows, codebook_frame):
    unified = source_rows
    gold = tmp_path / "gold.xlsx"
    with pd.ExcelWriter(gold, engine="openpyxl") as writer:
        unified.to_excel(writer, sheet_name="Gold_Annotation", index=False)
    codebook = tmp_path / "codebook.xlsx"
    with pd.ExcelWriter(codebook, engine="openpyxl") as writer:
        codebook_frame.to_excel(writer, sheet_name="Core_Schema", index=False)
    return ProjectConfig(
        root=tmp_path,
        gold_path=gold,
        codebook_path=codebook,
        database_path=tmp_path / "db.sqlite3",
        export_directory=tmp_path / "exports",
        schema_sheet="Core_Schema",
        annotation_sheet="Gold_Annotation",
        schema_locked=False,
        low_confidence_threshold=2,
    )
