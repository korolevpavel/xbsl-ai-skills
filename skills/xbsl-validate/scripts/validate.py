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
QUERY_PARAMETER_RE = re.compile(r"&([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)")
SCHEDULE_TIME_RE = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
SCHEDULE_MOMENT_RE = re.compile(
    r"^(?:0000|[0-3]\d{3}|4000)-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
    r"(?:T| |\u00a0)(?:[01]\d|2[0-3]):[0-5]\d"
    r"(?::[0-5]\d(?:\.\d{1,3})?)?"
    r"(?: |\u00a0)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d|"
    r"[A-Za-z][A-Za-z0-9_+./-]*)$"
)
DURATION_RE = re.compile(
    r"^(?P<sign>[+-])?(?:(?P<days>\d{1,15})д)?"
    r"(?:(?P<hours>\d{1,15})ч)?(?:(?P<minutes>\d{1,15})м)?"
    r"(?:(?P<seconds>\d{1,15})с)?(?:(?P<milliseconds>\d{1,15})мс)?$"
)
TIMED_SCHEDULE_KINDS = frozenset({"Ежедневно", "Еженедельно", "Ежемесячно"})
SCHEDULE_KINDS = frozenset(
    {"Однократно", "Периодическое", "Ежедневно", "Еженедельно", "Ежемесячно"}
)
KNOWN_NON_DOCUMENT_REFERENCES = frozenset(
    {"ДвоичныйОбъект.Ссылка", "Пользователи.Ссылка"}
)


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


def validate_access_key(
    input_file: InputFile, document: Mapping[str, Any]
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    text = input_file.actual_path.read_text(encoding="utf-8")

    for field in ("РучнаяВыдача", "ОтключитьСистемныеПересчеты"):
        if field in document and document[field] not in {"Истина", "Ложь"}:
            diagnostics.append(
                Diagnostic(
                    input_file.display_path,
                    key_line(text, field),
                    "error",
                    "owner.access_key.boolean_literal",
                    f"{field} must be the string literal Истина or Ложь",
                )
            )

    manual = document.get("РучнаяВыдача", "Ложь") == "Истина"
    if manual and "ОтключитьСистемныеПересчеты" in document:
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                key_line(text, "ОтключитьСистемныеПересчеты"),
                "error",
                "owner.access_key.system_recalculation_mode",
                "Manual access key must not define ОтключитьСистемныеПересчеты",
            )
        )

    parameters = document.get("Параметры", [])
    if isinstance(parameters, list):
        for parameter in parameters:
            if not isinstance(parameter, dict) or parameter.get("Имя") == "Владелец":
                continue
            parameter_id = parameter.get("Ид")
            if not isinstance(parameter_id, str) or UUID_RE.fullmatch(parameter_id) is None:
                parameter_name = parameter.get("Имя", "<unknown>")
                diagnostics.append(
                    Diagnostic(
                        input_file.display_path,
                        key_line(text, "Параметры"),
                        "error",
                        "owner.access_key.parameter_uuid",
                        f"Developer access-key parameter {parameter_name} requires a valid UUID",
                    )
                )

    if manual:
        companion = input_file.actual_path.with_suffix(".xbsl")
        if companion.is_file():
            try:
                companion_text = companion.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                companion_text = ""
            handler = re.search(
                r"(?m)^[ \t]*@Обработчик(?:[^\r\n]*)\r?\n"
                r"(?:(?:[ \t]*|[ \t]*//[^\r\n]*|[ \t]*@[^\r\n]+)\r?\n)*"
                r"[ \t]*метод[ \t]+ПроверитьНаличиеКлючейДоступа[ \t]*\(",
                companion_text,
            )
            if handler is not None:
                diagnostics.append(
                    Diagnostic(
                        input_file.display_path,
                        None,
                        "warning",
                        "owner.access_key.manual_handler_ignored",
                        "Manual access key companion handler ПроверитьНаличиеКлючейДоступа is ignored",
                    )
                )
    return diagnostics


