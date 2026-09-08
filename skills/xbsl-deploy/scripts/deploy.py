#!/usr/bin/env python3
"""
Полный цикл деплоя на 1С:Предприятие.Элемент.

Два пути деплоя:

  Путь 1 — из исходников (по умолчанию):
    build.py → upload-build → project-update → ожидание Running

  Путь 2 — из git-ветки (--from-branch):
    sync-branch (платформа сама делает git pull) → ожидание Running

Во всех командах ниже `{python}` означает `python` в Windows и `python3` в macOS/Linux/WSL. Выбирай команду сразу по текущей ОС, не запускай оба варианта.

Использование:
    {python} deploy.py
    {python} deploy.py --project-dir PATH --app-id ID --project-id ID
    {python} deploy.py --version 1.0-42
    {python} deploy.py --from-branch --branch-id ID
    {python} deploy.py --dry-run

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
START_TIMEOUT = 300  # 5 минут ждать Running
TASK_SUCCESS_STATUSES = {'Completed', 'Done'}
TASK_FAILURE_STATUSES = {'Failed', 'Error', 'Cancelled', 'Canceled'}
TASK_PROGRESS_STATUSES = {'Pending', 'Queued', 'InProgress', 'Running'}
APPLICATION_UPDATE_OPERATION = 'UpdateApplicationConfiguration'
DOMAIN_ERROR_ACTIONS = {'get-app', 'get-app-task'}


def fail_deploy(rule_id: str, error: str, details: dict) -> None:
    """Завершить deploy fail-closed со стабильной JSON-диагностикой."""
    print(
        json.dumps(
            {
                'error': error,
                'details': details,
                'rule_id': rule_id,
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    sys.exit(1)


def run(cmd: list[str], capture: bool = True) -> str:
    """Запустить команду, вернуть stdout или упасть с ошибкой."""
    result = subprocess.run(cmd, capture_output=capture, text=True)
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip()
        print(f'ERROR: {" ".join(cmd[:3])}... failed:\n{msg}', file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def api(action: str, *extra_args) -> dict | list:
    """Вызвать api.py и вернуть распарсенный JSON."""
    cmd = [sys.executable, API_PY, '--action', action, *extra_args]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    output = stdout or stderr
    try:
        result = json.loads(output)
    except json.JSONDecodeError:
        fail_deploy(
            'deploy.api_request_failed',
            'Cloud API client returned non-JSON output',
            {
                'action': action,
                'return-code': completed.returncode,
                'output': output,
            },
        )
    if completed.returncode != 0:
        rule_id = (
            result.get('rule_id')
            if isinstance(result, dict)
            and isinstance(result.get('rule_id'), str)
            and result['rule_id'].startswith('deploy.')
            else 'deploy.api_request_failed'
        )
        fail_deploy(
            rule_id,
            'Cloud API client failed',
            {
                'action': action,
                'return-code': completed.returncode,
                'api-error': result.get('error') if isinstance(result, dict) else None,
                'api-details': result.get('details') if isinstance(result, dict) else None,
            },
        )
    is_domain_dto = (
        action in DOMAIN_ERROR_ACTIONS
        and isinstance(result, dict)
        and isinstance(result.get('id'), str)
        and isinstance(result.get('status'), str)
    )
    if isinstance(result, dict) and result.get('error') and not is_domain_dto:
        rule_id = (
            result.get('rule_id')
            if isinstance(result.get('rule_id'), str)
            and result['rule_id'].startswith('deploy.')
            else 'deploy.api_request_failed'
        )
        fail_deploy(
            rule_id,
            'Cloud API request failed',
            {
                'action': action,
                'api-error': result.get('error'),
                'api-details': result.get('details'),
            },
        )
    if not isinstance(result, (dict, list)):
        fail_deploy(
            'deploy.api_request_failed',
            'Cloud API returned an unreadable response',
            {
                'action': action,
                'response-type': type(result).__name__,
            },
        )
    return result


TRANSITIONAL_STATUSES = {'Starting', 'Stopping', 'Initializing', 'Updating', 'Frozen'}
KNOWN_APPLICATION_STATUSES = TRANSITIONAL_STATUSES | {'Running', 'Stopped', 'Error'}


def require_application_state(payload: object, app_id: str) -> dict:
    """Проверить структурную читаемость ответа приложения."""
    if not isinstance(payload, dict):
        fail_deploy(
            'deploy.application_update_unverified',
            'Application state is unreadable',
            {
                'application-id': app_id,
                'response-type': type(payload).__name__,
            },
        )
    source = payload.get('source')
    if source is not None and not isinstance(source, dict):
        fail_deploy(
            'deploy.application_update_unverified',
            'Application source is unreadable',
            {
                'application-id': app_id,
                'source-type': type(source).__name__,
            },
        )
    status = payload.get('status')
    if not isinstance(status, str) or not status:
        fail_deploy(
            'deploy.application_update_unverified',
            'Application status is unreadable',
            {
                'application-id': app_id,
                'status-type': type(status).__name__,
            },
        )
    if status not in KNOWN_APPLICATION_STATUSES:
        fail_deploy(
            'deploy.application_update_unverified',
            'Application returned an unknown status',
            {
                'application-id': app_id,
                'status': status,
            },
        )
    return payload


def poll_status(app_id: str, target: str, timeout: int) -> str:
    """Опрашивать статус приложения до target или таймаута."""
    deadline = time.time() + timeout
    status = ''
    while time.time() < deadline:
        data = require_application_state(
            api('get-app', '--app-id', app_id), app_id
        )
        status = data.get('status', '')
        print(f'  статус: {status or "(пусто)"}')
        if status == 'Error' or data.get('error') is not None:
            fail_deploy(
                'deploy.application_update_failed',
                'Application reported an error while polling status',
                {
                    'application-id': app_id,
                    'status': status,
                    'application-error': data.get('error'),
                    'application-details': data.get('details'),
                },
            )
        if status == target:
            return status
        time.sleep(POLL_INTERVAL)
    fail_deploy(
        'deploy.application_update_unverified',
        'Application status polling timed out',
        {
            'application-id': app_id,
            'expected-status': target,
            'last-status': status,
            'timeout-seconds': timeout,
        },
    )


def wait_stable(app_id: str, timeout: int) -> str:
    """Ждать пока приложение выйдет из переходного состояния. Вернуть итоговый статус."""
    deadline = time.time() + timeout
    status = ''
    while time.time() < deadline:
        data = require_application_state(
            api('get-app', '--app-id', app_id), app_id
        )
        status = data.get('status', '')
        if status == 'Error' or data.get('error') is not None:
            fail_deploy(
                'deploy.application_update_failed',
                'Application update ended with an error',
                {
                    'application-id': app_id,
                    'status': status,
                    'application-error': data.get('error'),
                    'application-details': data.get('details'),
                },
            )
        if status and status not in TRANSITIONAL_STATUSES:
            return status
        label = status or '(пусто, ждём...)'
        print(f'  статус: {label} (ждём завершения операции...)')
        time.sleep(POLL_INTERVAL)
    fail_deploy(
        'deploy.application_update_unverified',
        'Application did not reach a stable status before timeout',
        {
            'application-id': app_id,
            'last-status': status,
            'timeout-seconds': timeout,
        },
    )


def list_application_tasks(app_id: str) -> list[dict]:
    tasks = api('list-app-tasks', '--app-id', app_id)
    if not isinstance(tasks, list):
        fail_deploy(
            'deploy.application_update_unverified',
            'Application task list is unavailable',
            {
                'application-id': app_id,
                'response-type': type(tasks).__name__,
            },
        )
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            fail_deploy(
                'deploy.application_update_unverified',
                'Application task list contains an unreadable item',
                {
                    'application-id': app_id,
                    'item-index': index,
                    'item-type': type(task).__name__,
                },
            )
        task_id = task.get('id')
        if not isinstance(task_id, str) or not task_id:
            fail_deploy(
                'deploy.application_update_unverified',
                'Application task has no stable identifier',
                {
                    'application-id': app_id,
                    'item-index': index,
                    'task-id-type': type(task_id).__name__,
                },
            )
        status = task.get('status')
        if not isinstance(status, str) or not status:
            fail_deploy(
                'deploy.application_update_unverified',
                'Application task status is unreadable',
                {
                    'application-id': app_id,
                    'item-index': index,
                    'task-id': task_id,
                    'status-type': type(status).__name__,
                },
            )
    return tasks


def application_task_ids(app_id: str) -> set[str]:
    return {task['id'] for task in list_application_tasks(app_id)}


def update_task_id(payload: object) -> str:
    """Извлечь ID application task только из явных task-полей ответа."""
    if not isinstance(payload, dict):
        return ''

    for key in ('task-id', 'task_id'):
        candidate = payload.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate

    for key in ('task', 'current-task'):
        candidate = payload.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
        if isinstance(candidate, dict):
            candidate_id = candidate.get('id')
            if isinstance(candidate_id, str) and candidate_id:
                return candidate_id

    if payload.get('operation-type') == APPLICATION_UPDATE_OPERATION:
        candidate = payload.get('id')
        if isinstance(candidate, str) and candidate:
            return candidate
    return ''


def task_failure_details(task: dict) -> dict:
    return {
        'task-id': task.get('id', ''),
        'operation-type': task.get('operation-type', ''),
        'status': task.get('status', ''),
        'error-message': task.get('error-message', ''),
        'error': task.get('error'),
        'details': task.get('details'),
    }


def wait_application_update_task(
    app_id: str,
    baseline_task_ids: set[str],
    timeout: int,
    task_id: str = '',
) -> dict:
    """Найти новую задачу обновления и дождаться её terminal status."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not task_id:
            candidates = [
                task
                for task in list_application_tasks(app_id)
                if task.get('id') not in baseline_task_ids
                and task.get('operation-type') == APPLICATION_UPDATE_OPERATION
            ]
            if len(candidates) > 1:
                fail_deploy(
                    'deploy.application_update_unverified',
                    'Application update task is ambiguous',
                    {
                        'application-id': app_id,
                        'candidate-task-ids': sorted(task['id'] for task in candidates),
                    },
                )
            if candidates:
                task_id = candidates[0]['id']

        if task_id:
            task = api('get-app-task', '--task-id', task_id)
            if not isinstance(task, dict):
                fail_deploy(
                    'deploy.application_update_unverified',
                    'Application update task is unreadable',
                    {
                        'application-id': app_id,
                        'task-id': task_id,
                        'response-type': type(task).__name__,
                    },
                )
            actual_task_id = task.get('id')
            if actual_task_id != task_id:
                fail_deploy(
                    'deploy.application_update_unverified',
                    'Application update task identity does not match',
                    {
                        'application-id': app_id,
                        'expected-task-id': task_id,
                        'actual-task-id': actual_task_id,
                    },
                )
            operation_type = task.get('operation-type')
            if operation_type != APPLICATION_UPDATE_OPERATION:
                fail_deploy(
                    'deploy.application_update_unverified',
                    'Application update task has an unexpected operation type',
                    {
                        'application-id': app_id,
                        'task-id': task_id,
                        'operation-type': operation_type,
                    },
                )
            status = task.get('status', '')
            if not isinstance(status, str) or not status:
                fail_deploy(
                    'deploy.application_update_unverified',
                    'Application update task status is unreadable',
                    {
                        'application-id': app_id,
                        'task-id': task_id,
                        'status-type': type(status).__name__,
                    },
                )
            if status in TASK_SUCCESS_STATUSES:
                return task
            if status in TASK_FAILURE_STATUSES:
                fail_deploy(
                    'deploy.application_update_failed',
                    'Application update task failed',
                    task_failure_details(task),
                )
            print(f'  задача {task_id}: {status or "(пусто)"}')

        time.sleep(POLL_INTERVAL)

    fail_deploy(
        'deploy.application_update_unverified',
        'Application update task was not completed before timeout',
        {
            'application-id': app_id,
            'task-id': task_id,
            'timeout-seconds': timeout,
        },
    )


