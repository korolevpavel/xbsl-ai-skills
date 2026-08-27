from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCHEDULED_SKILL_ROOT = REPOSITORY_ROOT / ".claude" / "skills" / "xbsl-scheduled-task"
META_SKILL_ROOT = REPOSITORY_ROOT / ".claude" / "skills" / "xbsl-meta-add"
COVERAGE_PATH = META_SKILL_ROOT / "object-coverage.json"
VALIDATOR_PATH = (
    REPOSITORY_ROOT
    / ".claude"
    / "skills"
    / "xbsl-validate"
    / "scripts"
    / "validate.py"
)
FIXTURES = Path(__file__).resolve().parent / "fixtures"

REFERENCE_SECTIONS = [
    "Назначение",
    "Версия",
    "YAML",
    "UUID",
    "Imports и visibility",
    "Companion artifacts",
    "Генерация",
    "Валидация",
]

PUBLIC_FORBIDDEN_TERMS = [
    "xbsl-docs",
    "mcp__",
    "xbsl_docs",
    "doc_key",
    "indexed",
    "source" + "_catalog",
    "official" + "_element_",
    "documentation" + "_verified_on",
    "## Версия и источники",
    "| Claim | Источник |",
    "Проверено",
    "source" + "-backed",
    "source" + " contract",
    "dev " + "provenance",
    "runtime_verification",
    "Runtime evidence",
    "test-only",
    "fixture",
    "contract-smoke",
    "tracking_issue",
    "#3",
    "#90",
    "#91",
    "#92",
    "#93",
    "/Users/",
]


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def construct_mapping_without_duplicates(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_mapping_without_duplicates,
)


def load_yaml(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)


def load_registry() -> dict:
    return json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))


def record_for(kind: str) -> dict:
    return next(
        record for record in load_registry()["objects"] if record["element_kind"] == kind
    )


def section_names(text: str) -> list[str]:
    return re.findall(r"(?m)^## (.+?)\s*$", text)


def collect_uuid_values(value) -> set[str]:
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    if isinstance(value, dict):
        result = set()
        for item in value.values():
            result |= collect_uuid_values(item)
        return result
    if isinstance(value, list):
        result = set()
        for item in value:
            result |= collect_uuid_values(item)
        return result
    if isinstance(value, str) and uuid_pattern.fullmatch(value):
        return {value}
    return set()


