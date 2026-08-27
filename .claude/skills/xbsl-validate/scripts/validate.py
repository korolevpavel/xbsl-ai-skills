#!/usr/bin/env python3
"""Read-only validator for 1C:Element YAML metadata files."""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only without dependency install
    yaml = None


def find_skills_root(path: Path) -> Path:
    for parent in path.resolve().parents:
        if parent.name == "skills":
            return parent
    raise RuntimeError("Cannot locate skills root")


SKILLS_ROOT = find_skills_root(Path(__file__))
COVERAGE_PATH = SKILLS_ROOT / "xbsl-meta-add" / "object-coverage.json"

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
NAME_RE = re.compile(r"^[A-Za-zА-Яа-я_][A-Za-zА-Яа-я0-9_]*(?:\.[A-Za-zА-Яа-я_][A-Za-zА-Яа-я0-9_]*)?$")
SCALAR_TYPES = {
    "Строка",
    "Число",
    "Булево",
    "Дата",
    "ДатаВремя",
    "Момент",
    "ДвоичныйОбъект.Ссылка",
    "Пользователи.Ссылка",
    "СекретПриложения",
}
CODE_2_RULES = {
    "cli.arguments",
    "input.not_found",
    "input.not_yaml",
    "input.unreadable",
    "yaml.parse",
    "yaml.duplicate_key",
}
FUNCTIONAL_TYPE_COLLECTIONS = frozenset(
    {
        "Реквизиты",
        "Измерения",
        "Ресурсы",
        "Параметры",
        "ПараметрыЗаписи",
        "ПараметрыУдаления",
        "ПараметрыЗапроса",
        "Поля",
        "Константы",
        "Свойства",
    }
)
STRUCTURAL_FILE_KINDS = {
    "Проект.yaml": "Проект",
    "Подсистема.yaml": "Подсистема",
}


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int | None
    severity: str
    rule_id: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "severity": self.severity,
            "rule_id": self.rule_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class InputFile:
    actual_path: Path
    display_path: str


class DuplicateKeyError(ValueError):
    def __init__(self, key: object, line: int | None) -> None:
        super().__init__(f"Duplicate key: {key}")
        self.line = line


class DuplicateKeySafeLoader(yaml.SafeLoader if yaml is not None else object):
    pass


def _construct_mapping(loader: DuplicateKeySafeLoader, node: Any, deep: bool = False) -> dict:
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise DuplicateKeyError(key, key_node.start_mark.line + 1)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


if yaml is not None:
    DuplicateKeySafeLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        _construct_mapping,
    )


def normalize_path(path: Path) -> str:
    return path.as_posix()


def has_json_mode(argv: Sequence[str]) -> bool:
    for index, token in enumerate(argv):
        if token == "--format=json":
            return True
        if token == "--format" and index + 1 < len(argv) and argv[index + 1] == "json":
            return True
    return False


def argument_error(message: str, json_mode: bool) -> int:
    diagnostic = Diagnostic("", None, "error", "cli.arguments", message)
    if json_mode:
        print(json.dumps(envelope([diagnostic], 0), ensure_ascii=False, indent=2))
    else:
        print(f"cli.arguments: {message}", file=sys.stderr)
    return 2


def parse_args(argv: Sequence[str]) -> tuple[str, list[str]] | tuple[None, str]:
    format_occurrences: list[tuple[int, str | None]] = []
    unknown_options: set[str] = set()
    paths: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--format":
            value = argv[index + 1] if index + 1 < len(argv) else None
            format_occurrences.append((index, value))
            index += 2 if value is not None else 1
            continue
        if token.startswith("--format="):
            format_occurrences.append((index, token.split("=", maxsplit=1)[1]))
            index += 1
            continue
        if token.startswith("-"):
            unknown_options.add(token)
            index += 1
            continue
        paths.append(token)
        index += 1

    if len(format_occurrences) > 1:
        return None, "option --format may be specified once"
    output_format = "text"
    if format_occurrences:
        _, value = format_occurrences[0]
        if value is None:
            return None, "option --format requires a value"
        if value not in {"text", "json"}:
            return None, f"invalid --format value: {value}; expected text or json"
        output_format = value
    if unknown_options:
        return None, "Unknown option(s): " + ", ".join(sorted(unknown_options))
    if not paths:
        return None, "At least one PATH is required"
    return output_format, paths


