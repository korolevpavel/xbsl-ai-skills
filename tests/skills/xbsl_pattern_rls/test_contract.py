from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
SKILL_PATH = ROOT_DIR / ".claude/skills/xbsl-pattern-rls/SKILL.md"
REFERENCE_PATH = ROOT_DIR / ".claude/skills/xbsl-pattern-rls/references/rls-паттерны.md"
POSITIVE_FIXTURES_DIR = ROOT_DIR / "tests/skills/xbsl_pattern_rls/fixtures/positive"
FIXTURE_PATH = (
    ROOT_DIR
    / "tests/skills/xbsl_pattern_rls/fixtures/positive/document_before_write/ЗаказКлиента.Объект.xbsl"
)


def test_public_contract_does_not_name_unsupported_before_write_handler() -> None:
    public_paths = [
        SKILL_PATH,
        *(path for path in REFERENCE_PATH.parent.rglob("*") if path.is_file()),
        *(path for path in POSITIVE_FIXTURES_DIR.rglob("*") if path.is_file()),
    ]

    for path in public_paths:
        assert "ДоЗаписи" not in path.read_text(encoding="utf-8"), path


def test_document_before_write_fixture_uses_documented_signature() -> None:
    source = FIXTURE_PATH.read_text(encoding="utf-8")
    expected = (
        "@Обработчик\n"
        "метод ПередЗаписью(\n"
        "    До: ЗаказКлиента.Данные,\n"
        "    ПараметрыЗаписи: ЗаказКлиента.ПараметрыЗаписи)\n"
        ";\n"
    )

    assert source == expected
