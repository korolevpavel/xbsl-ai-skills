#!/usr/bin/env python3
"""
Генерирует HttpСервис (.yaml + .xbsl) для проекта 1С:Элемент.

Использование:
    # Dry-run (показывает план):
    python3 .claude/skills/xbsl-meta-add/scripts/generate_http.py \\
      --name КонтрагентыHttpСервис \\
      --url /api/counterparties \\
      --routes "GET /, POST /, GET /{id}, PUT /{id}, DELETE /{id}" \\
      --root tools/test-app-1cmycloud

    # Применить:
    python3 .claude/skills/xbsl-meta-add/scripts/generate_http.py \\
      --name КонтрагентыHttpСервис \\
      --url /api/counterparties \\
      --routes "GET /, POST /, GET /{id}" \\
      --root tools/test-app-1cmycloud \\
      --apply
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
# Основная логика
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    root = os.path.abspath(args.root)
    routes = parse_routes(args.routes)
    templates = group_by_template(routes)

    # Найти путь размещения
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

    yaml_content = build_yaml(args.name, args.url, args.access, templates)
    xbsl_content = build_xbsl(templates)

    write_text(yaml_path, yaml_content)
    write_text(xbsl_path, xbsl_content)
    print()
    print("Готово.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Генерирует HttpСервис (.yaml + .xbsl) для проекта 1С:Элемент"
    )
    parser.add_argument("--name", required=True, help="Имя объекта (например КонтрагентыHttpСервис)")
    parser.add_argument("--url", required=True, help="КорневойUrl (например /api/counterparties)")
    parser.add_argument(
        "--routes",
        required=True,
        help='Маршруты через запятую: "GET /, POST /, GET /{id}"',
    )
    parser.add_argument("--root", default=".", help="Корень проекта (по умолчанию .)")
    parser.add_argument("--subsystem", default=None, help="Подсказка: имя подсистемы для размещения")
    parser.add_argument(
        "--access",
        default="РазрешеноВсем",
        help="Глобальный контроль доступа (по умолчанию РазрешеноВсем)",
    )
    parser.add_argument("--apply", action="store_true", help="Применить изменения (без флага — dry-run)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    run(parse_args(argv))


if __name__ == "__main__":
    main()
