from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPOSITORY_ROOT / ".claude" / "skills" / "xbsl-meta-add"
COVERAGE_PATH = SKILL_ROOT / "object-coverage.json"
RENDERER_PATH = REPOSITORY_ROOT / "scripts" / "render_xbsl_meta_add_coverage.py"


def load_renderer():
    assert RENDERER_PATH.exists(), "missing #89 coverage renderer"
    spec = importlib.util.spec_from_file_location("coverage_renderer", RENDERER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def load_registry() -> dict:
    assert COVERAGE_PATH.exists(), "missing canonical object coverage registry"
    text = COVERAGE_PATH.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "\t" not in text
    return json.loads(text, object_pairs_hook=reject_duplicate_keys)


def test_registry_has_exact_schema_initial_balance_and_safe_paths():
    renderer = load_renderer()
    data = load_registry()

    renderer.validate_coverage_data(data, repo_root=REPOSITORY_ROOT)

    assert list(data) == [
        "schema_version",
        "target_platform",
        "shared_references",
        "objects",
        "routing",
    ]
    assert data["schema_version"] == 2
    assert data["target_platform"] == {
        "name": "1С:Предприятие.Элемент",
        "version": "9.3",
    }
    assert data["shared_references"] == [
        "references/types.md",
        "references/ТабличныеЧасти.md",
        "references/reference-contract.md",
    ]

    objects = data["objects"]
    assert len(objects) == 32
    statuses = {status: 0 for status in ("supported", "partial", "routed")}
    for record in objects:
        statuses[record["status"]] += 1
    assert statuses == {"supported": 31, "partial": 0, "routed": 1}

    routed = [record for record in objects if record["status"] == "routed"]
    assert routed == [
        {
            "element_kind": "ЗапланированноеЗадание",
            "status": "routed",
            "owner_skill": "xbsl-scheduled-task",
            "reference_path": "references/ЗапланированноеЗадание.md",
            "shared_reference_paths": ["references/reference-contract.md"],
            "artifacts": [
                {
                    "pattern": "*.yaml",
                    "role": "описание объекта",
                    "required": True,
                    "basis": "platform",
                },
                {
                    "pattern": "*.xbsl",
                    "role": "модуль обработчика",
                    "required": True,
                    "basis": "platform",
                },
            ],
            "min_version": "9.1",
            "known_gaps": [],
        }
    ]

    assert {route["status"] for route in data["routing"]} == {
        "automatic",
        "out_of_scope",
    }
    assert all(
        route["status"] in {"automatic", "out_of_scope"}
        for route in data["routing"]
    )


def test_registry_is_canonical_json_and_round_trips_byte_identically():
    renderer = load_renderer()
    data = load_registry()
    expected = renderer.dump_canonical_json(data)
    assert COVERAGE_PATH.read_text(encoding="utf-8") == expected
    assert renderer.dump_canonical_json(json.loads(expected)) == expected


def test_repository_does_not_carry_private_audit_manifest():
    private_manifest_name = "object_coverage_" + "provenance.json"
    assert not (Path(__file__).resolve().parent / private_manifest_name).exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update({"extra": True}), "top-level"),
        (lambda data: data.update({"schema_version": 1}), "schema_version"),
        (
            lambda data: data["objects"][0].update({"legacy_audit": True}),
            "expected exact fields",
        ),
        (
            lambda data: data["objects"][0].update({"reference_path": "../escape.md"}),
            "path",
        ),
        (
            lambda data: data["objects"][0].update({"maintainer_note": "local"}),
            "expected exact fields",
        ),
    ],
)
def test_registry_validation_rejects_contract_breaks(mutation, message):
    renderer = load_renderer()
    data = load_registry()
    bad = copy.deepcopy(data)
    mutation(bad)

    with pytest.raises(renderer.CoverageValidationError, match=message):
        renderer.validate_coverage_data(bad, repo_root=REPOSITORY_ROOT)


def test_version_gate_is_numeric_and_rejects_features_above_target():
    renderer = load_renderer()
    data = load_registry()

    allowed = copy.deepcopy(data)
    allowed["objects"][0]["min_version"] = "9.3"
    renderer.validate_coverage_data(allowed, repo_root=REPOSITORY_ROOT)

    too_new = copy.deepcopy(data)
    too_new["objects"][0]["min_version"] = "9.10"
    with pytest.raises(renderer.CoverageValidationError, match="exceeds target"):
        renderer.validate_coverage_data(too_new, repo_root=REPOSITORY_ROOT)


def test_public_skill_artifacts_do_not_reference_local_only_materials():
    forbidden_terms = [
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
        "captured PDF",
        "source" + "-backed",
        "source" + " contract",
        "dev " + "provenance",
        "runtime_verification",
        "Runtime evidence",
        "test-only",
        "fixture",
        "contract-smoke",
        "tracking_issue",
        "#90",
        "#91",
        "#92",
        "#93",
    ]
    scanned = []

    for path in SKILL_ROOT.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix not in {".md", ".json", ".py"}:
            continue
        text = path.read_text(encoding="utf-8")
        scanned.append(path)
        for term in forbidden_terms:
            assert term not in text, f"{path.relative_to(REPOSITORY_ROOT)} contains {term!r}"

    assert scanned
