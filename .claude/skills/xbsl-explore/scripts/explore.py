#!/usr/bin/env python3
"""
Разведка структуры 1С:Элемент проекта.
Находит проекты, подсистемы и существующие объекты. Проверяет конфликты имён.

Использование:
    python3 .claude/skills/xbsl-explore/scripts/explore.py [--type ВидЭлемента] [--name ИмяОбъекта] [--root /path]

Примеры:
    python3 .claude/skills/xbsl-explore/scripts/explore.py --root cc
    python3 .claude/skills/xbsl-explore/scripts/explore.py --type Справочник --root cc
    python3 .claude/skills/xbsl-explore/scripts/explore.py --type Документ --name Заказы --root cc
"""

import argparse
import json
import os
import sys


def get_yaml_field(text: str, field: str) -> str | None:
    """Извлекает значение поля из YAML без внешних зависимостей."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(field + ":"):
            value = stripped[len(field) + 1:].strip().strip('"')
            return value if value else None
    return None


def scan_objects(folder: str) -> list[dict]:
    """Собирает все объекты конфигурации из папки подсистемы."""
    objects = []
    try:
        entries = sorted(os.listdir(folder))
    except OSError:
        return objects

    for filename in entries:
        if not filename.endswith(".yaml"):
            continue
        path = os.path.join(folder, filename)
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            continue
        obj_type = get_yaml_field(text, "ВидЭлемента")
        obj_name = get_yaml_field(text, "Имя")
        if obj_type and obj_name:
            objects.append({"name": obj_name, "type": obj_type, "file": filename})
    return objects


def find_subsystems(proj_path: str) -> list[dict]:
    """Ищет подсистемы (папки с Подсистема.yaml) внутри проекта."""
    subsystems = []
    try:
        entries = sorted(os.scandir(proj_path), key=lambda e: e.name)
    except OSError:
        return subsystems

    for entry in entries:
        if not entry.is_dir():
            continue
        if not os.path.isfile(os.path.join(entry.path, "Подсистема.yaml")):
            continue
        subsystems.append({
            "name": entry.name,
            "path": entry.path,
            "objects": scan_objects(entry.path),
        })
    return subsystems


def find_projects(search_root: str) -> list[dict]:
    """Ищет проекты (папки с Проект.yaml) в search_root."""
    projects = []
    try:
        entries = sorted(os.scandir(search_root), key=lambda e: e.name)
    except OSError:
        return projects

    for entry in entries:
        if not entry.is_dir():
            continue
        proj_yaml_path = os.path.join(entry.path, "Проект.yaml")
        if not os.path.isfile(proj_yaml_path):
            continue
        try:
            text = open(proj_yaml_path, encoding="utf-8").read()
        except OSError:
            continue
        proj_name = get_yaml_field(text, "Имя") or entry.name
        projects.append({
            "name": proj_name,
            "path": entry.path,
            "subsystems": find_subsystems(entry.path),
        })
    return projects


def check_name_conflict(projects: list[dict], name: str) -> dict | None:
    """Проверяет, существует ли объект с указанным именем в любой подсистеме."""
    for project in projects:
        for sub in project["subsystems"]:
            for obj in sub["objects"]:
                if obj["name"] == name:
                    return {
                        "project": project["name"],
                        "subsystem": sub["name"],
                        "path": sub["path"],
                        "type": obj["type"],
                        "file": obj["file"],
                    }
    return None


def main():
    parser = argparse.ArgumentParser(description="Разведка структуры 1С:Элемент проекта")
    parser.add_argument("--type", default=None,
                        help="Фильтр объектов по ВидЭлемента (Справочник, Документ, Перечисление...)")
    parser.add_argument("--name", default=None,
                        help="Имя объекта для проверки конфликта")
    parser.add_argument("--root", default=".",
                        help="Корневая папка поиска (по умолчанию: .)")
    args = parser.parse_args()

    root = os.path.abspath(args.root)

    all_projects = find_projects(root)

    if not all_projects:
        print(json.dumps({
            "error": "Проекты не найдены (нет папок с Проект.yaml)",
            "searched_in": root,
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    # Проверка конфликта имён (до фильтрации по типу)
    conflict = check_name_conflict(all_projects, args.name) if args.name else None

    # Фильтрация объектов по типу (для удобства чтения вывода)
    if args.type:
        for project in all_projects:
            for sub in project["subsystems"]:
                sub["objects"] = [o for o in sub["objects"] if o["type"] == args.type]

    # Рекомендуемый путь: первый проект с подсистемами
    suggested_path = None
    for project in all_projects:
        if project["subsystems"]:
            suggested_path = project["subsystems"][0]["path"]
            break

    result = {"projects": all_projects}

    if args.name:
        result["name_check"] = args.name
        result["conflict"] = conflict  # None — конфликта нет, объект — конфликт найден

    if suggested_path:
        result["suggested_path"] = suggested_path

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
