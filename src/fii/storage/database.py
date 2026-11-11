"""SQLite connection, migration, transaction, integrity and backup helpers."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Iterator


class PersistenceError(RuntimeError):
    """Raised when durable FII persistence cannot be completed safely."""


@dataclass(frozen=True)
class IntegrityReport:
    """Results from SQLite's physical and foreign-key integrity checks."""

    integrity_messages: tuple[str, ...]
    foreign_key_violations: tuple[tuple[object, ...], ...]

    @property
    def ok(self) -> bool:
        """Whether both SQLite integrity checks passed."""
        return self.integrity_messages == ("ok",) and not self.foreign_key_violations


_MIGRATION_NAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


def connect_database(
    database: str | os.PathLike[str],
    *,
    timeout: float = 5.0,
) -> sqlite3.Connection:
    """Open a SQLite connection with foreign-key enforcement enabled.

    The caller owns the returned connection and must close it. Parent
    directories are deliberately not created implicitly.
    """
    if isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("Database timeout must be greater than zero.")

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            os.fspath(database),
            timeout=timeout,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        enabled = connection.execute("PRAGMA foreign_keys").fetchone()
        if enabled is None or enabled[0] != 1:
            raise PersistenceError("SQLite foreign-key enforcement could not be enabled.")
        return connection
    except (OSError, sqlite3.Error) as exc:
        if connection is not None:
            connection.close()
        raise PersistenceError("Unable to open the SQLite evidence database.") from exc
    except PersistenceError:
        if connection is not None:
            connection.close()
        raise


@contextmanager
def transaction(
    connection: sqlite3.Connection,
    *,
    immediate: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Run one explicit transaction and fail loudly on every SQLite error.

    Nested transactions are rejected so callers cannot accidentally believe
    that an inner commit made data durable when an outer transaction can roll
    it back.
    """
    if connection.in_transaction:
        raise PersistenceError("Nested SQLite transactions are not supported.")

    try:
        connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    except sqlite3.Error as exc:
        raise PersistenceError("Unable to begin the SQLite transaction.") from exc

    try:
        yield connection
    except sqlite3.Error as exc:
        try:
            connection.rollback()
        except sqlite3.Error as rollback_error:
            raise PersistenceError("SQLite transaction failed and rollback also failed.") from (
                rollback_error
            )
        raise PersistenceError("SQLite transaction failed; changes were rolled back.") from exc
    except BaseException:
        try:
            connection.rollback()
        except sqlite3.Error as rollback_error:
            raise PersistenceError("Transaction failed and SQLite rollback also failed.") from (
                rollback_error
            )
        raise
    else:
        try:
            connection.commit()
        except sqlite3.Error as exc:
            try:
                connection.rollback()
            except sqlite3.Error as rollback_error:
                raise PersistenceError(
                    "SQLite commit failed and rollback also failed."
                ) from rollback_error
            raise PersistenceError("SQLite commit failed; changes were rolled back.") from exc


def _load_migrations() -> list[tuple[int, str, str, str]]:
    """Load numbered SQL resources and return version, name, SQL and checksum."""
    package = resources.files("fii.storage.migrations")
    migrations: list[tuple[int, str, str, str]] = []

    for resource in package.iterdir():
        match = _MIGRATION_NAME_RE.fullmatch(resource.name)
        if not match or not resource.is_file():
            continue
        version = int(match.group(1))
        name = match.group(2)
        try:
            sql = resource.read_text(encoding="utf-8")
        except OSError as exc:
            raise PersistenceError(
                f"Unable to read schema migration {resource.name}."
            ) from exc
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        migrations.append((version, name, sql, checksum))

    migrations.sort(key=lambda item: item[0])
    versions = [item[0] for item in migrations]
    if not migrations or versions != list(range(1, len(versions) + 1)):
        raise PersistenceError("SQLite migrations must be numbered contiguously from 0001.")
    return migrations


def _sql_statements(script: str) -> Iterator[str]:
    """Split migration SQL without breaking quoted text or trigger bodies."""
    buffer: list[str] = []
    for character in script:
        buffer.append(character)
        if character == ";":
            statement = "".join(buffer)
            if sqlite3.complete_statement(statement):
                if statement.strip():
                    yield statement.strip()
                buffer.clear()

    remainder = "".join(buffer).strip()
    if remainder:
        raise PersistenceError("A schema migration contains an incomplete SQL statement.")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def migrate_database(connection: sqlite3.Connection) -> int:
    """Apply pending numbered migrations without replacing existing evidence."""
    foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()
    if foreign_keys is None or foreign_keys[0] != 1:
        raise PersistenceError(
            "Migrations require a connection opened with foreign keys enabled."
        )

    migrations = _load_migrations()
    latest_version = migrations[-1][0]

    with transaction(connection, immediate=True):
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY CHECK (version > 0),
                name TEXT NOT NULL,
                checksum TEXT NOT NULL CHECK (length(checksum) = 64),
                applied_at TEXT NOT NULL
            )
            """
        )
        applied_rows = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        applied = {int(row["version"]): (row["name"], row["checksum"]) for row in applied_rows}

        if applied and max(applied) > latest_version:
            raise PersistenceError(
                "Database schema is newer than this FII release; refusing to downgrade it."
            )
        if sorted(applied) != list(range(1, max(applied, default=0) + 1)):
            raise PersistenceError("Database migration history contains a version gap.")

        for version, name, sql, checksum in migrations:
            existing = applied.get(version)
            if existing is not None:
                if existing != (name, checksum):
                    raise PersistenceError(
                        f"Applied migration {version:04d} differs from the packaged migration."
                    )
                continue

            for statement in _sql_statements(sql):
                connection.execute(statement)
            connection.execute(
                """
                INSERT INTO schema_migrations (version, name, checksum, applied_at)
                VALUES (?, ?, ?, ?)
                """,
                (version, name, checksum, _utc_now()),
            )

    return latest_version


