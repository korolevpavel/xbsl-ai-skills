import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT_DIR / ".claude" / "xbsl-spec.md"
SPEC_REFERENCE = ".claude/xbsl-spec.md"
XBSL_GENERATING_SKILLS = (
    "xbsl-init",
    "xbsl-meta-add",
    "xbsl-pattern-register",
    "xbsl-pattern-rls",
    "xbsl-image-add",
    "xbsl-form-dashboard",
    "xbsl-scheduled-task",
)
LEGACY_XBSL_SYNTAX = re.compile(
    r"\b(?:КонецЕсли|КонецЦикла|КонецПопытки|ИначеЕсли|Тогда|Процедура|Функция)\b",
    re.IGNORECASE,
)
OBSOLETE_META_ADD_APIS = (
    "Приложение.ВызватьГлобальноеКлиентскоеСобытие",
    "Приложение.ПодписатьсяНаГлобальноеКлиентскоеСобытие",
    "ФоматСтроки",
    "Доступ.ПроверитьКлюч",
)


def xbsl_code_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] | None = None

    for line in text.splitlines():
        if current is None:
            if line.strip() in {"```xbsl", "```bsl"}:
                current = []
        elif line.strip() == "```":
            blocks.append("\n".join(current))
            current = None
        else:
            current.append(line)

    return blocks


def test_xbsl_spec_defines_required_syntax_contract() -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")

    for required_text in (
        "XBSL",
        "9.3",
        "метод",
        "знч",
        "пер",
        "если",
        "иначе",
        "выбор",
        "когда",
        "для",
        "пока",
        "попытка",
        "поймать",
        "вконце",
        "импорт",
        "Массив",
        "Соответствие",
        "Неопределено",
        "КонецЕсли",
        "КонецЦикла",
    ):
        assert required_text in text

    assert "`исключение` объявляет собственный тип исключения" in text
    assert "для перехвата используй `поймать`" in text
    assert "`%{Выражение}` вызывает `ВСтроку()`" in text
    assert "`${Выражение}` — `Представление()`" in text
    assert len(text.splitlines()) <= 140


def test_xbsl_generating_instructions_link_to_shared_spec() -> None:
    paths = [ROOT_DIR / "CLAUDE.md"]
    paths.extend(
        ROOT_DIR / ".claude" / "skills" / skill / "SKILL.md"
        for skill in XBSL_GENERATING_SKILLS
    )

    for path in paths:
        assert SPEC_REFERENCE in path.read_text(encoding="utf-8"), path


def test_xbsl_generating_skills_do_not_contain_legacy_code_examples() -> None:
    for skill in XBSL_GENERATING_SKILLS:
        skill_dir = ROOT_DIR / ".claude" / "skills" / skill
        for path in skill_dir.rglob("*.md"):
            for block in xbsl_code_blocks(path.read_text(encoding="utf-8")):
                assert LEGACY_XBSL_SYNTAX.search(block) is None, path


def test_xbsl_meta_add_examples_do_not_contain_obsolete_apis() -> None:
    skill_dir = ROOT_DIR / ".claude" / "skills" / "xbsl-meta-add"
    for path in skill_dir.rglob("*.md"):
        for block in xbsl_code_blocks(path.read_text(encoding="utf-8")):
            for api in OBSOLETE_META_ADD_APIS:
                assert api not in block, path


def test_obsolete_global_event_apis_are_scanned() -> None:
    assert {
        "Приложение.ВызватьГлобальноеКлиентскоеСобытие",
        "Приложение.ПодписатьсяНаГлобальноеКлиентскоеСобытие",
    } <= set(OBSOLETE_META_ADD_APIS)
