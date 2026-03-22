#!/usr/bin/env python3
"""
Анализирует объект конфигурации 1С:Элемент и возвращает данные для создания форм:
путь к объекту, список реквизитов, табличные части, рекомендацию layout,
наличие уже созданных файлов форм.

Использование:
    python3 .claude/skills/xbsl-form-add/scripts/form_info.py --name <ИмяОбъекта> [--root .]

Пример вывода:
{
  "object_path": "/path/to/subsystem",
  "object_file": "Сотрудники.yaml",
  "object_type": "Справочник",
  "field_count": 7,
  "tc_count": 1,
  "fields": [{"name": "Имя", "type": "Строка"}, ...],
  "tc": [{"name": "Навыки"}],
  "suggested_layout": "panels",
  "existing_forms": {
    "ФормаОбъекта": "СотрудникиФормаОбъекта.yaml",
    "ФормаСписка": null
  }
}

suggested_layout:
  "simple" — нет ТЧ → ПроизвольныйШаблонФормы
  "panels" — 1 ТЧ и 5+ реквизитов → панельный layout (Группа)
  "tabs"   — 2+ ТЧ или менее 5 реквизитов → вкладочный layout (РазделФормы)
"""

import argparse
import json
import os
import sys


def get_yaml_field(text: str, field: str) -> str | None:
    """Извлекает значение простого поля из YAML без внешних зависимостей."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(field + ":"):
            value = stripped[len(field) + 1:].strip().strip('"')
            return value if value else None
    return None


def parse_list_section(text: str, section_name: str) -> list[dict]:
    """
    Парсит элементы верхнеуровневой YAML-секции вида:
        SectionName:
            -
                Имя: X
                Тип: Y
    Поддерживает как блочный, так и инлайновый формат ("- Имя: X, Тип: Y").
    Возвращает список словарей с полями верхнего уровня каждого элемента.
    """
    lines = text.splitlines()
    in_section = False
    items = []
    current: dict | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())

        # Начало нужной секции на верхнем уровне
        if indent == 0 and stripped == section_name + ":":
            in_section = True
            continue

        if not in_section:
            continue

        # Возврат на верхний уровень — секция закончилась
        if indent == 0 and not stripped.startswith("-"):
            break

        # Новый элемент списка (отступ 4)
        if indent == 4 and stripped.startswith("-"):
            if current is not None:
                items.append(current)
            current = {}
            rest = stripped[1:].strip()
            if rest:  # инлайновый формат: "- Имя: X, Тип: Y"
                for part in rest.split(","):
                    part = part.strip()
                    if ":" in part:
                        k, _, v = part.partition(":")
                        current[k.strip()] = v.strip()

        # Свойства текущего элемента (отступ 8)
        elif indent == 8 and current is not None and ":" in stripped and not stripped.startswith("-"):
            key, _, val = stripped.partition(":")
            val = val.strip()
            if val:  # пропускаем пустые значения (вложенные объекты)
                current[key.strip()] = val

    if current is not None:
        items.append(current)

    return items


def find_object(root: str, name: str) -> tuple[str, str, str] | None:
    """
    Ищет объект по имени во всех проектах и подсистемах.
    Возвращает (path_to_subsystem, filename, file_text) или None.
    """
    try:
        proj_entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        return None

    for proj_entry in proj_entries:
        if not proj_entry.is_dir():
            continue
        if not os.path.isfile(os.path.join(proj_entry.path, "Проект.yaml")):
            continue

        try:
            sub_entries = sorted(os.scandir(proj_entry.path), key=lambda e: e.name)
        except OSError:
            continue

        for sub_entry in sub_entries:
            if not sub_entry.is_dir():
                continue
            if not os.path.isfile(os.path.join(sub_entry.path, "Подсистема.yaml")):
                continue

            try:
                for fname in sorted(os.listdir(sub_entry.path)):
                    if not fname.endswith(".yaml"):
                        continue
                    fpath = os.path.join(sub_entry.path, fname)
                    try:
                        text = open(fpath, encoding="utf-8").read()
                    except OSError:
                        continue
                    if get_yaml_field(text, "Имя") == name:
                        return sub_entry.path, fname, text
            except OSError:
                continue

    return None


def suggest_layout(field_count: int, tc_count: int) -> str:
    if tc_count == 0:
        return "simple"
    if tc_count == 1 and field_count >= 5:
        return "panels"
    return "tabs"


def main():
    parser = argparse.ArgumentParser(description="Анализ объекта 1С:Элемент для создания форм")
    parser.add_argument("--name", required=True, help="Имя объекта конфигурации")
    parser.add_argument("--root", default=".", help="Корневая папка поиска (по умолчанию: .)")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    found = find_object(root, args.name)

    if not found:
        print(json.dumps({
            "error": f'Объект "{args.name}" не найден',
            "searched_in": root,
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    obj_path, obj_file, obj_text = found

    obj_type = get_yaml_field(obj_text, "ВидЭлемента") or "Неизвестно"
    fields = parse_list_section(obj_text, "Реквизиты")
    tc_list = parse_list_section(obj_text, "ТабличныеЧасти")

    # Нормализуем тип для полей Файлы (нет Тип — это файловый реквизит)
    for f in fields:
        if not f.get("Тип") and f.get("Имя") == "Файлы":
            f["Тип"] = "Файлы"

    field_count = len(fields)
    tc_count = len(tc_list)

    # Проверяем существование файлов форм
    form_obj_file = f"{args.name}ФормаОбъекта.yaml"
    form_list_file = f"{args.name}ФормаСписка.yaml"

    existing_forms = {
        "ФормаОбъекта": form_obj_file if os.path.isfile(os.path.join(obj_path, form_obj_file)) else None,
        "ФормаСписка": form_list_file if os.path.isfile(os.path.join(obj_path, form_list_file)) else None,
    }

    result = {
        "object_path": obj_path,
        "object_file": obj_file,
        "object_type": obj_type,
        "field_count": field_count,
        "tc_count": tc_count,
        "fields": [{"name": f.get("Имя", "?"), "type": f.get("Тип", "")} for f in fields],
        "tc": [{"name": t.get("Имя", "?")} for t in tc_list],
        "suggested_layout": suggest_layout(field_count, tc_count),
        "existing_forms": existing_forms,
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
