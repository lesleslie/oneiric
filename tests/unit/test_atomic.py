"""Atomic, owner-only file writes.

A fixed-name temp file is shared by every writer of the same
destination. Whichever writer renames first moves the file out from
under the others, so the rest fail with ``FileNotFoundError`` and can
publish each other's bytes. A leftover temp file from a crashed write is
reused rather than recreated, and opening it with ``O_CREAT | O_TRUNC``
follows symlinks -- so the published file inherits whatever mode that
stale file happened to have.

``tempfile.mkstemp`` closes both: a fresh, uniquely named file at 0600,
and it refuses to follow an existing path.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
from pathlib import Path

import pytest

from oneiric.core.atomic import atomic_write_bytes, atomic_write_text


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_atomic_write_text_publishes_the_content(tmp_path: Path) -> None:
    dest = tmp_path / "snapshot.json"
    atomic_write_text(dest, "hello")
    assert dest.read_text() == "hello"


def test_atomic_write_bytes_publishes_binary_content(tmp_path: Path) -> None:
    dest = tmp_path / "blob.bin"
    atomic_write_bytes(dest, b"\x00\x01\x02")
    assert dest.read_bytes() == b"\x00\x01\x02"


def test_atomic_write_text_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    dest = tmp_path / "snapshot.json"
    atomic_write_text(dest, "hello")
    assert [p.name for p in tmp_path.iterdir()] == ["snapshot.json"]


def test_atomic_write_text_publishes_owner_only_permissions(tmp_path: Path) -> None:
    dest = tmp_path / "snapshot.json"
    atomic_write_text(dest, "hello")
    assert _mode(dest) == 0o600


def test_atomic_write_text_honours_an_explicit_mode(tmp_path: Path) -> None:
    dest = tmp_path / "snapshot.json"
    atomic_write_text(dest, "hello", mode=0o640)
    assert _mode(dest) == 0o640


def test_a_stale_temp_file_cannot_leak_its_permissions(tmp_path: Path) -> None:
    """A leftover temp file from a crashed write must not be reused.

    ``Path.write_text`` truncates an existing file *in place* and keeps
    its mode, so a stale temp left at 0644 publishes the destination at
    0644 no matter what the writer intended.
    """
    dest = tmp_path / "snapshot.json"
    stale = tmp_path / "snapshot.tmp"
    stale.write_text("poison")
    stale.chmod(0o644)

    atomic_write_text(dest, "fresh")

    assert dest.read_text() == "fresh"
    assert _mode(dest) == 0o600


def test_a_symlinked_temp_file_is_never_written_through(tmp_path: Path) -> None:
    """The writer must not follow a symlink planted at a predictable path.

    ``Path.write_bytes`` opens with ``O_CREAT | O_TRUNC``, which follows
    a symlink: whatever the temp path points at gets truncated and
    overwritten.
    """
    dest = tmp_path / "snapshot.json"
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    (tmp_path / "snapshot.tmp").symlink_to(victim)

    atomic_write_text(dest, "fresh")

    assert victim.read_text() == "precious"
    assert dest.read_text() == "fresh"


def test_the_temp_file_is_owner_only_from_the_moment_it_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The temp file must never be observable at a wider mode.

    A write-then-chmod pattern leaves the temp readable by everyone for
    as long as the write takes -- which is exactly the window a
    sensitive payload is exposed in.
    """
    real_mkstemp = tempfile.mkstemp
    observed: list[int] = []

    def spy(*args: object, **kwargs: object) -> tuple[int, str]:
        fd, name = real_mkstemp(*args, **kwargs)  # type: ignore[arg-type]
        observed.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return fd, name

    monkeypatch.setattr(tempfile, "mkstemp", spy)

    atomic_write_text(tmp_path / "snapshot.json", "hello")

    assert observed == [0o600], f"the temp file was created at {observed}"


def test_atomic_write_text_replaces_the_destination_in_one_step(tmp_path: Path) -> None:
    dest = tmp_path / "snapshot.json"
    dest.write_text("old")
    atomic_write_text(dest, "new")
    assert dest.read_text() == "new"


def test_a_failed_rename_leaves_the_destination_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash between the write and the rename must not leak a temp file."""
    dest = tmp_path / "snapshot.json"
    dest.write_text("original")

    def boom(src: str, dst: str) -> None:
        raise OSError("rename failed")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError, match="rename failed"):
        atomic_write_text(dest, "new")

    assert dest.read_text() == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["snapshot.json"]


def test_concurrent_writers_all_succeed(tmp_path: Path) -> None:
    """Every writer of one destination must survive.

    With a fixed temp name the first writer to rename moves the file
    away from the others, whose rename then raises
    ``FileNotFoundError``.
    """
    dest = tmp_path / "snapshot.json"
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def writer(index: int) -> None:
        try:
            barrier.wait()
            for _ in range(25):
                atomic_write_text(dest, json.dumps({"writer": index}))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"concurrent writers raised: {errors[:3]}"
    assert json.loads(dest.read_text())["writer"] in range(8)


def test_the_published_file_is_never_a_mixture_of_two_writes(tmp_path: Path) -> None:
    """A published file must be one writer's bytes, never a blend.

    A shared temp file lets one writer truncate another's payload
    mid-flight, so what gets published can be half of each.
    """
    dest = tmp_path / "snapshot.json"
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def writer(index: int) -> None:
        try:
            barrier.wait()
            for _ in range(25):
                atomic_write_text(
                    dest, json.dumps({"writer": index, "filler": "x" * 4000})
                )
                # A reader must never observe a half-written file.
                assert json.loads(dest.read_text())["filler"] == "x" * 4000
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"concurrent writers raised: {errors[:3]}"
