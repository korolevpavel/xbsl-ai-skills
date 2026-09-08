#!/usr/bin/env python3
"""
Анализирует RLS-состояние объекта конфигурации 1С:Элемент:
КонтрольДоступа, наличие обработчиков уровня 1/2, подсказки по паттерну.

Во всех командах ниже `{python}` означает `python` в Windows и `python3` в macOS/Linux/WSL. Выбирай команду сразу по текущей ОС, не запускай оба варианта.

Использование:
    {python} skills/xbsl-pattern-rls/scripts/rls_state.py --name <ИмяОбъекта> [--root .]

Пример вывода:
{
  "object_name": "Задачи",
  "object_path": "/path/to/subsystem",
  "yaml_file": "Задачи.yaml",
  "xbsl_file": "Задачи.xbsl",
  "xbsl_exists": true,
  "control_access": {
    "exists": false,
    "расчет_разрешений_по": [],
    "разрешения": {}
  },
  "handlers": {
    "level1": false,
    "level2": false
  },
  "pattern_hints": [
    {"field": "Пользователь", "type": "Пользователи.Ссылка?", "pattern": "P1"}
  ]
}
"""

import argparse
import json
import os
import sys
from typing import NamedTuple


PROJECT_FILE = "Проект.yaml"
SUBSYSTEM_FILE = "Подсистема.yaml"

HANDLER_LEVEL1 = "ВычислитьРазрешенияДоступа"
HANDLER_LEVEL2 = "ВычислитьРазрешенияДоступаДляОбъектов"


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


def read_text_file(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def get_yaml_field(text: str, field: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(field + ":"):
            value = stripped[len(field) + 1:].strip().strip('"')
            return value if value else None
    return None


def parse_list_section(text: str, section_name: str) -> list[dict]:
    lines = text.splitlines()
    in_section = False
    items = []
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

        elif indent in (6, 8) and current is not None and ":" in stripped and not stripped.startswith("-"):
            key, _, val = stripped.partition(":")
            val = val.strip()
            if val:
                current[key.strip()] = val

    if current is not None:
        items.append(current)

    return items


def find_project_dirs(root: str) -> list[str]:
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


def find_xbsl_file(object_path: str, object_name: str) -> tuple[str | None, bool]:
    """Возвращает (имя_файла, существует). Приоритет: .xbsl (RLS-модуль), затем .Объект.xbsl (lifecycle)."""
    for candidate in (f"{object_name}.xbsl", f"{object_name}.Объект.xbsl"):
        if os.path.isfile(os.path.join(object_path, candidate)):
            return candidate, True
    return None, False


def parse_control_access(text: str) -> dict:
    """Парсит секцию КонтрольДоступа из YAML объекта."""
    lines = text.splitlines()
    in_section = False
    in_rashet = False
    rashet_po: list[str] = []
    razresheniya: dict[str, str] = {}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())

        if indent == 0 and stripped == "КонтрольДоступа:":
            in_section = True
            in_rashet = False
            continue

        if not in_section:
            continue

        if indent == 0:
            break

        if indent == 4 and stripped == "РасчетРазрешенийПо:":
            in_rashet = True
            continue

        if indent == 4 and stripped != "РасчетРазрешенийПо:":
            in_rashet = False

        if in_rashet and indent == 8 and stripped.startswith("- "):
            rashet_po.append(stripped[2:].strip())
            continue

        if indent == 4 and stripped == "Разрешения:":
            continue

        if indent == 8 and ":" in stripped and not stripped.startswith("-"):
            key, _, val = stripped.partition(":")
            if val.strip():
                razresheniya[key.strip()] = val.strip()

    exists = in_section
    return {
        "exists": exists,
        "расчет_разрешений_по": rashet_po,
        "разрешения": razresheniya,
    }


def check_handlers(xbsl_text: str) -> dict:
    """Проверяет наличие обработчиков RLS уровня 1 и 2 в .xbsl-файле."""
    return {
        "level1": HANDLER_LEVEL1 in xbsl_text,
        "level2": HANDLER_LEVEL2 in xbsl_text,
    }


def build_pattern_hints(fields: list[dict]) -> list[dict]:
    """Классифицирует реквизиты объекта по подходящему RLS-паттерну."""
    hints = []
    p2_count = 0
    for field in fields:
        name = field.get("Имя", "")
        ftype = field.get("Тип", "")
        if not ftype.endswith(".Ссылка?"):
            continue
        if ftype.startswith("Пользователи."):
            hints.append({"field": name, "type": ftype, "pattern": "P1"})
        else:
            p2_count += 1
            pattern = "P2/P3" if p2_count > 1 else "P2"
            hints.append({"field": name, "type": ftype, "pattern": pattern})
    # Если первый P2-кандидат и таких больше одного — переименовать первый тоже в P2/P3
    if p2_count > 1:
        for h in hints:
            if h["pattern"] == "P2":
                h["pattern"] = "P2/P3"
    return hints


def build_result(found: ObjectMatch, object_name: str) -> dict:
    xbsl_file, xbsl_exists = find_xbsl_file(found.object_path, object_name)
    xbsl_text = ""
    if xbsl_exists and xbsl_file:
        xbsl_text = read_text_file(os.path.join(found.object_path, xbsl_file)) or ""

    fields = parse_list_section(found.object_text, "Реквизиты")

    return {
        "object_name": object_name,
        "object_path": found.object_path,
        "yaml_file": found.object_file,
        "xbsl_file": xbsl_file,
        "xbsl_exists": xbsl_exists,
        "control_access": parse_control_access(found.object_text),
        "handlers": check_handlers(xbsl_text) if xbsl_exists else {"level1": False, "level2": False},
        "pattern_hints": build_pattern_hints(fields),
    }


def build_not_found_error(name: str, root: str) -> dict:
    return {"error": f'Объект "{name}" не найден', "searched_in": root}


def build_ambiguous_error(error: AmbiguousObjectError, root: str) -> dict:
    return {
        "error": str(error),
        "searched_in": root,
        "matches": [
            {"object_path": m.object_path, "object_file": m.object_file, "namespace": m.namespace}
            for m in error.matches
        ],
    }


def print_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RLS-состояние объекта конфигурации 1С:Элемент")
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

    print_json(build_result(found, args.name))


if __name__ == "__main__":
    main()
