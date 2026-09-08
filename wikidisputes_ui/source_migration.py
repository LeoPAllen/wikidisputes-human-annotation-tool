"""Reconcile mutable annotation projections to stable Gold keys."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pandas as pd

from .ingest import Dataset, stable_annotation_key
from .storage import Storage


def _aliases(row: pd.Series) -> set[str]:
    aliases = {stable_annotation_key(row)}
    for name in ("logical_utterance_uid", "original_utterance_id", "utterance_id"):
        value = row.get(name)
        if value is not None and not pd.isna(value) and str(value).strip():
            aliases.add(str(value).strip())
    return aliases


def _winner(rows: list[dict[str, Any]]) -> dict[str, Any]:
    submitted = [row for row in rows if row["status"] in {"submitted", "needs_rereview"}]
    candidates = submitted or rows
    winner = max(candidates, key=lambda row: (str(row["saved_at"]), int(row["revision_number"])))
    winner = dict(winner)
    if winner["status"] == "needs_rereview":
        winner["status"] = "submitted"
    winner["revision_number"] = max(int(row["revision_number"]) for row in rows)
    return winner


def reconcile_annotation_keys(storage: Storage, dataset: Dataset) -> None:
    """Move current rows from source IDs to stable keys without touching history."""
    alias_to_key: dict[str, str] = {}
    key_to_dispute: dict[str, str] = {}
    for _, source_row in dataset.annotatable_rows.iterrows():
        key = stable_annotation_key(source_row)
        key_to_dispute[key] = str(source_row["dispute_id"])
        for alias in _aliases(source_row):
            alias_to_key[alias] = key

    with storage.connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM utterance_annotations").fetchall()]
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            target = alias_to_key.get(str(row["utterance_id"]))
            if target is not None:
                grouped[(str(row["coder_id"]), target)].append(row)

        for (coder, target), matches in grouped.items():
            winner = _winner(matches)
            unchanged = (
                len(matches) == 1
                and str(winner["utterance_id"]) == target
                and winner["status"] == matches[0]["status"]
                and str(winner["dispute_id"]) == key_to_dispute[target]
            )
            if unchanged:
                continue
            source_ids = [str(row["utterance_id"]) for row in matches]
            placeholders = ",".join("?" for _ in source_ids)
            db.execute(
                f"DELETE FROM utterance_annotations WHERE coder_id=? AND utterance_id IN ({placeholders})",  # noqa: S608
                (coder, *source_ids),
            )
            winner["utterance_id"] = target
            winner["dispute_id"] = key_to_dispute[target]
            columns = (
                "coder_id",
                "utterance_id",
                "dispute_id",
                "status",
                "payload_json",
                "answered_fields_json",
                "schema_version",
                "schema_hash",
                "opened_at",
                "saved_at",
                "elapsed_wall_seconds",
                "revision_number",
            )
            db.execute(
                f"INSERT INTO utterance_annotations ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",  # noqa: S608
                tuple(winner[column] for column in columns),
            )
