from __future__ import annotations

import builtins
import importlib.util
import runpy
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT_DIR / ".claude/skills/xbsl-rename/scripts/rename.py"


def load_rename_module():
    spec = importlib.util.spec_from_file_location("rename_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load module spec for {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def create_project_structure(base_dir: Path, project_dir_name: str = "crm", subsystem_name: str = "Основное") -> tuple[Path, Path]:
    project_dir = base_dir / project_dir_name
    subsystem_dir = project_dir / subsystem_name
    write_file(project_dir / "Проект.yaml", "Имя: CRM\n")
    write_file(subsystem_dir / "Подсистема.yaml", "Имя: Подсистема\n")
    return project_dir, subsystem_dir


def create_catalog_fixture(base_dir: Path) -> tuple[Path, Path]:
    project_dir, subsystem_dir = create_project_structure(base_dir)
    write_file(
        subsystem_dir / "Номенклатура.yaml",
        """
Имя: Номенклатура
ВидЭлемента: Справочник
Форма: НоменклатураФормаОбъекта
Реквизиты:
    - Имя: Родитель, Тип: Номенклатура.Ссылка?
""".strip()
        + "\n",
    )
    write_file(
        subsystem_dir / "НоменклатураФормаОбъекта.yaml",
        """
Имя: НоменклатураФормаОбъекта
ВидЭлемента: КомпонентИнтерфейса
Тип: ФормаОбъекта<Номенклатура.Объект>
""".strip()
        + "\n",
    )
    write_file(
        subsystem_dir / "Номенклатура.Объект.xbsl",
        """
Перем Номенклатура;

Процедура ПередЗаписью()
    Значение = Номенклатура;
КонецПроцедуры
""".strip()
        + "\n",
    )
    write_file(
        subsystem_dir / "Служебный.yaml",
        """
Имя: Номенклатурация
ВидЭлемента: Справочник
""".strip()
        + "\n",
    )
    return project_dir, subsystem_dir


@pytest.fixture
def rename():
    return load_rename_module()


def test_get_yaml_field_handles_quoted_empty_and_missing_values(rename) -> None:
    text = 'Имя: "Номенклатура"\nПустое:\n'

    assert rename.get_yaml_field(text, "Имя") == "Номенклатура"
    assert rename.get_yaml_field(text, "Пустое") is None
    assert rename.get_yaml_field(text, "Несуществующее") is None


def test_find_project_roots_returns_sorted_projects_without_descending_into_nested_project(rename, tmp_path: Path) -> None:
    outer_project_dir, _ = create_project_structure(tmp_path, project_dir_name="b_outer")
    nested_project_dir, _ = create_project_structure(outer_project_dir / "nested", project_dir_name="inner")
    sibling_project_dir, _ = create_project_structure(tmp_path, project_dir_name="a_sibling")

    assert rename.find_project_roots(str(tmp_path)) == [
        str(sibling_project_dir),
        str(outer_project_dir),
    ]
    assert str(nested_project_dir) not in rename.find_project_roots(str(tmp_path))


def test_apply_substitutions_updates_standalone_and_compound_references_only(rename) -> None:
    content = """
Имя: Номенклатура
Форма: НоменклатураФормаОбъекта
Тип: ФормаОбъекта<Номенклатура.Объект>
Комментарий: Номенклатурация
""".strip()

    assert rename.apply_substitutions(content, "Номенклатура", "Товары") == """
Имя: Товары
Форма: ТоварыФормаОбъекта
Тип: ФормаОбъекта<Товары.Объект>
Комментарий: Номенклатурация
""".strip()


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Номенклатура.yaml", "Товары.yaml"),
        ("НоменклатураФормаОбъекта.yaml", "ТоварыФормаОбъекта.yaml"),
        ("МояНоменклатура.yaml", "МояНоменклатура.yaml"),
    ],
)
def test_new_filename_renames_only_supported_patterns(rename, filename: str, expected: str) -> None:
    assert rename.new_filename(filename, "Номенклатура", "Товары") == expected


def test_find_object_file_skips_unreadable_yaml(rename, tmp_path: Path, monkeypatch) -> None:
    project_dir, subsystem_dir = create_project_structure(tmp_path)
    unreadable_path = subsystem_dir / "Сломанный.yaml"
    target_path = subsystem_dir / "Номенклатура.yaml"
    write_file(unreadable_path, "Имя: Номенклатура\n")
    write_file(target_path, "Имя: Номенклатура\n")
    write_file(subsystem_dir / "Номенклатура.Объект.xbsl", "Перем Номенклатура;\n")

    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == str(unreadable_path):
            raise OSError("broken file")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)

    project_files = rename.collect_project_files(str(project_dir))

    assert rename.find_object_file(project_files, "Номенклатура") == str(target_path)


