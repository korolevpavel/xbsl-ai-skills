from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPOSITORY_ROOT / ".claude" / "skills" / "xbsl-meta-add"
COVERAGE_PATH = SKILL_ROOT / "object-coverage.json"
REFERENCES = SKILL_ROOT / "references"
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


def load_registry() -> dict:
    return json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))


def record_for(kind: str) -> dict:
    return next(
        record for record in load_registry()["objects"] if record["element_kind"] == kind
    )


def load_yaml(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)


def section_names(text: str) -> list[str]:
    return re.findall(r"(?m)^## (.+?)\s*$", text)


def required_artifact_patterns(record: dict) -> set[str]:
    return {
        artifact["pattern"]
        for artifact in record["artifacts"]
        if artifact["required"]
    }
