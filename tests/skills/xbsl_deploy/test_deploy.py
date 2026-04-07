from __future__ import annotations

import importlib.util
import json
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT_DIR / ".claude/skills/xbsl-deploy/scripts/deploy.py"


def load_deploy_module():
    spec = importlib.util.spec_from_file_location("deploy_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_main(deploy, monkeypatch, capsys, argv: list[str], expected_exit: int | None = None):
    monkeypatch.setattr(sys, "argv", ["deploy.py", *argv])

    if expected_exit is None:
        deploy.main()
    else:
        with pytest.raises(SystemExit) as exc_info:
            deploy.main()
        assert exc_info.value.code == expected_exit

    return capsys.readouterr()


@pytest.fixture
def deploy():
    return load_deploy_module()


@pytest.fixture(autouse=True)
def clear_deploy_env(monkeypatch) -> None:
    for key in (
        "ELEMENT_BASE_URL",
        "ELEMENT_CLIENT_ID",
        "ELEMENT_CLIENT_SECRET",
        "ELEMENT_APP_ID",
        "ELEMENT_PROJECT_ID",
        "ELEMENT_BRANCH_ID",
        "LAST_BUILD_VERSION",
    ):
        monkeypatch.delenv(key, raising=False)


def set_required_env(monkeypatch) -> None:
    monkeypatch.setenv("ELEMENT_BASE_URL", "https://example.com")
    monkeypatch.setenv("ELEMENT_CLIENT_ID", "client")
    monkeypatch.setenv("ELEMENT_CLIENT_SECRET", "secret")


def test_run_returns_stdout_on_success(deploy, monkeypatch) -> None:
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda cmd, capture_output, text: SimpleNamespace(returncode=0, stdout="ok\n", stderr=""),
    )

    assert deploy.run(["python3", "tool.py"]) == "ok"


@pytest.mark.parametrize(
    ("stderr_text", "stdout_text", "expected_fragment"),
    [
        ("boom", "", "boom"),
        ("", "fallback stdout", "fallback stdout"),
    ],
)
def test_run_exits_on_failure(deploy, monkeypatch, capsys, stderr_text: str, stdout_text: str, expected_fragment: str) -> None:
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda cmd, capture_output, text: SimpleNamespace(returncode=1, stdout=stdout_text, stderr=stderr_text),
    )

    with pytest.raises(SystemExit) as exc_info:
        deploy.run(["python3", "tool.py", "--flag"])

    assert exc_info.value.code == 1
    assert expected_fragment in capsys.readouterr().err


def test_api_invokes_script_and_parses_json(deploy, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        deploy,
        "run",
        lambda cmd: calls.append(cmd) or json.dumps({"status": "ok"}),
    )

    assert deploy.api("get-app", "--app-id", "app-1") == {"status": "ok"}
    assert calls == [[sys.executable, deploy.API_PY, "--action", "get-app", "--app-id", "app-1"]]


def test_api_exits_on_invalid_json(deploy, monkeypatch, capsys) -> None:
    monkeypatch.setattr(deploy, "run", lambda _cmd: "not-json")

    with pytest.raises(SystemExit) as exc_info:
        deploy.api("get-app", "--app-id", "app-1")

    assert exc_info.value.code == 1
    assert "ERROR: api.py returned non-JSON" in capsys.readouterr().err


def test_poll_status_returns_target(deploy, monkeypatch, capsys) -> None:
    responses = iter([{"status": "Starting"}, {"status": "Running"}])
    monkeypatch.setattr(deploy, "api", lambda *_args: next(responses))
    monkeypatch.setattr(deploy.time, "time", lambda: 0)
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)

    assert deploy.poll_status("app-1", "Running", 30) == "Running"
    assert "статус: Starting" in capsys.readouterr().out


def test_poll_status_exits_on_error(deploy, monkeypatch, capsys) -> None:
    monkeypatch.setattr(deploy, "api", lambda *_args: {"status": "Error", "error": "boom"})
    monkeypatch.setattr(deploy.time, "time", lambda: 0)

    with pytest.raises(SystemExit) as exc_info:
        deploy.poll_status("app-1", "Running", 30)

    assert exc_info.value.code == 1
    assert "ERROR: приложение в статусе Error: boom" in capsys.readouterr().err


