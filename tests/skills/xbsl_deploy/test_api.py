from __future__ import annotations

import builtins
import importlib.util
import io
import json
import runpy
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT_DIR / "skills/xbsl-deploy/scripts/api.py"


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def load_api_module():
    spec = importlib.util.spec_from_file_location("api_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_main(api, monkeypatch, capsys, argv: list[str], expected_exit: int | None = None):
    monkeypatch.setattr(sys, "argv", ["api.py", *argv])

    if expected_exit is None:
        api.main()
        return json.loads(capsys.readouterr().out)

    with pytest.raises(SystemExit) as exc_info:
        api.main()

    assert exc_info.value.code == expected_exit
    return json.loads(capsys.readouterr().out)


def write_assembly(path: Path, *, vendor: str = "Demo", name: str = "TestApp") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Assembly.yaml",
            (
                "ManifestVersion: 1.0\n"
                "ProjectKind: Application\n"
                f"Vendor: {vendor}\n"
                f"Name: {name}\n"
                "Version: 1.0-1\n"
            ),
        )
    return path


def run_upload_build(
    api,
    monkeypatch,
    capsys,
    build_path: Path | str,
    *,
    project_id: str = "",
    space_id: str = "",
    expected_exit: int | None = None,
):
    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    argv = [
        "--action",
        "upload-build",
        "--file",
        str(build_path),
        "--base-url",
        "https://example.com",
        "--client-id",
        "client",
        "--client-secret",
        "secret",
    ]
    if project_id:
        argv.extend(("--project-id", project_id))
    if space_id:
        argv.extend(("--space-id", space_id))
    return run_main(api, monkeypatch, capsys, argv, expected_exit=expected_exit)


@pytest.fixture
def api():
    return load_api_module()


@pytest.fixture(autouse=True)
def clear_element_env(monkeypatch) -> None:
    for key in (
        "ELEMENT_BASE_URL",
        "ELEMENT_CLIENT_ID",
        "ELEMENT_CLIENT_SECRET",
        "ELEMENT_APP_ID",
        "ELEMENT_PROJECT_ID",
        "ELEMENT_BRANCH",
        "ELEMENT_BRANCH_ID",
        "ELEMENT_SPACE_ID",
    ):
        monkeypatch.delenv(key, raising=False)


def test_get_token_cache_path_is_stable(api) -> None:
    path = api.get_token_cache_path("https://example.com", "client")

    assert path == api.get_token_cache_path("https://example.com", "client")
    assert path != api.get_token_cache_path("https://example.com", "other-client")


def test_token_cache_roundtrip_and_expiration(api, tmp_path: Path, monkeypatch) -> None:
    cache_path = tmp_path / "token.json"
    monkeypatch.setattr(api.time, "time", lambda: 1000)

    api.save_token_cache(str(cache_path), "TOKEN")

    assert api.load_cached_token(str(cache_path)) == "TOKEN"

    monkeypatch.setattr(api.time, "time", lambda: 1000 + api.TOKEN_TTL + 1)

    assert api.load_cached_token(str(cache_path)) is None


@pytest.mark.parametrize(
    "payload",
    [
        '{"expires_at": 999999}',
        '{"token": "x"}',
        json.dumps({"token": json.dumps({"error": "HTTP 401"}), "expires_at": 9999999999}),
        "not-json",
    ],
)
def test_load_cached_token_returns_none_for_invalid_payloads(api, tmp_path: Path, payload: str) -> None:
    cache_path = tmp_path / "token.json"
    cache_path.write_text(payload, encoding="utf-8")

    assert api.load_cached_token(str(cache_path)) is None


def test_save_token_cache_ignores_oserror(api, monkeypatch) -> None:
    def fake_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(builtins, "open", fake_open)

    api.save_token_cache("/tmp/token.json", "TOKEN")


def test_compact_reference_handles_non_dict_name_only_and_empty_dict(api) -> None:
    assert api.compact_reference("branch-main") == "branch-main"
    assert api.compact_reference({"name": "main"}) == {"name": "main"}
    assert api.compact_reference({}) == {}


def test_build_branch_body_skips_optional_fields_when_missing(api) -> None:
    assert api.build_branch_body({"source-branch": "branch-main"}, "fallback") == {
        "name": "fallback",
        "source-branch": "branch-main",
    }


def test_require_object_response_returns_dict_or_none(api) -> None:
    assert api.require_object_response({"id": "branch-1"}) == {"id": "branch-1"}
    assert api.require_object_response([{"id": "branch-1"}]) is None


def test_read_assembly_identity_handles_quoted_values_and_yaml_comments(api, tmp_path: Path) -> None:
    build_path = tmp_path / "TestApp.xasm"
    with zipfile.ZipFile(build_path, "w") as archive:
        archive.writestr(
            "Assembly.yaml",
            "Vendor: Demo # supplier\nName: \"TestApp\" # technical project name\n",
        )

    assert api.read_assembly_identity(str(build_path)) == ("Demo", "TestApp")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"id_token": "t0", "access_token": "Not implemented"}, "t0"),
        ({"token": "t1"}, "t1"),
        ({"access_token": "t2"}, "t2"),
        ({"value": "t3"}, "t3"),
    ],
)
def test_fetch_token_reads_supported_token_fields(api, monkeypatch, body: dict, expected: str) -> None:
    def fake_urlopen(request):
        assert request.full_url == "https://example.com/console/sys/token"
        assert request.get_method() == "POST"
        assert request.get_header("Accept") == "application/json"
        assert request.get_header("Content-type") == "application/x-www-form-urlencoded"
        assert request.data == b"grant_type=client_credentials"
        auth = request.get_header("Authorization")
        assert auth is not None
        assert auth.startswith("Basic ")
        assert api.base64.b64decode(auth.split(" ", 1)[1]).decode() == "client:secret"
        return FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)

    assert api.fetch_token("https://example.com", "client", "secret") == expected


def test_fetch_token_returns_diagnostic_if_token_field_missing(api, monkeypatch) -> None:
    monkeypatch.setattr(
        api.urllib.request,
        "urlopen",
        lambda _request: FakeResponse(b'{"status":"ok"}'),
    )

    with pytest.raises(api.TokenFetchError) as exc_info:
        api.fetch_token("https://example.com", "client", "secret")

    assert exc_info.value.payload == {"error": "token field not found", "response": {"status": "ok"}}


def test_fetch_token_returns_http_error_payload(api, monkeypatch) -> None:
    error = urllib.error.HTTPError(
        url="https://example.com/console/sys/token",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=io.BytesIO(b'{"message":"bad credentials"}'),
    )

    def fake_urlopen(_request):
        raise error

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(api.TokenFetchError) as exc_info:
        api.fetch_token("https://example.com", "client", "secret")

    assert exc_info.value.payload == {"error": "HTTP 401", "details": {"message": "bad credentials"}}


