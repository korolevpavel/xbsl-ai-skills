#!/usr/bin/env python3
"""
Находит компонент приложения (СтандартноеКлиентскоеПриложениеСРазделами) в проекте
1С:Элемент и анализирует его текущее состояние для xbsl-collab-add (P2/P3).

Использование:
    python3 .claude/skills/xbsl-collab-add/scripts/find_app.py [--root .]

Пример вывода:
{
  "status": "found",
  "apps": [{
    "yaml_path": "/abs/path/to/App.yaml",
    "xbsl_path": "/abs/path/to/App.xbsl",
    "xbsl_exists": false,
    "name": "App",
    "nav_yaml": "/abs/path/to/Nav.yaml",
    "nav_is_inline": false,
    "has_interaction_group": false,
    "has_web_chat": false
  }]
}
"""

import argparse
import json
import os
import sys

PROJECT_FILE = "Проект.yaml"
SUBSYSTEM_FILE = "Подсистема.yaml"
APP_TYPE = "СтандартноеКлиентскоеПриложениеСРазделами"
NAV_FIELD = "КомандныйИнтерфейсПанелиНавигации"
INTERACTION_MARKERS = [
    "ФормаУправленияСистемойВзаимодействия",
    "ФормаРегистрацииСистемыВзаимодействия",
    "ФормаРегистрацииВебЧата",
]


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


def is_app_component(text: str) -> bool:
    """Возвращает True если файл содержит Наследует: {Тип: СтандартноеКлиентскоеПриложениеСРазделами}."""
    lines = text.splitlines()
    in_inherits = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())

        if indent == 0 and stripped == "Наследует:":
            in_inherits = True
            continue

        if in_inherits and indent == 0:
            break

        if in_inherits and indent == 4 and stripped == f"Тип: {APP_TYPE}":
            return True

    return False


def get_nav_info(text: str, yaml_dir: str) -> tuple[str | None, bool, str]:
    """
    Определяет источник навигации.
    Возвращает (nav_yaml_path | None, nav_is_inline, nav_text).
    nav_text используется для поиска маркеров.
    """
    lines = text.splitlines()
    in_inherits = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())

        if indent == 0 and stripped == "Наследует:":
            in_inherits = True
            continue

        if in_inherits and indent == 0:
            break

        if in_inherits and indent == 4 and stripped.startswith(NAV_FIELD + ":"):
            value = stripped[len(NAV_FIELD) + 1:].strip()
            if value.startswith("="):
                nav_name = value[1:].strip()
                nav_path = os.path.join(yaml_dir, f"{nav_name}.yaml")
                nav_text = read_text_file(nav_path) or ""
                return nav_path if nav_text else None, False, nav_text
            # inline — ищем маркеры прямо в тексте приложения
            return None, True, text

    return None, True, text


def check_has_web_chat(text: str) -> bool:
    """Проверяет наличие ВебЧат: {Использовать: Истина} в Наследует."""
    lines = text.splitlines()
    in_inherits = False
    in_webchat = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())

        if indent == 0 and stripped == "Наследует:":
            in_inherits = True
            continue

        if in_inherits and indent == 0:
            break

        if in_inherits and indent == 4 and stripped == "ВебЧат:":
            in_webchat = True
            continue

        if in_webchat and indent == 4 and stripped != "ВебЧат:":
            in_webchat = False
            continue

        if in_webchat and stripped == "Использовать: Истина":
            return True

    return False


def check_has_interaction_group(nav_text: str) -> bool:
    """Проверяет наличие команд управления СВ в навигации."""
    for marker in INTERACTION_MARKERS:
        if marker in nav_text:
            return True
    return False


def find_projects(root: str) -> list[str]:
    if os.path.isfile(os.path.join(root, PROJECT_FILE)):
        return [root]
    result = []
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
            result.extend(find_projects(entry.path))
    return result


def find_subsystem_dirs(project_path: str) -> list[str]:
    try:
        entries = sorted(os.scandir(project_path), key=lambda e: e.name)
    except OSError:
        return []
    return [
        e.path for e in entries
        if e.is_dir() and os.path.isfile(os.path.join(e.path, SUBSYSTEM_FILE))
    ]


def scan_for_apps(root: str) -> list[dict]:
    apps = []
    for proj_path in find_projects(root):
        for subsys_path in find_subsystem_dirs(proj_path):
            try:
                filenames = sorted(os.listdir(subsys_path))
            except OSError:
                continue
            for filename in filenames:
                if not filename.endswith(".yaml"):
                    continue
                filepath = os.path.join(subsys_path, filename)
                text = read_text_file(filepath)
                if not text or not is_app_component(text):
                    continue

                name = get_yaml_field(text, "Имя") or filename[:-5]
                xbsl_path = os.path.join(subsys_path, f"{name}.xbsl")

                nav_yaml, nav_is_inline, nav_text = get_nav_info(text, subsys_path)

                apps.append({
                    "yaml_path": filepath,
                    "xbsl_path": xbsl_path,
                    "xbsl_exists": os.path.isfile(xbsl_path),
                    "name": name,
                    "nav_yaml": nav_yaml,
                    "nav_is_inline": nav_is_inline,
                    "has_interaction_group": check_has_interaction_group(nav_text),
                    "has_web_chat": check_has_web_chat(text),
                })
    return apps


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Найти компонент приложения в проекте 1С:Элемент"
    )
    parser.add_argument("--root", default=".", help="Корень проекта (по умолчанию: .)")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    apps = scan_for_apps(root)

    if not apps:
        print(json.dumps({"status": "not_found", "apps": []}, ensure_ascii=False, indent=2))
        sys.exit(1)

    print(json.dumps({"status": "found", "apps": apps}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
