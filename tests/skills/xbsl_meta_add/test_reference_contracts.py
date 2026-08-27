from pathlib import Path
import re
import sys

import pytest
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT / "tests"))
from test_xbsl_spec_contract import xbsl_code_blocks

EXAMPLES = REPOSITORY_ROOT / ".claude/skills/xbsl-meta-add/examples"
REFERENCES = REPOSITORY_ROOT / ".claude/skills/xbsl-meta-add/references"
FORM_SKILL = REPOSITORY_ROOT / ".claude/skills/xbsl-form-add/SKILL.md"
FORM_REPORT_REFERENCE = (
    REPOSITORY_ROOT / ".claude/skills/xbsl-form-add/references/ФормаОтчета.md"
)
REPORT_FIXTURES = (
    Path(__file__).resolve().parent / "fixtures" / "contracts-and-reports"
)

REPORT_YAML_PATH = EXAMPLES / "ОтчетОборотыПродаж.yaml"
REPORT_XBQL_PATH = EXAMPLES / "ОтчетОборотыПродаж.xbql"
REPORT_YAML = REPORT_YAML_PATH.read_text()
REPORT_XBQL = REPORT_XBQL_PATH.read_text()
CATALOG_UUID_TERMS = {
    "объект",
    "пользовательские реквизиты",
    "табличные части",
    "реквизиты табличных частей",
    "дополнительные иерархии",
    "пространства блокировок",
}
DOCUMENT_UUID_TERMS = CATALOG_UUID_TERMS - {"дополнительные иерархии"}


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


def yaml_blocks_or_text(text: str) -> list[str]:
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    return blocks or [text]


def root_scalar(text: str, key: str) -> str | None:
    match = re.search(
        rf"(?m)^{re.escape(key)}:\s*(?P<value>[^#\n]*?)\s*(?:#.*)?$", text
    )
    if match is None:
        return None
    return match.group("value").strip()


def assert_report_interface_properties_are_not_top_level(data: dict) -> None:
    assert "ВключатьВАвтоИнтерфейс" not in data, "auto-interface must be nested"
    assert "Форма" not in data, "custom report form must be nested"


def assert_query_report_companion(yaml_path: Path) -> Path:
    text = yaml_path.read_text(encoding="utf-8")
    name = root_scalar(text, "Имя")

    assert root_scalar(text, "ВидИсточникаДанных") == "Запрос"
    assert "Запрос" not in top_level_keys(text)
    assert name and yaml_path.stem == name
    query_path = yaml_path.with_suffix(".xbql")
    assert query_path.is_file(), "same-name .xbql companion is required"
    assert query_path.read_text(encoding="utf-8").strip(), "query must not be empty"
    return query_path


def yaml_list_item_mappings(text: str, key: str) -> list[dict[str, str]]:
    """Parse direct scalar properties of root-level YAML list items."""
    lines = text.splitlines()
    section_index = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(rf"^{re.escape(key)}:\s*(?:#.*)?$", line)
        ),
        None,
    )
    if section_index is None:
        return []

    section_lines: list[str] = []
    for line in lines[section_index + 1 :]:
        if line and not line.startswith((" ", "\t")):
            break
        section_lines.append(line)

    item_indents = [
        len(match.group("indent"))
        for line in section_lines
        if (match := re.match(r"^(?P<indent>\s*)-\s*", line))
    ]
    if not item_indents:
        return []
    item_indent = min(item_indents)
    item_starts = [
        index
        for index, line in enumerate(section_lines)
        if re.match(rf"^\s{{{item_indent}}}-\s*", line)
    ]

    items: list[dict[str, str]] = []
    for position, start in enumerate(item_starts):
        end = item_starts[position + 1] if position + 1 < len(item_starts) else len(
            section_lines
        )
        item_lines = section_lines[start:end]
        inline = re.match(r"^\s*-\s*(?P<property>.*)$", item_lines[0]).group(
            "property"
        )
        properties: dict[str, str] = {}
        if inline:
            property_match = re.match(
                r"^(?P<key>[^:#]+):\s*(?P<value>[^#]*?)\s*(?:#.*)?$", inline
            )
            if property_match:
                properties[property_match.group("key").strip()] = property_match.group(
                    "value"
                ).strip()

        property_indents = [
            len(match.group("indent"))
            for line in item_lines[1:]
            if (
                match := re.match(
                    r"^(?P<indent>\s+)(?P<key>[^:#]+):\s*(?P<value>[^#]*?)"
                    r"\s*(?:#.*)?$",
                    line,
                )
            )
        ]
        if property_indents:
            property_indent = min(property_indents)
            for line in item_lines[1:]:
                property_match = re.match(
                    rf"^\s{{{property_indent}}}(?P<key>[^:#]+):"
                    r"\s*(?P<value>[^#]*?)\s*(?:#.*)?$",
                    line,
                )
                if property_match:
                    properties[property_match.group("key").strip()] = property_match.group(
                        "value"
                    ).strip()
        items.append(properties)

    return items