def test_fetch_token_returns_connection_error(api, monkeypatch) -> None:
    monkeypatch.setattr(
        api.urllib.request,
        "urlopen",
        lambda _request: (_ for _ in ()).throw(api.urllib.error.URLError("dns failed")),
    )

    with pytest.raises(api.TokenFetchError) as exc_info:
        api.fetch_token("https://example.com", "client", "secret")

    assert exc_info.value.payload == {"error": "Connection error", "details": "dns failed"}


def test_fetch_token_returns_oserror(api, monkeypatch) -> None:
    monkeypatch.setattr(
        api.urllib.request,
        "urlopen",
        lambda _request: (_ for _ in ()).throw(OSError("socket closed")),
    )

    with pytest.raises(api.TokenFetchError) as exc_info:
        api.fetch_token("https://example.com", "client", "secret")

    assert exc_info.value.payload == {"error": "Connection error", "details": "socket closed"}


def test_fetch_token_returns_invalid_json_error(api, monkeypatch) -> None:
    monkeypatch.setattr(api.urllib.request, "urlopen", lambda _request: FakeResponse(b"not-json"))

    with pytest.raises(api.TokenFetchError) as exc_info:
        api.fetch_token("https://example.com", "client", "secret")

    assert exc_info.value.payload == {"error": "Invalid JSON response", "details": "not-json"}


def test_get_token_uses_cached_token(api, monkeypatch) -> None:
    args = SimpleNamespace(base_url="https://example.com", client_id="client", client_secret="secret")

    monkeypatch.setattr(api, "load_cached_token", lambda _path: "CACHED")
    monkeypatch.setattr(api, "fetch_token", lambda *_args: pytest.fail("fetch_token should not be called"))

    assert api.get_token(args) == "CACHED"


def test_get_token_fetches_and_saves_when_cache_misses(api, monkeypatch) -> None:
    args = SimpleNamespace(base_url="https://example.com", client_id="client", client_secret="secret")
    saved = []

    monkeypatch.setattr(api, "load_cached_token", lambda _path: None)
    monkeypatch.setattr(api, "fetch_token", lambda *_args: "NEW_TOKEN")
    monkeypatch.setattr(api, "save_token_cache", lambda path, token: saved.append((path, token)))

    assert api.get_token(args) == "NEW_TOKEN"
    assert saved == [(api.get_token_cache_path("https://example.com", "client"), "NEW_TOKEN")]


def test_get_token_does_not_save_failed_fetch(api, monkeypatch) -> None:
    args = SimpleNamespace(base_url="https://example.com", client_id="client", client_secret="secret")

    monkeypatch.setattr(api, "load_cached_token", lambda _path: None)
    monkeypatch.setattr(
        api,
        "fetch_token",
        lambda *_args: (_ for _ in ()).throw(api.TokenFetchError({"error": "HTTP 401"})),
    )
    monkeypatch.setattr(api, "save_token_cache", lambda *_args: pytest.fail("save_token_cache should not be called"))

    with pytest.raises(api.TokenFetchError) as exc_info:
        api.get_token(args)

    assert exc_info.value.payload == {"error": "HTTP 401"}


@pytest.mark.parametrize(
    ("body", "raw_response", "expected"),
    [
        (None, b'{"ok": true}', {"ok": True}),
        ({"payload": 1}, b"", {}),
    ],
)
def test_api_request_handles_success_and_empty_response(api, monkeypatch, body, raw_response: bytes, expected) -> None:
    captured = {}

    def fake_urlopen(request):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["accept"] = request.get_header("Accept")
        captured["content_type"] = request.get_header("Content-type")
        captured["data"] = request.data
        return FakeResponse(raw_response)

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)

    result = api.api_request("POST" if body is not None else "GET", "https://example.com/api", "TOKEN", body)

    assert result == expected
    assert captured["url"] == "https://example.com/api"
    assert captured["method"] == ("POST" if body is not None else "GET")
    assert captured["authorization"] == "Bearer TOKEN"
    assert captured["accept"] == "application/json"
    if body is None:
        assert captured["content_type"] is None
        assert captured["data"] is None
    else:
        assert json.loads(captured["data"].decode()) == body
        assert captured["content_type"] == "application/json"


@pytest.mark.parametrize(
    ("raw_body", "expected_details"),
    [
        (b'{"message":"bad request"}', {"message": "bad request"}),
        (b"plain text error", "plain text error"),
    ],
)
def test_api_request_returns_error_details_for_http_error(api, monkeypatch, raw_body: bytes, expected_details) -> None:
    error = urllib.error.HTTPError(
        url="https://example.com/api",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=io.BytesIO(raw_body),
    )

    def fake_urlopen(_request):
        raise error

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)

    assert api.api_request("GET", "https://example.com/api", "TOKEN") == {
        "error": "HTTP 400",
        "details": expected_details,
    }


def test_api_request_returns_connection_error(api, monkeypatch) -> None:
    monkeypatch.setattr(
        api.urllib.request,
        "urlopen",
        lambda _request: (_ for _ in ()).throw(api.urllib.error.URLError("connection refused")),
    )

    assert api.api_request("GET", "https://example.com/api", "TOKEN") == {
        "error": "Connection error",
        "details": "connection refused",
    }


def test_api_request_returns_oserror(api, monkeypatch) -> None:
    monkeypatch.setattr(
        api.urllib.request,
        "urlopen",
        lambda _request: (_ for _ in ()).throw(OSError("socket closed")),
    )

    assert api.api_request("GET", "https://example.com/api", "TOKEN") == {
        "error": "Connection error",
        "details": "socket closed",
    }


def test_api_request_returns_invalid_json_error(api, monkeypatch) -> None:
    monkeypatch.setattr(api.urllib.request, "urlopen", lambda _request: FakeResponse(b"not-json"))

    assert api.api_request("GET", "https://example.com/api", "TOKEN") == {
        "error": "Invalid JSON response",
        "details": "not-json",
    }


@pytest.mark.parametrize(
    ("raw_response", "expected"),
    [
        (b'{"ok": true}', {"ok": True}),
        (b"", {}),
    ],
)
def test_api_request_binary_handles_success_and_empty_response(
    api, monkeypatch, tmp_path: Path, raw_response: bytes, expected
) -> None:
    file_path = tmp_path / "build.zip"
    file_path.write_bytes(b"binary-payload")
    captured = {}

    def fake_urlopen(request):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["accept"] = request.get_header("Accept")
        captured["content_type"] = request.get_header("Content-type")
        captured["data"] = request.data
        return FakeResponse(raw_response)

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)

    result = api.api_request_binary(
        "POST",
        "https://example.com/upload",
        "TOKEN",
        str(file_path),
        {
            "SpaceId": "space-1",
            "BranchName": "",
            "CommitId": "abc123",
            "CommitMessage": "deploy build",
        },
    )

    assert result == expected
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.com/upload?SpaceId=space-1&CommitId=abc123&CommitMessage=deploy+build"
    assert captured["authorization"] == "Bearer TOKEN"
    assert captured["accept"] == "application/json"
    assert captured["content_type"] == "application/octet-stream"
    assert captured["data"] == b"binary-payload"