def output_diagnostics(diagnostics: list[Diagnostic], file_count: int, output_format: str) -> None:
    ordered = sort_diagnostics(diagnostics)
    if output_format == "json":
        print(json.dumps(envelope(ordered, file_count), ensure_ascii=False, indent=2))
        return
    for diagnostic in ordered:
        line = f":{diagnostic.line}" if diagnostic.line is not None else ""
        print(f"{diagnostic.path}{line}: {diagnostic.rule_id}: {diagnostic.message}")


def envelope(diagnostics: list[Diagnostic], file_count: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "diagnostics": [diagnostic.as_dict() for diagnostic in diagnostics],
        "summary": {
            "files": file_count,
            "errors": sum(1 for diagnostic in diagnostics if diagnostic.severity == "error"),
            "warnings": sum(1 for diagnostic in diagnostics if diagnostic.severity == "warning"),
        },
    }


def sort_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    return sorted(
        diagnostics,
        key=lambda item: (
            item.path,
            item.line if item.line is not None else 10**9,
            item.rule_id,
            item.message,
        ),
    )


def discover_inputs(paths: Sequence[str]) -> tuple[list[InputFile], list[Diagnostic]]:
    selected: dict[Path, str] = {}
    diagnostics: list[Diagnostic] = []
    for raw_path in paths:
        input_path = Path(raw_path)
        if not input_path.exists():
            diagnostics.append(
                Diagnostic(raw_path, None, "error", "input.not_found", "Input path does not exist")
            )
            continue
        if input_path.is_file():
            if input_path.suffix != ".yaml":
                diagnostics.append(
                    Diagnostic(raw_path, None, "error", "input.not_yaml", "Explicit file is not a .yaml file")
                )
                continue
            display_path = normalize_path(input_path)
            selected.setdefault(input_path.resolve(), display_path)
            continue
        if input_path.is_dir():
            yaml_files = sorted(path for path in input_path.rglob("*.yaml") if path.is_file())
            for yaml_path in yaml_files:
                display_path = normalize_path(yaml_path if input_path.is_absolute() else yaml_path)
                actual = yaml_path.resolve()
                previous = selected.get(actual)
                if previous is None or display_path < previous:
                    selected[actual] = display_path
            continue
        diagnostics.append(
            Diagnostic(raw_path, None, "error", "input.unreadable", "Input path is not a regular file or directory")
        )
    files = [
        InputFile(actual_path=actual, display_path=display)
        for actual, display in sorted(selected.items(), key=lambda item: item[1])
    ]
    return files, diagnostics


def load_coverage() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    data = json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))
    objects = {record["element_kind"]: record for record in data["objects"]}
    routing = {}
    for record in data["routing"]:
        for example in record["examples"]:
            routing[example] = record
    return data, objects, routing


def load_yaml(input_file: InputFile) -> tuple[Any | None, Diagnostic | None]:
    if yaml is None:
        return None, Diagnostic(
            input_file.display_path,
            None,
            "error",
            "yaml.parse",
            "PyYAML dependency is not installed",
        )
    try:
        text = input_file.actual_path.read_text(encoding="utf-8")
    except OSError:
        return None, Diagnostic(
            input_file.display_path,
            None,
            "error",
            "input.unreadable",
            "Unable to read input file",
        )
    try:
        return yaml.load(text, Loader=DuplicateKeySafeLoader), None
    except DuplicateKeyError as error:
        return None, Diagnostic(
            input_file.display_path,
            error.line,
            "error",
            "yaml.duplicate_key",
            str(error),
        )
    except yaml.YAMLError as error:
        line = None
        if getattr(error, "problem_mark", None) is not None:
            line = error.problem_mark.line + 1
        return None, Diagnostic(
            input_file.display_path,
            line,
            "error",
            "yaml.parse",
            "Failed to parse YAML",
        )


