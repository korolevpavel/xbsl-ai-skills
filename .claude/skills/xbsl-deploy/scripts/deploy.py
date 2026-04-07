#!/usr/bin/env python3
"""
Полный цикл деплоя на 1С:Предприятие.Элемент.

Два пути деплоя:

  Путь 1 — из исходников (по умолчанию):
    build.py → upload-build → project-update → ожидание Running

  Путь 2 — из git-ветки (--from-branch):
    sync-branch (платформа сама делает git pull) → ожидание Running

Использование:
    python3 deploy.py
    python3 deploy.py --project-dir PATH --app-id ID --project-id ID
    python3 deploy.py --version 1.0-42
    python3 deploy.py --from-branch --branch-id ID
    python3 deploy.py --dry-run

Env vars (обязательные):
    ELEMENT_BASE_URL        — базовый URL (например https://1cmycloud.com)
    ELEMENT_CLIENT_ID       — Client-Id
    ELEMENT_CLIENT_SECRET   — Client-Secret

Env vars (опциональные):
    ELEMENT_APP_ID          — ID приложения
    ELEMENT_PROJECT_ID      — ID проекта (нужен для пути из исходников)
    ELEMENT_BRANCH_ID       — ID ветки на платформе (нужен для --from-branch)
    LAST_BUILD_VERSION      — последняя версия сборки для автоинкремента
"""

import argparse
import json
import os
import subprocess
import sys
import time

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
BUILD_PY = os.path.join(SCRIPTS_DIR, 'build.py')
API_PY = os.path.join(SCRIPTS_DIR, 'api.py')

POLL_INTERVAL = 10   # секунд между опросами статуса
STOP_TIMEOUT = 180   # 3 минуты ждать Stopped
START_TIMEOUT = 300  # 5 минут ждать Running