def validate_report(input_file: InputFile, document: Mapping[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    source_kind = document.get("ВидИсточникаДанных", "Таблица")
    companion = input_file.actual_path.with_suffix(".xbql")

    if "Запрос" in document:
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                key_line(input_file.actual_path.read_text(encoding="utf-8"), "Запрос"),
                "error",
                "owner.report.source",
                "Report query must be stored in the same-name .xbql companion, not in YAML field Запрос",
            )
        )

    if "ВключатьВАвтоИнтерфейс" in document or "Форма" in document:
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.report.interface",
                "Report interface properties must be nested under Интерфейс",
            )
        )
    interface = document.get("Интерфейс")
    if interface is not None and not isinstance(interface, dict):
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.report.interface",
                "Интерфейс must be a mapping",
            )
        )

    if not isinstance(source_kind, str) or source_kind not in {"Таблица", "Запрос"}:
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.report.source",
                "ВидИсточникаДанных must be Таблица or Запрос",
            )
        )
        return diagnostics

    if source_kind == "Таблица":
        source = document.get("ИсточникДанных")
        if not isinstance(source, str) or not source:
            diagnostics.append(
                Diagnostic(
                    input_file.display_path,
                    None,
                    "error",
                    "owner.report.source",
                    "Table report requires a non-empty ИсточникДанных",
                )
            )
        if companion.exists():
            diagnostics.append(
                Diagnostic(
                    input_file.display_path,
                    None,
                    "error",
                    "owner.report.query_companion",
                    "Table report must not have an .xbql companion",
                )
            )
        if "ПараметрыЗапроса" in document:
            diagnostics.append(
                Diagnostic(
                    input_file.display_path,
                    None,
                    "error",
                    "owner.report.query_parameters",
                    "Table report must not define ПараметрыЗапроса",
                )
            )
        return diagnostics

    if document.get("ИсточникДанных") not in (None, ""):
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.report.source",
                "Query report must not define a non-empty ИсточникДанных",
            )
        )

    query_text: str | None = None
    try:
        query_text = companion.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        pass
    if query_text is None or not query_text.strip():
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.report.query_companion",
                "Query report requires a non-empty same-name .xbql companion",
            )
        )
        return diagnostics

    scrubbed_query = re.sub(r'"(?:[^"]|"")*"', '""', query_text)
    scrubbed_query = re.sub(r"(?m)//.*$", "", scrubbed_query)
    query_parameters = QUERY_PARAMETER_RE.findall(scrubbed_query)
    declared = document.get("ПараметрыЗапроса", [])
    declared_names: list[str] = []
    declared_valid = isinstance(declared, list)
    if declared_valid:
        for parameter in declared:
            if not isinstance(parameter, dict):
                declared_valid = False
                break
            name = parameter.get("Имя")
            type_value = parameter.get("Тип")
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(type_value, str)
                or not type_value
            ):
                declared_valid = False
                break
            declared_names.append(name)
    if (
        not declared_valid
        or len(declared_names) != len(set(declared_names))
        or set(declared_names) != set(query_parameters)
    ):
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.report.query_parameters",
                "ПараметрыЗапроса must match the exact set of &parameters in the .xbql companion",
            )
        )
    return diagnostics


def validate_register_member(
    input_file: InputFile,
    member: Any,
    *,
    require_id: bool,
    require_type: bool = True,
) -> list[Diagnostic]:
    if not isinstance(member, dict):
        return [
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.register.member",
                "Register collection members must be mappings",
            )
        ]
    if (
        not isinstance(member.get("Имя"), str)
        or not member.get("Имя")
        or (require_type and "Тип" not in member)
        or (
            "Тип" in member
            and (
                not isinstance(member.get("Тип"), str)
                or not member.get("Тип")
            )
        )
        or (require_id and "Ид" not in member)
    ):
        return [
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.register.member",
                "Register member requires non-empty Имя and Тип, and Ид where applicable",
            )
        ]
    if require_id and (
        not isinstance(member["Ид"], str) or UUID_RE.fullmatch(member["Ид"]) is None
    ):
        return [
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.register.invalid_uuid",
                "Register member has an invalid Ид",
            )
        ]
    return []


def reference_registrar_type(value: Any) -> bool:
    if not isinstance(value, str) or not valid_type_expression(value):
        return False
    if "|" not in value:
        member = value[:-1] if value.endswith("?") else value
        return value.endswith(".Ссылка?") and member not in KNOWN_NON_DOCUMENT_REFERENCES
    members = value.split("|")
    return len(members) >= 3 and members[-1] == "?" and all(
        member.endswith(".Ссылка") and member not in KNOWN_NON_DOCUMENT_REFERENCES
        for member in members[:-1]
    )


