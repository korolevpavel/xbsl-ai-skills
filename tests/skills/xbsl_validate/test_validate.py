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
    assert data["summary"] == {"files": 6, "errors": 3, "warnings": 3}
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
        ("error", "coverage.unknown_type", None),
        ("error", "owner.scheduled_task.missing_companion", None),
        ("error", "owner.scheduled_task.location", None),
    }
    assert sum(
        1
        for diagnostic in data["diagnostics"]
        if diagnostic["rule_id"] == "coverage.out_of_scope"
    ) == 2
    assert all(Path(diagnostic["path"]).is_relative_to(target) for diagnostic in data["diagnostics"])


def test_partial_status_diagnostic_can_be_reported_from_custom_registry():
    validator = load_validator()
    input_file = validator.InputFile(
        actual_path=FIXTURES / "status" / "valid_supported.yaml",
        display_path="partial.yaml",
    )

    diagnostics = validator.validate_coverage_status(
        input_file,
        {"ВидЭлемента": "ЭкспериментальныйОбъект"},
        {"ЭкспериментальныйОбъект": {"status": "partial"}},
        {},
    )

    assert [diagnostic.as_dict() for diagnostic in diagnostics] == [
        {
            "path": "partial.yaml",
            "line": None,
            "severity": "error",
            "rule_id": "coverage.partial",
            "message": "Object type has partial coverage and cannot be fully validated",
        }
    ]


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
    assert "tests/skills/xbsl_validate/fixtures/status/scheduled_missing_companion.yaml" in stdout
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


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("Строка?", True),
        ("Строка|Число", True),
        ("Строка|Число|Булево", True),
        ("Строка|Число|?", True),
        ("Строка|Число|Булево|?", True),
        ("Поступление.Ссылка|Списание.Ссылка|?", True),
        ("Массив<Строка?>", True),
        ("Массив<Поступление.Ссылка|Списание.Ссылка|?>", True),
        ("Массив<Массив<Строка|Число|?>>", True),
        ("Строка|?", False),
        ("Строка|Число?", False),
        ("Строка?|Число", False),
        ("Поступление.Ссылка?|Списание.Ссылка?", False),
        ("Массив<Поступление.Ссылка|Списание.Ссылка?>", False),
        ("Массив<Массив<Строка|Число?>>", False),
        ("?|Строка|Число", False),
        ("Строка|Число|?|?", False),
        ("Строка | Число | ?", False),
        ("Неопределено", False),
        ("Строка|Неопределено", False),
    ],
)
def test_nullable_union_type_grammar(expression, expected):
    validator = load_validator()

    assert validator.valid_type_expression(expression) is expected


@pytest.mark.parametrize(
    "expression",
    [
        "Строка|?",
        "Строка|Число?",
        "Поступление.Ссылка?|Списание.Ссылка?",
        "Неопределено",
        "Строка|Неопределено",
    ],
)
def test_invalid_nullable_union_keeps_stable_cli_rule_id(
    expression, tmp_path, capsys
):
    target = tmp_path / "Тип.yaml"
    target.write_text(
        "ВидЭлемента: Справочник\n"
        "Ид: 11111111-1111-4111-8111-111111111111\n"
        "Имя: ПроверкаТипа\n"
        "Реквизиты:\n"
        "  - Ид: 22222222-2222-4222-8222-222222222222\n"
        "    Имя: Значение\n"
        f"    Тип: {expression}\n",
        encoding="utf-8",
    )

    code, stdout, stderr = run_cli(["--format=json", str(target)], capsys)
    data = parse_json(stdout)

    assert code == 1
    assert stderr == ""
    assert data["summary"] == {"files": 1, "errors": 1, "warnings": 0}
    assert [item["rule_id"] for item in data["diagnostics"]] == ["types.invalid"]
    assert data["diagnostics"][0]["message"] == f"Invalid type expression: {expression}"


def test_schema_routing_precedes_functional_object_common_validation(capsys):
    target = FIXTURES / "schema_routing"

    code, stdout, stderr = run_cli(["--format=json", str(target)], capsys)
    data = parse_json(stdout)

    assert code == 0
    assert stderr == ""
    assert data["summary"] == {"files": 3, "errors": 0, "warnings": 3}
    assert {item["rule_id"] for item in data["diagnostics"]} == {
        "coverage.out_of_scope"
    }
    assert not {
        "common.required_field",
        "types.invalid",
    } & {item["rule_id"] for item in data["diagnostics"]}


