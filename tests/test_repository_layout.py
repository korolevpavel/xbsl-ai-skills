from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT_DIR / "skills"
EXPECTED_SKILLS = {
    "xbsl-access-set",
    "xbsl-deploy",
    "xbsl-explore",
    "xbsl-file-add",
    "xbsl-form-add",
    "xbsl-form-cards",
    "xbsl-form-dashboard",
    "xbsl-form-info",
    "xbsl-image-add",
    "xbsl-init",
    "xbsl-lib-connect",
    "xbsl-meta-add",
    "xbsl-pattern-register",
    "xbsl-pattern-rls",
    "xbsl-rename",
    "xbsl-scheduled-task",
    "xbsl-subsystem-add",
    "xbsl-uuid",
    "xbsl-validate",
}


def test_top_level_skills_is_the_only_canonical_source_layout() -> None:
    actual = {
        path.name
        for path in SKILLS_ROOT.iterdir()
        if path.is_dir() and (path / "SKILL.md").is_file()
    }

    assert actual == EXPECTED_SKILLS
    assert not (ROOT_DIR / ".claude" / "skills").exists()


def test_shared_xbsl_contract_is_outside_claude_runtime_settings() -> None:
    assert (ROOT_DIR / "docs" / "xbsl-spec.md").is_file()
    assert not (ROOT_DIR / ".claude" / "xbsl-spec.md").exists()


def test_runtime_evidence_ignore_rules_follow_canonical_source_layout() -> None:
    ignore_text = (ROOT_DIR / ".gitignore").read_text(encoding="utf-8")

    assert "skills/*/runtime-evidence/" in ignore_text
    assert "skills/*/references/evidence/" in ignore_text
    assert ".claude/settings.local.json" in ignore_text
    assert ".claude/skills/*/runtime-evidence/" not in ignore_text
