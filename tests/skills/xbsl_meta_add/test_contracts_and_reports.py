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
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "contracts-and-reports"
SKILL_TEXT = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")


CONTRACTS_AND_REPORTS_OBJECTS = {
    "КонтрактСервиса": {
        "reference": "references/КонтрактСервиса.md",
        "shared_reference_paths": [
            "references/types.md",
            "references/reference-contract.md",
        ],
        "required_artifacts": {"*.yaml", "*.xbsl"},
    },
    "КонтрактСущности": {
        "reference": "references/КонтрактСущности.md",
        "shared_reference_paths": [
            "references/types.md",
            "references/ТабличныеЧасти.md",
            "references/reference-contract.md",
        ],
        "required_artifacts": {"*.yaml"},
    },
    "КонтрактТипа": {
        "reference": "references/КонтрактТипа.md",
        "shared_reference_paths": [
            "references/types.md",
            "references/reference-contract.md",
        ],
        "required_artifacts": {"*.yaml"},
    },
    "ПанельОтчетов": {
        "reference": "references/ПанельОтчетов.md",
        "shared_reference_paths": [
            "references/types.md",
            "references/reference-contract.md",
        ],
        "required_artifacts": {"*.yaml"},
    },
    "ЦветоваяСхемаОтчета": {
        "reference": "references/ЦветоваяСхемаОтчета.md",
        "shared_reference_paths": [
            "references/types.md",
            "references/reference-contract.md",
        ],
        "required_artifacts": {"*.yaml"},
    },
}


def abstract_method_names(text: str) -> set[str]:
    return set(re.findall(r"абстрактный метод\s+([A-Za-zА-Яа-я_][\w]*)", text))


def implementation_method_names(text: str) -> set[str]:
    return set(re.findall(r"(?m)^метод\s+([A-Za-zА-Яа-я_][\w]*)", text))


@pytest.mark.parametrize("kind", CONTRACTS_AND_REPORTS_OBJECTS)
def test_contracts_and_reports_registry_records_are_supported_and_routed(kind: str):
    expected = CONTRACTS_AND_REPORTS_OBJECTS[kind]
    record = record_for(kind)

    assert record["status"] == "supported"
    assert record["owner_skill"] == "xbsl-meta-add"
    assert record["reference_path"] == expected["reference"]
    assert record["min_version"] == "9.1"
    assert record["shared_reference_paths"] == expected["shared_reference_paths"]
    assert required_artifact_patterns(record) == expected["required_artifacts"]
    assert record["known_gaps"] == []


@pytest.mark.parametrize("kind", CONTRACTS_AND_REPORTS_OBJECTS)
def test_contracts_and_reports_references_follow_shared_contract(kind: str):
    reference_path = SKILL_ROOT / CONTRACTS_AND_REPORTS_OBJECTS[kind]["reference"]
    text = reference_path.read_text(encoding="utf-8")

    assert section_names(text) == REFERENCE_SECTIONS
    assert "Required:" in text
    assert "Negative:" in text
    assert "Platform facts:" in text
    assert "Local conventions:" in text


