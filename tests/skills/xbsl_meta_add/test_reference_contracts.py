from pathlib import Path
import re

import pytest


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


def has_root_interface_wrapper(text: str) -> bool:
    return re.search(r"(?m)^Интерфейс[ \t]*:", text) is not None


def yaml_field_blocks(text: str) -> list[str]:
    """Return direct properties of developer-field YAML mappings in examples."""
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    fields = []
    for block in blocks:
        lines = block.splitlines()
        standalone = "\n".join(
            line.strip()
            for line in lines
            if re.match(r"^[^\s#][^:]*:\s*.*$", line)
        )
        if re.search(r"(?m)^Тип:", standalone):
            fields.append(standalone)

        for index, line in enumerate(lines):
            match = re.match(r"^(?P<indent>\s*)-\s*(?P<inline>.*)$", line)
            if match is None:
                continue

            item_indent = len(match.group("indent"))
            properties = [match.group("inline")]
            property_indent = None
            for following_line in lines[index + 1 :]:
                next_match = re.match(r"^(?P<indent>\s*)-\s*", following_line)
                next_indent = len(following_line) - len(following_line.lstrip())
                if next_match is not None and next_indent <= item_indent:
                    break
                if not following_line.strip():
                    continue
                if property_indent is None:
                    property_indent = next_indent
                if next_indent == property_indent:
                    properties.append(following_line.strip())

            field = "\n".join(properties)
            if "Тип:" in field:
                fields.append(field)
    return fields


def empty_value_policy_is_valid(text: str) -> bool:
    return all(
        "НезаполненноеЗначение" not in field
        or re.search(r"(?m)^Тип:\s*Строка\s*(?:#.*)?$", field)
        for field in yaml_field_blocks(text)
    )


@pytest.mark.parametrize(
    "wrapper",
    [
        "Интерфейс: { Форма: ФормаОтчета }",
        "Интерфейс: # запрещенный root-wrapper",
    ],
)
def test_report_root_interface_wrapper_check_detects_inline_forms(wrapper: str):
    assert has_root_interface_wrapper(wrapper)


def test_report_root_properties_are_not_nested_under_interface():
    assert {"ВключатьВАвтоИнтерфейс", "Форма"} <= top_level_keys(REPORT_YAML)
    assert not has_root_interface_wrapper(REPORT_YAML)


def test_report_reference_keeps_properties_at_report_root():
    example = yaml_example(read_reference("Отчет.md"), "Форма: ФормаОтчета")
    assert {"ВключатьВАвтоИнтерфейс", "Форма"} <= top_level_keys(example)
    assert not has_root_interface_wrapper(example)


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
        assert not has_root_interface_wrapper(example)


def test_information_register_key_and_leading_dimension_are_distinct():
    text = read_reference("РегистрСведений.md")
    assert "Все измерения образуют ключ записи" in text
    assert "каскад" in text.lower()
    assert "минимум одно измерение должно быть ведущим" not in text.lower()
    assert "ведущие измерения образуют первичный ключ" not in text.lower()


def test_generic_field_contract_does_not_advertise_uniqueness():
    assert "`Уникальность`" not in read_reference("types.md")


def test_catalog_name_can_define_empty_value_policy():
    text = read_reference("Справочник.md")
    assert "Наименование" in text
    assert "НезаполненноеЗначение: Разрешить" in text


def test_presentation_examples_reference_declared_fields():
    assert "Представление: ФИО" not in read_reference("Справочник.md")
    assert "Представление: Наименование" not in read_reference("Документ.md")


def test_uuid_contract_counts_hierarchies_and_lock_spaces():
    catalog = read_reference("Справочник.md")
    document = read_reference("Документ.md")
    assert "ДополнительныеИерархии" in catalog
    assert "ПространстваБлокировок" in catalog
    assert "ПространстваБлокировок" in document


@pytest.mark.parametrize(
    "reference_name",
    [
        "types.md",
        "РегистрСведений.md",
        "РегистрНакопления.md",
        "Документ.md",
        "ТабличныеЧасти.md",
    ],
)
def test_empty_value_policy_is_not_applied_to_reference_fields(reference_name: str):
    assert empty_value_policy_is_valid(read_reference(reference_name))


def test_empty_value_policy_rejects_concrete_reference_list_item():
    text = """```yaml
Реквизиты:
    - Ид: <UUID>
      Имя: Контрагент
      Тип: Контрагенты.Ссылка?
      НезаполненноеЗначение: ЗапретитьВсегда
```"""

    assert not empty_value_policy_is_valid(text)


def test_empty_value_policy_rejects_standalone_non_string_mapping():
    text = """```yaml
Тип: Число
НезаполненноеЗначение: ЗапретитьВсегда
```"""

    assert not empty_value_policy_is_valid(text)
