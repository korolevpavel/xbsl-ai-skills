#!/usr/bin/env python3
"""
Генерирует HttpСервис (.yaml + .xbsl) для проекта 1С:Элемент.

Режим 1 — создать новый сервис:
    python3 .claude/skills/xbsl-meta-add/scripts/generate_http.py \\
      --name КонтрагентыHttpСервис \\
      --url /api/counterparties \\
      --routes "GET /, POST /, GET /{id}, PUT /{id}, DELETE /{id}" \\
      --root tools/test-app-1cmycloud [--apply]

Режим 2 — добавить маршруты в существующий сервис:
    python3 .claude/skills/xbsl-meta-add/scripts/generate_http.py \\
      --service КонтрагентыHttpСервис \\
      --add-routes "DELETE /{id}, PATCH /{id}/photo" \\
      --root tools/test-app-1cmycloud [--apply]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

PROJECT_FILE = "Проект.yaml"
SUBSYSTEM_FILE = "Подсистема.yaml"

# Порядок HTTP методов для вывода
METHOD_ORDER = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

# Правила автоименования обработчиков: (метод, признак_параметра_в_пути) -> имя
HANDLER_NAMES: dict[tuple[str, bool], str] = {
    ("GET", False): "ПолучитьСписок",
    ("POST", False): "Создать",
    ("GET", True): "ПолучитьПоИд",
    ("PUT", True): "Обновить",
    ("PATCH", True): "ОбновитьЧастично",
    ("DELETE", True): "Удалить",
}


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def read_text(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


# ---------------------------------------------------------------------------
# Разведка проекта (рекурсивный поиск, как в form_info.py)
# ---------------------------------------------------------------------------

def find_project_dirs(root: str) -> list[str]:
    """Рекурсивно ищет папки с Проект.yaml, начиная с root."""
    if os.path.isfile(os.path.join(root, PROJECT_FILE)):
        return [root]
    result: list[str] = []
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        return result
    for entry in entries:
        if entry.is_dir():
            result.extend(find_project_dirs(entry.path))
    return result


def get_suggested_path(name: str, root: str, subsystem_hint: str | None = None) -> tuple[str, bool]:
    """Возвращает (suggested_path, conflict_exists).
    При ошибке печатает сообщение и завершает процесс."""
    project_dirs = find_project_dirs(root)
    if not project_dirs:
        print(f"Ошибка: не найдено ни одного проекта в {root}. Создайте проект через xbsl-init.", file=sys.stderr)
        sys.exit(1)

    # Собираем подсистемы из всех проектов
    subsystem_paths: list[str] = []
    conflict = False
    for proj_dir in project_dirs:
        try:
            entries = sorted(os.scandir(proj_dir), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            if not os.path.isfile(os.path.join(entry.path, SUBSYSTEM_FILE)):
                continue
            subsystem_paths.append(entry.path)
            # Проверяем конфликт
            yaml_file = os.path.join(entry.path, f"{name}.yaml")
            if os.path.isfile(yaml_file):
                conflict = True

    if not subsystem_paths:
        # Проект без подсистем — кладём прямо в папку проекта
        suggested = project_dirs[0]
    else:
        suggested = subsystem_paths[0]
        # Если указана подсказка — ищем подсистему с таким именем
        if subsystem_hint:
            for sp in subsystem_paths:
                if os.path.basename(sp) == subsystem_hint:
                    suggested = sp
                    break

    return suggested, conflict


# ---------------------------------------------------------------------------
# Парсинг маршрутов
# ---------------------------------------------------------------------------

def parse_routes(routes_str: str) -> list[tuple[str, str]]:
    """Парсит строку маршрутов в список (метод, путь).
    Формат: "GET /, POST /, GET /{id}" или "GET /\nPOST /"."""
    result: list[tuple[str, str]] = []
    for part in re.split(r"[,\n]+", routes_str):
        part = part.strip()
        if not part:
            continue
        tokens = part.split(None, 1)
        if len(tokens) != 2:
            print(f"Неверный формат маршрута: '{part}' (ожидается 'МЕТОД /путь')", file=sys.stderr)
            sys.exit(1)
        method, path = tokens[0].upper(), tokens[1].strip()
        if not path.startswith("/"):
            path = "/" + path
        result.append((method, path))
    return result


def group_by_template(routes: list[tuple[str, str]]) -> list[tuple[str, list[str]]]:
    """Группирует маршруты по шаблону URL, сохраняя порядок появления шаблонов.
    Возвращает [(путь, [методы])]."""
    seen: dict[str, list[str]] = {}
    order: list[str] = []
    for method, path in routes:
        if path not in seen:
            seen[path] = []
            order.append(path)
        if method not in seen[path]:
            seen[path].append(method)
    # Сортировать методы по METHOD_ORDER
    for path in order:
        seen[path].sort(key=lambda m: METHOD_ORDER.index(m) if m in METHOD_ORDER else 99)
    return [(path, seen[path]) for path in order]


def has_path_param(path: str) -> bool:
    """Проверяет, содержит ли шаблон параметры пути {xxx}."""
    return bool(re.search(r"\{[^}]+\}", path))


def template_name(path: str) -> str:
    """Авто-имя для шаблона URL.
    / → Список
    /{id} → ЭлементПоИд
    /{id}/items → ЭлементыПоРодителю
    /users → Пользователи (из сегментов)
    """
    if path == "/":
        return "Список"

    # Убираем ведущий слеш
    segments = [s for s in path.lstrip("/").split("/") if s]

    if len(segments) == 1:
        seg = segments[0]
        if seg.startswith("{") and seg.endswith("}"):
            return "ЭлементПоИд"
        # Литеральный сегмент — ПаскальКейс из кириллицы/латиницы
        return _to_pascal(seg)

    # Несколько сегментов — берём последний, убирая параметры
    literal_segs = [s for s in segments if not (s.startswith("{") and s.endswith("}"))]
    param_segs = [s for s in segments if s.startswith("{") and s.endswith("}")]

    if literal_segs and param_segs:
        return _to_pascal(literal_segs[-1]) + "ПоРодителю"
    if literal_segs:
        return _to_pascal(literal_segs[-1])
    # Всё параметры
    return "ЭлементПоИд"


def _to_pascal(s: str) -> str:
    """Простейшее преобразование: первая буква заглавная, остальное как есть."""
    if not s:
        return s
    # Убираем фигурные скобки
    s = s.strip("{}")
    return s[0].upper() + s[1:]


def handler_name(method: str, path: str, tpl_name: str) -> str:
    """Авто-имя обработчика для метода+пути."""
    key = (method, has_path_param(path))
    if key in HANDLER_NAMES:
        return HANDLER_NAMES[key]
    # Фолбэк: <Метод><ИмяШаблона>
    method_ru = {
        "GET": "Получить", "POST": "Создать", "PUT": "Обновить",
        "PATCH": "ОбновитьЧастично", "DELETE": "Удалить",
    }.get(method, method.capitalize())
    return f"{method_ru}{tpl_name}"


# ---------------------------------------------------------------------------
# Генерация YAML
# ---------------------------------------------------------------------------

def build_yaml(name: str, url: str, access: str,
               templates: list[tuple[str, list[str]]]) -> str:
    """Собирает YAML для HttpСервис."""
    uid = str(uuid.uuid4())
    lines = [
        f"ВидЭлемента: HttpСервис",
        f"Ид: {uid}",
        f"Имя: {name}",
        f"ОбластьВидимости: ВПодсистеме",
        f"КорневойUrl: {url}",
        f"КонтрольДоступа:",
        f"    Разрешения:",
        f"        Вызов: {access}",
        f"ШаблоныUrl:",
    ]

    for path, methods in templates:
        tpl_nm = template_name(path)
        lines.append(f"    -")
        lines.append(f"        Имя: {tpl_nm}")
        lines.append(f"        Шаблон: {path}")
        lines.append(f"        Методы:")
        for method in methods:
            hdl = handler_name(method, path, tpl_nm)
            lines.append(f"            -")
            lines.append(f"                Метод: {method}")
            lines.append(f"                Обработчик: {hdl}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Генерация XBSL
# ---------------------------------------------------------------------------

def _xbsl_get_list(handler: str) -> str:
    return f"""\
