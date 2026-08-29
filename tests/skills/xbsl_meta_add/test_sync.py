from __future__ import annotations

import importlib.util
import os
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SYNC_PATH = REPOSITORY_ROOT / "scripts" / "sync_xbsl_meta_add.py"


def load_sync():
    assert SYNC_PATH.exists(), "missing #89 sync script"
    spec = importlib.util.spec_from_file_location("sync_xbsl_meta_add", SYNC_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_file(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | 0o111)


def snapshot(root: Path) -> dict[str, tuple[str, str, bool]]:
    result = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            result[relative] = ("dir", "", False)
        elif path.is_file():
            result[relative] = (
                "file",
                path.read_text(encoding="utf-8"),
                bool(path.stat().st_mode & 0o111),
            )
    return result


def make_source(root: Path) -> Path:
    source = root / "source" / "xbsl-meta-add"
    write_file(source / "SKILL.md", "skill\n")
    write_file(source / "references" / "types.md", "types\n")
    write_file(source / "scripts" / "tool.py", "#!/usr/bin/env python3\n", executable=True)
    return source


def test_check_reports_missing_clean_and_drift_without_mutating(tmp_path):
    sync = load_sync()
    source = make_source(tmp_path)
    destination = tmp_path / "installed" / "xbsl-meta-add"

    assert sync.main(["--source", str(source), "--destination", str(destination), "--check"]) == 1
    assert not destination.exists()

    assert sync.main(["--source", str(source), "--destination", str(destination), "--sync"]) == 0
    clean_snapshot = snapshot(destination)
    assert sync.main(["--source", str(source), "--destination", str(destination), "--check"]) == 0
    assert snapshot(destination) == clean_snapshot

    write_file(destination / "extra.txt", "extra\n")
    drift_snapshot = snapshot(destination)
    assert sync.main(["--source", str(source), "--destination", str(destination), "--check"]) == 1
    assert snapshot(destination) == drift_snapshot


def test_check_accepts_direct_runtime_symlink_to_canonical_source(tmp_path):
    sync = load_sync()
    source = make_source(tmp_path)
    destination = tmp_path / "installed" / "xbsl-meta-add"
    destination.parent.mkdir(parents=True)
    os.symlink(source, destination)

    assert sync.main(["--source", str(source), "--destination", str(destination), "--check"]) == 0
    assert destination.is_symlink()
    assert destination.resolve() == source.resolve()
    assert sync.main(["--source", str(source), "--destination", str(destination), "--sync"]) == 2


def test_sync_installs_exact_mirror_and_removes_extra_entries_by_replacement(tmp_path):
    sync = load_sync()
    source = make_source(tmp_path)
    destination = tmp_path / "installed" / "xbsl-meta-add"
    write_file(destination / "old.txt", "old\n")

    assert sync.main(["--source", str(source), "--destination", str(destination), "--sync"]) == 0

    assert snapshot(destination) == snapshot(source)
    assert not (destination / "old.txt").exists()


def test_sync_excludes_generated_and_local_only_skill_artifacts(tmp_path):
    sync = load_sync()
    source = make_source(tmp_path)
    destination = tmp_path / "installed" / "xbsl-meta-add"

    write_file(source / ".DS_Store", "mac metadata\n")
    write_file(source / "scripts" / "__pycache__" / "tool.cpython-312.pyc", "bytecode\n")
    write_file(source / "scripts" / "tool.pyc", "bytecode\n")
    write_file(source / "runtime-evidence" / "run.txt", "local evidence\n")
    write_file(source / "references" / "evidence" / "capture.md", "local capture\n")
    write_file(destination / "scripts" / "__pycache__" / "stale.pyc", "stale\n")

    assert sync.main(["--source", str(source), "--destination", str(destination), "--sync"]) == 0

    installed_entries = snapshot(destination)
    assert "SKILL.md" in installed_entries
    assert "scripts/tool.py" in installed_entries
    assert all("__pycache__" not in entry for entry in installed_entries)
    assert all(not entry.endswith(".pyc") for entry in installed_entries)
    assert ".DS_Store" not in installed_entries
    assert "runtime-evidence/run.txt" not in installed_entries
    assert "references/evidence/capture.md" not in installed_entries


def test_path_safety_rejects_equal_nested_and_symlink_paths_before_mutation(tmp_path):
    sync = load_sync()
    source = make_source(tmp_path)
    destination = tmp_path / "installed" / "xbsl-meta-add"
    write_file(destination / "keep.txt", "keep\n")
    before = snapshot(destination)

    assert sync.main(["--source", str(source), "--destination", str(source), "--sync"]) == 2
    assert sync.main(["--source", str(source), "--destination", str(source / "child"), "--sync"]) == 2

    symlink_destination = tmp_path / "symlink-destination"
    os.symlink(destination, symlink_destination)
    assert sync.main(["--source", str(source), "--destination", str(symlink_destination), "--sync"]) == 2

    assert snapshot(destination) == before


def test_precommit_failure_restores_previous_destination_byte_for_byte(tmp_path):
    sync = load_sync()
    source = make_source(tmp_path)
    destination = tmp_path / "installed" / "xbsl-meta-add"
    write_file(destination / "old.txt", "old\n")
    before = snapshot(destination)

    result = sync.main(
        [
            "--source",
            str(source),
            "--destination",
            str(destination),
            "--sync",
            "--inject-failure",
            "after-backup",
        ]
    )

    assert result == 2
    assert snapshot(destination) == before


def test_postcommit_cleanup_failure_keeps_new_destination_authoritative(tmp_path):
    sync = load_sync()
    source = make_source(tmp_path)
    destination = tmp_path / "installed" / "xbsl-meta-add"
    write_file(destination / "old.txt", "old\n")

    result = sync.main(
        [
            "--source",
            str(source),
            "--destination",
            str(destination),
            "--sync",
            "--inject-failure",
            "cleanup",
        ]
    )

    assert result == 2
    assert snapshot(destination) == snapshot(source)
