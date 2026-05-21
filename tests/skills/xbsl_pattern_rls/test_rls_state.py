from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT_DIR / ".claude/skills/xbsl-pattern-rls/scripts/rls_state.py"


def load_module():
    spec = importlib.util.spec_from_file_location("rls_state_under_test", SCRIPT_PATH)
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
def rls_state():
    return load_module()


# --- parse_control_access ---

def test_parse_control_access_returns_empty_when_section_missing(rls_state) -> None:
    text = "Имя: Задачи\nВидЭлемента: Справочник\n"
    result = rls_state.parse_control_access(text)
    assert result == {"exists": False, "расчет_разрешений_по": [], "разрешения": {}}


def test_parse_control_access_parses_full_section(rls_state) -> None:
    text = (
        "Имя: Задачи\n"
        "КонтрольДоступа:\n"
        "    РасчетРазрешенийПо:\n"
        "        - Пользователь\n"
        "        - Организация\n"
        "    Разрешения:\n"
        "        ПоУмолчанию: РазрешенияВычисляютсяДляКаждогоОбъекта\n"
    )
    result = rls_state.parse_control_access(text)
    assert result["exists"] is True
    assert result["расчет_разрешений_по"] == ["Пользователь", "Организация"]
    assert result["разрешения"] == {"ПоУмолчанию": "РазрешенияВычисляютсяДляКаждогоОбъекта"}


def test_parse_control_access_single_field(rls_state) -> None:
    text = (
        "Имя: Задачи\n"
        "КонтрольДоступа:\n"
        "    РасчетРазрешенийПо:\n"
        "        - Пользователь\n"
        "    Разрешения:\n"
        "        ПоУмолчанию: РазрешеноАутентифицированным\n"
    )
    result = rls_state.parse_control_access(text)
    assert result["расчет_разрешений_по"] == ["Пользователь"]
    assert result["разрешения"]["ПоУмолчанию"] == "РазрешеноАутентифицированным"


# --- check_handlers ---

def test_check_handlers_both_absent(rls_state) -> None:
    assert rls_state.check_handlers("метод НекийМетод()\n;") == {"level1": False, "level2": False}


def test_check_handlers_level1_only(rls_state) -> None:
    xbsl = "метод ВычислитьРазрешенияДоступа()\n    Возврат Неопределено\n;"
    result = rls_state.check_handlers(xbsl)
    assert result["level1"] is True
    assert result["level2"] is False


def test_check_handlers_both_present(rls_state) -> None:
    xbsl = (
        "метод ВычислитьРазрешенияДоступа()\n;\n"
        "метод ВычислитьРазрешенияДоступаДляОбъектов(Объекты)\n;\n"
    )
    result = rls_state.check_handlers(xbsl)
    assert result["level1"] is True
    assert result["level2"] is True


# --- build_pattern_hints ---

def test_build_pattern_hints_empty_fields(rls_state) -> None:
    assert rls_state.build_pattern_hints([]) == []


def test_build_pattern_hints_p1(rls_state) -> None:
    fields = [{"Имя": "Пользователь", "Тип": "Пользователи.Ссылка?"}]
    hints = rls_state.build_pattern_hints(fields)
    assert hints == [{"field": "Пользователь", "type": "Пользователи.Ссылка?", "pattern": "P1"}]


def test_build_pattern_hints_p2_single(rls_state) -> None:
    fields = [{"Имя": "Организация", "Тип": "Организации.Ссылка?"}]
    hints = rls_state.build_pattern_hints(fields)
    assert hints == [{"field": "Организация", "type": "Организации.Ссылка?", "pattern": "P2"}]


def test_build_pattern_hints_p3_two_ref_fields(rls_state) -> None:
    fields = [
        {"Имя": "Заказчик", "Тип": "Клиенты.Ссылка?"},
        {"Имя": "Исполнитель", "Тип": "Сотрудники.Ссылка?"},
    ]
    hints = rls_state.build_pattern_hints(fields)
    assert all(h["pattern"] == "P2/P3" for h in hints)
    assert len(hints) == 2


def test_build_pattern_hints_skips_non_ref_fields(rls_state) -> None:
    fields = [
        {"Имя": "Наименование", "Тип": "Строка"},
        {"Имя": "Пользователь", "Тип": "Пользователи.Ссылка?"},
    ]
    hints = rls_state.build_pattern_hints(fields)
    assert len(hints) == 1
    assert hints[0]["pattern"] == "P1"


