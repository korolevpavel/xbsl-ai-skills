#!/usr/bin/env python3
"""Validate and render the xbsl-meta-add object coverage registry."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPOSITORY_ROOT / ".claude" / "skills" / "xbsl-meta-add"
COVERAGE_PATH = SKILL_ROOT / "object-coverage.json"
OUTPUT_PATH = SKILL_ROOT / "object-coverage.md"

TOP_LEVEL_FIELDS = [
    "schema_version",
    "target_platform",
    "source_catalog",
    "shared_references",
    "objects",
    "routing",
]
SOURCE_CATALOG_FIELDS = [
    "documented_platform_version",
    "base_url",
]
OBJECT_FIELDS = [
    "element_kind",
    "status",
    "owner_skill",
    "reference_path",
    "shared_reference_paths",
    "artifacts",
    "sources",
    "min_version",
    "documentation_verified_on",
    "known_gaps",
]
ARTIFACT_FIELDS = ["pattern", "role", "required", "basis"]
SOURCE_FIELDS = ["source_catalog", "claims"]
ROUTING_FIELDS = ["category", "status", "route_to", "examples", "reason"]
SHARED_REFERENCES = [
    "references/types.md",
    "references/ТабличныеЧасти.md",
    "references/reference-contract.md",
]
REFERENCE_CONTRACT_SECTIONS = [
    "Назначение",
    "Версия и источники",
    "YAML",
    "UUID",
    "Imports и visibility",
    "Companion artifacts",
    "Генерация",
    "Валидация",
]


class CoverageValidationError(ValueError):
    """Raised when coverage registry data violates the #89 contract."""


def _fail(message: str) -> None:
    raise CoverageValidationError(message)


def _require_type(value: Any, expected_type: type, path: str) -> None:
    if not isinstance(value, expected_type):
        _fail(f"{path}: expected {expected_type.__name__}")


def _require_exact_keys(record: Mapping[str, Any], fields: Sequence[str], path: str) -> None:
    if list(record) != list(fields):
        _fail(f"{path}: expected exact fields {list(fields)}")