def verify_application_state(
    app_data: object,
    expected_version_id: str | None = None,
) -> None:
    """Проверить terminal state и точную активную сборку приложения."""
    app_data = require_application_state(app_data, '')
    if 'error' not in app_data:
        fail_deploy(
            'deploy.application_update_unverified',
            'Application error field is missing after update',
            {'error-field-present': False},
        )
    app_error = app_data.get('error')
    if app_error is not None:
        fail_deploy(
            'deploy.application_update_failed',
            'Application error state is not clean after update',
            {
                'error-field-present': True,
                'application-error': app_error,
                'application-details': app_data.get('details'),
            },
        )

    status = app_data.get('status', '')
    current_task = app_data.get('current-task')
    source = app_data.get('source')
    actual_version_id = (source or {}).get('project-version-id')
    details = {
        'status': status,
        'current-task': current_task,
        'expected-version-id': expected_version_id,
        'actual-version-id': actual_version_id,
    }
    if (
        status != 'Running'
        or 'current-task' not in app_data
        or current_task is not None
    ):
        fail_deploy(
            'deploy.application_update_unverified',
            'Application did not reach a clean Running state',
            {
                **details,
                'current-task-field-present': 'current-task' in app_data,
            },
        )
    if expected_version_id and actual_version_id != expected_version_id:
        fail_deploy(
            'deploy.application_update_unverified',
            'Application is still running another project version',
            details,
        )