def test_service_contract_required_fixture_has_contract_module_and_separate_test_implementation():
    root = FIXTURES / "positive" / "КонтрактСервиса" / "required"
    data = load_yaml(root / "APIРасчетаСкидок.yaml")
    contract_module = (root / "APIРасчетаСкидок.xbsl").read_text(encoding="utf-8")
    implementation_yaml = load_yaml(root / "РасчетСкидок.yaml")
    implementation_module = (root / "РасчетСкидок.xbsl").read_text(encoding="utf-8")

    assert data["ВидЭлемента"] == "КонтрактСервиса"
    assert data["Обязательный"] == "Истина"
    assert data["Множественный"] == "Ложь"
    assert abstract_method_names(contract_module) == {"РассчитатьСкидку"}
    assert implementation_yaml["ВидЭлемента"] == "ОбщийМодуль"
    assert implementation_yaml["НастройкиТипа"]["Контракты"] == ["APIРасчетаСкидок"]
    assert implementation_method_names(implementation_module) == {"РассчитатьСкидку"}
    assert "@Реализация" in implementation_module

    optional_root = FIXTURES / "positive" / "КонтрактСервиса" / "optional"
    optional = load_yaml(optional_root / "APIРассылок.yaml")
    assert optional["ВидЭлемента"] == "КонтрактСервиса"
    assert optional.get("Обязательный", "Ложь") == "Ложь"
    assert (optional_root / "APIРассылок.xbsl").is_file()
    assert not (optional_root / "Рассылки.xbsl").exists()

    negative_root = FIXTURES / "negative" / "КонтрактСервиса"
    assert not (negative_root / "missing_contract_module" / "APIРасчетаСкидок.xbsl").exists()
    missing_implementation = load_yaml(
        negative_root / "missing_required_implementation" / "APIРасчетаСкидок.yaml"
    )
    assert missing_implementation["Обязательный"] == "Истина"
    bad_implementation = (
        negative_root
        / "incompatible_implementation_signature"
        / "РасчетСкидок.xbsl"
    ).read_text(encoding="utf-8")
    assert "РассчитатьСкидку(Клиент: Строка)" in bad_implementation


def test_entity_contract_fixture_covers_properties_tabular_sections_and_incompatible_implementations():
    root = FIXTURES / "positive" / "КонтрактСущности"
    contract = load_yaml(root / "ТоварныйОбъект.yaml")
    with_table = load_yaml(root / "ТоварныйОбъектСТабличнойЧастью.yaml")
    implementation = load_yaml(root / "Товары.yaml")

    assert contract["ВидЭлемента"] == "КонтрактСущности"
    assert {prop["Имя"] for prop in contract["Свойства"]} == {"Артикул"}
    assert with_table["ТабличныеЧасти"][0]["Имя"] == "Состав"
    assert implementation["НастройкиТипов"]["Справочник.Объект"]["Контракты"] == [
        "ТоварныйОбъект.Объект"
    ]

    negative_root = FIXTURES / "negative" / "КонтрактСущности"
    bad_property = load_yaml(negative_root / "incompatible_property" / "Товары.yaml")
    bad_table = load_yaml(negative_root / "incompatible_tabular_section" / "Товары.yaml")
    assert bad_property["Реквизиты"][0]["Тип"] == "Число"
    assert bad_table["ТабличныеЧасти"][0]["Реквизиты"][0]["Тип"] == "Строка"


def test_type_contract_fixture_distinguishes_contract_type_settings_from_implementing_type_settings():
    root = FIXTURES / "positive" / "КонтрактТипа"
    contract = load_yaml(root / "КонтрактСкидки.yaml")
    implementation = load_yaml(root / "ПравилоСкидки.yaml")

    assert contract["ВидЭлемента"] == "КонтрактТипа"
    assert {prop["Имя"] for prop in contract["Свойства"]} == {"Процент", "Комментарий"}
    assert contract["НастройкиТипа"]["Контракты"] == ["БазовыйКонтрактТипа"]
    assert implementation["НастройкиТипа"]["Контракты"] == ["КонтрактСкидки"]
    assert not (root / "КонтрактСкидки.xbsl").exists()

    negative_root = FIXTURES / "negative" / "КонтрактТипа"
    bad_type = load_yaml(negative_root / "incompatible_mutable_property" / "ПравилоСкидки.yaml")
    bad_narrowing = load_yaml(
        negative_root / "invalid_readonly_narrowing" / "ПравилоСкидки.yaml"
    )
    assert bad_type["Реквизиты"][0]["Тип"] == "Строка"
    assert bad_narrowing["Реквизиты"][1]["Тип"] == "Дата"


