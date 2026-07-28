from __future__ import annotations

import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VALIDATOR_PATH = (
    REPOSITORY_ROOT
    / ".claude"
    / "skills"
    / "xbsl-validate"
    / "scripts"
    / "validate.py"
)
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_validator_from(path: Path):
    assert path.exists(), "missing xbsl-validate CLI"
    spec = importlib.util.spec_from_file_location("xbsl_validate", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_validator():
    return load_validator_from(VALIDATOR_PATH)


def run_cli(args: list[str], capsys):
    validator = load_validator()
    code = validator.main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def parse_json(stdout: str) -> dict:
    data = json.loads(stdout)
    assert list(data) == ["schema_version", "diagnostics", "summary"]
    for diagnostic in data["diagnostics"]:
        assert list(diagnostic) == ["path", "line", "severity", "rule_id", "message"]
    assert list(data["summary"]) == ["files", "errors", "warnings"]
    return data


def snapshot_tree(root: Path) -> dict[str, tuple[int, int, bytes]]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            result[path.relative_to(root).as_posix()] = (
                stat.st_mode,
                stat.st_mtime_ns,
                path.read_bytes(),
            )
    return result


def test_argument_errors_are_deterministic_and_format_aware(capsys):
    code, stdout, stderr = run_cli([], capsys)
    assert code == 2
    assert stdout == ""
    assert stderr == "cli.arguments: At least one PATH is required\n"

    code, stdout, stderr = run_cli(["--format", "json"], capsys)
    assert code == 2
    assert stderr == ""
    assert parse_json(stdout) == {
        "schema_version": 1,
        "diagnostics": [
            {
                "path": "",
                "line": None,
                "severity": "error",
                "rule_id": "cli.arguments",
                "message": "At least one PATH is required",
            }
        ],
        "summary": {"files": 0, "errors": 1, "warnings": 0},
    }

    for args in (
        ["--format=json", "--format", "xml", str(FIXTURES / "valid_supported")],
        ["--format", "xml", "--format=json", str(FIXTURES / "valid_supported")],
    ):
        code, stdout, stderr = run_cli(args, capsys)
        assert code == 2
        assert stderr == ""
        data = parse_json(stdout)
        assert data["diagnostics"][0]["message"] == "option --format may be specified once"

    code, stdout, stderr = run_cli(["--format", "xml", str(FIXTURES / "valid_supported")], capsys)
    assert code == 2
    assert stdout == ""
    assert stderr == "cli.arguments: invalid --format value: xml; expected text or json\n"

    code, stdout, stderr = run_cli(["--format"], capsys)
    assert code == 2
    assert stdout == ""
    assert stderr == "cli.arguments: option --format requires a value\n"

    code, stdout, stderr = run_cli(["--zeta", "--alpha", "--zeta"], capsys)
    assert code == 2
    assert stdout == ""
    assert stderr == "cli.arguments: Unknown option(s): --alpha, --zeta\n"


def test_valid_supported_fixture_and_empty_directory_are_clean(tmp_path, capsys):
    code, stdout, stderr = run_cli([str(FIXTURES / "valid_supported")], capsys)
    assert code == 0
    assert stdout == ""
    assert stderr == ""

    empty = tmp_path / "empty"
    empty.mkdir()
    code, stdout, stderr = run_cli(["--format=json", str(empty)], capsys)
    assert code == 0
    assert stderr == ""
    assert parse_json(stdout) == {
        "schema_version": 1,
        "diagnostics": [],
        "summary": {"files": 0, "errors": 0, "warnings": 0},
    }


def test_installed_skill_layout_uses_sibling_coverage_registry(tmp_path, capsys):
    skills_root = tmp_path / "skills"
    installed_validator_dir = skills_root / "xbsl-validate" / "scripts"
    installed_registry_dir = skills_root / "xbsl-meta-add"
    installed_validator_dir.mkdir(parents=True)
    installed_registry_dir.mkdir()
    installed_validator = installed_validator_dir / "validate.py"
    installed_registry = installed_registry_dir / "object-coverage.json"
    shutil.copy2(VALIDATOR_PATH, installed_validator)
    shutil.copy2(
        REPOSITORY_ROOT / ".claude" / "skills" / "xbsl-meta-add" / "object-coverage.json",
        installed_registry,
    )

    validator = load_validator_from(installed_validator)
    code = validator.main([str(FIXTURES / "valid_supported")])
    captured = capsys.readouterr()

    assert validator.COVERAGE_PATH == installed_registry
    assert code == 0
    assert captured.out == ""
    assert captured.err == ""


def test_common_yaml_type_and_duplicate_key_errors(capsys):
    code, stdout, stderr = run_cli([str(FIXTURES / "invalid")], capsys)

    assert code == 2
    assert stderr == ""
    lines = stdout.splitlines()
    assert lines == sorted(lines)
    assert any(": yaml.duplicate_key: Duplicate key: Имя" in line for line in lines)
    assert any(": yaml.parse: Failed to parse YAML" in line for line in lines)
    assert any(": yaml.root_mapping: YAML root must be a mapping" in line for line in lines)
    assert any(": common.required_field: Missing required field: ВидЭлемента" in line for line in lines)
    assert any(": common.element_kind: ВидЭлемента must be a non-empty string" in line for line in lines)
    assert any(": common.invalid_uuid: Invalid UUID in field Ид" in line for line in lines)
    assert any(": types.invalid: Invalid type expression: Массив<>" in line for line in lines)
    assert "coverage.unknown_type" not in stdout


def test_json_envelope_uses_stable_summary_sorting_and_paths(capsys):
    target = FIXTURES / "status"
    code, stdout, stderr = run_cli(["--format", "json", str(target)], capsys)

    assert code == 1
    assert stderr == ""
    data = parse_json(stdout)
    assert data["summary"] == {"files": 7, "errors": 3, "warnings": 3}
    assert data["diagnostics"] == sorted(
        data["diagnostics"],
        key=lambda item: (
            item["path"],
            item["line"] if item["line"] is not None else 10**9,
            item["rule_id"],
            item["message"],
        ),
    )
    assert {
        (diagnostic["severity"], diagnostic["rule_id"], diagnostic["line"])
        for diagnostic in data["diagnostics"]
    } == {
        ("warning", "coverage.automatic", None),
        ("warning", "coverage.out_of_scope", None),
        ("error", "coverage.partial", None),
        ("error", "coverage.unknown_type", None),
        ("error", "owner.scheduled_task.missing_companion", None),
    }
    assert sum(
        1
        for diagnostic in data["diagnostics"]
        if diagnostic["rule_id"] == "coverage.out_of_scope"
    ) == 2
    assert all(Path(diagnostic["path"]).is_relative_to(target) for diagnostic in data["diagnostics"])


def test_routed_owner_adapter_can_pass_and_can_be_reported_unavailable(monkeypatch, capsys):
    validator = load_validator()
    valid_job = FIXTURES / "scheduled_valid" / "ЗапланированноеЗадание.yaml"

    assert validator.main([str(valid_job)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

    monkeypatch.setattr(validator, "ROUTED_VALIDATORS", {})
    assert validator.main(["--format=json", str(valid_job)]) == 1
    data = parse_json(capsys.readouterr().out)
    assert data["diagnostics"] == [
        {
            "path": str(valid_job),
            "line": None,
            "severity": "error",
            "rule_id": "coverage.route_unavailable",
            "message": "No validator adapter registered for owner skill: xbsl-scheduled-task",
        }
    ]


def test_input_errors_are_code_2_and_independent_files_continue(tmp_path, capsys):
    missing = tmp_path / "missing.yaml"
    not_yaml = tmp_path / "note.txt"
    not_yaml.write_text("hello\n", encoding="utf-8")
    valid = FIXTURES / "valid_supported" / "Справочник.yaml"

    code, stdout, stderr = run_cli([str(missing), str(not_yaml), str(valid)], capsys)

    assert code == 2
    assert stderr == ""
    assert f"{missing}: input.not_found: Input path does not exist" in stdout
    assert f"{not_yaml}: input.not_yaml: Explicit file is not a .yaml file" in stdout
    assert "Справочник.yaml" not in stdout


def test_display_paths_follow_user_inputs(capsys):
    absolute_file = (FIXTURES / "invalid" / "bad_uuid.yaml").resolve()
    relative_dir = Path("tests/skills/xbsl_validate/fixtures/status")

    code, stdout, stderr = run_cli([str(absolute_file), str(relative_dir)], capsys)

    assert code == 1
    assert stderr == ""
    assert str(absolute_file) in stdout
    assert "tests/skills/xbsl_validate/fixtures/status/partial.yaml" in stdout
    assert "/private/var/" not in stdout


def test_cli_is_read_only_and_deterministic(tmp_path, capsys):
    source = FIXTURES / "unicode_tree"
    target = tmp_path / "Юникод"
    shutil.copytree(source, target)
    before = snapshot_tree(target)

    first = run_cli(["--format=json", str(target)], capsys)
    second = run_cli(["--format=json", str(target)], capsys)

    assert first == second
    assert snapshot_tree(target) == before
