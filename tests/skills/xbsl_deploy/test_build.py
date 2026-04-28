from __future__ import annotations

import datetime
import importlib.util
import runpy
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT_DIR = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT_DIR / ".claude/skills/xbsl-deploy/scripts/build.py"


def load_build_module():
    spec = importlib.util.spec_from_file_location("build_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run_main(build, monkeypatch, capsys, argv: list[str], expected_exit: int | None = None):
    monkeypatch.setattr(sys, "argv", ["build.py", *argv])

    if expected_exit is None:
        build.main()
    else:
        with pytest.raises(SystemExit) as exc_info:
            build.main()
        assert exc_info.value.code == expected_exit

    return capsys.readouterr()


def write_project_yaml(project_dir: Path, *, vendor: str = "TestVendor", name: str = "DemoApp", version: str = "1.0") -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "Проект.yaml").write_text(
        f"Поставщик: {vendor}\nИмя: {name}\nВерсия: {version}\n",
        encoding="utf-8",
    )


@pytest.fixture
def build():
    return load_build_module()


@pytest.fixture(autouse=True)
def clear_build_env(monkeypatch) -> None:
    monkeypatch.delenv("LAST_BUILD_VERSION", raising=False)


def test_find_project_dir_skips_hidden_and_excluded_dirs(build, tmp_path: Path) -> None:
    (tmp_path / ".git" / "ignored").mkdir(parents=True)
    (tmp_path / ".git" / "ignored" / "Проект.yaml").write_text("Имя: ignored\n", encoding="utf-8")
    (tmp_path / ".hidden" / "ignored").mkdir(parents=True)
    (tmp_path / ".hidden" / "ignored" / "Проект.yaml").write_text("Имя: ignored\n", encoding="utf-8")
    write_project_yaml(tmp_path / "vendor" / "app")

    assert build.find_project_dir(str(tmp_path)) == str(tmp_path / "vendor" / "app")


def test_find_project_dir_returns_none_when_missing(build, tmp_path: Path) -> None:
    (tmp_path / "vendor" / "app").mkdir(parents=True)

    assert build.find_project_dir(str(tmp_path)) is None


def test_parse_simple_yaml_reads_flat_key_values(build, tmp_path: Path) -> None:
    yaml_path = tmp_path / "Проект.yaml"
    yaml_path.write_text(
        "# comment\n"
        "Имя: \"Demo App\"\n"
        "Поставщик: 'Vendor'\n"
        "Версия: 1.2\n"
        "Пусто:\n",
        encoding="utf-8",
    )

    assert build.parse_simple_yaml(str(yaml_path)) == {
        "Имя": "Demo App",
        "Поставщик": "Vendor",
        "Версия": "1.2",
        "Пусто": "",
    }


def test_git_info_returns_commit_and_branch(build, monkeypatch) -> None:
    calls = []

    def fake_check_output(cmd, cwd, text, stderr):
        calls.append((cmd, cwd, text, stderr))
        if cmd == ["git", "rev-parse", "HEAD"]:
            return "abc123\n"
        return "feature/test\n"

    monkeypatch.setattr(build.subprocess, "check_output", fake_check_output)

    assert build.git_info("/repo") == ("abc123", "feature/test")
    assert calls == [
        (["git", "rev-parse", "HEAD"], "/repo", True, build.subprocess.DEVNULL),
        (["git", "rev-parse", "--abbrev-ref", "HEAD"], "/repo", True, build.subprocess.DEVNULL),
    ]