def run(cmd: list[str], capture: bool = True) -> str:
    """Запустить команду, вернуть stdout или упасть с ошибкой."""
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip()
        print(f'ERROR: {" ".join(cmd[:3])}... failed:\n{msg}', file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def api(action: str, *extra_args) -> dict:
    """Вызвать api.py и вернуть распарсенный JSON."""
    cmd = [sys.executable, API_PY, '--action', action, *extra_args]
    output = run(cmd)
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        print(f'ERROR: api.py returned non-JSON:\n{output}', file=sys.stderr)
        sys.exit(1)


TRANSITIONAL_STATUSES = {'Starting', 'Stopping', 'Initializing', 'Updating', 'Frozen'}


def poll_status(app_id: str, target: str, timeout: int) -> str:
    """Опрашивать статус приложения до target или таймаута."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = api('get-app', '--app-id', app_id)
        status = data.get('status', '')
        print(f'  статус: {status or "(пусто)"}')
        if status == target:
            return status
        if status == 'Error':
            error = data.get('error', '')
            print(f'ERROR: приложение в статусе Error: {error}', file=sys.stderr)
            sys.exit(1)
        time.sleep(POLL_INTERVAL)
    print(f'ERROR: таймаут ожидания статуса {target}', file=sys.stderr)
    sys.exit(1)


def wait_stable(app_id: str, timeout: int) -> str:
    """Ждать пока приложение выйдет из переходного состояния. Вернуть итоговый статус."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = api('get-app', '--app-id', app_id)
        status = data.get('status', '')
        if status and status not in TRANSITIONAL_STATUSES:
            return status
        label = status or '(пусто, ждём...)'
        print(f'  статус: {label} (ждём завершения операции...)')
        time.sleep(POLL_INTERVAL)
    print(f'ERROR: таймаут ожидания стабильного статуса', file=sys.stderr)
    sys.exit(1)


def check_deploy_errors(app_id: str, app_data: dict) -> None:
    """Проверить ошибки применения проекта после достижения Running."""
    app_error = app_data.get('error', '')
    if app_error:
        print(f'\n⚠ Приложение сообщает об ошибке:\n  {app_error}')

    try:
        tasks = api('list-app-tasks', '--app-id', app_id)
        if isinstance(tasks, list):
            error_tasks = [t for t in tasks if t.get('status') == 'Error']
            for t in error_tasks:
                msg = t.get('error-message', '(нет описания)')
                op = t.get('operation-type', '')
                tid = t.get('id', '')
                print(f'\n⚠ Платформа зафиксировала ошибку применения проекта:')
                print(f'  {msg}')
                if op or tid:
                    print(f'  (операция: {op}, задача: {tid})')
    except Exception:
        pass  # не блокируем успешный деплой если задачи недоступны


def get_last_build_version(project_id: str) -> str:
    """Получить версию последней сборки проекта (для автоинкремента)."""
    try:
        data = api('list-builds', '--project-id', project_id)
        items = data if isinstance(data, list) else data.get('items', data.get('assemblies', []))
        versions = [x.get('assembly-version', '') for x in items if x.get('assembly-version')]

        def sort_key(v: str) -> int:
            try:
                return int(v.rsplit('-', 1)[1])
            except (IndexError, ValueError):
                return 0

        versions.sort(key=sort_key)
        return versions[-1] if versions else ''
    except SystemExit:
        return ''


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Deploy 1С:Элемент project: build → upload → update → restart'
    )
    parser.add_argument('--project-dir', help='Путь к каталогу проекта (с Проект.yaml)')
    parser.add_argument('--output', default='/tmp/xasm-build', help='Каталог для .xasm')
    parser.add_argument('--app-id', default=os.environ.get('ELEMENT_APP_ID', ''),
                        help='ID приложения (или ELEMENT_APP_ID)')
    parser.add_argument('--project-id', default=os.environ.get('ELEMENT_PROJECT_ID', ''),
                        help='ID проекта (или ELEMENT_PROJECT_ID)')
    parser.add_argument('--version', help='Полная версия сборки (переопределяет автоинкремент)')
    parser.add_argument('--branch', default='', help='Имя ветки для метаданных сборки')
    parser.add_argument('--commit', default='', help='Хэш коммита для метаданных сборки')
    parser.add_argument('--commit-message', default='', help='Сообщение коммита')
    parser.add_argument('--from-branch', action='store_true',
                        help='Обновить из git-ветки (платформа делает git pull сама)')
    parser.add_argument('--branch-id', default=os.environ.get('ELEMENT_BRANCH_ID', ''),
                        help='ID ветки на платформе для --from-branch (или ELEMENT_BRANCH_ID)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Только собрать .xasm, не деплоить (только для пути из исходников)')
    args = parser.parse_args()

    # — Проверка обязательных параметров
    for var in ('ELEMENT_BASE_URL', 'ELEMENT_CLIENT_ID', 'ELEMENT_CLIENT_SECRET'):
        if not os.environ.get(var):
            print(f'ERROR: не задана переменная окружения {var}', file=sys.stderr)
            sys.exit(1)

    app_id = args.app_id
    project_id = args.project_id

    if not args.dry_run:
        if not app_id:
            print('ERROR: --app-id или ELEMENT_APP_ID обязателен', file=sys.stderr)
            sys.exit(1)
        if args.from_branch:
            if not args.branch_id:
                print('ERROR: --branch-id или ELEMENT_BRANCH_ID обязателен для --from-branch', file=sys.stderr)
                sys.exit(1)
        else:
            if not project_id:
                print('ERROR: --project-id или ELEMENT_PROJECT_ID обязателен', file=sys.stderr)
                sys.exit(1)

    # ── Путь 2: из git-ветки ──────────────────────────────────────────────────
    if args.from_branch:
        print('▶ Загружаем изменения из git-ветки...')
        api('sync-branch', '--app-id', app_id, '--branch-id', args.branch_id)
        print('  ожидаем завершения синхронизации...')
        stable = wait_stable(app_id, START_TIMEOUT)
        print(f'  статус: {stable}')
        if stable != 'Running':
            print('▶ Запускаем приложение...')
            api('start-app', '--app-id', app_id)
            poll_status(app_id, 'Running', START_TIMEOUT)
        app_data = api('get-app', '--app-id', app_id)
        uri = app_data.get('uri', '')
        check_deploy_errors(app_id, app_data)
        print(f'\n✓ Деплой завершён. Приложение доступно: {uri}')
        return

    # ── Путь 1: из исходников ─────────────────────────────────────────────────

    # ── Шаг 1: определить версию ──────────────────────────────────────────────
    print('▶ Определяем версию сборки...')
    if args.version:
        version_args = ['--version', args.version]
        print(f'  версия: {args.version} (задана явно)')
    else:
        last_build = os.environ.get('LAST_BUILD_VERSION', '')
        if not last_build and project_id:
            print('  запрашиваем последнюю сборку из проекта...')
            last_build = get_last_build_version(project_id)
        version_args = ['--last-build', last_build] if last_build else []
        print(f'  последняя сборка: {last_build or "(нет)"}')

    # ── Шаг 2: сборка .xasm ───────────────────────────────────────────────────
    print('▶ Собираем .xasm...')
    build_cmd = [sys.executable, BUILD_PY, '--output', args.output, *version_args]
    if args.project_dir:
        build_cmd += ['--project-dir', args.project_dir]
    if args.commit:
        build_cmd += ['--commit', args.commit]
    if args.branch:
        build_cmd += ['--branch', args.branch]

    xasm_path = run(build_cmd)
    print(f'  файл: {xasm_path}')

    if args.dry_run:
        print('Dry-run завершён. Деплой пропущен.')
        return

    # ── Шаг 3: загрузка сборки ────────────────────────────────────────────────
    print('▶ Загружаем сборку...')
    upload_args = ['--file', xasm_path, '--project-id', project_id]
    if args.branch:
        upload_args += ['--branch-name', args.branch]
    if args.commit:
        upload_args += ['--commit-id', args.commit]
    if args.commit_message:
        upload_args += ['--commit-message', args.commit_message]

    upload_resp = api('upload-build', *upload_args)
    image_id = (upload_resp.get('image-id')
                or upload_resp.get('assembly-id')
                or upload_resp.get('id', ''))
    if not image_id:
        print(f'ERROR: не удалось получить image-id из ответа:\n{upload_resp}', file=sys.stderr)
        sys.exit(1)
    print(f'  image-id: {image_id}')

    # ── Шаг 4: переключить приложение на новую сборку ────────────────────────
    print('▶ Переключаем приложение на новую сборку...')
    api('project-update', '--app-id', app_id, '--version-id', image_id)

    # project-update может сам запустить перезапуск (Updating → Running).
    # Ждём пока выйдет из переходного состояния, смотрим что получилось.
    print('  ожидаем завершения обновления...')
    stable = wait_stable(app_id, START_TIMEOUT)
    print(f'  статус после обновления: {stable}')

    # ── Шаг 5: если не Running — перезапустить вручную ───────────────────────
    if stable == 'Running':
        print('▶ Приложение уже запущено платформой после обновления')
    else:
        if stable != 'Stopped':
            print('▶ Останавливаем приложение...')
            api('stop-app', '--app-id', app_id)
            poll_status(app_id, 'Stopped', STOP_TIMEOUT)
        print('▶ Запускаем приложение...')
        api('start-app', '--app-id', app_id)
        poll_status(app_id, 'Running', START_TIMEOUT)

    # ── Готово ────────────────────────────────────────────────────────────────
    app_data = api('get-app', '--app-id', app_id)
    uri = app_data.get('uri', '')
    check_deploy_errors(app_id, app_data)
    print(f'\n✓ Деплой завершён. Приложение доступно: {uri}')


if __name__ == '__main__':
    main()
