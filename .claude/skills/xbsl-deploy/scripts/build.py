#!/usr/bin/env python3
"""
Сборка .xasm файла для загрузки в 1С:Предприятие.Элемент.

.xasm — ZIP-архив, содержащий:
  - Assembly.yaml          (манифест, корень архива)
  - {vendor}/{name}/...    (файлы проекта: .yaml, .xbsl, .md)

Использование:
    python3 build.py [--project-dir PATH] [--output DIR]
                     [--version VER] [--last-build VER]
                     [--commit HASH] [--branch NAME]

Примеры:
    python3 build.py
    python3 build.py --last-build 1.0-20 --output /tmp
    python3 build.py --version 1.0-21 --output /tmp

Env vars:
    LAST_BUILD_VERSION  — последняя версия сборки (для автоинкремента)
"""

import argparse
import datetime
import os
import subprocess
import sys
import zipfile

# Расширения файлов, включаемых в сборку
INCLUDE_EXTENSIONS = {'.yaml', '.xbsl', '.xbql', '.md', '.txt'}

# Каталоги и файлы, исключаемые из сборки
EXCLUDE_DIRS = {'.claude', '.git', '__pycache__', 'node_modules', '.github'}
EXCLUDE_FILES = {'.gitignore', '.env', '.DS_Store'}


def find_project_dir(start: str) -> str | None:
    """Найти каталог, содержащий Проект.yaml."""
    for root, dirs, files in os.walk(start):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.'))
        if 'Проект.yaml' in files:
            return root
    return None


def parse_simple_yaml(path: str) -> dict:
    """Минимальный парсер YAML: читает пары key: value."""
    result = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if ':' in line and not line.startswith('#'):
                key, _, val = line.partition(':')
                result[key.strip()] = val.strip().strip('"').strip("'")
    return result


def git_info(cwd: str) -> tuple[str, str]:
    """Вернуть (commit_hash, branch_name) из git."""
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            cwd=cwd, text=True, stderr=subprocess.DEVNULL
        ).strip()
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=cwd, text=True, stderr=subprocess.DEVNULL
        ).strip()
        return commit, branch
    except (subprocess.CalledProcessError, FileNotFoundError):
        return '', 'master'


def should_include(rel_path: str) -> bool:
    """Включить файл в архив?"""
    parts = rel_path.replace('\\', '/').split('/')
    if any(p in EXCLUDE_DIRS or p.startswith('.') for p in parts):
        return False
    filename = parts[-1]
    if filename in EXCLUDE_FILES or filename.endswith('.xasm'):
        return False
    ext = os.path.splitext(filename)[1].lower()
    return ext in INCLUDE_EXTENSIONS


def next_version(base_version: str, last_build: str) -> str:
    """Вычислить следующую версию: {base}-{N+1}."""
    if last_build and '-' in last_build:
        try:
            counter = int(last_build.rsplit('-', 1)[1]) + 1
            return f"{base_version}-{counter}"
        except ValueError:
            pass
    return f"{base_version}-1"


def build_xasm(project_dir: str, output_dir: str,
               version: str, commit: str, branch: str) -> str:
    """
    Собрать .xasm архив из файлов проекта.

    Структура архива:
        Assembly.yaml
        {vendor}/{name}/Проект.yaml
        {vendor}/{name}/Проект.xbsl
        {vendor}/{name}/Основное/*.yaml
        ...
    """
    # project_dir = .../repo/vendor/project_name
    # vendor_dir  = .../repo/vendor
    # repo_dir    = .../repo  (корень: архивные пути от него)
    vendor_dir = os.path.dirname(project_dir)
    repo_dir = os.path.dirname(vendor_dir)

    meta = parse_simple_yaml(os.path.join(project_dir, 'Проект.yaml'))
    vendor = meta.get('Поставщик', os.path.basename(vendor_dir))
    name = meta.get('Имя', os.path.basename(project_dir))

    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y.%m.%d %H:%M:%S')
    assembly_yaml = (
        f"ManifestVersion: 1.0\n"
        f"ProjectKind: Application\n"
        f"Vendor: {vendor}\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
        f"Created: {now}\n"
        f"BranchName: {branch}\n"
        f"CommitId: {commit}\n"
    )

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{name} {version}.xasm")

    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Манифест — в корне архива
        zf.writestr('Assembly.yaml', assembly_yaml)

        # Файлы проекта — с путями относительно корня репозитория
        for root, dirs, files in os.walk(project_dir):
            dirs[:] = sorted(d for d in dirs
                             if d not in EXCLUDE_DIRS and not d.startswith('.'))
            for filename in sorted(files):
                filepath = os.path.join(root, filename)
                rel = os.path.relpath(filepath, repo_dir).replace('\\', '/')
                if should_include(rel):
                    zf.write(filepath, rel)

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description='Build .xasm assembly for 1С:Предприятие.Элемент'
    )
    parser.add_argument(
        '--project-dir',
        help='Путь к каталогу проекта (с Проект.yaml). По умолчанию — автопоиск.'
    )
    parser.add_argument(
        '--output', default='.',
        help='Каталог для сохранения .xasm (default: .)'
    )
    parser.add_argument(
        '--version',
        help='Полная версия сборки, например 1.0-21 (переопределяет автоинкремент)'
    )
    parser.add_argument(
        '--last-build',
        default=os.environ.get('LAST_BUILD_VERSION', ''),
        help='Последняя версия сборки для автоинкремента, например 1.0-20'
    )
    parser.add_argument('--commit', help='Переопределить git commit hash')
    parser.add_argument('--branch', help='Переопределить имя ветки')
    args = parser.parse_args()

    # — Найти каталог проекта
    project_dir = args.project_dir
    if not project_dir:
        project_dir = find_project_dir('.')
    if not project_dir or not os.path.isfile(os.path.join(project_dir, 'Проект.yaml')):
        print('ERROR: Проект.yaml not found. Use --project-dir', file=sys.stderr)
        sys.exit(1)
    project_dir = os.path.abspath(project_dir)

    # — Git-метаданные
    repo_dir = os.path.dirname(os.path.dirname(project_dir))
    commit, branch = git_info(repo_dir)
    if args.commit:
        commit = args.commit
    if args.branch:
        branch = args.branch

    # — Версия
    meta = parse_simple_yaml(os.path.join(project_dir, 'Проект.yaml'))
    base_version = meta.get('Версия', '1.0')
    version = args.version or next_version(base_version, args.last_build)

    # — Сборка
    output_path = build_xasm(project_dir, args.output, version, commit, branch)

    # Вывод пути — используется скриптами и CI
    print(output_path)


if __name__ == '__main__':
    main()