@pytest.mark.parametrize("error_kind", ["missing_git", "called_process"])
def test_git_info_returns_defaults_on_failure(build, monkeypatch, error_kind: str) -> None:
    if error_kind == "missing_git":
        error = FileNotFoundError()
    else:
        error = build.subprocess.CalledProcessError(1, ["git"])

    def fake_check_output(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(build.subprocess, "check_output", fake_check_output)

    assert build.git_info("/repo") == ("", "master")


@pytest.mark.parametrize(
    ("rel_path", "expected"),
    [
        ("acme/demo/Проект.yaml", True),
        ("acme/demo/README.MD", True),
        ("acme/demo/notes.txt", True),
        ("acme/demo/image.png", False),
        ("acme/demo/archive.xasm", False),
        ("acme/demo/.env", False),
        (".git/config", False),
        ("acme/.hidden/file.xbsl", False),
        ("node_modules/pkg/index.xbsl", False),
    ],
)
def test_should_include_filters_paths(build, rel_path: str, expected: bool) -> None:
    assert build.should_include(rel_path) is expected


@pytest.mark.parametrize(
    ("base_version", "last_build", "expected"),
    [
        ("1.0", "1.0-3", "1.0-4"),
        ("1.0", "1.0-bad", "1.0-1"),
        ("1.0", "broken", "1.0-1"),
        ("1.0", "", "1.0-1"),
    ],
)
def test_next_version(build, base_version: str, last_build: str, expected: str) -> None:
    assert build.next_version(base_version, last_build) == expected


def test_build_xasm_creates_expected_archive(build, monkeypatch, tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    project_dir = repo_dir / "acme" / "demo"
    write_project_yaml(project_dir)
    (project_dir / "Проект.xbsl").write_text("Процедура Тест()\nКонецПроцедуры\n", encoding="utf-8")
    (project_dir / "README.md").write_text("# demo\n", encoding="utf-8")
    (project_dir / "notes.txt").write_text("hello\n", encoding="utf-8")
    (project_dir / "image.png").write_bytes(b"\x89PNG")
    (project_dir / ".env").write_text("SECRET=1\n", encoding="utf-8")
    (project_dir / "archive.xasm").write_bytes(b"zip")
    (project_dir / "Основное").mkdir()
    (project_dir / "Основное" / "Модуль.xbsl").write_text("Перем x;\n", encoding="utf-8")
    (project_dir / ".hidden").mkdir()
    (project_dir / ".hidden" / "secret.xbsl").write_text("secret\n", encoding="utf-8")
    (project_dir / ".git").mkdir()
    (project_dir / ".git" / "config").write_text("ignored\n", encoding="utf-8")

    class FixedDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 29, 12, 34, 56, tzinfo=tz)

    monkeypatch.setattr(build.datetime, "datetime", FixedDateTime)

    output_path = build.build_xasm(str(project_dir), str(tmp_path / "out"), "1.0-2", "abc123", "main")

    assert Path(output_path).name == "DemoApp 1.0-2.xasm"
    with zipfile.ZipFile(output_path) as archive:
        names = sorted(archive.namelist())
        assert names == [
            "Assembly.yaml",
            "acme/demo/README.md",
            "acme/demo/notes.txt",
            "acme/demo/Основное/Модуль.xbsl",
            "acme/demo/Проект.xbsl",
            "acme/demo/Проект.yaml",
        ]
        manifest = archive.read("Assembly.yaml").decode("utf-8")
        assert "Vendor: TestVendor" in manifest
        assert "Name: DemoApp" in manifest
        assert "Version: 1.0-2" in manifest
        assert "Created: 2026.03.29 12:34:56" in manifest
        assert "BranchName: main" in manifest
        assert "CommitId: abc123" in manifest


def test_main_requires_project_yaml(build, monkeypatch, capsys, tmp_path: Path) -> None:
    captured = run_main(build, monkeypatch, capsys, ["--project-dir", str(tmp_path)], expected_exit=1)

    assert captured.out == ""
    assert "ERROR: Проект.yaml not found. Use --project-dir" in captured.err


def test_main_uses_explicit_overrides(build, monkeypatch, capsys, tmp_path: Path) -> None:
    project_dir = tmp_path / "repo" / "acme" / "demo"
    write_project_yaml(project_dir, version="2.0")
    calls = []

    monkeypatch.setattr(build, "git_info", lambda _cwd: ("git-commit", "git-branch"))
    monkeypatch.setattr(
        build,
        "build_xasm",
        lambda project_dir, output_dir, version, commit, branch, kind="application": calls.append(
            (project_dir, output_dir, version, commit, branch, kind)
        ) or "/tmp/custom.xasm",
    )

    captured = run_main(
        build,
        monkeypatch,
        capsys,
        [
            "--project-dir",
            str(project_dir),
            "--output",
            "/tmp/out",
            "--version",
            "2.0-5",
            "--commit",
            "override-commit",
            "--branch",
            "release",
        ],
    )

    assert calls == [
        (str(project_dir.resolve()), "/tmp/out", "2.0-5", "override-commit", "release", "application"),
    ]
    assert captured.out.strip() == "/tmp/custom.xasm"
    assert captured.err == ""


def test_main_autofinds_project_and_uses_last_build_env(build, monkeypatch, capsys, tmp_path: Path) -> None:
    project_dir = tmp_path / "repo" / "acme" / "demo"
    write_project_yaml(project_dir, version="3.1")
    calls = []

    monkeypatch.setenv("LAST_BUILD_VERSION", "3.1-9")
    monkeypatch.setattr(build, "find_project_dir", lambda _start: str(project_dir))
    monkeypatch.setattr(build, "git_info", lambda _cwd: ("abc123", "feature/demo"))
    monkeypatch.setattr(
        build,
        "build_xasm",
        lambda project_dir, output_dir, version, commit, branch, kind="application": calls.append(
            (project_dir, output_dir, version, commit, branch, kind)
        ) or "/tmp/auto.xasm",
    )

    captured = run_main(build, monkeypatch, capsys, ["--output", "/tmp/out"])

    assert calls == [
        (str(project_dir.resolve()), "/tmp/out", "3.1-10", "abc123", "feature/demo", "application"),
    ]
    assert captured.out.strip() == "/tmp/auto.xasm"


def test_script_entrypoint_executes_main(monkeypatch, capsys, tmp_path: Path) -> None:
    project_dir = tmp_path / "repo" / "acme" / "demo"
    write_project_yaml(project_dir, version="4.0")
    output_dir = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build.py",
            "--project-dir",
            str(project_dir),
            "--output",
            str(output_dir),
            "--version",
            "4.0-1",
            "--commit",
            "entrypoint-commit",
            "--branch",
            "entrypoint-branch",
        ],
    )

    runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    output_path = Path(capsys.readouterr().out.strip())
    assert output_path.exists()
    with zipfile.ZipFile(output_path) as archive:
        manifest = archive.read("Assembly.yaml").decode("utf-8")
        assert "Version: 4.0-1" in manifest
        assert "CommitId: entrypoint-commit" in manifest
        assert "BranchName: entrypoint-branch" in manifest
