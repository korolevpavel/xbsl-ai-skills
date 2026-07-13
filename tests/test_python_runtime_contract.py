from __future__ import annotations

import re
from pathlib import Path

import pytest

from python_runtime_contract import (
    COMPATIBILITY_LINE,
    DIRECT_PYTHON_SKILLS,
    LAUNCHER_INSTRUCTION,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT_DIR / ".claude" / "skills"

BARE_PYTHON_INVOCATION_RE = re.compile(
    r"(?<![\w{])python(?![\w}])\s+(?:-c\b|[^\s`]*\.py\b)"
)


def skill_path(slug: str) -> Path:
    return SKILLS_DIR / slug / "SKILL.md"


@pytest.mark.parametrize("slug", sorted(DIRECT_PYTHON_SKILLS))
def test_direct_python_skill_declares_scalar_runtime_compatibility(slug: str) -> None:
    text = skill_path(slug).read_text(encoding="utf-8")
    opening, separator, remainder = text.partition("\n---\n")

    assert separator, f"{slug}: frontmatter is missing or unterminated"
    assert opening.startswith("---\n"), f"{slug}: frontmatter must be the first block"
    compatibility_lines = [
        line
        for line in opening[4:].splitlines()
        if re.match(r"^compatibility\s*:", line)
    ]
    assert compatibility_lines == [COMPATIBILITY_LINE]
    assert remainder


@pytest.mark.parametrize("slug", sorted(DIRECT_PYTHON_SKILLS))
def test_direct_python_skill_explains_cross_platform_launcher(slug: str) -> None:
    text = skill_path(slug).read_text(encoding="utf-8")

    assert LAUNCHER_INSTRUCTION in text


def runtime_contract_paths() -> list[Path]:
    paths = [ROOT_DIR / "README.md", ROOT_DIR / "CLAUDE.md"]
    paths.extend(
        path
        for path in SKILLS_DIR.rglob("*")
        if path.is_file() and path.suffix in {".md", ".py"}
    )
    return paths


@pytest.mark.parametrize(
    "line",
    [
        "python scripts/build_site.py",
        "`python tools/check.py --root .`",
        'python -c "print(1)"',
    ],
)
def test_bare_python_invocation_pattern_detects_actionable_commands(line: str) -> None:
    assert BARE_PYTHON_INVOCATION_RE.search(line)


@pytest.mark.parametrize(
    "line",
    [
        "{python} scripts/build_site.py",
        '`{python} -c "print(1)"`',
        "#!/usr/bin/env python3",
        LAUNCHER_INSTRUCTION,
    ],
)
def test_bare_python_invocation_pattern_ignores_portable_and_shebang_lines(line: str) -> None:
    assert not BARE_PYTHON_INVOCATION_RE.search(line)


def test_python3_occurs_only_in_shebangs_or_exact_launcher_instructions() -> None:
    violations: list[str] = []

    for path in runtime_contract_paths():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "python3" not in line:
                continue
            if line == "#!/usr/bin/env python3":
                continue
            if line.strip() == LAUNCHER_INSTRUCTION:
                continue
            relative_path = path.relative_to(ROOT_DIR)
            violations.append(f"{relative_path}:{line_number}: {line.strip()}")

    assert not violations, "Unexpected python3 references:\n" + "\n".join(violations)


def test_actionable_python_invocations_use_cross_platform_placeholder() -> None:
    violations: list[str] = []

    for path in runtime_contract_paths():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not BARE_PYTHON_INVOCATION_RE.search(line):
                continue
            relative_path = path.relative_to(ROOT_DIR)
            violations.append(f"{relative_path}:{line_number}: {line.strip()}")

    assert not violations, "Bare python invocations must use {python}:\n" + "\n".join(violations)


def test_claude_md_documents_cross_platform_skill_development() -> None:
    text = (ROOT_DIR / "CLAUDE.md").read_text(encoding="utf-8")
    marker = "### Кроссплатформенность\n"

    assert marker in text
    section = text.split(marker, maxsplit=1)[1].split("\n### ", maxsplit=1)[0]
    assert LAUNCHER_INSTRUCTION in section
    required_fragments = (
        "`{python}`",
        "`sys.executable`",
        "`pathlib`",
        "`tempfile`",
        "`/tmp`",
        "Bash",
        "PowerShell",
        '`encoding="utf-8"`',
        f"`{COMPATIBILITY_LINE}`",
        "`LAUNCHER_INSTRUCTION`",
        "`DIRECT_PYTHON_SKILLS`",
        "контрактные тесты",
    )

    for fragment in required_fragments:
        assert fragment in section