def test_functional_object_type_slot_still_uses_types_invalid(capsys):
    target = FIXTURES / "invalid" / "bad_type.yaml"

    code, stdout, stderr = run_cli(["--format=json", str(target)], capsys)
    data = parse_json(stdout)

    assert code == 1
    assert stderr == ""
    assert data["summary"] == {"files": 1, "errors": 1, "warnings": 0}
    assert [item["rule_id"] for item in data["diagnostics"]] == ["types.invalid"]


def test_schema_routing_json_is_deterministic(capsys):
    args = ["--format=json", str(FIXTURES / "schema_routing")]

    first = run_cli(args, capsys)
    second = run_cli(args, capsys)

    assert first == second


def test_supported_object_validators_accept_documented_fixtures(capsys):
    targets = [
        FIXTURES / "object_rules" / "report" / "valid" / "Продажи.yaml",
        FIXTURES / "object_rules" / "register" / "valid" / "Остатки.yaml",
        FIXTURES / "object_rules" / "register" / "valid" / "Курсы.yaml",
        FIXTURES / "object_rules" / "register" / "valid" / "ВыгруженныеДанные.yaml",
        FIXTURES / "object_rules" / "register" / "valid" / "ОборотыБезТипа.yaml",
        FIXTURES / "object_rules" / "scheduled" / "valid" / "ЕжедневнаяОчистка.yaml",
        FIXTURES
        / "object_rules"
        / "scheduled"
        / "valid_mixed"
        / "СмешанноеРасписание.yaml",
        FIXTURES
        / "object_rules"
        / "scheduled"
        / "valid_nested"
        / "Пакет"
        / "ВложенноеЗадание.yaml",
    ]

    code, stdout, stderr = run_cli(["--format=json", *map(str, targets)], capsys)
    data = parse_json(stdout)

    assert code == 0
    assert stderr == ""
    assert data["summary"] == {"files": 8, "errors": 0, "warnings": 0}
    assert data["diagnostics"] == []


def test_report_object_specific_rules_have_stable_ids(capsys):
    root = FIXTURES / "object_rules" / "report"
    targets = [
        root / "invalid_yaml_query" / "ОшибочныйЗапрос.yaml",
        root / "missing_companion" / "БезЗапроса.yaml",
        root / "table_without_source" / "ТабличныйОтчет.yaml",
        root / "parameter_mismatch" / "ПараметризованныйОтчет.yaml",
        root / "invalid_interface" / "ОтчетСИнтерфейсом.yaml",
        root / "missing_parameter_type" / "ПараметрБезТипа.yaml",
        root / "query_with_source" / "ЗапросСИсточником.yaml",
    ]

    code, stdout, stderr = run_cli(["--format=json", *map(str, targets)], capsys)
    data = parse_json(stdout)

    assert code == 1
    assert stderr == ""
    assert data["summary"] == {"files": 7, "errors": 7, "warnings": 0}
    assert sorted(item["rule_id"] for item in data["diagnostics"]) == sorted(
        [
            "owner.report.source",
            "owner.report.query_companion",
            "owner.report.source",
            "owner.report.query_parameters",
            "owner.report.interface",
            "owner.report.query_parameters",
            "owner.report.source",
        ]
    )


def test_register_object_specific_rules_have_stable_ids(capsys):
    root = FIXTURES / "object_rules" / "register"
    targets = [
        root / "missing_dimensions" / "ПустыеИзмерения.yaml",
        root / "missing_resources" / "ПустыеРесурсы.yaml",
        root / "bad_member" / "НеверныйЭлемент.yaml",
        root / "bad_uuid" / "НеверныйИдентификатор.yaml",
        root / "bad_resource_type" / "СтроковыйРесурс.yaml",
        root / "missing_registrar" / "БезРегистратора.yaml",
        root / "bad_kind" / "НеверныйВид.yaml",
    ]

    code, stdout, stderr = run_cli(["--format=json", *map(str, targets)], capsys)
    data = parse_json(stdout)

    assert code == 1
    assert stderr == ""
    assert data["summary"] == {"files": 7, "errors": 7, "warnings": 0}
    assert sorted(item["rule_id"] for item in data["diagnostics"]) == sorted(
        [
            "owner.register.dimensions",
            "owner.register.resources",
            "owner.register.member",
            "owner.register.invalid_uuid",
            "owner.register.resource_type",
            "owner.register.registrar",
            "owner.register.kind",
        ]
    )