def load_validator():
    assert VALIDATOR_PATH.exists(), "missing xbsl-validate CLI"
    spec = importlib.util.spec_from_file_location("xbsl_validate", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_json(stdout: str) -> dict:
    data = json.loads(stdout)
    assert list(data) == ["schema_version", "diagnostics", "summary"]
    return data


def test_registry_routes_scheduled_task_to_ready_owner_without_local_gap():
    record = record_for("ЗапланированноеЗадание")

    assert record["status"] == "routed"
    assert record["owner_skill"] == "xbsl-scheduled-task"
    assert record["reference_path"] == "references/ЗапланированноеЗадание.md"
    assert record["shared_reference_paths"] == ["references/reference-contract.md"]
    assert record["known_gaps"] == []
    assert record["min_version"] == "9.1"
    assert {artifact["pattern"] for artifact in record["artifacts"]} == {
        "*.yaml",
        "*.xbsl",
    }

    assert SCHEDULED_SKILL_ROOT.is_dir()
    assert not (META_SKILL_ROOT / "references" / "ЗапланированноеЗадание.md").exists()


def test_public_scheduled_task_skill_declares_owner_workflow_and_reference():
    skill_path = SCHEDULED_SKILL_ROOT / "SKILL.md"
    reference_path = SCHEDULED_SKILL_ROOT / "references" / "ЗапланированноеЗадание.md"

    skill_text = skill_path.read_text(encoding="utf-8")
    reference_text = reference_path.read_text(encoding="utf-8")

    assert skill_text.startswith("---\nname: xbsl-scheduled-task\n")
    assert "Use when" in skill_text
    assert "xbsl-explore" in skill_text
    assert "xbsl-uuid" in skill_text
    assert "<Имя>.yaml" in skill_text
    assert "<Имя>.xbsl" in skill_text
    assert "не перезаписывай" in skill_text
    assert "references/ЗапланированноеЗадание.md" in skill_text

    assert section_names(reference_text) == REFERENCE_SECTIONS
    assert "Platform facts:" in reference_text
    assert "Local conventions:" in reference_text
    assert "Минимальная версия платформы: 9.1+" in reference_text


def test_public_scheduled_task_artifacts_do_not_reference_local_only_materials():
    scanned = []

    for path in SCHEDULED_SKILL_ROOT.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix not in {".md", ".json", ".py"}:
            continue
        text = path.read_text(encoding="utf-8")
        scanned.append(path)
        for term in PUBLIC_FORBIDDEN_TERMS:
            assert term not in text, f"{path.relative_to(REPOSITORY_ROOT)} contains {term!r}"
        assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
        assert not re.search(r"(?i)(api[_-]?key|secret|token)\s*[:=]", text)

    assert scanned


def test_minimal_daily_scheduled_task_fixture_matches_contract_and_validator(capsys):
    root = FIXTURES / "minimal"
    yaml_path = root / "ЗапланированноеЗадание.yaml"
    module_path = root / "ЗапланированноеЗадание.xbsl"
    data = load_yaml(yaml_path)

    assert data == {
        "ВидЭлемента": "ЗапланированноеЗадание",
        "Ид": "33333333-3333-4333-8333-333333333331",
        "Имя": "ЕжедневнаяОчистка",
        "ОбластьВидимости": "ВПодсистеме",
        "ПредопределенноеЗадание": "ЗапланироватьПриОбновленииПроекта",
        "Расписание": [
            {
                "Вид": "Ежедневно",
                "ЗапуститьВ": "08:00",
                "ПериодПовтораДней": 1,
            }
        ],
    }
    assert collect_uuid_values(data) == {"33333333-3333-4333-8333-333333333331"}
    assert "Обработчик" not in yaml_path.read_text(encoding="utf-8")

    module_text = module_path.read_text(encoding="utf-8")
    assert re.search(r"(?m)^@Обработчик\s*$", module_text)
    assert re.search(r"(?m)^\s*метод\s+Обработчик\s*\(\s*\)", module_text)
    assert not re.search(r"(?m)^\s*метод\s+Обработчик\s*\([^)]*\S[^)]*\)", module_text)

    validator = load_validator()
    assert validator.main([str(yaml_path)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_time_literals_are_unquoted_in_public_contract_and_fixtures():
    fixture_name = "ЗапланированноеЗадание.yaml"
    paths = [
        SCHEDULED_SKILL_ROOT / "SKILL.md",
        SCHEDULED_SKILL_ROOT / "references" / "ЗапланированноеЗадание.md",
        FIXTURES / "minimal" / fixture_name,
        FIXTURES / "negative" / "handler_with_parameters" / fixture_name,
        FIXTURES / "negative" / "missing_companion" / fixture_name,
        FIXTURES / "negative" / "missing_handler" / fixture_name,
        FIXTURES / "negative" / "wrong_handler_name" / fixture_name,
    ]
    unquoted_time = re.compile(
        r"(?m)^\s*ЗапуститьВ:\s+(?:[01]\d|2[0-3]):[0-5]\d\s*$"
    )
    quoted_time = re.compile(
        r'''(?m)^\s*ЗапуститьВ:\s*["'](?:[01]\d|2[0-3]):[0-5]\d["']\s*$'''
    )

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert unquoted_time.search(text), str(path)
        assert quoted_time.search(text) is None, str(path)


@pytest.mark.parametrize(
    ("case", "rule_id", "message"),
    [
        (
            "missing_companion",
            "owner.scheduled_task.missing_companion",
            "Scheduled task companion .xbsl file is required",
        ),
        (
            "missing_handler",
            "owner.scheduled_task.handler",
            "Scheduled task companion must define Обработчик() without parameters",
        ),
        (
            "wrong_handler_name",
            "owner.scheduled_task.handler",
            "Scheduled task companion must define Обработчик() without parameters",
        ),
        (
            "handler_with_parameters",
            "owner.scheduled_task.handler",
            "Scheduled task companion must define Обработчик() without parameters",
        ),
    ],
)
def test_negative_handler_cases_are_reported_by_validator(case, rule_id, message, capsys):
    yaml_path = FIXTURES / "negative" / case / "ЗапланированноеЗадание.yaml"

    validator = load_validator()
    assert validator.main(["--format=json", str(yaml_path)]) == 1
    data = parse_json(capsys.readouterr().out)

    assert data["diagnostics"] == [
        {
            "path": str(yaml_path),
            "line": None,
            "severity": "error",
            "rule_id": rule_id,
            "message": message,
        }
    ]