def validate_register(input_file: InputFile, document: Mapping[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    register_kind = document.get("ВидЭлемента")
    is_accumulation = register_kind == "РегистрНакопления"

    dimensions = document.get("Измерения")
    if not isinstance(dimensions, list):
        if is_accumulation or "Измерения" in document:
            diagnostics.append(
                Diagnostic(
                    input_file.display_path,
                    None,
                    "error",
                    "owner.register.dimensions",
                    "Register dimensions must be a list",
                )
            )
    elif is_accumulation and not dimensions:
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.register.dimensions",
                "Accumulation register requires a non-empty Измерения list",
            )
        )
    else:
        for member in dimensions:
            diagnostics.extend(validate_register_member(input_file, member, require_id=True))

    resources = document.get("Ресурсы")
    resources_required = is_accumulation
    if not isinstance(resources, list):
        if resources_required or "Ресурсы" in document:
            diagnostics.append(
                Diagnostic(
                    input_file.display_path,
                    None,
                    "error",
                    "owner.register.resources",
                    "Register resources must be a list",
                )
            )
    elif resources_required and not resources:
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.register.resources",
                "Accumulation register requires a non-empty Ресурсы list",
            )
        )
    else:
        for member in resources:
            member_diagnostics = validate_register_member(
                input_file,
                member,
                require_id=True,
                require_type=not is_accumulation,
            )
            diagnostics.extend(member_diagnostics)
            if (
                is_accumulation
                and not member_diagnostics
                and isinstance(member, dict)
                and "Тип" in member
                and member.get("Тип") != "Число"
            ):
                diagnostics.append(
                    Diagnostic(
                        input_file.display_path,
                        None,
                        "error",
                        "owner.register.resource_type",
                        "Accumulation register resources must have type Число",
                    )
                )

    attributes = document.get("Реквизиты", [])
    if not isinstance(attributes, list):
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.register.member",
                "Реквизиты must be a list",
            )
        )
        attributes = []
    for member in attributes:
        is_registrar = (
            is_accumulation
            and isinstance(member, dict)
            and member.get("Имя") == "Регистратор"
        )
        diagnostics.extend(
            validate_register_member(input_file, member, require_id=not is_registrar)
        )

    if is_accumulation:
        value = document.get("ВидРегистра", "Остатки")
        if not isinstance(value, str) or value not in {"Остатки", "Обороты"}:
            diagnostics.append(
                Diagnostic(
                    input_file.display_path,
                    None,
                    "error",
                    "owner.register.kind",
                    "ВидРегистра must be Остатки or Обороты",
                )
            )
        registrars = [
            member
            for member in attributes
            if isinstance(member, dict) and member.get("Имя") == "Регистратор"
        ]
        if (
            len(registrars) != 1
            or "Ид" in registrars[0]
            or not reference_registrar_type(registrars[0].get("Тип"))
        ):
            diagnostics.append(
                Diagnostic(
                    input_file.display_path,
                    None,
                    "error",
                    "owner.register.registrar",
                    "Accumulation register requires one Регистратор without Ид and with a document-reference-shaped type",
                )
            )
    return diagnostics


def scheduled_value_nodes(
    input_file: InputFile,
) -> list[tuple[str | None, str, str, str | None, int]]:
    if yaml is None:
        return []
    text = input_file.actual_path.read_text(encoding="utf-8")
    root = yaml.compose(text)
    result: list[tuple[str | None, str, str, str | None, int]] = []

    if not isinstance(root, yaml.nodes.MappingNode):
        return result
    schedule_node = None
    for key_node, value_node in root.value:
        if isinstance(key_node, yaml.nodes.ScalarNode) and key_node.value == "Расписание":
            schedule_node = value_node
            break
    if not isinstance(schedule_node, yaml.nodes.SequenceNode):
        return result
    for item in schedule_node.value:
        if not isinstance(item, yaml.nodes.MappingNode):
            continue
        kind = None
        for key_node, value_node in item.value:
            if (
                isinstance(key_node, yaml.nodes.ScalarNode)
                and key_node.value == "Вид"
                and isinstance(value_node, yaml.nodes.ScalarNode)
            ):
                kind = value_node.value
        for key_node, value_node in item.value:
            if (
                not isinstance(key_node, yaml.nodes.ScalarNode)
                or key_node.value not in {"ЗапуститьВ", "Период"}
            ):
                continue
            if isinstance(value_node, yaml.nodes.ScalarNode):
                result.append(
                    (
                        kind,
                        key_node.value,
                        value_node.value,
                        value_node.style,
                        value_node.start_mark.line + 1,
                    )
                )
            else:
                result.append(
                    (
                        kind,
                        key_node.value,
                        "",
                        "non-scalar",
                        value_node.start_mark.line + 1,
                    )
                )
    return result


def valid_moment_literal(value: str) -> bool:
    return SCHEDULE_MOMENT_RE.fullmatch(value) is not None


def valid_positive_duration_literal(value: str) -> bool:
    match = DURATION_RE.fullmatch(value)
    if match is None or match.group("sign") == "-":
        return False
    factors = {
        "days": 86_400_000,
        "hours": 3_600_000,
        "minutes": 60_000,
        "seconds": 1_000,
        "milliseconds": 1,
    }
    total_milliseconds = sum(
        int(match.group(name) or 0) * factor for name, factor in factors.items()
    )
    return 1_000 <= total_milliseconds <= 999_999_999_999_999


