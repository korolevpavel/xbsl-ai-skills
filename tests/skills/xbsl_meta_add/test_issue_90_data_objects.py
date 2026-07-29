from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPOSITORY_ROOT / ".claude" / "skills" / "xbsl-meta-add"
COVERAGE_PATH = SKILL_ROOT / "object-coverage.json"
REFERENCES = SKILL_ROOT / "references"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "issue-90"

REFERENCE_SECTIONS = [
    "Назначение",
    "Версия и источники",
    "YAML",
    "UUID",
    "Imports и visibility",
    "Companion artifacts",
    "Генерация",
    "Валидация",
]

ISSUE_90_OBJECTS = {
    "ВиртуальнаяТаблица": {
        "reference": "references/ВиртуальнаяТаблица.md",
        "min_version": "9.1",
        "sources": {"topics/latest/virtual-table"},
        "required_artifacts": {"*.yaml", "*.xbql"},
    },
    "НаборКонстант": {
        "reference": "references/НаборКонстант.md",
        "min_version": "9.1",
        "sources": {
            "topics/latest/constants-set-properties",
            "topics/latest/constants-set-element",
            "stdlib/latest/element/xbsl/Std/ConstantsSets/ConstantsSet_ru",
        },
        "required_artifacts": {"*.yaml"},
    },
    "Обработка": {
        "reference": "references/Обработка.md",
        "min_version": "9.1",
        "sources": {"topics/latest/processing-project-element"},
        "required_artifacts": {"*.yaml", "*.Объект.xbsl"},
    },
    "ПланОбмена": {
        "reference": "references/ПланОбмена.md",
        "min_version": "9.1",
        "sources": {"topics/latest/exchange-plan-properties"},
        "required_artifacts": {"*.yaml"},
    },
    "ХранилищеНастроек": {
        "reference": "references/ХранилищеНастроек.md",
        "min_version": "9.1",
        "sources": {
            "topics/latest/settings-repository",
            "stdlib/latest/element/xbsl/Std/SettingsStorages/SettingsStorage_ru",
        },
        "required_artifacts": {"*.yaml"},
    },
    "ХранимаяСтруктура": {
        "reference": "references/ХранимаяСтруктура.md",
        "min_version": "9.1",
        "sources": {"topics/latest/storable-structure-properties"},
        "required_artifacts": {"*.yaml"},
    },
    "ПараметрыРаботыКлиента": {
        "reference": "references/ПараметрыРаботыКлиента.md",
        "min_version": "9.2",
        "sources": {
            "https://1cmycloud.com/console/help/element/9.2/docs/topics/client-work-parameters/"
        },
        "required_artifacts": {"*.yaml", "*.xbsl"},
    },
}


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def construct_mapping_without_duplicates(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_mapping_without_duplicates,
)


def load_registry() -> dict:
    return json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))


def record_for(kind: str) -> dict:
    return next(
        record for record in load_registry()["objects"] if record["element_kind"] == kind
    )


def load_yaml(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)


def section_names(text: str) -> list[str]:
    return re.findall(r"(?m)^## (.+?)\s*$", text)


def source_ids(record: dict) -> set[str]:
    return {
        source.get("doc_key", source.get("url"))
        for source in record["sources"]
    }


def required_artifact_patterns(record: dict) -> set[str]:
    return {
        artifact["pattern"]
        for artifact in record["artifacts"]
        if artifact["required"]
    }


def xbql_parameter_names(text: str) -> set[str]:
    return set(re.findall(r"&([A-Za-zА-Яа-я_][\w]*)", text))


def yaml_parameter_names(data: dict, key: str = "Параметры") -> set[str]:
    return {
        item["Имя"]
        for item in data.get(key, [])
        if isinstance(item, dict) and "Имя" in item
    }


def operation_names(data: dict) -> set[str]:
    return {
        item["Имя"]
        for item in data.get("Операции", [])
        if isinstance(item, dict) and "Имя" in item
    }


