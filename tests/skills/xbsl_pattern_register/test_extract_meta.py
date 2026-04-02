from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT_DIR / ".claude/skills/xbsl-pattern-register/scripts/extract_meta.py"


def load_extract_meta_module():
    spec = importlib.util.spec_from_file_location("extract_meta_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load module spec for {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def extract_meta():
    return load_extract_meta_module()


def test_get_yaml_field_handles_quoted_empty_and_missing_values(extract_meta) -> None:
    text = 'Имя: "Продажи"\nПустое:\n'

    assert extract_meta.get_yaml_field(text, "Имя") == "Продажи"
    assert extract_meta.get_yaml_field(text, "Пустое") is None
    assert extract_meta.get_yaml_field(text, "Несуществующее") is None


def test_parse_flat_list_supports_inline_and_block_items(extract_meta) -> None:
    text = """
Измерения:
    - Имя: Склад, Тип: Склады.Ссылка
    -
        Имя: Номенклатура
        Тип: Номенклатура.Ссылка
        Настройки:
            - НеДолжноПопасть
    - Имя: Организация, Пропуск
После:
    Имя: Другое
""".strip()

    assert extract_meta.parse_flat_list(text, "Измерения") == [
        {"Имя": "Склад", "Тип": "Склады.Ссылка"},
        {"Имя": "Номенклатура", "Тип": "Номенклатура.Ссылка"},
        {"Имя": "Организация"},
    ]


def test_parse_flat_list_returns_empty_for_missing_section(extract_meta) -> None:
    assert extract_meta.parse_flat_list("Имя: Продажи\n", "Ресурсы") == []


def test_parse_table_parts_collects_table_names_and_fields(extract_meta) -> None:
    text = """
ТабличныеЧасти:
    -
        Имя: Товары
        Реквизиты:
            -
                Имя: Номенклатура
                Тип: Номенклатура.Ссылка
            -
                Имя: Количество
                Тип: Число
        Комментарий: ХвостПослеРеквизитов
    -
        Реквизиты:
            -
                Имя: Описание
                Тип: Строка
После:
    Имя: Другое
""".strip()

    assert extract_meta.parse_table_parts(text) == [
        {
            "name": "Товары",
            "fields": [
                {"Имя": "Номенклатура", "Тип": "Номенклатура.Ссылка"},
                {"Имя": "Количество", "Тип": "Число"},
            ],
        },
        {
            "name": "???",
            "fields": [{"Имя": "Описание", "Тип": "Строка"}],
        },
    ]


def test_extract_register_returns_register_metadata(extract_meta) -> None:
    text = """
Имя: ОстаткиТоваров
ВидЭлемента: РегистрНакопления
ВидРегистра: Остатки
Измерения:
    - Имя: Склад
    - Имя: Номенклатура, Тип: Номенклатура.Ссылка
Ресурсы:
    - Имя: Количество
    - Тип: Число
""".strip()

    assert extract_meta.extract_register(text) == {
        "element_type": "РегистрНакопления",
        "name": "ОстаткиТоваров",
        "register_kind": "Остатки",
        "dimensions": ["Склад", "Номенклатура"],
        "resources": ["Количество"],
        "needs_record_type": True,
    }


def test_extract_document_returns_header_fields_tables_and_handler(extract_meta) -> None:
    text = """
Имя: ПриходнаяНакладная
ВидЭлемента: Документ
Реквизиты:
    - Имя: Склад
    - Имя: Организация, Тип: Организации.Ссылка
ТабличныеЧасти:
    -
        Имя: Товары
        Реквизиты:
            -
                Имя: Номенклатура
            -
                Имя: Количество
    -
        Имя: Услуги
После:
    Имя: Другое
""".strip()

    assert extract_meta.extract_document(text) == {
        "element_type": "Документ",
        "name": "ПриходнаяНакладная",
        "header_fields": ["Склад", "Организация"],
        "tables": [
            {"name": "Товары", "fields": ["Номенклатура", "Количество"]},
            {"name": "Услуги", "fields": []},
        ],
        "handler_file": "ПриходнаяНакладная.Объект.xbsl",
    }


def test_main_prints_register_json(extract_meta, tmp_path: Path, monkeypatch, capsys) -> None:
    yaml_path = tmp_path / "register.yaml"
    write_file(
        yaml_path,
        """
Имя: ОстаткиТоваров
ВидЭлемента: РегистрНакопления
ВидРегистра: Обороты
Измерения:
    - Имя: Склад
Ресурсы:
    - Имя: Сумма
""".strip()
        + "\n",
    )

    monkeypatch.setattr(sys, "argv", ["extract_meta.py", str(yaml_path)])

    extract_meta.main()

    assert json.loads(capsys.readouterr().out) == {
        "element_type": "РегистрНакопления",
        "name": "ОстаткиТоваров",
        "register_kind": "Обороты",
        "dimensions": ["Склад"],
        "resources": ["Сумма"],
        "needs_record_type": False,
    }


def test_main_prints_document_json(extract_meta, tmp_path: Path, monkeypatch, capsys) -> None:
    yaml_path = tmp_path / "document.yaml"
    write_file(
        yaml_path,
        """
Имя: Реализация
ВидЭлемента: Документ
Реквизиты:
    - Имя: Контрагент
ТабличныеЧасти:
    -
        Имя: Товары
        Реквизиты:
            -
                Имя: Номенклатура
""".strip()
        + "\n",
    )

    monkeypatch.setattr(sys, "argv", ["extract_meta.py", str(yaml_path)])

    extract_meta.main()

    assert json.loads(capsys.readouterr().out) == {
        "element_type": "Документ",
        "name": "Реализация",
        "header_fields": ["Контрагент"],
        "tables": [{"name": "Товары", "fields": ["Номенклатура"]}],
        "handler_file": "Реализация.Объект.xbsl",
    }


def test_extract_info_register_returns_metadata_for_nonperiodic(extract_meta) -> None:
    text = """
Имя: ЦеныТоваров
ВидЭлемента: РегистрСведений
Периодичность: Непериодический
Измерения:
    - Имя: Товар
    - Имя: Склад, Тип: Склады.Ссылка
Ресурсы:
    - Имя: Цена
Реквизиты:
    - Имя: Комментарий
""".strip()

    assert extract_meta.extract_info_register(text) == {
        "element_type": "РегистрСведений",
        "name": "ЦеныТоваров",
        "periodicity": "Непериодический",
        "is_periodic": False,
        "dimensions": ["Товар", "Склад"],
        "resources": ["Цена"],
        "requisites": ["Комментарий"],
    }


def test_extract_info_register_periodic_sets_is_periodic_true(extract_meta) -> None:
    text = """
Имя: КурсыВалют
ВидЭлемента: РегистрСведений
Периодичность: День
Измерения:
    - Имя: Валюта
Ресурсы:
    - Имя: Курс
    - Имя: Кратность
""".strip()

    result = extract_meta.extract_info_register(text)

    assert result["periodicity"] == "День"
    assert result["is_periodic"] is True
    assert result["dimensions"] == ["Валюта"]
    assert result["resources"] == ["Курс", "Кратность"]
    assert result["requisites"] == []


def test_main_prints_info_register_json(extract_meta, tmp_path: Path, monkeypatch, capsys) -> None:
    yaml_path = tmp_path / "info_register.yaml"
    write_file(
        yaml_path,
        """
Имя: НастройкиПользователей
ВидЭлемента: РегистрСведений
Периодичность: Непериодический
Измерения:
    - Имя: Пользователь
Ресурсы:
    - Имя: Значение
""".strip()
        + "\n",
    )

    monkeypatch.setattr(sys, "argv", ["extract_meta.py", str(yaml_path)])

    extract_meta.main()

    assert json.loads(capsys.readouterr().out) == {
        "element_type": "РегистрСведений",
        "name": "НастройкиПользователей",
        "periodicity": "Непериодический",
        "is_periodic": False,
        "dimensions": ["Пользователь"],
        "resources": ["Значение"],
        "requisites": [],
    }


def test_main_prints_json_error_for_unknown_element_type(extract_meta, tmp_path: Path, monkeypatch, capsys) -> None:
    yaml_path = tmp_path / "catalog.yaml"
    write_file(
        yaml_path,
        """
Имя: Номенклатура
ВидЭлемента: Справочник
""".strip()
        + "\n",
    )

    monkeypatch.setattr(sys, "argv", ["extract_meta.py", str(yaml_path)])

    with pytest.raises(SystemExit) as exc_info:
        extract_meta.main()

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        "error": "Неизвестный ВидЭлемента: 'Справочник'",
        "supported": ["РегистрНакопления", "РегистрСведений", "Документ"],
    }


def test_script_entrypoint_prints_usage_to_stderr_when_path_is_missing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["extract_meta.py"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert captured.out == ""
    assert "Использование: python3 extract_meta.py <путь-к-файлу.yaml>" in captured.err


def test_script_entrypoint_prints_json_error_to_stderr_for_missing_file(monkeypatch, capsys, tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.yaml"
    monkeypatch.setattr(sys, "argv", ["extract_meta.py", str(missing_path)])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert captured.out == ""
    assert json.loads(captured.err) == {"error": f"Файл не найден: {missing_path}"}