метод {handler}(Запрос: HttpСервисЗапрос)
    попытка
        знч Ограничение = 100
        знч ПараметрЛимит = Запрос.Параметры.ПолучитьПервый("limit")
        если ПараметрЛимит != Неопределено
            Ограничение = Мин(Число.ПарсерИзСтроки(ПараметрЛимит), 100)
        ;
        // TODO: получить данные
        // знч Данные = <Справочник>.ПолучитьСписок(Ограничение)
        Запрос.Ответ.Заголовки.Установить("Content-Type", "application/json")
        // Запрос.Ответ.УстановитьТело(СериализацияJson.ЗаписатьОбъект(Данные))
    поймать Исключение: Исключение
        _ОбработатьОшибку(Запрос.Ответ, Исключение)
    ;
;"""


def _xbsl_create(handler: str) -> str:
    return f"""\
метод {handler}(Запрос: HttpСервисЗапрос)
    попытка
        // TODO: десериализовать тело и создать объект
        // знч Данные = СериализацияJson.ПрочитатьОбъект(Запрос.Тело, Тип<...>)
        // знч Ссылка = <Справочник>.Создать(Данные)
        Запрос.Ответ.КодСтатуса = 201
        // Запрос.Ответ.УстановитьТело(Ссылка.Ид.ВСтроку())
    поймать Исключение: Исключение
        _ОбработатьОшибку(Запрос.Ответ, Исключение)
    ;