def key_line(text: str, key: str) -> int | None:
    pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*:")
    match = pattern.search(text)
    if match is None:
        return None
    return text[: match.start()].count("\n") + 1


def walk_functional_type_values(value: Any) -> list[Any]:
    result: list[Any] = []

    def walk(node: Any, collection: str | None = None) -> None:
        if isinstance(node, dict):
            if collection in FUNCTIONAL_TYPE_COLLECTIONS and "Тип" in node:
                result.append(node["Тип"])
            for node_key, node_value in node.items():
                walk(node_value, node_key)
        elif isinstance(node, list):
            for item in node:
                walk(item, collection)

    walk(value)
    return result


def split_top_level(text: str, separator: str) -> list[str]:
    result: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char == "<":
            depth += 1
        elif char == ">":
            depth -= 1
            if depth < 0:
                return []
        elif char == separator and depth == 0:
            result.append(text[start:index])
            start = index + 1
    if depth != 0:
        return []
    result.append(text[start:])
    return result


def valid_type_expression(value: str) -> bool:
    if not value or value.strip() != value:
        return False
    union = split_top_level(value, "|")
    if len(union) > 1:
        nullable = union[-1] == "?"
        members = union[:-1] if nullable else union
        if nullable and len(members) < 2:
            return False
        return all(
            member
            and member != "?"
            and not member.endswith("?")
            and valid_type_expression(member)
            for member in members
        )
    if value.endswith("?"):
        inner = value[:-1]
        return bool(inner) and not inner.endswith("?") and valid_type_expression(inner)
    if value.startswith("Массив<"):
        if not value.endswith(">"):
            return False
        inner = value[len("Массив<") : -1]
        return bool(inner) and valid_type_expression(inner)
    if value == "Неопределено":
        return False
    return value in SCALAR_TYPES or bool(NAME_RE.fullmatch(value))


def validate_yaml_root(input_file: InputFile, document: Any) -> list[Diagnostic]:
    if not isinstance(document, dict):
        return [
            Diagnostic(
                input_file.display_path,
                1,
                "error",
                "yaml.root_mapping",
                "YAML root must be a mapping",
            )
        ]
    return []


def validate_common(input_file: InputFile, document: Any) -> list[Diagnostic]:
    diagnostics = validate_yaml_root(input_file, document)
    if diagnostics:
        return diagnostics

    text = input_file.actual_path.read_text(encoding="utf-8")

    for field in ("ВидЭлемента", "Ид", "Имя"):
        if field not in document:
            diagnostics.append(
                Diagnostic(
                    input_file.display_path,
                    None,
                    "error",
                    "common.required_field",
                    f"Missing required field: {field}",
                )
            )
    if "ВидЭлемента" in document and (
        not isinstance(document["ВидЭлемента"], str) or not document["ВидЭлемента"]
    ):
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                key_line(text, "ВидЭлемента"),
                "error",
                "common.element_kind",
                "ВидЭлемента must be a non-empty string",
            )
        )
    if "Ид" in document and (not isinstance(document["Ид"], str) or UUID_RE.fullmatch(document["Ид"]) is None):
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                key_line(text, "Ид"),
                "error",
                "common.invalid_uuid",
                "Invalid UUID in field Ид",
            )
        )
    for type_value in walk_functional_type_values(document):
        if not isinstance(type_value, str) or not valid_type_expression(type_value):
            diagnostics.append(
                Diagnostic(
                    input_file.display_path,
                    key_line(text, "Тип"),
                    "error",
                    "types.invalid",
                    f"Invalid type expression: {type_value}",
                )
            )
    return diagnostics


def validate_scheduled_task(input_file: InputFile, document: Mapping[str, Any]) -> list[Diagnostic]:
    companion = input_file.actual_path.with_suffix(".xbsl")
    if not companion.exists():
        return [
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.scheduled_task.missing_companion",
                "Scheduled task companion .xbsl file is required",
            )
        ]
    try:
        text = companion.read_text(encoding="utf-8")
    except OSError:
        return [
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.scheduled_task.unreadable_companion",
                "Unable to read scheduled task companion .xbsl file",
            )
        ]
    if re.search(r"(?m)^\s*метод\s+Обработчик\s*\(\s*\)", text) is None:
        return [
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.scheduled_task.handler",
                "Scheduled task companion must define Обработчик() without parameters",
            )
        ]
    return []


