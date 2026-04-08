from __future__ import annotations

import builtins
import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT_DIR / ".claude/skills/xbsl-form-info/scripts/form_info.py"


def load_form_info_module():
    spec = importlib.util.spec_from_file_location("form_info_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def create_project_structure(base_dir: Path, vendor: str = "Acme", project: str = "CRM", subsystem: str = "Основное") -> tuple[Path, Path]:
    project_dir = base_dir / vendor / project
    subsystem_dir = project_dir / subsystem
    write_file(project_dir / "Проект.yaml", f"Поставщик: {vendor}\nИмя: {project}\n")
    write_file(subsystem_dir / "Подсистема.yaml", "Имя: Подсистема\n")
    return project_dir, subsystem_dir


@pytest.fixture
def form_info():
    return load_form_info_module()


def test_get_yaml_field_handles_value_empty_and_missing(form_info) -> None:
    text = 'Имя: "Сотрудники"\nПустое:\n'

    assert form_info.get_yaml_field(text, "Имя") == "Сотрудники"
    assert form_info.get_yaml_field(text, "Пустое") is None
    assert form_info.get_yaml_field(text, "Несуществующее") is None


def test_parse_list_section_supports_inline_block_and_continuation(form_info) -> None:
    text = """
Имя: Сотрудники

Реквизиты:
    - Имя: Код, Тип: Строка
    -
        Имя: Файлы
        Представление: Вложения
        Настройки:
    - Имя: Телефон
      Тип: Строка
ТабличныеЧасти:
    - Имя: Навыки
""".strip()

    assert form_info.parse_list_section(text, "Реквизиты") == [
        {"Имя": "Код", "Тип": "Строка"},
        {"Имя": "Файлы", "Представление": "Вложения"},
        {"Имя": "Телефон", "Тип": "Строка"},
    ]


def test_parse_list_section_returns_empty_for_missing_section(form_info) -> None:
    assert form_info.parse_list_section("Имя: Сотрудники", "Реквизиты") == []


def test_parse_list_section_ignores_nested_lists_and_inline_fragments_without_pairs(form_info) -> None:
    text = """
Документ:
    Имя: Заказ
Реквизиты:
    - Имя: Номер, Пропуск, Тип: Строка
      Настройки:
            - ГлубокоВложенныйЭлемент
    -
        Имя: Контрагент
        Подсказка:
            - НеДолжноПопастьВСписок
        Тип: Контрагенты.Ссылка?
После:
    Имя: Другое
""".strip()

    assert form_info.parse_list_section(text, "Реквизиты") == [
        {"Имя": "Номер", "Тип": "Строка"},
        {"Имя": "Контрагент", "Тип": "Контрагенты.Ссылка?"},
    ]


def test_find_project_dirs_recurses_into_nested_directories(form_info, tmp_path: Path) -> None:
    project_dir, _ = create_project_structure(tmp_path)
    write_file(tmp_path / "README.md", "not a directory\n")

    assert form_info.find_project_dirs(str(tmp_path)) == [str(project_dir)]


def test_find_project_dirs_includes_root_project(form_info, tmp_path: Path) -> None:
    project_dir, _ = create_project_structure(tmp_path / "workspace")

    assert form_info.find_project_dirs(str(project_dir)) == [str(project_dir)]


def test_find_project_dirs_returns_empty_when_scandir_fails(form_info, monkeypatch) -> None:
    def fake_scandir(_root: str):
        raise OSError("permission denied")

    monkeypatch.setattr(form_info.os, "scandir", fake_scandir)

    assert form_info.find_project_dirs("/unreadable") == []


def test_find_object_handles_os_errors_and_returns_match(form_info, tmp_path: Path, monkeypatch) -> None:
    root_dir = tmp_path / "workspace"
    bad_project_dir = root_dir / "Acme" / "BrokenProject"
    good_project_dir, good_subsystem_dir = create_project_structure(root_dir, project="GoodProject")
    bad_project_dir.mkdir(parents=True)

    bad_subsystem_dir = good_project_dir / "Сломанная"
    bad_subsystem_dir.mkdir()
    write_file(bad_subsystem_dir / "Подсистема.yaml", "Имя: Сломанная\n")

    missing_subsystem_dir = good_project_dir / "БезПодсистемы"
    missing_subsystem_dir.mkdir()

    write_file(good_project_dir / "README.md", "skip me\n")
    write_file(good_subsystem_dir / "broken.yaml", "Имя: НеЧитается\n")
    write_file(good_subsystem_dir / "Сотрудники.yaml", "Имя: Сотрудники\n")
    write_file(good_subsystem_dir / "notes.txt", "skip me\n")

    real_scandir = form_info.os.scandir
    real_listdir = form_info.os.listdir
    real_open = builtins.open

    def fake_scandir(path: str):
        if path == str(bad_project_dir):
            raise OSError("broken scandir")
        return real_scandir(path)

    def fake_listdir(path: str):
        if path == str(bad_subsystem_dir):
            raise OSError("broken listdir")
        return real_listdir(path)

    def fake_open(path, *args, **kwargs):
        if str(path) == str(good_subsystem_dir / "broken.yaml"):
            raise OSError("broken file")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(form_info, "find_project_dirs", lambda _root: [str(bad_project_dir), str(good_project_dir)])
    monkeypatch.setattr(form_info.os, "scandir", fake_scandir)
    monkeypatch.setattr(form_info.os, "listdir", fake_listdir)
    monkeypatch.setattr(builtins, "open", fake_open)

    object_text = (good_subsystem_dir / "Сотрудники.yaml").read_text(encoding="utf-8")

    assert form_info.find_object(str(root_dir), "Сотрудники") == (
        str(good_subsystem_dir),
        "Сотрудники.yaml",
        object_text,
        "Acme::GoodProject::Основное",
    )


def test_find_object_uses_project_metadata_for_namespace(form_info, tmp_path: Path) -> None:
    root_dir = tmp_path / "workspace"
    project_dir = root_dir / "dir_vendor" / "dir_project"
    subsystem_dir = project_dir / "Основное"

    write_file(project_dir / "Проект.yaml", "Поставщик: Test\nИмя: LogicalProject\n")
    write_file(subsystem_dir / "Подсистема.yaml", "Имя: Подсистема\n")
    write_file(subsystem_dir / "Сотрудники.yaml", "Имя: Сотрудники\n")

    assert form_info.find_object(str(root_dir), "Сотрудники") == (
        str(subsystem_dir),
        "Сотрудники.yaml",
        "Имя: Сотрудники\n",
        "Test::LogicalProject::Основное",
    )


def test_get_project_namespace_parts_falls_back_to_directory_names(form_info, tmp_path: Path) -> None:
    project_dir = tmp_path / "dir_vendor" / "dir_project"
    project_dir.mkdir(parents=True)
    write_file(project_dir / "Проект.yaml", "Версия: 1.0\n")

    assert form_info.get_project_namespace_parts(str(project_dir)) == ("dir_vendor", "dir_project")


def test_find_object_continues_when_listdir_fails(form_info, tmp_path: Path, monkeypatch) -> None:
    root_dir = tmp_path / "workspace"
    project_dir, subsystem_dir = create_project_structure(root_dir)

    real_listdir = form_info.os.listdir

    def fake_listdir(path: str):
        if path == str(subsystem_dir):
            raise OSError("broken listdir")
        return real_listdir(path)

    monkeypatch.setattr(form_info, "find_project_dirs", lambda _root: [str(project_dir)])
    monkeypatch.setattr(form_info.os, "listdir", fake_listdir)

    assert form_info.find_object(str(root_dir), "Сотрудники") is None


@pytest.mark.parametrize(
    ("field_count", "tc_count", "expected"),
    [
        (0, 0, "simple"),
        (5, 1, "panels"),
        (4, 1, "tabs"),
        (1, 2, "tabs"),
    ],
)
def test_suggest_layout_variants(form_info, field_count: int, tc_count: int, expected: str) -> None:
    assert form_info.suggest_layout(field_count, tc_count) == expected


@pytest.mark.parametrize(
    ("obj_type", "field", "expected"),
    [
        ("Справочник", {"Имя": "Наименование"}, "Строка"),
        ("Документ", {"Имя": "Номер"}, "Строка"),
        ("Документ", {"Имя": "Файлы"}, "Файлы"),
        ("Справочник", {"Имя": "Код", "Тип": "Строка"}, "Строка"),
        ("Документ", {"Имя": "Дата"}, ""),
    ],
)
def test_infer_field_type_normalizes_standard_fields(form_info, obj_type: str, field: dict, expected: str) -> None:
    assert form_info.infer_field_type(obj_type, field) == expected


def test_main_prints_expected_json_for_found_object(form_info, tmp_path: Path, monkeypatch, capsys) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)
    write_file(
        subsystem_dir / "Employees.yaml",
        """
Имя: Сотрудники
ВидЭлемента: Справочник
Реквизиты:
    - Имя: Код, Тип: Строка
    - Имя: Наименование
    -
        Имя: Файлы
    - Имя: Телефон, Тип: Строка
    - Имя: Почта, Тип: Строка
ТабличныеЧасти:
    - Имя: Навыки
""".strip()
        + "\n",
    )
    write_file(subsystem_dir / "EmployeesФормаОбъекта.yaml", "Имя: ФормаОбъекта\n")

    monkeypatch.setattr(
        sys,
        "argv",
        ["form_info.py", "--name", "Сотрудники", "--root", str(tmp_path)],
    )

    form_info.main()

    result = json.loads(capsys.readouterr().out)

    assert result == {
        "object_path": str(subsystem_dir),
        "object_file": "Employees.yaml",
        "object_type": "Справочник",
        "namespace": "Acme::CRM::Основное",
        "field_count": 5,
        "tc_count": 1,
        "fields": [
            {"name": "Код", "type": "Строка"},
            {"name": "Наименование", "type": "Строка"},
            {"name": "Файлы", "type": "Файлы"},
            {"name": "Телефон", "type": "Строка"},
            {"name": "Почта", "type": "Строка"},
        ],
        "tc": [{"name": "Навыки"}],
        "suggested_layout": "panels",
        "existing_forms": {
            "ФормаОбъекта": "EmployeesФормаОбъекта.yaml",
            "ФормаСписка": None,
        },
        "is_hierarchical": False,
        "additional_hierarchies": [],
        "report_params": [],
        "data_source_kind": None,
        "data_source": None,
    }


