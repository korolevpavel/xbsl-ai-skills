from __future__ import annotations

import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
SKILL_ROOT = ROOT_DIR / "skills/xbsl-form-dashboard"
REFERENCES = SKILL_ROOT / "references"


def read_reference(name: str) -> str:
    return (REFERENCES / name).read_text(encoding="utf-8")


def fenced_blocks(text: str) -> list[tuple[str, str]]:
    return [
        (match.group("language").casefold(), match.group("body"))
        for match in re.finditer(
            r"```(?P<language>[^\r\n]*)\r?\n(?P<body>.*?)```",
            text,
            re.DOTALL,
        )
    ]


def test_replace_null_is_explicitly_query_only_with_positive_and_negative_examples() -> None:
    template = read_reference("xbsl-шаблон.md")
    normalized = " ".join(template.split())

    assert "функция языка запросов" in template.casefold()
    assert "только внутри `Запрос{...}` или отдельного `.xbql`" in normalized
    assert "не является методом XBSL" in template
    assert "```xbql\nВЫБРАТЬ\n    Поле.ЗаменитьNull(0) КАК Поле" in template
    assert (
        "// ❌ Недопустимо: у XBSL-значения нет метода ЗаменитьNull.\n"
        "знч Значение = Результат.ЗаменитьNull(0)"
    ) in template
    assert "Значение ?? 0" in template


def test_replace_null_calls_are_not_recommended_as_ordinary_xbsl_instance_api() -> None:
    violations: list[str] = []
    for path in sorted(SKILL_ROOT.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for language, body in fenced_blocks(text):
            if ".ЗаменитьNull(" not in body:
                continue
            valid_query_context = language == "xbql" or "Запрос{" in body
            explicit_invalid_example = (
                language == "xbsl"
                and "❌ Недопустимо" in body
                and "нет метода ЗаменитьNull" in body
            )
            if not valid_query_context and not explicit_invalid_example:
                violations.append(
                    f"{path.relative_to(SKILL_ROOT)}: {language or '<plain>'}"
                )

    assert not violations, "Ordinary XBSL instance API examples found: " + ", ".join(violations)


def test_every_dashboard_reference_qualifies_replace_null_as_query_language() -> None:
    mentions = []
    for path in sorted(SKILL_ROOT.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        if "ЗаменитьNull" in text:
            mentions.append((path.relative_to(SKILL_ROOT).as_posix(), text))

    assert {name for name, _text in mentions} == {
        "references/p3-таблица.md",
        "references/p5-диаграмма.md",
        "references/xbsl-шаблон.md",
    }
    for name, text in mentions:
        prose = re.sub(r"```[^\r\n]*\r?\n.*?```", "", text, flags=re.DOTALL)
        mention_paragraphs = [
            paragraph
            for paragraph in re.split(r"\r?\n[ \t>]*\r?\n", prose)
            if "ЗаменитьNull" in paragraph
        ]
        assert mention_paragraphs, name
        for paragraph in mention_paragraphs:
            normalized = paragraph.casefold()
            assert "функция языка запросов" in normalized, name
            assert "не является методом xbsl" in normalized, name
