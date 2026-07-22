"""Deterministic source-workbook quality checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re

import pandas as pd

from .codebook import EXPECTED_LABELS, load_codebook
from .config import ProjectConfig, load_config
from .ingest import ANNOTATION_COLUMNS, LEGACY_SOURCE_ANNOTATION_COLUMNS, REQUIRED_COLUMNS


@dataclass
class QCResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return bool(self.errors)


def _norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text).strip().casefold())


def validate_inputs(config: ProjectConfig) -> QCResult:
    result = QCResult()
    for label, path in (("gold workbook", config.gold_path), ("codebook", config.codebook_path)):
        if not path.is_file():
            result.errors.append(f"Missing {label}: {path}")
    if result.errors:
        return result
    try:
        book = pd.ExcelFile(config.gold_path)
    except Exception as exc:
        result.errors.append(f"Cannot read gold workbook: {exc}")
        return result
    sheet = config.annotation_sheet
    if sheet not in book.sheet_names:
        result.errors.append(f"Missing required annotation sheet {sheet!r}; found {book.sheet_names!r}.")
    else:
        frame = pd.read_excel(config.gold_path, sheet_name=sheet, dtype=object)
        missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
        annotation_variants = (ANNOTATION_COLUMNS, LEGACY_SOURCE_ANNOTATION_COLUMNS)
        if not any(columns <= set(frame.columns) for columns in annotation_variants):
            closest = min(annotation_variants, key=lambda columns: len(columns - set(frame.columns)))
            missing.extend(sorted(closest - set(frame.columns)))
        if not any(col in frame.columns for col in ("article_title", "source_page_title", "dispute_label")):
            missing.append("article_title (or source_page_title/dispute_label alias)")
        if missing:
            result.errors.append(f"{sheet}: missing columns: {', '.join(missing)}")
            return result
        for idx, row in frame.iterrows():
            excel_row = idx + 2
            uid, did, text = row["utterance_id"], row["dispute_id"], row["utterance_text"]
            if pd.isna(uid) or not str(uid).strip():
                result.errors.append(f"{sheet} row {excel_row}: empty utterance_id.")
            if pd.isna(did) or not str(did).strip():
                result.errors.append(f"{sheet} row {excel_row}: empty dispute_id.")
            if pd.isna(text) or not str(text).strip():
                result.errors.append(f"{sheet} row {excel_row} ({uid}): empty utterance_text.")
        duplicated = frame[frame["utterance_id"].astype(str).duplicated(keep=False)]
        for uid, group in duplicated.groupby(duplicated["utterance_id"].astype(str)):
            result.errors.append(
                f"{sheet}: duplicate utterance_id {uid!r} at rows {', '.join(str(i + 2) for i in group.index)}."
            )
        roles = set(frame["utterance_role"].dropna().astype(str))
        invalid_roles = roles - {"context", "utterance"}
        if frame["utterance_role"].isna().any() or invalid_roles:
            result.errors.append(
                f"{sheet}: utterance_role values must be exactly context or utterance; invalid values: "
                f"{sorted(invalid_roles | ({'<blank>'} if frame['utterance_role'].isna().any() else set()))}."
            )
        for did, group in frame.groupby("dispute_id", sort=False, dropna=False):
            did = str(did)
            orders = pd.to_numeric(group["utterance_order"], errors="coerce")
            rows = [int(i) + 2 for i in group.index]
            if orders.isna().any():
                result.errors.append(f"{sheet} dispute {did}: nonnumeric utterance_order at rows {rows}.")
                continue
            if not (orders == orders.astype(int)).all():
                result.errors.append(f"{sheet} dispute {did}: utterance_order must contain integers; rows {rows}.")
                continue
            actual = orders.astype(int).tolist()
            expected = list(range(min(actual), max(actual) + 1))
            if actual != expected:
                result.errors.append(
                    f"{sheet} dispute {did}: utterance_order must be strictly increasing and gap-free; rows {rows}, values {actual}."
                )
            positions = frame.index[frame["dispute_id"].astype(str) == did].tolist()
            if positions != list(range(min(positions), max(positions) + 1)):
                result.errors.append(f"{sheet}: dispute {did} is interleaved at rows {[i + 2 for i in positions]}.")
            context = group[group["utterance_role"] == "context"]
            if len(context) != 1:
                result.errors.append(f"{sheet} dispute {did}: expected exactly one context row; found {len(context)}.")
            elif context.index[0] != group.index[0]:
                result.errors.append(f"{sheet} dispute {did}: context row must be first.")
            if not context.empty:
                annotation_columns = (ANNOTATION_COLUMNS | LEGACY_SOURCE_ANNOTATION_COLUMNS) & set(context.columns)
                nonblank = [column for column in annotation_columns if context[column].notna().any()]
                if nonblank:
                    result.errors.append(
                        f"{sheet} dispute {did}: context annotation fields are not blank: {', '.join(sorted(nonblank))}."
                    )
            substantive = group[group["utterance_role"] == "utterance"]
            substantive_orders = pd.to_numeric(substantive["utterance_order"], errors="coerce")
            if substantive_orders.isna().any() or not substantive_orders.is_monotonic_increasing:
                result.errors.append(f"{sheet} dispute {did}: substantive ordering is incoherent.")
            id_to_order = {str(r["utterance_id"]): int(r["utterance_order"]) for _, r in group.iterrows()}
            for idx, row in group.iterrows():
                target = row["reply_to_utterance_id"]
                if pd.isna(target) or not str(target).strip():
                    continue
                target = str(target)
                if target not in id_to_order:
                    result.errors.append(
                        f"{sheet} row {idx + 2} ({row['utterance_id']}): reply target {target!r} is not in dispute {did}."
                    )
                elif id_to_order[target] >= int(row["utterance_order"]):
                    result.warnings.append(
                        f"{sheet} row {idx + 2} ({row['utterance_id']}): reply target {target!r} has a later "
                        "utterance_order (documented final-state reconstruction artifact); future text remains hidden."
                    )
            normalized: dict[str, list[tuple[int, str]]] = {}
            for idx, row in group.iterrows():
                normalized.setdefault(_norm(row["utterance_text"]), []).append((idx + 2, str(row["utterance_id"])))
            for matches in normalized.values():
                if len(matches) > 1:
                    result.warnings.append(
                        f"{sheet} dispute {did}: normalized repeated text at "
                        + ", ".join(f"row {r} ({u})" for r, u in matches)
                        + "."
                    )
            text_rows = [
                (idx + 2, str(row["utterance_id"]), _norm(row["utterance_text"])) for idx, row in group.iterrows()
            ]
            for position, (excel_row, uid, text) in enumerate(text_rows):
                absorbed = [
                    (row_number, prior_id)
                    for row_number, prior_id, prior_text in text_rows[:position]
                    if len(prior_text) >= 40 and prior_text in text
                ]
                if len(absorbed) >= 2:
                    result.warnings.append(
                        f"{sheet} row {excel_row} ({uid}): possible absorbed-turn reconstruction contains "
                        + ", ".join(f"row {row_number} ({prior_id})" for row_number, prior_id in absorbed)
                        + "."
                    )
        if not result.errors:
            result.checks.append(
                f"{sheet}: {len(frame)} retained rows; {(frame['utterance_role'] == 'utterance').sum()} annotatable; "
                f"{(frame['utterance_role'] == 'context').sum()} context; {frame['dispute_id'].nunique()} disputes."
            )
    try:
        codebook = load_codebook(config.codebook_path, config.schema_sheet)
        missing_labels = EXPECTED_LABELS - set(codebook.fields)
        if missing_labels:
            result.errors.append(f"Codebook missing UI labels: {', '.join(sorted(missing_labels))}.")
        unexpected_labels = set(codebook.fields) - EXPECTED_LABELS
        if unexpected_labels:
            result.errors.append(f"Codebook has unsupported UI labels: {', '.join(sorted(unexpected_labels))}.")
        if not codebook.evidence_types:
            result.errors.append("Codebook Evidence_Types has no allowed values.")
        if not codebook.dispute_objects:
            result.errors.append("Codebook Primary_Dispute_Objects has no allowed values.")
        if "0,1,2" not in codebook.fields["KS_argument_strength"].indicator.replace(" ", ""):
            result.errors.append("KS_argument_strength: authoritative indicator does not offer ordinal 0–2.")
    except Exception as exc:
        result.errors.append(f"Cannot load authoritative codebook: {exc}")
    result.checks.append(f"Source workbook sheets found: {', '.join(book.sheet_names)}")
    return result


def render_report(result: QCResult, config: ProjectConfig) -> str:
    status = "BLOCKED" if result.blocking else "PASS"
    lines = [
        "# Input QC Report",
        "",
        f"- Status: **{status}**",
        f"- Generated (UTC): {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
        f"- Gold workbook: `{config.gold_path}`",
        f"- Codebook: `{config.codebook_path}`",
        "",
        "## Blocking errors",
        "",
    ]
    lines.extend([f"- {item}" for item in result.errors] or ["- None."])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {item}" for item in result.warnings] or ["- None."])
    lines.extend(["", "## Checks", ""])
    lines.extend([f"- {item}" for item in result.checks] or ["- None."])
    lines.extend(
        [
            "",
            "Blocking errors prevent annotation. Source workbooks are never repaired or rewritten by this application.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    config = load_config()
    result = validate_inputs(config)
    report = render_report(result, config)
    path = config.root / "reports" / "input_qc.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    print(report)
    print(f"Report written to {path}")
    return 1 if result.blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