def test_build_plan_collects_text_changes_and_renames(rename, tmp_path: Path) -> None:
    project_dir, subsystem_dir = create_catalog_fixture(tmp_path)
    project_files = rename.collect_project_files(str(project_dir))

    text_changes, renames = rename.build_plan(project_files, "Номенклатура", "Товары")

    changed_paths = {Path(path) for path, _original, _modified in text_changes}
    assert changed_paths == {
        subsystem_dir / "Номенклатура.yaml",
        subsystem_dir / "НоменклатураФормаОбъекта.yaml",
        subsystem_dir / "Номенклатура.Объект.xbsl",
    }
    assert (subsystem_dir / "Служебный.yaml") not in changed_paths
    assert set(renames) == {
        (str(subsystem_dir / "Номенклатура.Объект.xbsl"), str(subsystem_dir / "Товары.Объект.xbsl")),
        (str(subsystem_dir / "Номенклатура.yaml"), str(subsystem_dir / "Товары.yaml")),
        (str(subsystem_dir / "НоменклатураФормаОбъекта.yaml"), str(subsystem_dir / "ТоварыФормаОбъекта.yaml")),
    }


def test_script_entrypoint_exits_when_projects_not_found(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["rename.py", "--old-name", "Номенклатура", "--new-name", "Товары", "--root", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert f"Ошибка: проекты не найдены (нет папок с Проект.yaml) в {tmp_path.resolve()}" in captured.err


def test_main_exits_when_object_not_found(rename, tmp_path: Path, monkeypatch, capsys) -> None:
    create_project_structure(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["rename.py", "--old-name", "Номенклатура", "--new-name", "Товары", "--root", str(tmp_path)],
    )

    with pytest.raises(SystemExit) as exc_info:
        rename.main()

    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert "Ошибка: объект с именем «Номенклатура» не найден в проектах." in captured.err


def test_main_dry_run_prints_plan_without_changing_files(rename, tmp_path: Path, monkeypatch, capsys) -> None:
    _, subsystem_dir = create_catalog_fixture(tmp_path)
    original_object_text = (subsystem_dir / "Номенклатура.yaml").read_text(encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        ["rename.py", "--old-name", "Номенклатура", "--new-name", "Товары", "--root", str(tmp_path)],
    )

    rename.main()

    captured = capsys.readouterr()

    assert "Объект: crm/Основное/Номенклатура.yaml" in captured.out
    assert "=== Файлы для переименования (3) ===" in captured.out
    assert "НоменклатураФормаОбъекта.yaml" in captured.out
    assert "+ Форма: ТоварыФормаОбъекта" in captured.out
    assert "--- Dry-run. Для применения добавьте флаг --apply ---" in captured.out
    assert (subsystem_dir / "Номенклатура.yaml").read_text(encoding="utf-8") == original_object_text
    assert not (subsystem_dir / "Товары.yaml").exists()


def test_main_apply_updates_files_and_renames_targets(rename, tmp_path: Path, monkeypatch, capsys) -> None:
    _, subsystem_dir = create_catalog_fixture(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["rename.py", "--old-name", "Номенклатура", "--new-name", "Товары", "--root", str(tmp_path), "--apply"],
    )

    rename.main()

    captured = capsys.readouterr()
    catalog_yaml = subsystem_dir / "Товары.yaml"
    form_yaml = subsystem_dir / "ТоварыФормаОбъекта.yaml"
    object_xbsl = subsystem_dir / "Товары.Объект.xbsl"

    assert "✓ Применено: 3 файлов обновлено, 3 переименовано." in captured.out
    assert catalog_yaml.exists()
    assert form_yaml.exists()
    assert object_xbsl.exists()
    assert not (subsystem_dir / "Номенклатура.yaml").exists()
    assert not (subsystem_dir / "НоменклатураФормаОбъекта.yaml").exists()
    assert not (subsystem_dir / "Номенклатура.Объект.xbsl").exists()
    assert "Имя: Товары" in catalog_yaml.read_text(encoding="utf-8")
    assert "Форма: ТоварыФормаОбъекта" in catalog_yaml.read_text(encoding="utf-8")
    assert "Тип: ФормаОбъекта<Товары.Объект>" in form_yaml.read_text(encoding="utf-8")
    assert "Значение = Товары;" in object_xbsl.read_text(encoding="utf-8")
    assert "Номенклатурация" in (subsystem_dir / "Служебный.yaml").read_text(encoding="utf-8")