def test_api_request_binary_returns_cannot_read_file(api) -> None:
    assert api.api_request_binary("POST", "https://example.com/upload", "TOKEN", "/tmp/missing.zip") == {
        "error": "Cannot read file",
        "details": "[Errno 2] No such file or directory: '/tmp/missing.zip'",
    }


def test_api_request_binary_ignores_empty_query_params(api, monkeypatch, tmp_path: Path) -> None:
    file_path = tmp_path / "build.zip"
    file_path.write_bytes(b"binary-payload")
    captured = {}

    def fake_urlopen(request):
        captured["url"] = request.full_url
        return FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)

    result = api.api_request_binary(
        "POST",
        "https://example.com/upload",
        "TOKEN",
        str(file_path),
        {"SpaceId": "", "BranchName": "", "CommitId": "", "CommitMessage": ""},
    )

    assert result == {"ok": True}
    assert captured["url"] == "https://example.com/upload"


@pytest.mark.parametrize(
    ("raw_body", "expected_details"),
    [
        (b'{"message":"bad request"}', {"message": "bad request"}),
        (b"plain text error", "plain text error"),
    ],
)
def test_api_request_binary_returns_error_details_for_http_error(api, monkeypatch, tmp_path: Path, raw_body: bytes, expected_details) -> None:
    file_path = tmp_path / "build.zip"
    file_path.write_bytes(b"binary-payload")
    error = urllib.error.HTTPError(
        url="https://example.com/upload",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=io.BytesIO(raw_body),
    )

    def fake_urlopen(_request):
        raise error

    monkeypatch.setattr(api.urllib.request, "urlopen", fake_urlopen)

    assert api.api_request_binary("POST", "https://example.com/upload", "TOKEN", str(file_path)) == {
        "error": "HTTP 400",
        "details": expected_details,
    }


def test_api_request_binary_returns_connection_error(api, monkeypatch, tmp_path: Path) -> None:
    file_path = tmp_path / "build.zip"
    file_path.write_bytes(b"binary-payload")
    monkeypatch.setattr(
        api.urllib.request,
        "urlopen",
        lambda _request: (_ for _ in ()).throw(api.urllib.error.URLError("connection refused")),
    )

    assert api.api_request_binary("POST", "https://example.com/upload", "TOKEN", str(file_path)) == {
        "error": "Connection error",
        "details": "connection refused",
    }


def test_api_request_binary_returns_oserror(api, monkeypatch, tmp_path: Path) -> None:
    file_path = tmp_path / "build.zip"
    file_path.write_bytes(b"binary-payload")
    monkeypatch.setattr(
        api.urllib.request,
        "urlopen",
        lambda _request: (_ for _ in ()).throw(OSError("socket closed")),
    )

    assert api.api_request_binary("POST", "https://example.com/upload", "TOKEN", str(file_path)) == {
        "error": "Connection error",
        "details": "socket closed",
    }


def test_api_request_binary_returns_invalid_json_error(api, monkeypatch, tmp_path: Path) -> None:
    file_path = tmp_path / "build.zip"
    file_path.write_bytes(b"binary-payload")
    monkeypatch.setattr(api.urllib.request, "urlopen", lambda _request: FakeResponse(b"not-json"))

    assert api.api_request_binary("POST", "https://example.com/upload", "TOKEN", str(file_path)) == {
        "error": "Invalid JSON response",
        "details": "not-json",
    }


def test_main_requires_base_url(api, monkeypatch, capsys) -> None:
    result = run_main(api, monkeypatch, capsys, ["--action", "list-projects"], expected_exit=1)

    assert result == {"error": "ELEMENT_BASE_URL not set"}


def test_main_get_token_requires_credentials(api, monkeypatch, capsys) -> None:
    result = run_main(
        api,
        monkeypatch,
        capsys,
        ["--action", "get-token", "--base-url", "https://example.com"],
        expected_exit=1,
    )

    assert result == {"error": "ELEMENT_CLIENT_ID / ELEMENT_CLIENT_SECRET not set"}


def test_main_non_token_actions_require_credentials(api, monkeypatch, capsys) -> None:
    result = run_main(
        api,
        monkeypatch,
        capsys,
        ["--action", "list-projects", "--base-url", "https://example.com"],
        expected_exit=1,
    )

    assert result == {"error": "ELEMENT_CLIENT_ID / ELEMENT_CLIENT_SECRET not set"}


def test_main_get_token_prints_token(api, monkeypatch, capsys) -> None:
    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "get-token",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
    )

    assert result == {"token": "TOKEN"}


def test_main_get_token_prints_error_and_exits_on_token_fetch_failure(api, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        api,
        "get_token",
        lambda _args: (_ for _ in ()).throw(api.TokenFetchError({"error": "HTTP 401", "details": "bad credentials"})),
    )

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "get-token",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
        expected_exit=1,
    )

    assert result == {"error": "HTTP 401", "details": "bad credentials"}


def test_main_non_token_action_prints_error_and_exits_on_token_fetch_failure(api, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        api,
        "get_token",
        lambda _args: (_ for _ in ()).throw(api.TokenFetchError({"error": "Connection error", "details": "dns failed"})),
    )

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "list-projects",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
        expected_exit=1,
    )

    assert result == {"error": "Connection error", "details": "dns failed"}


@pytest.mark.parametrize(
    ("argv", "expected_error"),
    [
        (["--action", "create-app"], "--name required"),
        (["--action", "create-app", "--technology-version", "9.1"], "--name required"),
        (["--action", "get-app"], "--app-id required"),
        (["--action", "delete-app"], "--app-id required"),
        (["--action", "start-app"], "--app-id required"),
        (["--action", "stop-app"], "--app-id required"),
        (["--action", "get-project"], "--project-id required"),
        (["--action", "delete-project"], "--project-id required"),
        (["--action", "upload-build"], "--file required"),
        (["--action", "list-builds"], "--project-id required"),
        (["--action", "get-build"], "--project-id and --version required"),
        (["--action", "delete-build"], "--project-id and --version required"),
        (["--action", "sync-branch"], "--app-id required"),
        (["--action", "sync-branch", "--app-id", "app-1"], "--branch-id or ELEMENT_BRANCH_ID required"),
        (["--action", "project-update"], "--app-id required"),
        (["--action", "project-update", "--app-id", "app-1"], "--version-id (assembly id) or --project-id required"),
        (["--action", "get-branch"], "--branch-id required"),
        (["--action", "create-branch"], "--project-id and --branch-name required"),
        (["--action", "update-branch"], "--branch-id required"),
        (["--action", "delete-branch"], "--branch-id required"),
        (["--action", "merge-branch"], "--branch-id required"),
        (["--action", "create-dump"], "--app-id required"),
        (["--action", "get-dump"], "--app-id and --dump-id required"),
        (["--action", "get-technology-version"], "--app-id required"),
        (["--action", "update-technology-version"], "--app-id required"),
        (
            ["--action", "update-technology-version", "--technology-version", "9.1"],
            "--app-id required",
        ),
        (["--action", "update-technology-version", "--app-id", "app-1"], "--technology-version required"),
        (["--action", "get-group-task"], "--task-id required"),
        (["--action", "list-app-tasks"], "--app-id required"),
        (["--action", "get-app-task"], "--task-id required"),
    ],
)
def test_main_validates_required_action_arguments(api, monkeypatch, capsys, argv: list[str], expected_error: str) -> None:
    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [*argv, "--base-url", "https://example.com", "--client-id", "client", "--client-secret", "secret"],
        expected_exit=1,
    )

    assert result == {"error": expected_error}