def initialize_database(database: str | os.PathLike[str]) -> int:
    """Open a database, apply migrations and close the connection."""
    connection = connect_database(database)
    try:
        return migrate_database(connection)
    finally:
        connection.close()


def check_integrity(connection: sqlite3.Connection) -> IntegrityReport:
    """Run SQLite integrity_check and foreign_key_check without mutating data."""
    try:
        integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
        foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.Error as exc:
        raise PersistenceError("Unable to check SQLite database integrity.") from exc

    return IntegrityReport(
        integrity_messages=tuple(str(row[0]) for row in integrity_rows),
        foreign_key_violations=tuple(tuple(row) for row in foreign_key_rows),
    )


def assert_integrity(connection: sqlite3.Connection) -> IntegrityReport:
    """Run integrity checks and raise when any database inconsistency is found."""
    report = check_integrity(connection)
    if not report.ok:
        raise PersistenceError(
            "SQLite integrity check failed: "
            f"{report.integrity_messages}; foreign-key violations: "
            f"{report.foreign_key_violations}"
        )
    return report


def backup_database(
    source: str | os.PathLike[str],
    destination: str | os.PathLike[str],
) -> Path:
    """Create a verified, private backup without overwriting an existing file.

    The backup is built in the destination directory, checked, then published
    with an atomic no-overwrite hard link. The source database is never changed.
    """
    source_path = Path(source).expanduser()
    destination_path = Path(destination).expanduser()

    if source_path.is_symlink() or destination_path.is_symlink():
        raise PersistenceError("Database backups refuse symlinked source or destination paths.")
    if not source_path.is_file():
        raise PersistenceError("Backup source database does not exist as a regular file.")
    if source_path.resolve() == destination_path.resolve():
        raise PersistenceError("Backup destination must differ from the source database.")
    if not destination_path.parent.is_dir():
        raise PersistenceError("Backup destination directory must already exist.")
    if destination_path.exists():
        raise PersistenceError("Backup destination already exists; refusing to overwrite it.")

    descriptor = -1
    temporary_path: Path | None = None
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination_path.name}.",
            suffix=".tmp",
            dir=destination_path.parent,
        )
        os.fchmod(descriptor, 0o600)
        os.close(descriptor)
        descriptor = -1
        temporary_path = Path(temporary_name)

        source_connection = connect_database(source_path)
        target_connection = connect_database(temporary_path)
        source_connection.backup(target_connection)
        assert_integrity(target_connection)
        target_connection.close()
        target_connection = None
        source_connection.close()
        source_connection = None

        with temporary_path.open("rb") as handle:
            os.fsync(handle.fileno())
        os.link(temporary_path, destination_path)
        temporary_path.unlink()
        temporary_path = None

        try:
            directory_descriptor = os.open(destination_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError:
            pass

        return destination_path
    except PersistenceError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise PersistenceError("Unable to create a verified SQLite backup.") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
