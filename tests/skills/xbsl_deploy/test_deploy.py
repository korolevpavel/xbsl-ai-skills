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
SCRIPT_PATH = ROOT_DIR / "skills/xbsl-deploy/scripts/deploy.py"
SKILL_PATH = ROOT_DIR / "skills/xbsl-deploy/SKILL.md"
ENDPOINTS_PATH = ROOT_DIR / "skills/xbsl-deploy/references/endpoints.md"


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


def stub_successful_update_tracking(deploy, monkeypatch) -> None:
    monkeypatch.setattr(
        deploy,
        "application_task_ids",
        lambda _app_id: {"task-before"},
    )
    monkeypatch.setattr(
        deploy,
        "wait_application_update_task",
        lambda _app_id, _baseline_ids, _timeout, task_id="": {
            "id": "task-update",
            "operation-type": "UpdateApplicationConfiguration",
            "status": "Completed",
        },
    )


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
        deploy.subprocess,
        "run",
        lambda cmd, capture_output, text: calls.append(cmd)
        or SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"status": "ok"}),
            stderr="",
        ),
    )

    assert deploy.api("get-app", "--app-id", "app-1") == {"status": "ok"}
    assert calls == [[sys.executable, deploy.API_PY, "--action", "get-app", "--app-id", "app-1"]]


def test_api_exits_on_invalid_json(deploy, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda _cmd, capture_output, text: SimpleNamespace(
            returncode=0, stdout="not-json", stderr=""
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        deploy.api("get-app", "--app-id", "app-1")

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.api_request_failed"
    assert diagnostic["error"] == "Cloud API client returned non-JSON output"


def test_api_exits_on_structured_error_payload(deploy, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda _cmd, capture_output, text: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"error": "HTTP 503", "details": {"message": "service unavailable"}}
            ),
            stderr="",
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        deploy.api("project-update", "--app-id", "app-1", "--version-id", "image-1")

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic == {
        "error": "Cloud API request failed",
        "details": {
            "action": "project-update",
            "api-error": "HTTP 503",
            "api-details": {"message": "service unavailable"},
        },
        "rule_id": "deploy.api_request_failed",
    }


def test_api_preserves_structured_error_from_nonzero_client(
    deploy, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda _cmd, capture_output, text: SimpleNamespace(
            returncode=1,
            stdout=json.dumps(
                {"error": "HTTP 401", "details": {"message": "unauthorized"}}
            ),
            stderr="",
        ),
    )

    with pytest.raises(SystemExit) as exc_info:
        deploy.api("list-builds", "--project-id", "project-1")

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.api_request_failed"
    assert diagnostic["details"] == {
        "action": "list-builds",
        "return-code": 1,
        "api-error": "HTTP 401",
        "api-details": {"message": "unauthorized"},
    }


@pytest.mark.parametrize(
    ("action", "payload"),
    [
        (
            "get-app",
            {
                "id": "app-1",
                "status": "Error",
                "error": "compile failed",
                "details": {"file": "Проект.yaml"},
            },
        ),
        (
            "get-app-task",
            {
                "id": "task-1",
                "status": "Failed",
                "error": "update failed",
                "details": {"stage": "compile"},
            },
        ),
    ],
)
def test_api_does_not_confuse_domain_error_dto_with_transport_error(
    deploy, monkeypatch, action: str, payload: dict
) -> None:
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda _cmd, capture_output, text: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )

    assert deploy.api(action) == payload


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
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.application_update_failed"
    assert diagnostic["details"]["application-error"] == "boom"


def test_poll_status_rejects_target_status_with_non_null_error(
    deploy, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        deploy,
        "api",
        lambda *_args: {
            "status": "Stopped",
            "error": "stop failed",
            "details": {"reason": "locked"},
        },
    )
    monkeypatch.setattr(deploy.time, "time", lambda: 0)

    with pytest.raises(SystemExit) as exc_info:
        deploy.poll_status("app-1", "Stopped", 30)

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.application_update_failed"
    assert diagnostic["details"]["application-details"] == {"reason": "locked"}