@pytest.mark.parametrize(
    ("argv", "invalid_value"),
    [
        (
            ["--action", "update-technology-version", "--app-id", "app-1", "--technology-version", "9.1"],
            "9.1",
        ),
        (
            ["--action", "update-technology-version", "--app-id", "app-1", "--technology-version", "9.2.9"],
            "9.2.9",
        ),
        (
            ["--action", "create-app", "--name", "demo", "--technology-version", "9.2.9-12-extra"],
            "9.2.9-12-extra",
        ),
    ],
)
def test_main_rejects_invalid_technology_version_before_api_request(
    api, monkeypatch, capsys, argv: list[str], invalid_value: str
) -> None:
    calls = []
    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(api, "api_request", lambda *args, **kwargs: calls.append((args, kwargs)) or {})

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [*argv, "--base-url", "https://example.com", "--client-id", "client", "--client-secret", "secret"],
        expected_exit=1,
    )

    assert result == {
        "error": "Invalid technology version format",
        "details": {
            "value": invalid_value,
            "expected": "<major>.<minor>.<patch>-<build>",
        },
        "rule_id": "deploy.technology_version_format",
    }
    assert calls == []


def test_update_technology_version_does_not_rewrite_project_yaml(
    api, monkeypatch, capsys, tmp_path: Path
) -> None:
    project_yaml = tmp_path / "Проект.yaml"
    original = "Имя: Demo\nРежимСовместимости: 9.1\n"
    project_yaml.write_text(original, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(
        api,
        "api_request",
        lambda method, url, token, body=None: calls.append((method, url, token, body))
        or {"id": "task-1"},
    )

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "update-technology-version",
            "--app-id",
            "app-1",
            "--technology-version",
            "9.2.9-12",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
    )

    assert result == {"id": "task-1"}
    assert calls == [
        (
            "POST",
            "https://example.com/console/api/v2/tasks/group-tasks/update-applications-technology",
            "TOKEN",
            {"technology-version": "9.2.9-12", "applications": ["app-1"]},
        )
    ]
    assert project_yaml.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    ("argv", "expected_call", "response"),
    [
        (
            ["--action", "list-apps"],
            ("GET", "https://example.com/console/api/v2/applications", "TOKEN", None),
            [{"id": "all-apps"}],
        ),
        (
            ["--action", "list-apps", "--name", "Demo App"],
            ("GET", "https://example.com/console/api/v2/applications?name=Demo%20App", "TOKEN", None),
            [{"id": "1"}],
        ),
        (
            ["--action", "get-app", "--app-id", "app-1"],
            ("GET", "https://example.com/console/api/v2/applications/app-1", "TOKEN", None),
            {"id": "app-1"},
        ),
        (
            ["--action", "create-app", "--name", "demo", "--space-id", "space-1"],
            (
                "POST",
                "https://example.com/console/api/v2/applications",
                "TOKEN",
                {
                    "source": {"type": "repository"},
                    "display-name": "demo",
                    "publication-context": "demo",
                    "development-mode": True,
                    "space-id": "space-1",
                },
            ),
            {"id": "app-1"},
        ),
        (
            ["--action", "create-app", "--name", "demo"],
            (
                "POST",
                "https://example.com/console/api/v2/applications",
                "TOKEN",
                {
                    "source": {"type": "repository"},
                    "display-name": "demo",
                    "publication-context": "demo",
                    "development-mode": True,
                },
            ),
            {"id": "app-2"},
        ),
        (
            ["--action", "create-app", "--name", "demo", "--version-id", "version-1"],
            (
                "POST",
                "https://example.com/console/api/v2/applications",
                "TOKEN",
                {
                    "source": {"type": "repository", "project-version-id": "version-1"},
                    "display-name": "demo",
                    "publication-context": "demo",
                    "development-mode": True,
                },
            ),
            {"id": "app-3"},
        ),
        (
            ["--action", "create-app", "--name", "demo", "--project-id", "project-1"],
            (
                "POST",
                "https://example.com/console/api/v2/applications",
                "TOKEN",
                {
                    "source": {"type": "repository", "image-id": "project-1"},
                    "display-name": "demo",
                    "publication-context": "demo",
                    "development-mode": True,
                },
            ),
            {"id": "app-4"},
        ),
        (
            ["--action", "delete-app", "--app-id", "app-1"],
            ("DELETE", "https://example.com/console/api/v2/applications/app-1", "TOKEN", None),
            {},
        ),
        (
            ["--action", "start-app", "--app-id", "app-1"],
            ("PUT", "https://example.com/console/api/v2/applications/app-1/status/start", "TOKEN", None),
            {"status": "Starting"},
        ),
        (
            ["--action", "stop-app", "--app-id", "app-1"],
            ("PUT", "https://example.com/console/api/v2/applications/app-1/status/stop", "TOKEN", None),
            {"status": "Stopping"},
        ),
        (
            ["--action", "get-technology-version", "--app-id", "app-1"],
            ("GET", "https://example.com/console/api/v2/applications/app-1", "TOKEN", None),
            # api_request вернёт полный объект приложения; action извлекает только technology-version
            # Тест проверяет, что вызван правильный URL. Сравнение result == response упрощено:
            # мок возвращает минимальный объект, из которого action извлекает нужные поля
            {"technology-version": "9.1.9-17", "date-updated": None},
        ),
        (
            ["--action", "update-technology-version", "--app-id", "app-1", "--technology-version", "9.1.11-21"],
            (
                "POST",
                "https://example.com/console/api/v2/tasks/group-tasks/update-applications-technology",
                "TOKEN",
                {"technology-version": "9.1.11-21", "applications": ["app-1"]},
            ),
            {"id": "task-1", "status": "Pending", "total-count": "1", "completed-count": "0"},
        ),
        (
            ["--action", "get-group-task", "--task-id", "task-1"],
            ("GET", "https://example.com/console/api/v2/tasks/group-tasks/task-1", "TOKEN", None),
            {"id": "task-1", "status": "Completed", "total-count": "1", "completed-count": "1", "cancelled-count": "0"},
        ),
        (
            ["--action", "create-app", "--name", "demo", "--space-id", "space-1", "--technology-version", "9.1.11-21"],
            (
                "POST",
                "https://example.com/console/api/v2/applications",
                "TOKEN",
                {
                    "source": {"type": "repository"},
                    "display-name": "demo",
                    "publication-context": "demo",
                    "development-mode": True,
                    "space-id": "space-1",
                    "technology-version": "9.1.11-21",
                },
            ),
            {"id": "app-5"},
        ),
        (
            ["--action", "list-spaces"],
            ("GET", "https://example.com/console/api/v2/spaces", "TOKEN", None),
            [{"id": "space-1"}],
        ),
        (
            ["--action", "list-projects"],
            ("GET", "https://example.com/console/api/v2/projects", "TOKEN", None),
            [{"id": "project-1"}],
        ),
        (
            ["--action", "get-project", "--project-id", "project-1"],
            ("GET", "https://example.com/console/api/v2/projects/project-1", "TOKEN", None),
            {"id": "project-1"},
        ),
        (
            ["--action", "delete-project", "--project-id", "project-1"],
            ("DELETE", "https://example.com/console/api/v2/projects/project-1", "TOKEN", None),
            {},
        ),
        (
            ["--action", "list-builds", "--project-id", "project-1"],
            ("GET", "https://example.com/console/api/v2/projects/project-1/assemblies", "TOKEN", None),
            [{"version": "1.2.3"}],
        ),
        (
            ["--action", "get-build", "--project-id", "project-1", "--version", "1.2.3"],
            ("GET", "https://example.com/console/api/v2/projects/project-1/assemblies/1.2.3", "TOKEN", None),
            {"version": "1.2.3"},
        ),
        (
            ["--action", "delete-build", "--project-id", "project-1", "--version", "1.2.3"],
            ("DELETE", "https://example.com/console/api/v2/projects/project-1/assemblies/1.2.3", "TOKEN", None),
            {},
        ),
        (
            ["--action", "sync-branch", "--app-id", "app-1", "--branch-id", "branch-1"],
            (
                "POST",
                "https://example.com/console/ui/module/call?locale=ru",
                "TOKEN",
                {
                    "module": "e1c::console::Applications::ApplicationConfigurationUpdateForm",
                    "method": "UpdateAppConfiguration",
                    "params": [
                        {"type": "e1c::console::Applications::Applications.Reference", "value": "app-1"},
                        {"type": "e1c::console::Team::Branches.Reference", "value": "branch-1"},
                        {"type": "Std::Boolean", "value": False},
                        {"type": "Std::Boolean", "value": False},
                    ],
                },
            ),
            {"updated": True},
        ),
        (
            ["--action", "project-update", "--app-id", "app-1", "--version-id", "assembly-1"],
            (
                "POST",
                "https://example.com/console/api/v2/applications/app-1/project/update",
                "TOKEN",
                {"source": {"type": "repository", "image-id": "assembly-1"}},
            ),
            {"updated": True},
        ),
        (
            ["--action", "project-update", "--app-id", "app-1", "--project-id", "project-1", "--version", "1.2.3"],
            (
                "POST",
                "https://example.com/console/api/v2/applications/app-1/project/update",
                "TOKEN",
                {"source": {"type": "repository", "project-id": "project-1", "assembly-version": "1.2.3"}},
            ),
            {"updated-from-project": True},
        ),
        (
            ["--action", "project-update", "--app-id", "app-1", "--project-id", "project-1"],
            (
                "POST",
                "https://example.com/console/api/v2/applications/app-1/project/update",
                "TOKEN",
                {"source": {"type": "repository", "project-id": "project-1"}},
            ),
            {"updated-from-project-no-version": True},
        ),
        (
            ["--action", "list-branches", "--project-id", "project-1", "--branch-name", "release"],
            ("GET", "https://example.com/console/api/v2/branches?project-id=project-1&name=release", "TOKEN", None),
            [{"id": "branch-1"}],
        ),
        (
            ["--action", "list-branches"],
            ("GET", "https://example.com/console/api/v2/branches", "TOKEN", None),
            [{"id": "branch-2"}],
        ),
        (
            ["--action", "get-branch", "--branch-id", "branch-1"],
            ("GET", "https://example.com/console/api/v2/branches/branch-1", "TOKEN", None),
            {"id": "branch-1"},
        ),
        (
            ["--action", "create-branch", "--project-id", "project-1", "--branch-name", "feature", "--app-id", "app-1"],
            (
                "POST",
                "https://example.com/console/api/v2/branches",
                "TOKEN",
                {
                    "name": "feature",
                    "kind": "development",
                    "project": {"id": "project-1"},
                    "application": {"id": "app-1"},
                },
            ),
            {"id": "branch-new"},
        ),
        (
            ["--action", "create-branch", "--project-id", "project-1", "--branch-name", "feature"],
            (
                "POST",
                "https://example.com/console/api/v2/branches",
                "TOKEN",
                {
                    "name": "feature",
                    "kind": "development",
                    "project": {"id": "project-1"},
                },
            ),
            {"id": "branch-new-2"},
        ),
        (
            ["--action", "create-branch", "--project-id", "project-1"],
            (
                "POST",
                "https://example.com/console/api/v2/branches",
                "TOKEN",
                {
                    "name": "main",
                    "kind": "development",
                    "project": {"id": "project-1"},
                },
            ),
            {"id": "branch-main"},
        ),
        (
            ["--action", "delete-branch", "--branch-id", "branch-1"],
            ("DELETE", "https://example.com/console/api/v2/branches/branch-1", "TOKEN", None),
            {},
        ),
        (
            ["--action", "create-dump", "--app-id", "app-1"],
            (
                "POST",
                "https://example.com/console/api/v2/applications/app-1/dumps",
                "TOKEN",
                {
                    "include-users": False,
                    "include-binary-data": False,
                    "description": "auto-dump before deploy",
                },
            ),
            {"id": "dump-1"},
        ),
        (
            ["--action", "get-dump", "--app-id", "app-1", "--dump-id", "dump-1"],
            ("GET", "https://example.com/console/api/v2/applications/app-1/dumps/dump-1", "TOKEN", None),
            {"id": "dump-1", "status": "Done"},
        ),
        (
            ["--action", "get-app-task", "--task-id", "task-1"],
            ("GET", "https://example.com/console/api/v2/tasks/application-tasks/task-1", "TOKEN", None),
            {
                "id": "task-1",
                "status": "Completed",
                "operation-type": "UpdateApplicationConfiguration",
            },
        ),
    ],
)
def test_main_single_request_actions(api, monkeypatch, capsys, argv: list[str], expected_call, response) -> None:
    calls = []

    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(api, "api_request", lambda method, url, token, body=None: calls.append((method, url, token, body)) or response)

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [*argv, "--base-url", "https://example.com", "--client-id", "client", "--client-secret", "secret"],
    )

    assert calls == [expected_call]
    assert result == response


