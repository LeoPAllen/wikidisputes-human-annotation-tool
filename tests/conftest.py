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
    calibration = pd.DataFrame(
        [
            [1, "D1", 1, "u1", "A", "2020-01-01", None, "utterance", "Article", "First proposal", None, None, None],
            [1, "D1", 2, "u2", "B", "2020-01-02", "u1", "utterance", "Article", "Reply", None, None, None],
            [1, "D1", 3, "u3", "A", "2020-01-03", "u2", "utterance", "Article", "Final", None, None, None],
        ],
        columns=columns,
    )
    heldout = pd.DataFrame(
        [
            [2, "D2", 1, "h1", "C", "2020-02-01", None, "utterance", "Other", "Heldout", None, None, None],
        ],
        columns=columns,
    )
    for frame in (calibration, heldout):
        for column in ANNOTATION_COLUMNS - set(frame.columns):
            frame[column] = None
    return calibration, heldout


@pytest.fixture
def synthetic_project(tmp_path: Path, source_rows):
    calibration, heldout = source_rows
    gold = tmp_path / "gold.xlsx"
    with pd.ExcelWriter(gold, engine="openpyxl") as writer:
        calibration.to_excel(writer, sheet_name="3_Calibration_Coder", index=False)
        heldout.to_excel(writer, sheet_name="4_Heldout_Coder", index=False)
    codebook = Path("data/source/codebook.xlsx").resolve()
    return ProjectConfig(
        tmp_path,
        gold,
        codebook,
        tmp_path / "db.sqlite3",
        tmp_path / "exports",
        "0.9.7",
        "Core_Schema_SIMPLIFIED",
        "calibration",
        False,
        2,
    )
