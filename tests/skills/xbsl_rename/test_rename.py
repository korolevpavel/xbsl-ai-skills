from __future__ import annotations

import builtins
import importlib.util
import runpy
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT_DIR / "skills/xbsl-rename/scripts/rename.py"


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
Перем ЛокальнаяНоменклатура;

Процедура ПередЗаписью()
    Значение = Номенклатура.Найти(Ссылка);
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


def test_get_yaml_field_ignores_nested_identity(rename) -> None:
    text = "Реквизиты:\n    - Имя: Категории\nИмя: ДругойОбъект\n"

    assert rename.get_yaml_field(text, "Имя") == "ДругойОбъект"


def test_bom_owner_identity_is_replaced_consistently(rename) -> None:
    content = "\ufeffИмя: Клиенты\r\nВидЭлемента: Справочник\r\n"

    assert rename.get_yaml_field(content, "Имя") == "Клиенты"
    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".yaml",
    ) == "\ufeffИмя: Покупатели\r\nВидЭлемента: Справочник\r\n"


@pytest.mark.parametrize(
    "line",
    [
        "Имя: КатегорииНоменклатуры # inline comment\n",
        "Имя: 'КатегорииНоменклатуры'\n",
        '"Имя": "КатегорииНоменклатуры" # inline comment\n',
    ],
)
def test_get_yaml_field_normalizes_quotes_and_inline_comments(rename, line: str) -> None:
    assert rename.get_yaml_field(line, "Имя") == "КатегорииНоменклатуры"


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
НезависимаяФорма: НоменклатураФормаОбъектаАрхив
UnicodeПрефикс: НоменклатураÜ
""".strip()

    assert rename.apply_substitutions(content, "Номенклатура", "Товары") == """
