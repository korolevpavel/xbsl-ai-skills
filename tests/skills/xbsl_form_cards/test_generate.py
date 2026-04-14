from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT_DIR / ".claude/skills/xbsl-form-cards/scripts/generate.py"


def load_generate_module():
    spec = importlib.util.spec_from_file_location("form_cards_generate_under_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Unable to load module spec for {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_form_info(
    object_name: str,
    object_path: Path,
    fields: list[dict],
    *,
    object_type: str = "Справочник",
    object_file: str | None = None,
    namespace: str = "Acme::CRM::Основное",
    existing_forms: dict | None = None,
) -> dict:
    return {
        "object_path": str(object_path),
        "object_file": object_file or f"{object_name}.yaml",
        "object_type": object_type,
        "namespace": namespace,
        "fields": fields,
        "existing_forms": existing_forms or {},
    }


@pytest.fixture
def generate():
    return load_generate_module()


def test_detect_roles_prefers_named_title_photo_and_collects_content(generate) -> None:
    fields = [
        {"name": "Код", "type": "Строка"},
        {"name": "Название", "type": "Строка"},
        {"name": "Фото", "type": "ДвоичныйОбъект.Ссылка?"},
        {"name": "Автор", "type": "Пользователи.Ссылка?"},
        {"name": "ДатаСоздания", "type": "Дата"},
        {"name": "Описание", "type": "Строка"},
    ]

    title, photo, content = generate.detect_roles(fields)

    assert title == "Название"
    assert photo == "Фото"
    assert content == [
        {"name": "Код", "type": "Строка"},
        {"name": "Автор", "type": "Пользователи.Ссылка?"},
        {"name": "ДатаСоздания", "type": "Дата"},
        {"name": "Описание", "type": "Строка"},
    ]


def test_detect_roles_falls_back_to_first_string_field(generate) -> None:
    fields = [
        {"name": "Код", "type": "Строка"},
        {"name": "Количество", "type": "Число"},
    ]

    title, photo, content = generate.detect_roles(fields)

    assert title == "Код"
    assert photo is None
    assert content == [{"name": "Количество", "type": "Число"}]


def test_build_card_content_yaml_handles_empty_single_and_multiple_fields(generate) -> None:
    assert generate.build_card_content_yaml([], indent=8) == ""

    assert generate.build_card_content_yaml(
        [{"name": "Дата", "type": "Дата"}],
        indent=8,
    ) == '        Содержимое: =ДанныеСтроки.Данные.Дата.Представление("дд ММММ гггг ЧЧ:мм")\n'

    assert generate.build_card_content_yaml(
        [{"name": "Автор", "type": "Пользователи.Ссылка?"}],
        indent=8,
    ) == (
        "        Содержимое:\n"
        "            Тип: Надпись\n"
        "            Значение: =ДанныеСтроки.Данные.Автор\n"
    )

    assert generate.build_card_content_yaml(
        [
            {"name": "Статус", "type": "Строка"},
            {"name": "Исполнитель", "type": "Пользователи.Ссылка?"},
        ],
        indent=8,
    ) == (
        "        Содержимое:\n"
        "            Тип: Группа\n"
        "            Содержимое:\n"
        "                -\n"
        "                    Тип: Надпись\n"
        "                    Значение: =ДанныеСтроки.Данные.Статус\n"
        "                -\n"
        "                    Тип: Надпись\n"
        "                    Значение: =ДанныеСтроки.Данные.Исполнитель\n"
    )


def test_build_source_fields_yaml_preserves_expected_field_order(generate) -> None:
    source_fields = generate.build_source_fields_yaml(
        "Название",
        "Фото",
        [
            {"name": "Статус", "type": "Строка"},
            {"name": "Исполнитель", "type": "Пользователи.Ссылка?"},
        ],
    )

    assert source_fields == (
        "                            -\n"
        "                                Тип: ПолеДинамическогоСписка\n"
        "                                Выражение: Ссылка\n"
        "                            -\n"
        "                                Тип: ПолеДинамическогоСписка\n"
        "                                Выражение: Название\n"
        "                            -\n"
        "                                Тип: ПолеДинамическогоСписка\n"
        "                                Выражение: Фото\n"
        "                            -\n"
        "                                Тип: ПолеДинамическогоСписка\n"
        "                                Выражение: Статус\n"
        "                            -\n"
        "                                Тип: ПолеДинамическогоСписка\n"
        "                                Выражение: Исполнитель\n"
    )


