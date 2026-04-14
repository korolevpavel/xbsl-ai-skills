#!/usr/bin/env python3
"""
Генерирует форму карточек (ПроизвольныйСписок с матричной компоновкой) для объекта 1С:Элемент.
Создаёт два файла: <Объект>ФормаСписка.yaml и СтрокаСписка<Объект>.yaml.

Dry-run (только показывает что будет создано):
    python3 .claude/skills/xbsl-form-cards/scripts/generate.py --object Задачи [--root .]

Применить:
    python3 .claude/skills/xbsl-form-cards/scripts/generate.py --object Задачи [--root .] --apply
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FORM_INFO_SCRIPT = os.path.normpath(
    os.path.join(SCRIPT_DIR, "../../xbsl-form-info/scripts/form_info.py")
)

TITLE_NAMES = {"Наименование", "Заголовок", "Название"}
PHOTO_TYPE = "ДвоичныйОбъект.Ссылка?"
CONTENT_TYPES = {"ДатаВремя", "Дата", "Число", "Строка"}


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Данные из form_info
# ---------------------------------------------------------------------------

def get_form_info(object_name: str, root: str) -> dict:
    result = subprocess.run(
        [sys.executable, FORM_INFO_SCRIPT, "--name", object_name, "--root", root],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Ошибка: form_info вернул неожиданный вывод:\n{result.stdout}", file=sys.stderr)
        sys.exit(1)

    if "error" in data:
        print(f"Ошибка: {data['error']}", file=sys.stderr)
        if "matches" in data:
            print("Найдено несколько объектов:", file=sys.stderr)
            for m in data["matches"]:
                print(f"  {m['object_path']}/{m['object_file']}", file=sys.stderr)
        sys.exit(1)
    return data


# ---------------------------------------------------------------------------
# Определение ролей полей
# ---------------------------------------------------------------------------

def detect_roles(fields: list[dict]) -> tuple[str | None, str | None, list[dict]]:
    """
    Возвращает (title_field_name, photo_field_name, content_fields).
    title — первое поле с именем из TITLE_NAMES или первое Строка-поле.
    photo — первое поле типа ДвоичныйОбъект.Ссылка?
    content — остальные значимые поля (исключая title и photo).
    """
    title: str | None = None
    photo: str | None = None

    # Приоритетные имена заголовка
    for f in fields:
        if f["type"] == "Строка" and f["name"] in TITLE_NAMES:
            title = f["name"]
            break

    # Первое строковое поле как запасной вариант
    if title is None:
        for f in fields:
            if f["type"] == "Строка":
                title = f["name"]
                break

    # Фото
    for f in fields:
        if f["type"] == PHOTO_TYPE:
            photo = f["name"]
            break

    # Содержимое: поля значимых типов, кроме заголовка и фото
    content = [
        f for f in fields
        if f["name"] not in (title, photo)
        and (f["type"] in CONTENT_TYPES or f["type"].endswith(".Ссылка?"))
        and f["type"] != PHOTO_TYPE
    ]

    return title, photo, content


# ---------------------------------------------------------------------------
# Генерация YAML для блока Содержимое карточки (СтандартнаяКарточка)
# ---------------------------------------------------------------------------

def _field_expr(f: dict) -> str:
    """Выражение для одного поля в карточке."""
    expr = f"=ДанныеСтроки.Данные.{f['name']}"
    if f["type"] in ("ДатаВремя", "Дата"):
        expr += '.Представление("дд ММММ гггг ЧЧ:мм")'
    return expr


def _is_ref(f: dict) -> bool:
    return f["type"].endswith(".Ссылка?") and f["type"] != PHOTO_TYPE


def build_card_content_yaml(content_fields: list[dict], indent: int) -> str:
    """
    Строит YAML для секции Содержимое СтандартнаяКарточка.
    indent — количество пробелов для строки с ключом 'Содержимое:'.
    Возвращает пустую строку если полей нет.
    """
    if not content_fields:
        return ""

    pad = " " * indent
    pad2 = " " * (indent + 4)
    pad3 = " " * (indent + 8)
    pad4 = " " * (indent + 12)

    if len(content_fields) == 1:
        f = content_fields[0]
        if _is_ref(f):
            return (
                f"{pad}Содержимое:\n"
                f"{pad2}Тип: Надпись\n"
                f"{pad2}Значение: =ДанныеСтроки.Данные.{f['name']}\n"
            )
        return f"{pad}Содержимое: {_field_expr(f)}\n"

    # Несколько полей — через Группу с Надписями
    lines = [
        f"{pad}Содержимое:\n",
        f"{pad2}Тип: Группа\n",
        f"{pad2}Содержимое:\n",
    ]
    for f in content_fields:
        lines.append(f"{pad3}-\n")
        lines.append(f"{pad4}Тип: Надпись\n")
        lines.append(f"{pad4}Значение: =ДанныеСтроки.Данные.{f['name']}\n")
    return "".join(lines)


# ---------------------------------------------------------------------------
# Генерация полей Источника (список Поля в ФормаСписка)
# ---------------------------------------------------------------------------

def build_source_fields_yaml(title: str, photo: str | None, content_fields: list[dict]) -> str:
    """
    Строит блок Поля для секции Источник в ФормаСписка.
    Каждое поле: 28 пробелов '-', 32 пробела 'Тип:' и 'Выражение:'.
    """
    field_names = ["Ссылка", title]
    if photo:
        field_names.append(photo)
    for f in content_fields:
        field_names.append(f["name"])

    lines = []
    for name in field_names:
        lines.append(
            f"                            -\n"
            f"                                Тип: ПолеДинамическогоСписка\n"
            f"                                Выражение: {name}\n"
        )
    return "".join(lines)


# ---------------------------------------------------------------------------
# Генерация файла 1: <Объект>ФормаСписка.yaml
# ---------------------------------------------------------------------------

def build_form_yaml(
    uid: str,
    obj: str,
    namespace: str,
    title: str,
    photo: str | None,
    content_fields: list[dict],
    min_width: int,
) -> str:
    source_fields = build_source_fields_yaml(title, photo, content_fields)

    return (
        f"ВидЭлемента: КомпонентИнтерфейса\n"
        f"Ид: {uid}\n"
        f"Имя: {obj}ФормаСписка\n"
        f"ОбластьВидимости: ВПодсистеме\n"
        f"Наследует:\n"
        f"    Тип: ФормаСписка\n"
        f"    ВключатьВАвтоИнтерфейс: Ложь\n"
        f"    Заголовок: {obj}\n"
        f"    ДополнительныеКоманды:\n"
        f"        Тип: ФрагментКомандногоИнтерфейса\n"
        f"        Элементы:\n"
        f"            - =Обновить\n"
        f"    КомандыСоздания: =Компоненты.ОсновнаяТаблица.ДобавитьСтроку\n"
        f"    КомпонентТаблицы: =Компоненты.ОсновнаяТаблица\n"
        f"    Содержимое:\n"
        f"        Тип: ПроизвольныйШаблонФормы\n"
        f"        Содержимое:\n"
        f"            Тип: Группа\n"
        f"            Содержимое:\n"
        f"                -\n"
        f"                    Тип: ПроизвольныйСписок<ДинамическийСписок<{namespace}::{obj}ФормаСписка.ДанныеСтрокиСписка>>\n"
        f"                    Имя: ОсновнаяТаблица\n"
        f"                    ОбрабатыватьНажатие: Истина\n"
        f"                    ТипКомпонентаСтроки: СтрокаСписка{obj}\n"
        f"                    Источник:\n"
        f"                        ИмяТипаДанныхСтроки: ДанныеСтрокиСписка\n"
        f"                        ОсновнаяТаблица:\n"
        f"                            Таблица: {obj}\n"
        f"                        Поля:\n"
        f"{source_fields}"
        f"                    КонтейнерСтрок:\n"
        f"                        Тип: Группа\n"
        f"                        Имя: МатричнаяГруппа\n"
        f"                        Компоновка: Матричная\n"
        f"                        РастягиватьПоВертикали: Ложь\n"
        f"                        РастягиватьПоГоризонтали: Истина\n"
        f"                        НастройкиМатричнойКомпоновки:\n"
        f"                            АвтоЗаполнение: ДобавлятьКолонкиИСтроки\n"
        f"                            ОписаниеАвтоматическихКолонок:\n"
        f"                                МинимальнаяШирина: {min_width}\n"
        f"                                РастягиватьПоГоризонтали: Истина\n"
        f"                            ОписаниеАвтоматическихСтрок:\n"
        f"                                РастягиватьПоВертикали: Истина\n"
    )


# ---------------------------------------------------------------------------
# Генерация файла 2: СтрокаСписка<Объект>.yaml
# ---------------------------------------------------------------------------

def build_row_yaml(
    uid: str,
    obj: str,
    namespace: str,
    title: str,
    photo: str | None,
    content_fields: list[dict],
) -> str:
    row_type = f"ПроизвольнаяСтрокаСписка<СтрокаДинамическогоСписка<{namespace}::{obj}ФормаСписка.ДанныеСтрокиСписка>>"

    if photo:
        # ПроизвольнаяКарточка с фото + надписью под ним
        placeholder = "Ресурс{Аккаунт.svg}.Ссылка"
        return (
            f"ВидЭлемента: КомпонентИнтерфейса\n"
            f"Ид: {uid}\n"
            f"Имя: СтрокаСписка{obj}\n"
            f"ОбластьВидимости: ВПодсистеме\n"
            f"Наследует:\n"
            f"    Тип: {row_type}\n"
            f"    Содержимое:\n"
            f"        Тип: ПроизвольнаяКарточка\n"
            f"        РастягиватьПоВертикали: Истина\n"
            f"        РастягиватьПоГоризонтали: Истина\n"
            f"        Содержимое:\n"
            f"            Тип: Группа\n"
            f"            Компоновка: Вертикальная\n"
            f"            РастягиватьПоГоризонтали: Истина\n"
            f"            Содержимое:\n"
            f"                -\n"
            f"                    Тип: Картинка\n"
            f"                    Высота: 200\n"
            f"                    Масштабирование: Пропорционально\n"
            f"                    РастягиватьПоГоризонтали: Истина\n"
            f"                    Изображение: =ДанныеСтроки.Данные.{photo} ?? {placeholder}\n"
            f"                -\n"
            f"                    Тип: Надпись\n"
            f"                    РастягиватьПоГоризонтали: Истина\n"
            f"                    ВыравниваниеВГруппеПоГоризонтали: Центр\n"
            f"                    Значение: =ДанныеСтроки.Данные.{title}\n"
        )

    # СтандартнаяКарточка без фото
    content_yaml = build_card_content_yaml(content_fields, indent=8)
    return (
        f"ВидЭлемента: КомпонентИнтерфейса\n"
        f"Ид: {uid}\n"
        f"Имя: СтрокаСписка{obj}\n"
        f"ОбластьВидимости: ВПодсистеме\n"
        f"Наследует:\n"
        f"    Тип: {row_type}\n"
        f"    Содержимое:\n"
        f"        Тип: СтандартнаяКарточка\n"
        f"        Заголовок: =ДанныеСтроки.Данные.{title}\n"
        f"        РастягиватьПоВертикали: Истина\n"
        f"        РастягиватьПоГоризонтали: Истина\n"
        f"{content_yaml}"
    )


# ---------------------------------------------------------------------------
# Обновление секции Интерфейс в объектном YAML
# ---------------------------------------------------------------------------

def update_interface(text: str, obj: str, obj_type: str) -> str:
    """
    Добавляет или обновляет Список.Форма в секции Интерфейс объектного YAML.
    Если секции нет — вставляет весь блок после строки ОбластьВидимости:.
    """
    form_name = f"{obj}ФормаСписка"
    lines = text.splitlines(keepends=True)

    # --- Случай 1: строка "        Форма: <что-то>" уже есть под Список — заменить ---
    # Ищем паттерн: Интерфейс → Список → Форма
    in_interface = False
    in_список = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        if line.rstrip() == "Интерфейс:":
            in_interface = True
            in_список = False
            continue

        if in_interface:
            if indent == 0 and stripped:          # покинули Интерфейс
                in_interface = False
                in_список = False
                continue
            if indent == 4 and stripped == "Список:":
                in_список = True
                continue
            if in_список:
                if indent == 4 and stripped:       # покинули Список
                    in_список = False
                    continue
                if indent == 8 and stripped.startswith("Форма:"):
                    lines[i] = f"        Форма: {form_name}\n"
                    return "".join(lines)

    # --- Случай 2: Список: есть под Интерфейс, но без Форма — добавить Форма после Список ---
    in_interface = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        if line.rstrip() == "Интерфейс:":
            in_interface = True
            continue

        if in_interface:
            if indent == 0 and stripped:
                break
            if indent == 4 and stripped == "Список:":
                lines.insert(i + 1, f"        Форма: {form_name}\n")
                return "".join(lines)

    # --- Случай 3: Интерфейс: есть, Список нет — вставить перед следующим ключом уровня 4 ---
    in_interface = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        if line.rstrip() == "Интерфейс:":
            in_interface = True
            continue

        if in_interface:
            if indent == 0 and stripped:           # конец Интерфейс блока
                insert_lines = [
                    f"    Список:\n",
                    f"        Форма: {form_name}\n",
                ]
                for j, l in enumerate(insert_lines):
                    lines.insert(i + j, l)
                return "".join(lines)

    # Если Интерфейс закончился в конце файла — добавить туда
    if in_interface:
        text_result = "".join(lines)
        addition = f"    Список:\n        Форма: {form_name}\n"
        return text_result + addition

    # --- Случай 4: нет Интерфейс вообще — вставить блок после ОбластьВидимости ---
    use_create = "Истина" if obj_type == "Справочник" else None
    interface_lines = ["Интерфейс:\n", "    ВключатьВАвтоИнтерфейс: Истина\n"]
    if use_create:
        interface_lines.append(f"    ИспользоватьСозданиеПриВводе: {use_create}\n")
    interface_lines += [
        "    Список:\n",
        f"        Форма: {form_name}\n",
    ]

    for i, line in enumerate(lines):
        if line.startswith("ОбластьВидимости:"):
            for j, l in enumerate(interface_lines):
                lines.insert(i + 1 + j, l)
            return "".join(lines)

    # Fallback: добавить в конец
    return "".join(lines) + "".join(interface_lines)


# ---------------------------------------------------------------------------
# Основная логика
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    root = os.path.abspath(args.root)
    info = get_form_info(args.object, root)

    object_path: str = info["object_path"]
    object_file: str = info["object_file"]
    object_type: str = info["object_type"]
    namespace: str = info["namespace"]
    fields: list[dict] = info["fields"]
    existing_forms: dict = info["existing_forms"]

    obj = args.object
    title, photo, content_fields = detect_roles(fields)

    if title is None:
        print(f"Ошибка: не найдено строковое поле для заголовка карточки в объекте {obj}.", file=sys.stderr)
        sys.exit(1)

    # МинимальнаяШирина
    if args.min_width is not None:
        min_width = args.min_width
    else:
        min_width = 250 if photo else 400

    # Пути выходных файлов
    form_filename = f"{obj}ФормаСписка.yaml"
    row_filename = f"СтрокаСписка{obj}.yaml"
    form_path = os.path.join(object_path, form_filename)
    row_path = os.path.join(object_path, row_filename)
    object_yaml_path = os.path.join(object_path, object_file)

    existing_form = existing_forms.get("ФормаСписка")

    # --- Dry-run вывод ---
    card_type = "ПроизвольнаяКарточка" if photo else "СтандартнаяКарточка"
    content_desc = ", ".join(f["name"] for f in content_fields) if content_fields else "(нет)"

    print(f"[{'DRY-RUN' if not args.apply else 'ПРИМЕНЯЮ'}] xbsl-form-cards для {obj}\n")
    print(f"Карточка:")
    print(f"  Заголовок: {title}")
    print(f"  Содержимое: {content_desc}")
    if photo:
        print(f"  Фото: {photo}  → {card_type}, МинимальнаяШирина: {min_width}")
    else:
        print(f"  Тип карточки: {card_type}, МинимальнаяШирина: {min_width}")
    print()

    if existing_form:
        print(f"  ⚠️  Форма списка уже существует: {existing_form} — будет перезаписана\n")

    action = "Будет создано" if not args.apply else "Создано"
    print(f"{action}:")
    print(f"  {form_path}")
    print(f"  {row_path}")
    print()
    action2 = "Будет обновлено" if not args.apply else "Обновлено"
    print(f"{action2}:")
    print(f"  {object_yaml_path}  (Интерфейс.Список.Форма)")
    print()

    if not args.apply:
        print("Чтобы применить: добавьте --apply")
        return

    # --- Применить ---
    uid1 = str(uuid.uuid4())
    uid2 = str(uuid.uuid4())

    form_yaml = build_form_yaml(uid1, obj, namespace, title, photo, content_fields, min_width)
    row_yaml = build_row_yaml(uid2, obj, namespace, title, photo, content_fields)

    write_text(form_path, form_yaml)
    write_text(row_path, row_yaml)

    obj_text = read_text(object_yaml_path)
    if obj_text is None:
        print(f"Предупреждение: не удалось прочитать {object_yaml_path}", file=sys.stderr)
    else:
        updated = update_interface(obj_text, obj, object_type)
        write_text(object_yaml_path, updated)

    print("Готово.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Генерация формы карточек для объекта 1С:Элемент")
    parser.add_argument("--object", required=True, help="Имя объекта (например Задачи)")
    parser.add_argument("--root", default=".", help="Корень проекта (по умолчанию: .)")
    parser.add_argument("--min-width", type=int, default=None, help="МинимальнаяШирина карточки (авто: 250 с фото, 400 без)")
    parser.add_argument("--apply", action="store_true", help="Применить изменения (без флага — dry-run)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()