def is_nonempty_schedule_collection(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def valid_schedule_entry(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    kind = item.get("Вид")
    if not isinstance(kind, str) or kind not in SCHEDULE_KINDS:
        return False
    if kind in TIMED_SCHEDULE_KINDS and "ЗапуститьВ" not in item:
        return False
    if kind == "Однократно":
        start_at = item.get("ЗапуститьВ")
        if start_at is None or isinstance(start_at, (dict, list)):
            return False
    if kind == "Периодическое":
        period = item.get("Период")
        if period is None or isinstance(period, (dict, list)) or period == "":
            return False
    if kind == "Еженедельно" and not is_nonempty_schedule_collection(
        item.get("ДниНедели")
    ):
        return False
    if kind == "Ежемесячно":
        if not is_nonempty_schedule_collection(item.get("Месяцы")):
            return False
        by_month_day = is_nonempty_schedule_collection(item.get("ДниВМесяце"))
        by_week = is_nonempty_schedule_collection(
            item.get("НеделиМесяца")
        ) and is_nonempty_schedule_collection(item.get("ДниНедели"))
        if not by_month_day and not by_week:
            return False
    return True


def is_inside_subsystem(path: Path) -> bool:
    for directory in path.parents:
        if (directory / "Подсистема.yaml").is_file():
            return True
        if (directory / "Проект.yaml").is_file():
            return False
    return False


def validate_scheduled_task(input_file: InputFile, document: Mapping[str, Any]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    schedule = document.get("Расписание")
    predefined = document.get("ПредопределенноеЗадание", "НеСоздавать")
    value_nodes = scheduled_value_nodes(input_file)
    schedule_invalid = False
    if schedule is None:
        schedule_invalid = predefined != "НеСоздавать"
    elif not isinstance(schedule, list) or not schedule:
        schedule_invalid = True
    else:
        for item in schedule:
            if not valid_schedule_entry(item):
                schedule_invalid = True
    if any(
        style is not None or not valid_moment_literal(value)
        for kind, field, value, style, _ in value_nodes
        if kind == "Однократно" and field == "ЗапуститьВ"
    ):
        schedule_invalid = True
    if any(
        style is not None or not valid_positive_duration_literal(value)
        for kind, field, value, style, _ in value_nodes
        if kind == "Периодическое" and field == "Период"
    ):
        schedule_invalid = True
    if schedule_invalid:
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.scheduled_task.schedule",
                "Scheduled task Расписание must be a non-empty list with documented schedule entries",
            )
        )

    time_nodes = [
        (value, style, line)
        for kind, field, value, style, line in value_nodes
        if kind in TIMED_SCHEDULE_KINDS and field == "ЗапуститьВ"
    ]
    if any(
        style is not None or SCHEDULE_TIME_RE.fullmatch(value) is None
        for value, style, _ in time_nodes
    ):
        line = next(
            (
                node_line
                for value, style, node_line in time_nodes
                if style is not None or SCHEDULE_TIME_RE.fullmatch(value) is None
            ),
            None,
        )
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                line,
                "error",
                "owner.scheduled_task.time_literal",
                "ЗапуститьВ must be an unquoted HH:MM YAML time literal",
            )
        )

    if not is_inside_subsystem(input_file.actual_path):
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.scheduled_task.location",
                "Scheduled task must be located inside a subsystem directory",
            )
        )
    if "Обработчик" in document or "МетодОбработчика" in document:
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.scheduled_task.yaml_handler",
                "Scheduled task handler must be defined only in the same-name .xbsl companion",
            )
        )

    companion = input_file.actual_path.with_suffix(".xbsl")
    if not companion.exists():
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.scheduled_task.missing_companion",
                "Scheduled task companion .xbsl file is required",
            )
        )
        return diagnostics
    try:
        text = companion.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.scheduled_task.unreadable_companion",
                "Unable to read scheduled task companion .xbsl file",
            )
        )
        return diagnostics
    handler_declaration = re.search(
        r"(?m)^[ \t]*@Обработчик[ \t]*\r?\n"
        r"(?:(?:[ \t]*|[ \t]*//[^\r\n]*|[ \t]*@[^\r\n]+)\r?\n)*"
        r"[ \t]*метод[ \t]+Обработчик[ \t]*\([ \t]*\)",
        text,
    )
    if handler_declaration is None:
        diagnostics.append(
            Diagnostic(
                input_file.display_path,
                None,
                "error",
                "owner.scheduled_task.handler",
                "Scheduled task companion must define Обработчик() without parameters",
            )
        )
    return diagnostics


SUPPORTED_VALIDATORS: dict[
    str, Callable[[InputFile, Mapping[str, Any]], list[Diagnostic]]
] = {
    "Отчет": validate_report,
    "РегистрНакопления": validate_register,
    "РегистрСведений": validate_register,
    "КлючДоступа": validate_access_key,
}


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
            adapter = SUPPORTED_VALIDATORS.get(kind)
            return adapter(input_file, document) if adapter is not None else []
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