ROUTED_VALIDATORS: dict[str, Callable[[InputFile, Mapping[str, Any]], list[Diagnostic]]] = {
    "xbsl-scheduled-task": validate_scheduled_task,
}


def resolve_schema_kind(input_file: InputFile, document: Mapping[str, Any]) -> str | None:
    kind = document.get("ВидЭлемента")
    if isinstance(kind, str) and kind:
        return kind
    if "ВидЭлемента" not in document:
        return STRUCTURAL_FILE_KINDS.get(input_file.actual_path.name)
    return None


def validate_coverage_status(
    input_file: InputFile,
    document: Any,
    objects: Mapping[str, Any],
    routing: Mapping[str, Any],
    schema_kind: str | None = None,
) -> list[Diagnostic]:
    if not isinstance(document, dict):
        return []
    kind = schema_kind if schema_kind is not None else document.get("ВидЭлемента")
    if not isinstance(kind, str) or not kind:
        return []
    if kind in objects:
        record = objects[kind]
        status = record["status"]
        if status == "supported":
            return []
        if status == "partial":
            return [
                Diagnostic(
                    input_file.display_path,
                    None,
                    "error",
                    "coverage.partial",
                    "Object type has partial coverage and cannot be fully validated",
                )
            ]
        if status == "routed":
            adapter = ROUTED_VALIDATORS.get(record["owner_skill"])
            if adapter is None:
                return [
                    Diagnostic(
                        input_file.display_path,
                        None,
                        "error",
                        "coverage.route_unavailable",
                        f"No validator adapter registered for owner skill: {record['owner_skill']}",
                    )
                ]
            return adapter(input_file, document)
    if kind in routing:
        route = routing[kind]
        rule_id = f"coverage.{route['status']}"
        return [
            Diagnostic(
                input_file.display_path,
                None,
                "warning",
                rule_id,
                route["reason"],
            )
        ]
    return [
        Diagnostic(
            input_file.display_path,
            None,
            "error",
            "coverage.unknown_type",
            f"Unknown object type: {kind}",
        )
    ]


def validate_file(
    input_file: InputFile,
    objects: Mapping[str, Any],
    routing: Mapping[str, Any],
) -> list[Diagnostic]:
    document, parse_error = load_yaml(input_file)
    if parse_error is not None:
        return [parse_error]

    diagnostics = validate_yaml_root(input_file, document)
    if diagnostics:
        return diagnostics

    schema_kind = resolve_schema_kind(input_file, document)
    if schema_kind is None:
        return validate_common(input_file, document)

    if schema_kind in objects:
        diagnostics.extend(validate_common(input_file, document))
    diagnostics.extend(
        validate_coverage_status(
            input_file,
            document,
            objects,
            routing,
            schema_kind=schema_kind,
        )
    )
    return diagnostics


def exit_code_for(diagnostics: list[Diagnostic]) -> int:
    if any(diagnostic.rule_id in CODE_2_RULES for diagnostic in diagnostics):
        return 2
    if any(diagnostic.severity == "error" for diagnostic in diagnostics):
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    json_mode = has_json_mode(argv)
    parsed_format, parsed_paths_or_error = parse_args(argv)
    if parsed_format is None:
        return argument_error(parsed_paths_or_error, json_mode)
    output_format = parsed_format
    paths = parsed_paths_or_error

    files, diagnostics = discover_inputs(paths)
    try:
        _, objects, routing = load_coverage()
    except OSError as error:
        diagnostics.append(Diagnostic("", None, "error", "input.unreadable", str(error)))
        objects = {}
        routing = {}
    for input_file in files:
        diagnostics.extend(validate_file(input_file, objects, routing))

    output_diagnostics(diagnostics, len(files), output_format)
    return exit_code_for(diagnostics)


if __name__ == "__main__":
    raise SystemExit(main())