def test_list_app_tasks_uses_actual_endpoint_and_filters_application(api, monkeypatch, capsys) -> None:
    calls = []
    response = [
        {"id": "task-1", "application-id": "app-1", "status": "Completed"},
        {"id": "task-2", "application-id": "app-2", "status": "Failed"},
    ]
    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(
        api,
        "api_request",
        lambda method, url, token, body=None: calls.append((method, url, token, body))
        or response,
    )

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "list-app-tasks",
            "--app-id",
            "app-1",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
    )

    assert calls == [
        (
            "GET",
            "https://example.com/console/api/v2/tasks/application-tasks",
            "TOKEN",
            None,
        )
    ]
    assert result == [response[0]]


@pytest.mark.parametrize(
    ("argv", "expected_call", "response"),
    [
        (
            [
                "--action",
                "upload-build",
                "--file",
                "/tmp/build.zip",
                "--project-id",
                "project-1",
                "--space-id",
                "space-1",
                "--branch-name",
                "release",
                "--commit-id",
                "abc123",
                "--commit-message",
                "deploy build",
            ],
            (
                "POST",
                "https://example.com/console/api/v2/projects/project-1/assemblies",
                "TOKEN",
                "/tmp/build.zip",
                {
                    "SpaceId": "space-1",
                    "BranchName": "release",
                    "CommitId": "abc123",
                    "CommitMessage": "deploy build",
                },
            ),
            {"id": "assembly-1"},
        ),
    ],
)
def test_main_upload_build_routes_to_binary_request(api, monkeypatch, capsys, argv: list[str], expected_call, response) -> None:
    calls = []

    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(
        api,
        "api_request_binary",
        lambda method, url, token, file_path, params=None: calls.append((method, url, token, file_path, params)) or response,
    )

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [*argv, "--base-url", "https://example.com", "--client-id", "client", "--client-secret", "secret"],
    )

    assert calls == [expected_call]
    assert result == response