def test_poll_status_exits_on_timeout(deploy, monkeypatch, capsys) -> None:
    times = iter([0, 0, 2])
    monkeypatch.setattr(deploy, "api", lambda *_args: {"status": "Starting"})
    monkeypatch.setattr(deploy.time, "time", lambda: next(times))
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)

    with pytest.raises(SystemExit) as exc_info:
        deploy.poll_status("app-1", "Running", 1)

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.application_update_unverified"
    assert diagnostic["details"]["expected-status"] == "Running"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"status": []},
        {"status": "Starting", "source": []},
    ],
)
def test_poll_status_rejects_malformed_application_state(
    deploy, monkeypatch, capsys, payload
) -> None:
    monkeypatch.setattr(deploy, "api", lambda *_args: payload)
    monkeypatch.setattr(deploy.time, "time", lambda: 0)

    with pytest.raises(SystemExit) as exc_info:
        deploy.poll_status("app-1", "Running", 30)

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().err)["rule_id"] == (
        "deploy.application_update_unverified"
    )


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
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.application_update_unverified"
    assert diagnostic["details"]["last-status"] == "Updating"


def test_wait_stable_fails_closed_on_application_error(
    deploy, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        deploy,
        "api",
        lambda *_args: {
            "status": "Error",
            "error": "compile rejected",
            "details": {"file": "Проект.yaml"},
        },
    )
    monkeypatch.setattr(deploy.time, "time", lambda: 0)

    with pytest.raises(SystemExit) as exc_info:
        deploy.wait_stable("app-1", 30)

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.application_update_failed"
    assert diagnostic["details"] == {
        "application-id": "app-1",
        "status": "Error",
        "application-error": "compile rejected",
        "application-details": {"file": "Проект.yaml"},
    }


def test_wait_stable_rejects_malformed_application_state(
    deploy, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(deploy, "api", lambda *_args: ["not-an-application"])
    monkeypatch.setattr(deploy.time, "time", lambda: 0)

    with pytest.raises(SystemExit) as exc_info:
        deploy.wait_stable("app-1", 30)

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().err)["rule_id"] == (
        "deploy.application_update_unverified"
    )


def test_wait_stable_rejects_unknown_application_status(
    deploy, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        deploy,
        "api",
        lambda *_args: {"status": "Suspended", "error": None},
    )
    monkeypatch.setattr(deploy.time, "time", lambda: 0)

    with pytest.raises(SystemExit) as exc_info:
        deploy.wait_stable("app-1", 30)

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.application_update_unverified"
    assert diagnostic["details"]["status"] == "Suspended"


def test_wait_application_update_task_rejects_failed_terminal_task(
    deploy, monkeypatch, capsys
) -> None:
    calls = []

    def fake_api(action, *args):
        calls.append((action, list(args)))
        if action == "list-app-tasks":
            return [
                {
                    "id": "task-new",
                    "application-id": "app-1",
                    "operation-type": "UpdateApplicationConfiguration",
                    "status": "InProgress",
                }
            ]
        if action == "get-app-task":
            return {
                "id": "task-new",
                "operation-type": "UpdateApplicationConfiguration",
                "status": "Failed",
                "error-message": "project rejected",
            }
        raise AssertionError(action)

    monkeypatch.setattr(deploy, "api", fake_api)
    monkeypatch.setattr(deploy.time, "time", lambda: 0)
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)

    with pytest.raises(SystemExit) as exc_info:
        deploy.wait_application_update_task("app-1", {"task-old"}, 30)

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.application_update_failed"
    assert diagnostic["details"] == {
        "task-id": "task-new",
        "operation-type": "UpdateApplicationConfiguration",
        "status": "Failed",
        "error-message": "project rejected",
        "error": None,
        "details": None,
    }
    assert calls == [
        ("list-app-tasks", ["--app-id", "app-1"]),
        ("get-app-task", ["--task-id", "task-new"]),
    ]