def test_build_existing_forms_report_type_returns_forma_otcheta_key(form_info, tmp_path: Path) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)
    report_form_file = subsystem_dir / "АнализПродажФормаОтчета.yaml"
    report_form_file.write_text("Имя: ФормаОтчета\n", encoding="utf-8")

    result = form_info.build_existing_forms(str(subsystem_dir), "АнализПродаж.yaml", "Отчет")

    assert result == {"ФормаОтчета": "АнализПродажФормаОтчета.yaml"}


def test_build_existing_forms_non_report_type_returns_forma_obekta_and_spiska(form_info, tmp_path: Path) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)

    result = form_info.build_existing_forms(str(subsystem_dir), "Сотрудники.yaml", "Справочник")

    assert set(result.keys()) == {"ФормаОбъекта", "ФормаСписка"}


def test_build_result_for_report_returns_report_fields(form_info, tmp_path: Path) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)
    write_file(
        subsystem_dir / "АнализПродаж.yaml",
        """
ВидЭлемента: Отчет
Имя: АнализПродаж
ОбластьВидимости: ВПодсистеме
ВидИсточникаДанных: Запрос
Представление: Анализ продаж
ПараметрыЗапроса:
    -
        Имя: НачалоПериода
        Тип: ДатаВремя
    -
        Имя: КонецПериода
        Тип: ДатаВремя
""".strip()
        + "\n",
    )
    write_file(subsystem_dir / "АнализПродажФормаОтчета.yaml", "Имя: ФормаОтчета\n")

    found = form_info.find_object(str(tmp_path), "АнализПродаж")
    assert found is not None

    result = form_info.build_result(found)

    assert result["object_type"] == "Отчет"
    assert result["suggested_layout"] == "report"
    assert result["data_source_kind"] == "Запрос"
    assert result["data_source"] is None
    assert result["report_params"] == [
        {"name": "НачалоПериода", "type": "ДатаВремя"},
        {"name": "КонецПериода", "type": "ДатаВремя"},
    ]
    assert result["existing_forms"] == {"ФормаОтчета": "АнализПродажФормаОтчета.yaml"}
    assert result["fields"] == []