def test_upload_without_project_id_blocks_exact_identity_before_binary(
    api, monkeypatch, capsys, tmp_path: Path
) -> None:
    build_path = write_assembly(tmp_path / "TestApp.xasm")
    calls = []

    def fake_request(method, url, token, body=None):
        calls.append((method, url, token, body))
        if url.endswith("/projects"):
            return {
                "projects": [
                    {
                        "id": "group-1",
                        "project-kind": "Group",
                        "space-id": "space-1",
                        "deleted": False,
                    },
                    {
                        "id": "project-1",
                        "project-kind": "Application",
                        "space-id": "space-1",
                        "deleted": False,
                    },
                ]
            }
        assert url.endswith("/projects/project-1/assemblies")
        return {
            "assemblies": [
                {"project-developer": "OldVendor", "project-name": "OldApp"},
                {"project-developer": "Demo", "project-name": "TestApp"},
            ]
        }

    monkeypatch.setattr(api, "api_request", fake_request)
    monkeypatch.setattr(
        api,
        "api_request_binary",
        lambda *_args, **_kwargs: pytest.fail("upload must not be called on identity conflict"),
    )

    result = run_upload_build(
        api, monkeypatch, capsys, build_path, space_id="space-1", expected_exit=1
    )

    assert calls == [
        ("GET", "https://example.com/console/api/v2/projects", "TOKEN", None),
        (
            "GET",
            "https://example.com/console/api/v2/projects/project-1/assemblies",
            "TOKEN",
            None,
        ),
    ]
    assert result["rule_id"] == "deploy.project_identity_conflict"
    assert result["identity"] == {"vendor": "Demo", "name": "TestApp"}
    assert result["project-ids"] == ["project-1"]
    assert "--project-id" in result["details"]


def test_upload_without_project_id_collects_all_exact_identity_conflicts(
    api, monkeypatch, capsys, tmp_path: Path
) -> None:
    build_path = write_assembly(tmp_path / "TestApp.xasm")
    calls = []

    def fake_request(method, url, token, body=None):
        calls.append((method, url, token, body))
        if url.endswith("/projects"):
            return [
                {"id": "project-b", "project-kind": "Application", "deleted": False},
                {"id": "project-a", "project-kind": "Application", "deleted": False},
            ]
        return [{"project-developer": "Demo", "project-name": "TestApp"}]

    monkeypatch.setattr(api, "api_request", fake_request)
    monkeypatch.setattr(
        api,
        "api_request_binary",
        lambda *_args, **_kwargs: pytest.fail("upload must not be called on identity conflict"),
    )

    result = run_upload_build(api, monkeypatch, capsys, build_path, expected_exit=1)

    assert result["project-ids"] == ["project-a", "project-b"]
    assert [call[1] for call in calls] == [
        "https://example.com/console/api/v2/projects",
        "https://example.com/console/api/v2/projects/project-b/assemblies",
        "https://example.com/console/api/v2/projects/project-a/assemblies",
    ]


def test_upload_without_project_id_fails_closed_when_project_listing_fails_without_leaking_details(
    api, monkeypatch, capsys, tmp_path: Path
) -> None:
    build_path = write_assembly(tmp_path / "TestApp.xasm")
    calls = []

    monkeypatch.setattr(
        api,
        "api_request",
        lambda method, url, token, body=None: calls.append((method, url, token, body))
        or {"error": "HTTP 503", "details": {"token": "DO_NOT_PRINT"}},
    )
    monkeypatch.setattr(
        api,
        "api_request_binary",
        lambda *_args, **_kwargs: pytest.fail("upload must not be called when preflight is unavailable"),
    )

    result = run_upload_build(api, monkeypatch, capsys, build_path, expected_exit=1)

    assert len(calls) == 1
    assert result["rule_id"] == "deploy.project_identity_preflight_failed"
    assert "HTTP 503" in result["details"]
    assert "DO_NOT_PRINT" not in json.dumps(result)


@pytest.mark.parametrize(
    ("existing_vendor", "existing_name"),
    [("demo", "TestApp"), ("Demo", "testapp"), ("Other", "TestApp"), ("Demo", "Other")],
)
def test_upload_without_project_id_uses_exact_pair_and_keeps_create_flow_when_unique(
    api,
    monkeypatch,
    capsys,
    tmp_path: Path,
    existing_vendor: str,
    existing_name: str,
) -> None:
    build_path = write_assembly(tmp_path / "TestApp.xasm")
    calls = []

    def fake_request(method, url, token, body=None):
        calls.append((method, url, token, body))
        if url.endswith("/projects"):
            return [{"id": "project-1", "project-kind": "Application", "deleted": False}]
        return [{"project-developer": existing_vendor, "project-name": existing_name}]

    def fake_binary(method, url, token, file_path, params=None):
        calls.append((method, url, token, file_path, params))
        return {"id": "project-new"}

    monkeypatch.setattr(api, "api_request", fake_request)
    monkeypatch.setattr(api, "api_request_binary", fake_binary)

    result = run_upload_build(api, monkeypatch, capsys, build_path, space_id="space-1")

    assert result == {"id": "project-new"}
    assert calls[-1] == (
        "POST",
        "https://example.com/console/api/v2/projects",
        "TOKEN",
        str(build_path),
        {
            "SpaceId": "space-1",
            "BranchName": "",
            "CommitId": "",
            "CommitMessage": "",
        },
    )