@pytest.mark.parametrize("kind", ISSUE_90_OBJECTS)
def test_issue_90_registry_records_are_supported_and_routed(kind: str):
    expected = ISSUE_90_OBJECTS[kind]
    record = record_for(kind)

    assert record["status"] == "supported"
    assert record["owner_skill"] == "xbsl-meta-add"
    assert record["tracking_issue"] == 90
    assert record["reference_path"] == expected["reference"]
    assert record["min_version"] == expected["min_version"]
    assert record["shared_reference_paths"] == [
        "references/types.md",
        "references/reference-contract.md",
    ]
    assert expected["sources"] <= source_ids(record)
    assert required_artifact_patterns(record) == expected["required_artifacts"]


@pytest.mark.parametrize("kind", ISSUE_90_OBJECTS)
def test_issue_90_references_follow_shared_contract(kind: str):
    reference_path = SKILL_ROOT / ISSUE_90_OBJECTS[kind]["reference"]
    text = reference_path.read_text(encoding="utf-8")

    assert section_names(text) == REFERENCE_SECTIONS
    assert "## Runtime evidence" not in text
    assert "## Platform facts и local conventions" not in text
    assert "Required:" in text
    assert "Negative:" in text
    for source in ISSUE_90_OBJECTS[kind]["sources"]:
        assert source in text


def test_virtual_table_fixture_requires_matching_nonempty_xbql_and_parameters():
    root = FIXTURES / "positive" / "ВиртуальнаяТаблица"
    yaml_path = root / "СотрудникиПоРоли.yaml"
    xbql_path = root / "СотрудникиПоРоли.xbql"
    data = load_yaml(yaml_path)
    query = xbql_path.read_text(encoding="utf-8")

    assert data["ВидЭлемента"] == "ВиртуальнаяТаблица"
    assert data["Имя"] == "СотрудникиПоРоли"
    assert query.strip()
    assert yaml_parameter_names(data) == {"Должность"}
    assert xbql_parameter_names(query) == {"Должность"}

    negative_root = FIXTURES / "negative" / "ВиртуальнаяТаблица"
    assert (negative_root / "empty_query" / "СотрудникиПоРоли.xbql").read_text(
        encoding="utf-8"
    ).strip() == ""
    assert not (negative_root / "missing_query" / "СотрудникиПоРоли.xbql").exists()
    mismatch = negative_root / "parameter_mismatch" / "СотрудникиПоРоли.xbql"
    assert xbql_parameter_names(mismatch.read_text(encoding="utf-8")) == {
        "НеОбъявлен"
    }


def test_constants_set_has_periodic_and_nonperiodic_fixtures_without_required_companion():
    root = FIXTURES / "positive" / "НаборКонстант"
    nonperiodic = load_yaml(root / "ДанныеОрганизации.yaml")
    periodic = load_yaml(root / "КурсДоллара.yaml")
    record = record_for("НаборКонстант")

    assert nonperiodic["Периодичность"] == "Непериодический"
    assert periodic["Периодичность"] == "День"
    assert all("Ид" in item for item in nonperiodic["Константы"])
    assert all("Ид" in item for item in periodic["Константы"])
    assert required_artifact_patterns(record) == {"*.yaml"}
    assert any(
        not artifact["required"] and "test-only" in artifact["role"]
        for artifact in record["artifacts"]
    )

    negative = (
        FIXTURES
        / "negative"
        / "НаборКонстант"
        / "periodic_nonperiodic_api_mix.xbsl"
    ).read_text(encoding="utf-8")
    assert "КурсДоллара.Получить()" in negative
    assert "ошибка:" in negative