def object_presentation_references_declared_requisite(text: str) -> bool:
    presentation = root_scalar(text, "Представление")
    if presentation is None:
        return True
    requisite_names = {
        item["Имя"]
        for item in yaml_list_item_mappings(text, "Реквизиты")
        if "Имя" in item
    }
    return presentation in requisite_names


def uuid_formula_terms(text: str, object_kind: str) -> set[str]:
    uuid_section = re.search(
        r"(?ms)^## UUID\s*$\n(?P<body>.*?)(?=^## |\Z)", text
    )
    if uuid_section is None:
        return set()

    section_lines = uuid_section.group("body").splitlines()
    formula_start = next(
        (
            index
            for index, line in enumerate(section_lines)
            if re.match(rf"^{re.escape(object_kind)}\s*=", line)
        ),
        None,
    )
    if formula_start is None:
        return set()

    formula_lines = [section_lines[formula_start]]
    for line in section_lines[formula_start + 1 :]:
        if not re.match(r"^\s*\+", line):
            break
        formula_lines.append(line)
    formula = " ".join(formula_lines).split("=", maxsplit=1)[1]
    return {
        re.sub(r"\s+", " ", term).strip().casefold()
        for term in formula.split("+")
        if term.strip()
    }


def yaml_reference_list_items_have_ids(text: str, key: str) -> bool:
    items = [
        item
        for block in yaml_blocks_or_text(text)
        for item in yaml_list_item_mappings(block, key)
    ]
    return bool(items) and all("Ид" in item for item in items)


def access_parameter_shapes_are_valid(text: str) -> bool:
    items = [
        item
        for block in yaml_blocks_or_text(text)
        for item in yaml_list_item_mappings(block, "Параметры")
    ]
    owners = [item for item in items if item.get("Имя") == "Владелец"]
    developer_parameters = [
        item for item in items if item.get("Имя") not in {None, "Владелец"}
    ]
    return (
        len(owners) == 1
        and set(owners[0]) == {"Имя", "Тип"}
        and any(
            {"Ид", "Имя", "Тип"} <= set(parameter)
            for parameter in developer_parameters
        )
    )


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


def test_report_auto_interface_property_is_nested_under_interface():
    data = yaml.safe_load(REPORT_YAML)

    assert data["Интерфейс"]["ВключатьВАвтоИнтерфейс"] == "Истина"
    assert "Форма" not in data["Интерфейс"]
    assert_report_interface_properties_are_not_top_level(data)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ВключатьВАвтоИнтерфейс", "Истина", "auto-interface must be nested"),
        ("Форма", "ПродажиФормаОтчета", "custom report form must be nested"),
    ],
)
def test_legacy_top_level_report_interface_properties_are_rejected(
    field: str, value: str, message: str
):
    data = yaml.safe_load(
        f"ВидЭлемента: Отчет\nИмя: Продажи\n{field}: {value}\nИнтерфейс: {{}}\n"
    )

    with pytest.raises(AssertionError, match=message):
        assert_report_interface_properties_are_not_top_level(data)


def test_report_reference_nests_auto_interface_property():
    example = yaml_example(read_reference("Отчет.md"), "ВидИсточникаДанных: Запрос")
    data = yaml.safe_load(example)

    assert data["Интерфейс"]["ВключатьВАвтоИнтерфейс"] == "Истина"
    assert "Форма" not in data["Интерфейс"]
    assert_report_interface_properties_are_not_top_level(data)


def test_report_reference_keeps_custom_form_independently():
    example = yaml_example(
        read_reference("Отчет.md"), "Форма: <ИмяОтчета>ФормаОтчета"
    )
    data = yaml.safe_load(example)

    assert data["Интерфейс"] == {"Форма": "<ИмяОтчета>ФормаОтчета"}
    assert_report_interface_properties_are_not_top_level(data)


def test_report_and_xbql_parameter_sets_are_equal():
    assert report_parameter_names(REPORT_YAML) == xbql_parameter_names(REPORT_XBQL)
    assert report_parameter_names(REPORT_YAML) == {"НачалоПериода"}


def test_query_report_uses_implicit_same_name_xbql_companion():
    assert root_scalar(REPORT_YAML, "ВидИсточникаДанных") == "Запрос"
    assert "Запрос" not in top_level_keys(REPORT_YAML)
    assert REPORT_YAML_PATH.stem == root_scalar(REPORT_YAML, "Имя")
    assert REPORT_XBQL_PATH.stem == REPORT_YAML_PATH.stem
    assert REPORT_XBQL.strip()
    assert assert_query_report_companion(REPORT_YAML_PATH) == REPORT_XBQL_PATH