def test_main_infers_document_number_type_when_type_is_omitted(form_info, tmp_path: Path, monkeypatch, capsys) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)
    write_file(
        subsystem_dir / "Orders.yaml",
        """
Имя: Заказы
ВидЭлемента: Документ
Реквизиты:
    - Имя: Номер
    - Имя: Дата, Тип: ДатаВремя
""".strip()
        + "\n",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["form_info.py", "--name", "Заказы", "--root", str(tmp_path)],
    )

    form_info.main()

    result = json.loads(capsys.readouterr().out)

    assert result["object_type"] == "Документ"
    assert result["fields"] == [
        {"name": "Номер", "type": "Строка"},
        {"name": "Дата", "type": "ДатаВремя"},
    ]


def test_main_reports_ambiguity_and_exits(form_info, tmp_path: Path, monkeypatch, capsys) -> None:
    _, subsystem_dir_1 = create_project_structure(tmp_path, project="CRM")
    _, subsystem_dir_2 = create_project_structure(tmp_path, project="ERP")
    write_file(subsystem_dir_1 / "Сотрудники.yaml", "Имя: Сотрудники\n")
    write_file(subsystem_dir_2 / "Сотрудники.yaml", "Имя: Сотрудники\n")

    monkeypatch.setattr(
        sys,
        "argv",
        ["form_info.py", "--name", "Сотрудники", "--root", str(tmp_path)],
    )

    with pytest.raises(SystemExit) as exc_info:
        form_info.main()

    result = json.loads(capsys.readouterr().out)

    assert exc_info.value.code == 1
    assert result == {
        "error": 'Найдено несколько объектов с именем "Сотрудники"',
        "searched_in": str(tmp_path.resolve()),
        "matches": [
            {
                "object_path": str(subsystem_dir_1),
                "object_file": "Сотрудники.yaml",
                "namespace": "Acme::CRM::Основное",
            },
            {
                "object_path": str(subsystem_dir_2),
                "object_file": "Сотрудники.yaml",
                "namespace": "Acme::ERP::Основное",
            },
        ],
    }


