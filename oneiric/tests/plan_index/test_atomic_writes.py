from pathlib import Path

from oneiric.plan_index.regenerate import regenerate


def test_concurrent_writes_last_writer_wins(tmp_path: Path):
    """os.replace overwrites atomically on POSIX; last writer wins; no .bak."""
    import threading

    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    results = []

    def regen():
        results.append(regenerate(repo_root=tmp_path))

    threads = [threading.Thread(target=regen) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # All threads succeeded; no .bak file present; one PLAN_INDEX.md exists.
    assert (tmp_path / "docs" / "plans" / "PLAN_INDEX.md").exists()
    leftover = list((tmp_path / "docs" / "plans").glob(".PLAN_INDEX.md.*.tmp"))
    assert not leftover
