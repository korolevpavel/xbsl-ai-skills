#!/usr/bin/env python3
"""
Безопасное переименование объекта конфигурации 1С:Элемент.
Обновляет все ссылки в YAML и XBSL файлах проекта, переименовывает файлы.

Во всех командах ниже `{python}` означает `python` в Windows и `python3` в macOS/Linux/WSL. Выбирай команду сразу по текущей ОС, не запускай оба варианта.

Использование (dry-run — только показывает изменения):
    {python} .claude/skills/xbsl-rename/scripts/rename.py --old-name Номенклатура --new-name Товары [--root .]

Применить изменения:
    {python} .claude/skills/xbsl-rename/scripts/rename.py --old-name Номенклатура --new-name Товары [--root .] --apply
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import os
import re
import sys
import unicodedata


PROJECT_FILE = "Проект.yaml"
SUBSYSTEM_FILE = "Подсистема.yaml"
YAML_EXT = ".yaml"
XBSL_EXT = ".xbsl"
XBQL_EXT = ".xbql"
PROJECT_EXTENSIONS = (YAML_EXT, XBSL_EXT, XBQL_EXT)
FORM_SUFFIXES = (
    "Форма",
    "ФормаОбъекта",
    "ФормаСписка",
    "ФормаОтчета",
    "ФормаОбработки",
)
XBSL_RESERVED_WORDS = {
    "вконце", "finally", "вниз", "down", "возврат", "return", "выбор", "case",
    "выбросить", "throw", "для", "for", "если", "if", "знч", "val", "и", "and",
    "из", "in", "или", "or", "импорт", "import", "иначе", "else", "исключение",
    "exception", "исп", "use", "как", "as", "когда", "when", "конст", "const",
    "конструктор", "constructor", "метод", "method", "не", "not", "неизвестно",
    "unknown", "ничто", "void", "новый", "new", "обз", "req", "область", "scope",
    "пер", "var", "перечисление", "enum", "по", "to", "поймать", "catch", "пока",
    "while", "попытка", "try", "прервать", "break", "продолжить", "continue",
    "статический", "static", "структура", "structure", "умолчание", "default",
    "шаг", "step", "это", "is", "этот", "this",
    "истина", "true", "ложь", "false", "неопределено", "undefined",
}


class RenameCollisionError(ValueError):
    """План переименования небезопасен из-за коллизии."""


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.read()
    except (OSError, UnicodeError):
        return None


def write_text(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)


def get_yaml_field(text: str, field: str) -> str | None:
    field_pattern = re.compile(
        rf"^\ufeff?(?:{re.escape(field)}|\"{re.escape(field)}\"|'{re.escape(field)}')[ \t]*:[ \t]*(.*)$"
    )
    for line in text.splitlines():
        match = field_pattern.match(line)
        if match:
            value = _parse_yaml_scalar(match.group(1))
            return value if value else None
    return None


def _parse_yaml_scalar(raw_value: str) -> str:
    """Читает простой YAML scalar, учитывая кавычки и inline comment."""
    comment_at = _yaml_comment_index(raw_value)
    value = raw_value[:comment_at].strip() if comment_at is not None else raw_value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value


def _yaml_comment_index(raw_value: str) -> int | None:
    """Позиция YAML comment marker вне кавычек."""
    quote: str | None = None
    escaped = False
    for index, char in enumerate(raw_value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if char in ("'", '"'):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if char == "#" and quote is None and (index == 0 or raw_value[index - 1].isspace()):
            return index
    return None


# ---------------------------------------------------------------------------
# Поиск файлов проекта
# ---------------------------------------------------------------------------

def find_project_roots(root: str) -> list[str]:
    """Рекурсивно находит папки с Проект.yaml."""
    result: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        if PROJECT_FILE in filenames:
            result.append(dirpath)
            dirnames.clear()  # не погружаться внутрь проекта
    return sorted(result)


def collect_project_files(project_root: str) -> list[str]:
    """Все YAML, XBSL и XBQL файлы внутри проекта."""
    files: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(project_root):
        for name in sorted(filenames):
            if name.endswith(PROJECT_EXTENSIONS):
                files.append(os.path.join(dirpath, name))
    return files


# ---------------------------------------------------------------------------
# Замены в тексте
# ---------------------------------------------------------------------------

def _token_pattern(name: str) -> re.Pattern[str]:
    """Паттерн одного полного XBSL/YAML-идентификатора."""
    marks = "\\u0300-\\u036f\\u0483-\\u0489\\u1ab0-\\u1aff\\u1dc0-\\u1dff\\u20d0-\\u20ff\\ufe20-\\ufe2f"
    return re.compile(rf"(?<![\w{marks}]){re.escape(name)}(?![\w{marks}])", re.UNICODE)


def _default_exact_replacements(old_name: str, new_name: str) -> dict[str, str]:
    """Совместимая карта только известных составных имён форм."""
    replacements = {old_name: new_name}
    for suffix in FORM_SUFFIXES:
        replacements[old_name + suffix] = new_name + suffix
    return replacements


def make_patterns(old_name: str) -> list[tuple[re.Pattern[str], str]]:
    """
    Возвращает список (pattern, replacement) для замены старого имени новым.

    В отличие от прежней реализации не создаёт паттерн произвольного
    префикса. Составные имена форм перечислены явным allowlist.
    """
    names = [old_name, *(old_name + suffix for suffix in FORM_SUFFIXES)]
    return [(_token_pattern(name), name) for name in sorted(names, key=len, reverse=True)]


_XBSL_IMPORT_RE = re.compile(r"^\s*(?:импорт|import)\b", re.IGNORECASE | re.UNICODE)
_YAML_IMPORT_RE = re.compile(r'''^([ \t]*)(?:Импорт|"Импорт"|'Импорт')[ \t]*:''', re.UNICODE)
_YAML_FIELD_TEMPLATE = r'''^(?P<prefix>\ufeff?[ \t]*(?:-[ \t]+)?(?:{field}|"{field}"|'{field}')[ \t]*:[ \t]*)(?P<value>[^\r\n]*)(?P<newline>\r?\n)?$'''


def _replace_exact_tokens(line: str, replacements: dict[str, str]) -> str:
    for old_token in sorted(replacements, key=len, reverse=True):
        line = _token_pattern(old_token).sub(lambda _match: replacements[old_token], line)
    return line


def _replace_qualified_tokens(text: str, replacements: dict[str, str]) -> str:
    """Меняет только токены-ссылки ``Имя.Член``, но не ``alias.Имя``."""
    marks = "\\u0300-\\u036f\\u0483-\\u0489\\u1ab0-\\u1aff\\u1dc0-\\u1dff\\u20d0-\\u20ff\\ufe20-\\ufe2f"
    for old_token in sorted(replacements, key=len, reverse=True):
        pattern = re.compile(
            rf"(?<![.\w{marks}]){re.escape(old_token)}(?=[ \t]*\.)",
            re.UNICODE,
        )
        text = pattern.sub(lambda _match: replacements[old_token], text)
    return text


def _yaml_field_match(line: str, field: str) -> re.Match[str] | None:
    return re.match(_YAML_FIELD_TEMPLATE.format(field=re.escape(field)), line, re.UNICODE)


_YAML_ANY_FIELD_RE = re.compile(
    r'''(?:^\ufeff?[ \t]*(?:-[ \t]+)?|,[ \t]*)(?P<key>[\wЁё]+|"[^"]+"|'[^']+')[ \t]*:[ \t]*''',
    re.UNICODE,
)


def _yaml_field_ranges(line: str) -> list[tuple[str, int, int]]:
    """Возвращает key/value ranges для обычного и compact YAML mapping."""
    comment_at = _yaml_comment_index(line)
    newline_at = len(line.rstrip("\r\n"))
    content_end = min(index for index in (comment_at, newline_at) if index is not None)
    candidate = line[:content_end]
    quote: str | None = None
    outside_quote: list[bool] = []
    escaped = False
    for char in candidate:
        outside_quote.append(quote is None)
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
        elif char in ("'", '"'):
            quote = char if quote is None else (None if quote == char else quote)

    matches = [
        match
        for match in _YAML_ANY_FIELD_RE.finditer(candidate)
        if match.start() >= len(outside_quote) or outside_quote[match.start()]
    ]
    result: list[tuple[str, int, int]] = []
    for index, match in enumerate(matches):
        key = match.group("key").strip("'\"")
        value_end = matches[index + 1].start() if index + 1 < len(matches) else content_end
        result.append((key, match.end(), value_end))
    return result


def _replace_yaml_named_values(
    line: str,
    field: str,
    replacements: dict[str, str],
    qualified_only: bool = False,
) -> str:
    spans: list[tuple[int, int, str]] = []
    for key, start, end in _yaml_field_ranges(line):
        if key != field:
            continue
        value = line[start:end]
        modified = (
            _replace_qualified_tokens(value, replacements)
            if qualified_only
            else _replace_exact_tokens(value, replacements)
        )
        if modified != value:
            spans.append((start, end, modified))
    return _apply_spans(line, spans)


def _replace_yaml_expressions(line: str, replacements: dict[str, str]) -> str:
    spans: list[tuple[int, int, str]] = []
    for _key, start, end in _yaml_field_ranges(line):
        value = line[start:end]
        if value.strip().lstrip("'\"").startswith("="):
            modified = _replace_expression_code(value, replacements)
            if modified != value:
                spans.append((start, end, modified))
    return _apply_spans(line, spans)


def _replace_expression_code(text: str, replacements: dict[str, str]) -> str:
    masked = _mask_literals_and_comments(text)
    return _apply_spans(text, _qualified_reference_spans(masked, replacements))


def _replace_yaml_field_value(
    line: str,
    field: str,
    replacements: dict[str, str],
    qualified_only: bool = False,
) -> str:
    match = _yaml_field_match(line, field)
    if not match:
        return line
    value = match.group("value")
    comment_at = _yaml_comment_index(value)
    reference_value = value[:comment_at] if comment_at is not None else value
    comment = value[comment_at:] if comment_at is not None else ""
    modified = (
        _replace_qualified_tokens(reference_value, replacements)
        if qualified_only
        else _replace_exact_tokens(reference_value, replacements)
    )
    return match.group("prefix") + modified + comment + (match.group("newline") or "")


def _mask_literals_and_comments(
    text: str, *, preserve_interpolations: bool = True
) -> str:
    """Маскирует literals/comments, но оставляет код `${...}`/`%{...}` видимым."""
    chars = list(text)
    index = 0
    state = "code"
    interpolation_depth = 0
    while index < len(chars):
        char = chars[index]
        next_char = chars[index + 1] if index + 1 < len(chars) else ""
        if state in {"line_comment", "interpolation_line_comment"}:
            if char in "\r\n":
                state = "interpolation" if state.startswith("interpolation_") else "code"
            else:
                chars[index] = " "
            index += 1
            continue
        if state in {"block_comment", "interpolation_block_comment"}:
            if char == "*" and next_char == "/":
                chars[index] = chars[index + 1] = " "
                index += 2
                state = "interpolation" if state.startswith("interpolation_") else "code"
            else:
                if char not in "\r\n":
                    chars[index] = " "
                index += 1
            continue
        if state in {"string", "interpolation_string"}:
            return_state = "interpolation" if state == "interpolation_string" else "code"
            if char == '"' and next_char == '"':
                chars[index] = chars[index + 1] = " "
                index += 2
                continue
            if char == "\\" and next_char:
                chars[index] = " "
                if next_char not in "\r\n":
                    chars[index + 1] = " "
                index += 2
                continue
            if (
                preserve_interpolations
                and state == "string"
                and char in {"$", "%"}
                and next_char == "{"
            ):
                chars[index] = chars[index + 1] = " "
                interpolation_depth = 1
                state = "interpolation"
                index += 2
                continue
            if char == '"':
                chars[index] = " "
                state = return_state
            elif char not in "\r\n":
                chars[index] = " "
            index += 1
            continue
        if state == "interpolation":
            if char == "/" and next_char == "/":
                chars[index] = chars[index + 1] = " "
                index += 2
                state = "interpolation_line_comment"
                continue
            if char == "/" and next_char == "*":
                chars[index] = chars[index + 1] = " "
                index += 2
                state = "interpolation_block_comment"
                continue
            if char == '"':
                chars[index] = " "
                state = "interpolation_string"
                index += 1
                continue
            if char == "{":
                interpolation_depth += 1
            elif char == "}":
                interpolation_depth -= 1
                if interpolation_depth == 0:
                    chars[index] = " "
                    state = "string"
            index += 1
            continue
        if char == "/" and next_char == "/":
            chars[index] = chars[index + 1] = " "
            index += 2
            state = "line_comment"
            continue
        if char == "/" and next_char == "*":
            chars[index] = chars[index + 1] = " "
            index += 2
            state = "block_comment"
            continue
        if char == '"':
            chars[index] = " "
            state = "string"
        index += 1
    return "".join(chars)


def _apply_spans(text: str, spans: list[tuple[int, int, str]]) -> str:
    """Применяет непересекающиеся замены по позициям исходного текста."""
    chosen: list[tuple[int, int, str]] = []
    last_end = -1
    for start, end, replacement in sorted(set(spans), key=lambda item: (item[0], -(item[1] - item[0]))):
        if start < last_end:
            continue
        chosen.append((start, end, replacement))
        last_end = end
    for start, end, replacement in reversed(chosen):
        text = text[:start] + replacement + text[end:]
    return text


def _type_annotation_end(masked: str, start: int, limit: int) -> int:
    """Возвращает конец потенциально многострочного type-expression после ``:``."""
    cursor = start
    stack: list[str] = []
    pairs = {"(": ")", "[": "]", "{": "}", "<": ">"}
    saw_token = False
    line_last_significant = ""
    while cursor < limit:
        char = masked[cursor]
        if not stack and char == "=":
            return cursor
        if char in "\r\n":
            newline_start = cursor
            if char == "\r" and cursor + 1 < limit and masked[cursor + 1] == "\n":
                cursor += 1
            next_cursor = cursor + 1
            while next_cursor < limit and masked[next_cursor] in " \t\r\n":
                next_cursor += 1
            next_char = masked[next_cursor] if next_cursor < limit else ""
            continued = bool(stack) or line_last_significant in {"|", ",", "<", "(", "[", "{"}
            if line_last_significant == ">" and masked[:newline_start].rstrip().endswith("->"):
                continued = True
            if next_char == "|":
                continued = True
            if saw_token and not continued:
                return newline_start
            cursor += 1
            line_last_significant = ""
            continue
        if char in pairs:
            stack.append(pairs[char])
        elif char in ")]}>" and stack and char == stack[-1]:
            stack.pop()
        if not char.isspace():
            saw_token = True
            line_last_significant = char
        cursor += 1
    return cursor


def _method_scopes(masked: str) -> list[tuple[int, int, int]]:
    """Возвращает ``(start, body_start, end)`` для верхнеуровневых методов."""
    method_re = re.compile(
        r"^(?P<indent>[ \t]*)(?:(?:(?:знч|пер|val|var)[ \t]+[\wЁё]+[ \t]*=[ \t]*)|"
        r"(?:(?:статический|static)[ \t]+)?)(?:метод|method)\b",
        re.IGNORECASE | re.MULTILINE | re.UNICODE,
    )
    scopes: list[tuple[int, int, int]] = []
    for method in method_re.finditer(masked):
        indent = method.group("indent")
        terminator_re = re.compile(
            rf"^{re.escape(indent)};[ \t]*(?:\r?\n|$)",
            re.MULTILINE,
        )
        terminator = terminator_re.search(masked, method.end())
        end = terminator.end() if terminator else len(masked)
        opening = masked.find("(", method.end(), end)
        header_end = method.end()
        if opening >= 0:
            depth = 0
            for index in range(opening, end):
                if masked[index] == "(":
                    depth += 1
                elif masked[index] == ")":
                    depth -= 1
                    if depth == 0:
                        header_end = index + 1
                        break
        anonymous = opening >= 0 and not masked[method.end():opening].strip()
        arrow_start = header_end
        while arrow_start < end and masked[arrow_start].isspace():
            arrow_start += 1
        if anonymous and masked.startswith("->", arrow_start):
            body_start = arrow_start + 2
            same_line_end = masked.find("\n", body_start, end)
            same_line_end = end if same_line_end < 0 else same_line_end
            inline_terminator = masked.find(";", body_start, same_line_end)
            if inline_terminator >= 0:
                end = inline_terminator + 1
            scopes.append((method.start(), body_start, end))
            continue
        after_parameters = header_end
        while after_parameters < end and masked[after_parameters] in " \t":
            after_parameters += 1
        if after_parameters < end and masked[after_parameters] == ":":
            header_end = _type_annotation_end(masked, after_parameters + 1, end)
        newline = masked.find("\n", header_end, end)
        body_start = newline + 1 if newline >= 0 else method.end()
        scopes.append((method.start(), body_start, end))
    return scopes


def _shadowed_receiver_ranges(masked: str, names: set[str]) -> dict[str, list[tuple[int, int]]]:
    """Находит области, где metadata-like имя затенено локальным binding."""
    result = {name: [] for name in names}
    scopes = _method_scopes(masked)

    for scope_start, body_start, scope_end in scopes:
        header = masked[scope_start:body_start]
        for name in names:
            parameter = re.compile(
                rf"(?:\(|,)[ \t\r\n]*{re.escape(name)}[ \t]*(?=[:,)=])",
                re.UNICODE,
            )
            if parameter.search(header):
                result[name].append((body_start, scope_end))

    def lexical_block_end(position: int, containing_end: int, inclusive: bool) -> int:
        line_start = masked.rfind("\n", 0, position) + 1
        binding_indent = len(masked[line_start:position]) - len(
            masked[line_start:position].lstrip(" \t")
        )
        line_end = masked.find("\n", position)
        cursor = len(masked) if line_end < 0 else line_end + 1
        boundary_re = re.compile(
            r"^(?P<indent>[ \t]*)(?P<kind>;|иначеесли\b|иначе\b|когда\b|"
            r"поймать\b|вконце\b|finally\b|elseif\b|else\b|when\b|catch\b)",
            re.IGNORECASE | re.MULTILINE | re.UNICODE,
        )
        for boundary in boundary_re.finditer(masked, cursor, containing_end):
            boundary_indent = len(boundary.group("indent"))
            if boundary_indent < binding_indent or (
                inclusive and boundary_indent == binding_indent
            ):
                if boundary.group("kind") == ";":
                    line_end = masked.find("\n", boundary.end(), containing_end)
                    return containing_end if line_end < 0 else line_end + 1
                return boundary.start()
        return containing_end

    def lambda_expression_end(arrow_start: int, arrow_end: int) -> int:
        arrow_line_start = masked.rfind("\n", 0, arrow_start) + 1
        arrow_indent = len(masked[arrow_line_start:arrow_start]) - len(
            masked[arrow_line_start:arrow_start].lstrip(" \t")
        )
        cursor = arrow_end
        stack: list[str] = []
        pairs = {"(": ")", "[": "]", "{": "}"}
        saw_token = False
        while cursor < len(masked):
            char = masked[cursor]
            if char in pairs:
                stack.append(pairs[char])
                saw_token = True
            elif char in ")]}":
                if stack and char == stack[-1]:
                    stack.pop()
                elif not stack:
                    return cursor
            elif not stack and char in ",;":
                return cursor
            elif not stack and char in "\r\n":
                newline_start = cursor
                if char == "\r" and cursor + 1 < len(masked) and masked[cursor + 1] == "\n":
                    cursor += 1
                next_line_start = cursor + 1
                next_cursor = next_line_start
                while next_cursor < len(masked) and masked[next_cursor] in " \t":
                    next_cursor += 1
                if not saw_token:
                    cursor += 1
                    continue
                next_indent = next_cursor - next_line_start
                continuation = next_indent > arrow_indent or re.match(
                    r"(?:\?\?|\.|\?|:|\+|-|\*|/|и\b|или\b|and\b|or\b)",
                    masked[next_cursor:],
                    re.IGNORECASE | re.UNICODE,
                ) is not None
                if not continuation:
                    return newline_start
            elif not char.isspace():
                saw_token = True
            cursor += 1
        return len(masked)

    def matching_opening_parenthesis(closing: int) -> int | None:
        depth = 0
        for index in range(closing, -1, -1):
            if masked[index] == ")":
                depth += 1
            elif masked[index] == "(":
                depth -= 1
                if depth == 0:
                    return index
        return None

    def parameter_segments(parameters: str) -> list[str]:
        result: list[str] = []
        start = 0
        stack: list[str] = []
        pairs = {"(": ")", "[": "]", "{": "}", "<": ">"}
        for index, char in enumerate(parameters):
            if char in pairs:
                stack.append(pairs[char])
            elif char in ")]}>" and stack and char == stack[-1]:
                stack.pop()
            elif char == "," and not stack:
                result.append(parameters[start:index])
                start = index + 1
        result.append(parameters[start:])
        return result

    def lambda_parameters(arrow_start: int) -> list[str]:
        cursor = arrow_start - 1
        while cursor >= 0 and masked[cursor] in " \t\r\n":
            cursor -= 1
        if cursor >= 0 and masked[cursor] == ")":
            opening = matching_opening_parenthesis(cursor)
            if opening is None:
                return []
            before = opening - 1
            while before >= 0 and masked[before].isspace():
                before -= 1
            # ``Имя: (Тип)->Тип`` — функциональный тип, не lambda-expression.
            if before >= 0 and masked[before] == ":":
                return []
            names: list[str] = []
            for segment in parameter_segments(masked[opening + 1:cursor]):
                match = re.match(
                    r"^[ \t\r\n]*([\wЁё]+)(?:[ \t\r\n]*:.*)?[ \t\r\n]*$",
                    segment,
                    re.DOTALL | re.UNICODE,
                )
                if match:
                    names.append(match.group(1))
            return names
        line_start = masked.rfind("\n", 0, arrow_start) + 1
        single = re.search(r"([\wЁё]+)[ \t]*$", masked[line_start:arrow_start], re.UNICODE)
        return [single.group(1)] if single else []

    binding_words = r"(?:знч|пер|конст|val|var|const)"
    loop_words = r"(?:для|for)"
    in_words = r"(?:из|in)"
    for name in names:
        binding_re = re.compile(
            rf"\b{binding_words}[ \t]+{re.escape(name)}(?!\w)",
            re.IGNORECASE | re.UNICODE,
        )
        use_binding_re = re.compile(
            rf"\b(?:исп|use|using)[ \t]+{re.escape(name)}(?!\w)"
            r"(?=[ \t]*(?::[^=\r\n]+)?[ \t]*=)",
            re.IGNORECASE | re.UNICODE,
        )
        loop_re = re.compile(
            rf"\b{loop_words}[ \t]+{re.escape(name)}[ \t]+{in_words}\b",
            re.IGNORECASE | re.UNICODE,
        )
        numeric_loop_re = re.compile(
            rf"\b{loop_words}[ \t]+{re.escape(name)}[ \t]*=",
            re.IGNORECASE | re.UNICODE,
        )
        catch_re = re.compile(
            rf"\b(?:поймать|catch)[ \t]+{re.escape(name)}(?=[ \t]*:|\b)",
            re.IGNORECASE | re.UNICODE,
        )
        for pattern, inclusive in (
            (binding_re, False),
            (use_binding_re, False),
            (loop_re, True),
            (numeric_loop_re, True),
            (catch_re, True),
        ):
            for binding in pattern.finditer(masked):
                line_end = masked.find("\n", binding.end())
                line_end = len(masked) if line_end < 0 else line_end + 1
                candidates = [
                    (scope_start, scope_end)
                    for scope_start, _body_start, scope_end in scopes
                    if scope_start <= binding.start() < scope_end
                ]
                containing = min(
                    candidates,
                    key=lambda scope: scope[1] - scope[0],
                    default=None,
                )
                containing_end = containing[1] if containing else len(masked)
                result[name].append(
                    (line_end, lexical_block_end(binding.start(), containing_end, inclusive))
                )

        for arrow in re.finditer(r"->", masked):
            if name in lambda_parameters(arrow.start()):
                result[name].append(
                    (arrow.end(), lambda_expression_end(arrow.start(), arrow.end()))
                )
    return result


def _qualified_reference_spans(
    masked: str,
    replacements: dict[str, str],
    shadowed: dict[str, list[tuple[int, int]]] | None = None,
) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    marks = "\\u0300-\\u036f\\u0483-\\u0489\\u1ab0-\\u1aff\\u1dc0-\\u1dff\\u20d0-\\u20ff\\ufe20-\\ufe2f"
    for old_token in sorted(replacements, key=len, reverse=True):
        pattern = re.compile(
            rf"(?<![.\w{marks}]){re.escape(old_token)}(?=[ \t]*\.)",
            re.UNICODE,
        )
        for match in pattern.finditer(masked):
            explicitly_qualified = masked[max(0, match.start() - 2):match.start()] == "::"
            hidden = any(
                start <= match.start() < end
                for start, end in (shadowed or {}).get(old_token, ())
            )
            if not hidden or explicitly_qualified:
                spans.append((match.start(), match.end(), replacements[old_token]))
    return spans


def _angle_type_ranges(masked: str) -> list[tuple[int, int]]:
    """Находит generic/type-literal `<...>`, не принимая spaced comparisons за тип."""
    stack: list[int] = []
    pairs: list[tuple[int, int]] = []
    for index, char in enumerate(masked):
        if char == "<":
            stack.append(index)
        elif char == ">" and stack:
            opening = stack.pop()
            pairs.append((opening, index + 1))

    result: list[tuple[int, int]] = []
    for start, end in pairs:
        suffix = masked[end:]
        type_literal = re.match(r"[ \t]*(?:\[|\{)", suffix) is not None
        prefix_match = re.search(r"([\wЁё]+)[ \t]*$", masked[:start], re.UNICODE)
        type_operator = False
        if prefix_match:
            before_prefix = masked[:prefix_match.start()]
            type_operator = re.search(
                r"\b(?:Тип|новый|new|как|as)[ \t]*$",
                before_prefix,
                re.IGNORECASE | re.UNICODE,
            ) is not None
        if type_operator or type_literal:
            result.append((start, end))
    return result


def _forced_type_reference_spans(
    masked: str,
    replacements: dict[str, str],
) -> list[tuple[int, int, str]]:
    """Однозначные type slots, которые сильнее локального shadowing."""
    spans: list[tuple[int, int, str]] = []

    # Вся сигнатура метода является type context для qualified references;
    # parameter bindings начинают затенять имя только в теле.
    for start, body_start, _end in _method_scopes(masked):
        for ref_start, ref_end, replacement in _qualified_reference_spans(
            masked[start:body_start], replacements
        ):
            spans.append((start + ref_start, start + ref_end, replacement))

    declaration_re = re.compile(
        r"^[ \t]*(?:(?:обз|эксп|export)[ \t]+)*(?:знч|пер|val|var)[ \t]+"
        r"[\wЁё]+[ \t]*(?P<colon>:)",
        re.IGNORECASE | re.MULTILINE | re.UNICODE,
    )
    for declaration in declaration_re.finditer(masked):
        type_start = declaration.end("colon")
        type_end = _type_annotation_end(masked, type_start, len(masked))
        for ref_start, ref_end, replacement in _qualified_reference_spans(
            masked[type_start:type_end], replacements
        ):
            spans.append((type_start + ref_start, type_start + ref_end, replacement))

    for start, end in _angle_type_ranges(masked):
        for ref_start, ref_end, replacement in _qualified_reference_spans(
            masked[start:end], replacements
        ):
            spans.append((start + ref_start, start + ref_end, replacement))
    return spans


def _replace_code_references(
    text: str,
    replacements: dict[str, str],
    shadowed: dict[str, list[tuple[int, int]]] | None = None,
) -> str:
    """Меняет квалифицированные XBSL-ссылки вне строк и комментариев."""
    masked = _mask_literals_and_comments(text)
    masked_chars = list(masked)
    for import_match in re.finditer(
        r"^[ \t]*(?:импорт|import)\b[^\r\n]*",
        masked,
        re.IGNORECASE | re.MULTILINE | re.UNICODE,
    ):
        for index in range(import_match.start(), import_match.end()):
            masked_chars[index] = " "
    masked = "".join(masked_chars)
    if shadowed is None:
        shadowed = _shadowed_receiver_ranges(masked, set(replacements))
    spans = _qualified_reference_spans(masked, replacements, shadowed)
    spans.extend(_forced_type_reference_spans(masked, replacements))
    marks = "\\u0300-\\u036f\\u0483-\\u0489\\u1ab0-\\u1aff\\u1dc0-\\u1dff\\u20d0-\\u20ff\\ufe20-\\ufe2f"
    for old_token in sorted(replacements, key=len, reverse=True):
        namespace_pattern = re.compile(
            rf"(?<=::){re.escape(old_token)}(?![\w{marks}]|[ \t]*::)"
            rf"(?=[ \t]*(?:[>?|,\)\]\}}]|$))",
            re.MULTILINE | re.UNICODE,
        )
        for match in namespace_pattern.finditer(masked):
            spans.append((match.start(), match.end(), replacements[old_token]))
        # Типовые контексты остаются metadata-ссылками даже когда такое же имя
        # присвоено локальной переменной: ``знч Товары = <Товары.Ссылка>[]``;
        # ``новый Товары.Объект()``.
        constructor_patterns = (
            re.compile(
                rf"\b(?:новый|new)[ \t\r\n]+({re.escape(old_token)})(?=[ \t]*\.)",
                re.IGNORECASE | re.UNICODE,
            ),
        )
        for pattern in constructor_patterns:
            for match in pattern.finditer(masked):
                start, end = match.span(1)
                spans.append((start, end, replacements[old_token]))
        cast_pattern = re.compile(
            rf"\b(?:как|as)[ \t]+({re.escape(old_token)})(?![\w{marks}])",
            re.IGNORECASE | re.UNICODE,
        )
        for match in cast_pattern.finditer(masked):
            start, end = match.span(1)
            spans.append((start, end, replacements[old_token]))
        generic_type_pattern = re.compile(
            rf"\bТип[ \t]*<[ \t]*({re.escape(old_token)})(?![\w{marks}]|[ \t]*::)",
            re.IGNORECASE | re.UNICODE,
        )
        for match in generic_type_pattern.finditer(masked):
            start, end = match.span(1)
            spans.append((start, end, replacements[old_token]))
    return _apply_spans(text, spans)


def _replace_query_references(
    text: str,
    old_name: str,
    new_name: str,
    ignored_ranges: list[tuple[int, int]] | None = None,
) -> str:
    """Меняет query sources и разрешает aliases по вложенным SELECT scopes."""
    masked_chars = list(_mask_literals_and_comments(text))
    for start, end in ignored_ranges or ():
        for index in range(start, min(end, len(masked_chars))):
            if masked_chars[index] not in "\r\n":
                masked_chars[index] = " "
    masked = "".join(masked_chars)
    marks = r"\u0300-\u036f\u0483-\u0489\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff\ufe20-\ufe2f"
    identifier = rf"[\w{marks}]+"
    token_re = re.compile(rf"{identifier}|::|[(),.]", re.UNICODE)
    tokens: list[tuple[str, int, int, int]] = []
    depth = 0
    for token_match in token_re.finditer(masked):
        token = token_match.group(0)
        if token == ")":
            depth = max(0, depth - 1)
        tokens.append((token, token_match.start(), token_match.end(), depth))
        if token == "(":
            depth += 1

    select_words = {"выбрать", "select"}
    union_words = {"объединить", "union"}
    from_words = {"из", "from"}
    join_words = {"соединение", "join"}
    alias_words = {"как", "as"}
    clause_end_words = {
        "где", "where", "сгруппировать", "group", "упорядочить", "order",
        "имеющие", "having", "итоги", "totals", "индексировать", "index",
        "для", "for", "получить", "fetch", "со", "смещением", "offset",
        *union_words,
    }
    non_alias_words = {
        *clause_end_words, *from_words, *join_words, *alias_words,
        "левое", "правое", "полное", "внутреннее", "внешнее",
        "left", "right", "full", "inner", "outer", "по", "on", "все", "all",
    }

    select_indexes = [
        index for index, token in enumerate(tokens) if token[0].casefold() in select_words
    ]
    scope_ends: dict[int, int] = {}
    for select_index in select_indexes:
        select_depth = tokens[select_index][3]
        scope_end = len(tokens)
        for index in range(select_index + 1, len(tokens)):
            token, _start, _end, token_depth = tokens[index]
            folded = token.casefold()
            if token_depth < select_depth:
                scope_end = index
                break
            if token_depth == select_depth and (
                folded in union_words or folded in select_words
            ):
                scope_end = index
                break
        scope_ends[select_index] = scope_end

    spans: list[tuple[int, int, str]] = []
    scope_bindings: dict[int, str | None] = {}
    for select_index in select_indexes:
        select_depth = tokens[select_index][3]
        scope_end = scope_ends[select_index]
        in_from = False
        expect_source = False
        target_sources: list[tuple[int, bool, str | None]] = []
        explicit_old_alias = False
        index = select_index + 1
        while index < scope_end:
            token, _start, _end, token_depth = tokens[index]
            if token_depth != select_depth:
                index += 1
                continue
            folded = token.casefold()
            if folded in from_words:
                in_from = True
                expect_source = True
                index += 1
                continue
            if in_from and folded in clause_end_words:
                in_from = False
                expect_source = False
                index += 1
                continue
            if in_from and folded in join_words:
                expect_source = True
                index += 1
                continue
            if in_from and token == ",":
                expect_source = True
                index += 1
                continue
            if not (in_from and expect_source):
                index += 1
                continue
            if token == "(":
                closing = index + 1
                while closing < scope_end:
                    if tokens[closing][0] == ")" and tokens[closing][3] == select_depth:
                        break
                    closing += 1
                cursor = min(closing + 1, scope_end)
                alias: str | None = None
                if (
                    cursor + 1 < scope_end
                    and tokens[cursor][3] == select_depth
                    and tokens[cursor][0].casefold() in alias_words
                ):
                    alias = tokens[cursor + 1][0]
                    cursor += 2
                elif cursor < scope_end:
                    possible_alias, _alias_start, _alias_end, alias_depth = tokens[cursor]
                    if (
                        alias_depth == select_depth
                        and possible_alias not in {"(", ")", ",", ".", "::"}
                        and possible_alias.casefold() not in non_alias_words
                    ):
                        alias = possible_alias
                        cursor += 1
                if (alias or "").casefold() == old_name.casefold():
                    explicit_old_alias = True
                expect_source = False
                index = max(index + 1, cursor)
                continue

            # Namespace-qualified source: ``Подсистема::Объект``.
            source_index = index
            while (
                source_index + 2 < scope_end
                and tokens[source_index + 1][0] == "::"
                and tokens[source_index + 2][3] == select_depth
            ):
                source_index += 2
            source_token, source_start, source_end, _source_depth = tokens[source_index]
            cursor = source_index + 1
            virtual_table = False
            if cursor + 1 < scope_end and tokens[cursor][0] == ".":
                virtual_table = True
                cursor += 2
                if cursor < scope_end and tokens[cursor][0] == "(":
                    cursor += 1
                    while cursor < scope_end and tokens[cursor][3] > select_depth:
                        cursor += 1
                    if cursor < scope_end and tokens[cursor][0] == ")":
                        cursor += 1
            alias: str | None = None
            if (
                cursor + 1 < scope_end
                and tokens[cursor][3] == select_depth
                and tokens[cursor][0].casefold() in alias_words
            ):
                alias = tokens[cursor + 1][0]
                cursor += 2
            elif cursor < scope_end:
                possible_alias, _alias_start, _alias_end, alias_depth = tokens[cursor]
                if (
                    alias_depth == select_depth
                    and possible_alias not in {"(", ")", ",", ".", "::"}
                    and possible_alias.casefold() not in non_alias_words
                ):
                    alias = possible_alias
                    cursor += 1
            if source_token.casefold() == old_name.casefold():
                spans.append((source_start, source_end, new_name))
                target_sources.append((source_index, virtual_table, alias))
            if (alias or "").casefold() == old_name.casefold():
                explicit_old_alias = True
            expect_source = False
            index = max(index + 1, cursor)

        has_implicit_alias = any(not table and alias is None for _source, table, alias in target_sources)
        if has_implicit_alias and explicit_old_alias:
            raise RenameCollisionError(
                f"неоднозначный alias «{old_name}» в одной области запроса"
            )
        scope_bindings[select_index] = (
            "preserve" if explicit_old_alias else ("rename" if has_implicit_alias else None)
        )

    for index in range(len(tokens) - 1):
        token, start, end, _token_depth = tokens[index]
        next_token = tokens[index + 1]
        if token.casefold() != old_name.casefold() or next_token[0] != ".":
            continue
        previous = tokens[index - 1][0] if index > 0 else None
        if previous == ".":
            continue
        if previous == "::":
            spans.append((start, end, new_name))
            continue
        containing_scopes = [
            select_index
            for select_index in select_indexes
            if select_index <= index < scope_ends[select_index]
        ]
        containing_scopes.sort(
            key=lambda select_index: (tokens[select_index][3], select_index),
            reverse=True,
        )
        resolution = next(
            (
                scope_bindings[select_index]
                for select_index in containing_scopes
                if scope_bindings.get(select_index) is not None
            ),
            None,
        )
        if resolution == "rename":
            spans.append((start, end, new_name))
    return _apply_spans(text, spans)


def _query_ranges(text: str) -> list[tuple[int, int]]:
    """Находит сбалансированные блоки ``Запрос{...}`` в XBSL."""
    masked = _mask_literals_and_comments(text)
    ranges: list[tuple[int, int]] = []
    cursor = 0
    start_pattern = re.compile(r"\bЗапрос[ \t]*\{", re.IGNORECASE | re.UNICODE)
    while True:
        match = start_pattern.search(masked, cursor)
        if not match:
            break
        brace = masked.find("{", match.start(), match.end())
        depth = 0
        end = len(masked)
        for index in range(brace, len(masked)):
            if masked[index] == "{":
                depth += 1
            elif masked[index] == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        ranges.append((match.start(), end))
        cursor = end
    return ranges


def _query_interpolation_ranges(text: str) -> list[tuple[int, int, int, int]]:
    """Возвращает full/content ranges для XBSL-параметров ``%{...}``/``${...}``."""
    visible = _mask_literals_and_comments(text, preserve_interpolations=False)
    result: list[tuple[int, int, int, int]] = []
    cursor = 0
    marker_re = re.compile(r"%\{")
    while True:
        marker = marker_re.search(visible, cursor)
        if not marker:
            break
        brace = marker.end() - 1
        depth = 1
        state = "code"
        index = brace + 1
        while index < len(text):
            char = text[index]
            next_char = text[index + 1] if index + 1 < len(text) else ""
            if state == "string":
                if char == "\\" and next_char:
                    index += 2
                    continue
                if char == '"' and next_char == '"':
                    index += 2
                    continue
                if char == '"':
                    state = "code"
                index += 1
                continue
            if state == "line_comment":
                if char in "\r\n":
                    state = "code"
                index += 1
                continue
            if state == "block_comment":
                if char == "*" and next_char == "/":
                    state = "code"
                    index += 2
                else:
                    index += 1
                continue
            if char == '"':
                state = "string"
            elif char == "/" and next_char == "/":
                state = "line_comment"
                index += 2
                continue
            elif char == "/" and next_char == "*":
                state = "block_comment"
                index += 2
                continue
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    result.append((marker.start(), brace + 1, index, index + 1))
                    cursor = index + 1
                    break
            index += 1
        else:
            cursor = marker.end()
    return result


def _slice_shadowed_ranges(
    shadowed: dict[str, list[tuple[int, int]]],
    start: int,
    end: int,
) -> dict[str, list[tuple[int, int]]]:
    return {
        name: [
            (max(range_start, start) - start, min(range_end, end) - start)
            for range_start, range_end in ranges
            if range_start < end and range_end > start
        ]
        for name, ranges in shadowed.items()
    }


def _replace_xbsl_references(
    content: str,
    old_name: str,
    new_name: str,
    replacements: dict[str, str],
) -> str:
    global_masked = _mask_literals_and_comments(content)
    global_shadowed = _shadowed_receiver_ranges(global_masked, set(replacements))
    result: list[str] = []
    cursor = 0
    for start, end in _query_ranges(content):
        result.append(
            _replace_code_references(
                content[cursor:start],
                replacements,
                _slice_shadowed_ranges(global_shadowed, cursor, start),
            )
        )
        query = content[start:end]
        interpolations = _query_interpolation_ranges(query)
        for _full_start, code_start, code_end, _full_end in reversed(interpolations):
            query = (
                query[:code_start]
                + _replace_code_references(
                    query[code_start:code_end],
                    replacements,
                    _slice_shadowed_ranges(
                        global_shadowed,
                        start + code_start,
                        start + code_end,
                    ),
                )
                + query[code_end:]
            )
        ignored = [(full_start, full_end) for full_start, _a, _b, full_end in _query_interpolation_ranges(query)]
        result.append(_replace_query_references(query, old_name, new_name, ignored))
        cursor = end
    result.append(
        _replace_code_references(
            content[cursor:],
            replacements,
            _slice_shadowed_ranges(global_shadowed, cursor, len(content)),
        )
    )
    return "".join(result)


def _replace_yaml_references(
    content: str,
    old_name: str,
    replacements: dict[str, str],
    replace_identity: bool,
    rename_imports: bool,
    rename_form_reference: bool,
) -> str:
    """Меняет только документированные YAML reference slots."""
    lines = content.splitlines(keepends=True)
    result: list[str] = []
    yaml_import_indent: int | None = None
    reference_list_indent: int | None = None
    form_replacements = {
        key: value
        for key, value in replacements.items()
        if rename_form_reference or key != old_name
    }
    for line in lines:
        stripped = line.strip()
        current_indent = len(line) - len(line.lstrip(" \t"))
        if yaml_import_indent is not None:
            import_item = current_indent > yaml_import_indent or (
                current_indent == yaml_import_indent and stripped.startswith("-")
            )
            if not stripped or stripped.startswith("#") or import_item:
                result.append(_replace_exact_tokens(line, replacements) if rename_imports else line)
                continue
            yaml_import_indent = None

        if reference_list_indent is not None:
            reference_item = current_indent > reference_list_indent or (
                current_indent == reference_list_indent and stripped.startswith("-")
            )
            if not stripped or stripped.startswith("#") or reference_item:
                comment_at = _yaml_comment_index(line)
                reference_part = line[:comment_at] if comment_at is not None else line
                comment = line[comment_at:] if comment_at is not None else ""
                result.append(_replace_exact_tokens(reference_part, replacements) + comment)
                continue
            reference_list_indent = None

        yaml_import = _YAML_IMPORT_RE.match(line)
        if yaml_import:
            yaml_import_indent = len(yaml_import.group(1))
            result.append(_replace_exact_tokens(line, replacements) if rename_imports else line)
            continue

        if any(key == "СозданиеНаОсновании" for key, _start, _end in _yaml_field_ranges(line)):
            reference_list_indent = current_indent

        modified = line
        if replace_identity and not line.startswith((" ", "\t", "-")):
            modified = _replace_yaml_named_values(modified, "Имя", replacements)
        modified = _replace_yaml_named_values(modified, "Тип", replacements)
        modified = _replace_yaml_named_values(modified, "Форма", form_replacements)
        modified = _replace_yaml_named_values(modified, "ТипФормы", replacements)
        modified = _replace_yaml_named_values(
            modified,
            "Таблица",
            {old_name: replacements[old_name]},
        )
        modified = _replace_yaml_named_values(modified, "Ключ", replacements, qualified_only=True)
        modified = _replace_yaml_named_values(
            modified,
            "Выражение",
            replacements,
            qualified_only=True,
        )
        modified = _replace_yaml_named_values(
            modified,
            "ИсточникДанных",
            {old_name: replacements[old_name]},
        )
        modified = _replace_yaml_named_values(modified, "СозданиеНаОсновании", replacements)
        modified = _replace_yaml_expressions(modified, replacements)

        expression = stripped[1:].lstrip() if stripped.startswith("-") else stripped
        if expression.lstrip("'\"").startswith("="):
            comment_at = _yaml_comment_index(modified)
            reference_part = modified[:comment_at] if comment_at is not None else modified
            comment = modified[comment_at:] if comment_at is not None else ""
            result.append(_replace_expression_code(reference_part, replacements) + comment)
        else:
            result.append(modified)
    return "".join(result)


def apply_substitutions(
    content: str,
    old_name: str,
    new_name: str,
    new_presentation: str | None = None,
    old_presentation: str | None = None,
    replace_labels: bool = False,
    exact_replacements: dict[str, str] | None = None,
    rename_imports: bool = True,
    file_extension: str | None = None,
    replace_identity: bool = True,
    rename_form_reference: bool = False,
) -> str:
    """Применяет все замены к тексту, возвращает изменённый текст.

    replace_labels=True только для файлов объекта и его форм (файлы из списка переименований).
    Для всех остальных файлов (Подсистема.yaml, документы и т.д.) поля Заголовок/Представление
    не трогаются.
    """
    replacements = exact_replacements or _default_exact_replacements(old_name, new_name)

    extension = file_extension
    if extension is None:
        extension = YAML_EXT if re.search(r"^\s*[А-Яа-яЁёA-Za-z]+\s*:", content, re.MULTILINE) else XBSL_EXT
    if extension == YAML_EXT:
        content = _replace_yaml_references(
            content,
            old_name,
            replacements,
            replace_identity,
            rename_imports,
            rename_form_reference,
        )
    elif extension == XBQL_EXT:
        content = _replace_query_references(content, old_name, new_name)
    else:
        content = _replace_xbsl_references(content, old_name, new_name, replacements)

    # Поля Представление/Заголовок — только для файла объекта и его форм
    if replace_labels:
        content = _replace_label_fields(content, old_name, new_presentation or new_name, old_presentation)
    return content


_LABEL_FIELD_RE = re.compile(
    r'''^(?P<prefix>\ufeff?[ \t]*(?:Представление|Заголовок|"Представление"|"Заголовок"|'Представление'|'Заголовок')[ \t]*:[ \t]*)'''
    r"(?P<value>[^\r\n]*)(?P<newline>\r?\n)?$",
    re.MULTILINE | re.UNICODE,
)

# Строки, начинающиеся с Представление: или Заголовок: — не трогаются базовой заменой
_LABEL_LINE_RE = re.compile(
    r"^\s*(?:Представление|Заголовок)\s*:",
    re.UNICODE,
)


def _replace_label_fields(
    content: str,
    old_name: str,
    new_presentation: str,
    old_presentation: str | None = None,
) -> str:
    """
    Заменяет значения полей Представление/Заголовок если:
    - значение является «корнем» старого имени (old_name начинается с этого значения, минимум 3 символа), или
    - значение совпадает с явно заданным old_presentation.
    Использует new_presentation как новое значение (может содержать пробелы).
    """
    def replacer(m: re.Match) -> str:
        raw_value = m.group("value")
        comment_at = _yaml_comment_index(raw_value)
        scalar_part = raw_value[:comment_at] if comment_at is not None else raw_value
        comment = raw_value[comment_at:] if comment_at is not None else ""
        leading = scalar_part[: len(scalar_part) - len(scalar_part.lstrip())]
        trailing = scalar_part[len(scalar_part.rstrip()):]
        stripped = scalar_part.strip()
        quote = stripped[0] if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'} else ""
        value = stripped[1:-1] if quote else stripped
        if value == new_presentation:
            return m.group(0)
        replacement: str | None = None
        if old_presentation and value == old_presentation:
            replacement = new_presentation
        elif len(value) >= 3 and old_name.startswith(value):
            replacement = new_presentation
        if replacement is None:
            return m.group(0)
        rendered = f"{quote}{replacement}{quote}" if quote else replacement
        return (
            m.group("prefix") + leading + rendered + trailing + comment
            + (m.group("newline") or "")
        )

    return _LABEL_FIELD_RE.sub(replacer, content)


def changed_lines(original: str, modified: str, filepath: str) -> list[str]:
    """Возвращает строки с изменениями в формате diff-подобного вывода."""
    orig_lines = original.splitlines()
    mod_lines = modified.splitlines()
    result: list[str] = []
    for i, (old_line, new_line) in enumerate(zip(orig_lines, mod_lines), start=1):
        if old_line != new_line:
            result.append(f"  строка {i}:")
            result.append(f"    - {old_line.strip()}")
            result.append(f"    + {new_line.strip()}")
    return result


# ---------------------------------------------------------------------------
# Переименование файлов
# ---------------------------------------------------------------------------

def new_filename(
    name: str,
    old_name: str,
    new_name: str,
    exact_replacements: dict[str, str] | None = None,
) -> str:
    """Вычисляет имя файла только для точного объекта/companion-артефакта."""
    replacements = exact_replacements or _default_exact_replacements(old_name, new_name)
    for old_token in sorted(replacements, key=len, reverse=True):
        new_token = replacements[old_token]
        suffixes = (YAML_EXT, XBSL_EXT) if old_token != old_name else (
            YAML_EXT,
            XBSL_EXT,
            ".Объект" + XBSL_EXT,
            XBQL_EXT,
        )
        for suffix in suffixes:
            if name == old_token + suffix:
                return new_token + suffix
    return name


def files_to_rename(
    project_files: list[str],
    old_name: str,
    new_name: str,
    exact_replacements: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    """Находит файлы, которые нужно переименовать (старый путь, новый путь)."""
    renames: list[tuple[str, str]] = []
    for path in project_files:
        base = os.path.basename(path)
        new_base = new_filename(base, old_name, new_name, exact_replacements)
        if new_base != base:
            new_path = os.path.join(os.path.dirname(path), new_base)
            renames.append((path, new_path))
    return renames


# ---------------------------------------------------------------------------
# Поиск объекта
# ---------------------------------------------------------------------------

def find_object_files(project_files: list[str], old_name: str) -> list[tuple[str, str]]:
    """Находит все YAML-файлы с полем Имя: {old_name}.

    Возвращает список (path, вид_элемента).
    """
    result: list[tuple[str, str]] = []
    for path in project_files:
        if not path.endswith(YAML_EXT):
            continue
        text = read_text(path)
        if text and get_yaml_field(text, "Имя") == old_name:
            kind = get_yaml_field(text, "ВидЭлемента") or "?"
            result.append((path, kind))
    return result


# ---------------------------------------------------------------------------
# Основная логика
# ---------------------------------------------------------------------------

def linked_form_names(object_file: str) -> set[str]:
    """Извлекает точные значения всех полей ``Форма:`` из YAML владельца."""
    text = read_text(object_file) or ""
    result: set[str] = set()
    for line in text.splitlines():
        for key, start, end in _yaml_field_ranges(line):
            if key != "Форма":
                continue
            value = _parse_yaml_scalar(line[start:end].rstrip(" ,\t"))
            if value:
                result.add(value)
    return result


def exact_replacements_for_object(object_file: str, old_name: str, new_name: str) -> dict[str, str]:
    """Строит карту объекта и только явно привязанных conventional-форм."""
    replacements = {old_name: new_name}
    linked_forms = linked_form_names(object_file)
    for suffix in FORM_SUFFIXES:
        old_form = old_name + suffix
        if old_form in linked_forms:
            replacements[old_form] = new_name + suffix
    return replacements


def object_family(object_file: str, old_name: str) -> set[str]:
    """Точные файлы владельца и явно указанных им форм, без prefix-поиска."""
    obj_dir = os.path.dirname(object_file)
    object_text = read_text(object_file) or ""
    object_kind = get_yaml_field(object_text, "ВидЭлемента")
    candidates = {
        old_name + YAML_EXT,
        old_name + XBSL_EXT,
        old_name + ".Объект" + XBSL_EXT,
    }
    if object_kind in {"Отчет", "Отчёт"}:
        candidates.add(old_name + XBQL_EXT)
    linked_forms = linked_form_names(object_file)
    for suffix in FORM_SUFFIXES:
        form_name = old_name + suffix
        if form_name in linked_forms:
            candidates.add(form_name + YAML_EXT)
            candidates.add(form_name + XBSL_EXT)
    family = {
        os.path.join(obj_dir, filename)
        for filename in candidates
        if os.path.isfile(os.path.join(obj_dir, filename))
    }
    family.add(object_file)
    return family


def build_plan(
    project_files: list[str],
    old_name: str,
    new_name: str,
    new_presentation: str | None = None,
    old_presentation: str | None = None,
    object_file: str | None = None,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
    """
    Возвращает:
    - text_changes: список (path, original, modified) для файлов с заменами в тексте
    - renames: список (old_path, new_path) для файлов на переименование

    object_file — путь к файлу переименуемого объекта (из find_object_files).
    replace_labels=True только для файлов семейства этого объекта.
    """
    if object_file is None:
        matches = find_object_files(project_files, old_name)
        if len(matches) == 1:
            object_file = matches[0][0]

    exact_replacements = (
        exact_replacements_for_object(object_file, old_name, new_name)
        if object_file
        else _default_exact_replacements(old_name, new_name)
    )
    object_kind = get_yaml_field(read_text(object_file) or "", "ВидЭлемента") if object_file else None
    # Единственная owner-family модель используется и для paths, и для labels.
    label_files: set[str] = object_family(object_file, old_name) if object_file else set()
    rename_sources = sorted(label_files) if object_file else project_files
    renames = files_to_rename(rename_sources, old_name, new_name, exact_replacements)

    text_changes: list[tuple[str, str, str]] = []

    for path in project_files:
        text = read_text(path)
        if text is None:
            raise RenameCollisionError(f"не удалось прочитать файл проекта: {path}")
        replace_labels = path in label_files
        modified = apply_substitutions(
            text,
            old_name,
            new_name,
            new_presentation,
            old_presentation,
            replace_labels,
            exact_replacements,
            rename_imports=False,
            file_extension=os.path.splitext(path)[1],
            replace_identity=replace_labels,
            rename_form_reference=object_kind == "КомпонентИнтерфейса",
        )
        if modified != text:
            text_changes.append((path, text, modified))

    return text_changes, renames


def print_plan(
    text_changes: list[tuple[str, str, str]],
    renames: list[tuple[str, str]],
    root: str,
) -> None:
    def rel(path: str) -> str:
        return os.path.relpath(path, root)

    if renames:
        print(f"\n=== Файлы для переименования ({len(renames)}) ===")
        for old_path, new_path in renames:
            print(f"  {rel(old_path)}")
            print(f"    → {rel(new_path)}")
    else:
        print("\n=== Файлы для переименования: нет ===")

    if text_changes:
        print(f"\n=== Текстовые замены в файлах ({len(text_changes)}) ===")
        for path, original, modified in text_changes:
            lines = changed_lines(original, modified, path)
            if lines:
                print(f"\n  {rel(path)}:")
                for line in lines:
                    print(line)
    else:
        print("\n=== Текстовые замены: нет ===")


def apply_plan(
    text_changes: list[tuple[str, str, str]],
    renames: list[tuple[str, str]],
) -> None:
    validate_path_collisions(renames)

    # Сначала применяем текстовые замены
    for path, _original, modified in text_changes:
        write_text(path, modified)

    # Затем переименовываем файлы (после записи, чтобы не потерять содержимое)
    for old_path, new_path in renames:
        os.rename(old_path, new_path)


def _normalized_path_key(path: str) -> str:
    return unicodedata.normalize("NFC", os.path.abspath(path)).casefold()


def _normalized_identifier_key(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def is_valid_project_identifier(name: str) -> bool:
    return (
        name.isidentifier()
        and _normalized_identifier_key(name) not in XBSL_RESERVED_WORDS
    )


def validate_path_collisions(renames: list[tuple[str, str]]) -> None:
    """Проверяет все пути назначения до первой записи."""
    destinations: dict[str, str] = {}
    for old_path, new_path in renames:
        old_key = _normalized_path_key(old_path)
        new_key = _normalized_path_key(new_path)
        if old_key == new_key and os.path.abspath(old_path) != os.path.abspath(new_path):
            raise RenameCollisionError(
                f"коллизия регистра/Unicode пути: {old_path} → {new_path}"
            )
        previous = destinations.get(new_key)
        if previous is not None and os.path.abspath(previous) != os.path.abspath(old_path):
            raise RenameCollisionError(
                f"несколько файлов претендуют на путь {new_path}: {previous}, {old_path}"
            )
        destinations[new_key] = old_path
        if os.path.lexists(new_path) and os.path.abspath(new_path) != os.path.abspath(old_path):
            raise RenameCollisionError(f"путь назначения уже существует: {new_path}")
        try:
            siblings = os.scandir(os.path.dirname(new_path))
        except OSError:
            siblings = ()
        with siblings if hasattr(siblings, "__enter__") else nullcontext(siblings) as entries:
            for entry in entries:
                if (
                    _normalized_path_key(entry.path) == new_key
                    and os.path.abspath(entry.path) != os.path.abspath(old_path)
                ):
                    raise RenameCollisionError(
                        f"путь с тем же регистром/Unicode-представлением уже существует: {entry.path}"
                    )


def validate_identifier_collisions(
    project_files: list[str],
    owned_files: set[str],
    target_names: set[str],
) -> None:
    """Запрещает существующий ``Имя: <target>`` вне выбранного семейства."""
    owned_keys = {_normalized_path_key(path) for path in owned_files}
    normalized_targets = {_normalized_identifier_key(name) for name in target_names}
    collisions: list[tuple[str, str]] = []
    for path in project_files:
        if not path.endswith(YAML_EXT) or _normalized_path_key(path) in owned_keys:
            continue
        text = read_text(path)
        name = get_yaml_field(text, "Имя") if text is not None else None
        if name is not None and _normalized_identifier_key(name) in normalized_targets:
            collisions.append((path, name))
    if collisions:
        details = "; ".join(f"{name}: {path}" for path, name in collisions)
        raise RenameCollisionError(f"коллизия логического имени: {details}")


def validate_project_readability(project_files: list[str]) -> None:
    """Fail-closed: безопасный план невозможен, если файл нельзя проверить."""
    unreadable = [path for path in project_files if read_text(path) is None]
    if unreadable:
        raise RenameCollisionError(
            "не удалось прочитать файлы проекта: " + "; ".join(unreadable)
        )


def validate_source_ambiguities(
    project_files: list[str],
    owned_files: set[str],
    old_name: str,
    replacements: dict[str, str],
) -> None:
    """Запрещает одноимённые source identifiers/companions вне owner-family."""
    owned_keys = {_normalized_path_key(path) for path in owned_files}
    owned_basenames = {os.path.basename(path) for path in owned_files}
    expected_basenames = {
        old_name + YAML_EXT,
        old_name + XBSL_EXT,
        old_name + ".Объект" + XBSL_EXT,
    }
    if old_name + XBQL_EXT in owned_basenames:
        expected_basenames.add(old_name + XBQL_EXT)
    for source_name in replacements:
        if source_name != old_name:
            expected_basenames.add(source_name + YAML_EXT)
            expected_basenames.add(source_name + XBSL_EXT)
    new_name = replacements[old_name]
    destination_basenames = {
        new_name + YAML_EXT,
        new_name + XBSL_EXT,
        new_name + ".Объект" + XBSL_EXT,
    }
    if old_name + XBQL_EXT in owned_basenames:
        destination_basenames.add(new_name + XBQL_EXT)
    for source_name, target_name in replacements.items():
        if source_name != old_name:
            destination_basenames.add(target_name + YAML_EXT)
            destination_basenames.add(target_name + XBSL_EXT)
    normalized_basenames = {
        _normalized_identifier_key(name)
        for name in expected_basenames | destination_basenames
    }
    source_names = {_normalized_identifier_key(name) for name in replacements}
    collisions: list[str] = []
    for path in project_files:
        if _normalized_path_key(path) in owned_keys:
            continue
        if _normalized_identifier_key(os.path.basename(path)) in normalized_basenames:
            collisions.append(path)
            continue
        if path.endswith(YAML_EXT):
            text = read_text(path)
            if text is not None:
                logical_name = get_yaml_field(text, "Имя")
                if (
                    logical_name is not None
                    and _normalized_identifier_key(logical_name) in source_names
                ):
                    collisions.append(path)
    if collisions:
        raise RenameCollisionError(
            "коллизия или неоднозначный logical address/companion вне выбранного семейства: "
            + "; ".join(sorted(set(collisions)))
        )


def owning_project_root(object_file: str, project_roots: list[str]) -> str | None:
    """Находит единственный проект, содержащий выбранный объект."""
    object_path = os.path.abspath(object_file)
    owners = []
    for project_root in project_roots:
        project_path = os.path.abspath(project_root)
        try:
            if os.path.commonpath((object_path, project_path)) == project_path:
                owners.append(project_path)
        except ValueError:
            continue
    return max(owners, key=len) if owners else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Безопасное переименование объекта конфигурации 1С:Элемент"
    )
    parser.add_argument("--old-name", required=True, help="Текущее имя объекта")
    parser.add_argument("--new-name", required=True, help="Новое имя объекта")
    parser.add_argument(
        "--new-presentation",
        default=None,
        help="Человекочитаемое представление (Представление/Заголовок). "
             "Если не задано — используется --new-name.",
    )
    parser.add_argument(
        "--old-presentation",
        default=None,
        help="Старое представление объекта (Представление/Заголовок). "
             "Используется для замены значений в полях Заголовок/Представление, "
             "которые не совпадают с техническим именем (напр. «Место хранения» для МестаХранения).",
    )
    parser.add_argument("--root", default=".", help="Корневая папка поиска (по умолчанию: .)")
    parser.add_argument(
        "--object-file",
        default=None,
        help="Путь к файлу переименуемого объекта (относительно --root или абсолютный). "
             "Обязателен если в проекте несколько объектов с одинаковым именем.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Применить изменения (без флага — только показать план)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = os.path.abspath(args.root)
    old_name: str = args.old_name
    new_name: str = args.new_name
    new_presentation: str = args.new_presentation if args.new_presentation else new_name
    old_presentation: str | None = args.old_presentation

    if not is_valid_project_identifier(old_name) or not is_valid_project_identifier(new_name):
        print(
            "Ошибка: --old-name и --new-name должны быть одиночными идентификаторами "
            "без путей и не могут быть ключевыми словами XBSL.",
            file=sys.stderr,
        )
        sys.exit(1)

    project_roots = find_project_roots(root)
    if not project_roots:
        print(f"Ошибка: проекты не найдены (нет папок с {PROJECT_FILE}) в {root}", file=sys.stderr)
        sys.exit(1)

    # Сначала собираем файлы всех проектов только для однозначного выбора объекта.
    all_files: list[str] = []
    for proj_root in project_roots:
        all_files.extend(collect_project_files(proj_root))

    # Определяем файл объекта
    if args.object_file:
        object_file = os.path.abspath(os.path.join(root, args.object_file))
        if not os.path.isfile(object_file):
            print(f"Ошибка: файл «{args.object_file}» не найден.", file=sys.stderr)
            sys.exit(1)
        object_text = read_text(object_file)
        if object_text is None or get_yaml_field(object_text, "Имя") != old_name:
            print(
                f"Ошибка: файл «{args.object_file}» не описывает объект с именем «{old_name}».",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        matches = find_object_files(all_files, old_name)
        if not matches:
            print(f"Ошибка: объект с именем «{old_name}» не найден в проектах.", file=sys.stderr)
            sys.exit(1)
        if len(matches) > 1:
            print(f"Найдено несколько объектов с именем «{old_name}»:", file=sys.stderr)
            for path, kind in matches:
                print(f"  [{kind}]  {os.path.relpath(path, root)}", file=sys.stderr)
            print(
                f"\nУкажите нужный объект через --object-file <путь>",
                file=sys.stderr,
            )
            sys.exit(2)
        object_file = matches[0][0]

    project_root = owning_project_root(object_file, project_roots)
    if project_root is None:
        print("Ошибка: выбранный объект не принадлежит найденному проекту.", file=sys.stderr)
        sys.exit(1)

    # После выбора логического объекта меняем только его owning project. Это
    # исключает порчу одноимённых объектов в соседних проектах под общим root.
    project_files = collect_project_files(project_root)
    try:
        validate_project_readability(project_files)
    except RenameCollisionError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        sys.exit(1)
    local_matches = find_object_files(project_files, old_name)
    if len(local_matches) > 1:
        print(
            "Ошибка: в выбранном проекте несколько объектов с таким именем; "
            "точные неквалифицированные ссылки неоднозначны, переименование остановлено.",
            file=sys.stderr,
        )
        sys.exit(2)

    print(f"Объект: {os.path.relpath(object_file, root)}")
    print(f"Переименование: «{old_name}» → «{new_name}»")
    if new_presentation != new_name:
        print(f"Представление: «{new_presentation}»")

    try:
        text_changes, renames = build_plan(
            project_files,
            old_name,
            new_name,
            new_presentation,
            old_presentation,
            object_file,
        )
        replacements = exact_replacements_for_object(object_file, old_name, new_name)
        owned_files = object_family(object_file, old_name)
        validate_source_ambiguities(
            project_files,
            owned_files,
            old_name,
            replacements,
        )
        validate_identifier_collisions(project_files, owned_files, set(replacements.values()))
        validate_path_collisions(renames)
    except RenameCollisionError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        sys.exit(1)

    print_plan(text_changes, renames, root)

    total = len(text_changes) + len(renames)
    if total == 0:
        print("\nИзменений нет.")
        return

    if not args.apply:
        print(f"\n--- Dry-run. Для применения добавьте флаг --apply ---")
        return

    try:
        apply_plan(text_changes, renames)
    except RenameCollisionError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        sys.exit(1)
    print(f"\n✓ Применено: {len(text_changes)} файлов обновлено, {len(renames)} переименовано.")


if __name__ == "__main__":
    main()