def test_report_panel_fixture_requires_presentation_without_manual_designer_layout():
    root = FIXTURES / "positive" / "ПанельОтчетов"
    data = load_yaml(root / "КоммерческаяПанель.yaml")
    record = record_for("ПанельОтчетов")
    reference = (REFERENCES / "ПанельОтчетов.md").read_text(encoding="utf-8")

    assert data["ВидЭлемента"] == "ПанельОтчетов"
    assert data["Представление"] == "Коммерческая панель"
    assert "Макет" not in data
    assert "Отчет" not in data
    assert required_artifact_patterns(record) == {"*.yaml"}
    assert "designer-owned" in reference

    bad = load_yaml(
        FIXTURES
        / "negative"
        / "ПанельОтчетов"
        / "missing_presentation"
        / "КоммерческаяПанель.yaml"
    )
    assert "Представление" not in bad


def test_report_color_scheme_fixtures_cover_dark_theme_and_fallback_without_report_links():
    root = FIXTURES / "positive" / "ЦветоваяСхемаОтчета"
    explicit_dark = load_yaml(root / "СхемаПродаж.yaml")
    fallback = load_yaml(root / "СхемаПродажFallback.yaml")
    record = record_for("ЦветоваяСхемаОтчета")

    assert explicit_dark["ВидЭлемента"] == "ЦветоваяСхемаОтчета"
    assert explicit_dark["Цвета"] == ["RGB(009E73)", "RGB(56B4E9)", "RGB(CC79A7)"]
    assert explicit_dark["ЦветаТемнойТемы"] == [
        "RGB(03DAC6)",
        "RGB(3700B3)",
        "RGB(BB86FC)",
    ]
    assert fallback["Цвета"] == ["RGB(009E73)", "RGB(56B4E9)"]
    assert "ЦветаТемнойТемы" not in fallback
    assert "Отчет" not in explicit_dark
    assert required_artifact_patterns(record) == {"*.yaml"}

    bad = load_yaml(
        FIXTURES
        / "negative"
        / "ЦветоваяСхемаОтчета"
        / "invalid_absolute_color"
        / "СхемаПродаж.yaml"
    )
    assert bad["Цвета"] == ["#009E73"]


def test_report_export_to_image_delta_is_documented():
    report = record_for("Отчет")
    reference = (REFERENCES / "Отчет.md").read_text(encoding="utf-8")
    positive = (
        FIXTURES
        / "positive"
        / "Отчет"
        / "export_to_image_92.xbsl"
    ).read_text(encoding="utf-8")
    negative = (
        FIXTURES
        / "negative"
        / "Отчет"
        / "target_91_export_to_image.xbsl"
    ).read_text(encoding="utf-8")

    assert report["min_version"] == "9.1"
    assert report["known_gaps"] == []
    assert "Feature delta 9.2+: ЭкспортироватьВИзображение()" in reference
    assert "https://" not in reference
    assert "ЭкспортироватьВИзображение(" in reference
    assert "Ширина: Число? = Неопределено" in reference
    assert "Высота: Число? = Неопределено" in reference
    assert "Dpi: Число = 200" in reference
    assert "ЦветоваяСхема: ЦветоваяСхема = ЦветоваяСхема.Светлая" in reference
    assert "): Байты" in reference
    assert "Доступность: Клиент" in reference
    assert "ИсключениеЭкспортаОтчета" in reference
    assert "ИсключениеНедопустимыйАргумент" in reference
    assert "Версия 9.2+" in reference
    assert "// target-platform: 9.2" in positive
    assert "ЭкспортироватьВИзображение()" in positive
    assert "// target-platform: 9.1" in negative
    assert "feature-gate negative" in negative
    assert "ЭкспортироватьВИзображение()" in negative


def test_skill_step_4_uses_registry_required_artifacts_for_service_contract_companions():
    assert "Создай каждый required companion из `artifacts` записи registry" in SKILL_TEXT
    assert "КонтрактСервиса` всегда требует" in SKILL_TEXT
    assert "только если пользователь явно запросил методы" not in SKILL_TEXT
