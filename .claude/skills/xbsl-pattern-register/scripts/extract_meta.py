#!/usr/bin/env python3
"""
Извлекает метаданные из YAML-файла объекта конфигурации 1С:Элемент.
Поддерживает: РегистрНакопления, Документ.

Использование:
    python3 .claude/skills/xbsl-pattern-register/scripts/extract_meta.py <путь-к-файлу.yaml>

Вывод: JSON
    Для РегистрНакопления — element_type, name, register_kind, dimensions, resources, needs_record_type.
    Для Документа — element_type, name, header_fields, tables, handler_file.
"""

import json
import sys


def print_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def get_yaml_field(text: str, field: str) -> str | None:
    """Извлекает значение простого поля из YAML без внешних зависимостей."""
    prefix = field + ":"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix):].strip().strip('"')
            return value if value else None
    return None


def parse_flat_list(text: str, section_name: str) -> list[dict]:
    """
    Парсит одноуровневую YAML-секцию (секция на indent 0, элементы на indent 4,
    поля элементов на indent 8). Возвращает список словарей.
    """
    lines = text.splitlines()
    in_section = False
    items: list[dict] = []
    current: dict | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())

        if indent == 0 and stripped == section_name + ":":
            in_section = True
            continue

        if not in_section:
            continue

        if indent == 0 and not stripped.startswith("-"):
            break

        if indent == 4 and stripped.startswith("-"):
            if current is not None:
                items.append(current)
            current = {}
            rest = stripped[1:].strip()
            if rest:
                for part in rest.split(","):
                    part = part.strip()
                    if ":" in part:
                        k, _, v = part.partition(":")
                        current[k.strip()] = v.strip()

        elif indent == 8 and current is not None and ":" in stripped and not stripped.startswith("-"):
            key, _, val = stripped.partition(":")
            val = val.strip().strip('"')
            if val:
                current[key.strip()] = val

    if current is not None:
        items.append(current)

    return items


def parse_table_parts(text: str) -> list[dict]:
    """
    Парсит секцию ТабличныеЧасти включая вложенные Реквизиты каждой ТЧ.

    Структура YAML (4 пробела на уровень):
        ТабличныеЧасти:         # indent 0
            -                   # indent 4
                Имя: Товары     # indent 8
                Реквизиты:      # indent 8
                    -           # indent 12
                        Имя: X  # indent 16
    """
    lines = text.splitlines()
    in_tables = False
    in_requisites = False
    tables: list[dict] = []
    current_table: dict | None = None
    current_req: dict | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())

        if indent == 0 and stripped == "ТабличныеЧасти:":
            in_tables = True
            continue

        if not in_tables:
            continue

        if indent == 0 and not stripped.startswith("-"):
            break

        # Новая ТЧ
        if indent == 4 and stripped == "-":
            if current_table is not None:
                if current_req is not None:
                    current_table["fields"].append(current_req)
                    current_req = None
                tables.append(current_table)
            current_table = {"name": "???", "fields": []}
            in_requisites = False
            continue

        if current_table is None:
            continue

        # Поля ТЧ
        if indent == 8:
            if stripped.startswith("Имя:"):
                current_table["name"] = stripped[4:].strip().strip('"')
            elif stripped == "Реквизиты:":
                in_requisites = True
            elif not stripped.startswith("-"):
                in_requisites = False
            continue

        if not in_requisites:
            continue

        # Новый реквизит ТЧ
        if indent == 12 and stripped == "-":
            if current_req is not None:
                current_table["fields"].append(current_req)
            current_req = {}
            continue

        # Поля реквизита ТЧ
        if indent == 16 and current_req is not None and ":" in stripped:
            key, _, val = stripped.partition(":")
            val = val.strip().strip('"')
            if val:
                current_req[key.strip()] = val

    if current_table is not None:
        if current_req is not None:
            current_table["fields"].append(current_req)
        tables.append(current_table)

    return tables


def extract_register(text: str) -> dict:
    name = get_yaml_field(text, "Имя") or "???"
    register_kind = get_yaml_field(text, "ВидРегистра") or "???"

    dimensions = [d["Имя"] for d in parse_flat_list(text, "Измерения") if "Имя" in d]
    resources = [r["Имя"] for r in parse_flat_list(text, "Ресурсы") if "Имя" in r]

    return {
        "element_type": "РегистрНакопления",
        "name": name,
        "register_kind": register_kind,
        "dimensions": dimensions,
        "resources": resources,
        "needs_record_type": register_kind == "Остатки",
    }


def extract_document(text: str) -> dict:
    name = get_yaml_field(text, "Имя") or "???"

    header_fields = [f["Имя"] for f in parse_flat_list(text, "Реквизиты") if "Имя" in f]
    tables = [
        {"name": t["name"], "fields": [f["Имя"] for f in t["fields"] if "Имя" in f]}
        for t in parse_table_parts(text)
    ]

    return {
        "element_type": "Документ",
        "name": name,
        "header_fields": header_fields,
        "tables": tables,
        "handler_file": f"{name}.Объект.xbsl",
    }


def read_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(json.dumps({"error": f"Файл не найден: {path}"}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        print("Использование: python3 extract_meta.py <путь-к-файлу.yaml>", file=sys.stderr)
        sys.exit(1)

    text = read_file(sys.argv[1])
    element_type = get_yaml_field(text, "ВидЭлемента") or ""

    if element_type == "РегистрНакопления":
        print_json(extract_register(text))
    elif element_type == "Документ":
        print_json(extract_document(text))
    else:
        print_json({
            "error": f"Неизвестный ВидЭлемента: '{element_type}'",
            "supported": ["РегистрНакопления", "Документ"],
        })
        sys.exit(1)


if __name__ == "__main__":
    main()