def test_poll_status_exits_on_timeout(deploy, monkeypatch, capsys) -> None:
    times = iter([0, 0, 2])
    monkeypatch.setattr(deploy, "api", lambda *_args: {"status": "Starting"})
    monkeypatch.setattr(deploy.time, "time", lambda: next(times))
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)

    with pytest.raises(SystemExit) as exc_info:
        deploy.poll_status("app-1", "Running", 1)

    assert exc_info.value.code == 1
    assert "ERROR: таймаут ожидания статуса Running" in capsys.readouterr().err


def test_wait_stable_returns_first_non_transitional_status(deploy, monkeypatch) -> None:
    responses = iter([{"status": "Updating"}, {"status": "Stopped"}])
    monkeypatch.setattr(deploy, "api", lambda *_args: next(responses))
    monkeypatch.setattr(deploy.time, "time", lambda: 0)
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)

    assert deploy.wait_stable("app-1", 30) == "Stopped"


def test_wait_stable_exits_on_timeout(deploy, monkeypatch, capsys) -> None:
    times = iter([0, 0, 2])
    monkeypatch.setattr(deploy, "api", lambda *_args: {"status": "Updating"})
    monkeypatch.setattr(deploy.time, "time", lambda: next(times))
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)

    with pytest.raises(SystemExit) as exc_info:
        deploy.wait_stable("app-1", 1)

    assert exc_info.value.code == 1
    assert "ERROR: таймаут ожидания стабильного статуса" in capsys.readouterr().err


@pytest.mark.parametrize(
    "payload",
    [
        [{"assembly-version": "1.0-2"}, {"assembly-version": "1.0-10"}, {"assembly-version": "broken"}],
        {"items": [{"assembly-version": "1.0-1"}, {"assembly-version": "1.0-7"}]},
        {"assemblies": [{"assembly-version": "1.0-3"}, {"assembly-version": "1.0-4"}]},
    ],
)
def test_get_last_build_version_reads_supported_payload_shapes(deploy, monkeypatch, payload) -> None:
    monkeypatch.setattr(deploy, "api", lambda *_args: payload)

    assert deploy.get_last_build_version("project-1").endswith(("-10", "-7", "-4"))


def test_get_last_build_version_returns_empty_on_api_failure(deploy, monkeypatch) -> None:
    monkeypatch.setattr(deploy, "api", lambda *_args: (_ for _ in ()).throw(SystemExit(1)))

    assert deploy.get_last_build_version("project-1") == ""


@pytest.mark.parametrize(
    "missing_var",
    ["ELEMENT_BASE_URL", "ELEMENT_CLIENT_ID", "ELEMENT_CLIENT_SECRET"],
)
def test_main_requires_base_environment(deploy, monkeypatch, capsys, missing_var: str) -> None:
    set_required_env(monkeypatch)
    monkeypatch.delenv(missing_var, raising=False)

    captured = run_main(
        deploy,
        monkeypatch,
        capsys,
        ["--dry-run", "--version", "1.0-1"],
        expected_exit=1,
    )

    assert f"ERROR: не задана переменная окружения {missing_var}" in captured.err


def test_main_requires_app_id_when_not_dry_run(deploy, monkeypatch, capsys) -> None:
    set_required_env(monkeypatch)

    captured = run_main(
        deploy,
        monkeypatch,
        capsys,
        ["--project-id", "project-1", "--version", "1.0-1"],
        expected_exit=1,
    )

    assert "ERROR: --app-id или ELEMENT_APP_ID обязателен" in captured.err


def test_main_requires_project_id_for_source_deploy(deploy, monkeypatch, capsys) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv("ELEMENT_APP_ID", "app-1")

    captured = run_main(
        deploy,
        monkeypatch,
        capsys,
        ["--version", "1.0-1"],
        expected_exit=1,
    )

    assert "ERROR: --project-id или ELEMENT_PROJECT_ID обязателен" in captured.err


def test_main_requires_branch_id_for_branch_deploy(deploy, monkeypatch, capsys) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv("ELEMENT_APP_ID", "app-1")

    captured = run_main(
        deploy,
        monkeypatch,
        capsys,
        ["--from-branch"],
        expected_exit=1,
    )

    assert "ERROR: --branch-id или ELEMENT_BRANCH_ID обязателен для --from-branch" in captured.err