def check_deploy_errors(
    app_id: str,
    app_data: object,
    baseline_task_ids: set[str] | None = None,
    expected_version_id: str | None = None,
) -> None:
    """Проверить ошибки применения проекта после достижения Running.

    baseline_task_ids — снимок ID до update; проверяем только появившиеся задачи.
    """
    verify_application_state(app_data, expected_version_id=expected_version_id)
    new_tasks = [
        task
        for task in list_application_tasks(app_id)
    ]
    if baseline_task_ids is not None:
        new_tasks = [
            task
            for task in new_tasks
            if task['id'] not in baseline_task_ids
        ]
    error_tasks = [
        task for task in new_tasks if task['status'] in TASK_FAILURE_STATUSES
    ]
    if error_tasks:
        error_tasks.sort(
            key=lambda task: _parse_iso(task.get('start-date', '')),
            reverse=True,
        )
        fail_deploy(
            'deploy.application_update_failed',
            'Platform recorded a failed application task',
            task_failure_details(error_tasks[0]),
        )
    nonterminal_tasks = [
        task for task in new_tasks if task['status'] not in TASK_SUCCESS_STATUSES
    ]
    if nonterminal_tasks:
        task = nonterminal_tasks[0]
        fail_deploy(
            'deploy.application_update_unverified',
            'A new application task has no successful terminal status',
            {
                'task-id': task['id'],
                'operation-type': task.get('operation-type', ''),
                'status': task['status'],
                'known-progress-status': task['status'] in TASK_PROGRESS_STATUSES,
            },
        )


