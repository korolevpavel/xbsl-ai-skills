from __future__ import annotations

import builtins
import importlib.util
import io
import json
import runpy
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT_DIR / ".claude/skills/xbsl-deploy/scripts/api.py"


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
        (["--action", "get-app"], "--app-id required"),
        (["--action", "delete-app"], "--app-id required"),
        (["--action", "start-app"], "--app-id required"),
        (["--action", "stop-app"], "--app-id required"),
        (["--action", "get-branch"], "--branch-id required"),
        (["--action", "create-branch"], "--project-id and --branch-name required"),
        (["--action", "update-branch"], "--branch-id required"),
        (["--action", "delete-branch"], "--branch-id required"),
        (["--action", "merge-branch"], "--branch-id required"),
        (["--action", "create-dump"], "--app-id required"),
        (["--action", "get-dump"], "--app-id and --dump-id required"),
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
                    "development-mode": False,
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
                    "development-mode": False,
                },
            ),
            {"id": "app-2"},
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
            ["--action", "list-projects"],
            ("GET", "https://example.com/console/api/v2/projects", "TOKEN", None),
            [{"id": "project-1"}],
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
                    "project-id": "project-1",
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
                    "project-id": "project-1",
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
                    "project-id": "project-1",
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