;"""


def _xbsl_get_by_id(handler: str, param: str) -> str:
    return f"""\
метод {handler}(Запрос: HttpСервисЗапрос)
    попытка
        знч Ид = Запрос.ПараметрыПути.ПолучитьПервый("{param}")
        // TODO: найти объект по Ид
        // знч Объект = <Справочник>.НайтиПоИд(Ид)
        // если Объект == Неопределено
        //     Запрос.Ответ.КодСтатуса = 404
        //     возврат
        // ;
        // Запрос.Ответ.УстановитьТело(СериализацияJson.ЗаписатьОбъект(Объект))
    поймать Исключение: Исключение
        _ОбработатьОшибку(Запрос.Ответ, Исключение)
    ;
;"""


def _xbsl_stub(handler: str, method: str) -> str:
    return f"""\
метод {handler}(Запрос: HttpСервисЗапрос)
    попытка
        // TODO: реализовать {method}
    поймать Исключение: Исключение
        _ОбработатьОшибку(Запрос.Ответ, Исключение)
    ;
;"""


def _xbsl_error_helper() -> str:
    return """\
метод _ОбработатьОшибку(Ответ: HttpСервисОтвет, Исключение: Исключение)
    Ответ.КодСтатуса = 500
    Ответ.УстановитьТело(Исключение.ИнформацияОбОшибке())
