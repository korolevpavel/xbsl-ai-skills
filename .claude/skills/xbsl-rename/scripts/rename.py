#!/usr/bin/env python3
"""
Безопасное переименование объекта конфигурации 1С:Элемент.
Обновляет все ссылки в YAML и XBSL файлах проекта, переименовывает файлы.

Использование (dry-run — только показывает изменения):
    python3 .claude/skills/xbsl-rename/scripts/rename.py --old-name Номенклатура --new-name Товары [--root .]

Применить изменения:
    python3 .claude/skills/xbsl-rename/scripts/rename.py --old-name Номенклатура --new-name Товары [--root .] --apply
"""

from __future__ import annotations

import argparse
import os
import re
import sys


PROJECT_FILE = "Проект.yaml"
SUBSYSTEM_FILE = "Подсистема.yaml"
YAML_EXT = ".yaml"
XBSL_EXT = ".xbsl"


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


# ---------------------------------------------------------------------------
# Поиск файлов проекта
# ---------------------------------------------------------------------------

def find_project_roots(root: str) -> list[str]:
    """Рекурсивно находит папки с Проект.yaml."""
    result: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        if PROJECT_FILE in filenames:
            result.append(dirpath)
            dirnames.clear()  # не погружаться внутрь проекта
    return sorted(result)


def collect_project_files(project_root: str) -> list[str]:
    """Все .yaml и .xbsl файлы внутри проекта."""
    files: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(project_root):
        for name in sorted(filenames):
            if name.endswith(YAML_EXT) or name.endswith(XBSL_EXT):
                files.append(os.path.join(dirpath, name))
    return files


# ---------------------------------------------------------------------------
# Замены в тексте
# ---------------------------------------------------------------------------

def make_patterns(old_name: str) -> list[tuple[re.Pattern, str]]:
    """
    Возвращает список (pattern, replacement) для замены старого имени новым.

    Два случая:
    1. Имя как самостоятельное слово: Номенклатура.Ссылка?, Имя: Номенклатура, ...
    2. Имя как префикс составного имени формы: НоменклатураФормаОбъекта
       (следующий символ — прописная буква кириллицы или латиницы)
    """
    escaped = re.escape(old_name)
    return [
        # Составные имена (форма): Номенклатура перед заглавной буквой
        (re.compile(r"\b" + escaped + r"(?=[А-ЯЁA-Z])", re.UNICODE), old_name),
        # Самостоятельное слово
        (re.compile(r"\b" + escaped + r"\b", re.UNICODE), old_name),
    ]


def apply_substitutions(
    content: str,
    old_name: str,
    new_name: str,
    new_presentation: str | None = None,
    old_presentation: str | None = None,
    replace_labels: bool = False,
) -> str:
    """Применяет все замены к тексту, возвращает изменённый текст.

    replace_labels=True только для файлов объекта и его форм (файлы из списка переименований).
    Для всех остальных файлов (Подсистема.yaml, документы и т.д.) поля Заголовок/Представление
    не трогаются.
    """
    escaped = re.escape(old_name)
    compound_re = re.compile(r"\b" + escaped + r"(?=[А-ЯЁA-Z])", re.UNICODE)
    standalone_re = re.compile(r"\b" + escaped + r"\b", re.UNICODE)

    # Базовая замена — построчно, пропуская строки Представление:/Заголовок:
    # (их обрабатывает _replace_label_fields — только для файлов семейства объекта)
    lines = content.splitlines(keepends=True)
    result: list[str] = []
    for line in lines:
        if _LABEL_LINE_RE.match(line):
            result.append(line)
        else:
            line = compound_re.sub(new_name, line)
            line = standalone_re.sub(new_name, line)
            result.append(line)
    content = "".join(result)

    # Поля Представление/Заголовок — только для файла объекта и его форм
    if replace_labels:
        content = _replace_label_fields(content, old_name, new_presentation or new_name, old_presentation)
    return content


_LABEL_FIELD_RE = re.compile(
    r"^(\s*(?:Представление|Заголовок)\s*:\s*)(.+)$",
    re.MULTILINE | re.UNICODE,
)

# Строки, начинающиеся с Представление: или Заголовок: — не трогаются базовой заменой
_LABEL_LINE_RE = re.compile(
    r"^\s*(?:Представление|Заголовок)\s*:",
    re.UNICODE,
)