def test_build_form_yaml_contains_matrix_layout_and_min_width(generate) -> None:
    yaml_text = generate.build_form_yaml(
        "uid-form",
        "Задачи",
        "Acme::CRM::Основное",
        "Название",
        "Фото",
        [{"name": "Статус", "type": "Строка"}],
        250,
    )

    assert "Имя: ЗадачиФормаСписка" in yaml_text
    assert "ТипКомпонентаСтроки: СтрокаСпискаЗадачи" in yaml_text
    assert "ПроизвольныйСписок<ДинамическийСписок<Acme::CRM::Основное::ЗадачиФормаСписка.ДанныеСтрокиСписка>>" in yaml_text
    assert "Выражение: Ссылка" in yaml_text
    assert "Выражение: Название" in yaml_text
    assert "Выражение: Фото" in yaml_text
    assert "МинимальнаяШирина: 250" in yaml_text


def test_build_row_yaml_switches_between_photo_and_standard_cards(generate) -> None:
    with_photo = generate.build_row_yaml(
        "uid-row",
        "Задачи",
        "Acme::CRM::Основное",
        "Название",
        "Фото",
        [{"name": "Статус", "type": "Строка"}],
    )
    without_photo = generate.build_row_yaml(
        "uid-row",
        "Задачи",
        "Acme::CRM::Основное",
        "Название",
        None,
        [{"name": "Статус", "type": "Строка"}],
    )
    with_photo_document = generate.build_row_yaml(
        "uid-row",
        "Задачи",
        "Acme::CRM::Основное",
        "Название",
        "Фото",
        [
            {"name": "Статус", "type": "Строка"},
            {"name": "Дата", "type": "Дата"},
        ],
        "Документ",
    )

    assert "Тип: ПроизвольнаяКарточка" in with_photo
    assert "Изображение: =ДанныеСтроки.Данные.Фото ?? Ресурс{Аккаунт.svg}.Ссылка" in with_photo
    assert "Значение: =ДанныеСтроки.Данные.Название" in with_photo
    assert "Значение: =ДанныеСтроки.Данные.Статус" not in with_photo
    assert "Изображение: =ДанныеСтроки.Данные.Фото ?? Ресурс{Файл.svg}.Ссылка" in with_photo_document
    assert "Значение: =ДанныеСтроки.Данные.Статус" in with_photo_document
    assert 'Значение: =ДанныеСтроки.Данные.Дата.Представление("дд ММММ гггг ЧЧ:мм")' in with_photo_document
    assert "Тип: СтандартнаяКарточка" in without_photo
    assert "Заголовок: =ДанныеСтроки.Данные.Название" in without_photo
    assert "Содержимое: =ДанныеСтроки.Данные.Статус" in without_photo


def test_update_interface_replaces_existing_form(generate) -> None:
    original = (
        "Имя: Задачи\n"
        "ОбластьВидимости: ВПодсистеме\n"
        "Интерфейс:\n"
        "    Список:\n"
        "        Форма: СтараяФорма\n"
    )

    updated = generate.update_interface(original, "Задачи", "Справочник")

    assert "        Форма: ЗадачиФормаСписка\n" in updated
    assert "СтараяФорма" not in updated


def test_update_interface_adds_form_when_list_exists_without_form(generate) -> None:
    original = (
        "Имя: Задачи\n"
        "ОбластьВидимости: ВПодсистеме\n"
        "Интерфейс:\n"
        "    Список:\n"
        "    Команды:\n"
        "        Тип: ФрагментКомандногоИнтерфейса\n"
    )

    updated = generate.update_interface(original, "Задачи", "Справочник")

    assert "    Список:\n        Форма: ЗадачиФормаСписка\n    Команды:\n" in updated


def test_update_interface_adds_list_inside_existing_interface(generate) -> None:
    original = (
        "Имя: Задачи\n"
        "ОбластьВидимости: ВПодсистеме\n"
        "Интерфейс:\n"
        "    ВключатьВАвтоИнтерфейс: Истина\n"
        "Команды:\n"
        "    - =Обновить\n"
    )

    updated = generate.update_interface(original, "Задачи", "Справочник")

    assert (
        "Интерфейс:\n"
        "    ВключатьВАвтоИнтерфейс: Истина\n"
        "    Список:\n"
        "        Форма: ЗадачиФормаСписка\n"
        "Команды:\n"
    ) in updated


