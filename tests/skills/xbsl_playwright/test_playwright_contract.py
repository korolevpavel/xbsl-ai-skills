"""Packaging checks for the reusable xbsl-playwright skill and its resources."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml


ROOT_DIR = Path(__file__).resolve().parents[3]
SKILL_DIR = ROOT_DIR / "skills" / "xbsl-playwright"
SKILL_PATH = SKILL_DIR / "SKILL.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_frontmatter_identifies_skill_and_runtime() -> None:
    match = re.match(r"^---\n(.*?)\n---\n", read(SKILL_PATH), flags=re.DOTALL)
    assert match is not None
    metadata = yaml.safe_load(match.group(1))

    assert isinstance(metadata, dict)
    assert metadata["name"] == SKILL_DIR.name
    assert isinstance(metadata["description"], str)
    assert 0 < len(metadata["description"].strip()) <= 1024
    assert set(metadata) <= {
        "name", "description", "license", "allowed-tools", "metadata"
    }
    runtime = metadata["metadata"]["runtime"]
    assert "Node.js" in runtime
    assert "@playwright/test" in runtime


def test_local_markdown_links_resolve_inside_skill() -> None:
    checked = 0
    for document in SKILL_DIR.rglob("*.md"):
        for destination in re.findall(r"\[[^\]]*\]\(([^)]+)\)", read(document)):
            target = urlsplit(destination.strip().strip("<>"))
            if target.scheme or target.netloc or not target.path:
                continue
            resource = (document.parent / unquote(target.path)).resolve()
            assert resource.is_relative_to(SKILL_DIR.resolve()), (
                f"{document.relative_to(SKILL_DIR)} links outside the skill: "
                f"{destination}"
            )
            assert resource.exists(), f"Missing resource: {destination} in {document}"
            checked += 1
    assert checked, "The skill must link to its reusable resources"


def test_public_resources_have_no_pilot_or_local_repository_dependency() -> None:
    forbidden_patterns = (
        r"testapp-skills-",
        r"\bapp-\d{6,}\b",
        r"\bf179ab1e\b",
        r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b",
        r"/Users/",
        r"/home/[^/\s]+/",
        r"[a-z]:\\Users\\",
        r"\.claude/skills",
        r"(?:\.\./)+tools/",
    )
    for path in SKILL_DIR.rglob("*"):
        if not path.is_file() or path.suffix not in {".md", ".ts", ".json", ".mjs"}:
            continue
        content = read(path)
        for pattern in forbidden_patterns:
            assert not re.search(pattern, content, flags=re.IGNORECASE), (
                f"Local or pilot-specific content in {path.relative_to(SKILL_DIR)}: "
                f"{pattern}"
            )


def test_repository_documents_skill() -> None:
    readme = read(ROOT_DIR / "README.md")
    claude = read(ROOT_DIR / "CLAUDE.md")

    assert "skills/xbsl-playwright/SKILL.md" in readme
    assert "Node.js" in readme and "@playwright/test" in readme
    assert re.search(r"^### xbsl-playwright$", claude, flags=re.MULTILINE)


def test_node_dependencies_are_not_added_to_repository_root() -> None:
    for name in (
        "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
        "bun.lock", "bun.lockb", "node_modules",
    ):
        assert not (ROOT_DIR / name).exists(), f"Unexpected root Node dependency: {name}"