def test_positive_report_yaml_never_declares_query_file_as_a_property():
    candidates = list(EXAMPLES.glob("*.yaml")) + list(
        (REPORT_FIXTURES / "positive").rglob("*.yaml")
    )
    report_paths = [
        path
        for path in candidates
        if root_scalar(path.read_text(encoding="utf-8"), "ВидЭлемента") == "Отчет"
    ]

    assert report_paths
    for path in report_paths:
        assert "Запрос" not in top_level_keys(path.read_text(encoding="utf-8")), path


def test_report_reference_query_example_uses_implicit_xbql_companion():
    reference = read_reference("Отчет.md")
    example = yaml_example(reference, "ВидИсточникаДанных: Запрос")

    assert "Запрос" not in top_level_keys(example)
    assert "одноименный" in reference
    assert "непуст" in reference


@pytest.mark.parametrize("case", ["missing_query", "misnamed_query"])
def test_missing_or_misnamed_query_report_companion_is_rejected(case: str):
    yaml_path = REPORT_FIXTURES / "negative" / "Отчет" / case / "Продажи.yaml"
    query_files = list(yaml_path.parent.glob("*.xbql"))

    if case == "misnamed_query":
        assert len(query_files) == 1
        assert query_files[0].stem != root_scalar(
            yaml_path.read_text(encoding="utf-8"), "Имя"
        )
    else:
        assert query_files == []

    with pytest.raises(AssertionError, match="same-name .xbql companion is required"):
        assert_query_report_companion(yaml_path)


def test_report_reference_requires_exact_query_parameter_set_unconditionally():
    text = read_reference("Отчет.md")
    assert "пользователь явно указал параметры" not in text
    assert "только по явному запросу пользователя" not in text
    assert (
        "каждый сгенерированный параметр `&Имя` в XBQL всегда имеет ровно один "
        "соответствующий элемент `ПараметрыЗапроса`, независимо от того, как "
        "возникло требование к запросу; лишние элементы запрещены"
    ) in text
    assert (
        "Если XBQL не содержит параметров, `ПараметрыЗапроса` отсутствует"
    ) in text
    assert (
        "`set(имена &параметров в XBQL) == set(имена элементов "
        "ПараметрыЗапроса)`"
    ) in text


def test_accumulation_virtual_fields_use_russian_suffixes():
    report_reference = read_reference("Отчет.md")
    for suffix in ("Оборот", "Приход", "Расход"):
        assert f"<ИмяРесурса>{suffix}" in report_reference
    assert "Turnover" not in report_reference
    assert "Turnover" not in REPORT_XBQL


def test_report_form_consumers_nest_auto_interface_property():
    for consumer in (FORM_SKILL.read_text(), FORM_REPORT_REFERENCE.read_text()):
        data = yaml.safe_load(report_object_example(consumer))
        assert data["Интерфейс"]["ВключатьВАвтоИнтерфейс"] == "Истина"
        assert_report_interface_properties_are_not_top_level(data)


def test_report_form_consumers_keep_custom_form_independently():
    for consumer in (FORM_SKILL.read_text(), FORM_REPORT_REFERENCE.read_text()):
        data = yaml.safe_load(report_object_example(consumer))
        assert data["Интерфейс"]["Форма"] == "<ИмяОтчета>ФормаОтчета"
        assert_report_interface_properties_are_not_top_level(data)


def test_information_register_key_and_leading_dimension_are_distinct():
    text = read_reference("РегистрСведений.md")
    assert "Все измерения образуют ключ записи" in text
    assert "каскад" in text.lower()
    assert "минимум одно измерение должно быть ведущим" not in text.lower()
    assert "ведущие измерения образуют первичный ключ" not in text.lower()


def test_information_register_documents_leading_default_and_explicit_false():
    text = read_reference("РегистрСведений.md")
    assert "`Ведущее` — `Истина` по умолчанию" in text
    assert (
        "Для каждого ссылочного измерения без каскадного удаления явно указывай "
        "`Ведущее: Ложь`"
    ) in text

    examples = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
    reference_dimensions = [
        item
        for example in examples
        for item in yaml_list_item_mappings(example, "Измерения")
        if ".Ссылка" in item.get("Тип", "")
    ]
    assert any(
        {item.get("Ведущее") for item in yaml_list_item_mappings(example, "Измерения")}
        == {"Истина", "Ложь"}
        for example in examples
    )
    assert all("Ведущее" in item for item in reference_dimensions)


