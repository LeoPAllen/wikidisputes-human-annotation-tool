"""Safely reconcile current annotation projections when Gold changes.

The event tables remain the audit record. This module only updates their current
projections after comparing a stable annotation key and the text a coder could see.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .ingest import Dataset, stable_annotation_key
from .storage import Storage


@dataclass(frozen=True)
class SourceMigrationReport:
    """A concise, non-sensitive account of a reconciliation run."""

    source_rows: int
    source_newly_annotatable: int
    source_signature_changed: int
    source_affected_disputes: int
    db_rows_rekeyed: int
    db_rows_preserved: int
    db_rows_marked_needs_rereview: int
    db_rows_stale_projections_removed: int
    db_dispute_projections_invalidated: int
    backup_path: Path | None = None

    @property
    def changed(self) -> bool:
        return bool(
            self.db_rows_rekeyed
            or self.db_rows_marked_needs_rereview
            or self.db_rows_stale_projections_removed
            or self.db_dispute_projections_invalidated
        )

    def render(self) -> str:
        lines = [
            "# Gold reconciliation report",
            "",
            f"- Generated (UTC): {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
            f"- Source annotatable rows: {self.source_rows}",
            f"- Source newly annotatable stable keys: {self.source_newly_annotatable}",
            f"- Source keys with changed visible context: {self.source_signature_changed}",
            f"- Source disputes affected by a visible-context change: {self.source_affected_disputes}",
            f"- Current annotation rows rekeyed: {self.db_rows_rekeyed}",
            f"- Current submitted annotation rows preserved: {self.db_rows_preserved}",
            f"- Current annotation rows marked `needs_rereview`: {self.db_rows_marked_needs_rereview}",
            f"- Stale current projections removed: {self.db_rows_stale_projections_removed}",
            f"- Current dispute projections invalidated: {self.db_dispute_projections_invalidated}",
            f"- Database backup: `{self.backup_path}`" if self.backup_path else "- Database backup: not needed",
            "",
            "Current projections may change; append-only event history is retained.",
            "",
        ]
        return "\n".join(lines)


def _aliases(row: pd.Series) -> set[str]:
    aliases = {stable_annotation_key(row)}
    for name in ("logical_utterance_uid", "original_utterance_id", "utterance_id"):
        value = row.get(name)
        if value is not None and not pd.isna(value) and str(value).strip():
            aliases.add(str(value).strip())
    return aliases


def _winner(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose one projection without allowing review-required work to become submitted."""
    needs_rereview = [row for row in rows if row["status"] == "needs_rereview"]
    submitted = [row for row in rows if row["status"] == "submitted"]
    candidates = needs_rereview or submitted or rows
    winner = dict(max(candidates, key=lambda row: (str(row["saved_at"]), int(row["revision_number"]))))
    winner["revision_number"] = max(int(row["revision_number"]) for row in rows)
    return winner


def _text(value: Any) -> str | None:
    return None if value is None or pd.isna(value) else str(value)


def context_signature(dataset: Dataset, row: pd.Series) -> str:
    """Serialize focal text plus exactly the ordered, prior visible source turns."""
    prior = dataset.displayable_prior_context(str(row["dispute_id"]), int(row["_display_order"]))
    signature = {
        "focal_utterance_text": _text(row.get("utterance_text")),
        "prior_visible": [
            {"stable_key": stable_annotation_key(prior_row), "utterance_text": _text(prior_row.get("utterance_text"))}
            for _, prior_row in prior.iterrows()
        ],
    }
    return json.dumps(signature, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _write_report(report: SourceMigrationReport, path: str | Path | None) -> None:
    if path is None:
        return
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.render(), encoding="utf-8")


def _states_for_dataset(dataset: Dataset) -> dict[str, dict[str, str]]:
    return {
        stable_annotation_key(row): {
            "dispute_id": str(row["dispute_id"]),
            "context_signature": context_signature(dataset, row),
        }
        for _, row in dataset.annotatable_rows.iterrows()
    }