def test_processing_fixture_pairs_operations_with_required_handlers():
    root = FIXTURES / "positive" / "Обработка"
    data = load_yaml(root / "ОчисткаДемоДанных.yaml")
    module = (root / "ОчисткаДемоДанных.Объект.xbsl").read_text(encoding="utf-8")

    assert operation_names(data) == {"Очистить"}
    assert "@Обработчик" in module
    assert re.search(r"(?m)^метод Очистить\(\)", module)

    negative = (
        FIXTURES
        / "negative"
        / "Обработка"
        / "missing_handler"
        / "ОчисткаДемоДанных.Объект.xbsl"
    ).read_text(encoding="utf-8")
    assert not re.search(r"(?m)^метод Очистить\(\)", negative)


def test_exchange_plan_fixture_composition_resolves_to_local_element():
    root = FIXTURES / "positive" / "ПланОбмена"
    plan = load_yaml(root / "СинхронизацияСкладов.yaml")
    local_catalog = load_yaml(root / "Склады.yaml")

    composition = plan["Состав"]
    assert composition == [{"Элемент": "Склады"}]
    assert local_catalog["ВидЭлемента"] == "Справочник"
    assert local_catalog["Имя"] == "Склады"

    bad = load_yaml(
        FIXTURES
        / "negative"
        / "ПланОбмена"
        / "unresolved_composition"
        / "СинхронизацияСкладов.yaml"
    )
    assert bad["Состав"] == [{"Элемент": "НесуществующийЭлемент"}]


def test_settings_storage_fixture_has_no_required_form_or_module():
    data = load_yaml(
        FIXTURES / "positive" / "ХранилищеНастроек" / "НастройкиОтчетов.yaml"
    )
    record = record_for("ХранилищеНастроек")
    reference = (REFERENCES / "ХранилищеНастроек.md").read_text(encoding="utf-8")

    assert data["ВидЭлемента"] == "ХранилищеНастроек"
    assert "Интерфейс" not in data
    assert required_artifact_patterns(record) == {"*.yaml"}
    assert "форма не является обязательным companion" in reference
    assert "модуль не является обязательным companion" in reference


def test_storable_structure_fixture_rejects_non_storable_field_type():
    data = load_yaml(
        FIXTURES / "positive" / "ХранимаяСтруктура" / "ПараметрыПечати.yaml"
    )
    bad = load_yaml(
        FIXTURES
        / "negative"
        / "ХранимаяСтруктура"
        / "non_storable_type"
        / "ПараметрыПечати.yaml"
    )

    assert data["ВидЭлемента"] == "ХранимаяСтруктура"
    assert {field["Тип"] for field in data["Поля"]} == {"Строка", "Булево"}
    assert bad["Поля"][0]["Тип"] == "Объект"


def test_client_work_parameters_fixture_has_handler_and_no_nested_parameter_ids():
    root = FIXTURES / "positive" / "ПараметрыРаботыКлиента"
    data = load_yaml(root / "СтартовыеПараметры.yaml")
    module = (root / "СтартовыеПараметры.xbsl").read_text(encoding="utf-8")

    assert data["ВидЭлемента"] == "ПараметрыРаботыКлиента"
    assert data["ОбластьВидимости"] == "ВПроекте"
    assert set(data) >= {"ОбластьВидимости", "Ид", "Имя", "Параметры"}
    assert all("Ид" not in parameter for parameter in data["Параметры"])
    assert "@Обработчик" in module
    assert "@НаСервере" in module
    assert (
        "статический метод ВычислитьПараметрыРаботыКлиента(): "
        "СтартовыеПараметры.Параметры"
    ) in module

    negative_root = FIXTURES / "negative" / "ПараметрыРаботыКлиента"
    nested_id = load_yaml(negative_root / "nested_parameter_id" / "СтартовыеПараметры.yaml")
    bad_type = load_yaml(negative_root / "non_client_type" / "СтартовыеПараметры.yaml")
    bad_module = (
        negative_root / "wrong_handler" / "СтартовыеПараметры.xbsl"
    ).read_text(encoding="utf-8")

    assert "Ид" in nested_id["Параметры"][0]
    assert bad_type["Параметры"][0]["Тип"] == "ПотокЧтения"
    assert "ВычислитьПараметрыРаботыКлиента" not in bad_module