def test_main_dry_run_builds_and_skips_deploy(deploy, monkeypatch, capsys, tmp_path: Path) -> None:
    set_required_env(monkeypatch)
    calls = []
    monkeypatch.setattr(deploy, "api", lambda *_args, **_kwargs: pytest.fail("api should not be called"))
    monkeypatch.setattr(deploy, "run", lambda cmd: calls.append(cmd) or str(tmp_path / "demo.xasm"))

    captured = run_main(
        deploy,
        monkeypatch,
        capsys,
        [
            "--dry-run",
            "--project-dir",
            "/repo/acme/demo",
            "--output",
            str(tmp_path / "out"),
            "--version",
            "1.0-9",
            "--branch",
            "release",
            "--commit",
            "abc123",
        ],
    )

    assert calls == [[
        sys.executable,
        deploy.BUILD_PY,
        "--output",
        str(tmp_path / "out"),
        "--version",
        "1.0-9",
        "--project-dir",
        "/repo/acme/demo",
        "--commit",
        "abc123",
        "--branch",
        "release",
    ]]
    assert "Dry-run завершён. Деплой пропущен." in captured.out


def test_main_source_deploy_restarts_manually_when_needed(deploy, monkeypatch, capsys, tmp_path: Path) -> None:
    set_required_env(monkeypatch)
    calls = []
    poll_calls = []
    last_build_queries = []
    monkeypatch.setenv("ELEMENT_APP_ID", "app-1")
    monkeypatch.setenv("ELEMENT_PROJECT_ID", "project-1")
    monkeypatch.setattr(
        deploy,
        "run",
        lambda cmd: calls.append(("run", cmd)) or str(tmp_path / "demo.xasm"),
    )
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *extra_args: calls.append(("api", action, list(extra_args))) or {
            "upload-build": {"id": "image-1"},
            "project-update": {},
            "stop-app": {},
            "start-app": {},
            "get-app": {"uri": "https://demo.example.com"},
            "list-app-tasks": [],
        }[action],
    )
    monkeypatch.setattr(
        deploy,
        "get_last_build_version",
        lambda project_id: last_build_queries.append(project_id) or "1.0-3",
    )
    monkeypatch.setattr(deploy, "wait_stable", lambda _app_id, _timeout: "Frozen")
    monkeypatch.setattr(
        deploy,
        "poll_status",
        lambda app_id, target, timeout: poll_calls.append((app_id, target, timeout)) or target,
    )

    captured = run_main(
        deploy,
        monkeypatch,
        capsys,
        [
            "--project-dir",
            "/repo/acme/demo",
            "--branch",
            "release",
            "--commit",
            "abc123",
            "--commit-message",
            "deploy build",
        ],
    )

    assert last_build_queries == ["project-1"]
    assert calls == [
        (
            "run",
            [
                sys.executable,
                deploy.BUILD_PY,
                "--output",
                "/tmp/xasm-build",
                "--last-build",
                "1.0-3",
                "--project-dir",
                "/repo/acme/demo",
                "--commit",
                "abc123",
                "--branch",
                "release",
            ],
        ),
        (
            "api",
            "upload-build",
            [
                "--file",
                str(tmp_path / "demo.xasm"),
                "--project-id",
                "project-1",
                "--branch-name",
                "release",
                "--commit-id",
                "abc123",
                "--commit-message",
                "deploy build",
            ],
        ),
        ("api", "project-update", ["--app-id", "app-1", "--version-id", "image-1"]),
        ("api", "stop-app", ["--app-id", "app-1"]),
        ("api", "start-app", ["--app-id", "app-1"]),
        ("api", "get-app", ["--app-id", "app-1"]),
        ("api", "list-app-tasks", ["--app-id", "app-1"]),
    ]
    assert poll_calls == [
        ("app-1", "Stopped", deploy.STOP_TIMEOUT),
        ("app-1", "Running", deploy.START_TIMEOUT),
    ]
    assert "✓ Деплой завершён. Приложение доступно: https://demo.example.com" in captured.out


