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
ACCESS_SET_PATH = ROOT_DIR / ".claude/skills/xbsl-access-set/SKILL.md"


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


def test_access_key_lifecycle_modes_are_explicit_and_backward_compatible() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")
    reference = REFERENCE_PATH.read_text(encoding="utf-8")

    for mode in ("automatic", "automatic-disabled", "manual"):
        assert mode in skill
        assert mode in reference
    assert "`automatic` — default" in skill
    assert "РучнаяВыдача: Истина" in reference
    assert "ОтключитьСистемныеПересчеты: Истина" in reference


def test_manual_mode_documents_issue_revoke_without_key_recalculation() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")
    reference = REFERENCE_PATH.read_text(encoding="utf-8")

    for api in (".Выдать(", ".Отозвать(", ".ОтозватьКлючи(", "ВыдатьКлючиДоступа("):
        assert api in reference
    assert "В режиме `manual` этот файл с\nhandler не создавай" in skill
    assert "Не предлагай для manual key" in reference


def test_custom_key_parameters_get_uuid_but_owner_does_not() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")
    reference = REFERENCE_PATH.read_text(encoding="utf-8")

    assert "по одному UUID на каждый\nпользовательский параметр" in skill
    assert "Только системный\n> `Владелец` содержит `Имя` и `Тип`, без `Ид`" in reference


def test_access_set_routes_manual_key_requests_to_rls() -> None:
    text = ACCESS_SET_PATH.read_text(encoding="utf-8")
    assert "ручную выдачу или отзыв экземпляров ключа доступа" in text
    assert "`access_state.py` и список поддерживаемых типов не расширяй" in text
