#!/usr/bin/env python3
"""
HTTP-клиент для Console API v2 (1С:Предприятие.Элемент / 1cmycloud.com).
Все зависимости — только стандартная библиотека Python.

Во всех командах ниже `{python}` означает `python` в Windows и `python3` в macOS/Linux/WSL. Выбирай команду сразу по текущей ОС, не запускай оба варианта.

Использование:
    {python} api.py --action get-token
    {python} api.py --action list-apps
    {python} api.py --action get-app --app-id <id>
    {python} api.py --action create-app --name <name> [--project-id <id>] [--version-id <build-id>]
    {python} api.py --action start-app --app-id <id>
    {python} api.py --action stop-app --app-id <id>
    {python} api.py --action delete-app --app-id <id>
    {python} api.py --action list-spaces
    {python} api.py --action list-projects
    {python} api.py --action get-project --project-id <id>
    {python} api.py --action delete-project --project-id <id>
    {python} api.py --action upload-build --file <path> [--project-id <id>] [--space-id <id>] [--branch-name <name>] [--commit-id <hash>] [--commit-message <msg>]
    {python} api.py --action list-builds --project-id <id>
    {python} api.py --action get-build --project-id <id> --version <ver>
    {python} api.py --action delete-build --project-id <id> --version <ver>
    {python} api.py --action project-update --app-id <id> --version-id <assembly-id>
    {python} api.py --action sync-branch --app-id <id> --branch-id <id>
    {python} api.py --action list-branches --project-id <id> [--branch-name <name>]
    {python} api.py --action get-branch --branch-id <id>
    {python} api.py --action create-branch --project-id <id> --branch-name <name> [--app-id <id>]
    {python} api.py --action update-branch --branch-id <id> [--app-id <id>]
    {python} api.py --action delete-branch --branch-id <id>
    {python} api.py --action create-dump --app-id <id>
    {python} api.py --action get-dump --app-id <id> --dump-id <id>
    {python} api.py --action merge-branch --branch-id <id>
    {python} api.py --action list-app-tasks --app-id <id>
    {python} api.py --action get-app-task --task-id <id>
    {python} api.py --action get-technology-version --app-id <id>
    {python} api.py --action update-technology-version --app-id <id> --technology-version <version>

Env vars (приоритет над флагами):
    ELEMENT_BASE_URL       — базовый URL (например https://1cmycloud.com)
    ELEMENT_CLIENT_ID      — Client-Id для получения токена
    ELEMENT_CLIENT_SECRET  — Client-Secret для получения токена
    ELEMENT_APP_ID         — ID приложения по умолчанию
    ELEMENT_PROJECT_ID     — ID проекта по умолчанию
    ELEMENT_BRANCH         — имя ветки по умолчанию (default: main)
    ELEMENT_BRANCH_ID      — ID ветки для sync-branch (внутренний ID ветки на платформе)
    ELEMENT_SPACE_ID       — ID пространства (если не задан — определяется автоматически через list-spaces)
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

# TTL кеша токена в секундах
TOKEN_TTL = 3600
ASSEMBLY_MANIFEST_MAX_BYTES = 64 * 1024
IDENTITY_CONFLICT_RULE_ID = "deploy.project_identity_conflict"
IDENTITY_PREFLIGHT_RULE_ID = "deploy.project_identity_preflight_failed"
TECHNOLOGY_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+-[0-9]+$")


class TokenFetchError(Exception):
    def __init__(self, payload: dict):
        super().__init__(payload.get("error", "token fetch error"))
        self.payload = payload


class IdentityPreflightError(Exception):
    """Безопасная диагностическая ошибка preflight без сырых ответов API."""


def build_error(error: str, details=None, response=None) -> dict:
    payload = {"error": error}
    if details is not None:
        payload["details"] = details
    if response is not None:
        payload["response"] = response
    return payload


def identity_preflight_error(details: str) -> dict:
    return {
        "error": "Project identity preflight failed",
        "details": details,
        "rule_id": IDENTITY_PREFLIGHT_RULE_ID,
    }


def identity_conflict_error(vendor: str, name: str, project_ids: list[str]) -> dict:
    ids = sorted(set(project_ids))
    return {
        "error": "Project identity conflict",
        "details": (
            "Existing project assembly metadata contains the exact Vendor + Name identity. "
            "Inspect the listed project(s), then repeat with an explicit --project-id only if "
            "the selected project is correct; automatic selection is forbidden."
        ),
        "rule_id": IDENTITY_CONFLICT_RULE_ID,
        "identity": {"vendor": vendor, "name": name},
        "project-ids": ids,
    }


def safe_api_error(response, fallback: str) -> str:
    """Вернуть только безопасное поле error, не копируя details/response с секретами."""
    if isinstance(response, dict) and isinstance(response.get("error"), str):
        return response["error"]
    return fallback


def api_collection(response, wrapper_keys: tuple[str, ...]) -> list | None:
    if isinstance(response, list):
        return response
    if not isinstance(response, dict) or "error" in response:
        return None
    for key in wrapper_keys:
        value = response.get(key)
        if isinstance(value, list):
            return value
    return None


def parse_manifest_value(raw_value: str) -> str:
    """Разобрать безопасный строковый YAML scalar и отбросить inline comment."""
    value = raw_value.strip()
    if not value:
        return ""
    if value.startswith('"'):
        try:
            parsed, end = json.JSONDecoder().raw_decode(value)
        except json.JSONDecodeError as error:
            raise IdentityPreflightError("Assembly.yaml contains invalid quoted identity") from error
        if not isinstance(parsed, str):
            raise IdentityPreflightError("Assembly.yaml identity must be a string")
        remainder = value[end:].strip()
        if remainder and not remainder.startswith("#"):
            raise IdentityPreflightError("Assembly.yaml contains trailing identity data")
        return parsed
    if value.startswith("'"):
        characters: list[str] = []
        index = 1
        while index < len(value):
            if value[index] != "'":
                characters.append(value[index])
                index += 1
                continue
            if index + 1 < len(value) and value[index + 1] == "'":
                characters.append("'")
                index += 2
                continue
            remainder = value[index + 1:].strip()
            if remainder and not remainder.startswith("#"):
                raise IdentityPreflightError("Assembly.yaml contains trailing identity data")
            return "".join(characters)
        raise IdentityPreflightError("Assembly.yaml contains invalid quoted identity")

    for index, character in enumerate(value):
        if character == "#" and index > 0 and value[index - 1].isspace():
            value = value[:index].rstrip()
            break
    return value


def read_assembly_identity(file_path: str) -> tuple[str, str]:
    """Прочитать точную пару Vendor + Name из корневого Assembly.yaml."""
    try:
        with zipfile.ZipFile(file_path) as archive:
            manifests = [info for info in archive.infolist() if info.filename == "Assembly.yaml"]
            if not manifests:
                raise IdentityPreflightError("Assembly.yaml is missing at archive root")
            if len(manifests) != 1:
                raise IdentityPreflightError("Archive contains duplicate Assembly.yaml entries")
            manifest_info = manifests[0]
            if manifest_info.file_size > ASSEMBLY_MANIFEST_MAX_BYTES:
                raise IdentityPreflightError("Assembly.yaml is too large")
            manifest = archive.read(manifest_info).decode("utf-8-sig")
    except IdentityPreflightError:
        raise
    except Exception as error:
        raise IdentityPreflightError(f"Cannot read Assembly.yaml: {type(error).__name__}") from error

    values: dict[str, str] = {}
    for line in manifest.splitlines():
        if not line or line[0].isspace() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        if key not in ("Vendor", "Name"):
            continue
        value = parse_manifest_value(raw_value)
        if not value:
            raise IdentityPreflightError(f"Assembly.yaml field {key} is empty")
        if not value.isidentifier():
            raise IdentityPreflightError(f"Assembly.yaml field {key} is not a valid identifier")
        if key in values:
            raise IdentityPreflightError(f"Assembly.yaml contains duplicate {key} fields")
        values[key] = value

    missing = [key for key in ("Vendor", "Name") if key not in values]
    if missing:
        raise IdentityPreflightError(
            "Assembly.yaml is missing required identity field(s): " + ", ".join(missing)
        )
    return values["Vendor"], values["Name"]


def assembly_identity(record: dict) -> tuple[str, str] | None:
    vendor = record.get("project-developer")
    name = record.get("project-name")
    if isinstance(vendor, str) and vendor and isinstance(name, str) and name:
        return vendor, name
    return None


def find_project_identity_conflicts(
    base: str,
    token: str,
    space_id: str,
    target_identity: tuple[str, str],
) -> list[str]:
    projects_url = f"{base}/console/api/v2/projects"
    projects_response = api_request("GET", projects_url, token)
    projects = api_collection(projects_response, ("items", "projects"))
    if projects is None:
        reason = safe_api_error(projects_response, "unexpected list-projects response")
        raise IdentityPreflightError(f"Cannot list projects: {reason}")

    conflicts: list[str] = []
    seen_project_ids: set[str] = set()
    for project in projects:
        if not isinstance(project, dict):
            raise IdentityPreflightError("Cannot inspect project identity: malformed project record")
        if str(project.get("project-kind", "")).casefold() == "group":
            continue
        if project.get("deleted") is True:
            continue
        project_space_id = project.get("space-id")
        if space_id and project_space_id:
            if not isinstance(project_space_id, str):
                raise IdentityPreflightError(
                    "Cannot inspect project identity: malformed project space id"
                )
            if project_space_id != space_id:
                continue

        project_id = project.get("id")
        if not isinstance(project_id, str) or not project_id:
            raise IdentityPreflightError("Cannot inspect project identity: project id is missing")
        if project_id in seen_project_ids:
            continue
        seen_project_ids.add(project_id)

        assemblies_url = f"{base}/console/api/v2/projects/{project_id}/assemblies"
        assemblies_response = api_request("GET", assemblies_url, token)
        assemblies = api_collection(assemblies_response, ("items", "assemblies"))
        if assemblies is None:
            reason = safe_api_error(assemblies_response, "unexpected list-builds response")
            raise IdentityPreflightError(
                f"Cannot inspect project {project_id} identity: {reason}"
            )
        if not assemblies:
            raise IdentityPreflightError(
                f"Cannot inspect project {project_id} identity: no assemblies returned"
            )

        identities: set[tuple[str, str]] = set()
        for assembly in assemblies:
            if not isinstance(assembly, dict):
                raise IdentityPreflightError(
                    f"Cannot inspect project {project_id} identity: malformed assembly record"
                )
            identity = assembly_identity(assembly)
            if identity is None:
                raise IdentityPreflightError(
                    f"Cannot inspect project {project_id} identity: assembly identity is missing"
                )
            identities.add(identity)

        if target_identity in identities:
            conflicts.append(project_id)

    return sorted(conflicts)


def technology_version_format_error(value: str) -> dict | None:
    if TECHNOLOGY_VERSION_PATTERN.fullmatch(value):
        return None
    return {
        "error": "Invalid technology version format",
        "details": {
            "value": value,
            "expected": "<major>.<minor>.<patch>-<build>",
        },
        "rule_id": "deploy.technology_version_format",
    }


def parse_json_or_text(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def is_error_token(token: str) -> bool:
    try:
        payload = json.loads(token)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and "error" in payload


def extract_token(body: dict) -> str | None:
    for key in ("id_token", "token", "value"):
        token = body.get(key)
        if token:
            return token

    access_token = body.get("access_token")
    if access_token and access_token != "Not implemented":
        return access_token
    return None


def resolve_branch_name(branch_name: str) -> str:
    return branch_name or os.environ.get("ELEMENT_BRANCH", "main")


def compact_reference(value):
    if not isinstance(value, dict):
        return value
    if value.get("id"):
        return {"id": value["id"]}
    if value.get("name"):
        return {"name": value["name"]}
    return value


def build_branch_body(current: dict, fallback_name: str, app_id: str = "", merge: bool = False) -> dict:
    body = {
        "name": current.get("name") or fallback_name,
    }
    if "kind" in current:
        body["kind"] = current["kind"]
    if "source-branch" in current:
        body["source-branch"] = compact_reference(current["source-branch"])
    if "deletion-mark" in current:
        body["deletion-mark"] = current["deletion-mark"]

    current_application = compact_reference(current.get("application"))
    if current_application:
        body["application"] = current_application

    if current.get("version-stamp"):
        body["version-stamp"] = current["version-stamp"]
    if app_id:
        body["application"] = {"id": app_id}
    if merge:
        body["write-parameters"] = {"merge": True}
    return body


def require_object_response(response) -> dict | None:
    if isinstance(response, dict):
        return response
    return None


def get_token_cache_path(base_url: str, client_id: str) -> str:
    h = hashlib.md5(f"{base_url}:{client_id}".encode()).hexdigest()[:8]
    return f"/tmp/element_token_{h}.json"


def load_cached_token(cache_path: str) -> str | None:
    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
        token = data["token"]
        if is_error_token(token):
            return None
        if time.time() < data.get("expires_at", 0):
            return token
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
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data=data,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        details = parse_json_or_text(e.read().decode(errors="replace"))
        raise TokenFetchError(build_error(f"HTTP {e.code}", details=details)) from e
    except urllib.error.URLError as e:
        raise TokenFetchError(build_error("Connection error", details=str(e.reason))) from e
    except OSError as e:
        raise TokenFetchError(build_error("Connection error", details=str(e))) from e

    try:
        body = json.loads(raw)
    except json.JSONDecodeError as e:
        raise TokenFetchError(build_error("Invalid JSON response", details=raw)) from e

    token = extract_token(body)
    if not token:
        raise TokenFetchError(build_error("token field not found", response=body))
    return token


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


def api_request_binary(method: str, url: str, token: str, file_path: str, params: dict | None = None) -> dict | list:
    """Отправить бинарный файл (application/octet-stream) с query-параметрами."""
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v})
        if qs:
            url = f"{url}?{qs}"
    try:
        with open(file_path, "rb") as f:
            data = f.read()
    except OSError as e:
        return build_error("Cannot read file", details=str(e))

    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "Accept": "application/json",
        },
        data=data,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        err_body = parse_json_or_text(e.read().decode(errors="replace"))
        return build_error(f"HTTP {e.code}", details=err_body)
    except urllib.error.URLError as e:
        return build_error("Connection error", details=str(e.reason))
    except OSError as e:
        return build_error("Connection error", details=str(e))

    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return build_error("Invalid JSON response", details=raw)


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
            raw = resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        err_body = parse_json_or_text(e.read().decode(errors="replace"))
        return build_error(f"HTTP {e.code}", details=err_body)
    except urllib.error.URLError as e:
        return build_error("Connection error", details=str(e.reason))
    except OSError as e:
        return build_error("Connection error", details=str(e))

    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return build_error("Invalid JSON response", details=raw)


def main():
    parser = argparse.ArgumentParser(description="Console API v2 client")
    parser.add_argument("--action", required=True)
    parser.add_argument("--base-url", default=os.environ.get("ELEMENT_BASE_URL", ""))
    parser.add_argument("--client-id", default=os.environ.get("ELEMENT_CLIENT_ID", ""))
    parser.add_argument("--client-secret", default=os.environ.get("ELEMENT_CLIENT_SECRET", ""))
    parser.add_argument("--app-id", default=os.environ.get("ELEMENT_APP_ID", ""))
    parser.add_argument("--project-id", default=os.environ.get("ELEMENT_PROJECT_ID", ""))
    parser.add_argument("--branch-id", default=os.environ.get("ELEMENT_BRANCH_ID", ""))
    parser.add_argument("--branch-name", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--space-id", default=os.environ.get("ELEMENT_SPACE_ID", ""))
    parser.add_argument("--dump-id", default="")
    parser.add_argument("--file", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--version-id", default="")
    parser.add_argument("--commit-id", default="")
    parser.add_argument("--commit-message", default="")
    parser.add_argument("--technology-version", default="")
    parser.add_argument("--task-id", default="")
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
        try:
            token = get_token(args)
        except TokenFetchError as e:
            print(json.dumps(e.payload, ensure_ascii=False))
            sys.exit(1)
        print(json.dumps({"token": token}, ensure_ascii=False))
        return

    # Все остальные действия требуют токена
    if not args.client_id or not args.client_secret:
        print(json.dumps({"error": "ELEMENT_CLIENT_ID / ELEMENT_CLIENT_SECRET not set"}, ensure_ascii=False))
        sys.exit(1)
    try:
        token = get_token(args)
    except TokenFetchError as e:
        print(json.dumps(e.payload, ensure_ascii=False, indent=2))
        sys.exit(1)

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
        if args.technology_version:
            format_error = technology_version_format_error(args.technology_version)
            if format_error:
                print(json.dumps(format_error, ensure_ascii=False))
                sys.exit(1)
        url = f"{base}/console/api/v2/applications"
        source: dict = {"type": "repository"}
        if args.version_id:
            source["project-version-id"] = args.version_id
        elif args.project_id:
            source["image-id"] = args.project_id
        body = {
            "source": source,
            "display-name": args.name,
            "publication-context": args.name,
            "development-mode": True,
        }
        if args.space_id:
            body["space-id"] = args.space_id
        if args.technology_version:
            body["technology-version"] = args.technology_version
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

    elif action == "get-technology-version":
        if not args.app_id:
            print(json.dumps({"error": "--app-id required"}, ensure_ascii=False))
            sys.exit(1)
        # Специализированный endpoint /technology-version поддерживается не всеми версиями
        # платформы. Читаем technology-version из стандартного GET /applications/{id}.
        url = f"{base}/console/api/v2/applications/{args.app_id}"
        result = api_request("GET", url, token)
        if isinstance(result, dict) and "technology-version" in result:
            print(json.dumps(
                {"technology-version": result["technology-version"], "date-updated": result.get("date-updated")},
                ensure_ascii=False,
                indent=2,
            ))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "update-technology-version":
        if not args.app_id:
            print(json.dumps({"error": "--app-id required"}, ensure_ascii=False))
            sys.exit(1)
        if not args.technology_version:
            print(json.dumps({"error": "--technology-version required"}, ensure_ascii=False))
            sys.exit(1)
        format_error = technology_version_format_error(args.technology_version)
        if format_error:
            print(json.dumps(format_error, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/tasks/group-tasks/update-applications-technology"
        body = {"technology-version": args.technology_version, "applications": [args.app_id]}
        result = api_request("POST", url, token, body)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "get-group-task":
        if not args.task_id:
            print(json.dumps({"error": "--task-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/tasks/group-tasks/{args.task_id}"
        result = api_request("GET", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ── Пространства ───────────────────────────────────────────────────────────

    elif action == "list-spaces":
        url = f"{base}/console/api/v2/spaces"
        result = api_request("GET", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    # ── Проекты ────────────────────────────────────────────────────────────────

    elif action == "list-projects":
        url = f"{base}/console/api/v2/projects"
        result = api_request("GET", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "get-project":
        if not args.project_id:
            print(json.dumps({"error": "--project-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/projects/{args.project_id}"
        result = api_request("GET", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "delete-project":
        if not args.project_id:
            print(json.dumps({"error": "--project-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/projects/{args.project_id}"
        result = api_request("DELETE", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "upload-build":
        if not args.file:
            print(json.dumps({"error": "--file required"}, ensure_ascii=False))
            sys.exit(1)
        # Если project-id задан — добавляем сборку к существующему проекту
        # Если нет — создаём новый проект
        if args.project_id:
            url = f"{base}/console/api/v2/projects/{args.project_id}/assemblies"
        else:
            try:
                identity = read_assembly_identity(args.file)
                conflicts = find_project_identity_conflicts(
                    base,
                    token,
                    args.space_id,
                    identity,
                )
            except IdentityPreflightError as error:
                print(json.dumps(
                    identity_preflight_error(str(error)),
                    ensure_ascii=False,
                    indent=2,
                ))
                sys.exit(1)
            if conflicts:
                print(json.dumps(
                    identity_conflict_error(*identity, conflicts),
                    ensure_ascii=False,
                    indent=2,
                ))
                sys.exit(1)
            url = f"{base}/console/api/v2/projects"
        params = {
            "SpaceId": args.space_id,
            "BranchName": resolve_branch_name(args.branch_name) if args.branch_name else "",
            "CommitId": args.commit_id,
            "CommitMessage": args.commit_message,
        }
        result = api_request_binary("POST", url, token, args.file, params)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "list-builds":
        if not args.project_id:
            print(json.dumps({"error": "--project-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/projects/{args.project_id}/assemblies"
        result = api_request("GET", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "get-build":
        if not args.project_id or not args.version:
            print(json.dumps({"error": "--project-id and --version required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/projects/{args.project_id}/assemblies/{args.version}"
        result = api_request("GET", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "delete-build":
        if not args.project_id or not args.version:
            print(json.dumps({"error": "--project-id and --version required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/projects/{args.project_id}/assemblies/{args.version}"
        result = api_request("DELETE", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "sync-branch":
        # Загрузить изменения из git-ветки (внутренний UI API платформы).
        # Эквивалент кнопки "Загрузить из ветки" в IDE.
        # branch-id — внутренний ID ветки на платформе (ELEMENT_BRANCH_ID).
        if not args.app_id:
            print(json.dumps({"error": "--app-id required"}, ensure_ascii=False))
            sys.exit(1)
        if not args.branch_id:
            print(json.dumps({"error": "--branch-id or ELEMENT_BRANCH_ID required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/ui/module/call?locale=ru"
        body = {
            "module": "e1c::console::Applications::ApplicationConfigurationUpdateForm",
            "method": "UpdateAppConfiguration",
            "params": [
                {"type": "e1c::console::Applications::Applications.Reference", "value": args.app_id},
                {"type": "e1c::console::Team::Branches.Reference", "value": args.branch_id},
                {"type": "Std::Boolean", "value": False},
                {"type": "Std::Boolean", "value": False},
            ],
        }
        result = api_request("POST", url, token, body)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "project-update":
        if not args.app_id:
            print(json.dumps({"error": "--app-id required"}, ensure_ascii=False))
            sys.exit(1)
        if not args.version_id and not args.project_id:
            print(json.dumps({"error": "--version-id (assembly id) or --project-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/applications/{args.app_id}/project/update"
        source: dict = {"type": "repository"}
        if args.version_id:
            source["image-id"] = args.version_id
        else:
            source["project-id"] = args.project_id
            if args.version:
                source["assembly-version"] = args.version
        result = api_request("POST", url, token, {"source": source})
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
        branch_name = resolve_branch_name(args.branch_name)
        if not args.project_id or not branch_name:
            print(json.dumps({"error": "--project-id and --branch-name required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/branches"
        body: dict = {
            "name": branch_name,
            "kind": "development",
            "project": {"id": args.project_id},
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
        current = require_object_response(api_request("GET", url_get, token))
        if current is None:
            print(json.dumps(build_error("Unexpected response type"), ensure_ascii=False, indent=2))
            sys.exit(1)
        if "error" in current:
            print(json.dumps(current, ensure_ascii=False, indent=2))
            sys.exit(1)
        body = build_branch_body(current, resolve_branch_name(args.branch_name), app_id=args.app_id)
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
        current = require_object_response(api_request("GET", url_get, token))
        if current is None:
            print(json.dumps(build_error("Unexpected response type"), ensure_ascii=False, indent=2))
            sys.exit(1)
        if "error" in current:
            print(json.dumps(current, ensure_ascii=False, indent=2))
            sys.exit(1)
        body = build_branch_body(current, resolve_branch_name(args.branch_name), merge=True)
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

    elif action == "list-app-tasks":
        if not args.app_id:
            print(json.dumps({"error": "--app-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/tasks/application-tasks"
        result = api_request("GET", url, token)
        # Фильтруем по application-id на клиенте (API не поддерживает query-фильтр)
        if isinstance(result, list):
            result = [t for t in result if t.get("application-id") == args.app_id]
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif action == "get-app-task":
        if not args.task_id:
            print(json.dumps({"error": "--task-id required"}, ensure_ascii=False))
            sys.exit(1)
        url = f"{base}/console/api/v2/tasks/application-tasks/{args.task_id}"
        result = api_request("GET", url, token)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        print(json.dumps({"error": f"Unknown action: {action}"}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