def test_main_source_deploy_skips_restart_when_platform_already_running(deploy, monkeypatch, capsys, tmp_path: Path) -> None:
    set_required_env(monkeypatch)
    calls = []
    monkeypatch.setenv("ELEMENT_APP_ID", "app-1")
    monkeypatch.setenv("ELEMENT_PROJECT_ID", "project-1")
    monkeypatch.setenv("LAST_BUILD_VERSION", "1.0-4")
    monkeypatch.setattr(deploy, "run", lambda cmd: str(tmp_path / "demo.xasm"))
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *extra_args: calls.append((action, list(extra_args))) or {
            "upload-build": {"assembly-id": "image-2"},
            "project-update": {},
            "get-app": {"uri": "https://running.example.com"},
            "list-app-tasks": [],
        }[action],
    )
    monkeypatch.setattr(deploy, "wait_stable", lambda _app_id, _timeout: "Running")
    monkeypatch.setattr(deploy, "poll_status", lambda *_args: pytest.fail("poll_status should not be called"))
    monkeypatch.setattr(
        deploy,
        "get_last_build_version",
        lambda _project_id: pytest.fail("get_last_build_version should not be called when LAST_BUILD_VERSION is set"),
    )

    captured = run_main(deploy, monkeypatch, capsys, [])

    assert calls == [
        ("upload-build", ["--file", str(tmp_path / "demo.xasm"), "--project-id", "project-1"]),
        ("project-update", ["--app-id", "app-1", "--version-id", "image-2"]),
        ("get-app", ["--app-id", "app-1"]),
        ("list-app-tasks", ["--app-id", "app-1"]),
    ]
    assert "Приложение уже запущено платформой после обновления" in captured.out


def test_main_source_deploy_restarts_without_stop_when_already_stopped(deploy, monkeypatch, capsys, tmp_path: Path) -> None:
    set_required_env(monkeypatch)
    calls = []
    poll_calls = []
    monkeypatch.setenv("ELEMENT_APP_ID", "app-1")
    monkeypatch.setenv("ELEMENT_PROJECT_ID", "project-1")
    monkeypatch.setattr(deploy, "run", lambda _cmd: str(tmp_path / "demo.xasm"))
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *extra_args: calls.append((action, list(extra_args))) or {
            "upload-build": {"image-id": "image-3"},
            "project-update": {},
            "start-app": {},
            "get-app": {"uri": "https://stopped.example.com"},
            "list-app-tasks": [],
        }[action],
    )
    monkeypatch.setattr(deploy, "wait_stable", lambda _app_id, _timeout: "Stopped")
    monkeypatch.setattr(
        deploy,
        "poll_status",
        lambda app_id, target, timeout: poll_calls.append((app_id, target, timeout)) or target,
    )

    captured = run_main(
        deploy,
        monkeypatch,
        capsys,
        ["--version", "1.0-1"],
    )

    assert calls == [
        ("upload-build", ["--file", str(tmp_path / "demo.xasm"), "--project-id", "project-1"]),
        ("project-update", ["--app-id", "app-1", "--version-id", "image-3"]),
        ("start-app", ["--app-id", "app-1"]),
        ("get-app", ["--app-id", "app-1"]),
        ("list-app-tasks", ["--app-id", "app-1"]),
    ]
    assert poll_calls == [("app-1", "Running", deploy.START_TIMEOUT)]
    assert "✓ Деплой завершён. Приложение доступно: https://stopped.example.com" in captured.out


def test_main_source_deploy_requires_image_id(deploy, monkeypatch, capsys, tmp_path: Path) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv("ELEMENT_APP_ID", "app-1")
    monkeypatch.setenv("ELEMENT_PROJECT_ID", "project-1")
    monkeypatch.setattr(deploy, "run", lambda _cmd: str(tmp_path / "demo.xasm"))
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *extra_args: {"upload-build": {"status": "ok"}}[action],
    )
    monkeypatch.setattr(deploy, "wait_stable", lambda *_args: pytest.fail("wait_stable should not be called"))

    captured = run_main(
        deploy,
        monkeypatch,
        capsys,
        ["--version", "1.0-1"],
        expected_exit=1,
    )

    assert "ERROR: не удалось получить image-id из ответа" in captured.err