# --- find_xbsl_file ---

def test_find_xbsl_file_prefers_object_suffix(rls_state, tmp_path: Path) -> None:
    write_file(tmp_path / "Задачи.Объект.xbsl", "метод X();")
    write_file(tmp_path / "Задачи.xbsl", "метод Y();")
    xbsl_file, exists = rls_state.find_xbsl_file(str(tmp_path), "Задачи")
    assert xbsl_file == "Задачи.Объект.xbsl"
    assert exists is True


def test_find_xbsl_file_falls_back_to_plain_xbsl(rls_state, tmp_path: Path) -> None:
    write_file(tmp_path / "Задачи.xbsl", "метод Y();")
    xbsl_file, exists = rls_state.find_xbsl_file(str(tmp_path), "Задачи")
    assert xbsl_file == "Задачи.xbsl"
    assert exists is True


def test_find_xbsl_file_returns_none_when_missing(rls_state, tmp_path: Path) -> None:
    xbsl_file, exists = rls_state.find_xbsl_file(str(tmp_path), "Задачи")
    assert xbsl_file is None
    assert exists is False


# --- main / integration ---

def test_main_object_not_found(rls_state, tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["rls_state.py", "--name", "НеизвестныйОбъект", "--root", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        rls_state.main()
    result = json.loads(capsys.readouterr().out)
    assert exc_info.value.code == 1
    assert "не найден" in result["error"]


def test_main_object_found_no_xbsl(rls_state, tmp_path: Path, monkeypatch, capsys) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)
    write_file(
        subsystem_dir / "Задачи.yaml",
        "Имя: Задачи\nВидЭлемента: Справочник\nРеквизиты:\n    - Имя: Пользователь, Тип: Пользователи.Ссылка?\n",
    )
    monkeypatch.setattr(sys, "argv", ["rls_state.py", "--name", "Задачи", "--root", str(tmp_path)])
    rls_state.main()
    result = json.loads(capsys.readouterr().out)
    assert result["object_name"] == "Задачи"
    assert result["xbsl_exists"] is False
    assert result["xbsl_file"] is None
    assert result["handlers"] == {"level1": False, "level2": False}
    assert result["control_access"]["exists"] is False
    assert result["pattern_hints"] == [{"field": "Пользователь", "type": "Пользователи.Ссылка?", "pattern": "P1"}]


def test_main_object_with_control_access_and_handlers(rls_state, tmp_path: Path, monkeypatch, capsys) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)
    write_file(
        subsystem_dir / "Задачи.yaml",
        (
            "Имя: Задачи\n"
            "ВидЭлемента: Справочник\n"
            "КонтрольДоступа:\n"
            "    РасчетРазрешенийПо:\n"
            "        - Пользователь\n"
            "    Разрешения:\n"
            "        ПоУмолчанию: РазрешенияВычисляютсяДляКаждогоОбъекта\n"
            "Реквизиты:\n"
            "    - Имя: Пользователь, Тип: Пользователи.Ссылка?\n"
        ),
    )
    write_file(
        subsystem_dir / "Задачи.Объект.xbsl",
        "метод ВычислитьРазрешенияДоступа()\n;\nметод ВычислитьРазрешенияДоступаДляОбъектов(Объекты)\n;\n",
    )
    monkeypatch.setattr(sys, "argv", ["rls_state.py", "--name", "Задачи", "--root", str(tmp_path)])
    rls_state.main()
    result = json.loads(capsys.readouterr().out)
    assert result["xbsl_file"] == "Задачи.Объект.xbsl"
    assert result["xbsl_exists"] is True
    assert result["handlers"] == {"level1": True, "level2": True}
    assert result["control_access"]["exists"] is True
    assert result["control_access"]["расчет_разрешений_по"] == ["Пользователь"]
    assert result["control_access"]["разрешения"] == {"ПоУмолчанию": "РазрешенияВычисляютсяДляКаждогоОбъекта"}


def test_script_entrypoint_exits_when_not_found(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["rls_state.py", "--name", "Неизвестный", "--root", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
    result = json.loads(capsys.readouterr().out)
    assert exc_info.value.code == 1
    assert result["error"] == 'Объект "Неизвестный" не найден'
