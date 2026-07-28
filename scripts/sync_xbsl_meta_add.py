#!/usr/bin/env python3
"""Check or install xbsl-meta-add as an exact path-safe mirror."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPOSITORY_ROOT / ".claude" / "skills" / "xbsl-meta-add"
DEFAULT_DESTINATION = Path.home() / ".codex" / "skills" / "xbsl-meta-add"


class SyncError(RuntimeError):
    """Operational or safety error during sync."""


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path(".")
    for part in path.parts[1:] if path.is_absolute() else path.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _normalize_existing_parent(path: Path) -> Path:
    if path.exists():
        return path.resolve()
    return path.parent.resolve() / path.name


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_paths(source: Path, destination: Path) -> tuple[Path, Path]:
    source = Path(source).expanduser()
    destination = Path(destination).expanduser()
    if not source.exists() or not source.is_dir():
        raise SyncError("source must be an existing directory")
    if _has_symlink_component(source) or _has_symlink_component(destination):
        raise SyncError("source and destination must not contain symlinks")

    normalized_source = source.resolve()
    normalized_destination = _normalize_existing_parent(destination)
    forbidden_destinations = {
        Path("/").resolve(),
        Path.home().resolve(),
        REPOSITORY_ROOT.resolve(),
    }
    if normalized_destination in forbidden_destinations:
        raise SyncError("destination is too broad")
    if normalized_source == normalized_destination:
        raise SyncError("source and destination must be different")
    if _is_relative_to(normalized_source, normalized_destination) or _is_relative_to(
        normalized_destination, normalized_source
    ):
        raise SyncError("source and destination must not be nested")
    if normalized_destination.name != "xbsl-meta-add":
        raise SyncError("destination must be the xbsl-meta-add directory")
    return normalized_source, normalized_destination


def _entry_map(root: Path) -> dict[str, tuple[str, str | None, bool]]:
    entries: dict[str, tuple[str, str | None, bool]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SyncError(f"symlink entries are not allowed: {path}")
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            entries[relative] = ("dir", None, False)
        elif path.is_file():
            entries[relative] = (
                "file",
                path.read_bytes().hex(),
                bool(path.stat().st_mode & 0o111),
            )
        else:
            raise SyncError(f"unsupported entry type: {path}")
    return entries


def compare_trees(source: Path, destination: Path) -> bool:
    if not destination.exists() or not destination.is_dir():
        return False
    return _entry_map(source) == _entry_map(destination)


def _copy_tree(source: Path, staging: Path) -> None:
    shutil.copytree(source, staging, symlinks=False)
    if not compare_trees(source, staging):
        raise SyncError("staging validation failed")


def _cleanup(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def check(source: Path, destination: Path) -> int:
    source, destination = validate_paths(source, destination)
    if compare_trees(source, destination):
        print("clean")
        return 0
    if not destination.exists():
        print("missing destination")
    else:
        print("drift")
    return 1


def sync(source: Path, destination: Path, *, inject_failure: str | None = None) -> int:
    try:
        source, destination = validate_paths(source, destination)
        if compare_trees(source, destination):
            print("clean")
            return 0

        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True)
        staging = parent / f".{destination.name}.staging-{uuid.uuid4().hex}"
        rollback: Path | None = None
        committed = False

        try:
            _copy_tree(source, staging)
            if inject_failure == "before-backup":
                raise SyncError("injected failure before backup")

            if destination.exists():
                rollback = Path(
                    tempfile.mkdtemp(prefix=f".{destination.name}.rollback-", dir=parent)
                )
                rollback.rmdir()
                os.replace(destination, rollback)
            if inject_failure == "after-backup":
                raise SyncError("injected failure after backup")

            os.replace(staging, destination)
            if not compare_trees(source, destination):
                raise SyncError("postvalidation failed")
            committed = True

            if rollback is not None:
                if inject_failure == "cleanup":
                    raise SyncError(f"injected cleanup failure; cleanup path: {rollback}")
                _cleanup(rollback)
            print("synced")
            return 0
        except Exception as error:
            if committed:
                print(f"error: {error}")
                return 2
            if staging.exists():
                _cleanup(staging)
            if rollback is not None:
                if destination.exists():
                    _cleanup(destination)
                os.replace(rollback, destination)
            print(f"error: {error}")
            return 2
    except (OSError, SyncError) as error:
        print(f"error: {error}")
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument(
        "--inject-failure",
        choices=["before-backup", "after-backup", "cleanup"],
        default=None,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    if args.check == args.sync:
        print("error: pass exactly one of --check or --sync")
        return 2
    if args.check:
        try:
            return check(args.source, args.destination)
        except (OSError, SyncError) as error:
            print(f"error: {error}")
            return 2
    return sync(args.source, args.destination, inject_failure=args.inject_failure)


if __name__ == "__main__":
    raise SystemExit(main())
