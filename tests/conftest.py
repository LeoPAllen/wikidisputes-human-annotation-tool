from pathlib import Path

import pandas as pd
import pytest

from wikidisputes_ui.config import ProjectConfig
from wikidisputes_ui.ingest import ANNOTATION_COLUMNS


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
def synthetic_project(tmp_path: Path, source_rows):
    unified = source_rows
    gold = tmp_path / "gold.xlsx"
    with pd.ExcelWriter(gold, engine="openpyxl") as writer:
        unified.to_excel(writer, sheet_name="Gold_Annotation", index=False)
    codebook = Path("data/source/codebook.xlsx").resolve()
    return ProjectConfig(
        tmp_path,
        gold,
        codebook,
        tmp_path / "db.sqlite3",
        tmp_path / "exports",
        "0.9.7",
        "Core_Schema_SIMPLIFIED",
        "Gold_Annotation",
        False,
        2,
    )
