"""Atomic, owner-only file writes.

One audited implementation of the "write to a temp file, then rename over
the destination" pattern. The naive fixed-name version of this pattern
has two distinct failure modes, both of which are closed by using a
uniquely named temp file:

1. **Concurrent-writer collision.** With a fixed temp name, every
   writer of the same destination shares one temp file. Whichever
   writer renames first moves the file out from under the others, whose
   rename then fails with ``FileNotFoundError`` -- and can publish the
   other writer's bytes.
2. **Stale temp reuse and symlink following.** A temp file left behind
   by an earlier write is reused rather than recreated, so the new
   content lands in a file whose permissions were decided by that
   earlier -- possibly crashed -- write. And opening a fixed temp path
   with ``O_CREAT | O_TRUNC`` follows symlinks, so anything able to
   write into the destination directory can redirect the write -- and
   its truncation -- at an arbitrary file.

``tempfile.mkstemp`` closes both: it creates a fresh file with a unique
name, at 0600, and refuses to follow an existing path.

The published file's mode is set with ``fchmod`` on the open descriptor
rather than ``chmod`` on the path, so the file is never observable at a
wider mode than requested, even momentarily. A file created by
``Path.write_text`` takes the ambient umask (0644 under the default
022) and only narrows when a later ``chmod`` runs -- which leaves the
payload world-readable for the duration of the write.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

__all__ = ["atomic_write_bytes", "atomic_write_text"]


def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Write ``data`` to ``path`` atomically, with owner-only permissions.

    The content is written to a uniquely named temp file in the
    destination directory, flushed and fsynced, then renamed over
    ``path`` with ``os.replace``. That rename is atomic on POSIX, so a
    concurrent reader sees either the previous file or the complete new
    one -- never a half-written file.

    Args:
        path: Destination path. Its parent directory must already exist.
        data: The bytes to write.
        mode: Permission bits for the published file.

    Raises:
        OSError: If the temp file cannot be created, written, or renamed.
    """
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    """Write ``text`` to ``path`` atomically, with owner-only permissions.

    Args:
        path: Destination path. Its parent directory must already exist.
        text: The text to write, encoded as UTF-8.
        mode: Permission bits for the published file.

    Raises:
        OSError: If the temp file cannot be created, written, or renamed.
    """
    atomic_write_bytes(path, text.encode("utf-8"), mode=mode)
