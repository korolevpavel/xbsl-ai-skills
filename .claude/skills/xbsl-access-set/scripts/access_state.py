#!/usr/bin/env python3
"""
Управление секцией КонтрольДоступа в объектах конфигурации 1С:Элемент.

Во всех командах ниже `{python}` означает `python` в Windows и `python3` в macOS/Linux/WSL. Выбирай команду сразу по текущей ОС, не запускай оба варианта.

Режим сводки (без --set):
    {python} .claude/skills/xbsl-access-set/scripts/access_state.py --root .

Dry-run:
    {python} .claude/skills/xbsl-access-set/scripts/access_state.py --root . --set РазрешеноАутентифицированным

Применить:
    {python} .claude/skills/xbsl-access-set/scripts/access_state.py --root . --set РазрешеноАутентифицированным --apply

Коды выхода: 0 = успех, 1 = ошибка, 3 = объект использует РазрешенияВычисляютсяДляКаждогоОбъекта.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


PROJECT_FILE = "Проект.yaml"
SUBSYSTEM_FILE = "Подсистема.yaml"
YAML_EXT = ".yaml"

SUPPORTED_TYPES = frozenset([
    "Справочник",
    "Документ",
    "РегистрСведений",
    "РегистрНакопления",
    "HttpСервис",
])

VALID_VALUES = frozenset([
    "РазрешеноВсем",
    "РазрешеноАутентифицированным",
    "РазрешеноАдминистраторам",
    "РазрешенияВычисляются",
    "РазрешенияВычисляютсяДляКаждогоОбъекта",
])

# Для каждого типа — секции-якоря: вставить КонтрольДоступа перед первой найденной.
INSERT_BEFORE: dict[str, list[str]] = {
    "Справочник":        ["Интерфейс", "Индексы", "Реквизиты", "ТабличныеЧасти"],
    "Документ":          ["Реквизиты", "ТабличныеЧасти"],
    "РегистрСведений":   ["Измерения", "Ресурсы", "Реквизиты"],
    "РегистрНакопления": ["ПараметрыЗаписи", "ХранитьПериодическиеИтоги", "Измерения", "Ресурсы", "Реквизиты"],
    "HttpСервис":        ["ШаблоныUrl"],
}

_OPERATIONS = frozenset(["Чтение", "Изменение", "Добавление", "Удаление", "Создание", "Вызов"])


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def get_yaml_field(text: str, field: str) -> str | None:
    prefix = field + ":"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix):].strip().strip('"')
            return value if value else None
    return None


def find_project_roots(root: str) -> list[str]:
    result: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        if PROJECT_FILE in filenames:
            result.append(dirpath)
            dirnames.clear()
    return sorted(result)


# ---------------------------------------------------------------------------
# Парсинг КонтрольДоступа
# ---------------------------------------------------------------------------

def parse_control_access(text: str) -> dict:
    """
    Парсит верхнеуровневую секцию КонтрольДоступа (indent=0).

    Возвращает:
    {
        "exists": bool,
        "по_умолчанию": str | None,
        "операции": dict[str, str],
        "расчет_разрешений_по": list[str],
        "обработчик": str | None,
    }
    """
    result: dict = {
        "exists": False,
        "по_умолчанию": None,
        "операции": {},
        "расчет_разрешений_по": [],
        "обработчик": None,
    }

    in_section = False
    in_razr = False
    in_raschet = False

    for line in text.splitlines():
        raw_indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if not stripped:
            continue

        if not in_section:
            if raw_indent == 0 and stripped == "КонтрольДоступа:":
                in_section = True
                result["exists"] = True
            continue

        if raw_indent == 0:
            break  # вышли из секции

        if raw_indent == 4:
            if stripped == "Разрешения:":
                in_razr = True
                in_raschet = False
            elif stripped == "РасчетРазрешенийПо:":
                in_razr = False
                in_raschet = True
            elif stripped.startswith("Обработчик:"):
                val = stripped[len("Обработчик:"):].strip().strip('"')
                result["обработчик"] = val or None
                in_razr = False
                in_raschet = False
            else:
                in_razr = False
                in_raschet = False

        elif raw_indent == 8:
            if in_razr:
                if stripped.startswith("ПоУмолчанию:"):
                    val = stripped[len("ПоУмолчанию:"):].strip().strip('"')
                    result["по_умолчанию"] = val or None
                else:
                    for op in _OPERATIONS:
                        if stripped.startswith(op + ":"):
                            val = stripped[len(op) + 1:].strip().strip('"')
                            result["операции"][op] = val
                            break
            elif in_raschet:
                if stripped.startswith("- "):
                    val = stripped[2:].strip().strip('"')
                    if val:
                        result["расчет_разрешений_по"].append(val)

    return result


# ---------------------------------------------------------------------------
# Сканирование объектов
# ---------------------------------------------------------------------------

def scan_objects(project_root: str, object_name: str | None = None) -> list[dict]:
    """
    Обходит подсистемы проекта и возвращает список объектов поддерживаемых типов.

    Каждый элемент: {name, type, path, access, _text}.
    """
    objects: list[dict] = []

    for dirpath, _dirnames, filenames in os.walk(project_root):
        if SUBSYSTEM_FILE not in filenames:
            continue
        for fname in sorted(filenames):
            if not fname.endswith(YAML_EXT) or fname in (PROJECT_FILE, SUBSYSTEM_FILE):
                continue
            fpath = os.path.join(dirpath, fname)
            text = read_text(fpath)
            if text is None:
                continue
            obj_type = get_yaml_field(text, "ВидЭлемента")
            obj_name = get_yaml_field(text, "Имя")
            if not obj_type or obj_type not in SUPPORTED_TYPES:
                continue
            if object_name is not None and obj_name != object_name:
                continue
            access = parse_control_access(text)
            objects.append({
                "name": obj_name or "",
                "type": obj_type,
                "path": fpath,
                "access": access,
                "_text": text,
            })

    return sorted(objects, key=lambda x: (os.path.dirname(x["path"]), x["name"]))


# ---------------------------------------------------------------------------
# Сводка (JSON)
# ---------------------------------------------------------------------------

def build_summary(objects: list[dict], root: str) -> dict:
    return {
        "objects": [
            {
                "name": obj["name"],
                "type": obj["type"],
                "file": os.path.relpath(obj["path"], root),
                "access": obj["access"],
            }
            for obj in objects
        ],
        "total": len(objects),
    }


# ---------------------------------------------------------------------------
# Обновление/вставка КонтрольДоступа
# ---------------------------------------------------------------------------

def update_default_permission(text: str, new_value: str) -> str:
    """Обновляет ПоУмолчанию в существующей секции КонтрольДоступа."""
    lines = text.splitlines(keepends=True)
    result: list[str] = []
    in_section = False
    in_razr = False
    inserted = False
    razr_line_idx: int | None = None
    section_line_idx: int | None = None

    for line in lines:
        raw_indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if not in_section:
            if raw_indent == 0 and stripped == "КонтрольДоступа:":
                in_section = True
                section_line_idx = len(result)
            result.append(line)
        else:
            if raw_indent == 0:
                in_section = False
                in_razr = False
                result.append(line)
            elif raw_indent == 4 and stripped == "Разрешения:":
                in_razr = True
                razr_line_idx = len(result)
                result.append(line)
            elif raw_indent == 4:
                in_razr = False
                result.append(line)
            elif raw_indent == 8 and in_razr and stripped.startswith("ПоУмолчанию:"):
                result.append(f"        ПоУмолчанию: {new_value}\n")
                inserted = True
            else:
                result.append(line)

    if not inserted:
        if razr_line_idx is not None:
            result.insert(razr_line_idx + 1, f"        ПоУмолчанию: {new_value}\n")
        elif section_line_idx is not None:
            result.insert(section_line_idx + 1, f"    Разрешения:\n        ПоУмолчанию: {new_value}\n")

    return "".join(result)


def insert_control_access(text: str, object_type: str, new_value: str) -> str:
    """Вставляет новую секцию КонтрольДоступа перед первым найденным якорем."""
    block = f"КонтрольДоступа:\n    Разрешения:\n        ПоУмолчанию: {new_value}\n"
    anchors = INSERT_BEFORE.get(object_type, ["Реквизиты"])

    lines = text.splitlines(keepends=True)
    insert_idx: int | None = None

    for i, line in enumerate(lines):
        if line.startswith((" ", "\t")):
            continue
        stripped = line.rstrip("\n").rstrip()
        for anchor in anchors:
            if stripped == anchor + ":" or stripped.startswith(anchor + ": "):
                insert_idx = i
                break
        if insert_idx is not None:
            break

    if insert_idx is not None:
        lines.insert(insert_idx, block)
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(block)

    return "".join(lines)


def set_control_access(text: str, object_type: str, new_value: str) -> tuple[str | None, str]:
    """
    Обновляет или вставляет КонтрольДоступа.

    Возвращает (reason, new_text):
    - reason=None        → изменение нужно применить
    - reason="already_set" → значение уже установлено
    - reason="rls_computed" → текущее ПоУмолчанию = РазрешенияВычисляютсяДляКаждогоОбъекта
    """
    access = parse_control_access(text)

    if access["exists"]:
        curr = access["по_умолчанию"]
        if curr == new_value:
            return "already_set", text
        if curr == "РазрешенияВычисляютсяДляКаждогоОбъекта":
            return "rls_computed", text
        return None, update_default_permission(text, new_value)

    return None, insert_control_access(text, object_type, new_value)


# ---------------------------------------------------------------------------
# Построение плана изменений
# ---------------------------------------------------------------------------

def build_change_plan(
    objects: list[dict],
    new_value: str,
) -> tuple[list[tuple[str, str, str, str]], list[str], list[str]]:
    """
    Возвращает:
    - changes: [(path, original_text, new_text, old_display_value), ...]
    - skipped_same: пути с уже установленным значением
    - skipped_rls: пути с РазрешенияВычисляютсяДляКаждогоОбъекта
    """
    changes: list[tuple[str, str, str, str]] = []
    skipped_same: list[str] = []
    skipped_rls: list[str] = []

    for obj in objects:
        text: str = obj["_text"]
        path: str = obj["path"]
        obj_type: str = obj["type"]
        old_val: str = obj["access"]["по_умолчанию"] or "<секция отсутствует>"

        reason, new_text = set_control_access(text, obj_type, new_value)

        if reason == "already_set":
            skipped_same.append(path)
        elif reason == "rls_computed":
            skipped_rls.append(path)
        else:
            changes.append((path, text, new_text, old_val))

    return changes, skipped_same, skipped_rls


# ---------------------------------------------------------------------------
# Вывод
# ---------------------------------------------------------------------------

def print_dry_run(
    changes: list[tuple[str, str, str, str]],
    skipped_same: list[str],
    skipped_rls: list[str],
    root: str,
    new_value: str,
) -> None:
    def rel(p: str) -> str:
        return os.path.relpath(p, root)

    if changes:
        print(f"\n=== Изменения ({len(changes)}) ===")
        for path, _orig, _new, old_val in changes:
            print(f"\n  {rel(path)}")
            print(f"    - ПоУмолчанию: {old_val}")
            print(f"    + ПоУмолчанию: {new_value}")
    else:
        print("\n=== Изменения: нет ===")

    if skipped_same:
        print(f"\n=== Пропущено (уже установлено): {len(skipped_same)} ===")
        for path in skipped_same:
            print(f"  {rel(path)}")

    if skipped_rls:
        print(f"\n=== Требуют RLS-настройки (xbsl-pattern-rls): {len(skipped_rls)} ===")
        for path in skipped_rls:
            print(f"  {rel(path)}  [РазрешенияВычисляютсяДляКаждогоОбъекта]")

    if changes:
        print(f"\n--- Dry-run. Для применения добавьте флаг --apply ---")


def apply_changes(changes: list[tuple[str, str, str, str]]) -> None:
    for path, _orig, new_text, _old in changes:
        write_text(path, new_text)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Управление КонтрольДоступа в объектах конфигурации 1С:Элемент"
    )
    parser.add_argument("--root", default=".", help="Корень проекта (по умолчанию: .)")
    parser.add_argument(
        "--set",
        default=None,
        dest="set",
        metavar="ЗНАЧЕНИЕ",
        help="Целевое значение ПоУмолчанию. Без флага — режим сводки.",
    )
    parser.add_argument("--object", default=None, help="Ограничить одним объектом")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Применить изменения (без флага — dry-run)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = os.path.abspath(args.root)

    project_roots = find_project_roots(root)
    if not project_roots:
        print(f"Ошибка: проекты не найдены (нет {PROJECT_FILE}) в {root}", file=sys.stderr)
        sys.exit(1)

    all_objects: list[dict] = []
    for proj_root in project_roots:
        all_objects.extend(scan_objects(proj_root, args.object))

    if not all_objects:
        if args.object:
            print(f"Ошибка: объект «{args.object}» не найден.", file=sys.stderr)
        else:
            print("Ошибка: поддерживаемые объекты не найдены.", file=sys.stderr)
        sys.exit(1)

    if args.set is None:
        summary = build_summary(all_objects, root)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    new_value: str = args.set
    if new_value not in VALID_VALUES:
        print(f"Ошибка: недопустимое значение «{new_value}».", file=sys.stderr)
        print(f"Допустимые значения: {', '.join(sorted(VALID_VALUES))}", file=sys.stderr)
        sys.exit(1)

    if new_value == "РазрешенияВычисляютсяДляКаждогоОбъекта":
        print(
            "Ошибка: прямая установка РазрешенияВычисляютсяДляКаждогоОбъекта не поддерживается. "
            "Используйте скилл xbsl-pattern-rls.",
            file=sys.stderr,
        )
        sys.exit(1)

    changes, skipped_same, skipped_rls = build_change_plan(all_objects, new_value)

    # Один объект с RLS → exit(3) как сигнал для скилла
    if args.object and not changes and not skipped_same and skipped_rls:
        print(
            f"Объект «{args.object}» использует РазрешенияВычисляютсяДляКаждогоОбъекта. "
            "Для управления используйте скилл xbsl-pattern-rls.",
            file=sys.stderr,
        )
        sys.exit(3)

    print_dry_run(changes, skipped_same, skipped_rls, root, new_value)

    if not args.apply:
        return

    apply_changes(changes)
    print(f"\n✓ Применено: {len(changes)} файлов обновлено.")


if __name__ == "__main__":
    main()