def test_wait_application_update_task_polls_exact_task_to_completed(
    deploy, monkeypatch
) -> None:
    detail_responses = iter(
        [
            {
                "id": "task-new",
                "operation-type": "UpdateApplicationConfiguration",
                "status": "InProgress",
                "error-message": "",
            },
            {
                "id": "task-new",
                "operation-type": "UpdateApplicationConfiguration",
                "status": "Completed",
                "error-message": "",
            },
        ]
    )

    def fake_api(action, *_args):
        if action == "list-app-tasks":
            return [
                {
                    "id": "task-new",
                    "operation-type": "UpdateApplicationConfiguration",
                    "status": "InProgress",
                }
            ]
        if action == "get-app-task":
            return next(detail_responses)
        raise AssertionError(action)

    monkeypatch.setattr(deploy, "api", fake_api)
    monkeypatch.setattr(deploy.time, "time", lambda: 0)
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)

    result = deploy.wait_application_update_task("app-1", {"task-old"}, 30)

    assert result["id"] == "task-new"
    assert result["status"] == "Completed"


def test_wait_application_update_task_fails_closed_when_no_new_task(
    deploy, monkeypatch, capsys
) -> None:
    times = iter([0, 0, 2])
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *_args: (
            [{"id": "task-old", "operation-type": "UpdateApplicationConfiguration"}]
            if action == "list-app-tasks"
            else pytest.fail(f"unexpected action: {action}")
        ),
    )
    monkeypatch.setattr(deploy.time, "time", lambda: next(times))
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)

    with pytest.raises(SystemExit) as exc_info:
        deploy.wait_application_update_task("app-1", {"task-old"}, 1)

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.application_update_unverified"
    assert diagnostic["details"]["application-id"] == "app-1"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"task-id": "task-1"}, "task-1"),
        ({"task_id": "task-2"}, "task-2"),
        ({"task": {"id": "task-3"}}, "task-3"),
        ({"current-task": "task-4"}, "task-4"),
        (
            {
                "id": "task-5",
                "operation-type": "UpdateApplicationConfiguration",
            },
            "task-5",
        ),
        ({"id": "application-not-task"}, ""),
        ([{"task-id": "task-6"}], ""),
    ],
)
def test_update_task_id_uses_only_explicit_task_fields(deploy, payload, expected) -> None:
    assert deploy.update_task_id(payload) == expected


def test_wait_application_update_task_uses_explicit_id_without_heuristic_discovery(
    deploy, monkeypatch
) -> None:
    calls = []

    def fake_api(action, *args):
        calls.append((action, list(args)))
        if action == "get-app-task":
            return {
                "id": "task-ours",
                "operation-type": "UpdateApplicationConfiguration",
                "status": "Completed",
            }
        pytest.fail(f"unexpected heuristic action: {action}")

    monkeypatch.setattr(deploy, "api", fake_api)
    monkeypatch.setattr(deploy.time, "time", lambda: 0)

    result = deploy.wait_application_update_task(
        "app-1", {"task-old"}, 30, task_id="task-ours"
    )

    assert result["id"] == "task-ours"
    assert calls == [("get-app-task", ["--task-id", "task-ours"])]


def test_wait_application_update_task_rejects_ambiguous_new_tasks(
    deploy, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *_args: [
                {
                    "id": "task-ours",
                    "operation-type": "UpdateApplicationConfiguration",
                    "status": "InProgress",
                },
                {
                    "id": "task-concurrent",
                    "operation-type": "UpdateApplicationConfiguration",
                    "status": "InProgress",
                },
        ]
        if action == "list-app-tasks"
        else pytest.fail(f"unexpected action: {action}"),
    )
    monkeypatch.setattr(deploy.time, "time", lambda: 0)

    with pytest.raises(SystemExit) as exc_info:
        deploy.wait_application_update_task("app-1", {"task-old"}, 30)

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.application_update_unverified"
    assert diagnostic["details"]["candidate-task-ids"] == [
        "task-concurrent",
        "task-ours",
    ]


