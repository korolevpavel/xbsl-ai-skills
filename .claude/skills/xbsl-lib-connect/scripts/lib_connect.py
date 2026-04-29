#!/usr/bin/env python3
"""
Вспомогательный скрипт для скилла xbsl-lib-connect.

Действия (--action):
  inspect         — прочитать метаданные из .xlib (Assembly.yaml внутри ZIP)
  find-xlib       — найти все *.xlib файлы в папке рекурсивно
  patch-yaml      — добавить/обновить библиотеку в разделе Библиотеки Проект.yaml
  analyze         — извлечь подсистемы и публичные типы из .xlib
  validate-version — проверить формат версии релиза (X.Y.Z)
  cleanup         — удалить временную папку

Использование:
  python3 lib_connect.py --action inspect --file lib.xlib
  python3 lib_connect.py --action find-xlib --dir /tmp/repo
  python3 lib_connect.py --action patch-yaml --project-yaml Проект.yaml \\
      --name TelegramBot --vendor e1c --version 1.0.0 [--dry-run]
  python3 lib_connect.py --action analyze --file lib.xlib
  python3 lib_connect.py --action validate-version --version 1.0.0
  python3 lib_connect.py --action cleanup --dir /tmp/xlib_src_abc
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def parse_simple_yaml(text: str) -> dict:
    """Минимальный парсер YAML: читает пары key: value (плоский уровень)."""
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if ':' in line and not line.startswith('#') and not line.startswith('-'):
            key, _, val = line.partition(':')
            result[key.strip()] = val.strip().strip('"').strip("'")
    return result


def out(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def die(data: dict) -> None:
    out(data)
    sys.exit(1)


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------

def action_inspect(file: str) -> None:
    if not os.path.isfile(file):
        die({"error": "file_not_found", "file": file})

    try:
        with zipfile.ZipFile(file) as zf:
            if 'Assembly.yaml' not in zf.namelist():
                die({"error": "no_assembly_yaml", "file": file})
            raw = zf.read('Assembly.yaml').decode('utf-8')
    except zipfile.BadZipFile:
        die({"error": "not_a_zip", "file": file})

    meta = parse_simple_yaml(raw)
    project_kind = meta.get('ProjectKind', '')
    result = {
        "vendor": meta.get('Vendor', ''),
        "name": meta.get('Name', ''),
        "version": meta.get('Version', ''),
        "project_kind": project_kind,
        "technology_version": meta.get('TechnologyVersion', ''),
    }

    if project_kind != 'Library':
        result["error"] = "not_a_library"
        die(result)

    out(result)


# ---------------------------------------------------------------------------
# find-xlib
# ---------------------------------------------------------------------------

def action_find_xlib(directory: str) -> None:
    if not os.path.isdir(directory):
        die({"error": "dir_not_found", "dir": directory})

    found = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        for f in sorted(files):
            if f.endswith('.xlib'):
                found.append(os.path.join(root, f))

    out(found)


# ---------------------------------------------------------------------------
# patch-yaml
# ---------------------------------------------------------------------------

def _build_library_entry(name: str, vendor: str, version: str) -> str:
    return f"    -\n        Имя: {name}\n        Поставщик: {vendor}\n        Версия: {version}\n"


def patch_project_yaml(content: str, name: str, vendor: str, version: str) -> str:
    """Добавить/обновить библиотеку в разделе Библиотеки Проект.yaml."""
    lines = content.splitlines(keepends=True)

    # Найти раздел Библиотеки:
    lib_section_idx = None
    for i, line in enumerate(lines):
        if re.match(r'^Библиотеки:\s*$', line):
            lib_section_idx = i
            break

    if lib_section_idx is None:
        # Раздела нет — дописать в конец
        entry = f"\nБиблиотеки:\n{_build_library_entry(name, vendor, version)}"
        return content.rstrip('\n') + entry + '\n'

    # Найти существующую запись с этим именем и поставщиком
    i = lib_section_idx + 1
    entry_start = None
    version_line_idx = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Новый раздел верхнего уровня — выходим из секции
        if stripped and not stripped.startswith('#') and not stripped.startswith('-') \
                and not line.startswith(' ') and not line.startswith('\t') \
                and i != lib_section_idx:
            break

        if stripped == '-':
            entry_start = i
            entry_name = entry_vendor = None
            j = i + 1
            while j < len(lines) and (lines[j].startswith(' ') or lines[j].startswith('\t')):
                sub = lines[j].strip()
                if sub.startswith('Имя:'):
                    entry_name = sub.split(':', 1)[1].strip()
                elif sub.startswith('Поставщик:'):
                    entry_vendor = sub.split(':', 1)[1].strip()
                elif sub.startswith('Версия:') and entry_name == name and entry_vendor == vendor:
                    version_line_idx = j
                j += 1

        i += 1

    if version_line_idx is not None:
        # Библиотека уже есть — обновить версию
        lines[version_line_idx] = re.sub(r'(Версия:\s*).*', f'\\g<1>{version}', lines[version_line_idx])
        return ''.join(lines)

    # Раздел есть, но библиотеки нет — добавить после последнего элемента раздела
    insert_at = lib_section_idx + 1
    i = lib_section_idx + 1
    while i < len(lines):
        line = lines[i]
        if line.startswith(' ') or line.startswith('\t') or line.strip().startswith('-'):
            insert_at = i + 1
        elif line.strip() and i != lib_section_idx:
            break
        i += 1

    entry_lines = _build_library_entry(name, vendor, version).splitlines(keepends=True)
    for j, entry_line in enumerate(entry_lines):
        lines.insert(insert_at + j, entry_line)

    return ''.join(lines)


def action_patch_yaml(project_yaml: str, name: str, vendor: str, version: str, dry_run: bool) -> None:
    if not os.path.isfile(project_yaml):
        die({"error": "file_not_found", "file": project_yaml})

    with open(project_yaml, encoding='utf-8') as f:
        before = f.read()

    after = patch_project_yaml(before, name, vendor, version)

    if dry_run:
        out({"status": "dry_run", "before": before, "after": after})
        return

    with open(project_yaml, 'w', encoding='utf-8') as f:
        f.write(after)

    out({"status": "patched"})


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

def action_analyze(file: str) -> None:
    if not os.path.isfile(file):
        die({"error": "file_not_found", "file": file})

    tmp_dir = tempfile.mkdtemp(prefix='xlib_analyze_')
    try:
        with zipfile.ZipFile(file) as zf:
            zf.extractall(tmp_dir)

        # Метаданные из Assembly.yaml
        assembly_path = os.path.join(tmp_dir, 'Assembly.yaml')
        meta = {}
        if os.path.isfile(assembly_path):
            with open(assembly_path, encoding='utf-8') as f:
                meta = parse_simple_yaml(f.read())

        subsystems = []
        public_types = []

        for root, dirs, files in os.walk(tmp_dir):
            dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
            for fname in sorted(files):
                if not fname.endswith('.yaml'):
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath, encoding='utf-8') as f:
                    content = f.read()
                fields = parse_simple_yaml(content)
                kind = fields.get('ВидЭлемента', '')

                if kind == 'Подсистема':
                    subsystems.append({
                        "name": fields.get('Имя', ''),
                        "title": fields.get('Представление', ''),
                    })
                elif fields.get('ОбластьВидимости') == 'Глобально' and fields.get('Имя'):
                    public_types.append({
                        "name": fields.get('Имя', ''),
                        "kind": kind,
                    })

        out({
            "vendor": meta.get('Vendor', ''),
            "name": meta.get('Name', ''),
            "subsystems": subsystems,
            "public_types": public_types,
        })
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# validate-version
# ---------------------------------------------------------------------------

def action_validate_version(version: str) -> None:
    if re.fullmatch(r'\d+\.\d+(\.\d+)*', version):
        out({"valid": True})
    else:
        die({"valid": False, "error": "Формат должен быть X.Y.Z, например 1.0.0"})


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

def action_cleanup(directory: str) -> None:
    shutil.rmtree(directory, ignore_errors=True)
    out({"status": "cleaned"})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description='xbsl-lib-connect helper')
    parser.add_argument('--action', required=True,
                        choices=['inspect', 'find-xlib', 'patch-yaml',
                                 'analyze', 'validate-version', 'cleanup'])
    parser.add_argument('--file', help='Путь к .xlib файлу')
    parser.add_argument('--dir', help='Путь к папке')
    parser.add_argument('--project-yaml', help='Путь к Проект.yaml')
    parser.add_argument('--name', help='Имя библиотеки')
    parser.add_argument('--vendor', help='Поставщик библиотеки')
    parser.add_argument('--version', help='Версия библиотеки или релиза')
    parser.add_argument('--dry-run', action='store_true', help='Показать изменения без применения')
    args = parser.parse_args()

    if args.action == 'inspect':
        if not args.file:
            die({"error": "missing_argument", "argument": "--file"})
        action_inspect(args.file)

    elif args.action == 'find-xlib':
        if not args.dir:
            die({"error": "missing_argument", "argument": "--dir"})
        action_find_xlib(args.dir)

    elif args.action == 'patch-yaml':
        for arg, name in [('project_yaml', '--project-yaml'), ('name', '--name'),
                           ('vendor', '--vendor'), ('version', '--version')]:
            if not getattr(args, arg):
                die({"error": "missing_argument", "argument": name})
        action_patch_yaml(args.project_yaml, args.name, args.vendor, args.version, args.dry_run)

    elif args.action == 'analyze':
        if not args.file:
            die({"error": "missing_argument", "argument": "--file"})
        action_analyze(args.file)

    elif args.action == 'validate-version':
        if not args.version:
            die({"error": "missing_argument", "argument": "--version"})
        action_validate_version(args.version)

    elif args.action == 'cleanup':
        if not args.dir:
            die({"error": "missing_argument", "argument": "--dir"})
        action_cleanup(args.dir)


if __name__ == '__main__':
    main()