def _require_non_empty_string(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value:
        _fail(f"{path}: expected non-empty string")


def _require_string_list(value: Any, path: str, *, non_empty: bool) -> None:
    if not isinstance(value, list):
        _fail(f"{path}: expected array")
    if non_empty and not value:
        _fail(f"{path}: expected non-empty array")
    seen: set[str] = set()
    for index, item in enumerate(value):
        _require_non_empty_string(item, f"{path}[{index}]")
        if item in seen:
            _fail(f"{path}: duplicate value {item!r}")
        seen.add(item)


def _require_iso_date(value: Any, path: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        _fail(f"{path}: expected YYYY-MM-DD date")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        _fail(f"{path}: invalid date {error}")


def _is_safe_relative_path(value: str) -> bool:
    if "\x00" in value or not value:
        return False
    candidate = PurePosixPath(value)
    if candidate.is_absolute():
        return False
    return all(part not in {"", ".", ".."} for part in candidate.parts)


def _require_safe_path(value: Any, path: str) -> None:
    _require_non_empty_string(value, path)
    if not _is_safe_relative_path(value):
        _fail(f"{path}: unsafe path")


def _require_https_base(value: Any, path: str) -> None:
    _require_non_empty_string(value, path)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        _fail(f"{path}: expected absolute HTTPS base URL")
    if not value.endswith("/"):
        _fail(f"{path}: base URL must end with /")


def _validate_url_source(url: str, catalog: Mapping[str, Any], path: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query:
        _fail(f"{path}: expected canonical versioned HTTPS URL")

    page_url = url.split("#", maxsplit=1)[0]
    base_url = catalog["base_url"]
    if not page_url.startswith(base_url):
        _fail(f"{path}: URL is outside source_catalog base")
    version = catalog["documented_platform_version"]
    parsed_page = urlparse(page_url)
    if f"/{version}/docs/" not in parsed_page.path:
        _fail(f"{path}: URL must use versioned path segment {version}")
    if "/latest/" in parsed_page.path:
        _fail(f"{path}: latest URL is not versioned")


def validate_reference_contract(text: str) -> None:
    sections = re.findall(r"(?m)^## (.+?)\s*$", text)
    if sections != REFERENCE_CONTRACT_SECTIONS:
        _fail("reference contract must contain exactly eight sections in order")
    if "Не применяется — <source-backed reason>" not in text:
        _fail("reference contract must require a source-backed reason")
    if re.search(r"Не применяется(?! — <source-backed reason>)", text):
        _fail("Не применяется must include a source-backed reason")


def _validate_source_catalog(data: Mapping[str, Any]) -> None:
    _require_type(data, dict, "source_catalog")
    if not data:
        _fail("source_catalog: expected non-empty object")
    for source_id, source in data.items():
        _require_non_empty_string(source_id, f"source_catalog key {source_id!r}")
        _require_type(source, dict, f"source_catalog.{source_id}")
        _require_exact_keys(source, SOURCE_CATALOG_FIELDS, f"source_catalog.{source_id}")
        if source["documented_platform_version"] not in {"9.1", "9.2"}:
            _fail(f"source_catalog.{source_id}.documented_platform_version: invalid version")
        _require_https_base(source["base_url"], f"source_catalog.{source_id}.base_url")


def _validate_artifact(artifact: Any, path: str) -> None:
    _require_type(artifact, dict, path)
    _require_exact_keys(artifact, ARTIFACT_FIELDS, path)
    _require_non_empty_string(artifact["pattern"], f"{path}.pattern")
    _require_non_empty_string(artifact["role"], f"{path}.role")
    if not isinstance(artifact["required"], bool):
        _fail(f"{path}.required: expected boolean")
    if artifact["basis"] not in {"platform", "skill"}:
        _fail(f"{path}.basis: invalid basis")


def _validate_source(source: Any, catalog: Mapping[str, Any], path: str) -> None:
    _require_type(source, dict, path)
    if set(source) != {*SOURCE_FIELDS, "path"} and set(source) != {*SOURCE_FIELDS, "url"}:
        _fail(f"{path}: expected source_catalog, claims and exactly one of path/url")
    source_id = source["source_catalog"]
    if source_id not in catalog:
        _fail(f"{path}.source_catalog: unknown source_catalog {source_id!r}")
    _require_string_list(source["claims"], f"{path}.claims", non_empty=True)
    if "path" in source:
        _require_safe_path(source["path"], f"{path}.path")
    else:
        _require_non_empty_string(source["url"], f"{path}.url")
        _validate_url_source(source["url"], catalog[source_id], f"{path}.url versioned")


def _validate_object(record: Any, catalog: Mapping[str, Any], shared: set[str], path: str) -> None:
    _require_type(record, dict, path)
    _require_exact_keys(record, OBJECT_FIELDS, path)
    _require_non_empty_string(record["element_kind"], f"{path}.element_kind")
    if record["status"] not in {"supported", "partial", "routed"}:
        _fail(f"{path}.status: invalid status")
    _require_non_empty_string(record["owner_skill"], f"{path}.owner_skill")
    if record["reference_path"] is not None:
        _require_safe_path(record["reference_path"], f"{path}.reference_path")
    _require_string_list(record["shared_reference_paths"], f"{path}.shared_reference_paths", non_empty=False)
    for reference_path in record["shared_reference_paths"]:
        if reference_path not in shared:
            _fail(f"{path}.shared_reference_paths: unknown shared reference {reference_path!r}")
    if not isinstance(record["artifacts"], list):
        _fail(f"{path}.artifacts: expected array")
    for index, artifact in enumerate(record["artifacts"]):
        _validate_artifact(artifact, f"{path}.artifacts[{index}]")
    if not isinstance(record["sources"], list) or not record["sources"]:
        _fail(f"{path}.sources: expected non-empty array")
    for index, source in enumerate(record["sources"]):
        _validate_source(source, catalog, f"{path}.sources[{index}]")
    min_version = record["min_version"]
    if min_version is not None and min_version not in {"9.1", "9.2"}:
        _fail(f"{path}.min_version: invalid version")
    if record["status"] in {"supported", "routed"} and min_version is None:
        _fail(f"{path}.min_version: supported/routed objects require min_version")
    if min_version is None and (record["status"] != "partial" or not record["known_gaps"]):
        _fail(f"{path}.min_version: null is only allowed for partial records with known gaps")
    _require_iso_date(record["documentation_verified_on"], f"{path}.documentation_verified_on")
    _require_string_list(record["known_gaps"], f"{path}.known_gaps", non_empty=False)


def _validate_routing(record: Any, path: str) -> None:
    _require_type(record, dict, path)
    _require_exact_keys(record, ROUTING_FIELDS, path)
    _require_non_empty_string(record["category"], f"{path}.category")
    if record["status"] not in {"automatic", "out_of_scope"}:
        _fail(f"{path}.status: invalid routing status")
    _require_non_empty_string(record["route_to"], f"{path}.route_to")
    _require_string_list(record["examples"], f"{path}.examples", non_empty=True)
    _require_non_empty_string(record["reason"], f"{path}.reason")


def validate_coverage_data(data: Mapping[str, Any], *, repo_root: Path = REPOSITORY_ROOT) -> None:
    _require_type(data, dict, "top-level")
    _require_exact_keys(data, TOP_LEVEL_FIELDS, "top-level")
    if data["schema_version"] != 1:
        _fail("schema_version: expected 1")
    if data["target_platform"] != {"name": "1С:Предприятие.Элемент", "version": "9.2"}:
        _fail("target_platform: expected 1С:Предприятие.Элемент 9.2")

    _validate_source_catalog(data["source_catalog"])
    if data["shared_references"] != SHARED_REFERENCES:
        _fail("shared_references: unexpected shared reference list")
    for path in data["shared_references"]:
        _require_safe_path(path, f"shared_references.{path}")
        full_path = repo_root / ".claude" / "skills" / "xbsl-meta-add" / path
        if path != "references/reference-contract.md" and not full_path.is_file():
            _fail(f"shared_references.{path}: referenced file does not exist")

    objects = data["objects"]
    if not isinstance(objects, list) or len(objects) != 32:
        _fail("objects: expected exactly 32 records")
    seen_objects: set[str] = set()
    shared = set(data["shared_references"])
    for index, record in enumerate(objects):
        _validate_object(record, data["source_catalog"], shared, f"objects[{index}]")
        if record["element_kind"] in seen_objects:
            _fail(f"objects: duplicate element_kind {record['element_kind']!r}")
        seen_objects.add(record["element_kind"])

    counts = Counter(record["status"] for record in objects)
    expected_counts = {"supported": 31, "partial": 0, "routed": 1}
    if {status: counts[status] for status in expected_counts} != expected_counts:
        _fail("objects: expected balance 31 supported + 0 partial + 1 routed")
    routed = [record for record in objects if record["status"] == "routed"]
    if routed[0]["element_kind"] != "ЗапланированноеЗадание":
        _fail("objects: routed type must be ЗапланированноеЗадание")

    routing = data["routing"]
    if not isinstance(routing, list) or not routing:
        _fail("routing: expected non-empty array")
    seen_routes: set[str] = set()
    for index, record in enumerate(routing):
        _validate_routing(record, f"routing[{index}]")
        if record["category"] in seen_routes:
            _fail(f"routing: duplicate category {record['category']!r}")
        seen_routes.add(record["category"])


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CoverageValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_coverage(path: Path = COVERAGE_PATH) -> dict[str, Any]:
    data = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    validate_coverage_data(data)
    return data


def dump_canonical_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _escape_cell(value: Any) -> str:
    return str(value).replace("\r\n", "<br>").replace("\n", "<br>").replace("|", "\\|")


def _format_value(value: Any) -> str:
    return "null" if value is None else str(value)


def _format_reference(record: Mapping[str, Any]) -> str:
    references = []
    if record["reference_path"] is not None:
        references.append(record["reference_path"])
    references.extend(record["shared_reference_paths"])
    return "<br>".join(f"`{_escape_cell(reference)}`" for reference in references) or "—"


def _format_required_artifacts(record: Mapping[str, Any]) -> str:
    required = [
        f"`{_escape_cell(artifact['pattern'])}` — {_escape_cell(artifact['role'])}"
        for artifact in record["artifacts"]
        if artifact["required"]
    ]
    return "<br>".join(required) or "—"


def render_markdown(data: Mapping[str, Any]) -> str:
    validate_coverage_data(data)
    target = data["target_platform"]
    counts = Counter(record["status"] for record in data["objects"])
    lines = [
        "# Матрица покрытия xbsl-meta-add",
        "",
        "<!-- GENERATED FILE: source is object-coverage.json; do not edit manually. -->",
        "",
        f"Целевая платформа: **{_escape_cell(target['name'])} {_escape_cell(target['version'])}**.",
        "",
        "## Баланс",
        "",
        f"`{counts['supported']} supported + {counts['partial']} partial + {counts['routed']} routed = {len(data['objects'])}`",
        "",
        "## Объекты",
        "",
        "| Вид элемента | Статус | Владелец | Min version | Reference | Required artifacts |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for record in data["objects"]:
        lines.append(
            "| "
            f"`{_escape_cell(record['element_kind'])}` | "
            f"`{_escape_cell(record['status'])}` | "
            f"`{_escape_cell(record['owner_skill'])}` | "
            f"`{_escape_cell(_format_value(record['min_version']))}` | "
            f"{_format_reference(record)} | "
            f"{_format_required_artifacts(record)} |"
        )

    lines.extend(
        [
            "",
            "## Routing",
            "",
            "| Category | Status | Route to | Examples | Reason |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for record in data["routing"]:
        lines.append(
            "| "
            f"`{_escape_cell(record['category'])}` | "
            f"`{_escape_cell(record['status'])}` | "
            f"`{_escape_cell(record['route_to'])}` | "
            f"{_escape_cell(', '.join(record['examples']))} | "
            f"{_escape_cell(record['reason'])} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, default=COVERAGE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    try:
        data = load_coverage(args.coverage)
        rendered = render_markdown(data)
    except (OSError, json.JSONDecodeError, CoverageValidationError) as error:
        print(f"error: {error}")
        return 2

    if args.check:
        try:
            current = args.output.read_text(encoding="utf-8")
        except OSError:
            current = None
        if current != rendered:
            print(f"stale: {args.output}")
            return 1
        return 0

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    except OSError as error:
        print(f"error: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