@pytest.mark.parametrize("status", ["Cancelled", "Canceled", "Error"])
def test_wait_application_update_task_rejects_all_failure_statuses(
    deploy, monkeypatch, capsys, status: str
) -> None:
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *_args: {
            "id": "task-new",
            "operation-type": "UpdateApplicationConfiguration",
            "status": status,
        }
        if action == "get-app-task"
        else pytest.fail(f"unexpected action: {action}"),
    )
    monkeypatch.setattr(deploy.time, "time", lambda: 0)

    with pytest.raises(SystemExit) as exc_info:
        deploy.wait_application_update_task(
            "app-1", set(), 30, task_id="task-new"
        )

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().err)["rule_id"] == (
        "deploy.application_update_failed"
    )


def test_wait_application_update_task_rejects_mismatched_detail_identity(
    deploy, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *_args: {
            "id": "task-other",
            "operation-type": "UpdateApplicationConfiguration",
            "status": "Completed",
        }
        if action == "get-app-task"
        else pytest.fail(f"unexpected action: {action}"),
    )
    monkeypatch.setattr(deploy.time, "time", lambda: 0)

    with pytest.raises(SystemExit) as exc_info:
        deploy.wait_application_update_task(
            "app-1", set(), 30, task_id="task-expected"
        )

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.application_update_unverified"
    assert diagnostic["details"]["expected-task-id"] == "task-expected"


def test_wait_application_update_task_rejects_malformed_detail_status(
    deploy, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *_args: {
            "id": "task-new",
            "operation-type": "UpdateApplicationConfiguration",
            "status": [],
        }
        if action == "get-app-task"
        else pytest.fail(f"unexpected action: {action}"),
    )
    monkeypatch.setattr(deploy.time, "time", lambda: 0)

    with pytest.raises(SystemExit) as exc_info:
        deploy.wait_application_update_task(
            "app-1", set(), 30, task_id="task-new"
        )

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().err)["rule_id"] == (
        "deploy.application_update_unverified"
    )


@pytest.mark.parametrize(
    "tasks",
    [
        [None],
        [{"id": [], "status": "Completed"}],
        [{"status": "Completed"}],
        [{"id": "task-1"}],
        [{"id": "task-1", "status": []}],
    ],
)
def test_list_application_tasks_rejects_malformed_items(
    deploy, monkeypatch, capsys, tasks
) -> None:
    monkeypatch.setattr(deploy, "api", lambda *_args: tasks)

    with pytest.raises(SystemExit) as exc_info:
        deploy.list_application_tasks("app-1")

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().err)["rule_id"] == (
        "deploy.application_update_unverified"
    )


