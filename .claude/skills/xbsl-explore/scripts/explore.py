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

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import TypedDict


PROJECT_FILE = "Проект.yaml"
SUBSYSTEM_FILE = "Подсистема.yaml"
YAML_SUFFIX = ".yaml"


class ObjectInfo(TypedDict):
    name: str
    type: str
    file: str


class SubsystemInfo(TypedDict):
    name: str
    path: str
    objects: list[ObjectInfo]


class ProjectInfo(TypedDict):
    name: str
    path: str
    subsystems: list[SubsystemInfo]


class NameConflict(TypedDict):
    project: str
    subsystem: str
    path: str
    type: str
    file: str


def print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def get_yaml_field(text: str, field: str) -> str | None:
    """Извлекает значение поля из YAML без внешних зависимостей."""
    prefix = f"{field}:"
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix):].strip().strip('"')
        return value if value else None
    return None


def read_text_file(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as file:
            return file.read()
    except OSError:
        return None


def list_sorted_names(folder: str) -> list[str]:
    try:
        return sorted(os.listdir(folder))
    except OSError:
        return []


def scandir_sorted(folder: str) -> list[os.DirEntry[str]]:
    try:
        return sorted(os.scandir(folder), key=lambda entry: entry.name)
    except OSError:
        return []


def build_object_info(filename: str, text: str) -> ObjectInfo | None:
    obj_type = get_yaml_field(text, "ВидЭлемента")
    obj_name = get_yaml_field(text, "Имя")
    if not obj_type or not obj_name:
        return None
    return {"name": obj_name, "type": obj_type, "file": filename}


def scan_objects(folder: str) -> list[ObjectInfo]:
    """Собирает все объекты конфигурации из папки подсистемы."""
    objects: list[ObjectInfo] = []
    for filename in list_sorted_names(folder):
        if not filename.endswith(YAML_SUFFIX):
            continue
        path = os.path.join(folder, filename)
        text = read_text_file(path)
        if text is None:
            continue
        obj_info = build_object_info(filename, text)
        if obj_info is not None:
            objects.append(obj_info)
    return objects


def build_subsystem_info(entry: os.DirEntry[str]) -> SubsystemInfo | None:
    if not entry.is_dir():
        return None
    if not os.path.isfile(os.path.join(entry.path, SUBSYSTEM_FILE)):
        return None
    return {
        "name": entry.name,
        "path": entry.path,
        "objects": scan_objects(entry.path),
    }


def find_subsystems(proj_path: str) -> list[SubsystemInfo]:
    """Ищет подсистемы (папки с Подсистема.yaml) внутри проекта."""
    subsystems: list[SubsystemInfo] = []
    for entry in scandir_sorted(proj_path):
        subsystem = build_subsystem_info(entry)
        if subsystem is not None:
            subsystems.append(subsystem)
    return subsystems


def build_project_info(entry: os.DirEntry[str]) -> ProjectInfo | None:
    if not entry.is_dir():
        return None

    proj_yaml_path = os.path.join(entry.path, PROJECT_FILE)
    if not os.path.isfile(proj_yaml_path):
        return None

    text = read_text_file(proj_yaml_path)
    if text is None:
        return None

    proj_name = get_yaml_field(text, "Имя") or entry.name
    return {
        "name": proj_name,
        "path": entry.path,
        "subsystems": find_subsystems(entry.path),
    }


def find_projects(search_root: str) -> list[ProjectInfo]:
    """Ищет проекты (папки с Проект.yaml) в search_root."""
    projects: list[ProjectInfo] = []
    for entry in scandir_sorted(search_root):
        project = build_project_info(entry)
        if project is not None:
            projects.append(project)
    return projects


def check_name_conflict(projects: list[ProjectInfo], name: str) -> NameConflict | None:
    """Проверяет, существует ли объект с указанным именем в любой подсистеме."""
    for project in projects:
        for subsystem in project["subsystems"]:
            for obj in subsystem["objects"]:
                if obj["name"] != name:
                    continue
                return {
                    "project": project["name"],
                    "subsystem": subsystem["name"],
                    "path": subsystem["path"],
                    "type": obj["type"],
                    "file": obj["file"],
                }
    return None


def filter_projects_by_type(projects: list[ProjectInfo], object_type: str | None) -> list[ProjectInfo]:
    if object_type is None:
        return projects

    filtered_projects: list[ProjectInfo] = []
    for project in projects:
        filtered_subsystems: list[SubsystemInfo] = []
        for subsystem in project["subsystems"]:
            filtered_subsystems.append({
                "name": subsystem["name"],
                "path": subsystem["path"],
                "objects": [obj for obj in subsystem["objects"] if obj["type"] == object_type],
            })
        filtered_projects.append({
            "name": project["name"],
            "path": project["path"],
            "subsystems": filtered_subsystems,
        })
    return filtered_projects


def find_suggested_path(projects: list[ProjectInfo]) -> str | None:
    for project in projects:
        if project["subsystems"]:
            return project["subsystems"][0]["path"]
    return None


def build_result(
    projects: list[ProjectInfo],
    name: str | None,
    conflict: NameConflict | None,
    suggested_path: str | None,
) -> dict:
    result: dict = {"projects": projects}
    if name:
        result["name_check"] = name
        result["conflict"] = conflict
    if suggested_path:
        result["suggested_path"] = suggested_path
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Разведка структуры 1С:Элемент проекта")
    parser.add_argument(
        "--type",
        default=None,
        help="Фильтр объектов по ВидЭлемента (Справочник, Документ, Перечисление...)",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Имя объекта для проверки конфликта",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Корневая папка поиска (по умолчанию: .)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = os.path.abspath(args.root)
    all_projects = find_projects(root)

    if not all_projects:
        print_json({
            "error": "Проекты не найдены (нет папок с Проект.yaml)",
            "searched_in": root,
        })
        sys.exit(1)

    conflict = check_name_conflict(all_projects, args.name) if args.name else None
    filtered_projects = filter_projects_by_type(all_projects, args.type)
    suggested_path = find_suggested_path(filtered_projects)

    print_json(build_result(filtered_projects, args.name, conflict, suggested_path))


if __name__ == "__main__":
    main()