def test_main_branch_deploy_restarts_when_not_running(deploy, monkeypatch, capsys) -> None:
    set_required_env(monkeypatch)
    calls = []
    poll_calls = []
    monkeypatch.setenv("ELEMENT_APP_ID", "app-1")
    monkeypatch.setenv("ELEMENT_BRANCH_ID", "branch-1")
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *extra_args: calls.append((action, list(extra_args))) or {
            "sync-branch": {},
            "start-app": {},
            "get-app": {"uri": "https://branch.example.com"},
            "list-app-tasks": [],
        }[action],
    )
    monkeypatch.setattr(deploy, "wait_stable", lambda _app_id, _timeout: "Stopped")
    monkeypatch.setattr(
        deploy,
        "poll_status",
        lambda app_id, target, timeout: poll_calls.append((app_id, target, timeout)) or target,
    )

    captured = run_main(deploy, monkeypatch, capsys, ["--from-branch"])

    assert calls == [
        ("sync-branch", ["--app-id", "app-1", "--branch-id", "branch-1"]),
        ("start-app", ["--app-id", "app-1"]),
        ("get-app", ["--app-id", "app-1"]),
        ("list-app-tasks", ["--app-id", "app-1"]),
    ]
    assert poll_calls == [("app-1", "Running", deploy.START_TIMEOUT)]
    assert "✓ Деплой завершён. Приложение доступно: https://branch.example.com" in captured.out


def test_main_branch_deploy_skips_restart_when_already_running(deploy, monkeypatch, capsys) -> None:
    set_required_env(monkeypatch)
    calls = []
    monkeypatch.setenv("ELEMENT_APP_ID", "app-1")
    monkeypatch.setenv("ELEMENT_BRANCH_ID", "branch-1")
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *extra_args: calls.append((action, list(extra_args))) or {
            "sync-branch": {},
            "get-app": {"uri": "https://branch-running.example.com"},
            "list-app-tasks": [],
        }[action],
    )
    monkeypatch.setattr(deploy, "wait_stable", lambda _app_id, _timeout: "Running")
    monkeypatch.setattr(deploy, "poll_status", lambda *_args: pytest.fail("poll_status should not be called"))

    captured = run_main(deploy, monkeypatch, capsys, ["--from-branch"])

    assert calls == [
        ("sync-branch", ["--app-id", "app-1", "--branch-id", "branch-1"]),
        ("get-app", ["--app-id", "app-1"]),
        ("list-app-tasks", ["--app-id", "app-1"]),
    ]
    assert "✓ Деплой завершён. Приложение доступно: https://branch-running.example.com" in captured.out


def test_script_entrypoint_executes_main(monkeypatch, capsys) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv("ELEMENT_APP_ID", "app-1")
    monkeypatch.setenv("ELEMENT_BRANCH_ID", "branch-1")
    calls = []
    responses = iter(
        [
            json.dumps({}),
            json.dumps({"status": "Running"}),
            json.dumps({"uri": "https://entrypoint.example.com"}),
            json.dumps([]),
        ]
    )

    monkeypatch.setattr(sys, "argv", ["deploy.py", "--from-branch"])
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, capture_output, text: calls.append(cmd) or SimpleNamespace(
            returncode=0,
            stdout=next(responses),
            stderr="",
        ),
    )

    runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    assert calls == [
        [sys.executable, str(ROOT_DIR / ".claude/skills/xbsl-deploy/scripts/api.py"), "--action", "sync-branch", "--app-id", "app-1", "--branch-id", "branch-1"],
        [sys.executable, str(ROOT_DIR / ".claude/skills/xbsl-deploy/scripts/api.py"), "--action", "get-app", "--app-id", "app-1"],
        [sys.executable, str(ROOT_DIR / ".claude/skills/xbsl-deploy/scripts/api.py"), "--action", "get-app", "--app-id", "app-1"],
        [sys.executable, str(ROOT_DIR / ".claude/skills/xbsl-deploy/scripts/api.py"), "--action", "list-app-tasks", "--app-id", "app-1"],
    ]
    assert "https://entrypoint.example.com" in capsys.readouterr().out