def test_update_interface_appends_list_when_interface_reaches_end_of_file(generate) -> None:
    original = (
        "Имя: Задачи\n"
        "ОбластьВидимости: ВПодсистеме\n"
        "Интерфейс:\n"
        "    ВключатьВАвтоИнтерфейс: Истина\n"
    )

    updated = generate.update_interface(original, "Задачи", "Справочник")

    assert updated.endswith("    ВключатьВАвтоИнтерфейс: Истина\n    Список:\n        Форма: ЗадачиФормаСписка\n")


@pytest.mark.parametrize(
    ("object_type", "expected_create_flag"),
    [
        ("Справочник", True),
        ("Документ", False),
    ],
)
def test_update_interface_inserts_new_block_after_visibility(generate, object_type: str, expected_create_flag: bool) -> None:
    original = (
        "Имя: Задачи\n"
        f"ВидЭлемента: {object_type}\n"
        "ОбластьВидимости: ВПодсистеме\n"
        "Реквизиты:\n"
        "    - Имя: Название\n"
    )

    updated = generate.update_interface(original, "Задачи", object_type)

    assert (
        "ОбластьВидимости: ВПодсистеме\n"
        "Интерфейс:\n"
        "    ВключатьВАвтоИнтерфейс: Истина\n"
    ) in updated
    assert "    Список:\n        Форма: ЗадачиФормаСписка\n" in updated
    assert ("ИспользоватьСозданиеПриВводе: Истина" in updated) is expected_create_flag


def test_get_form_info_exits_on_invalid_json(generate, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        generate.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="not-json", stderr="", returncode=0),
    )

    with pytest.raises(SystemExit) as exc_info:
        generate.get_form_info("Задачи", "/tmp/project")

    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert "Ошибка: form_info вернул неожиданный вывод:" in captured.err
    assert "not-json" in captured.err


def test_get_form_info_exits_on_error_payload_and_prints_matches(generate, monkeypatch, capsys) -> None:
    stdout = json.dumps(
        {
            "error": "найдено несколько объектов",
            "matches": [
                {"object_path": "/tmp/p1/Основное", "object_file": "Задачи.yaml"},
                {"object_path": "/tmp/p2/Продажи", "object_file": "Задачи.yaml"},
            ],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        generate.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=stdout, stderr="", returncode=0),
    )

    with pytest.raises(SystemExit) as exc_info:
        generate.get_form_info("Задачи", "/tmp/project")

    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert "Ошибка: найдено несколько объектов" in captured.err
    assert "Найдено несколько объектов:" in captured.err
    assert "/tmp/p1/Основное/Задачи.yaml" in captured.err
    assert "/tmp/p2/Продажи/Задачи.yaml" in captured.err


def test_main_dry_run_prints_summary_and_does_not_write_files(generate, tmp_path: Path, monkeypatch, capsys) -> None:
    object_path = tmp_path / "Demo" / "TestApp" / "Основное"
    object_path.mkdir(parents=True)
    object_yaml = object_path / "Задачи.yaml"
    original_text = "Имя: Задачи\nОбластьВидимости: ВПодсистеме\n"
    write_file(object_yaml, original_text)

    monkeypatch.setattr(
        generate,
        "get_form_info",
        lambda _object_name, _root: make_form_info(
            "Задачи",
            object_path,
            [
                {"name": "Название", "type": "Строка"},
                {"name": "Фото", "type": "ДвоичныйОбъект.Ссылка?"},
                {"name": "Автор", "type": "Пользователи.Ссылка?"},
                {"name": "ДатаПубликации", "type": "Дата"},
            ],
            existing_forms={"ФормаСписка": "СтараяФормаСписка"},
        ),
    )

    generate.main(["--object", "Задачи", "--root", str(tmp_path)])

    captured = capsys.readouterr()

    assert "[DRY-RUN] xbsl-form-cards для Задачи" in captured.out
    assert "Заголовок: Название" in captured.out
    assert "Фото: Фото  → ПроизвольнаяКарточка, МинимальнаяШирина: 250" in captured.out
    assert "Содержимое:" not in captured.out
    assert "Под фото:" not in captured.out
    assert "⚠️  Форма списка уже существует: СтараяФормаСписка — будет перезаписана" in captured.out
    assert str(object_path / "ЗадачиФормаСписка.yaml") in captured.out
    assert str(object_path / "СтрокаСпискаЗадачи.yaml") in captured.out
    assert "Чтобы применить: добавьте --apply" in captured.out
    assert object_yaml.read_text(encoding="utf-8") == original_text
    assert not (object_path / "ЗадачиФормаСписка.yaml").exists()
    assert not (object_path / "СтрокаСпискаЗадачи.yaml").exists()


