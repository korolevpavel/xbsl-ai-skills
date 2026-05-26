from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT_DIR / ".claude/skills/xbsl-access-set/scripts/access_state.py"


def load_access_state_module():
    spec = importlib.util.spec_from_file_location("access_state_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load module spec for {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def create_project_structure(base_dir: Path, project_name: str = "prj") -> tuple[Path, Path]:
    project_dir = base_dir / project_name
    subsystem_dir = project_dir / "Основное"
    write_file(project_dir / "Проект.yaml", "Имя: Проект\n")
    write_file(subsystem_dir / "Подсистема.yaml", "Имя: Основное\n")
    return project_dir, subsystem_dir


@pytest.fixture
def access_state():
    return load_access_state_module()


# ---------------------------------------------------------------------------
# parse_control_access
# ---------------------------------------------------------------------------

def test_parse_missing_section(access_state) -> None:
    text = "ВидЭлемента: Справочник\nИмя: Склады\nОбластьВидимости: ВПодсистеме\nРеквизиты:\n    - Имя: Код\n"
    result = access_state.parse_control_access(text)
    assert result["exists"] is False
    assert result["по_умолчанию"] is None
    assert result["операции"] == {}
    assert result["расчет_разрешений_по"] == []
    assert result["обработчик"] is None


def test_parse_po_umolchaniyu(access_state) -> None:
    text = (
        "ВидЭлемента: Справочник\nИмя: Склады\n"
        "КонтрольДоступа:\n"
        "    Разрешения:\n"
        "        ПоУмолчанию: РазрешеноАутентифицированным\n"
        "Реквизиты:\n"
    )
    result = access_state.parse_control_access(text)
    assert result["exists"] is True
    assert result["по_умолчанию"] == "РазрешеноАутентифицированным"
    assert result["операции"] == {}


def test_parse_separate_operations(access_state) -> None:
    text = (
        "КонтрольДоступа:\n"
        "    Разрешения:\n"
        "        Чтение: РазрешеноАутентифицированным\n"
        "        Изменение: РазрешеноАдминистраторам\n"
    )
    result = access_state.parse_control_access(text)
    assert result["exists"] is True
    assert result["по_умолчанию"] is None
    assert result["операции"]["Чтение"] == "РазрешеноАутентифицированным"
    assert result["операции"]["Изменение"] == "РазрешеноАдминистраторам"


def test_parse_raschet_razresheniy_po(access_state) -> None:
    text = (
        "КонтрольДоступа:\n"
        "    РасчетРазрешенийПо:\n"
        "        - Клиент\n"
        "        - Регион\n"
        "    Разрешения:\n"
        "        ПоУмолчанию: РазрешенияВычисляютсяДляКаждогоОбъекта\n"
    )
    result = access_state.parse_control_access(text)
    assert result["расчет_разрешений_по"] == ["Клиент", "Регион"]
    assert result["по_умолчанию"] == "РазрешенияВычисляютсяДляКаждогоОбъекта"


def test_parse_with_obrabotchik(access_state) -> None:
    text = (
        "КонтрольДоступа:\n"
        "    Обработчик: МойОбработчик\n"
        "    Разрешения:\n"
        "        Вызов: РазрешенияВычисляются\n"
    )
    result = access_state.parse_control_access(text)
    assert result["обработчик"] == "МойОбработчик"
    assert result["операции"]["Вызов"] == "РазрешенияВычисляются"


def test_parse_rls_computed(access_state) -> None:
    text = (
        "КонтрольДоступа:\n"
        "    Разрешения:\n"
        "        ПоУмолчанию: РазрешенияВычисляютсяДляКаждогоОбъекта\n"
    )
    result = access_state.parse_control_access(text)
    assert result["по_умолчанию"] == "РазрешенияВычисляютсяДляКаждогоОбъекта"


# ---------------------------------------------------------------------------
# scan_objects
# ---------------------------------------------------------------------------

def test_scan_returns_supported_types_only(access_state, tmp_path: Path) -> None:
    _, sub = create_project_structure(tmp_path)
    write_file(sub / "Склады.yaml", "ВидЭлемента: Справочник\nИмя: Склады\n")
    write_file(sub / "Статус.yaml", "ВидЭлемента: Перечисление\nИмя: Статус\n")
    write_file(sub / "Утилиты.yaml", "ВидЭлемента: ОбщийМодуль\nИмя: Утилиты\n")

    proj_dir = tmp_path / "prj"
    objects = access_state.scan_objects(str(proj_dir))
    names = [o["name"] for o in objects]
    assert "Склады" in names
    assert "Статус" not in names
    assert "Утилиты" not in names


def test_scan_all_supported_types(access_state, tmp_path: Path) -> None:
    _, sub = create_project_structure(tmp_path)
    write_file(sub / "Клиенты.yaml", "ВидЭлемента: Справочник\nИмя: Клиенты\n")
    write_file(sub / "Заказы.yaml", "ВидЭлемента: Документ\nИмя: Заказы\n")
    write_file(sub / "КурсыВалют.yaml", "ВидЭлемента: РегистрСведений\nИмя: КурсыВалют\n")
    write_file(sub / "Остатки.yaml", "ВидЭлемента: РегистрНакопления\nИмя: Остатки\n")
    write_file(sub / "АпиЗаказов.yaml", "ВидЭлемента: HttpСервис\nИмя: АпиЗаказов\n")

    proj_dir = tmp_path / "prj"
    objects = access_state.scan_objects(str(proj_dir))
    assert len(objects) == 5


def test_scan_filter_by_object_name(access_state, tmp_path: Path) -> None:
    _, sub = create_project_structure(tmp_path)
    write_file(sub / "Склады.yaml", "ВидЭлемента: Справочник\nИмя: Склады\n")
    write_file(sub / "Товары.yaml", "ВидЭлемента: Справочник\nИмя: Товары\n")

    proj_dir = tmp_path / "prj"
    objects = access_state.scan_objects(str(proj_dir), object_name="Склады")
    assert len(objects) == 1
    assert objects[0]["name"] == "Склады"


def test_scan_returns_access_info(access_state, tmp_path: Path) -> None:
    _, sub = create_project_structure(tmp_path)
    write_file(
        sub / "Склады.yaml",
        "ВидЭлемента: Справочник\nИмя: Склады\n"
        "КонтрольДоступа:\n    Разрешения:\n        ПоУмолчанию: РазрешеноВсем\n",
    )

    proj_dir = tmp_path / "prj"
    objects = access_state.scan_objects(str(proj_dir))
    assert objects[0]["access"]["exists"] is True
    assert objects[0]["access"]["по_умолчанию"] == "РазрешеноВсем"


def test_scan_access_missing(access_state, tmp_path: Path) -> None:
    _, sub = create_project_structure(tmp_path)
    write_file(sub / "Товары.yaml", "ВидЭлемента: Справочник\nИмя: Товары\nРеквизиты:\n")

    proj_dir = tmp_path / "prj"
    objects = access_state.scan_objects(str(proj_dir))
    assert objects[0]["access"]["exists"] is False


# ---------------------------------------------------------------------------
# set_control_access — обновление существующей секции
# ---------------------------------------------------------------------------

def test_update_already_set_returns_reason(access_state) -> None:
    text = (
        "ВидЭлемента: Справочник\nИмя: Склады\n"
        "КонтрольДоступа:\n    Разрешения:\n        ПоУмолчанию: РазрешеноВсем\n"
        "Реквизиты:\n"
    )
    reason, new_text = access_state.set_control_access(text, "Справочник", "РазрешеноВсем")
    assert reason == "already_set"
    assert new_text == text


def test_update_existing_po_umolchaniyu(access_state) -> None:
    text = (
        "ВидЭлемента: Справочник\nИмя: Склады\n"
        "КонтрольДоступа:\n    Разрешения:\n        ПоУмолчанию: РазрешеноАдминистраторам\n"
        "Реквизиты:\n"
    )
    reason, new_text = access_state.set_control_access(text, "Справочник", "РазрешеноВсем")
    assert reason is None
    assert "ПоУмолчанию: РазрешеноВсем" in new_text
    assert "ПоУмолчанию: РазрешеноАдминистраторам" not in new_text


def test_update_rls_computed_returns_reason(access_state) -> None:
    text = (
        "КонтрольДоступа:\n"
        "    Разрешения:\n"
        "        ПоУмолчанию: РазрешенияВычисляютсяДляКаждогоОбъекта\n"
    )
    reason, new_text = access_state.set_control_access(text, "Справочник", "РазрешеноВсем")
    assert reason == "rls_computed"
    assert new_text == text


def test_update_rls_to_rls_is_already_set(access_state) -> None:
    text = (
        "КонтрольДоступа:\n"
        "    Разрешения:\n"
        "        ПоУмолчанию: РазрешенияВычисляютсяДляКаждогоОбъекта\n"
    )
    reason, _ = access_state.set_control_access(
        text, "Справочник", "РазрешенияВычисляютсяДляКаждогоОбъекта"
    )
    assert reason == "already_set"


# ---------------------------------------------------------------------------
# insert_control_access — вставка новой секции
# ---------------------------------------------------------------------------

def test_insert_before_rekvizity_spravochnik(access_state) -> None:
    text = (
        "ВидЭлемента: Справочник\nИмя: Склады\nОбластьВидимости: ВПодсистеме\n"
        "Реквизиты:\n    - Имя: Код\n"
    )
    result = access_state.insert_control_access(text, "Справочник", "РазрешеноАутентифицированным")
    lines = result.splitlines()
    kad_idx = next(i for i, l in enumerate(lines) if l == "КонтрольДоступа:")
    rek_idx = next(i for i, l in enumerate(lines) if l == "Реквизиты:")
    assert kad_idx < rek_idx
    assert "ПоУмолчанию: РазрешеноАутентифицированным" in result


def test_insert_before_interfeys_spravochnik(access_state) -> None:
    text = (
        "ВидЭлемента: Справочник\nИмя: Склады\nОбластьВидимости: ВПодсистеме\n"
        "Интерфейс:\n    Список:\n        Представление: Склад\n"
        "Реквизиты:\n    - Имя: Код\n"
    )
    result = access_state.insert_control_access(text, "Справочник", "РазрешеноВсем")
    lines = result.splitlines()
    kad_idx = next(i for i, l in enumerate(lines) if l == "КонтрольДоступа:")
    inf_idx = next(i for i, l in enumerate(lines) if l == "Интерфейс:")
    assert kad_idx < inf_idx


def test_insert_before_izmereriya_rs(access_state) -> None:
    text = (
        "ВидЭлемента: РегистрСведений\nИмя: КурсыВалют\nОбластьВидимости: ВПодсистеме\n"
        "Измерения:\n    - Имя: Валюта\n"
    )
    result = access_state.insert_control_access(text, "РегистрСведений", "РазрешеноАутентифицированным")
    lines = result.splitlines()
    kad_idx = next(i for i, l in enumerate(lines) if l == "КонтрольДоступа:")
    izm_idx = next(i for i, l in enumerate(lines) if l == "Измерения:")
    assert kad_idx < izm_idx


def test_insert_before_shablony_http(access_state) -> None:
    text = (
        "ВидЭлемента: HttpСервис\nИмя: МойСервис\nОбластьВидимости: ВПодсистеме\n"
        "ШаблоныUrl:\n    - Имя: Метод1\n"
    )
    result = access_state.insert_control_access(text, "HttpСервис", "РазрешеноАутентифицированным")
    lines = result.splitlines()
    kad_idx = next(i for i, l in enumerate(lines) if l == "КонтрольДоступа:")
    sh_idx = next(i for i, l in enumerate(lines) if l == "ШаблоныUrl:")
    assert kad_idx < sh_idx


def test_insert_appended_if_no_anchor(access_state) -> None:
    text = "ВидЭлемента: Справочник\nИмя: Склады\nОбластьВидимости: ВПодсистеме\n"
    result = access_state.insert_control_access(text, "Справочник", "РазрешеноВсем")
    assert "КонтрольДоступа:" in result
    assert "ПоУмолчанию: РазрешеноВсем" in result


def test_insert_preserves_existing_content(access_state) -> None:
    text = (
        "ВидЭлемента: Справочник\nИмя: Склады\nОбластьВидимости: ВПодсистеме\n"
        "Реквизиты:\n    - Имя: Код\n    - Имя: Наименование\n"
    )
    result = access_state.insert_control_access(text, "Справочник", "РазрешеноАутентифицированным")
    assert "Имя: Склады" in result
    assert "Реквизиты:" in result
    assert "Наименование" in result


# ---------------------------------------------------------------------------
# update_default_permission — обновление внутри существующей секции
# ---------------------------------------------------------------------------

def test_update_replaces_po_umolchaniyu(access_state) -> None:
    text = (
        "КонтрольДоступа:\n"
        "    Разрешения:\n"
        "        ПоУмолчанию: РазрешеноАдминистраторам\n"
        "Реквизиты:\n"
    )
    result = access_state.update_default_permission(text, "РазрешеноВсем")
    assert "ПоУмолчанию: РазрешеноВсем" in result
    assert "РазрешеноАдминистраторам" not in result
    assert "Реквизиты:" in result


def test_update_inserts_po_umolchaniyu_when_absent(access_state) -> None:
    text = (
        "КонтрольДоступа:\n"
        "    Разрешения:\n"
        "        Чтение: РазрешеноАутентифицированным\n"
    )
    result = access_state.update_default_permission(text, "РазрешеноВсем")
    assert "ПоУмолчанию: РазрешеноВсем" in result
    assert "Чтение: РазрешеноАутентифицированным" in result


def test_update_inserts_razresheniya_when_absent(access_state) -> None:
    text = "КонтрольДоступа:\n    Обработчик: МойОбработчик\n"
    result = access_state.update_default_permission(text, "РазрешеноВсем")
    assert "Разрешения:" in result
    assert "ПоУмолчанию: РазрешеноВсем" in result


# ---------------------------------------------------------------------------
# main — dry-run и apply
# ---------------------------------------------------------------------------

def test_main_summary_no_set(access_state, tmp_path: Path, monkeypatch, capsys) -> None:
    _, sub = create_project_structure(tmp_path)
    write_file(sub / "Склады.yaml", "ВидЭлемента: Справочник\nИмя: Склады\n")
    monkeypatch.setattr(sys, "argv", ["access_state.py", "--root", str(tmp_path)])

    access_state.main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["total"] == 1
    assert data["objects"][0]["name"] == "Склады"


def test_main_summary_single_object(access_state, tmp_path: Path, monkeypatch, capsys) -> None:
    _, sub = create_project_structure(tmp_path)
    write_file(sub / "Склады.yaml", "ВидЭлемента: Справочник\nИмя: Склады\n")
    write_file(sub / "Товары.yaml", "ВидЭлемента: Справочник\nИмя: Товары\n")
    monkeypatch.setattr(
        sys, "argv", ["access_state.py", "--root", str(tmp_path), "--object", "Склады"]
    )

    access_state.main()

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["total"] == 1
    assert data["objects"][0]["name"] == "Склады"


def test_main_dry_run_shows_changes(access_state, tmp_path: Path, monkeypatch, capsys) -> None:
    _, sub = create_project_structure(tmp_path)
    write_file(sub / "Склады.yaml", "ВидЭлемента: Справочник\nИмя: Склады\nРеквизиты:\n")
    original = (sub / "Склады.yaml").read_text(encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv",
        ["access_state.py", "--root", str(tmp_path), "--set", "РазрешеноАутентифицированным"],
    )

    access_state.main()

    captured = capsys.readouterr()
    assert "Dry-run" in captured.out
    assert "РазрешеноАутентифицированным" in captured.out
    assert (sub / "Склады.yaml").read_text(encoding="utf-8") == original


def test_main_dry_run_skips_already_set(access_state, tmp_path: Path, monkeypatch, capsys) -> None:
    _, sub = create_project_structure(tmp_path)
    write_file(
        sub / "Склады.yaml",
        "ВидЭлемента: Справочник\nИмя: Склады\n"
        "КонтрольДоступа:\n    Разрешения:\n        ПоУмолчанию: РазрешеноАутентифицированным\n",
    )
    monkeypatch.setattr(
        sys, "argv",
        ["access_state.py", "--root", str(tmp_path), "--set", "РазрешеноАутентифицированным"],
    )

    access_state.main()

    captured = capsys.readouterr()
    assert "Пропущено (уже установлено)" in captured.out


def test_main_exit3_rls_computed(access_state, tmp_path: Path, monkeypatch, capsys) -> None:
    _, sub = create_project_structure(tmp_path)
    write_file(
        sub / "Задачи.yaml",
        "ВидЭлемента: Справочник\nИмя: Задачи\n"
        "КонтрольДоступа:\n    Разрешения:\n        ПоУмолчанию: РазрешенияВычисляютсяДляКаждогоОбъекта\n",
    )
    monkeypatch.setattr(
        sys, "argv",
        ["access_state.py", "--root", str(tmp_path), "--set", "РазрешеноВсем", "--object", "Задачи"],
    )

    with pytest.raises(SystemExit) as exc_info:
        access_state.main()

    assert exc_info.value.code == 3


def test_main_exit1_no_projects(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["access_state.py", "--root", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    assert exc_info.value.code == 1


def test_main_exit1_object_not_found(access_state, tmp_path: Path, monkeypatch, capsys) -> None:
    create_project_structure(tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        ["access_state.py", "--root", str(tmp_path), "--object", "НесуществующийОбъект"],
    )

    with pytest.raises(SystemExit) as exc_info:
        access_state.main()

    assert exc_info.value.code == 1
    assert "НесуществующийОбъект" in capsys.readouterr().err


def test_main_apply_updates_file(access_state, tmp_path: Path, monkeypatch, capsys) -> None:
    _, sub = create_project_structure(tmp_path)
    write_file(
        sub / "Склады.yaml",
        "ВидЭлемента: Справочник\nИмя: Склады\n"
        "КонтрольДоступа:\n    Разрешения:\n        ПоУмолчанию: РазрешеноАдминистраторам\n"
        "Реквизиты:\n",
    )
    monkeypatch.setattr(
        sys, "argv",
        [
            "access_state.py", "--root", str(tmp_path),
            "--set", "РазрешеноАутентифицированным", "--apply",
        ],
    )

    access_state.main()

    content = (sub / "Склады.yaml").read_text(encoding="utf-8")
    assert "ПоУмолчанию: РазрешеноАутентифицированным" in content
    assert "РазрешеноАдминистраторам" not in content


def test_main_apply_inserts_new_section(access_state, tmp_path: Path, monkeypatch, capsys) -> None:
    _, sub = create_project_structure(tmp_path)
    write_file(
        sub / "Товары.yaml",
        "ВидЭлемента: Справочник\nИмя: Товары\nОбластьВидимости: ВПодсистеме\nРеквизиты:\n    - Имя: Код\n",
    )
    monkeypatch.setattr(
        sys, "argv",
        [
            "access_state.py", "--root", str(tmp_path),
            "--set", "РазрешеноАутентифицированным", "--apply",
        ],
    )

    access_state.main()

    content = (sub / "Товары.yaml").read_text(encoding="utf-8")
    assert "КонтрольДоступа:" in content
    assert "ПоУмолчанию: РазрешеноАутентифицированным" in content


def test_main_apply_skips_already_set(access_state, tmp_path: Path, monkeypatch, capsys) -> None:
    _, sub = create_project_structure(tmp_path)
    original = (
        "ВидЭлемента: Справочник\nИмя: Товары\n"
        "КонтрольДоступа:\n    Разрешения:\n        ПоУмолчанию: РазрешеноВсем\n"
    )
    write_file(sub / "Товары.yaml", original)
    monkeypatch.setattr(
        sys, "argv",
        ["access_state.py", "--root", str(tmp_path), "--set", "РазрешеноВсем", "--apply"],
    )

    access_state.main()

    assert (sub / "Товары.yaml").read_text(encoding="utf-8") == original


def test_main_apply_reports_count(access_state, tmp_path: Path, monkeypatch, capsys) -> None:
    _, sub = create_project_structure(tmp_path)
    write_file(sub / "А.yaml", "ВидЭлемента: Справочник\nИмя: А\nРеквизиты:\n")
    write_file(sub / "Б.yaml", "ВидЭлемента: Справочник\nИмя: Б\nРеквизиты:\n")
    monkeypatch.setattr(
        sys, "argv",
        ["access_state.py", "--root", str(tmp_path), "--set", "РазрешеноВсем", "--apply"],
    )

    access_state.main()

    captured = capsys.readouterr()
    assert "✓ Применено: 2 файлов обновлено." in captured.out