Имя: Товары
Форма: ТоварыФормаОбъекта
Тип: ФормаОбъекта<Товары.Объект>
Комментарий: Номенклатурация
НезависимаяФорма: НоменклатураФормаОбъектаАрхив
UnicodeПрефикс: НоменклатураÜ
""".strip()


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Номенклатура.yaml", "Товары.yaml"),
        ("НоменклатураФормаОбъекта.yaml", "ТоварыФормаОбъекта.yaml"),
        ("МояНоменклатура.yaml", "МояНоменклатура.yaml"),
        ("НоменклатураТоваров.yaml", "НоменклатураТоваров.yaml"),
        ("НоменклатураФормаОбъектаАрхив.yaml", "НоменклатураФормаОбъектаАрхив.yaml"),
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

    matches = rename.find_object_files(project_files, "Номенклатура")
    assert len(matches) == 1
    assert matches[0][0] == str(target_path)


def test_read_write_preserves_crlf(rename, tmp_path: Path) -> None:
    source = tmp_path / "Источник.xbsl"
    source.write_bytes("пер Значение: Клиенты.Ссылка?\r\n".encode())

    content = rename.read_text(str(source))
    modified = rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    )
    rename.write_text(str(source), modified)

    assert source.read_bytes() == "пер Значение: Покупатели.Ссылка?\r\n".encode()


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
    assert "Тип: Товары.Ссылка?" in catalog_yaml.read_text(encoding="utf-8")
    assert "Тип: ФормаОбъекта<Товары.Объект>" in form_yaml.read_text(encoding="utf-8")
    assert "Значение = Товары.Найти(Ссылка);" in object_xbsl.read_text(encoding="utf-8")
    assert "Номенклатурация" in (subsystem_dir / "Служебный.yaml").read_text(encoding="utf-8")


def test_common_prefix_neighbor_stays_byte_identical_in_preview_and_apply(
    rename, tmp_path: Path, monkeypatch, capsys
) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)
    write_file(
        subsystem_dir / "Категории.yaml",
        "Имя: Категории\n"
        "ВидЭлемента: Справочник\n"
        "Интерфейс:\n"
        "    Объект:\n"
        "        Форма: КатегорииФормаОбъекта\n"
        "    Список:\n"
        "        Форма: КатегорииФормаСписка\n",
    )
    write_file(
        subsystem_dir / "КатегорииФормаОбъекта.yaml",
        "Имя: КатегорииФормаОбъекта\n"
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Тип: ФормаОбъекта<Категории.Объект>\n",
    )
    write_file(
        subsystem_dir / "Категории.Объект.xbsl",
        "пер Категории: Категории.Ссылка?\n",
    )
    write_file(
        subsystem_dir / "КатегорииФормаОбъекта.xbsl",
        "пер Владелец: Категории.Объект\n",
    )
    write_file(
        subsystem_dir / "КатегорииФормаСписка.yaml",
        "Имя: КатегорииФормаСписка\n"
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Тип: ФормаСписка<Категории.ДанныеСтрокиСписка>\n",
    )
    write_file(
        subsystem_dir / "КатегорииФормаСписка.xbsl",
        "пер Строка: Категории.ДанныеСтрокиСписка\n",
    )
    independent_files = [
        subsystem_dir / "КатегорииТоваров.yaml",
        subsystem_dir / "КатегорииТоваровФормаОбъекта.yaml",
        subsystem_dir / "КатегорииТоваровФормаСписка.yaml",
        subsystem_dir / "КатегорииТоваров.Объект.xbsl",
        subsystem_dir / "КатегорииТоваровФормаОбъекта.xbsl",
        subsystem_dir / "КатегорииФормаОтчета.yaml",
    ]
    write_file(
        independent_files[0],
        "Имя: КатегорииТоваров\n"
        "ВидЭлемента: Справочник\n"
        "Интерфейс:\n"
        "    Объект:\n"
        "        Форма: КатегорииТоваровФормаОбъекта\n"
        "    Список:\n"
        "        Форма: КатегорииТоваровФормаСписка\n",
    )
    write_file(
        independent_files[1],
        "Имя: КатегорииТоваровФормаОбъекта\n"
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Тип: ФормаОбъекта<КатегорииТоваров.Объект>\n",
    )
    write_file(
        independent_files[2],
        "Имя: КатегорииТоваровФормаСписка\n"
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Тип: ФормаСписка<КатегорииТоваров.ДанныеСтрокиСписка>\n",
    )
    write_file(
        independent_files[3],
        "пер КатегорииТоваров: КатегорииТоваров.Ссылка?\n",
    )
    write_file(
        independent_files[4],
        "пер Владелец: КатегорииТоваров.Объект\n",
    )
    write_file(
        independent_files[5],
        "Имя: КатегорииФормаОтчета\n"
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Тип: ФормаОтчета<ДругойОтчет.Данные>\n",
    )
    consumer = subsystem_dir / "Потребитель.yaml"
    write_file(
        consumer,
        "Имя: Потребитель\n"
        "ВидЭлемента: Документ\n"
        "Импорт:\n"
        "    - Категории\n"
        "Тип: Категории.Ссылка?\n"
        "Форма: КатегорииФормаОбъекта\n",
    )
    xbsl_consumer = subsystem_dir / "Потребитель.xbsl"
    write_file(
        xbsl_consumer,
        "импорт Категории\n"
        "пер ТочнаяСсылка: Категории.Ссылка?\n"
        "пер НезависимаяСсылка: КатегорииТоваров.Ссылка?\n",
    )
    independent_before = {path: path.read_bytes() for path in independent_files}

    base_argv = [
        "rename.py",
        "--old-name",
        "Категории",
        "--new-name",
        "КатегорииНоменклатуры",
        "--root",
        str(tmp_path),
    ]
    monkeypatch.setattr(sys, "argv", base_argv)
    rename.main()
    preview = capsys.readouterr().out

    assert "КатегорииТоваров" not in preview

    monkeypatch.setattr(sys, "argv", [*base_argv, "--apply"])
    rename.main()
    capsys.readouterr()

    assert {path: path.read_bytes() for path in independent_files} == independent_before
    assert (subsystem_dir / "КатегорииНоменклатуры.yaml").is_file()
    assert (subsystem_dir / "КатегорииНоменклатурыФормаОбъекта.yaml").is_file()
    assert (subsystem_dir / "КатегорииНоменклатурыФормаОбъекта.xbsl").is_file()
    assert (subsystem_dir / "КатегорииНоменклатурыФормаСписка.yaml").is_file()
    assert (subsystem_dir / "КатегорииНоменклатурыФормаСписка.xbsl").is_file()
    assert (subsystem_dir / "КатегорииНоменклатуры.Объект.xbsl").is_file()
    consumer_text = consumer.read_text(encoding="utf-8")
    assert "    - Категории\n" in consumer_text
    assert "Тип: КатегорииНоменклатуры.Ссылка?" in consumer_text
    assert "Форма: КатегорииНоменклатурыФормаОбъекта" in consumer_text
    xbsl_consumer_text = xbsl_consumer.read_text(encoding="utf-8")
    assert "импорт Категории\n" in xbsl_consumer_text
    assert "КатегорииНоменклатуры.Ссылка?" in xbsl_consumer_text
    assert "КатегорииТоваров.Ссылка?" in xbsl_consumer_text


@pytest.mark.parametrize(
    "collision_line",
    [
        "Имя: КатегорииНоменклатуры\n",
        "Имя: категорииноменклатуры\n",
        "Имя: 'КатегорииНоменклатуры'\n",
        'Имя: "КатегорииНоменклатуры" # existing logical name\n',
    ],
)
def test_apply_blocks_new_name_collision_before_any_write(
    rename, tmp_path: Path, monkeypatch, capsys, collision_line: str
) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)
    target = subsystem_dir / "Категории.yaml"
    collision = subsystem_dir / "ДругойФайл.yaml"
    consumer = subsystem_dir / "Потребитель.xbsl"
    write_file(target, "Имя: Категории\nВидЭлемента: Справочник\n")
    write_file(
        collision,
        collision_line + "ВидЭлемента: Справочник\n",
    )
    write_file(consumer, "пер Значение: Категории.Ссылка?\n")
    before = {path: path.read_bytes() for path in (target, collision, consumer)}

    def unexpected_write(*_args, **_kwargs):
        pytest.fail("collision preflight must run before write_text/os.rename")

    monkeypatch.setattr(rename, "write_text", unexpected_write)
    monkeypatch.setattr(rename.os, "rename", unexpected_write)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rename.py",
            "--old-name",
            "Категории",
            "--new-name",
            "КатегорииНоменклатуры",
            "--root",
            str(tmp_path),
            "--apply",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        rename.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "коллиз" in captured.err.lower()
    assert {path: path.read_bytes() for path in (target, collision, consumer)} == before


def test_apply_blocks_companion_path_collision_before_any_write(
    rename, tmp_path: Path, monkeypatch, capsys
) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)
    target = subsystem_dir / "Категории.yaml"
    target_module = subsystem_dir / "Категории.xbsl"
    destination_collision = subsystem_dir / "КатегорииНоменклатуры.xbsl"
    consumer = subsystem_dir / "Потребитель.xbsl"
    write_file(target, "Имя: Категории\nВидЭлемента: Справочник\n")
    write_file(target_module, "пер Значение: Категории.Ссылка?\n")
    write_file(destination_collision, "// independent destination\n")
    write_file(consumer, "пер Значение: Категории.Ссылка?\n")
    before = {
        path: path.read_bytes()
        for path in (target, target_module, destination_collision, consumer)
    }

    def unexpected_write(*_args, **_kwargs):
        pytest.fail("path collision preflight must run before write_text/os.rename")

    monkeypatch.setattr(rename, "write_text", unexpected_write)
    monkeypatch.setattr(rename.os, "rename", unexpected_write)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rename.py",
            "--old-name",
            "Категории",
            "--new-name",
            "КатегорииНоменклатуры",
            "--root",
            str(tmp_path),
            "--apply",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        rename.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "коллиз" in captured.err.lower() or "существует" in captured.err.lower()
    assert {
        path: path.read_bytes()
        for path in (target, target_module, destination_collision, consumer)
    } == before


def test_report_query_and_explicit_forms_are_exact_companions(rename, tmp_path: Path) -> None:
    project_dir, subsystem_dir = create_project_structure(tmp_path)
    report = subsystem_dir / "АнализПродаж.yaml"
    write_file(
        report,
        "Имя: АнализПродаж\n"
        "ВидЭлемента: Отчет\n"
        "Интерфейс:\n"
        "    Форма: АнализПродажФормаОтчета\n",
    )
    write_file(
        subsystem_dir / "АнализПродаж.xbql",
        "ВЫБРАТЬ Ссылка\nИЗ АнализПродаж\n",
    )
    write_file(
        subsystem_dir / "АнализПродажФормаОтчета.yaml",
        "Имя: АнализПродажФормаОтчета\nТип: ФормаОтчета<АнализПродаж.Данные>\n",
    )
    write_file(
        subsystem_dir / "АнализПродажФормаОтчета.xbsl",
        "пер Данные: АнализПродаж.Данные\n",
    )
    unrelated = subsystem_dir / "АнализПродажПоГодам.xbql"
    write_file(unrelated, "ВЫБРАТЬ АнализПродажПоГодам.Ссылка\n")
    unrelated_before = unrelated.read_bytes()

    project_files = rename.collect_project_files(str(project_dir))
    text_changes, renames = rename.build_plan(
        project_files,
        "АнализПродаж",
        "Продажи",
        object_file=str(report),
    )

    assert unrelated not in {Path(path) for path, _old, _new in text_changes}
    assert set(renames) == {
        (str(report), str(subsystem_dir / "Продажи.yaml")),
        (str(subsystem_dir / "АнализПродаж.xbql"), str(subsystem_dir / "Продажи.xbql")),
        (
            str(subsystem_dir / "АнализПродажФормаОтчета.yaml"),
            str(subsystem_dir / "ПродажиФормаОтчета.yaml"),
        ),
        (
            str(subsystem_dir / "АнализПродажФормаОтчета.xbsl"),
            str(subsystem_dir / "ПродажиФормаОтчета.xbsl"),
        ),
    }

    rename.apply_plan(text_changes, renames)

    assert (subsystem_dir / "Продажи.xbql").read_text(encoding="utf-8") == (
        "ВЫБРАТЬ Ссылка\nИЗ Продажи\n"
    )
    assert (subsystem_dir / "ПродажиФормаОтчета.yaml").is_file()
    assert (subsystem_dir / "ПродажиФормаОтчета.xbsl").is_file()
    assert unrelated.read_bytes() == unrelated_before


def test_object_file_scopes_changes_to_its_owning_project(
    rename, tmp_path: Path, monkeypatch, capsys
) -> None:
    _, first_subsystem = create_project_structure(tmp_path, project_dir_name="first")
    _, second_subsystem = create_project_structure(tmp_path, project_dir_name="second")
    first_object = first_subsystem / "Категории.yaml"
    second_object = second_subsystem / "Категории.yaml"
    write_file(first_object, "Имя: Категории\nВидЭлемента: Справочник\n")
    write_file(second_object, "Имя: Категории\nВидЭлемента: Справочник\n")
    second_consumer = second_subsystem / "Потребитель.xbsl"
    write_file(second_consumer, "пер Значение: Категории.Ссылка?\n")
    untouched = {
        second_object: second_object.read_bytes(),
        second_consumer: second_consumer.read_bytes(),
    }
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rename.py",
            "--old-name",
            "Категории",
            "--new-name",
            "КатегорииНоменклатуры",
            "--root",
            str(tmp_path),
            "--object-file",
            str(first_object),
            "--apply",
        ],
    )

    rename.main()
    capsys.readouterr()

    assert (first_subsystem / "КатегорииНоменклатуры.yaml").is_file()
    assert {path: path.read_bytes() for path in untouched} == untouched


def test_import_blocks_with_quoted_key_and_indentationless_sequence_stay_unchanged(rename) -> None:
    content = (
        '"Импорт":\n'
        "- Категории\n"
        "Тип: Категории.Ссылка? # Категории.Ссылка? stays in comment\n"
    )

    assert rename.apply_substitutions(
        content,
        "Категории",
        "КатегорииНоменклатуры",
        rename_imports=False,
        file_extension=".yaml",
    ) == (
        '"Импорт":\n'
        "- Категории\n"
        "Тип: КатегорииНоменклатуры.Ссылка? # Категории.Ссылка? stays in comment\n"
    )

    xbsl = (
        "импорт Основное::Категории\n"
        "пер Значение: Категории.Ссылка?\n"
        "// Категории.Ссылка? stays in comment\n"
    )
    assert rename.apply_substitutions(
        xbsl,
        "Категории",
        "КатегорииНоменклатуры",
        rename_imports=False,
        file_extension=".xbsl",
    ) == (
        "импорт Основное::Категории\n"
        "пер Значение: КатегорииНоменклатуры.Ссылка?\n"
        "// Категории.Ссылка? stays in comment\n"
    )


def test_selected_owner_family_does_not_rename_same_basename_in_other_subsystem(
    rename, tmp_path: Path, monkeypatch, capsys
) -> None:
    project_dir, first_subsystem = create_project_structure(tmp_path, subsystem_name="A")
    second_subsystem = project_dir / "B"
    write_file(second_subsystem / "Подсистема.yaml", "")
    target = first_subsystem / "Категории.yaml"
    target_form = first_subsystem / "КатегорииФормаОбъекта.yaml"
    independent_companion = second_subsystem / "КатегорииФормаОбъекта.xbsl"
    write_file(
        target,
        "Имя: Категории\nВидЭлемента: Справочник\nФорма: КатегорииФормаОбъекта\n",
    )
    write_file(
        target_form,
        "Имя: КатегорииФормаОбъекта\nТип: ФормаОбъекта<Категории.Объект>\n",
    )
    write_file(independent_companion, "пер Данные: ДругойОбъект.Данные\n")
    project_files = rename.collect_project_files(str(project_dir))

    _changes, renames = rename.build_plan(
        project_files,
        "Категории",
        "КатегорииНоменклатуры",
        object_file=str(target),
    )

    assert all(Path(old).parent == first_subsystem for old, _new in renames)
    before = independent_companion.read_bytes()

    def unexpected_write(*_args, **_kwargs):
        pytest.fail("ambiguous companion must block before write_text/os.rename")

    monkeypatch.setattr(rename, "write_text", unexpected_write)
    monkeypatch.setattr(rename.os, "rename", unexpected_write)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rename.py",
            "--old-name",
            "Категории",
            "--new-name",
            "КатегорииНоменклатуры",
            "--root",
            str(project_dir),
            "--object-file",
            str(target),
            "--apply",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        rename.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "неоднознач" in captured.err.lower()
    assert independent_companion.read_bytes() == before


def test_register_rename_changes_query_sources_but_not_enum_aliases_or_strings(
    rename, tmp_path: Path
) -> None:
    project_dir, subsystem_dir = create_project_structure(tmp_path)
    register = subsystem_dir / "Остатки.yaml"
    write_file(
        register,
        "ВидЭлемента: РегистрНакопления\n"
        "Имя: Остатки\n"
        "ВидРегистра: Остатки\n",
    )
    query = subsystem_dir / "ОстаткиОтчет.xbql"
    write_file(
        query,
        "ВЫБРАТЬ\n"
        "    Остатки.Номенклатура\n"
        "ИЗ\n"
        "    Остатки.Остатки(&Период) КАК Остатки\n"
        "ГДЕ Остатки.КоличествоОстаток > 0\n",
    )
    module = subsystem_dir / "Проверка.xbsl"
    write_file(
        module,
        'пер Статус = "Остатки, цены, брак"\n'
        "пер Набор = новый Остатки.НаборЗаписей()\n"
        "пер Запрос = Запрос{\n"
        "    ВЫБРАТЬ Остатки.Номенклатура\n"
        "    ИЗ Остатки.Остатки КАК Остатки\n"
        "    ГДЕ Остатки.КоличествоОстаток > 0\n"
        "}\n",
    )
    localization = subsystem_dir / "ЛокализованныеСтроки.yaml"
    write_file(localization, "Строки:\n    Остатки: Остатки товаров\n")
    navigation = subsystem_dir / "Навигация.yaml"
    write_file(
        navigation,
        "Имя: Навигация\n"
        "Представление: $ЛокализованныеСтроки.Остатки\n",
    )

    project_files = rename.collect_project_files(str(project_dir))
    text_changes, renames = rename.build_plan(
        project_files,
        "Остатки",
        "СкладскиеОстатки",
        object_file=str(register),
    )
    modified = {Path(path): text for path, _original, text in text_changes}

    assert renames == [(str(register), str(subsystem_dir / "СкладскиеОстатки.yaml"))]
    assert "ВидРегистра: Остатки" in modified[register]
    assert (
        "СкладскиеОстатки.Остатки(&Период) КАК Остатки" in modified[query]
    )
    assert "Остатки.Номенклатура" in modified[query]
    assert "ГДЕ Остатки.КоличествоОстаток" in modified[query]
    assert '"Остатки, цены, брак"' in modified[module]
    assert "новый СкладскиеОстатки.НаборЗаписей()" in modified[module]
    assert "ИЗ СкладскиеОстатки.Остатки КАК Остатки" in modified[module]
    assert localization not in modified
    assert navigation not in modified


def test_arbitrary_linked_form_keeps_identity_path_and_labels(rename, tmp_path: Path) -> None:
    project_dir, subsystem_dir = create_project_structure(tmp_path)
    target = subsystem_dir / "Категории.yaml"
    arbitrary_form = subsystem_dir / "КарточкаКатегории.yaml"
    write_file(
        target,
        "Имя: Категории\nВидЭлемента: Справочник\nФорма: КарточкаКатегории\n",
    )
    write_file(
        arbitrary_form,
        "Имя: КарточкаКатегории\n"
        "Заголовок: Категория\n"
        "Тип: ФормаОбъекта<Категории.Объект>\n",
    )

    text_changes, renames = rename.build_plan(
        rename.collect_project_files(str(project_dir)),
        "Категории",
        "КатегорииНоменклатуры",
        new_presentation="Категория номенклатуры",
        old_presentation="Категория",
        object_file=str(target),
    )
    modified = {Path(path): text for path, _old, text in text_changes}

    assert all(Path(old) != arbitrary_form for old, _new in renames)
    assert "Имя: КарточкаКатегории" in modified[arbitrary_form]
    assert "Заголовок: Категория" in modified[arbitrary_form]
    assert "Тип: ФормаОбъекта<КатегорииНоменклатуры.Объект>" in modified[arbitrary_form]


def test_non_report_does_not_claim_same_named_xbql(rename, tmp_path: Path) -> None:
    project_dir, subsystem_dir = create_project_structure(tmp_path)
    target = subsystem_dir / "Категории.yaml"
    independent_query = subsystem_dir / "Категории.xbql"
    write_file(target, "Имя: Категории\nВидЭлемента: Справочник\n")
    write_file(independent_query, "ВЫБРАТЬ 1\n")

    _changes, renames = rename.build_plan(
        rename.collect_project_files(str(project_dir)),
        "Категории",
        "КатегорииНоменклатуры",
        object_file=str(target),
    )

    assert all(Path(old) != independent_query for old, _new in renames)


def test_invalid_identifier_is_rejected_before_project_changes(
    rename, tmp_path: Path, monkeypatch, capsys
) -> None:
    create_catalog_fixture(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rename.py",
            "--old-name",
            "Номенклатура",
            "--new-name",
            "../ВнеПроекта",
            "--root",
            str(tmp_path),
            "--apply",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        rename.main()

    assert exc_info.value.code == 1
    assert "идентификатор" in capsys.readouterr().err.lower()


@pytest.mark.parametrize(
    "reserved_name",
    ["если", "IF", "метод", "return", "Истина", "false", "Неопределено"],
)
def test_reserved_keyword_is_rejected_before_project_changes(
    rename, tmp_path: Path, monkeypatch, capsys, reserved_name: str
) -> None:
    create_catalog_fixture(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rename.py",
            "--old-name",
            "Номенклатура",
            "--new-name",
            reserved_name,
            "--root",
            str(tmp_path),
            "--apply",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        rename.main()

    assert exc_info.value.code == 1
    assert "ключевыми словами" in capsys.readouterr().err


def test_indented_method_and_lambda_shadowing_ends_at_matching_indent(rename) -> None:
    content = (
        "исключение Контейнер\n"
        "    метод Первый(Клиенты: Массив<Клиенты.Ссылка>)\n"
        "        возврат Клиенты.Первый()\n"
        "    ;\n"
        "    метод Второй(): Клиенты.Ссылка?\n"
        "        возврат Клиенты.Найти(Неопределено)\n"
        "    ;\n"
        ";\n"
        "метод Внешний()\n"
        "    знч Делегат = метод(Клиенты: Массив<Клиенты.Ссылка>) ->\n"
        "        возврат Клиенты.Первый()\n"
        "    ;\n"
        "    возврат Клиенты.Найти(Неопределено)\n"
        ";\n"
    )

    modified = rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    )

    assert modified.count("возврат Клиенты.Первый()") == 2
    assert modified.count("возврат Покупатели.Найти(Неопределено)") == 2
    assert modified.count("Массив<Покупатели.Ссылка>") == 2
    assert "метод Второй(): Покупатели.Ссылка?" in modified


def test_no_space_comparison_is_not_treated_as_generic_type(rename) -> None:
    content = (
        "метод Проверить(Клиенты: Массив<Клиенты.Ссылка>)\n"
        "    если А<Клиенты.Количество()>1\n"
        "        возврат Клиенты.Первый()\n"
        "    ;\n"
        ";\n"
    )

    modified = rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    )

    assert "А<Клиенты.Количество()>1" in modified
    assert "Массив<Покупатели.Ссылка>" in modified


def test_shadowing_uses_current_block_and_supported_bindings(rename) -> None:
    content = (
        "метод Проверить()\n"
        "    если Истина\n"
        "        конст Клиенты = Получить()\n"
        "        Клиенты.Первый()\n"
        "    ;\n"
        "    возврат Клиенты.Найти(Неопределено)\n"
        ";\n"
        "метод Цикл()\n"
        "    для Клиенты = 0 по 1\n"
        "        Клиенты.Представление()\n"
        "    ;\n"
        "    попытка\n"
        "        Выполнить()\n"
        "    поймать Клиенты: Исключение\n"
        "        Клиенты.Представление()\n"
        "    ;\n"
        "    возврат Клиенты.Найти(Неопределено)\n"
        ";\n"
    )

    modified = rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    )

    assert "конст Клиенты" in modified
    assert modified.count("Клиенты.Представление()") == 2
    assert modified.count("возврат Покупатели.Найти(Неопределено)") == 2


def test_multiline_and_parenthesized_lambda_parameters_shadow_receivers(rename) -> None:
    content = (
        "метод Проверить()\n"
        "    знч Один = Данные.Преобразовать(Клиенты ->\n"
        "        {\"Имя\": Клиенты.Имя}\n"
        "    )\n"
        "    знч Два = новый Команда((Клиенты, Уведомление) -> Клиенты.Открыть(\n"
        "        Уведомление.Данные))\n"
        "    возврат Клиенты.Найти(Неопределено)\n"
        ";\n"
    )

    modified = rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    )

    assert '{"Имя": Клиенты.Имя}' in modified
    assert "(Клиенты, Уведомление) -> Клиенты.Открыть(" in modified
    assert "возврат Покупатели.Найти(Неопределено)" in modified


def test_namespace_qualified_bare_type_is_renamed(rename) -> None:
    content = "знч ТипОбъекта = Тип<ПланОбмена::Данные::Номенклатура>\n"

    assert rename.apply_substitutions(
        content,
        "Номенклатура",
        "Товары",
        file_extension=".xbsl",
    ) == "знч ТипОбъекта = Тип<ПланОбмена::Данные::Товары>\n"


def test_query_without_explicit_alias_updates_implicit_qualifier(rename) -> None:
    query = (
        "ВЫБРАТЬ Категории.Имя\n"
        "ИЗ Категории\n"
        "ГДЕ Категории.ПометкаУдаления == Ложь\n"
    )

    assert rename.apply_substitutions(
        query,
        "Категории",
        "КатегорииНоменклатуры",
        file_extension=".xbql",
    ) == (
        "ВЫБРАТЬ КатегорииНоменклатуры.Имя\n"
        "ИЗ КатегорииНоменклатуры\n"
        "ГДЕ КатегорииНоменклатуры.ПометкаУдаления == Ложь\n"
    )


def test_path_collision_checks_casefolded_existing_siblings(rename, tmp_path: Path, monkeypatch) -> None:
    old_path = tmp_path / "Категории.xbsl"
    new_path = tmp_path / "НовыеКатегории.xbsl"
    write_file(old_path, "// source\n")

    class FakeEntry:
        path = str(tmp_path / "новыекатегории.xbsl")

    class FakeScandir:
        def __enter__(self):
            return iter([FakeEntry()])

        def __exit__(self, _type, _value, _traceback):
            return None

    monkeypatch.setattr(rename.os, "scandir", lambda _path: FakeScandir())
    monkeypatch.setattr(rename.os.path, "lexists", lambda _path: False)

    with pytest.raises(rename.RenameCollisionError, match="регистром/Unicode"):
        rename.validate_path_collisions([(str(old_path), str(new_path))])


def test_yaml_reference_slots_and_comments_are_context_aware(rename) -> None:
    content = (
        "СозданиеНаОсновании:\n"
        "    - Сделки.Ссылка # Сделки.Ссылка stays in comment\n"
        "    # Сделки.Ссылка comment only\n"
        "Видимость: =Сделки.Доступны() # Сделки.Доступны stays in comment\n"
        "Ключ: Сделки.Ссылка\n"
        "Выражение: Сделки.Ссылка\n"
    )

    assert rename.apply_substitutions(
        content,
        "Сделки",
        "Продажи",
        file_extension=".yaml",
    ) == (
        "СозданиеНаОсновании:\n"
        "    - Продажи.Ссылка # Сделки.Ссылка stays in comment\n"
        "    # Сделки.Ссылка comment only\n"
        "Видимость: =Продажи.Доступны() # Сделки.Доступны stays in comment\n"
        "Ключ: Продажи.Ссылка\n"
        "Выражение: Продажи.Ссылка\n"
    )


def test_yaml_expression_masks_literal_text_but_updates_interpolation(rename) -> None:
    content = (
        'Подсказка: ="текст Клиенты.Найти ${Клиенты.Найти()}" '
        "# Клиенты.Найти comment\n"
        'Команды:\n    - ="текст Клиенты.Найти ${Клиенты.Найти()}" '
        "# Клиенты.Найти comment\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".yaml",
    ) == (
        'Подсказка: ="текст Клиенты.Найти ${Покупатели.Найти()}" '
        "# Клиенты.Найти comment\n"
        'Команды:\n    - ="текст Клиенты.Найти ${Покупатели.Найти()}" '
        "# Клиенты.Найти comment\n"
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('Представление: "Клиент"\n', 'Представление: "Покупатель"\n'),
        ("Представление: Клиент # UI\n", "Представление: Покупатель # UI\n"),
        ("Заголовок: 'Клиент' # UI\r\n", "Заголовок: 'Покупатель' # UI\r\n"),
    ],
)
def test_label_replacement_preserves_quotes_comments_and_newlines(
    rename, source: str, expected: str
) -> None:
    assert rename.apply_substitutions(
        source,
        "Клиенты",
        "Покупатели",
        new_presentation="Покупатель",
        old_presentation="Клиент",
        replace_labels=True,
        file_extension=".yaml",
    ) == expected

def test_quoted_form_link_is_owned_companion(rename, tmp_path: Path) -> None:
    project_dir, subsystem_dir = create_project_structure(tmp_path)
    owner = subsystem_dir / "Категории.yaml"
    form = subsystem_dir / "КатегорииФормаОбъекта.yaml"
    write_file(
        owner,
        "Имя: Категории\nВидЭлемента: Справочник\n\"Форма\": 'КатегорииФормаОбъекта'\n",
    )
    write_file(
        form,
        "Имя: КатегорииФормаОбъекта\nВидЭлемента: КомпонентИнтерфейса\n"
        "Тип: ФормаОбъекта<Категории.Объект>\n",
    )

    changes, renames = rename.build_plan(
        rename.collect_project_files(str(project_dir)),
        "Категории",
        "КатегорииНоменклатуры",
        object_file=str(owner),
    )
    modified = {Path(path): text for path, _old, text in changes}

    assert (str(form), str(subsystem_dir / "КатегорииНоменклатурыФормаОбъекта.yaml")) in renames
    assert "'КатегорииНоменклатурыФормаОбъекта'" in modified[owner]


def test_direct_form_rename_updates_owner_form_reference(rename, tmp_path: Path) -> None:
    project_dir, subsystem_dir = create_project_structure(tmp_path)
    owner = subsystem_dir / "Категории.yaml"
    form = subsystem_dir / "КатегорииФормаОбъекта.yaml"
    module = subsystem_dir / "КатегорииФормаОбъекта.xbsl"
    write_file(owner, "Имя: Категории\nФорма: КатегорииФормаОбъекта\n")
    write_file(form, "Имя: КатегорииФормаОбъекта\nВидЭлемента: КомпонентИнтерфейса\n")
    write_file(module, "// form module\n")

    changes, renames = rename.build_plan(
        rename.collect_project_files(str(project_dir)),
        "КатегорииФормаОбъекта",
        "КатегорииКарточка",
        object_file=str(form),
    )
    modified = {Path(path): text for path, _old, text in changes}

    assert "Форма: КатегорииКарточка" in modified[owner]
    assert set(renames) == {
        (str(form), str(subsystem_dir / "КатегорииКарточка.yaml")),
        (str(module), str(subsystem_dir / "КатегорииКарточка.xbsl")),
    }


def test_xbsl_local_binding_shadows_metadata_receiver(rename) -> None:
    content = (
        "метод СоздатьКлиентов(): ЧитаемыйМассив<Клиенты.Ссылка>\n"
        "    знч Клиенты = <Клиенты.Ссылка>[]\n"
        "    Клиенты.Добавить(новый Клиенты.Объект())\n"
        "    возврат Клиенты\n"
        ";\n"
        "метод Найти(): Клиенты.Ссылка?\n"
        "    возврат Клиенты.Найти(Неопределено)\n"
        ";\n"
        "метод Явно(): Клиенты.Ссылка?\n"
        "    знч Клиенты = <Клиенты.Ссылка>[]\n"
        "    возврат Пресейл::Клиенты.Найти(Неопределено)\n"
        ";\n"
    )

    modified = rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    )

    assert "ЧитаемыйМассив<Покупатели.Ссылка>" in modified
    assert "знч Клиенты = <Покупатели.Ссылка>[]" in modified
    assert "Клиенты.Добавить(новый Покупатели.Объект())" in modified
    assert "возврат Покупатели.Найти" in modified
    assert "Пресейл::Покупатели.Найти" in modified


def test_xbsl_multiline_parameter_shadows_only_body_receiver(rename) -> None:
    content = (
        "метод Добавить(\n"
        "    Клиенты: ЧитаемыйМассив<Клиенты.Ссылка>\n"
        ")\n"
        "    Клиенты.Добавить(Неопределено)\n"
        ";\n"
    )

    modified = rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    )

    assert "Клиенты: ЧитаемыйМассив<Покупатели.Ссылка>" in modified
    assert "Клиенты.Добавить(Неопределено)" in modified


def test_xbsl_shadowing_does_not_rewrite_maps_ternary_or_comparisons(rename) -> None:
    content = (
        "метод Проверить()\n"
        "    знч Клиенты = ПолучитьКлиентов()\n"
        "    знч Карта = {\"Ключ\": Клиенты.Первый()}\n"
        "    знч Выбор = Истина ? Неопределено : Клиенты\n"
        "    если 0 < Клиенты.Количество() > 1\n"
        "        возврат Клиенты.Первый()\n"
        "    ;\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == content


def test_xbsl_braced_interpolation_updates_code_but_not_escaped_or_local_names(rename) -> None:
    content = (
        "метод Глобальная()\n"
        "    возврат \"${Клиенты.Найти(Неопределено)} / %{Клиенты.Получить()} / "
        "\\${Клиенты.НеКод()} / $Клиенты\"\n"
        ";\n"
        "метод Локальная(Клиенты: Массив<Клиенты.Ссылка>)\n"
        "    возврат \"${Клиенты.Первый()}\"\n"
        ";\n"
    )

    modified = rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    )

    assert "${Покупатели.Найти(Неопределено)}" in modified
    assert "%{Покупатели.Получить()}" in modified
    assert r"\${Клиенты.НеКод()}" in modified
    assert "$Клиенты" in modified
    assert "${Клиенты.Первый()}" in modified
    assert "Массив<Покупатели.Ссылка>" in modified


def test_query_multiline_alias_and_union_branches_are_independent(rename) -> None:
    query = (
        "ВЫБРАТЬ Категории.Имя\n"
        "ИЗ Категории\n"
        "ОБЪЕДИНИТЬ ВСЕ\n"
        "ВЫБРАТЬ Категории.Имя\n"
        "ИЗ Категории\n"
        "КАК Категории\n"
    )

    assert rename.apply_substitutions(
        query,
        "Категории",
        "НовыеКатегории",
        file_extension=".xbql",
    ) == (
        "ВЫБРАТЬ НовыеКатегории.Имя\n"
        "ИЗ НовыеКатегории\n"
        "ОБЪЕДИНИТЬ ВСЕ\n"
        "ВЫБРАТЬ Категории.Имя\n"
        "ИЗ НовыеКатегории\n"
        "КАК Категории\n"
    )


def test_query_nested_alias_scopes_and_comma_sources_are_independent(rename) -> None:
    query = (
        "ВЫБРАТЬ Категории.Имя\n"
        "ИЗ Другие КАК Д, Категории\n"
        "ГДЕ Категории.Ид В (\n"
        "    ВЫБРАТЬ Категории.Ид\n"
        "    ИЗ Категории КАК Категории\n"
        ")\n"
    )

    assert rename.apply_substitutions(
        query,
        "Категории",
        "НовыеКатегории",
        file_extension=".xbql",
    ) == (
        "ВЫБРАТЬ НовыеКатегории.Имя\n"
        "ИЗ Другие КАК Д, НовыеКатегории\n"
        "ГДЕ НовыеКатегории.Ид В (\n"
        "    ВЫБРАТЬ Категории.Ид\n"
        "    ИЗ НовыеКатегории КАК Категории\n"
        ")\n"
    )


def test_query_parenthesized_qualifiers_follow_implicit_source(rename) -> None:
    query = (
        'ВЫБРАТЬ ЕСТЬNULL(Клиенты.Имя, "")\n'
        "ИЗ Клиенты\n"
        "ГДЕ (Клиенты.Ид == 1)\n"
    )

    assert rename.apply_substitutions(
        query,
        "Клиенты",
        "Покупатели",
        file_extension=".xbql",
    ) == (
        'ВЫБРАТЬ ЕСТЬNULL(Покупатели.Имя, "")\n'
        "ИЗ Покупатели\n"
        "ГДЕ (Покупатели.Ид == 1)\n"
    )


def test_query_implicit_explicit_alias_is_preserved(rename) -> None:
    query = "ВЫБРАТЬ Клиенты.Имя\nИЗ Клиенты Клиенты\n"

    assert rename.apply_substitutions(
        query,
        "Клиенты",
        "Покупатели",
        file_extension=".xbql",
    ) == "ВЫБРАТЬ Клиенты.Имя\nИЗ Покупатели Клиенты\n"


def test_query_index_by_is_not_mistaken_for_alias(rename) -> None:
    query = (
        "ВЫБРАТЬ Клиенты.Имя\n"
        "ПОМЕСТИТЬ ВТ\n"
        "ИЗ Клиенты\n"
        "ИНДЕКСИРОВАТЬ ПО Имя\n"
    )

    assert rename.apply_substitutions(
        query,
        "Клиенты",
        "Покупатели",
        file_extension=".xbql",
    ) == (
        "ВЫБРАТЬ Покупатели.Имя\n"
        "ПОМЕСТИТЬ ВТ\n"
        "ИЗ Покупатели\n"
        "ИНДЕКСИРОВАТЬ ПО Имя\n"
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('"Представление": "Клиент"\n', '"Представление": "Покупатель"\n'),
        ("'Заголовок': 'Клиент' # UI\r\n", "'Заголовок': 'Покупатель' # UI\r\n"),
    ],
)
def test_quoted_label_keys_are_replaced_without_losing_style(
    rename, source: str, expected: str
) -> None:
    assert rename.apply_substitutions(
        source,
        "Клиенты",
        "Покупатели",
        new_presentation="Покупатель",
        old_presentation="Клиент",
        replace_labels=True,
        file_extension=".yaml",
    ) == expected


def test_namespace_prefix_segment_is_not_treated_as_owned_object(rename) -> None:
    content = "знч ТипОбъекта = Тип<Клиенты::Данные::Ссылка>\n"

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == content


def test_default_parameter_shadows_receiver_only_in_method_body(rename) -> None:
    content = (
        "метод Добавить(Клиенты: Массив<Клиенты.Ссылка> = Неопределено)\n"
        "    Клиенты.Добавить(Неопределено)\n"
        ";\n"
        "метод Найти()\n"
        "    возврат Клиенты.Найти(Неопределено)\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == (
        "метод Добавить(Клиенты: Массив<Покупатели.Ссылка> = Неопределено)\n"
        "    Клиенты.Добавить(Неопределено)\n"
        ";\n"
        "метод Найти()\n"
        "    возврат Покупатели.Найти(Неопределено)\n"
        ";\n"
    )


def test_multiline_method_return_type_is_signature_not_shadowed_body(rename) -> None:
    content = (
        "метод Получить(\n"
        "    Клиенты: Массив<Клиенты.Ссылка>\n"
        "):\n"
        "    Клиенты.Ссылка?\n"
        "    возврат Клиенты.Первый()\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == (
        "метод Получить(\n"
        "    Клиенты: Массив<Покупатели.Ссылка>\n"
        "):\n"
        "    Покупатели.Ссылка?\n"
        "    возврат Клиенты.Первый()\n"
        ";\n"
    )


def test_multiline_typed_lambda_parameters_shadow_only_lambda_body(rename) -> None:
    content = (
        "метод Проверить()\n"
        "    знч Функция = (\n"
        "        Клиенты: Массив<Клиенты.Ссылка>,\n"
        "        Уведомление: Объект\n"
        "    ) -> Клиенты.Открыть(Уведомление)\n"
        "    возврат Клиенты.Найти(Неопределено)\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == (
        "метод Проверить()\n"
        "    знч Функция = (\n"
        "        Клиенты: Массив<Покупатели.Ссылка>,\n"
        "        Уведомление: Объект\n"
        "    ) -> Клиенты.Открыть(Уведомление)\n"
        "    возврат Покупатели.Найти(Неопределено)\n"
        ";\n"
    )


def test_short_lambda_continuation_stays_in_lambda_scope(rename) -> None:
    content = (
        "метод Проверить()\n"
        "    знч Функция = Клиенты -> Клиенты.Первый()\n"
        "        ?? Клиенты.Последний()\n"
        "    возврат Клиенты.Найти(Неопределено)\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == (
        "метод Проверить()\n"
        "    знч Функция = Клиенты -> Клиенты.Первый()\n"
        "        ?? Клиенты.Последний()\n"
        "    возврат Покупатели.Найти(Неопределено)\n"
        ";\n"
    )


def test_lambda_generic_comma_does_not_create_phantom_parameter(rename) -> None:
    content = (
        "метод Проверить()\n"
        "    знч Функция = (Значение: Соответствие<Строка, Клиенты.Ссылка>, "
        "Флаг: Булево) -> Клиенты.Найти(Неопределено)\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == (
        "метод Проверить()\n"
        "    знч Функция = (Значение: Соответствие<Строка, Покупатели.Ссылка>, "
        "Флаг: Булево) -> Покупатели.Найти(Неопределено)\n"
        ";\n"
    )


def test_correlated_query_uses_outer_implicit_alias_and_preserves_field_chain(rename) -> None:
    query = (
        "ВЫБРАТЬ Категории.Имя, Данные.Категории.Имя\n"
        "ИЗ Категории\n"
        "ГДЕ Категории.Ид В (\n"
        "    ВЫБРАТЬ Другие.Ид\n"
        "    ИЗ Другие КАК Другие\n"
        "    ГДЕ Другие.Владелец == Категории.Ид\n"
        ")\n"
    )

    assert rename.apply_substitutions(
        query,
        "Категории",
        "НовыеКатегории",
        file_extension=".xbql",
    ) == (
        "ВЫБРАТЬ НовыеКатегории.Имя, Данные.Категории.Имя\n"
        "ИЗ НовыеКатегории\n"
        "ГДЕ НовыеКатегории.Ид В (\n"
        "    ВЫБРАТЬ Другие.Ид\n"
        "    ИЗ Другие КАК Другие\n"
        "    ГДЕ Другие.Владелец == НовыеКатегории.Ид\n"
        ")\n"
    )


def test_query_parameter_expression_respects_outer_local_shadow(rename) -> None:
    content = (
        "метод Локальный(Клиенты: Массив<Клиенты.Ссылка>)\n"
        "    знч Запрос = Запрос{ВЫБРАТЬ Сотрудники.Ссылка ИЗ Сотрудники "
        "ГДЕ Сотрудники.Владелец == %{Клиенты.Первый()}}\n"
        "    возврат Запрос.Выполнить()\n"
        ";\n"
        "метод Глобальный()\n"
        "    возврат Запрос{ВЫБРАТЬ Сотрудники.Ссылка ИЗ Сотрудники "
        "ГДЕ Сотрудники.Владелец == %{Клиенты.Найти(Неопределено)}}\n"
        ";\n"
    )

    modified = rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    )

    assert "Массив<Покупатели.Ссылка>" in modified
    assert "%{Клиенты.Первый()}" in modified
    assert "%{Покупатели.Найти(Неопределено)}" in modified


def test_missing_old_companion_collision_blocks_before_any_write(
    rename, tmp_path: Path, monkeypatch, capsys
) -> None:
    _, subsystem_dir = create_project_structure(tmp_path)
    target = subsystem_dir / "Категории.yaml"
    destination_collision = subsystem_dir / "КатегорииНоменклатуры.xbsl"
    write_file(target, "Имя: Категории\nВидЭлемента: Справочник\n")
    write_file(destination_collision, "// independent destination\n")
    before = {path: path.read_bytes() for path in (target, destination_collision)}

    def unexpected_write(*_args, **_kwargs):
        pytest.fail("collision preflight must run before write_text/os.rename")

    monkeypatch.setattr(rename, "write_text", unexpected_write)
    monkeypatch.setattr(rename.os, "rename", unexpected_write)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rename.py",
            "--old-name",
            "Категории",
            "--new-name",
            "КатегорииНоменклатуры",
            "--root",
            str(tmp_path),
            "--apply",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        rename.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "коллиз" in captured.err.lower()
    assert {path: path.read_bytes() for path in (target, destination_collision)} == before


def test_local_shadow_does_not_leak_into_sibling_branch(rename) -> None:
    content = (
        "метод Проверить()\n"
        "    если Истина\n"
        "        знч Клиенты = ПолучитьКлиентов()\n"
        "        Клиенты.Первый()\n"
        "    иначе\n"
        "        Клиенты.Найти(Неопределено)\n"
        "    ;\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == (
        "метод Проверить()\n"
        "    если Истина\n"
        "        знч Клиенты = ПолучитьКлиентов()\n"
        "        Клиенты.Первый()\n"
        "    иначе\n"
        "        Покупатели.Найти(Неопределено)\n"
        "    ;\n"
        ";\n"
    )


def test_multiline_declaration_union_type_is_forced_type_context(rename) -> None:
    content = (
        "метод Проверить()\n"
        "    знч Клиенты = ПолучитьКлиентов()\n"
        "    пер Значение: Строка |\n"
        "        Клиенты.Ссылка\n"
        "    возврат Клиенты.Первый()\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == (
        "метод Проверить()\n"
        "    знч Клиенты = ПолучитьКлиентов()\n"
        "    пер Значение: Строка |\n"
        "        Покупатели.Ссылка\n"
        "    возврат Клиенты.Первый()\n"
        ";\n"
    )


def test_multiline_method_union_return_type_is_forced_type_context(rename) -> None:
    content = (
        "метод Получить(Клиенты: Массив<Клиенты.Ссылка>): Строка |\n"
        "    Клиенты.Ссылка\n"
        "    возврат Клиенты.Первый()\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == (
        "метод Получить(Клиенты: Массив<Покупатели.Ссылка>): Строка |\n"
        "    Покупатели.Ссылка\n"
        "    возврат Клиенты.Первый()\n"
        ";\n"
    )


def test_functional_type_arrow_is_not_mistaken_for_lambda_parameter(rename) -> None:
    content = (
        "метод Проверить()\n"
        "    знч Функция: (Клиенты.Ссылка)->Булево = "
        "Значение -> Клиенты.Найти(Значение)\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == (
        "метод Проверить()\n"
        "    знч Функция: (Покупатели.Ссылка)->Булево = "
        "Значение -> Покупатели.Найти(Значение)\n"
        ";\n"
    )


def test_inline_full_lambda_scope_ends_at_its_terminator(rename) -> None:
    content = (
        "метод Проверить()\n"
        "    знч Функция = метод(Клиенты: Клиенты.Ссылка) -> "
        "возврат Клиенты.Первый();\n"
        "    возврат Клиенты.Найти(Неопределено)\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == (
        "метод Проверить()\n"
        "    знч Функция = метод(Клиенты: Покупатели.Ссылка) -> "
        "возврат Клиенты.Первый();\n"
        "    возврат Покупатели.Найти(Неопределено)\n"
        ";\n"
    )


def test_derived_table_alias_shadows_outer_query_alias(rename) -> None:
    query = (
        "ВЫБРАТЬ Клиенты.Имя\n"
        "ИЗ Клиенты\n"
        "ГДЕ СУЩЕСТВУЕТ (\n"
        "    ВЫБРАТЬ Клиенты.Имя\n"
        "    ИЗ (\n"
        "        ВЫБРАТЬ Другие.Имя\n"
        "        ИЗ Другие КАК Другие\n"
        "    ) КАК Клиенты\n"
        ")\n"
    )

    assert rename.apply_substitutions(
        query,
        "Клиенты",
        "Покупатели",
        file_extension=".xbql",
    ) == (
        "ВЫБРАТЬ Покупатели.Имя\n"
        "ИЗ Покупатели\n"
        "ГДЕ СУЩЕСТВУЕТ (\n"
        "    ВЫБРАТЬ Клиенты.Имя\n"
        "    ИЗ (\n"
        "        ВЫБРАТЬ Другие.Имя\n"
        "        ИЗ Другие КАК Другие\n"
        "    ) КАК Клиенты\n"
        ")\n"
    )


@pytest.mark.parametrize(
    "tail",
    ["ПОЛУЧИТЬ 10\n", "FETCH 10\n", "СО СМЕЩЕНИЕМ 5\n", "OFFSET 5\n"],
)
def test_query_fetch_and_offset_clauses_are_not_aliases(rename, tail: str) -> None:
    query = "ВЫБРАТЬ Клиенты.Имя\nИЗ Клиенты\n" + tail

    assert rename.apply_substitutions(
        query,
        "Клиенты",
        "Покупатели",
        file_extension=".xbql",
    ) == "ВЫБРАТЬ Покупатели.Имя\nИЗ Покупатели\n" + tail


def test_casefolded_destination_companion_blocks_before_write(
    rename, tmp_path: Path, monkeypatch, capsys
) -> None:
    project_dir, first_subsystem = create_project_structure(tmp_path, subsystem_name="A")
    second_subsystem = project_dir / "B"
    write_file(second_subsystem / "Подсистема.yaml", "")
    target = first_subsystem / "Клиенты.yaml"
    collision = second_subsystem / "покупатели.xbsl"
    write_file(target, "Имя: Клиенты\nВидЭлемента: Справочник\n")
    write_file(collision, "// independent destination\n")
    before = {path: path.read_bytes() for path in (target, collision)}

    def unexpected_write(*_args, **_kwargs):
        pytest.fail("collision preflight must run before write_text/os.rename")

    monkeypatch.setattr(rename, "write_text", unexpected_write)
    monkeypatch.setattr(rename.os, "rename", unexpected_write)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rename.py",
            "--old-name",
            "Клиенты",
            "--new-name",
            "Покупатели",
            "--root",
            str(project_dir),
            "--object-file",
            str(target),
            "--apply",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        rename.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "коллиз" in captured.err.lower()
    assert {path: path.read_bytes() for path in (target, collision)} == before


def test_resource_use_expression_does_not_create_local_shadow(rename) -> None:
    content = (
        "метод Проверить()\n"
        "    исп Клиенты.Открыть()\n"
        "    возврат Клиенты.Найти(Неопределено)\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == (
        "метод Проверить()\n"
        "    исп Покупатели.Открыть()\n"
        "    возврат Покупатели.Найти(Неопределено)\n"
        ";\n"
    )


def test_resource_use_binding_shadows_receiver_after_assignment(rename) -> None:
    content = (
        "метод Проверить()\n"
        "    исп Клиенты = Фабрика.Открыть()\n"
        "    Клиенты.Закрыть()\n"
        ";\n"
        "метод Найти()\n"
        "    возврат Клиенты.Найти(Неопределено)\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == (
        "метод Проверить()\n"
        "    исп Клиенты = Фабрика.Открыть()\n"
        "    Клиенты.Закрыть()\n"
        ";\n"
        "метод Найти()\n"
        "    возврат Покупатели.Найти(Неопределено)\n"
        ";\n"
    )

def test_catch_binding_does_not_leak_into_finally_branch(rename) -> None:
    content = (
        "метод Проверить()\n"
        "    попытка\n"
        "        Выполнить()\n"
        "    поймать Клиенты: Исключение\n"
        "        Клиенты.Локальный()\n"
        "    вконце\n"
        "        Клиенты.Найти(Неопределено)\n"
        "    ;\n"
        ";\n"
    )

    assert rename.apply_substitutions(
        content,
        "Клиенты",
        "Покупатели",
        file_extension=".xbsl",
    ) == (
        "метод Проверить()\n"
        "    попытка\n"
        "        Выполнить()\n"
        "    поймать Клиенты: Исключение\n"
        "        Клиенты.Локальный()\n"
        "    вконце\n"
        "        Покупатели.Найти(Неопределено)\n"
        "    ;\n"
        ";\n"
    )


def test_unreadable_project_file_blocks_apply_before_any_write(
    rename, tmp_path: Path, monkeypatch, capsys
) -> None:
    project_dir, subsystem_dir = create_project_structure(tmp_path)
    target = subsystem_dir / "Клиенты.yaml"
    hidden = subsystem_dir / "СкрытаяКоллизия.yaml"
    consumer = subsystem_dir / "Потребитель.xbsl"
    write_file(target, "Имя: Клиенты\nВидЭлемента: Справочник\n")
    write_file(hidden, "Имя: Покупатели\nВидЭлемента: Справочник\n")
    write_file(consumer, "пер Значение: Клиенты.Ссылка?\n")
    before = {path: path.read_bytes() for path in (target, hidden, consumer)}
    original_read_text = rename.read_text

    def unreadable(path: str):
        if Path(path) == hidden:
            return None
        return original_read_text(path)

    def unexpected_write(*_args, **_kwargs):
        pytest.fail("readability preflight must run before write_text/os.rename")

    monkeypatch.setattr(rename, "read_text", unreadable)
    monkeypatch.setattr(rename, "write_text", unexpected_write)
    monkeypatch.setattr(rename.os, "rename", unexpected_write)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rename.py",
            "--old-name",
            "Клиенты",
            "--new-name",
            "Покупатели",
            "--root",
            str(project_dir),
            "--object-file",
            str(target),
            "--apply",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        rename.main()

    captured = capsys.readouterr()
    assert exc_info.value.code == 1
    assert "прочитать" in captured.err.lower()
    assert {path: path.read_bytes() for path in (target, hidden, consumer)} == before