@pytest.mark.parametrize(
    "assemblies_response",
    [
        {"error": "HTTP 502", "details": {"token": "DO_NOT_PRINT"}},
        {},
        [],
        [{"project-developer": "Demo"}],
    ],
)
def test_upload_without_project_id_fails_closed_when_project_identity_is_unavailable(
    api,
    monkeypatch,
    capsys,
    tmp_path: Path,
    assemblies_response,
) -> None:
    build_path = write_assembly(tmp_path / "TestApp.xasm")
    calls = []

    def fake_request(method, url, token, body=None):
        calls.append((method, url, token, body))
        if url.endswith("/projects"):
            return [{"id": "project-1", "project-kind": "Application", "deleted": False}]
        return assemblies_response

    monkeypatch.setattr(api, "api_request", fake_request)
    monkeypatch.setattr(
        api,
        "api_request_binary",
        lambda *_args, **_kwargs: pytest.fail("upload must not be called when identity is unavailable"),
    )

    result = run_upload_build(api, monkeypatch, capsys, build_path, expected_exit=1)

    assert len(calls) == 2
    assert result["rule_id"] == "deploy.project_identity_preflight_failed"
    assert "project-1" in result["details"]
    assert "DO_NOT_PRINT" not in json.dumps(result)


@pytest.mark.parametrize(
    "archive_kind",
    ["not_zip", "missing_manifest", "missing_name", "duplicate_manifest", "yaml_escape"],
)
def test_upload_without_project_id_rejects_invalid_local_identity_before_network(
    api,
    monkeypatch,
    capsys,
    tmp_path: Path,
    archive_kind: str,
) -> None:
    build_path = tmp_path / "TestApp.xasm"
    if archive_kind == "not_zip":
        build_path.write_bytes(b"not a zip archive")
    else:
        with zipfile.ZipFile(build_path, "w") as archive:
            if archive_kind != "missing_manifest":
                if archive_kind == "missing_name":
                    manifest = "Vendor: Demo\n"
                elif archive_kind == "yaml_escape":
                    manifest = 'Vendor: "De\\x6do"\nName: TestApp\n'
                else:
                    manifest = "Vendor: Demo\nName: TestApp\n"
                archive.writestr("Assembly.yaml", manifest)
                if archive_kind == "duplicate_manifest":
                    with pytest.warns(UserWarning, match="Duplicate name"):
                        archive.writestr("Assembly.yaml", manifest)

    monkeypatch.setattr(
        api,
        "api_request",
        lambda *_args, **_kwargs: pytest.fail("network must not be called for invalid local identity"),
    )
    monkeypatch.setattr(
        api,
        "api_request_binary",
        lambda *_args, **_kwargs: pytest.fail("upload must not be called for invalid local identity"),
    )

    result = run_upload_build(api, monkeypatch, capsys, build_path, expected_exit=1)

    assert result["rule_id"] == "deploy.project_identity_preflight_failed"


def test_upload_without_project_id_ignores_deleted_and_other_space_projects(
    api, monkeypatch, capsys, tmp_path: Path
) -> None:
    build_path = write_assembly(tmp_path / "TestApp.xasm")
    read_calls = []
    binary_calls = []

    def fake_request(method, url, token, body=None):
        read_calls.append((method, url, token, body))
        assert url.endswith("/projects")
        return [
            {
                "id": "deleted-project",
                "project-kind": "Application",
                "space-id": "space-1",
                "deleted": True,
            },
            {
                "id": "other-space-project",
                "project-kind": "Application",
                "space-id": "space-2",
                "deleted": False,
            },
        ]

    monkeypatch.setattr(api, "api_request", fake_request)
    monkeypatch.setattr(
        api,
        "api_request_binary",
        lambda method, url, token, file_path, params=None: binary_calls.append(
            (method, url, token, file_path, params)
        )
        or {"id": "project-new"},
    )

    result = run_upload_build(api, monkeypatch, capsys, build_path, space_id="space-1")

    assert result == {"id": "project-new"}
    assert len(read_calls) == 1
    assert len(binary_calls) == 1


def test_upload_without_project_id_fails_closed_on_malformed_project_space_id(
    api, monkeypatch, capsys, tmp_path: Path
) -> None:
    build_path = write_assembly(tmp_path / "TestApp.xasm")
    monkeypatch.setattr(
        api,
        "api_request",
        lambda *_args, **_kwargs: [
            {
                "id": "project-1",
                "project-kind": "Application",
                "space-id": {"id": "space-1"},
                "deleted": False,
            }
        ],
    )
    monkeypatch.setattr(
        api,
        "api_request_binary",
        lambda *_args, **_kwargs: pytest.fail("upload must not be called for malformed space id"),
    )

    result = run_upload_build(
        api, monkeypatch, capsys, build_path, space_id="space-1", expected_exit=1
    )

    assert result["rule_id"] == "deploy.project_identity_preflight_failed"
    assert "space id" in result["details"]


def test_upload_with_project_id_skips_identity_preflight(api, monkeypatch, capsys) -> None:
    binary_calls = []
    monkeypatch.setattr(
        api,
        "api_request",
        lambda *_args, **_kwargs: pytest.fail("read-only preflight must be skipped with explicit project id"),
    )
    monkeypatch.setattr(
        api,
        "api_request_binary",
        lambda method, url, token, file_path, params=None: binary_calls.append(
            (method, url, token, file_path, params)
        )
        or {"id": "assembly-1"},
    )

    result = run_upload_build(
        api,
        monkeypatch,
        capsys,
        "/path/need-not-exist.xasm",
        project_id="project-1",
    )

    assert result == {"id": "assembly-1"}
    assert binary_calls[0][1] == "https://example.com/console/api/v2/projects/project-1/assemblies"


def test_main_sync_branch_uses_branch_id_from_env(api, monkeypatch, capsys) -> None:
    calls = []
    monkeypatch.setenv("ELEMENT_BRANCH_ID", "branch-env")
    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(
        api,
        "api_request",
        lambda method, url, token, body=None: calls.append((method, url, token, body)) or {"updated": True},
    )

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "sync-branch",
            "--app-id",
            "app-1",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
    )

    assert calls == [
        (
            "POST",
            "https://example.com/console/ui/module/call?locale=ru",
            "TOKEN",
            {
                "module": "e1c::console::Applications::ApplicationConfigurationUpdateForm",
                "method": "UpdateAppConfiguration",
                "params": [
                    {"type": "e1c::console::Applications::Applications.Reference", "value": "app-1"},
                    {"type": "e1c::console::Team::Branches.Reference", "value": "branch-env"},
                    {"type": "Std::Boolean", "value": False},
                    {"type": "Std::Boolean", "value": False},
                ],
            },
        )
    ]
    assert result == {"updated": True}


