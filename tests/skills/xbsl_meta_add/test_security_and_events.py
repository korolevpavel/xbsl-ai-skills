from __future__ import annotations

import re
from pathlib import Path

import pytest

from .helpers import (
    REFERENCE_SECTIONS,
    SKILL_ROOT,
    load_registry,
    load_yaml,
    record_for,
    required_artifact_patterns,
    section_names,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "security-and-events"


SECURITY_AND_EVENTS_OBJECTS = {
    "ПравоНаДействие": {
        "reference": "references/ПравоНаДействие.md",
        "required_artifacts": {"*.yaml"},
    },
    "ПравоНаЭлемент": {
        "reference": "references/ПравоНаЭлемент.md",
        "required_artifacts": {"*.yaml"},
    },
    "СобытиеЖурналаСобытий": {
        "reference": "references/СобытиеЖурналаСобытий.md",
        "required_artifacts": {"*.yaml"},
    },
    "ПараметрСамостоятельнойРегистрацииПользователя": {
        "reference": "references/ПараметрСамостоятельнойРегистрацииПользователя.md",
        "required_artifacts": {"*.yaml", "*.xbsl"},
    },
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


@pytest.mark.parametrize("kind", SECURITY_AND_EVENTS_OBJECTS)
def test_security_and_events_registry_records_are_supported_and_portable(kind: str):
    expected = SECURITY_AND_EVENTS_OBJECTS[kind]
    record = record_for(kind)

    assert record["status"] == "supported"
    assert record["owner_skill"] == "xbsl-meta-add"
    assert record["reference_path"] == expected["reference"]
    assert record["min_version"] == "9.1"
    assert record["shared_reference_paths"] == [
        "references/types.md",
        "references/reference-contract.md",
    ]
    assert required_artifact_patterns(record) == expected["required_artifacts"]
    assert record["known_gaps"] == []


def test_security_and_events_status_balance_finishes_security_events_without_new_public_issue_links():
    registry = load_registry()
    statuses = {status: 0 for status in ("supported", "partial", "routed")}
    for record in registry["objects"]:
        statuses[record["status"]] += 1

    assert statuses == {"supported": 31, "partial": 0, "routed": 1}
    assert not [record for record in registry["objects"] if record["status"] == "partial"]


@pytest.mark.parametrize("kind", SECURITY_AND_EVENTS_OBJECTS)
def test_security_and_events_references_follow_shared_contract_without_local_history(kind: str):
    reference_path = SKILL_ROOT / SECURITY_AND_EVENTS_OBJECTS[kind]["reference"]
    text = reference_path.read_text(encoding="utf-8")

    assert section_names(text) == REFERENCE_SECTIONS
    assert "Required:" in text
    assert "Negative:" in text
    assert "Platform facts:" in text
    assert "Local conventions:" in text
    assert "Runtime evidence" not in text
    assert "tracking_issue" not in text
    assert "security-and-events task history" not in text


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

    assert data["ВидЭлемента"] == "СобытиеЖурналаСобытий"
    assert data["ВидСобытия"] == "Операция"
    assert data["Важность"] == "Низкая"
    assert data["ОбластьВидимости"] == "ВПодсистеме"
    assert {"Добавлено", "Пропущено", "Задание"} <= {
        property_["Имя"] for property_ in data["Свойства"]
    }
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
