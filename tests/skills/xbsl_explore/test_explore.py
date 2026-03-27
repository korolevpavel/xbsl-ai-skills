from __future__ import annotations

import builtins
import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT_DIR / ".claude/skills/xbsl-explore/scripts/explore.py"


def load_explore_module():
    spec = importlib.util.spec_from_file_location("explore_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load module spec for {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def create_project_structure(
    base_dir: Path,
    project_dir_name: str = "crm",
    project_name: str | None = "CRM",
    subsystem_name: str = "Основное",
) -> tuple[Path, Path]:
    project_dir = base_dir / project_dir_name
    if project_name is None:
        project_yaml = "Версия: 1.0\n"
    else:
        project_yaml = f"Имя: {project_name}\n"

    subsystem_dir = project_dir / subsystem_name
    write_file(project_dir / "Проект.yaml", project_yaml)
    write_file(subsystem_dir / "Подсистема.yaml", "Имя: Подсистема\n")
    return project_dir, subsystem_dir


@pytest.fixture
def explore():
    return load_explore_module()


def test_get_yaml_field_handles_value_empty_and_missing(explore) -> None:
    text = 'Имя: "Сотрудники"\nПустое:\n'

    assert explore.get_yaml_field(text, "Имя") == "Сотрудники"
    assert explore.get_yaml_field(text, "Пустое") is None
    assert explore.get_yaml_field(text, "Несуществующее") is None


def test_scan_objects_collects_only_complete_yaml_objects(explore, tmp_path: Path, monkeypatch) -> None:
    subsystem_dir = tmp_path / "Основное"
    subsystem_dir.mkdir()
    write_file(subsystem_dir / "Catalog.yaml", "Имя: Сотрудники\nВидЭлемента: Справочник\n")
    write_file(subsystem_dir / "Broken.yaml", "Имя: Сломанный\nВидЭлемента: Документ\n")
    write_file(subsystem_dir / "MissingType.yaml", "Имя: БезТипа\n")
    write_file(subsystem_dir / "notes.txt", "skip me\n")

    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == str(subsystem_dir / "Broken.yaml"):
            raise OSError("broken file")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)

    assert explore.scan_objects(str(subsystem_dir)) == [
        {"name": "Сотрудники", "type": "Справочник", "file": "Catalog.yaml"},
    ]


def test_scan_objects_returns_empty_when_listdir_fails(explore, monkeypatch) -> None:
    def fake_listdir(_path: str):
        raise OSError("permission denied")

    monkeypatch.setattr(explore.os, "listdir", fake_listdir)

    assert explore.scan_objects("/unreadable") == []


def test_find_subsystems_detects_only_marked_directories(explore, tmp_path: Path) -> None:
    project_dir, subsystem_dir = create_project_structure(tmp_path, project_dir_name="crm")
    write_file(subsystem_dir / "Employees.yaml", "Имя: Сотрудники\nВидЭлемента: Справочник\n")
    write_file(project_dir / "README.md", "skip me\n")
    write_file(project_dir / "Common" / "Employees.yaml", "Имя: НеДолженПопасть\nВидЭлемента: Справочник\n")

    assert explore.find_subsystems(str(project_dir)) == [
        {
            "name": "Основное",
            "path": str(subsystem_dir),
            "objects": [
                {"name": "Сотрудники", "type": "Справочник", "file": "Employees.yaml"},
            ],
        }
    ]


def test_find_subsystems_returns_empty_when_scandir_fails(explore, monkeypatch) -> None:
    def fake_scandir(_path: str):
        raise OSError("permission denied")

    monkeypatch.setattr(explore.os, "scandir", fake_scandir)

    assert explore.find_subsystems("/unreadable") == []


def test_find_projects_uses_project_name_and_directory_fallback(explore, tmp_path: Path, monkeypatch) -> None:
    _, alpha_subsystem_dir = create_project_structure(tmp_path, project_dir_name="alpha", project_name="CRM")
    write_file(alpha_subsystem_dir / "Employees.yaml", "Имя: Сотрудники\nВидЭлемента: Справочник\n")

    _, beta_subsystem_dir = create_project_structure(tmp_path, project_dir_name="beta", project_name=None)
    write_file(beta_subsystem_dir / "Orders.yaml", "Имя: Заказы\nВидЭлемента: Документ\n")

    broken_project_dir, _ = create_project_structure(tmp_path, project_dir_name="broken", project_name="Broken")

    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == str(broken_project_dir / "Проект.yaml"):
            raise OSError("broken project file")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)

    assert explore.find_projects(str(tmp_path)) == [
        {
            "name": "CRM",
            "path": str(tmp_path / "alpha"),
            "subsystems": [
                {
                    "name": "Основное",
                    "path": str(alpha_subsystem_dir),
                    "objects": [
                        {"name": "Сотрудники", "type": "Справочник", "file": "Employees.yaml"},
                    ],
                }
            ],
        },
        {
            "name": "beta",
            "path": str(tmp_path / "beta"),
            "subsystems": [
                {
                    "name": "Основное",
                    "path": str(beta_subsystem_dir),
                    "objects": [
                        {"name": "Заказы", "type": "Документ", "file": "Orders.yaml"},
                    ],
                }
            ],
        },
    ]