def reconcile_annotation_keys(
    storage: Storage,
    dataset: Dataset,
    report_path: str | Path | None = None,
    *,
    previous_states: dict[str, dict[str, str]] | None = None,
    former_context_keys: set[str] | None = None,
) -> SourceMigrationReport:
    """Rekey safely and require re-review only when visible coding context changed.

    Call after reading the active Gold file. The stored snapshot means the retired
    workbook need not remain available after a filename swap. The first call records
    a baseline and preserves existing submitted projections because no prior context
    signature exists to compare.
    """
    alias_to_key: dict[str, str] = {}
    key_to_dispute: dict[str, str] = {}
    signatures: dict[str, str] = {}
    source_roles = {
        stable_annotation_key(source_row): str(source_row["utterance_role"])
        for _, source_row in dataset.source_rows.iterrows()
    }
    for _, source_row in dataset.annotatable_rows.iterrows():
        key = stable_annotation_key(source_row)
        key_to_dispute[key] = str(source_row["dispute_id"])
        signatures[key] = context_signature(dataset, source_row)
        for alias in _aliases(source_row):
            alias_to_key[alias] = key

    with storage.connect() as db:
        stored_states = {
            str(row["stable_key"]): {
                "dispute_id": str(row["dispute_id"]),
                "context_signature": str(row["context_signature"]),
            }
            for row in db.execute("SELECT stable_key,dispute_id,context_signature FROM gold_utterance_states")
        }
        stored_roles = {
            str(row["stable_key"]): str(row["utterance_role"])
            for row in db.execute("SELECT stable_key,utterance_role FROM gold_source_roles")
        }
        old_states = stored_states if previous_states is None else previous_states
        current_rows = [dict(row) for row in db.execute("SELECT * FROM utterance_annotations").fetchall()]
        former_context_keys = (former_context_keys or set()) | {
            key for key, role in stored_roles.items() if role != "utterance" and key in signatures
        }
        # Explicit old/new cutovers carry the former-context keys on every
        # invocation. Once the new roles have been stored, those keys are valid
        # annotatable work and must not be deleted on a later rerun.
        former_context_keys = {key for key in former_context_keys if stored_roles.get(key, "context") != "utterance"}
        stale_rows = [row for row in current_rows if alias_to_key.get(str(row["utterance_id"])) in former_context_keys]
        stale_row_ids = {(str(row["coder_id"]), str(row["utterance_id"])) for row in stale_rows}
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in current_rows:
            target = alias_to_key.get(str(row["utterance_id"]))
            if target is not None and (str(row["coder_id"]), str(row["utterance_id"])) not in stale_row_ids:
                grouped[(str(row["coder_id"]), target)].append(row)

        rekeys: list[tuple[str, str, list[dict[str, Any]], dict[str, Any]]] = []
        for (coder, target), matches in grouped.items():
            winner = _winner(matches)
            unchanged = (
                len(matches) == 1
                and str(winner["utterance_id"]) == target
                and str(winner["dispute_id"]) == key_to_dispute[target]
            )
            if not unchanged:
                rekeys.append((coder, target, matches, winner))

        source_changed_keys = {
            key
            for key, signature in signatures.items()
            if key in old_states and old_states[key]["context_signature"] != signature
        }
        source_affected_disputes = {key_to_dispute[key] for key in source_changed_keys}
        stored_snapshot_changed = any(
            key not in stored_states
            or stored_states[key]["dispute_id"] != key_to_dispute[key]
            or stored_states[key]["context_signature"] != signature
            for key, signature in signatures.items()
        ) or bool(set(stored_states) - set(signatures))
        # A repeated direct old/new invocation still reports the source
        # comparison, but must not repeat projection mutations or backups after
        # the stored snapshot already matches the new Gold.
        changed_keys = source_changed_keys if stored_snapshot_changed else set()
        rereview_rows = [
            row
            for row in current_rows
            if alias_to_key.get(str(row["utterance_id"])) in changed_keys
            and (str(row["coder_id"]), str(row["utterance_id"])) not in stale_row_ids
            and row["status"] != "needs_rereview"
        ]
        affected_disputes = {key_to_dispute[key] for key in changed_keys}
        decisions_to_invalidate = [
            str(row["dispute_id"])
            for row in db.execute("SELECT DISTINCT dispute_id FROM dispute_annotations").fetchall()
            if str(row["dispute_id"]) in affected_disputes
        ]
        state_changes = stored_snapshot_changed
        role_changes = source_roles != stored_roles
        mutates = bool(
            rekeys or rereview_rows or stale_rows or decisions_to_invalidate or state_changes or role_changes
        )

    # This is intentionally after every read-only comparison and immediately before
    # opening the transaction that can update projections or the Gold snapshot.
    backup = storage.backup_before_source_migration() if mutates else None
    with storage.connect() as db:
        for row in stale_rows:
            db.execute(
                "DELETE FROM utterance_annotations WHERE coder_id=? AND utterance_id=?",
                (row["coder_id"], row["utterance_id"]),
            )
        for coder, target, matches, winner in rekeys:
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

        # Rekeying above may have moved an alias to a changed stable key.
        if changed_keys:
            placeholders = ",".join("?" for _ in changed_keys)
            db.execute(
                f"UPDATE utterance_annotations SET status='needs_rereview' WHERE utterance_id IN ({placeholders})",  # noqa: S608
                tuple(changed_keys),
            )
        if decisions_to_invalidate:
            placeholders = ",".join("?" for _ in decisions_to_invalidate)
            db.execute(
                f"DELETE FROM dispute_annotations WHERE dispute_id IN ({placeholders})",  # noqa: S608
                tuple(decisions_to_invalidate),
            )
        recorded_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if signatures:
            db.execute(
                f"DELETE FROM gold_utterance_states WHERE stable_key NOT IN ({','.join('?' for _ in signatures)})",  # noqa: S608
                tuple(signatures),
            )
        else:
            db.execute("DELETE FROM gold_utterance_states")
        if source_roles:
            db.execute(
                f"DELETE FROM gold_source_roles WHERE stable_key NOT IN ({','.join('?' for _ in source_roles)})",  # noqa: S608
                tuple(source_roles),
            )
        else:
            db.execute("DELETE FROM gold_source_roles")
        for key, role in source_roles.items():
            db.execute(
                """INSERT INTO gold_source_roles(stable_key,utterance_role) VALUES(?,?)
                ON CONFLICT(stable_key) DO UPDATE SET utterance_role=excluded.utterance_role""",
                (key, role),
            )
        for key, signature in signatures.items():
            db.execute(
                """INSERT INTO gold_utterance_states(stable_key,dispute_id,context_signature,recorded_at)
                VALUES(?,?,?,?) ON CONFLICT(stable_key) DO UPDATE SET dispute_id=excluded.dispute_id,
                context_signature=excluded.context_signature,recorded_at=excluded.recorded_at""",
                (key, key_to_dispute[key], signature, recorded_at),
            )

    report = SourceMigrationReport(
        source_rows=len(signatures),
        source_newly_annotatable=len(set(signatures) - set(old_states)),
        source_signature_changed=len(source_changed_keys),
        source_affected_disputes=len(source_affected_disputes),
        db_rows_rekeyed=len(rekeys),
        db_rows_preserved=sum(
            1
            for row in current_rows
            if alias_to_key.get(str(row["utterance_id"])) in signatures
            and row["status"] == "submitted"
            and alias_to_key.get(str(row["utterance_id"])) not in changed_keys
            and (str(row["coder_id"]), str(row["utterance_id"])) not in stale_row_ids
        ),
        db_rows_marked_needs_rereview=len(rereview_rows),
        db_rows_stale_projections_removed=len(stale_rows),
        db_dispute_projections_invalidated=len(decisions_to_invalidate),
        backup_path=backup,
    )
    _write_report(report, report_path)
    return report