def _parse_iso(s: str) -> float:
    """Преобразовать ISO 8601 строку в unix-timestamp. Возвращает 0.0 при ошибке."""
    try:
        import datetime
        dt = datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
        return dt.timestamp()
    except Exception:
        return 0.0


def get_last_build_version(project_id: str) -> str:
    """Получить версию последней сборки проекта (для автоинкремента)."""
    data = api('list-builds', '--project-id', project_id)
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        if 'items' in data:
            items = data['items']
        elif 'assemblies' in data:
            items = data['assemblies']
        else:
            fail_deploy(
                'deploy.api_request_failed',
                'Build list has an unknown response shape',
                {'project-id': project_id},
            )
    else:
        fail_deploy(
            'deploy.api_request_failed',
            'Build list is unreadable',
            {'project-id': project_id, 'response-type': type(data).__name__},
        )
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        fail_deploy(
            'deploy.api_request_failed',
            'Build list is unreadable',
            {'project-id': project_id},
        )
    versions = []
    for index, item in enumerate(items):
        version = item.get('assembly-version')
        if not isinstance(version, str) or not version:
            fail_deploy(
                'deploy.api_request_failed',
                'Build version is unreadable',
                {
                    'project-id': project_id,
                    'item-index': index,
                    'version-type': type(version).__name__,
                },
            )
        versions.append(version)

    def sort_key(v: str) -> int:
        try:
            return int(v.rsplit('-', 1)[1])
        except (AttributeError, IndexError, ValueError):
            return 0

    versions.sort(key=sort_key)
    return versions[-1] if versions else ''


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
        baseline_task_ids = application_task_ids(app_id)
        update_response = api(
            'sync-branch', '--app-id', app_id, '--branch-id', args.branch_id
        )
        task_id = update_task_id(update_response)
        if not task_id:
            task_id = update_task_id(api('get-app', '--app-id', app_id))
        if task_id in baseline_task_ids:
            task_id = ''
        print('  ожидаем terminal status задачи обновления...')
        wait_application_update_task(
            app_id,
            baseline_task_ids,
            START_TIMEOUT,
            task_id=task_id,
        )
        print('  ожидаем завершения синхронизации...')
        stable = wait_stable(app_id, START_TIMEOUT)
        print(f'  статус: {stable}')
        if stable != 'Running':
            print('▶ Запускаем приложение...')
            api('start-app', '--app-id', app_id)
            poll_status(app_id, 'Running', START_TIMEOUT)
        app_data = api('get-app', '--app-id', app_id)
        check_deploy_errors(
            app_id,
            app_data,
            baseline_task_ids=baseline_task_ids,
        )
        uri = app_data.get('uri', '')
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
    if not isinstance(upload_resp, dict):
        fail_deploy(
            'deploy.api_request_failed',
            'Build upload response is unreadable',
            {'response-type': type(upload_resp).__name__},
        )
    image_id = (upload_resp.get('image-id')
                or upload_resp.get('assembly-id')
                or upload_resp.get('id', ''))
    if not isinstance(image_id, str) or not image_id:
        fail_deploy(
            'deploy.api_request_failed',
            'Build upload response has no image identifier',
            {
                'response-keys': sorted(str(key) for key in upload_resp),
                'image-id-type': type(image_id).__name__,
            },
        )
    print(f'  image-id: {image_id}')

    # ── Шаг 4: переключить приложение на новую сборку ────────────────────────
    print('▶ Переключаем приложение на новую сборку...')
    baseline_task_ids = application_task_ids(app_id)
    update_response = api(
        'project-update', '--app-id', app_id, '--version-id', image_id
    )
    task_id = update_task_id(update_response)
    if not task_id:
        task_id = update_task_id(api('get-app', '--app-id', app_id))
    if task_id in baseline_task_ids:
        task_id = ''
    print('  ожидаем terminal status задачи обновления...')
    wait_application_update_task(
        app_id,
        baseline_task_ids,
        START_TIMEOUT,
        task_id=task_id,
    )

    # project-update может сам запустить перезапуск (Updating → Running).
    # Ждём пока выйдет из переходного состояния, смотрим что получилось.
    print('  ожидаем завершения обновления...')
    stable = wait_stable(app_id, START_TIMEOUT)
    print(f'  статус после обновления: {stable}')

    # ── Шаг 5: если не Running — перезапустить вручную ───────────────────────
    if stable == 'Running':
        print('▶ Приложение уже запущено платформой после обновления')
    else:
        print('▶ Запускаем приложение...')
        api('start-app', '--app-id', app_id)
        poll_status(app_id, 'Running', START_TIMEOUT)

    # ── Готово ────────────────────────────────────────────────────────────────
    app_data = api('get-app', '--app-id', app_id)
    check_deploy_errors(
        app_id,
        app_data,
        baseline_task_ids=baseline_task_ids,
        expected_version_id=image_id,
    )
    uri = app_data.get('uri', '')
    print(f'\n✓ Деплой завершён. Приложение доступно: {uri}')


if __name__ == '__main__':
    main()
