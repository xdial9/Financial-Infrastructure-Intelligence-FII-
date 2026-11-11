"""Private, content-addressed raw evidence preservation."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from fii.sources.contracts import (
    CollectionContext,
    EvidenceWriteError,
    RawEvidenceReference,
)

_SAFE_SOURCE_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SAFE_SUFFIX = re.compile(r"^[a-z0-9]{1,8}$")
_SECRET_ASSIGNMENT = re.compile(
    r"""(?P<prefix>["']?\b(?:api[_-]?key|client[_-]?secret|access[_-]?token|"""
    r"""refresh[_-]?token|secret|password|authorization|private[_-]?key)\b"""
    r"""["']?\s*[:=]\s*)["'](?P<value>[^"'\x60\\]{4,})["']""",
    re.IGNORECASE,
)
_BEARER_VALUE = re.compile(r"\b(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_QUERY_SECRET_VALUE = re.compile(
    r"([?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password)"
    r"=)[^&#\s\"'\x60]+",
    re.IGNORECASE,
)


def redact_sensitive_text(text: str) -> tuple[str, int]:
    """Remove likely credential values while retaining field names and structure."""
    redacted, first = _SECRET_ASSIGNMENT.subn(
        lambda match: f'{match.group("prefix")}"[REDACTED]"',
        text,
    )
    redacted, second = _BEARER_VALUE.subn(r"\1[REDACTED]", redacted)
    redacted, third = _QUERY_SECRET_VALUE.subn(r"\1[REDACTED]", redacted)
    return redacted, first + second + third


def write_raw_evidence(
    context: CollectionContext,
    *,
    source_id: str,
    original_name: str,
    content: bytes,
    media_type: str,
    redact_text: bool = False,
) -> RawEvidenceReference:
    """Store bytes privately, without overwriting prior evidence.

    When text redaction is requested, the original digest is retained as
    metadata while the stored artifact contains only the redacted content.
    """
    if not _SAFE_SOURCE_ID.fullmatch(source_id):
        raise EvidenceWriteError("Invalid source ID for raw evidence storage.")

    raw_bytes = content
    original_digest = hashlib.sha256(raw_bytes).hexdigest()
    redactions = 0
    if redact_text:
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EvidenceWriteError("Text evidence is not valid UTF-8.") from exc
        safe_text, redactions = redact_sensitive_text(text)
        raw_bytes = safe_text.encode("utf-8")

    suffix = Path(original_name).suffix.lower().lstrip(".") or "bin"
    if not _SAFE_SUFFIX.fullmatch(suffix):
        suffix = "bin"
    digest = hashlib.sha256(raw_bytes).hexdigest()

    root = Path(context.raw_directory).expanduser()
    if root.is_symlink():
        raise EvidenceWriteError("Refusing a symlinked raw evidence directory.")

    descriptor = -1
    temporary_path: Path | None = None
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        source_directory = root / source_id
        if source_directory.is_symlink():
            raise EvidenceWriteError("Refusing a symlinked source evidence directory.")
        source_directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(source_directory, 0o700)
        resolved_root = root.resolve(strict=True)
        resolved_directory = source_directory.resolve(strict=True)
        resolved_directory.relative_to(resolved_root)

        destination = source_directory / f"{digest}.{suffix}"
        if destination.is_symlink():
            raise EvidenceWriteError("Refusing a symlinked raw evidence file.")
        if destination.exists():
            if destination.read_bytes() != raw_bytes:
                raise EvidenceWriteError(
                    "Content-addressed evidence path contains different bytes."
                )
        else:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".evidence-",
                suffix=".tmp",
                dir=source_directory,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                os.fchmod(handle.fileno(), 0o600)
                handle.write(raw_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary_path, destination)
            except FileExistsError:
                if destination.is_symlink() or destination.read_bytes() != raw_bytes:
                    raise EvidenceWriteError(
                        "Concurrent evidence write produced an unexpected destination."
                    )
            temporary_path.unlink()
            temporary_path = None

        relative_path = destination.relative_to(root).as_posix()
        return RawEvidenceReference(
            relative_path=relative_path,
            sha256=digest,
            original_sha256=original_digest,
            size_bytes=len(raw_bytes),
            media_type=media_type,
            redactions_applied=redactions,
        )
    except EvidenceWriteError:
        raise
    except (OSError, ValueError) as exc:
        raise EvidenceWriteError("Unable to preserve raw source evidence safely.") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
