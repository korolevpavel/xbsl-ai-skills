from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from .helpers import (
    REFERENCES,
    REFERENCE_SECTIONS,
    SKILL_ROOT,
    load_registry,
    load_yaml,
    record_for,
    required_artifact_patterns,
    section_names,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "integration"


INTEGRATION_OBJECTS = {
    "SoapСервис": {
        "reference": "references/SoapСервис.md",
        "required_artifacts": {"*.yaml", "*.xbsl"},
    },
    "КлиентSoapСервиса": {
        "reference": "references/КлиентSoapСервиса.md",
        "required_artifacts": {"*.yaml", "*.Wsdl.1"},
    },
    "ПроцессИнтеграции": {
        "reference": "references/ПроцессИнтеграции.md",
        "required_artifacts": {"*.yaml", "*.xbsl"},
    },
}


def method_names(module_path: Path) -> set[str]:
    text = module_path.read_text(encoding="utf-8")
    return set(re.findall(r"(?m)^\s*метод\s+([A-Za-zА-Яа-я_][\w]*)\s*\(", text))


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


def wsdl_operation_names(path: Path) -> set[str]:
    document = ET.parse(path)
    namespace = {"wsdl": "http://schemas.xmlsoap.org/wsdl/"}
    return {
        operation.attrib["name"]
        for operation in document.findall(".//wsdl:portType/wsdl:operation", namespace)
    }


def wsdl_schema_locations(path: Path) -> set[str]:
    document = ET.parse(path)
    result: set[str] = set()
    for node in document.iter():
        location = node.attrib.get("schemaLocation")
        if location:
            result.add(location)
    return result


@pytest.mark.parametrize("kind", INTEGRATION_OBJECTS)
def test_integration_registry_records_are_supported_and_portable(kind: str):
    expected = INTEGRATION_OBJECTS[kind]
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


def test_integration_status_balance_finishes_all_local_partial_records():
    registry = load_registry()
    statuses = {status: 0 for status in ("supported", "partial", "routed")}
    for record in registry["objects"]:
        statuses[record["status"]] += 1

    assert statuses == {"supported": 31, "partial": 0, "routed": 1}
    assert not [record for record in registry["objects"] if record["status"] == "partial"]


@pytest.mark.parametrize("kind", INTEGRATION_OBJECTS)
def test_integration_references_follow_contract_without_local_artifacts(kind: str):
    text = (SKILL_ROOT / INTEGRATION_OBJECTS[kind]["reference"]).read_text(
        encoding="utf-8"
    )

    assert section_names(text) == REFERENCE_SECTIONS
    assert "Required:" in text
    assert "Negative:" in text
    assert "Platform facts:" in text
    assert "Local conventions:" in text
    assert "Runtime evidence" not in text
    assert "tracking_issue" not in text
    assert "integration task history" not in text
    assert "xbsl-docs" not in text


def test_soap_service_fixture_links_operations_to_server_module_without_wsdl_input():
    root = FIXTURES / "positive" / "SoapСервис"
    data = load_yaml(root / "СервисЗаказов.yaml")

    assert data["ВидЭлемента"] == "SoapСервис"
    assert data["Имя"] == "СервисЗаказов"
    assert data["ОбластьВидимости"] == "ВПодсистеме"
    assert data["ПространствоИменСервиса"] == "https://example.com/orders"
    assert data["ИмяСервиса"] == "OrdersService"
    assert data["КорневойUrl"] == "/orders"
    assert collect_uuid_values(data) == {"55555555-5555-4555-8555-555555555551"}

    handlers = {handler["Метод"] for handler in data["Обработчики"]}
    assert handlers == {"GetOrder"}
    assert handlers <= method_names(root / "СервисЗаказов.xbsl")
    assert "ServiceFault" in (root / "СервисЗаказов.xbsl").read_text(encoding="utf-8")
    assert not list(root.glob("*.Wsdl.*"))
    assert not list(root.glob("*.Xsd.*"))

    negative = FIXTURES / "negative" / "SoapСервис" / "missing_module"
    assert (negative / "СервисЗаказов.yaml").exists()
    assert not (negative / "СервисЗаказов.xbsl").exists()


def test_soap_client_fixture_resolves_wsdl_xsd_and_declares_generated_calls():
    root = FIXTURES / "positive" / "КлиентSoapСервиса"
    data = load_yaml(root / "КлиентЗаказов.yaml")
    wsdl = root / "КлиентЗаказов.Wsdl.1"

    assert data["ВидЭлемента"] == "КлиентSoapСервиса"
    assert data["Имя"] == "КлиентЗаказов"
    assert data["ОбластьВидимости"] == "ВПроекте"
    assert data["UrlПоУмолчанию"] == "https://partner.example/soap/orders"
    assert data["ВерсияSoap"] == "Soap_1_1"
    assert collect_uuid_values(data) == {"66666666-6666-4666-8666-666666666661"}

    assert wsdl_operation_names(wsdl) == {"GetOrder"}
    schema_locations = wsdl_schema_locations(wsdl)
    assert schema_locations == {"КлиентЗаказов.Xsd.1"}
    assert all((root / location).is_file() for location in schema_locations)
    assert {"НастроитьЗаголовкиSoapGetOrder", "ОбработатьЗаголовкиSoapGetOrder"} <= (
        method_names(root / "КлиентЗаказов.xbsl")
    )

    missing_wsdl = FIXTURES / "negative" / "КлиентSoapСервиса" / "missing_wsdl"
    assert (missing_wsdl / "КлиентЗаказов.yaml").exists()
    assert not (missing_wsdl / "КлиентЗаказов.Wsdl.1").exists()

    missing_xsd = FIXTURES / "negative" / "КлиентSoapСервиса" / "missing_xsd"
    broken_locations = wsdl_schema_locations(missing_xsd / "КлиентЗаказов.Wsdl.1")
    assert "КлиентЗаказов.Xsd.1" in broken_locations
    assert not (missing_xsd / "КлиентЗаказов.Xsd.1").exists()


def test_integration_process_fixture_has_schema_graph_and_matching_handlers():
    root = FIXTURES / "positive" / "ПроцессИнтеграции"
    data = load_yaml(root / "ОбменЗаказами.yaml")
    schema = data["Схема"]

    assert data["ВидЭлемента"] == "ПроцессИнтеграции"
    assert data["Имя"] == "ОбменЗаказами"
    assert data["ОбластьВидимости"] == "ВПодсистеме"
    assert data["СправочникУчастников"] == "Общие::ИнформационныеСистемы"
    assert collect_uuid_values(data) == {
        "77777777-7777-4777-8777-777777777771",
        "77777777-7777-4777-8777-777777777772",
        "77777777-7777-4777-8777-777777777773",
        "77777777-7777-4777-8777-777777777774",
        "77777777-7777-4777-8777-777777777775",
        "77777777-7777-4777-8777-777777777776",
        "77777777-7777-4777-8777-777777777777",
        "77777777-7777-4777-8777-777777777778",
    }

    node_names = {node["Имя"] for node in schema["Узлы"]}
    group_names = {group["Имя"] for group in schema["ГруппыУчастников"]}
    assert node_names == {"ВходящиеЗаказы", "НормализацияЗаказа", "ВОсновнуюБазу"}
    assert group_names == {"Партнеры"}
    assert {(route["Из"], route["В"]) for route in schema["Маршруты"]} == {
        ("ВходящиеЗаказы", "НормализацияЗаказа"),
        ("НормализацияЗаказа", "ВОсновнуюБазу"),
    }
    assert all(route["Из"] in node_names and route["В"] in node_names for route in schema["Маршруты"])
    assert all(link["Группа"] in group_names and link["Узел"] in node_names for link in schema["Связи"])

    translator = next(node for node in schema["Узлы"] if node["Вид"] == "Транслятор")
    assert translator["Преобразование"] == "NormalizeOrder"
    assert "NormalizeOrder" in method_names(root / "ОбменЗаказами.xbsl")

    missing_schema = FIXTURES / "negative" / "ПроцессИнтеграции" / "missing_schema"
    assert "Схема" not in load_yaml(missing_schema / "ОбменЗаказами.yaml")

    missing_module = FIXTURES / "negative" / "ПроцессИнтеграции" / "missing_module"
    assert load_yaml(missing_module / "ОбменЗаказами.yaml")["Схема"]["Узлы"][1][
        "Преобразование"
    ] == "NormalizeOrder"
    assert not (missing_module / "ОбменЗаказами.xbsl").exists()