@pytest.mark.parametrize(
    ("collection", "rule_id"),
    [
        ("Измерения", "owner.register.dimensions"),
        ("Ресурсы", "owner.register.resources"),
        ("Реквизиты", "owner.register.member"),
    ],
)
def test_null_register_collections_are_diagnostics_instead_of_a_crash(
    collection, rule_id, tmp_path, capsys
):
    target = tmp_path / f"{collection}.yaml"
    target.write_text(
        "ВидЭлемента: РегистрСведений\n"
        "Ид: 22911111-1111-4111-8111-111111111111\n"
        "Имя: ПроверкаNull\n"
        f"{collection}: null\n",
        encoding="utf-8",
    )

    code, stdout, stderr = run_cli(["--format=json", str(target)], capsys)
    data = parse_json(stdout)

    assert code == 1
    assert stderr == ""
    assert data["summary"] == {"files": 1, "errors": 1, "warnings": 0}
    assert [item["rule_id"] for item in data["diagnostics"]] == [rule_id]


def test_non_scalar_discriminators_are_stable_diagnostics(tmp_path, capsys):
    report = tmp_path / "Отчет.yaml"
    report.write_text(
        "ВидЭлемента: Отчет\n"
        "Ид: 23111111-1111-4111-8111-111111111111\n"
        "Имя: Отчет\n"
        "ВидИсточникаДанных: []\n",
        encoding="utf-8",
    )
    register = tmp_path / "Регистр.yaml"
    register.write_text(
        "ВидЭлемента: РегистрНакопления\n"
        "Ид: 23211111-1111-4111-8111-111111111111\n"
        "Имя: Регистр\n"
        "ВидРегистра: []\n"
        "Измерения:\n"
        "  - Ид: 23311111-1111-4111-8111-111111111111\n"
        "    Имя: Аналитика\n"
        "    Тип: Строка\n"
        "Ресурсы:\n"
        "  - Ид: 23411111-1111-4111-8111-111111111111\n"
        "    Имя: Сумма\n"
        "Реквизиты:\n"
        "  - Имя: Регистратор\n"
        "    Тип: Документ.Ссылка?\n",
        encoding="utf-8",
    )
    subsystem = tmp_path / "Подсистема.yaml"
    subsystem.write_text("Интерфейс: {}\n", encoding="utf-8")
    scheduled = tmp_path / "Задание.yaml"
    scheduled.write_text(
        "ВидЭлемента: ЗапланированноеЗадание\n"
        "Ид: 23511111-1111-4111-8111-111111111111\n"
        "Имя: Задание\n"
        "Расписание:\n"
        "  - Вид: []\n",
        encoding="utf-8",
    )
    scheduled.with_suffix(".xbsl").write_text(
        "@Обработчик\nметод Обработчик()\n;\n", encoding="utf-8"
    )

    code, stdout, stderr = run_cli(
        ["--format=json", str(report), str(register), str(scheduled)], capsys
    )
    data = parse_json(stdout)

    assert code == 1
    assert stderr == ""
    assert data["summary"] == {"files": 3, "errors": 3, "warnings": 0}
    assert sorted(item["rule_id"] for item in data["diagnostics"]) == sorted(
        [
            "owner.report.source",
            "owner.register.kind",
            "owner.scheduled_task.schedule",
        ]
    )


@pytest.mark.parametrize(
    "type_value", ["ДвоичныйОбъект.Ссылка?", "Пользователи.Ссылка?"]
)
def test_registrar_rejects_known_non_document_references(type_value):
    validator = load_validator()

    assert validator.reference_registrar_type(type_value) is False


def test_scheduled_task_object_specific_rules_have_stable_ids(capsys):
    root = FIXTURES / "object_rules" / "scheduled"
    targets = [
        root / "quoted_time" / "СтроковоеВремя.yaml",
        root / "missing_schedule" / "БезРасписания.yaml",
        root / "invalid_schedule" / "НеверноеРасписание.yaml",
        root / "invalid_location" / "КорневоеЗадание.yaml",
        root / "yaml_handler" / "ОбработчикВYaml.yaml",
        root / "wrong_handler" / "ОбработчикСПараметром.yaml",
        root / "wrong_handler_binding" / "НепривязанныйОбработчик.yaml",
    ]

    code, stdout, stderr = run_cli(["--format=json", *map(str, targets)], capsys)
    data = parse_json(stdout)

    assert code == 1
    assert stderr == ""
    assert data["summary"] == {"files": 7, "errors": 7, "warnings": 0}
    assert sorted(item["rule_id"] for item in data["diagnostics"]) == sorted(
        [
            "owner.scheduled_task.time_literal",
            "owner.scheduled_task.schedule",
            "owner.scheduled_task.schedule",
            "owner.scheduled_task.location",
            "owner.scheduled_task.yaml_handler",
            "owner.scheduled_task.handler",
            "owner.scheduled_task.handler",
        ]
    )


