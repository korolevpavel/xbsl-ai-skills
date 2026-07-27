from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from python_runtime_contract import DIRECT_PYTHON_SKILLS, PYTHON_RUNTIME_LABEL


ROOT_DIR = Path(__file__).resolve().parents[1]
BUILD_SITE_PATH = ROOT_DIR / "scripts" / "build_site.py"


def load_build_site_module():
    spec = importlib.util.spec_from_file_location("build_site_under_test", BUILD_SITE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load module spec for {BUILD_SITE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


build_site = load_build_site_module()


def collect_actual_skills():
    readme_text = build_site.README_PATH.read_text(encoding="utf-8")
    skill_paths = list(build_site.SKILLS_ROOT.glob("*/SKILL.md"))
    page_map = build_site.build_page_map(skill_paths)
    return build_site.collect_skills(readme_text, page_map)


def test_parse_frontmatter_normalizes_scalar_python_requirement() -> None:
    frontmatter = "compatibility: Requires Python 3."

    assert build_site.parse_frontmatter(frontmatter)["runtime"] == [PYTHON_RUNTIME_LABEL]


def test_parse_frontmatter_normalizes_legacy_nested_python3_requirement() -> None:
    frontmatter = """\
compatibility:
  runtime:
    - python3
"""

    assert build_site.parse_frontmatter(frontmatter)["runtime"] == [PYTHON_RUNTIME_LABEL]


def test_collect_skills_normalizes_runtime_for_all_direct_python_skills() -> None:
    skills = collect_actual_skills()
    runtime_by_slug = {
        skill.slug: skill.runtime
        for skill in skills
        if skill.slug in DIRECT_PYTHON_SKILLS
    }

    assert set(runtime_by_slug) == DIRECT_PYTHON_SKILLS
    assert runtime_by_slug == {
        slug: [PYTHON_RUNTIME_LABEL] for slug in DIRECT_PYTHON_SKILLS
    }


def test_collect_skills_never_exposes_literal_python3_runtime_labels() -> None:
    skills = collect_actual_skills()
    violations = [
        f"{skill.slug}: {label}"
        for skill in skills
        for label in skill.runtime
        if "python3" in label.casefold()
    ]

    assert not violations, "Literal python3 runtime labels:\n" + "\n".join(violations)