def migrate_gold_change(
    storage: Storage,
    old_dataset: Dataset,
    new_dataset: Dataset,
    report_path: str | Path | None = None,
) -> SourceMigrationReport:
    """Compare old and new Gold directly, then apply one safe, idempotent cutover.

    Use this before or immediately after the manual source filename swap. Context
    rows promoted to annotatable rows remain unannotated even if stale projections
    happen to share their old identifier.
    """
    old_states = _states_for_dataset(old_dataset)
    former_context_keys = {
        stable_annotation_key(row)
        for _, row in old_dataset.source_rows.iterrows()
        if row["utterance_role"] != "utterance"
    } & set(new_dataset.annotatable_rows["_annotation_key"].astype(str))
    return reconcile_annotation_keys(
        storage,
        new_dataset,
        report_path,
        previous_states=old_states,
        former_context_keys=former_context_keys,
    )


def main() -> int:
    """Run an explicit, idempotent Gold cutover after the workbook filename swap."""
    import argparse
    from dataclasses import replace

    from .config import load_config
    from .ingest import read_gold
    from .validation import validate_inputs

    parser = argparse.ArgumentParser(description="Safely reconcile annotation projections to a new Gold workbook.")
    parser.add_argument("--old-gold", help="Retained pre-swap Gold workbook for a direct comparison.")
    parser.add_argument("--new-gold", help="Replacement Gold workbook for a direct comparison.")
    args = parser.parse_args()
    if bool(args.old_gold) != bool(args.new_gold):
        parser.error("--old-gold and --new-gold must be supplied together")
    config = load_config()
    qc_configs = (
        (replace(config, gold_path=Path(args.old_gold)), replace(config, gold_path=Path(args.new_gold)))
        if args.old_gold
        else (config,)
    )
    for qc_config in qc_configs:
        qc = validate_inputs(qc_config)
        if qc.blocking:
            print("Gold reconciliation blocked by input QC:")
            print("\n".join(f"- {error}" for error in qc.errors))
            return 1
    storage = Storage(config.database_path)
    report_path = config.root / "reports" / "gold_reconciliation.md"
    if args.old_gold:
        report = migrate_gold_change(
            storage,
            read_gold(args.old_gold, config.annotation_sheet),
            read_gold(args.new_gold, config.annotation_sheet),
            report_path,
        )
    else:
        report = reconcile_annotation_keys(storage, read_gold(config.gold_path, config.annotation_sheet), report_path)
    print(report.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
