"""Transactional SQLite state, history, and one-time legacy migration."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from . import __version__

CODER_RE = re.compile(r"^[A-Za-z0-9_-]{3,40}$")
DATABASE_VERSION = 2
ANNOTATION_TABLES = (
    "utterance_annotations",
    "utterance_annotation_events",
    "dispute_annotations",
    "dispute_annotation_events",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class SchemaDriftError(RuntimeError):
    pass


class MigrationError(RuntimeError):
    pass


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migration_backup: Path | None = None
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _columns(db: sqlite3.Connection, table: str) -> list[str]:
        return [str(row[1]) for row in db.execute(f"PRAGMA table_info({table})").fetchall()]  # noqa: S608

    @staticmethod
    def _create_annotation_tables(db: sqlite3.Connection, suffix: str = "") -> None:
        statements = (
            f"""CREATE TABLE utterance_annotations{suffix} (
                coder_id TEXT NOT NULL, utterance_id TEXT NOT NULL, dispute_id TEXT NOT NULL,
                status TEXT NOT NULL, payload_json TEXT NOT NULL, answered_fields_json TEXT NOT NULL,
                schema_version TEXT NOT NULL, schema_hash TEXT NOT NULL, opened_at TEXT NOT NULL,
                saved_at TEXT NOT NULL, elapsed_wall_seconds REAL NOT NULL, revision_number INTEGER NOT NULL,
                PRIMARY KEY(coder_id, utterance_id), FOREIGN KEY(coder_id) REFERENCES coders(coder_id))""",
            f"""CREATE TABLE utterance_annotation_events{suffix} (
                event_id TEXT PRIMARY KEY, coder_id TEXT NOT NULL, utterance_id TEXT NOT NULL,
                dispute_id TEXT NOT NULL, event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
                answered_fields_json TEXT NOT NULL, schema_version TEXT NOT NULL, schema_hash TEXT NOT NULL,
                opened_at TEXT NOT NULL, saved_at TEXT NOT NULL, elapsed_wall_seconds REAL NOT NULL,
                revision_number INTEGER NOT NULL, app_version TEXT NOT NULL)""",
            f"""CREATE TABLE dispute_annotations{suffix} (
                coder_id TEXT NOT NULL, dispute_id TEXT NOT NULL, payload_json TEXT NOT NULL,
                schema_version TEXT NOT NULL, schema_hash TEXT NOT NULL, opened_at TEXT NOT NULL,
                saved_at TEXT NOT NULL, elapsed_wall_seconds REAL NOT NULL, revision_number INTEGER NOT NULL,
                PRIMARY KEY(coder_id, dispute_id))""",
            f"""CREATE TABLE dispute_annotation_events{suffix} (
                event_id TEXT PRIMARY KEY, coder_id TEXT NOT NULL, dispute_id TEXT NOT NULL,
                event_type TEXT NOT NULL, payload_json TEXT NOT NULL, answered_fields_json TEXT NOT NULL,
                schema_version TEXT NOT NULL, schema_hash TEXT NOT NULL, opened_at TEXT NOT NULL,
                saved_at TEXT NOT NULL, elapsed_wall_seconds REAL NOT NULL, revision_number INTEGER NOT NULL,
                app_version TEXT NOT NULL)""",
        )
        for statement in statements:
            db.execute(statement)

    def _migrate_legacy(self) -> None:
        with sqlite3.connect(self.path) as audit:
            collisions = []
            for table, unit in (("utterance_annotations", "utterance_id"), ("dispute_annotations", "dispute_id")):
                rows = audit.execute(
                    f"SELECT coder_id,{unit},COUNT(*) FROM {table} GROUP BY coder_id,{unit} HAVING COUNT(*)>1"  # noqa: S608
                ).fetchall()
                collisions.extend(f"{table}: coder={r[0]!r}, {unit}={r[1]!r}, records={r[2]}" for r in rows)
        if collisions:
            raise MigrationError(
                "Legacy database migration stopped before making changes because records from different old values "
                "collide under the unified keys: "
                + "; ".join(collisions)
                + ". Export or reconcile those records in a copy, then retry."
            )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self.path.with_name(f"{self.path.name}.pre-unified-{stamp}.bak")
        with sqlite3.connect(self.path) as source, sqlite3.connect(backup) as destination:
            source.backup(destination)
        self.migration_backup = backup
        try:
            with sqlite3.connect(self.path) as db:
                db.execute("PRAGMA foreign_keys=OFF")
                db.execute("BEGIN IMMEDIATE")
                self._create_annotation_tables(db, "_new")
                for table in ANNOTATION_TABLES:
                    old = [column for column in self._columns(db, table) if column != "partition"]
                    columns = ",".join(old)
                    db.execute(f"INSERT INTO {table}_new ({columns}) SELECT {columns} FROM {table}")  # noqa: S608
                    db.execute(f"DROP TABLE {table}")  # noqa: S608
                    db.execute(f"ALTER TABLE {table}_new RENAME TO {table}")  # noqa: S608
                db.execute(f"PRAGMA user_version={DATABASE_VERSION}")
                db.commit()
        except Exception as exc:
            shutil.copy2(backup, self.path)
            raise MigrationError(
                f"Legacy database migration failed; the original was restored from {backup}: {exc}"
            ) from exc

    def _initialize(self) -> None:
        existed = self.path.exists() and self.path.stat().st_size > 0
        if existed:
            with sqlite3.connect(self.path) as db:
                legacy = "partition" in self._columns(db, "utterance_annotations")
            if legacy:
                self._migrate_legacy()
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS coders (
                    coder_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS schema_versions (
                    schema_version TEXT NOT NULL, file_hash TEXT NOT NULL, source_filename TEXT NOT NULL,
                    registered_at TEXT NOT NULL, PRIMARY KEY(schema_version, file_hash));
            """)
            if not self._columns(db, "utterance_annotations"):
                self._create_annotation_tables(db)
            db.execute(f"PRAGMA user_version={DATABASE_VERSION}")

    def register_schema(self, version: str, file_hash: str, source: str, locked: bool = False) -> None:
        with self.connect() as db:
            rows = db.execute("SELECT file_hash FROM schema_versions WHERE schema_version=?", (version,)).fetchall()
            if rows and file_hash not in {row[0] for row in rows}:
                raise SchemaDriftError(
                    f"Schema version {version} was already registered with a different codebook hash; increment schema_version."
                )
            if locked:
                latest = db.execute(
                    "SELECT schema_version,file_hash FROM schema_versions ORDER BY registered_at DESC LIMIT 1"
                ).fetchone()
                if latest and (latest[0], latest[1]) != (version, file_hash):
                    raise SchemaDriftError("Schema is administratively locked; the active version/hash differs.")
            db.execute(
                "INSERT OR IGNORE INTO schema_versions VALUES (?,?,?,?)", (version, file_hash, source, utc_now())
            )

    def set_active_coder(self, coder_id: str) -> None:
        if not CODER_RE.fullmatch(coder_id):
            raise ValueError("Coder ID must be 3–40 letters, numbers, hyphens, or underscores.")
        with self.connect() as db:
            db.execute("UPDATE coders SET active=0")
            db.execute(
                "INSERT INTO coders(coder_id,created_at,active) VALUES(?,?,1) ON CONFLICT(coder_id) DO UPDATE SET active=1",
                (coder_id, utc_now()),
            )

    def active_coder(self) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT coder_id FROM coders WHERE active=1 LIMIT 1").fetchone()
            return None if row is None else str(row[0])

    def current_utterance(self, coder: str, utterance_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM utterance_annotations WHERE coder_id=? AND utterance_id=?", (coder, utterance_id)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        result["answered_fields"] = json.loads(result.pop("answered_fields_json"))
        return result

    def save_utterance(
        self,
        *,
        coder: str,
        utterance_id: str,
        dispute_id: str,
        payload: dict[str, Any],
        answered_fields: set[str],
        submit: bool,
        schema_version: str,
        schema_hash: str,
        opened_at: str,
        elapsed_wall_seconds: float,
    ) -> tuple[str, int]:
        saved_at, elapsed = utc_now(), max(0.0, float(elapsed_wall_seconds))
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        answered_json = json.dumps(sorted(answered_fields))
        with self.connect() as db:
            current = db.execute(
                "SELECT status,payload_json,answered_fields_json,revision_number FROM utterance_annotations WHERE coder_id=? AND utterance_id=?",
                (coder, utterance_id),
            ).fetchone()
            if (
                current
                and current[1] == payload_json
                and current[2] == answered_json
                and (not submit or current[0] == "submitted")
            ):
                return "unchanged", int(current[3])
            previous = 0 if not current else int(current[3])
            revision = previous + 1 if submit or previous else 0
            event_type = "revise" if previous else ("submit" if submit else "draft")
            status = "submitted" if submit else "draft"
            args = (
                coder,
                utterance_id,
                dispute_id,
                status,
                payload_json,
                answered_json,
                schema_version,
                schema_hash,
                opened_at,
                saved_at,
                elapsed,
                revision,
            )
            db.execute(
                """INSERT INTO utterance_annotations VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(coder_id,utterance_id) DO UPDATE SET dispute_id=excluded.dispute_id,status=excluded.status,
                payload_json=excluded.payload_json,answered_fields_json=excluded.answered_fields_json,
                schema_version=excluded.schema_version,schema_hash=excluded.schema_hash,opened_at=excluded.opened_at,
                saved_at=excluded.saved_at,elapsed_wall_seconds=excluded.elapsed_wall_seconds,revision_number=excluded.revision_number""",
                args,
            )
            db.execute(
                "INSERT INTO utterance_annotation_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    coder,
                    utterance_id,
                    dispute_id,
                    event_type,
                    payload_json,
                    answered_json,
                    schema_version,
                    schema_hash,
                    opened_at,
                    saved_at,
                    elapsed,
                    revision,
                    __version__,
                ),
            )
            return event_type, revision

    def save_dispute(
        self,
        *,
        coder: str,
        dispute_id: str,
        payload: dict[str, Any],
        answered_fields: set[str],
        schema_version: str,
        schema_hash: str,
        opened_at: str,
        elapsed_wall_seconds: float,
    ) -> tuple[str, int]:
        saved_at, elapsed = utc_now(), max(0.0, float(elapsed_wall_seconds))
        data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self.connect() as db:
            current = db.execute(
                "SELECT payload_json,revision_number FROM dispute_annotations WHERE coder_id=? AND dispute_id=?",
                (coder, dispute_id),
            ).fetchone()
            if current and current[0] == data:
                return "unchanged", int(current[1])
            revision = 1 if not current else int(current[1]) + 1
            event_type = "submit" if not current else "revise"
            db.execute(
                """INSERT INTO dispute_annotations VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(coder_id,dispute_id)
                DO UPDATE SET payload_json=excluded.payload_json,schema_version=excluded.schema_version,
                schema_hash=excluded.schema_hash,opened_at=excluded.opened_at,saved_at=excluded.saved_at,
                elapsed_wall_seconds=excluded.elapsed_wall_seconds,revision_number=excluded.revision_number""",
                (coder, dispute_id, data, schema_version, schema_hash, opened_at, saved_at, elapsed, revision),
            )
            db.execute(
                "INSERT INTO dispute_annotation_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(uuid4()),
                    coder,
                    dispute_id,
                    event_type,
                    data,
                    json.dumps(sorted(answered_fields)),
                    schema_version,
                    schema_hash,
                    opened_at,
                    saved_at,
                    elapsed,
                    revision,
                    __version__,
                ),
            )
            return event_type, revision

    def rows(self, table: str, coder: str | None = None) -> list[dict[str, Any]]:
        if table not in {"schema_versions", *ANNOTATION_TABLES}:
            raise ValueError("Unknown table")
        with self.connect() as db:
            query, params = f"SELECT * FROM {table}", ()  # noqa: S608
            if coder and table != "schema_versions":
                query, params = query + " WHERE coder_id=?", (coder,)
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def backup_bytes(self) -> bytes:
        target = self.path.with_suffix(".backup.tmp")
        try:
            with self.connect() as source, sqlite3.connect(target) as destination:
                source.backup(destination)
            return target.read_bytes()
        finally:
            target.unlink(missing_ok=True)