@pytest.mark.parametrize(
    "entry",
    [
        "        Вид: Однократно\n",
        "        Вид: Однократно\n        ЗапуститьВ: foo\n",
        (
            "        Вид: Однократно\n"
            '        ЗапуститьВ: "2026-08-27T10:00:00Z"\n'
        ),
        "        Вид: Периодическое\n",
        "        Вид: Периодическое\n        Период: foo\n",
        "        Вид: Периодическое\n        Период: 500мс\n",
        "        Вид: Периодическое\n        Период: " + "9" * 5000 + "с\n",
        "        Вид: Еженедельно\n        ЗапуститьВ: 08:00\n",
        "        Вид: Ежемесячно\n        ЗапуститьВ: 08:00\n",
        (
            "        Вид: Ежемесячно\n"
            "        ЗапуститьВ: 08:00\n"
            "        Месяцы: [Январь]\n"
        ),
    ],
)
def test_schedule_kinds_require_documented_fields(entry, tmp_path, capsys):
    subsystem = tmp_path / "Подсистема.yaml"
    subsystem.write_text("Интерфейс: {}\n", encoding="utf-8")
    target = tmp_path / "Задание.yaml"
    target.write_text(
        "ВидЭлемента: ЗапланированноеЗадание\n"
        "Ид: 23611111-1111-4111-8111-111111111111\n"
        "Имя: Задание\n"
        "Расписание:\n"
        "    -\n"
        f"{entry}",
        encoding="utf-8",
    )
    target.with_suffix(".xbsl").write_text(
        "@Обработчик\nметод Обработчик()\n;\n", encoding="utf-8"
    )

    code, stdout, stderr = run_cli(["--format=json", str(target)], capsys)
    data = parse_json(stdout)

    assert code == 1
    assert stderr == ""
    assert data["summary"] == {"files": 1, "errors": 1, "warnings": 0}
    assert [item["rule_id"] for item in data["diagnostics"]] == [
        "owner.scheduled_task.schedule"
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1с", True),
        ("+3с", True),
        ("1ч30м5с", True),
        ("999999999999999мс", True),
        ("0с", False),
        ("500мс", False),
        ("-3с", False),
        ("1000000000000000мс", False),
        ("9" * 5000 + "с", False),
    ],
)
def test_positive_duration_literal_bounds(value, expected):
    validator = load_validator()

    assert validator.valid_positive_duration_literal(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0000-12-31 06:00:00.000 Z", True),
        ("2026-08-27T10:00:00Z", True),
        ("2025-05-01 23:30:40.345 UTC+3", True),
        ("4000-01-01 17:59:59.999 Z", True),
        ("4001-01-01 00:00:00 Z", False),
        ("2026-08-27 9:00 Z", False),
        ("foo", False),
    ],
)
def test_moment_literal_shape_and_bound_years(value, expected):
    validator = load_validator()

    assert validator.valid_moment_literal(value) is expected


def test_scheduled_task_unreadable_companion_is_a_stable_diagnostic(
    monkeypatch, capsys
):
    target = (
        FIXTURES
        / "object_rules"
        / "scheduled"
        / "valid"
        / "ЕжедневнаяОчистка.yaml"
    )
    companion = target.with_suffix(".xbsl")
    original_read_text = Path.read_text

    def read_text(path, *args, **kwargs):
        if path == companion:
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    code, stdout, stderr = run_cli(["--format=json", str(target)], capsys)
    data = parse_json(stdout)

    assert code == 1
    assert stderr == ""
    assert data["summary"] == {"files": 1, "errors": 1, "warnings": 0}
    assert [item["rule_id"] for item in data["diagnostics"]] == [
        "owner.scheduled_task.unreadable_companion"
    ]


def test_object_specific_json_is_deterministic(capsys):
    target = (
        FIXTURES
        / "object_rules"
        / "report"
        / "parameter_mismatch"
        / "ПараметризованныйОтчет.yaml"
    )
    args = ["--format=json", str(target)]

    first = run_cli(args, capsys)
    second = run_cli(args, capsys)

    assert first == second
