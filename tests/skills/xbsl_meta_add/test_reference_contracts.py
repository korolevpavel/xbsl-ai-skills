from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPOSITORY_ROOT / ".claude/skills/xbsl-meta-add/examples"
REFERENCES = REPOSITORY_ROOT / ".claude/skills/xbsl-meta-add/references"
FORM_SKILL = REPOSITORY_ROOT / ".claude/skills/xbsl-form-add/SKILL.md"
FORM_REPORT_REFERENCE = (
    REPOSITORY_ROOT / ".claude/skills/xbsl-form-add/references/ФормаОтчета.md"
)

REPORT_YAML = (EXAMPLES / "ОтчетОборотыПродаж.yaml").read_text()
REPORT_XBQL = (EXAMPLES / "ОтчетОборотыПродаж.xbql").read_text()


def top_level_keys(text: str) -> set[str]:
    return {
        match.group("key")
        for line in text.splitlines()
        if (match := re.match(r"^(?P<key>[^\s#:][^:]*):", line))
    }


def report_parameter_names(text: str) -> set[str]:
    parameters = re.search(
        r"(?m)^ПараметрыЗапроса:\s*\n(?P<body>(?:^[ \t]+.*\n?)*)", text
    )
    if parameters is None:
        return set()
    return set(re.findall(r"(?m)^\s*Имя:\s*([^\s#]+)", parameters.group("body")))


def xbql_parameter_names(text: str) -> set[str]:
    return set(re.findall(r"&([A-Za-zА-Яа-я_][\w]*)", text))


def read_reference(name: str) -> str:
    return (REFERENCES / name).read_text()


def report_object_example(text: str) -> str:
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    return next(
        block
        for block in blocks
        if "Форма: <ИмяОтчета>ФормаОтчета" in block
    )


def yaml_example(text: str, fragment: str) -> str:
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    return next(block for block in blocks if fragment in block)


def test_report_root_properties_are_not_nested_under_interface():
    assert {"ВключатьВАвтоИнтерфейс", "Форма"} <= top_level_keys(REPORT_YAML)
    assert re.search(r"(?m)^Интерфейс:\s*$", REPORT_YAML) is None


def test_report_reference_keeps_properties_at_report_root():
    example = yaml_example(read_reference("Отчет.md"), "Форма: ФормаОтчета")
    assert {"ВключатьВАвтоИнтерфейс", "Форма"} <= top_level_keys(example)
    assert re.search(r"(?m)^Интерфейс:\s*$", example) is None


def test_report_and_xbql_parameter_sets_are_equal():
    assert report_parameter_names(REPORT_YAML) == xbql_parameter_names(REPORT_XBQL)
    assert report_parameter_names(REPORT_YAML) == {"НачалоПериода"}


def test_accumulation_virtual_fields_use_russian_suffixes():
    report_reference = read_reference("Отчет.md")
    for suffix in ("Оборот", "Приход", "Расход"):
        assert f"<ИмяРесурса>{suffix}" in report_reference
    assert "Turnover" not in report_reference
    assert "Turnover" not in REPORT_XBQL


def test_report_form_consumers_keep_properties_at_report_root():
    for consumer in (FORM_SKILL.read_text(), FORM_REPORT_REFERENCE.read_text()):
        example = report_object_example(consumer)
        assert {"ВключатьВАвтоИнтерфейс", "Форма"} <= top_level_keys(example)
        assert re.search(r"(?m)^Интерфейс:\s*$", example) is None
