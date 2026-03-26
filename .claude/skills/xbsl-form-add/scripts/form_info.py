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


class AmbiguousObjectError(Exception):
    def __init__(self, name: str, matches: list[tuple[str, str, str, str]]):
        super().__init__(f'Найдено несколько объектов с именем "{name}"')
        self.name = name
        self.matches = matches


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

        # Свойства текущего элемента (отступ 6 — продолжение inline-элемента, или 8 — блочный элемент)
        elif indent in (6, 8) and current is not None and ":" in stripped and not stripped.startswith("-"):
            key, _, val = stripped.partition(":")
            val = val.strip()
            if val:  # пропускаем пустые значения (вложенные объекты)
                current[key.strip()] = val

    if current is not None:
        items.append(current)

    return items


def find_project_dirs(root: str) -> list[str]:
    """
    Рекурсивно ищет все папки, содержащие Проект.yaml, начиная с root.
    Возвращает список путей к таким папкам.
    """
    result = []
    if os.path.isfile(os.path.join(root, "Проект.yaml")):
        return [root]

    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        return result

    for entry in entries:
        if not entry.is_dir():
            continue
        if os.path.isfile(os.path.join(entry.path, "Проект.yaml")):
            result.append(entry.path)
        else:
            result.extend(find_project_dirs(entry.path))

    return result


def read_text_file(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def get_project_namespace_parts(proj_path: str) -> tuple[str, str]:
    project_file = os.path.join(proj_path, "Проект.yaml")
    project_text = read_text_file(project_file) or ""

    vendor = get_yaml_field(project_text, "Поставщик") or os.path.basename(os.path.dirname(proj_path))
    project = get_yaml_field(project_text, "Имя") or os.path.basename(proj_path)
    return vendor, project


def find_object(root: str, name: str) -> tuple[str, str, str, str] | None:
    """
    Ищет объект по имени во всех проектах и подсистемах.
    Сначала рекурсивно находит все папки с Проект.yaml, затем ищет объект в подсистемах.
    Возвращает (path_to_subsystem, filename, file_text, namespace) или None.
    namespace имеет вид "vendor::project::subsystem".
    """
    project_dirs = find_project_dirs(root)
    matches = []

    for proj_path in project_dirs:
        vendor, project = get_project_namespace_parts(proj_path)

        try:
            sub_entries = sorted(os.scandir(proj_path), key=lambda e: e.name)
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
                    text = read_text_file(fpath)
                    if text is None:
                        continue
                    if get_yaml_field(text, "Имя") == name:
                        subsystem = os.path.basename(sub_entry.path)
                        namespace = f"{vendor}::{project}::{subsystem}"
                        matches.append((sub_entry.path, fname, text, namespace))
            except OSError:
                continue

    if not matches:
        return None
    if len(matches) > 1:
        raise AmbiguousObjectError(name, matches)
    return matches[0]


def suggest_layout(field_count: int, tc_count: int) -> str:
    if tc_count == 0:
        return "simple"
    if tc_count == 1 and field_count >= 5:
        return "panels"
    return "tabs"


def infer_field_type(obj_type: str, field: dict) -> str:
    field_type = field.get("Тип")
    if field_type:
        return field_type

    field_name = field.get("Имя")
    if field_name == "Файлы":
        return "Файлы"
    if obj_type == "Справочник" and field_name == "Наименование":
        return "Строка"
    if obj_type == "Документ" and field_name == "Номер":
        return "Строка"
    return ""


def main():
    parser = argparse.ArgumentParser(description="Анализ объекта 1С:Элемент для создания форм")
    parser.add_argument("--name", required=True, help="Имя объекта конфигурации")
    parser.add_argument("--root", default=".", help="Корневая папка поиска (по умолчанию: .)")
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    try:
        found = find_object(root, args.name)
    except AmbiguousObjectError as exc:
        print(json.dumps({
            "error": str(exc),
            "searched_in": root,
            "matches": [
                {
                    "object_path": obj_path,
                    "object_file": obj_file,
                    "namespace": namespace,
                }
                for obj_path, obj_file, _obj_text, namespace in exc.matches
            ],
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    if not found:
        print(json.dumps({
            "error": f'Объект "{args.name}" не найден',
            "searched_in": root,
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    obj_path, obj_file, obj_text, namespace = found

    obj_type = get_yaml_field(obj_text, "ВидЭлемента") or "Неизвестно"
    fields = parse_list_section(obj_text, "Реквизиты")
    tc_list = parse_list_section(obj_text, "ТабличныеЧасти")

    for f in fields:
        f["Тип"] = infer_field_type(obj_type, f)

    field_count = len(fields)
    tc_count = len(tc_list)

    # Проверяем существование файлов форм
    object_stem = os.path.splitext(obj_file)[0]
    form_obj_file = f"{object_stem}ФормаОбъекта.yaml"
    form_list_file = f"{object_stem}ФормаСписка.yaml"

    existing_forms = {
        "ФормаОбъекта": form_obj_file if os.path.isfile(os.path.join(obj_path, form_obj_file)) else None,
        "ФормаСписка": form_list_file if os.path.isfile(os.path.join(obj_path, form_list_file)) else None,
    }

    result = {
        "object_path": obj_path,
        "object_file": obj_file,
        "object_type": obj_type,
        "namespace": namespace,
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