;"""


def _extract_path_param(path: str) -> str:
    """Возвращает имя первого параметра пути, например 'id' из '/{id}'."""
    m = re.search(r"\{([^}]+)\}", path)
    return m.group(1) if m else "id"


def build_xbsl(templates: list[tuple[str, list[str]]]) -> str:
    """Собирает XBSL с заготовками обработчиков."""
    blocks: list[str] = []

    for path, methods in templates:
        tpl_nm = template_name(path)
        for method in methods:
            hdl = handler_name(method, path, tpl_nm)
            has_param = has_path_param(path)
            key = (method, has_param)

            if key == ("GET", False):
                blocks.append(_xbsl_get_list(hdl))
            elif key == ("POST", False):
                blocks.append(_xbsl_create(hdl))
            elif key == ("GET", True):
                param = _extract_path_param(path)
                blocks.append(_xbsl_get_by_id(hdl, param))
            else:
                blocks.append(_xbsl_stub(hdl, method))

    blocks.append(_xbsl_error_helper())
    return "\n\n".join(blocks) + "\n"


# ---------------------------------------------------------------------------
# Добавление маршрутов в существующий сервис
# ---------------------------------------------------------------------------

def find_service_files(name: str, root: str) -> tuple[str, str] | None:
    """Ищет .yaml и .xbsl файлы существующего сервиса по имени.
    Возвращает (yaml_path, xbsl_path) или None если не найден."""
    project_dirs = find_project_dirs(root)
    for proj_dir in project_dirs:
        try:
            entries = sorted(os.scandir(proj_dir), key=lambda e: e.name)
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            yaml_path = os.path.join(entry.path, f"{name}.yaml")
            if not os.path.isfile(yaml_path):
                continue
            text = read_text(yaml_path) or ""
            # Проверяем что это HttpСервис с нужным именем
            if "ВидЭлемента: HttpСервис" not in text:
                continue
            xbsl_path = os.path.join(entry.path, f"{name}.xbsl")
            return yaml_path, xbsl_path
    return None


def yaml_append_templates(yaml_text: str, templates: list[tuple[str, list[str]]]) -> str:
    """Добавляет новые шаблоны URL или методы в существующие шаблоны YAML.
    Если шаблон с таким путём уже есть — добавляет методы в него.
    Иначе — добавляет новый шаблон в конец."""
    result = yaml_text
    new_template_lines: list[str] = []

    for path, methods in templates:
        tpl_nm = template_name(path)
        path_escaped = re.escape(path)
        if re.search(rf"        Шаблон: {path_escaped}\n", result):
            # Путь уже есть — вставляем методы в существующий шаблон
            result = _yaml_insert_methods(result, path, methods, tpl_nm)
        else:
            # Новый путь — добавляем новый блок
            new_template_lines.append(f"    -")
            new_template_lines.append(f"        Имя: {tpl_nm}")
            new_template_lines.append(f"        Шаблон: {path}")
            new_template_lines.append(f"        Методы:")
            for method in methods:
                hdl = handler_name(method, path, tpl_nm)
                new_template_lines.append(f"            -")
                new_template_lines.append(f"                Метод: {method}")
                new_template_lines.append(f"                Обработчик: {hdl}")

    if new_template_lines:
        suffix = "\n".join(new_template_lines) + "\n"
        result = result.rstrip("\n") + "\n" + suffix

    return result


def _yaml_insert_methods(yaml_text: str, path: str, methods: list[str], tpl_nm: str) -> str:
    """Вставляет методы в существующий шаблон YAML с заданным путём."""
    path_escaped = re.escape(path)
    m = re.search(rf"        Шаблон: {path_escaped}\n", yaml_text)
    if not m:
        return yaml_text

    # Конец блока — следующий "    -\n" на уровне шаблона или конец файла
    search_from = m.end()
    next_block = re.search(r"\n    -\n", yaml_text[search_from:])
    block_end = search_from + next_block.start() + 1 if next_block else len(yaml_text)
    block = yaml_text[search_from:block_end]

    # Вставляем после последнего Обработчик: в блоке
    last_hdl = None
    for hdl_m in re.finditer(r"                Обработчик: \S+[^\n]*\n", block):
        last_hdl = hdl_m

    if last_hdl:
        insert_pos = search_from + last_hdl.end()
    else:
        # Нет методов — вставить после "        Методы:\n"
        methods_m = re.search(r"        Методы:\n", block)
        if not methods_m:
            return yaml_text
        insert_pos = search_from + methods_m.end()

    new_lines: list[str] = []
    for method in methods:
        hdl = handler_name(method, path, tpl_nm)
        new_lines += [f"            -",
                      f"                Метод: {method}",
                      f"                Обработчик: {hdl}"]
    insertion = "\n".join(new_lines) + "\n"
    return yaml_text[:insert_pos] + insertion + yaml_text[insert_pos:]


def xbsl_append_handlers(xbsl_text: str, templates: list[tuple[str, list[str]]]) -> str:
    """Добавляет новые обработчики в XBSL — перед _ОбработатьОшибку, если есть."""
    new_blocks: list[str] = []
    for path, methods in templates:
        tpl_nm = template_name(path)
        for method in methods:
            hdl = handler_name(method, path, tpl_nm)
            has_param = has_path_param(path)
            key = (method, has_param)
            if key == ("GET", False):
                new_blocks.append(_xbsl_get_list(hdl))
            elif key == ("POST", False):
                new_blocks.append(_xbsl_create(hdl))
            elif key == ("GET", True):
                param = _extract_path_param(path)
                new_blocks.append(_xbsl_get_by_id(hdl, param))
            else:
                new_blocks.append(_xbsl_stub(hdl, method))

    if not new_blocks:
        return xbsl_text

    insertion = "\n\n".join(new_blocks)

    # Вставить перед _ОбработатьОшибку если есть, иначе в конец
    marker = "метод _ОбработатьОшибку"
    if marker in xbsl_text:
        idx = xbsl_text.index(marker)
        return xbsl_text[:idx] + insertion + "\n\n" + xbsl_text[idx:]

    return xbsl_text.rstrip("\n") + "\n\n" + insertion + "\n"


def get_existing_handlers(xbsl_text: str) -> set[str]:
    """Возвращает множество имён методов из XBSL."""
    return set(re.findall(r"^метод\s+(\w+)\s*\(", xbsl_text, re.MULTILINE))


# ---------------------------------------------------------------------------
# Dry-run вывод
# ---------------------------------------------------------------------------

def print_plan(
    name: str,
    yaml_path: str,
    xbsl_path: str,
    templates: list[tuple[str, list[str]]],
    conflict: bool,
    dry_run: bool,
) -> None:
    prefix = "[DRY-RUN]" if dry_run else "[ПРИМЕНЯЮ]"
    print(f"{prefix} xbsl-meta-add HttpСервис: {name}")
    print()
    print("Маршруты:")
    for path, methods in templates:
        tpl_nm = template_name(path)
        for method in methods:
            hdl = handler_name(method, path, tpl_nm)
            print(f"  {method:<8} {path:<20} → {hdl}")
    print()

    if conflict:
        print(f"  ⚠️  Сервис уже существует: {name}.yaml — будет перезаписан")
        print()

    action = "Будет создано" if dry_run else "Создано"
    print(f"{action}:")
    print(f"  {yaml_path}")
    print(f"  {xbsl_path}")

    if dry_run:
        print()
        print("Чтобы применить: добавьте --apply")


# ---------------------------------------------------------------------------
# Основная логика — режим создания
# ---------------------------------------------------------------------------

def run_create(args: argparse.Namespace) -> None:
    root = os.path.abspath(args.root)
    routes = parse_routes(args.routes)
    templates = group_by_template(routes)

    suggested_path, conflict = get_suggested_path(args.name, root, args.subsystem)

    yaml_path = os.path.join(suggested_path, f"{args.name}.yaml")
    xbsl_path = os.path.join(suggested_path, f"{args.name}.xbsl")

    print_plan(
        name=args.name,
        yaml_path=yaml_path,
        xbsl_path=xbsl_path,
        templates=templates,
        conflict=conflict,
        dry_run=not args.apply,
    )

    if not args.apply:
        return

    write_text(yaml_path, build_yaml(args.name, args.url, args.access, templates))
    write_text(xbsl_path, build_xbsl(templates))
    print()
    print("Готово.")


# ---------------------------------------------------------------------------
# Основная логика — режим добавления маршрутов
# ---------------------------------------------------------------------------

def run_add_routes(args: argparse.Namespace) -> None:
    root = os.path.abspath(args.root)
    routes = parse_routes(args.add_routes)
    templates = group_by_template(routes)

    found = find_service_files(args.service, root)
    if not found:
        print(f"Ошибка: сервис '{args.service}' не найден в {root}", file=sys.stderr)
        sys.exit(1)
    yaml_path, xbsl_path = found

    # Проверяем дублирующиеся обработчики
    existing_xbsl = read_text(xbsl_path) or ""
    existing_handlers = get_existing_handlers(existing_xbsl)
    duplicates: list[str] = []
    for path, methods in templates:
        tpl_nm = template_name(path)
        for method in methods:
            hdl = handler_name(method, path, tpl_nm)
            if hdl in existing_handlers:
                duplicates.append(hdl)

    prefix = "[DRY-RUN]" if not args.apply else "[ПРИМЕНЯЮ]"
    print(f"{prefix} добавление маршрутов в {args.service}")
    print()
    print("Новые маршруты:")
    for path, methods in templates:
        tpl_nm = template_name(path)
        for method in methods:
            hdl = handler_name(method, path, tpl_nm)
            warn = "  ⚠️  обработчик уже существует" if hdl in existing_handlers else ""
            print(f"  {method:<8} {path:<20} → {hdl}{warn}")
    print()

    action = "Будет обновлено" if not args.apply else "Обновлено"
    print(f"{action}:")
    print(f"  {yaml_path}  (ШаблоныUrl)")
    print(f"  {xbsl_path}  (новые методы)")

    if not args.apply:
        print()
        print("Чтобы применить: добавьте --apply")
        return

    if duplicates:
        print()
        print(f"⚠️  Обработчики уже существуют, пропускаем: {', '.join(duplicates)}")
        # Убираем дубликаты из шаблонов
        templates = [
            (path, [m for m in methods
                    if handler_name(m, path, template_name(path)) not in existing_handlers])
            for path, methods in templates
        ]
        templates = [(p, ms) for p, ms in templates if ms]

    if templates:
        yaml_text = read_text(yaml_path) or ""
        write_text(yaml_path, yaml_append_templates(yaml_text, templates))
        write_text(xbsl_path, xbsl_append_handlers(existing_xbsl, templates))

    print()
    print("Готово.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Генерирует HttpСервис (.yaml + .xbsl) для проекта 1С:Элемент"
    )

    # Режим 1: создать новый сервис
    parser.add_argument("--name", default=None, help="Имя нового сервиса")
    parser.add_argument("--url", default=None, help="КорневойUrl (например /api/counterparties)")
    parser.add_argument("--routes", default=None, help='Маршруты: "GET /, POST /, GET /{id}"')
    parser.add_argument("--subsystem", default=None, help="Имя подсистемы для размещения")
    parser.add_argument("--access", default="РазрешеноВсем", help="Контроль доступа")

    # Режим 2: добавить маршруты в существующий
    parser.add_argument("--service", default=None, help="Имя существующего сервиса")
    parser.add_argument("--add-routes", default=None, dest="add_routes",
                        help='Новые маршруты: "DELETE /{id}, PATCH /{id}/photo"')

    # Общие
    parser.add_argument("--root", default=".", help="Корень проекта")
    parser.add_argument("--apply", action="store_true", help="Применить (без — dry-run)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    if args.service and args.add_routes:
        run_add_routes(args)
    elif args.name and args.url and args.routes:
        run_create(args)
    else:
        print("Ошибка: укажите либо --name/--url/--routes (создать), "
              "либо --service/--add-routes (добавить маршруты)", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
