from __future__ import annotations

import json
import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
INIT_SKILL = ROOT_DIR / ".claude/skills/xbsl-init/SKILL.md"
DEPLOY_SKILL = ROOT_DIR / ".claude/skills/xbsl-deploy/SKILL.md"
FIXTURE_DIR = Path(__file__).parent / "fixtures/compatibility_9_1_technology_9_2"


def _compatibility_mode(project_yaml: str) -> str:
    match = re.search(r"(?m)^РежимСовместимости:\s*([^\s#]+)", project_yaml)
    assert match is not None
    return match.group(1).strip('"\'')


def test_regression_fixture_keeps_compatibility_and_technology_independent() -> None:
    project_yaml = (FIXTURE_DIR / "Проект.yaml").read_text(encoding="utf-8")
    application = json.loads((FIXTURE_DIR / "application.json").read_text(encoding="utf-8"))

    compatibility_mode = _compatibility_mode(project_yaml)
    technology_version = application["technology-version"]

    assert compatibility_mode == "9.1"
    assert technology_version == "9.2.9-12"
    assert re.fullmatch(r"\d+\.\d+", compatibility_mode)
    assert re.fullmatch(r"\d+\.\d+\.\d+-\d+", technology_version)


def test_init_contract_preserves_explicit_compatibility_mode() -> None:
    skill = INIT_SKILL.read_text(encoding="utf-8")

    assert "xbsl-init.compatibility_mode_format" in skill
    assert "9.1" in skill
    assert "9.2.9-12" in skill
    assert "не выводи" in skill.lower()
    assert "сохран" in skill.lower()


def test_deploy_contract_does_not_rewrite_project_compatibility_mode() -> None:
    skill = DEPLOY_SKILL.read_text(encoding="utf-8")

    assert "deploy.technology_version_format" in skill
    assert "9.1" in skill
    assert "9.2.9-12" in skill
    assert "Проект.yaml" in skill
    assert "не измен" in skill.lower()
    assert "не сравнив" in skill.lower()
