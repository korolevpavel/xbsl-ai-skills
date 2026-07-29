from __future__ import annotations

import re
from pathlib import Path

import pytest

from .helpers import (
    REFERENCES,
    REFERENCE_SECTIONS,
    SKILL_ROOT,
    load_yaml,
    record_for,
    required_artifact_patterns,
    section_names,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "data-and-execution"


DATA_AND_EXECUTION_OBJECTS = {
    "ВиртуальнаяТаблица": {
        "reference": "references/ВиртуальнаяТаблица.md",
        "min_version": "9.1",
        "required_artifacts": {"*.yaml", "*.xbql"},
    },
    "НаборКонстант": {
        "reference": "references/НаборКонстант.md",
        "min_version": "9.1",
        "required_artifacts": {"*.yaml"},
    },
    "Обработка": {
        "reference": "references/Обработка.md",
        "min_version": "9.1",
        "required_artifacts": {"*.yaml", "*.Объект.xbsl"},
    },
    "ПланОбмена": {
        "reference": "references/ПланОбмена.md",
        "min_version": "9.1",
        "required_artifacts": {"*.yaml"},
    },
    "ХранилищеНастроек": {
        "reference": "references/ХранилищеНастроек.md",
        "min_version": "9.1",
        "required_artifacts": {"*.yaml"},
    },
    "ХранимаяСтруктура": {
        "reference": "references/ХранимаяСтруктура.md",
        "min_version": "9.1",
        "required_artifacts": {"*.yaml"},
    },
    "ПараметрыРаботыКлиента": {
        "reference": "references/ПараметрыРаботыКлиента.md",
        "min_version": "9.2",
        "required_artifacts": {"*.yaml", "*.xbsl"},
    },
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


@pytest.mark.parametrize("kind", DATA_AND_EXECUTION_OBJECTS)
def test_data_and_execution_registry_records_are_supported_and_routed(kind: str):
    expected = DATA_AND_EXECUTION_OBJECTS[kind]
    record = record_for(kind)

    assert record["status"] == "supported"
    assert record["owner_skill"] == "xbsl-meta-add"
    assert record["reference_path"] == expected["reference"]
    assert record["min_version"] == expected["min_version"]
    assert record["shared_reference_paths"] == [
        "references/types.md",
        "references/reference-contract.md",
    ]
    assert required_artifact_patterns(record) == expected["required_artifacts"]


@pytest.mark.parametrize("kind", DATA_AND_EXECUTION_OBJECTS)
def test_data_and_execution_references_follow_shared_contract(kind: str):
    reference_path = SKILL_ROOT / DATA_AND_EXECUTION_OBJECTS[kind]["reference"]
    text = reference_path.read_text(encoding="utf-8")

    assert section_names(text) == REFERENCE_SECTIONS
    assert "## Runtime evidence" not in text
    assert "## Platform facts и local conventions" not in text
    assert "Required:" in text
    assert "Negative:" in text


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
    assert all(artifact["required"] for artifact in record["artifacts"])

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