def _replace_label_fields(
    content: str,
    old_name: str,
    new_presentation: str,
    old_presentation: str | None = None,
) -> str:
    """
    Заменяет значения полей Представление/Заголовок если:
    - значение является «корнем» старого имени (old_name начинается с этого значения, минимум 3 символа), или
    - значение совпадает с явно заданным old_presentation.
    Использует new_presentation как новое значение (может содержать пробелы).
    """
    def replacer(m: re.Match) -> str:
        prefix, value = m.group(1), m.group(2).strip()
        if value == new_presentation:
            return m.group(0)
        if old_presentation and value == old_presentation:
            return prefix + new_presentation
        if len(value) >= 3 and old_name.startswith(value):
            return prefix + new_presentation
        return m.group(0)

    return _LABEL_FIELD_RE.sub(replacer, content)


def changed_lines(original: str, modified: str, filepath: str) -> list[str]:
    """Возвращает строки с изменениями в формате diff-подобного вывода."""
    orig_lines = original.splitlines()
    mod_lines = modified.splitlines()
    result: list[str] = []
    for i, (old_line, new_line) in enumerate(zip(orig_lines, mod_lines), start=1):
        if old_line != new_line:
            result.append(f"  строка {i}:")
            result.append(f"    - {old_line.strip()}")
            result.append(f"    + {new_line.strip()}")
    return result


# ---------------------------------------------------------------------------
# Переименование файлов
# ---------------------------------------------------------------------------

def new_filename(name: str, old_name: str, new_name: str) -> str:
    """Вычисляет новое имя файла с учётом обоих паттернов замены."""
    # Составное имя (форма): НоменклатураФормаОбъекта → ТоварыФормаОбъекта
    result = re.sub(
        r"\b" + re.escape(old_name) + r"(?=[А-ЯЁA-Z])",
        new_name,
        name,
        flags=re.UNICODE,
    )
    # Самостоятельное слово: Номенклатура.yaml → Товары.yaml
    result = re.sub(
        r"\b" + re.escape(old_name) + r"\b",
        new_name,
        result,
        flags=re.UNICODE,
    )
    return result


def files_to_rename(project_files: list[str], old_name: str, new_name: str) -> list[tuple[str, str]]:
    """Находит файлы, которые нужно переименовать (старый путь, новый путь)."""
    renames: list[tuple[str, str]] = []
    for path in project_files:
        base = os.path.basename(path)
        new_base = new_filename(base, old_name, new_name)
        if new_base != base:
            new_path = os.path.join(os.path.dirname(path), new_base)
            renames.append((path, new_path))
    return renames


# ---------------------------------------------------------------------------
# Поиск объекта
# ---------------------------------------------------------------------------

def find_object_files(project_files: list[str], old_name: str) -> list[tuple[str, str]]:
    """Находит все YAML-файлы с полем Имя: {old_name}.

    Возвращает список (path, вид_элемента).
    """
    result: list[tuple[str, str]] = []
    for path in project_files:
        if not path.endswith(YAML_EXT):
            continue
        text = read_text(path)
        if text and get_yaml_field(text, "Имя") == old_name:
            kind = get_yaml_field(text, "ВидЭлемента") or "?"
            result.append((path, kind))
    return result


# ---------------------------------------------------------------------------
# Основная логика
# ---------------------------------------------------------------------------

def object_family(object_file: str, old_name: str) -> set[str]:
    """Возвращает множество путей файлов семейства объекта: сам файл + его .xbsl и формы.

    Семейство определяется по директории и имени: все файлы в той же папке,
    чьё basename начинается с old_name (учитывает СтароеИмя.xbsl, СтароеИмяФорма*.yaml и т.д.).
    """
    obj_dir = os.path.dirname(object_file)
    prefix = old_name.lower()
    family: set[str] = set()
    try:
        for entry in os.scandir(obj_dir):
            if entry.name.lower().startswith(prefix) and (
                entry.name.endswith(YAML_EXT) or entry.name.endswith(XBSL_EXT)
            ):
                family.add(entry.path)
    except OSError:
        pass
    family.add(object_file)
    return family