def test_build_result_detects_simple_hierarchy(form_info, tmp_path: Path) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)
    write_file(
        subsystem_dir / "Категории.yaml",
        "Имя: Категории\nВидЭлемента: Справочник\nИерархический: Истина\nРеквизиты:\n    - Имя: Наименование\n",
    )
    found = form_info.find_object(str(tmp_path), "Категории")
    result = form_info.build_result(found)

    assert result["is_hierarchical"] is True
    assert result["additional_hierarchies"] == []


def test_build_result_detects_additional_hierarchies(form_info, tmp_path: Path) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)
    write_file(
        subsystem_dir / "Задачи.yaml",
        (
            "Имя: Задачи\nВидЭлемента: Справочник\n"
            "ДополнительныеИерархии:\n"
            "    -\n"
            "        Ид: aaa\n"
            "        Имя: Проект\n"
            "        ПолеРодителя: Проект\n"
            "    -\n"
            "        Ид: bbb\n"
            "        Имя: Исполнитель\n"
            "        ПолеРодителя: Исполнитель\n"
            "Реквизиты:\n    - Имя: Наименование\n"
        ),
    )
    found = form_info.find_object(str(tmp_path), "Задачи")
    result = form_info.build_result(found)

    assert result["is_hierarchical"] is False
    assert result["additional_hierarchies"] == [
        {"name": "Проект", "field": "Проект"},
        {"name": "Исполнитель", "field": "Исполнитель"},
    ]


def test_build_result_non_hierarchical_catalog(form_info, tmp_path: Path) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)
    write_file(
        subsystem_dir / "Товары.yaml",
        "Имя: Товары\nВидЭлемента: Справочник\nРеквизиты:\n    - Имя: Наименование\n",
    )
    found = form_info.find_object(str(tmp_path), "Товары")
    result = form_info.build_result(found)

    assert result["is_hierarchical"] is False
    assert result["additional_hierarchies"] == []


def test_script_entrypoint_prints_error_and_exits_when_object_not_found(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["form_info.py", "--name", "НеизвестныйОбъект", "--root", str(tmp_path)],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    result = json.loads(capsys.readouterr().out)

    assert exc_info.value.code == 1
    assert result == {
        "error": 'Объект "НеизвестныйОбъект" не найден',
        "searched_in": str(tmp_path.resolve()),
    }