@pytest.mark.parametrize(
    ("app_data", "expected_fragment", "expected_rule_id"),
    [
        (
            {
                "status": "Running",
                "current-task": None,
                "source": {"project-version-id": "image-1"},
            },
            "error-field-present",
            "deploy.application_update_unverified",
        ),
        (
            {
                "status": "Running",
                "error": "",
                "current-task": None,
                "source": {"project-version-id": "image-1"},
            },
            "application-error",
            "deploy.application_update_failed",
        ),
        (
            {
                "status": "Running",
                "error": None,
                "source": {"project-version-id": "image-1"},
            },
            "current-task-field-present",
            "deploy.application_update_unverified",
        ),
        (
            [],
            "response-type",
            "deploy.application_update_unverified",
        ),
        (
            {
                "status": "Running",
                "error": None,
                "current-task": None,
                "source": [],
            },
            "source-type",
            "deploy.application_update_unverified",
        ),
        (
            {
                "status": "Running",
                "error": None,
                "current-task": None,
                "source": {"project-version-id": "old-image"},
            },
            "actual-version-id",
            "deploy.application_update_unverified",
        ),
        (
            {
                "status": "Running",
                "error": "compile failed",
                "current-task": None,
                "source": {"project-version-id": "image-1"},
            },
            "application-error",
            "deploy.application_update_failed",
        ),
        (
            {
                "status": "Running",
                "error": None,
                "current-task": {"id": "task-pending"},
                "source": {"project-version-id": "image-1"},
            },
            "current-task",
            "deploy.application_update_unverified",
        ),
    ],
)
def test_verify_application_state_fails_closed(
    deploy,
    capsys,
    app_data: object,
    expected_fragment: str,
    expected_rule_id: str,
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        deploy.verify_application_state(app_data, expected_version_id="image-1")

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == expected_rule_id
    assert expected_fragment in diagnostic["details"]


def test_verify_application_state_preserves_final_error_details(
    deploy, capsys
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        deploy.verify_application_state(
            {
                "status": "Running",
                "error": "late failure",
                "details": {"stage": "activate", "file": "Проект.yaml"},
                "current-task": None,
                "source": {"project-version-id": "image-1"},
            },
            expected_version_id="image-1",
        )

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.application_update_failed"
    assert diagnostic["details"]["application-details"] == {
        "stage": "activate",
        "file": "Проект.yaml",
    }


def test_check_deploy_errors_exits_on_recent_failed_task(
    deploy, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *_args: [
            {
                "id": "task-failed",
                "status": "Failed",
                "operation-type": "UpdateApplicationConfiguration",
                "error-message": "Contact administrator for details",
            }
        ]
        if action == "list-app-tasks"
        else pytest.fail(f"unexpected action: {action}"),
    )

    with pytest.raises(SystemExit) as exc_info:
        deploy.check_deploy_errors(
            "app-1",
            {"status": "Running", "error": None, "current-task": None},
            baseline_task_ids={"task-old"},
        )

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.application_update_failed"
    assert diagnostic["details"]["task-id"] == "task-failed"
    assert "Contact administrator" in diagnostic["details"]["error-message"]


def test_check_deploy_errors_ignores_preexisting_failed_task(
    deploy, monkeypatch
) -> None:
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *_args: [
            {
                "id": "task-before",
                "status": "Failed",
                "operation-type": "UpdateApplicationConfiguration",
                "error-message": "historical failure",
            }
        ]
        if action == "list-app-tasks"
        else pytest.fail(f"unexpected action: {action}"),
    )

    deploy.check_deploy_errors(
        "app-1",
        {
            "status": "Running",
            "error": None,
            "current-task": None,
            "source": {"project-version-id": "image-1"},
        },
        baseline_task_ids={"task-before"},
        expected_version_id="image-1",
    )


@pytest.mark.parametrize("status", ["InProgress", "UnexpectedStatus"])
def test_check_deploy_errors_rejects_new_nonterminal_or_unknown_task(
    deploy, monkeypatch, capsys, status: str
) -> None:
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *_args: [
            {
                "id": "task-new",
                "status": status,
                "operation-type": "UpdateApplicationConfiguration",
            }
        ]
        if action == "list-app-tasks"
        else pytest.fail(f"unexpected action: {action}"),
    )

    with pytest.raises(SystemExit) as exc_info:
        deploy.check_deploy_errors(
            "app-1",
            {
                "status": "Running",
                "error": None,
                "current-task": None,
                "source": {"project-version-id": "image-1"},
            },
            baseline_task_ids=set(),
            expected_version_id="image-1",
        )

    assert exc_info.value.code == 1
    diagnostic = json.loads(capsys.readouterr().err)
    assert diagnostic["rule_id"] == "deploy.application_update_unverified"
    assert diagnostic["details"]["status"] == status


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


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"unknown": []},
        {"items": [{}]},
        {"items": [{"assembly-version": ""}]},
        {
            "assemblies": [
                {"assembly-version": "1.0-7"},
                {"status": "Completed"},
            ]
        },
    ],
)
def test_get_last_build_version_rejects_incomplete_payloads(
    deploy, monkeypatch, capsys, payload
) -> None:
    monkeypatch.setattr(deploy, "api", lambda *_args: payload)

    with pytest.raises(SystemExit) as exc_info:
        deploy.get_last_build_version("project-1")

    assert exc_info.value.code == 1
    assert json.loads(capsys.readouterr().err)["rule_id"] == (
        "deploy.api_request_failed"
    )


def test_get_last_build_version_propagates_api_failure(deploy, monkeypatch) -> None:
    monkeypatch.setattr(deploy, "api", lambda *_args: (_ for _ in ()).throw(SystemExit(1)))

    with pytest.raises(SystemExit) as exc_info:
        deploy.get_last_build_version("project-1")

    assert exc_info.value.code == 1