def build_plan(
    project_files: list[str],
    old_name: str,
    new_name: str,
    new_presentation: str | None = None,
    old_presentation: str | None = None,
    object_file: str | None = None,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
    """
    Возвращает:
    - text_changes: список (path, original, modified) для файлов с заменами в тексте
    - renames: список (old_path, new_path) для файлов на переименование

    object_file — путь к файлу переименуемого объекта (из find_object_files).
    replace_labels=True только для файлов семейства этого объекта.
    """
    renames = files_to_rename(project_files, old_name, new_name)

    # Семейство объекта — файлы, в которых меняются Представление/Заголовок
    label_files: set[str] = object_family(object_file, old_name) if object_file else set()

    text_changes: list[tuple[str, str, str]] = []

    for path in project_files:
        text = read_text(path)
        if text is None:
            continue
        replace_labels = path in label_files
        modified = apply_substitutions(text, old_name, new_name, new_presentation, old_presentation, replace_labels)
        if modified != text:
            text_changes.append((path, text, modified))

    return text_changes, renames


def print_plan(
    text_changes: list[tuple[str, str, str]],
    renames: list[tuple[str, str]],
    root: str,
) -> None:
    def rel(path: str) -> str:
        return os.path.relpath(path, root)

    if renames:
        print(f"\n=== Файлы для переименования ({len(renames)}) ===")
        for old_path, new_path in renames:
            print(f"  {rel(old_path)}")
            print(f"    → {rel(new_path)}")
    else:
        print("\n=== Файлы для переименования: нет ===")

    if text_changes:
        print(f"\n=== Текстовые замены в файлах ({len(text_changes)}) ===")
        for path, original, modified in text_changes:
            lines = changed_lines(original, modified, path)
            if lines:
                print(f"\n  {rel(path)}:")
                for line in lines:
                    print(line)
    else:
        print("\n=== Текстовые замены: нет ===")


def apply_plan(
    text_changes: list[tuple[str, str, str]],
    renames: list[tuple[str, str]],
) -> None:
    # Сначала применяем текстовые замены
    for path, _original, modified in text_changes:
        write_text(path, modified)

    # Затем переименовываем файлы (после записи, чтобы не потерять содержимое)
    for old_path, new_path in renames:
        os.rename(old_path, new_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Безопасное переименование объекта конфигурации 1С:Элемент"
    )
    parser.add_argument("--old-name", required=True, help="Текущее имя объекта")
    parser.add_argument("--new-name", required=True, help="Новое имя объекта")
    parser.add_argument(
        "--new-presentation",
        default=None,
        help="Человекочитаемое представление (Представление/Заголовок). "
             "Если не задано — используется --new-name.",
    )
    parser.add_argument(
        "--old-presentation",
        default=None,
        help="Старое представление объекта (Представление/Заголовок). "
             "Используется для замены значений в полях Заголовок/Представление, "
             "которые не совпадают с техническим именем (напр. «Место хранения» для МестаХранения).",
    )
    parser.add_argument("--root", default=".", help="Корневая папка поиска (по умолчанию: .)")
    parser.add_argument(
        "--object-file",
        default=None,
        help="Путь к файлу переименуемого объекта (относительно --root или абсолютный). "
             "Обязателен если в проекте несколько объектов с одинаковым именем.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Применить изменения (без флага — только показать план)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = os.path.abspath(args.root)
    old_name: str = args.old_name
    new_name: str = args.new_name
    new_presentation: str = args.new_presentation if args.new_presentation else new_name
    old_presentation: str | None = args.old_presentation

    project_roots = find_project_roots(root)
    if not project_roots:
        print(f"Ошибка: проекты не найдены (нет папок с {PROJECT_FILE}) в {root}", file=sys.stderr)
        sys.exit(1)

    # Собираем файлы всех проектов
    all_files: list[str] = []
    for proj_root in project_roots:
        all_files.extend(collect_project_files(proj_root))

    # Определяем файл объекта
    if args.object_file:
        object_file = os.path.abspath(os.path.join(root, args.object_file))
        if not os.path.isfile(object_file):
            print(f"Ошибка: файл «{args.object_file}» не найден.", file=sys.stderr)
            sys.exit(1)
    else:
        matches = find_object_files(all_files, old_name)
        if not matches:
            print(f"Ошибка: объект с именем «{old_name}» не найден в проектах.", file=sys.stderr)
            sys.exit(1)
        if len(matches) > 1:
            print(f"Найдено несколько объектов с именем «{old_name}»:", file=sys.stderr)
            for path, kind in matches:
                print(f"  [{kind}]  {os.path.relpath(path, root)}", file=sys.stderr)
            print(
                f"\nУкажите нужный объект через --object-file <путь>",
                file=sys.stderr,
            )
            sys.exit(2)
        object_file = matches[0][0]

    print(f"Объект: {os.path.relpath(object_file, root)}")
    print(f"Переименование: «{old_name}» → «{new_name}»")
    if new_presentation != new_name:
        print(f"Представление: «{new_presentation}»")

    text_changes, renames = build_plan(all_files, old_name, new_name, new_presentation, old_presentation, object_file)

    print_plan(text_changes, renames, root)

    total = len(text_changes) + len(renames)
    if total == 0:
        print("\nИзменений нет.")
        return

    if not args.apply:
        print(f"\n--- Dry-run. Для применения добавьте флаг --apply ---")
        return

    apply_plan(text_changes, renames)
    print(f"\n✓ Применено: {len(text_changes)} файлов обновлено, {len(renames)} переименовано.")


if __name__ == "__main__":
    main()
