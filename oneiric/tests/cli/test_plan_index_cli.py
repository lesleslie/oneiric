import subprocess
import sys
from pathlib import Path

def test_oneiric_plan_index_regenerate_runs(tmp_path: Path):
    docs = tmp_path / "docs" / "plans"
    docs.mkdir(parents=True)
    (docs / "foo.md").write_text("---\nstatus: active\n---\n# Foo\n")
    result = subprocess.run(
        [sys.executable, "-m", "oneiric", "plan-index", "regenerate",
         "--repo-root", str(tmp_path)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "docs" / "plans" / "PLAN_INDEX.md").exists()

def test_oneiric_plan_index_subcommand_listed_in_help(capsys):
    result = subprocess.run([sys.executable, "-m", "oneiric", "--help"],
                            capture_output=True, text=True, timeout=10)
    assert "plan-index" in result.stdout