def test_main_update_branch_prints_get_error_and_exits(api, monkeypatch, capsys) -> None:
    calls = []

    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(
        api,
        "api_request",
        lambda method, url, token, body=None: calls.append((method, url, token, body)) or {"error": "HTTP 404"},
    )

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "update-branch",
            "--branch-id",
            "branch-1",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
        expected_exit=1,
    )

    assert calls == [("GET", "https://example.com/console/api/v2/branches/branch-1", "TOKEN", None)]
    assert result == {"error": "HTTP 404"}


def test_main_update_branch_prints_unexpected_response_type_and_exits(api, monkeypatch, capsys) -> None:
    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(api, "api_request", lambda *_args, **_kwargs: [{"id": "branch-1"}])

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "update-branch",
            "--branch-id",
            "branch-1",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
        expected_exit=1,
    )

    assert result == {"error": "Unexpected response type"}


def test_main_update_branch_success_uses_current_name_version_and_application(api, monkeypatch, capsys) -> None:
    responses = iter(
        [
            {
                "name": "release",
                "kind": "release",
                "source-branch": {"id": "branch-main", "name": "main"},
                "deletion-mark": False,
                "version-stamp": "v1",
                "application": {"id": "old-app", "name": "Old app", "url": "https://old-app"},
            },
            {"ok": True},
        ]
    )
    calls = []

    def fake_api_request(method, url, token, body=None):
        calls.append((method, url, token, body))
        return next(responses)

    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(api, "api_request", fake_api_request)

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "update-branch",
            "--branch-id",
            "branch-1",
            "--app-id",
            "app-1",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
    )

    assert calls == [
        ("GET", "https://example.com/console/api/v2/branches/branch-1", "TOKEN", None),
        (
            "PUT",
            "https://example.com/console/api/v2/branches/branch-1",
            "TOKEN",
            {
                "name": "release",
                "kind": "release",
                "source-branch": {"id": "branch-main"},
                "deletion-mark": False,
                "version-stamp": "v1",
                "application": {"id": "app-1"},
            },
        ),
    ]
    assert result == {"ok": True}


def test_main_update_branch_falls_back_to_branch_name_without_optional_fields(api, monkeypatch, capsys) -> None:
    responses = iter([{"kind": "development", "application": {"id": "current-app"}}, {"ok": True}])
    calls = []

    def fake_api_request(method, url, token, body=None):
        calls.append((method, url, token, body))
        return next(responses)

    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(api, "api_request", fake_api_request)

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "update-branch",
            "--branch-id",
            "branch-1",
            "--branch-name",
            "fallback",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
    )

    assert calls[1] == (
        "PUT",
        "https://example.com/console/api/v2/branches/branch-1",
        "TOKEN",
        {"name": "fallback", "kind": "development", "application": {"id": "current-app"}},
    )
    assert result == {"ok": True}


def test_main_merge_branch_prints_get_error_and_exits(api, monkeypatch, capsys) -> None:
    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(api, "api_request", lambda *_args, **_kwargs: {"error": "HTTP 409"})

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "merge-branch",
            "--branch-id",
            "branch-1",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
        expected_exit=1,
    )

    assert result == {"error": "HTTP 409"}


def test_main_merge_branch_prints_unexpected_response_type_and_exits(api, monkeypatch, capsys) -> None:
    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(api, "api_request", lambda *_args, **_kwargs: [{"id": "branch-1"}])

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "merge-branch",
            "--branch-id",
            "branch-1",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
        expected_exit=1,
    )

    assert result == {"error": "Unexpected response type"}


def test_main_merge_branch_success_uses_version_stamp(api, monkeypatch, capsys) -> None:
    responses = iter(
        [
            {
                "name": "release",
                "kind": "release",
                "deletion-mark": False,
                "application": {"id": "app-1", "name": "App"},
                "version-stamp": "v2",
            },
            {"merged": True},
        ]
    )
    calls = []

    def fake_api_request(method, url, token, body=None):
        calls.append((method, url, token, body))
        return next(responses)

    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(api, "api_request", fake_api_request)

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "merge-branch",
            "--branch-id",
            "branch-1",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
    )

    assert calls == [
        ("GET", "https://example.com/console/api/v2/branches/branch-1", "TOKEN", None),
        (
            "PUT",
            "https://example.com/console/api/v2/branches/branch-1",
            "TOKEN",
            {
                "name": "release",
                "kind": "release",
                "deletion-mark": False,
                "application": {"id": "app-1"},
                "version-stamp": "v2",
                "write-parameters": {"merge": True},
            },
        ),
    ]
    assert result == {"merged": True}


def test_main_merge_branch_omits_version_stamp_when_missing(api, monkeypatch, capsys) -> None:
    responses = iter([{"kind": "development", "application": {"id": "current-app"}}, {"merged": True}])
    calls = []

    def fake_api_request(method, url, token, body=None):
        calls.append((method, url, token, body))
        return next(responses)

    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")
    monkeypatch.setattr(api, "api_request", fake_api_request)

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "merge-branch",
            "--branch-id",
            "branch-1",
            "--branch-name",
            "fallback",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
    )

    assert calls[1] == (
        "PUT",
        "https://example.com/console/api/v2/branches/branch-1",
        "TOKEN",
        {
            "name": "fallback",
            "kind": "development",
            "application": {"id": "current-app"},
            "write-parameters": {"merge": True},
        },
    )
    assert result == {"merged": True}


def test_main_unknown_action_returns_error(api, monkeypatch, capsys) -> None:
    monkeypatch.setattr(api, "get_token", lambda _args: "TOKEN")

    result = run_main(
        api,
        monkeypatch,
        capsys,
        [
            "--action",
            "unknown-action",
            "--base-url",
            "https://example.com",
            "--client-id",
            "client",
            "--client-secret",
            "secret",
        ],
        expected_exit=1,
    )

    assert result == {"error": "Unknown action: unknown-action"}


def test_script_entrypoint_executes_main(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "api.py",
            "--action",
            "get-token",
            "--base-url",
            "https://example.com",
            "--client-id",
            "entrypoint-client",
            "--client-secret",
            "secret",
        ],
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _request: FakeResponse(b'{"id_token":"ENTRYPOINT_TOKEN","access_token":"Not implemented"}'),
    )

    runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    assert json.loads(capsys.readouterr().out) == {"token": "ENTRYPOINT_TOKEN"}