def test_find_projects_returns_empty_when_scandir_fails(explore, monkeypatch) -> None:
    def fake_scandir(_path: str):
        raise OSError("permission denied")

    monkeypatch.setattr(explore.os, "scandir", fake_scandir)

    assert explore.find_projects("/unreadable") == []


def test_check_name_conflict_returns_first_match_and_none(explore) -> None:
    projects = [
        {
            "name": "CRM",
            "subsystems": [
                {
                    "name": "Основное",
                    "path": "/tmp/crm",
                    "objects": [
                        {"name": "Сотрудники", "type": "Справочник", "file": "Employees.yaml"},
                        {"name": "Заказы", "type": "Документ", "file": "Orders.yaml"},
                    ],
                }
            ],
        },
        {
            "name": "ERP",
            "subsystems": [
                {
                    "name": "Сервис",
                    "path": "/tmp/erp",
                    "objects": [
                        {"name": "Сотрудники", "type": "Справочник", "file": "Staff.yaml"},
                    ],
                }
            ],
        },
    ]

    assert explore.check_name_conflict(projects, "Сотрудники") == {
        "project": "CRM",
        "subsystem": "Основное",
        "path": "/tmp/crm",
        "type": "Справочник",
        "file": "Employees.yaml",
    }
    assert explore.check_name_conflict(projects, "Неизвестный") is None


def test_main_filters_objects_but_checks_name_conflict_before_filtering(
    explore,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    alpha_project_dir, alpha_subsystem_dir = create_project_structure(
        tmp_path,
        project_dir_name="alpha",
        project_name="CRM",
    )
    write_file(alpha_subsystem_dir / "Employees.yaml", "Имя: Сотрудники\nВидЭлемента: Справочник\n")
    write_file(alpha_subsystem_dir / "Orders.yaml", "Имя: Заказы\nВидЭлемента: Документ\n")

    _, beta_subsystem_dir = create_project_structure(
        tmp_path,
        project_dir_name="beta",
        project_name="ERP",
        subsystem_name="Сервис",
    )
    write_file(beta_subsystem_dir / "Acts.yaml", "Имя: Акты\nВидЭлемента: Документ\n")

    monkeypatch.setattr(
        sys,
        "argv",
        ["explore.py", "--type", "Документ", "--name", "Сотрудники", "--root", str(tmp_path)],
    )

    explore.main()

    result = json.loads(capsys.readouterr().out)

    assert result == {
        "projects": [
            {
                "name": "CRM",
                "path": str(alpha_project_dir),
                "subsystems": [
                    {
                        "name": "Основное",
                        "path": str(alpha_subsystem_dir),
                        "objects": [
                            {"name": "Заказы", "type": "Документ", "file": "Orders.yaml"},
                        ],
                    }
                ],
            },
            {
                "name": "ERP",
                "path": str(tmp_path / "beta"),
                "subsystems": [
                    {
                        "name": "Сервис",
                        "path": str(beta_subsystem_dir),
                        "objects": [
                            {"name": "Акты", "type": "Документ", "file": "Acts.yaml"},
                        ],
                    }
                ],
            },
        ],
        "name_check": "Сотрудники",
        "conflict": {
            "project": "CRM",
            "subsystem": "Основное",
            "path": str(alpha_subsystem_dir),
            "type": "Справочник",
            "file": "Employees.yaml",
        },
        "suggested_path": str(alpha_subsystem_dir),
    }


def test_script_entrypoint_prints_error_and_exits_when_projects_not_found(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["explore.py", "--root", str(tmp_path)],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    result = json.loads(capsys.readouterr().out)

    assert exc_info.value.code == 1
    assert result == {
        "error": "Проекты не найдены (нет папок с Проект.yaml)",
        "searched_in": str(tmp_path.resolve()),
    }
