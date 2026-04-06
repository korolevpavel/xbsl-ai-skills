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
from typing import NamedTuple


PROJECT_FILE = "Проект.yaml"
SUBSYSTEM_FILE = "Подсистема.yaml"
UNKNOWN_OBJECT_TYPE = "Неизвестно"


class ObjectMatch(NamedTuple):
    object_path: str
    object_file: str
    object_text: str
    namespace: str


class AmbiguousObjectError(Exception):
    def __init__(self, name: str, matches: list[ObjectMatch]):
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
    if os.path.isfile(os.path.join(root, PROJECT_FILE)):
        return [root]

    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        return result

    for entry in entries:
        if not entry.is_dir():
            continue
        if os.path.isfile(os.path.join(entry.path, PROJECT_FILE)):
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
    project_file = os.path.join(proj_path, PROJECT_FILE)
    project_text = read_text_file(project_file) or ""

    vendor = get_yaml_field(project_text, "Поставщик") or os.path.basename(os.path.dirname(proj_path))
    project = get_yaml_field(project_text, "Имя") or os.path.basename(proj_path)
    return vendor, project


def iter_subsystem_dirs(project_path: str) -> list[str]:
    try:
        entries = sorted(os.scandir(project_path), key=lambda e: e.name)
    except OSError:
        return []

    return [
        entry.path
        for entry in entries
        if entry.is_dir() and os.path.isfile(os.path.join(entry.path, SUBSYSTEM_FILE))
    ]


def iter_yaml_files(path: str):
    try:
        filenames = sorted(os.listdir(path))
    except OSError:
        return

    for filename in filenames:
        if filename.endswith(".yaml"):
            yield filename, os.path.join(path, filename)


def find_object(root: str, name: str) -> ObjectMatch | None:
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
        for subsystem_path in iter_subsystem_dirs(proj_path):
            for filename, file_path in iter_yaml_files(subsystem_path) or ():
                text = read_text_file(file_path)
                if text is None or get_yaml_field(text, "Имя") != name:
                    continue

                subsystem = os.path.basename(subsystem_path)
                namespace = f"{vendor}::{project}::{subsystem}"
                matches.append(ObjectMatch(subsystem_path, filename, text, namespace))

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


def normalize_fields(obj_type: str, fields: list[dict]) -> list[dict]:
    normalized_fields = []

    for field in fields:
        normalized_field = dict(field)
        normalized_field["Тип"] = infer_field_type(obj_type, normalized_field)
        normalized_fields.append(normalized_field)

    return normalized_fields


def build_existing_forms(object_path: str, object_file: str) -> dict[str, str | None]:
    object_stem = os.path.splitext(object_file)[0]
    form_obj_file = f"{object_stem}ФормаОбъекта.yaml"
    form_list_file = f"{object_stem}ФормаСписка.yaml"

    return {
        "ФормаОбъекта": form_obj_file if os.path.isfile(os.path.join(object_path, form_obj_file)) else None,
        "ФормаСписка": form_list_file if os.path.isfile(os.path.join(object_path, form_list_file)) else None,
    }


def build_result(found: ObjectMatch) -> dict:
    obj_type = get_yaml_field(found.object_text, "ВидЭлемента") or UNKNOWN_OBJECT_TYPE
    fields = normalize_fields(obj_type, parse_list_section(found.object_text, "Реквизиты"))
    tc_list = parse_list_section(found.object_text, "ТабличныеЧасти")
    additional_hierarchies = parse_list_section(found.object_text, "ДополнительныеИерархии")

    field_count = len(fields)
    tc_count = len(tc_list)
    is_hierarchical = get_yaml_field(found.object_text, "Иерархический") == "Истина"

    return {
        "object_path": found.object_path,
        "object_file": found.object_file,
        "object_type": obj_type,
        "namespace": found.namespace,
        "field_count": field_count,
        "tc_count": tc_count,
        "fields": [{"name": field.get("Имя", "?"), "type": field.get("Тип", "")} for field in fields],
        "tc": [{"name": tc.get("Имя", "?")} for tc in tc_list],
        "suggested_layout": suggest_layout(field_count, tc_count),
        "existing_forms": build_existing_forms(found.object_path, found.object_file),
        "is_hierarchical": is_hierarchical,
        "additional_hierarchies": [
            {"name": h.get("Имя", ""), "field": h.get("ПолеРодителя", "")}
            for h in additional_hierarchies
        ],
    }


def build_not_found_error(name: str, root: str) -> dict:
    return {
        "error": f'Объект "{name}" не найден',
        "searched_in": root,
    }


def build_ambiguous_error(error: AmbiguousObjectError, root: str) -> dict:
    return {
        "error": str(error),
        "searched_in": root,
        "matches": [
            {
                "object_path": match.object_path,
                "object_file": match.object_file,
                "namespace": match.namespace,
            }
            for match in error.matches
        ],
    }


def print_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Анализ объекта 1С:Элемент для создания форм")
    parser.add_argument("--name", required=True, help="Имя объекта конфигурации")
    parser.add_argument("--root", default=".", help="Корневая папка поиска (по умолчанию: .)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    args = parse_args(argv)
    root = os.path.abspath(args.root)
    try:
        found = find_object(root, args.name)
    except AmbiguousObjectError as exc:
        print_json(build_ambiguous_error(exc, root))
        sys.exit(1)

    if not found:
        print_json(build_not_found_error(args.name, root))
        sys.exit(1)

    print_json(build_result(found))


if __name__ == "__main__":
    main()
