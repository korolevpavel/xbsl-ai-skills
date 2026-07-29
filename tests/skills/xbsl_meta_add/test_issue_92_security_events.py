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
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "issue-92"

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

ISSUE_92_OBJECTS = {
    "ПравоНаДействие": {
        "reference": "references/ПравоНаДействие.md",
        "sources": {"topics/latest/privilege-on-action-properties"},
        "required_artifacts": {"*.yaml"},
    },
    "ПравоНаЭлемент": {
        "reference": "references/ПравоНаЭлемент.md",
        "sources": {"topics/latest/privilege-on-element-properties"},
        "required_artifacts": {"*.yaml"},
    },
    "СобытиеЖурналаСобытий": {
        "reference": "references/СобытиеЖурналаСобытий.md",
        "sources": {"topics/latest/event-properties"},
        "required_artifacts": {"*.yaml"},
    },
    "ПараметрСамостоятельнойРегистрацииПользователя": {
        "reference": "references/ПараметрСамостоятельнойРегистрацииПользователя.md",
        "sources": {
            "topics/latest/self-registration-form",
            "topics/latest/whats-new-in-6-0",
            (
                "stdlib/latest/element/xbsl/Std/Users/SelfService/"
                "UserSelfRegistrationParameter_ru"
            ),
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
    return {source.get("path", source.get("url")) for source in record["sources"]}


def required_artifact_patterns(record: dict) -> set[str]:
    return {
        artifact["pattern"]
        for artifact in record["artifacts"]
        if artifact["required"]
    }


def collect_uuid_values(value) -> set[str]:
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    if isinstance(value, dict):
        result = set()
        for item in value.values():
            result |= collect_uuid_values(item)
        return result
    if isinstance(value, list):
        result = set()
        for item in value:
            result |= collect_uuid_values(item)
        return result
    if isinstance(value, str) and uuid_pattern.fullmatch(value):
        return {value}
    return set()


@pytest.mark.parametrize("kind", ISSUE_92_OBJECTS)
def test_issue_92_registry_records_are_supported_and_portable(kind: str):
    expected = ISSUE_92_OBJECTS[kind]
    record = record_for(kind)

    assert record["status"] == "supported"
    assert record["owner_skill"] == "xbsl-meta-add"
    assert record["reference_path"] == expected["reference"]
    assert record["min_version"] == "9.1"
    assert record["shared_reference_paths"] == [
        "references/types.md",
        "references/reference-contract.md",
    ]
    assert expected["sources"] <= source_ids(record)
    assert required_artifact_patterns(record) == expected["required_artifacts"]
    assert record["known_gaps"] == []
    assert all("doc_key" not in source for source in record["sources"])


def test_issue_92_status_balance_finishes_security_events_without_new_public_issue_links():
    registry = load_registry()
    statuses = {record["status"]: 0 for record in registry["objects"]}
    for record in registry["objects"]:
        statuses[record["status"]] += 1

    assert statuses == {"supported": 28, "partial": 3, "routed": 1}
    assert {
        record["element_kind"]
        for record in registry["objects"]
        if record["status"] == "partial"
    } == {"SoapСервис", "КлиентSoapСервиса", "ПроцессИнтеграции"}


@pytest.mark.parametrize("kind", ISSUE_92_OBJECTS)
def test_issue_92_references_follow_shared_contract_and_source_boundaries(kind: str):
    reference_path = SKILL_ROOT / ISSUE_92_OBJECTS[kind]["reference"]
    text = reference_path.read_text(encoding="utf-8")

    assert section_names(text) == REFERENCE_SECTIONS
    assert "Required:" in text
    assert "Negative:" in text
    assert "Platform facts:" in text
    assert "Local conventions:" in text
    assert "Runtime evidence" not in text
    assert "tracking_issue" not in text
    assert "#92" not in text
    for source in ISSUE_92_OBJECTS[kind]["sources"]:
        assert source in text


def test_privilege_on_action_fixture_uses_parameters_not_element_actions():
    root = FIXTURES / "positive" / "ПравоНаДействие"
    data = load_yaml(root / "ПравоНаЗакрытиеЗаявки.yaml")

    assert data["ВидЭлемента"] == "ПравоНаДействие"
    assert data["Имя"] == "ПравоНаЗакрытиеЗаявки"
    assert data["ОбластьВидимости"] == "ВПодсистеме"
    assert {parameter["Имя"] for parameter in data["Параметры"]} == {"Заявка"}
    assert "Элементы" not in data
    assert collect_uuid_values(data) == {
        "11111111-1111-4111-8111-111111111111",
        "11111111-1111-4111-8111-111111111112",
    }

    negative = load_yaml(
        FIXTURES
        / "negative"
        / "ПравоНаДействие"
        / "element_actions_are_not_action_parameters"
        / "ПравоНаЗакрытиеЗаявки.yaml"
    )
    assert "Элементы" in negative
    assert "Параметры" not in negative


def test_privilege_on_element_fixture_uses_elements_not_action_parameters():
    root = FIXTURES / "positive" / "ПравоНаЭлемент"
    data = load_yaml(root / "ПравоНаЗаявку.yaml")

    assert data["ВидЭлемента"] == "ПравоНаЭлемент"
    assert data["Имя"] == "ПравоНаЗаявку"
    assert data["ОбластьВидимости"] == "ВПодсистеме"
    assert {item["Имя"] for item in data["Элементы"]} == {
        "Закрытие",
        "ИзменениеОтветственного",
    }
    assert "Параметры" not in data
    assert collect_uuid_values(data) == {
        "22222222-2222-4222-8222-222222222221",
        "22222222-2222-4222-8222-222222222222",
        "22222222-2222-4222-8222-222222222223",
    }

    negative = load_yaml(
        FIXTURES
        / "negative"
        / "ПравоНаЭлемент"
        / "action_parameters_are_not_element_actions"
        / "ПравоНаЗаявку.yaml"
    )
    assert "Параметры" in negative
    assert "Элементы" not in negative


def test_event_log_event_fixture_covers_yaml_without_claiming_xbsl_api():
    root = FIXTURES / "positive" / "СобытиеЖурналаСобытий"
    data = load_yaml(root / "ОперацияИмпортаДанных.yaml")
    record = record_for("СобытиеЖурналаСобытий")

    assert data["ВидЭлемента"] == "СобытиеЖурналаСобытий"
    assert data["ВидСобытия"] == "Операция"
    assert data["Важность"] == "Низкая"
    assert data["ОбластьВидимости"] == "ВПодсистеме"
    assert {"Добавлено", "Пропущено", "Задание"} <= {
        property_["Имя"] for property_ in data["Свойства"]
    }
    assert all("XBSL API" not in source["claims"] for source in record["sources"])
    assert not (root / "ОперацияИмпортаДанных.xbsl").exists()
    assert collect_uuid_values(data) == {
        "33333333-3333-4333-8333-333333333331",
        "33333333-3333-4333-8333-333333333332",
        "33333333-3333-4333-8333-333333333333",
        "33333333-3333-4333-8333-333333333334",
    }

    negative = load_yaml(
        FIXTURES
        / "negative"
        / "СобытиеЖурналаСобытий"
        / "operation_event_missing_templates"
        / "ОперацияИмпортаДанных.yaml"
    )
    assert negative["ВидСобытия"] == "Операция"
    assert "ШаблонПредставленияНачала" not in negative


def test_self_registration_parameter_fixture_has_fields_and_safe_required_handler():
    root = FIXTURES / "positive" / "ПараметрСамостоятельнойРегистрацииПользователя"
    data = load_yaml(root / "ДанныеПользователя.yaml")
    module = (root / "ДанныеПользователя.xbsl").read_text(encoding="utf-8")

    assert data["ВидЭлемента"] == "ПараметрСамостоятельнойРегистрацииПользователя"
    assert data["Имя"] == "ДанныеПользователя"
    assert data["ОбластьВидимости"] == "ВПодсистеме"
    assert {field["Имя"] for field in data["Поля"]} == {
        "Имя",
        "Фамилия",
        "ДатаРождения",
    }
    assert all("Ид" not in field for field in data["Поля"])
    assert collect_uuid_values(data) == {"44444444-4444-4444-8444-444444444441"}
    assert re.search(r"(?m)^метод ПослеПодключения\(\)", module)
    assert "ПриПроверкеПараметра" in module
    assert "Пользователи.ТекущийПользователь" not in module
    assert "СпискиПользователей" not in module
    assert "КонтрольДоступа" not in module

    negative = (
        FIXTURES
        / "negative"
        / "ПараметрСамостоятельнойРегистрацииПользователя"
        / "missing_required_handler"
        / "ДанныеПользователя.xbsl"
    ).read_text(encoding="utf-8")
    assert "ПриПроверкеПараметра" in negative
    assert "ПослеПодключения" not in negative