def test_main_stops_before_build_when_build_lookup_fails(
    deploy, monkeypatch, capsys
) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv("ELEMENT_APP_ID", "app-1")
    monkeypatch.setenv("ELEMENT_PROJECT_ID", "project-1")

    def fail_list_builds(action, *_args):
        assert action == "list-builds"
        deploy.fail_deploy(
            "deploy.api_request_failed",
            "Cloud API request failed",
            {"action": action, "api-error": "HTTP 503"},
        )

    monkeypatch.setattr(deploy, "api", fail_list_builds)
    monkeypatch.setattr(
        deploy,
        "run",
        lambda *_args, **_kwargs: pytest.fail("build must not run after lookup failure"),
    )

    captured = run_main(deploy, monkeypatch, capsys, [], expected_exit=1)

    diagnostic = json.loads(captured.err)
    assert diagnostic["rule_id"] == "deploy.api_request_failed"
    assert "▶ Собираем .xasm" not in captured.out
    assert "✓ Деплой завершён" not in captured.out


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
    stub_successful_update_tracking(deploy, monkeypatch)
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
            "project-update": {"task-id": "task-update"},
            "stop-app": {},
            "start-app": {},
            "get-app": {
                "uri": "https://demo.example.com",
                "status": "Running",
                "error": None,
                "current-task": None,
                "source": {"project-version-id": "image-1"},
            },
            "list-app-tasks": [],
        }[action],
    )
    monkeypatch.setattr(
        deploy,
        "get_last_build_version",
        lambda project_id: last_build_queries.append(project_id) or "1.0-3",
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
        ("api", "start-app", ["--app-id", "app-1"]),
        ("api", "get-app", ["--app-id", "app-1"]),
        ("api", "list-app-tasks", ["--app-id", "app-1"]),
    ]
    assert poll_calls == [
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

    def fake_api(action, *extra_args):
        calls.append((action, list(extra_args)))
        if action == "upload-build":
            return {"assembly-id": "image-2"}
        if action == "list-app-tasks":
            tasks = [
                {
                    "id": "task-before",
                    "operation-type": "UpdateApplicationConfiguration",
                    "status": "Completed",
                }
            ]
            if len([call for call in calls if call[0] == "list-app-tasks"]) > 1:
                tasks.extend(
                    [
                        {
                            "id": "task-ours",
                            "operation-type": "UpdateApplicationConfiguration",
                            "status": "Completed",
                        },
                        {
                            "id": "task-concurrent",
                            "operation-type": "UpdateApplicationConfiguration",
                            "status": "Completed",
                        },
                    ]
                )
            return tasks
        if action == "project-update":
            return {"task-id": "task-ours"}
        if action == "get-app-task":
            assert extra_args == ("--task-id", "task-ours")
            return {
                "id": "task-ours",
                "operation-type": "UpdateApplicationConfiguration",
                "status": "Completed",
            }
        if action == "get-app":
            return {
                "uri": "https://running.example.com",
                "status": "Running",
                "error": None,
                "current-task": None,
                "source": {"project-version-id": "image-2"},
            }
        raise AssertionError(action)

    monkeypatch.setattr(deploy, "api", fake_api)
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
        ("list-app-tasks", ["--app-id", "app-1"]),
        ("project-update", ["--app-id", "app-1", "--version-id", "image-2"]),
        ("get-app-task", ["--task-id", "task-ours"]),
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
    stub_successful_update_tracking(deploy, monkeypatch)
    monkeypatch.setattr(deploy, "run", lambda _cmd: str(tmp_path / "demo.xasm"))
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *extra_args: calls.append((action, list(extra_args))) or {
            "upload-build": {"image-id": "image-3"},
            "project-update": {"task-id": "task-update"},
            "start-app": {},
            "get-app": {
                "uri": "https://stopped.example.com",
                "status": "Running",
                "error": None,
                "current-task": None,
                "source": {"project-version-id": "image-3"},
            },
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

    diagnostic = json.loads(captured.err)
    assert diagnostic["rule_id"] == "deploy.api_request_failed"
    assert diagnostic["error"] == "Build upload response has no image identifier"
    assert "✓ Деплой завершён" not in captured.out


def test_main_source_deploy_never_reports_success_for_failed_update_task(
    deploy, monkeypatch, capsys, tmp_path: Path
) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv("ELEMENT_APP_ID", "app-1")
    monkeypatch.setenv("ELEMENT_PROJECT_ID", "project-1")
    monkeypatch.setattr(deploy, "run", lambda _cmd: str(tmp_path / "demo.xasm"))
    monkeypatch.setattr(deploy.time, "time", lambda: 0)
    monkeypatch.setattr(deploy.time, "sleep", lambda _seconds: None)
    calls = []

    def fake_api(action, *extra_args):
        calls.append((action, list(extra_args)))
        if action == "upload-build":
            return {"id": "image-new"}
        if action == "list-app-tasks" and len(
            [call for call in calls if call[0] == "list-app-tasks"]
        ) == 1:
            return [
                {
                    "id": "task-old",
                    "operation-type": "UpdateApplicationConfiguration",
                    "status": "Completed",
                }
            ]
        if action == "project-update":
            return {"task-id": "task-new"}
        if action == "list-app-tasks":
            return [
                {
                    "id": "task-new",
                    "operation-type": "UpdateApplicationConfiguration",
                    "status": "InProgress",
                }
            ]
        if action == "get-app-task":
            return {
                "id": "task-new",
                "operation-type": "UpdateApplicationConfiguration",
                "status": "Failed",
                "error-message": "Ошибка применения проекта",
            }
        raise AssertionError(action)

    monkeypatch.setattr(deploy, "api", fake_api)

    captured = run_main(
        deploy,
        monkeypatch,
        capsys,
        ["--version", "1.0-1"],
        expected_exit=1,
    )

    diagnostic = json.loads(captured.err)
    assert diagnostic["rule_id"] == "deploy.application_update_failed"
    assert diagnostic["details"]["task-id"] == "task-new"
    assert "✓ Деплой завершён" not in captured.out
    assert ("get-app", ["--app-id", "app-1"]) not in calls


@pytest.mark.parametrize(
    ("app_state", "expected_rule_id"),
    [
        (
            {
                "status": "Error",
                "error": "project compile failed",
                "details": {"file": "Проект.yaml"},
                "current-task": None,
            },
            "deploy.application_update_failed",
        ),
        (
            {
                "status": "Suspended",
                "error": None,
                "current-task": None,
            },
            "deploy.application_update_unverified",
        ),
    ],
)
def test_main_source_deploy_does_not_restart_after_unacceptable_state(
    deploy,
    monkeypatch,
    capsys,
    tmp_path: Path,
    app_state: dict,
    expected_rule_id: str,
) -> None:
    set_required_env(monkeypatch)
    monkeypatch.setenv("ELEMENT_APP_ID", "app-1")
    monkeypatch.setenv("ELEMENT_PROJECT_ID", "project-1")
    monkeypatch.setattr(deploy, "run", lambda _cmd: str(tmp_path / "demo.xasm"))
    monkeypatch.setattr(deploy.time, "time", lambda: 0)
    calls = []

    def fake_api(action, *extra_args):
        calls.append((action, list(extra_args)))
        if action == "upload-build":
            return {"id": "image-new"}
        if action == "list-app-tasks":
            return [
                {
                    "id": "task-old",
                    "operation-type": "UpdateApplicationConfiguration",
                    "status": "Completed",
                }
            ]
        if action == "project-update":
            return {"task-id": "task-new"}
        if action == "get-app-task":
            return {
                "id": "task-new",
                "operation-type": "UpdateApplicationConfiguration",
                "status": "Completed",
            }
        if action == "get-app":
            return app_state
        raise AssertionError(action)

    monkeypatch.setattr(deploy, "api", fake_api)

    captured = run_main(
        deploy,
        monkeypatch,
        capsys,
        ["--version", "1.0-1"],
        expected_exit=1,
    )

    diagnostic = json.loads(captured.err)
    assert diagnostic["rule_id"] == expected_rule_id
    if app_state["status"] == "Error":
        assert diagnostic["details"]["application-error"] == (
            "project compile failed"
        )
    assert not any(action in {"stop-app", "start-app"} for action, _ in calls)
    assert "✓ Деплой завершён" not in captured.out


def test_deploy_contract_requires_terminal_task_and_exact_source_verification() -> None:
    skill = SKILL_PATH.read_text(encoding="utf-8")
    endpoints = ENDPOINTS_PATH.read_text(encoding="utf-8")

    assert "deploy.api_request_failed" in skill
    assert "deploy.application_update_failed" in skill
    assert "deploy.application_update_unverified" in skill
    assert "project-version-id" in skill
    assert "/console/api/v2/tasks/application-tasks`" in endpoints
    assert "/console/api/v2/tasks/application-tasks/{id}`" in endpoints
    assert "/console/api/v2/tasks/applications`" not in endpoints
    assert "/console/api/v2/tasks/{id}`" not in endpoints


def test_main_branch_deploy_restarts_when_not_running(deploy, monkeypatch, capsys) -> None:
    set_required_env(monkeypatch)
    calls = []
    poll_calls = []
    monkeypatch.setenv("ELEMENT_APP_ID", "app-1")
    monkeypatch.setenv("ELEMENT_BRANCH_ID", "branch-1")
    stub_successful_update_tracking(deploy, monkeypatch)
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *extra_args: calls.append((action, list(extra_args))) or {
            "sync-branch": {"task-id": "task-update"},
            "start-app": {},
            "get-app": {
                "uri": "https://branch.example.com",
                "status": "Running",
                "error": None,
                "current-task": None,
            },
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
    stub_successful_update_tracking(deploy, monkeypatch)
    monkeypatch.setattr(
        deploy,
        "api",
        lambda action, *extra_args: calls.append((action, list(extra_args))) or {
            "sync-branch": {"task-id": "task-update"},
            "get-app": {
                "uri": "https://branch-running.example.com",
                "status": "Running",
                "error": None,
                "current-task": None,
            },
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
            json.dumps(
                [
                    {
                        "id": "task-old",
                        "application-id": "app-1",
                        "operation-type": "UpdateApplicationConfiguration",
                        "status": "Completed",
                    }
                ]
            ),
            json.dumps({"task-id": "task-new"}),
            json.dumps(
                {
                    "id": "task-new",
                    "operation-type": "UpdateApplicationConfiguration",
                    "status": "Completed",
                    "error-message": "",
                }
            ),
            json.dumps({"status": "Running"}),
            json.dumps(
                {
                    "uri": "https://entrypoint.example.com",
                    "status": "Running",
                    "error": None,
                    "current-task": None,
                }
            ),
            json.dumps(
                [
                    {
                        "id": "task-new",
                        "application-id": "app-1",
                        "operation-type": "UpdateApplicationConfiguration",
                        "status": "Completed",
                    }
                ]
            ),
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
        [sys.executable, str(ROOT_DIR / "skills/xbsl-deploy/scripts/api.py"), "--action", "list-app-tasks", "--app-id", "app-1"],
        [sys.executable, str(ROOT_DIR / "skills/xbsl-deploy/scripts/api.py"), "--action", "sync-branch", "--app-id", "app-1", "--branch-id", "branch-1"],
        [sys.executable, str(ROOT_DIR / "skills/xbsl-deploy/scripts/api.py"), "--action", "get-app-task", "--task-id", "task-new"],
        [sys.executable, str(ROOT_DIR / "skills/xbsl-deploy/scripts/api.py"), "--action", "get-app", "--app-id", "app-1"],
        [sys.executable, str(ROOT_DIR / "skills/xbsl-deploy/scripts/api.py"), "--action", "get-app", "--app-id", "app-1"],
        [sys.executable, str(ROOT_DIR / "skills/xbsl-deploy/scripts/api.py"), "--action", "list-app-tasks", "--app-id", "app-1"],
    ]
    assert "https://entrypoint.example.com" in capsys.readouterr().out
