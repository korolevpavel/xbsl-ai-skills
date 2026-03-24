#!/usr/bin/env python3
"""
HTTP-клиент для Console API v2 (1С:Предприятие.Элемент / 1cmycloud.com).
Все зависимости — только стандартная библиотека Python.

Использование:
    python3 api.py --action get-token
    python3 api.py --action list-apps
    python3 api.py --action get-app --app-id <id>
    python3 api.py --action create-app --name <name>
    python3 api.py --action start-app --app-id <id>
    python3 api.py --action stop-app --app-id <id>
    python3 api.py --action delete-app --app-id <id>
    python3 api.py --action list-projects
    python3 api.py --action list-branches --project-id <id> [--branch-name <name>]
    python3 api.py --action get-branch --branch-id <id>
    python3 api.py --action create-branch --project-id <id> --branch-name <name> [--app-id <id>]
    python3 api.py --action update-branch --branch-id <id> [--app-id <id>]
    python3 api.py --action delete-branch --branch-id <id>
    python3 api.py --action create-dump --app-id <id>
    python3 api.py --action get-dump --app-id <id> --dump-id <id>
    python3 api.py --action merge-branch --branch-id <id>

Env vars (приоритет над флагами):
    ELEMENT_BASE_URL       — базовый URL (например https://1cmycloud.com)
    ELEMENT_CLIENT_ID      — Client-Id для получения токена
    ELEMENT_CLIENT_SECRET  — Client-Secret для получения токена
    ELEMENT_APP_ID         — ID приложения по умолчанию
    ELEMENT_PROJECT_ID     — ID проекта по умолчанию
    ELEMENT_BRANCH         — имя ветки по умолчанию (default: main)
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# TTL кеша токена в секундах
TOKEN_TTL = 3600


def get_token_cache_path(base_url: str, client_id: str) -> str:
    h = hashlib.md5(f"{base_url}:{client_id}".encode()).hexdigest()[:8]
    return f"/tmp/element_token_{h}.json"


def load_cached_token(cache_path: str) -> str | None:
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
        if time.time() < data.get("expires_at", 0):
            return data["token"]
    except (OSError, KeyError, json.JSONDecodeError):
        pass
    return None


def save_token_cache(cache_path: str, token: str) -> None:
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"token": token, "expires_at": time.time() + TOKEN_TTL}, f)
    except OSError:
        pass


def fetch_token(base_url: str, client_id: str, client_secret: str) -> str:
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    url = f"{base_url}/console/sys/token"
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        data=b"{}",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode())
            # API возвращает токен в поле token или access_token
            token = body.get("token") or body.get("access_token") or body.get("value")
            if not token:
                # Если поле не нашли — вернуть весь ответ для диагностики
                return json.dumps({"error": "token field not found", "response": body}, ensure_ascii=False)
            return token
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return json.dumps({"error": f"HTTP {e.code}", "details": body}, ensure_ascii=False)


def get_token(args) -> str:
    base_url = args.base_url
    client_id = args.client_id
    client_secret = args.client_secret

    cache_path = get_token_cache_path(base_url, client_id)
    cached = load_cached_token(cache_path)
    if cached:
        return cached

    token = fetch_token(base_url, client_id, client_secret)
    save_token_cache(cache_path, token)
    return token


def api_request(method: str, url: str, token: str, body: dict | None = None) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if data:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            err_body = json.loads(raw)
        except json.JSONDecodeError:
            err_body = raw
        return {"error": f"HTTP {e.code}", "details": err_body}


def main():
    parser = argparse.ArgumentParser(description="Console API v2 client")
    parser.add_argument("--action", required=True)
    parser.add_argument("--base-url", default=os.environ.get("ELEMENT_BASE_URL", ""))
    parser.add_argument("--client-id", default=os.environ.get("ELEMENT_CLIENT_ID", ""))
    parser.add_argument("--client-secret", default=os.environ.get("ELEMENT_CLIENT_SECRET", ""))
    parser.add_argument("--app-id", default=os.environ.get("ELEMENT_APP_ID", ""))
    parser.add_argument("--project-id", default=os.environ.get("ELEMENT_PROJECT_ID", ""))
    parser.add_argument("--branch-id", default="")
    parser.add_argument("--branch-name", default=os.environ.get("ELEMENT_BRANCH", "main"))
    parser.add_argument("--name", default="")
    parser.add_argument("--space-id", default=os.environ.get("ELEMENT_SPACE_ID", ""))
    parser.add_argument("--dump-id", default="")
    args = parser.parse_args()

    if not args.base_url:
        print(json.dumps({"error": "ELEMENT_BASE_URL not set"}, ensure_ascii=False))
        sys.exit(1)

    action = args.action
    base = args.base_url.rstrip("/")

    # get-token: не требует существующего токена
    if action == "get-token":
        if not args.client_id or not args.client_secret:
            print(json.dumps({"error": "ELEMENT_CLIENT_ID / ELEMENT_CLIENT_SECRET not set"}, ensure_ascii=False))
            sys.exit(1)
        token = get_token(args)
        print(json.dumps({"token": token}, ensure_ascii=False))
        return

    # Все остальные действия требуют токена
    if not args.client_id or not args.client_secret:
        print(json.dumps({"error": "ELEMENT_CLIENT_ID / ELEMENT_CLIENT_SECRET not set"}, ensure_ascii=False))
        sys.exit(1)
    token = get_token(args)

    # ── Приложения ─────────────────────────────────────────────────────────────

    if action == "list-apps":
        url = f"{base}/console/api/v2/applications"
        if args.name:
            url += f"?name={urllib.parse.quote(args.name)}"
        result = api_request("GET", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "get-app":
        if not args.app_id:
            print(json.dumps({"error": "--app-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/applications/{args.app_id}"
        result = api_request("GET", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "create-app":
        if not args.name:
            print(json.dumps({"error": "--name required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/applications"
        body = {
            "source": {"type": "repository"},
            "display-name": args.name,
            "publication-context": args.name,
            "development-mode": False,
        }
        if args.space_id:
            body["space-id"] = args.space_id
        result = api_request("POST", url, token, body)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "delete-app":
        if not args.app_id:
            print(json.dumps({"error": "--app-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/applications/{args.app_id}"
        result = api_request("DELETE", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "start-app":
        if not args.app_id:
            print(json.dumps({"error": "--app-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/applications/{args.app_id}/status/start"
        result = api_request("PUT", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "stop-app":
        if not args.app_id:
            print(json.dumps({"error": "--app-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/applications/{args.app_id}/status/stop"
        result = api_request("PUT", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ── Проекты ────────────────────────────────────────────────────────────────

    elif action == "list-projects":
        url = f"{base}/console/api/v2/projects"
        result = api_request("GET", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ── Ветки ──────────────────────────────────────────────────────────────────

    elif action == "list-branches":
        params = {}
        if args.project_id:
            params["project-id"] = args.project_id
        if args.branch_name:
            params["name"] = args.branch_name
        qs = urllib.parse.urlencode(params)
        url = f"{base}/console/api/v2/branches?{qs}" if qs else f"{base}/console/api/v2/branches"
        result = api_request("GET", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "get-branch":
        if not args.branch_id:
            print(json.dumps({"error": "--branch-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/branches/{args.branch_id}"
        result = api_request("GET", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "create-branch":
        if not args.project_id or not args.branch_name:
            print(json.dumps({"error": "--project-id and --branch-name required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/branches"
        body: dict = {
            "name": args.branch_name,
            "kind": "development",
            "project-id": args.project_id,
        }
        if args.app_id:
            body["application"] = {"id": args.app_id}
        result = api_request("POST", url, token, body)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "update-branch":
        if not args.branch_id:
            print(json.dumps({"error": "--branch-id required"}, ensure_ascii=False))
            sys.exit(1)
        # Сначала получаем текущие данные ветки (нужны name и version-stamp)
        url_get = f"{base}/console/api/v2/branches/{args.branch_id}"
        current = api_request("GET", url_get, token)
        if "error" in current:
            print(json.dumps(current, ensure_ascii=False, indent=2))
            sys.exit(1)
        body = {
            "name": current.get("name", args.branch_name),
        }
        if current.get("version-stamp"):
            body["version-stamp"] = current["version-stamp"]
        if args.app_id:
            body["application"] = {"id": args.app_id}
        url = f"{base}/console/api/v2/branches/{args.branch_id}"
        result = api_request("PUT", url, token, body)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "delete-branch":
        if not args.branch_id:
            print(json.dumps({"error": "--branch-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/branches/{args.branch_id}"
        result = api_request("DELETE", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "merge-branch":
        if not args.branch_id:
            print(json.dumps({"error": "--branch-id required"}, ensure_ascii=False))
            sys.exit(1)
        # Получаем текущие данные ветки для оптимистической блокировки
        url_get = f"{base}/console/api/v2/branches/{args.branch_id}"
        current = api_request("GET", url_get, token)
        if "error" in current:
            print(json.dumps(current, ensure_ascii=False, indent=2))
            sys.exit(1)
        body = {
            "name": current.get("name", args.branch_name),
            "write-parameters": {"merge": True},
        }
        if current.get("version-stamp"):
            body["version-stamp"] = current["version-stamp"]
        url = f"{base}/console/api/v2/branches/{args.branch_id}"
        result = api_request("PUT", url, token, body)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ── Дампы ──────────────────────────────────────────────────────────────────

    elif action == "create-dump":
        if not args.app_id:
            print(json.dumps({"error": "--app-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/applications/{args.app_id}/dumps"
        body = {
            "include-users": False,
            "include-binary-data": False,
            "description": "auto-dump before deploy",
        }
        result = api_request("POST", url, token, body)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "get-dump":
        if not args.app_id or not args.dump_id:
            print(json.dumps({"error": "--app-id and --dump-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/applications/{args.app_id}/dumps/{args.dump_id}"
        result = api_request("GET", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print(json.dumps({"error": f"Unknown action: {action}"}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