def test_generic_field_contract_does_not_advertise_uniqueness():
    assert "`Уникальность`" not in read_reference("types.md")


def test_catalog_name_can_define_empty_value_policy():
    text = read_reference("Справочник.md")
    assert "Наименование" in text
    assert "НезаполненноеЗначение: Разрешить" in text


@pytest.mark.parametrize(
    ("reference_name", "object_kind"),
    [("Справочник.md", "Справочник"), ("Документ.md", "Документ")],
)
def test_object_presentations_reference_requisites_declared_by_same_example(
    reference_name: str, object_kind: str
):
    examples = [
        block
        for block in re.findall(
            r"```yaml\n(.*?)```", read_reference(reference_name), re.DOTALL
        )
        if re.search(rf"(?m)^ВидЭлемента:\s*{object_kind}\s*$", block)
    ]
    assert examples
    assert all(
        object_presentation_references_declared_requisite(example)
        for example in examples
    )


@pytest.mark.parametrize(
    ("example", "expected"),
    [
        (
            """ВидЭлемента: Справочник
Представление: Заголовок
Реквизиты:
    - Имя: Заголовок
""",
            True,
        ),
        (
            """ВидЭлемента: Документ
Реквизиты:
    - Имя: Номер
""",
            True,
        ),
        (
            """ВидЭлемента: Документ
Представление: НеОбъявлено
Реквизиты:
    - Имя: Номер
""",
            False,
        ),
    ],
)
def test_object_presentation_check_handles_declared_omitted_and_dangling_fields(
    example: str, expected: bool
):
    assert object_presentation_references_declared_requisite(example) is expected


@pytest.mark.parametrize(
    ("reference_name", "object_kind", "expected_terms"),
    [
        ("Справочник.md", "Справочник", CATALOG_UUID_TERMS),
        ("Документ.md", "Документ", DOCUMENT_UUID_TERMS),
    ],
)
def test_uuid_formula_has_exact_normalized_terms(
    reference_name: str, object_kind: str, expected_terms: set[str]
):
    assert uuid_formula_terms(
        read_reference(reference_name), object_kind
    ) == expected_terms


def test_uuid_formula_check_rejects_a_missing_term():
    incomplete_formula = """## UUID

Документ = объект + пользовательские реквизиты + табличные части
  + реквизиты табличных частей

## Структура YAML
"""
    assert (
        uuid_formula_terms(incomplete_formula, "Документ") != DOCUMENT_UUID_TERMS
    )


@pytest.mark.parametrize(
    ("reference_name", "key"),
    [
        ("Справочник.md", "ДополнительныеИерархии"),
        ("Справочник.md", "ПространстваБлокировок"),
        ("Документ.md", "ПространстваБлокировок"),
    ],
)
def test_uuid_bearing_reference_list_items_have_own_ids(
    reference_name: str, key: str
):
    assert yaml_reference_list_items_have_ids(read_reference(reference_name), key)


def test_uuid_bearing_list_item_check_rejects_missing_own_id():
    example = """```yaml
ПространстваБлокировок:
    - Имя: ПоКонтрагенту
      Поля: [Контрагент]
```"""
    assert not yaml_reference_list_items_have_ids(
        example, "ПространстваБлокировок"
    )


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


def test_global_event_uses_documented_instance_methods():
    text = read_reference("ГлобальноеКлиентскоеСобытие.md")
    assert ".Оповестить(" in text
    assert ".ПодключитьОбработчик(" in text


def test_localized_strings_use_direct_xbsl_access():
    text = read_reference("ЛокализованныеСтроки.md")
    xbsl = "\n".join(xbsl_code_blocks(text))
    assert "$ЛокализованныеСтроки" not in xbsl
    assert "ЛокализованныеСтроки.ЗаказСохранён" in xbsl


def test_access_key_owner_and_developer_parameters_have_distinct_shapes():
    text = read_reference("КлючДоступа.md")
    assert (
        "Нужен: 1 (объект) + по 1 на каждый параметр, определённый разработчиком."
        in text
    )
    assert "Системный параметр `Владелец` UUID не требует." in text
    assert "1 (объект) + по 1 на каждый параметр (если есть)" not in text
    assert access_parameter_shapes_are_valid(text)
    assert "Доступ.ПроверитьКлюч" not in text


def test_access_parameter_shape_check_rejects_owner_with_id():
    example = """```yaml
ВидЭлемента: КлючДоступа
Параметры:
    - Ид: <UUID>
      Имя: Владелец
      Тип: Сотрудники.Ссылка?
    - Ид: <UUID>
      Имя: УровеньДоступа
      Тип: УровниДоступа
```"""
    assert not access_parameter_shapes_are_valid(example)
