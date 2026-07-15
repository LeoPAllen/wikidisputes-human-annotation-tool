"""Project configuration for one authoritative annotation worksheet."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class ProjectConfig:
    root: Path
    gold_path: Path
    codebook_path: Path
    database_path: Path
    export_directory: Path
    schema_version: str
    schema_sheet: str
    annotation_sheet: str
    schema_locked: bool
    low_confidence_threshold: int


def load_config(path: str | Path = "config/project.toml") -> ProjectConfig:
    config_path = Path(path).resolve()
    values = tomllib.loads(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent
    resolve = lambda key: (root / values[key]).resolve()  # noqa: E731
    return ProjectConfig(
        root=root,
        gold_path=resolve("gold_path"),
        codebook_path=resolve("codebook_path"),
        database_path=resolve("database_path"),
        export_directory=resolve("export_directory"),
        schema_version=str(values["schema_version"]),
        schema_sheet=str(values["schema_sheet"]),
        annotation_sheet=str(values["annotation_sheet"]),
        schema_locked=bool(values["schema_locked"]),
        low_confidence_threshold=int(values["low_confidence_threshold"]),
    )