def test_main_dry_run_prints_photo_extra_for_non_catalog_object(generate, tmp_path: Path, monkeypatch, capsys) -> None:
    object_path = tmp_path / "Demo" / "TestApp" / "Продажи"
    object_path.mkdir(parents=True)
    write_file(object_path / "Задачи.yaml", "Имя: Задачи\nОбластьВидимости: ВПодсистеме\n")

    monkeypatch.setattr(
        generate,
        "get_form_info",
        lambda _object_name, _root: make_form_info(
            "Задачи",
            object_path,
            [
                {"name": "Название", "type": "Строка"},
                {"name": "Фото", "type": "ДвоичныйОбъект.Ссылка?"},
                {"name": "Автор", "type": "Пользователи.Ссылка?"},
                {"name": "ДатаПубликации", "type": "Дата"},
            ],
            object_type="Документ",
        ),
    )

    generate.main(["--object", "Задачи", "--root", str(tmp_path)])

    captured = capsys.readouterr()

    assert "Фото: Фото  → ПроизвольнаяКарточка, МинимальнаяШирина: 250" in captured.out
    assert "Под фото: Автор, ДатаПубликации" in captured.out


def test_main_apply_writes_files_and_updates_object_yaml(generate, tmp_path: Path, monkeypatch, capsys) -> None:
    object_path = tmp_path / "Demo" / "TestApp" / "Закупки"
    object_path.mkdir(parents=True)
    object_yaml = object_path / "Задачи.yaml"
    write_file(
        object_yaml,
        "Имя: Задачи\nВидЭлемента: Справочник\nОбластьВидимости: ВПодсистеме\nРеквизиты:\n    - Имя: Название\n",
    )

    monkeypatch.setattr(
        generate,
        "get_form_info",
        lambda _object_name, _root: make_form_info(
            "Задачи",
            object_path,
            [
                {"name": "Название", "type": "Строка"},
                {"name": "Статус", "type": "Строка"},
                {"name": "Исполнитель", "type": "Пользователи.Ссылка?"},
            ],
        ),
    )
    uuids = iter(["form-uuid", "row-uuid"])
    monkeypatch.setattr(generate.uuid, "uuid4", lambda: next(uuids))

    generate.main(["--object", "Задачи", "--root", str(tmp_path), "--min-width", "320", "--apply"])

    captured = capsys.readouterr()
    form_yaml = object_path / "ЗадачиФормаСписка.yaml"
    row_yaml = object_path / "СтрокаСпискаЗадачи.yaml"

    assert "[ПРИМЕНЯЮ] xbsl-form-cards для Задачи" in captured.out
    assert "Готово." in captured.out
    assert form_yaml.exists()
    assert row_yaml.exists()
    assert "Ид: form-uuid" in form_yaml.read_text(encoding="utf-8")
    assert "МинимальнаяШирина: 320" in form_yaml.read_text(encoding="utf-8")
    assert "ТипКомпонентаСтроки: СтрокаСпискаЗадачи" in form_yaml.read_text(encoding="utf-8")
    assert "Ид: row-uuid" in row_yaml.read_text(encoding="utf-8")
    assert "Тип: СтандартнаяКарточка" in row_yaml.read_text(encoding="utf-8")
    assert "Значение: =ДанныеСтроки.Данные.Исполнитель" in row_yaml.read_text(encoding="utf-8")
    updated_object_yaml = object_yaml.read_text(encoding="utf-8")
    assert "Интерфейс:" in updated_object_yaml
    assert "ИспользоватьСозданиеПриВводе: Истина" in updated_object_yaml
    assert "Форма: ЗадачиФормаСписка" in updated_object_yaml


def test_main_exits_when_string_title_field_is_missing(generate, tmp_path: Path, monkeypatch, capsys) -> None:
    object_path = tmp_path / "Demo" / "TestApp" / "Закупки"
    object_path.mkdir(parents=True)

    monkeypatch.setattr(
        generate,
        "get_form_info",
        lambda _object_name, _root: make_form_info(
            "Задачи",
            object_path,
            [
                {"name": "Фото", "type": "ДвоичныйОбъект.Ссылка?"},
                {"name": "ДатаСоздания", "type": "Дата"},
            ],
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        generate.main(["--object", "Задачи", "--root", str(tmp_path)])

    captured = capsys.readouterr()

    assert exc_info.value.code == 1
    assert "Ошибка: не найдено строковое поле для заголовка карточки в объекте Задачи." in captured.err
