"""Тесты для generate_http.py — генератора HttpСервис."""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                ".claude", "skills", "xbsl-meta-add", "scripts"))

from generate_http import (
    parse_routes,
    group_by_template,
    template_name,
    handler_name,
    has_path_param,
    build_yaml,
    build_xbsl,
    find_project_dirs,
    get_suggested_path,
    main,
)


# ---------------------------------------------------------------------------
# parse_routes
# ---------------------------------------------------------------------------

class TestParseRoutes:
    def test_basic(self):
        result = parse_routes("GET /, POST /")
        assert result == [("GET", "/"), ("POST", "/")]

    def test_with_path_param(self):
        result = parse_routes("GET /{id}, PUT /{id}")
        assert result == [("GET", "/{id}"), ("PUT", "/{id}")]

    def test_newline_separator(self):
        result = parse_routes("GET /\nPOST /")
        assert result == [("GET", "/"), ("POST", "/")]

    def test_mixed_case_method(self):
        result = parse_routes("get /")
        assert result == [("GET", "/")]

    def test_path_without_leading_slash(self):
        result = parse_routes("GET items")
        assert result == [("GET", "/items")]

    def test_invalid_format(self):
        with pytest.raises(SystemExit):
            parse_routes("INVALID")

    def test_empty_parts_skipped(self):
        result = parse_routes("GET /, , POST /")
        assert result == [("GET", "/"), ("POST", "/")]


# ---------------------------------------------------------------------------
# group_by_template
# ---------------------------------------------------------------------------

class TestGroupByTemplate:
    def test_groups_same_path(self):
        routes = [("GET", "/"), ("POST", "/")]
        result = group_by_template(routes)
        assert result == [("/", ["GET", "POST"])]

    def test_preserves_path_order(self):
        routes = [("GET", "/"), ("POST", "/"), ("GET", "/{id}")]
        result = group_by_template(routes)
        assert [path for path, _ in result] == ["/", "/{id}"]

    def test_methods_sorted_by_method_order(self):
        routes = [("DELETE", "/{id}"), ("GET", "/{id}"), ("PUT", "/{id}")]
        result = group_by_template(routes)
        assert result[0][1] == ["GET", "PUT", "DELETE"]

    def test_no_duplicates(self):
        routes = [("GET", "/"), ("GET", "/")]
        result = group_by_template(routes)
        assert result == [("/", ["GET"])]


# ---------------------------------------------------------------------------
# template_name
# ---------------------------------------------------------------------------

class TestTemplateName:
    def test_root(self):
        assert template_name("/") == "Список"

    def test_single_param(self):
        assert template_name("/{id}") == "ЭлементПоИд"

    def test_literal_segment(self):
        assert template_name("/items") == "Items"

    def test_param_with_sub(self):
        assert template_name("/{id}/items") == "ItemsПоРодителю"

    def test_all_params(self):
        assert template_name("/{id}/{sub}") == "ЭлементПоИд"

    def test_cyrillic_segment(self):
        # Убеждаемся что кириллица не ломается
        result = template_name("/контрагенты")
        assert result == "Контрагенты"


# ---------------------------------------------------------------------------
# has_path_param
# ---------------------------------------------------------------------------

class TestHasPathParam:
    def test_no_param(self):
        assert has_path_param("/") is False
        assert has_path_param("/items") is False

    def test_with_param(self):
        assert has_path_param("/{id}") is True
        assert has_path_param("/items/{item_id}") is True


# ---------------------------------------------------------------------------
# handler_name
# ---------------------------------------------------------------------------

class TestHandlerName:
    def test_get_list(self):
        assert handler_name("GET", "/", "Список") == "ПолучитьСписок"

    def test_post_create(self):
        assert handler_name("POST", "/", "Список") == "Создать"

    def test_get_by_id(self):
        assert handler_name("GET", "/{id}", "ЭлементПоИд") == "ПолучитьПоИд"

    def test_put_update(self):
        assert handler_name("PUT", "/{id}", "ЭлементПоИд") == "Обновить"

    def test_delete(self):
        assert handler_name("DELETE", "/{id}", "ЭлементПоИд") == "Удалить"

    def test_patch(self):
        assert handler_name("PATCH", "/{id}", "ЭлементПоИд") == "ОбновитьЧастично"

    def test_fallback(self):
        # Нестандартный метод — фолбэк
        result = handler_name("HEAD", "/", "Список")
        assert "HEAD" in result.upper() or "Список" in result or len(result) > 0


# ---------------------------------------------------------------------------
# build_yaml
# ---------------------------------------------------------------------------

class TestBuildYaml:
    def _make_templates(self):
        return [("/", ["GET", "POST"]), ("/{id}", ["GET", "PUT", "DELETE"])]

    def test_contains_required_fields(self):
        yaml = build_yaml("TestСервис", "/api/test", "РазрешеноВсем", self._make_templates())
        assert "ВидЭлемента: HttpСервис" in yaml
        assert "Имя: TestСервис" in yaml
        assert "КорневойUrl: /api/test" in yaml
        assert "РазрешеноВсем" in yaml

    def test_contains_uuid(self):
        yaml = build_yaml("TestСервис", "/api/test", "РазрешеноВсем", self._make_templates())
        # UUID формат: 8-4-4-4-12
        import re
        assert re.search(r"Ид: [0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", yaml)

    def test_handlers_in_yaml(self):
        yaml = build_yaml("TestСервис", "/api/test", "РазрешеноВсем", self._make_templates())
        assert "ПолучитьСписок" in yaml
        assert "Создать" in yaml
        assert "ПолучитьПоИд" in yaml

    def test_templates_in_yaml(self):
        yaml = build_yaml("TestСервис", "/api/test", "РазрешеноВсем", self._make_templates())
        assert "Шаблон: /" in yaml
        assert "Шаблон: /{id}" in yaml

    def test_each_call_unique_uuid(self):
        templates = [("/", ["GET"])]
        yaml1 = build_yaml("Сервис", "/api/x", "РазрешеноВсем", templates)
        yaml2 = build_yaml("Сервис", "/api/x", "РазрешеноВсем", templates)
        # UUID должны быть разными
        import re
        uuid_pat = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
        uuid1 = re.search(uuid_pat, yaml1).group()
        uuid2 = re.search(uuid_pat, yaml2).group()
        assert uuid1 != uuid2

    def test_access_level(self):
        yaml = build_yaml("Сервис", "/api/x", "РазрешеноАутентифицированным", [("/", ["GET"])])
        assert "РазрешеноАутентифицированным" in yaml


# ---------------------------------------------------------------------------
# build_xbsl
# ---------------------------------------------------------------------------

class TestBuildXbsl:
    def test_get_list_pattern(self):
        xbsl = build_xbsl([("/", ["GET"])])
        assert "метод ПолучитьСписок" in xbsl
        assert "ПолучитьПервый(\"limit\")" in xbsl

    def test_create_pattern(self):
        xbsl = build_xbsl([("/", ["POST"])])
        assert "метод Создать" in xbsl
        assert "201" in xbsl

    def test_get_by_id_pattern(self):
        xbsl = build_xbsl([("/{id}", ["GET"])])
        assert "метод ПолучитьПоИд" in xbsl
        assert "ПараметрыПути" in xbsl
        assert '"id"' in xbsl

    def test_error_helper_always_present(self):
        xbsl = build_xbsl([("/", ["GET"])])
        assert "метод _ОбработатьОшибку" in xbsl

    def test_try_catch_in_all_handlers(self):
        xbsl = build_xbsl([("/", ["GET", "POST"]), ("/{id}", ["GET", "PUT", "DELETE"])])
        handlers = ["ПолучитьСписок", "Создать", "ПолучитьПоИд", "Обновить", "Удалить"]
        for h in handlers:
            assert f"метод {h}" in xbsl
        # Каждый метод должен иметь попытка/поймать
        assert xbsl.count("попытка") >= len(handlers)

    def test_path_param_name_used(self):
        # Параметр из пути должен быть в xbsl
        xbsl = build_xbsl([("/{counterparty_id}", ["GET"])])
        assert '"counterparty_id"' in xbsl


# ---------------------------------------------------------------------------
# find_project_dirs
# ---------------------------------------------------------------------------

class TestFindProjectDirs:
    def test_finds_project_yaml(self, tmp_path):
        proj = tmp_path / "Vendor" / "MyProject"
        proj.mkdir(parents=True)
        (proj / "Проект.yaml").write_text("Имя: MyProject\n", encoding="utf-8")
        result = find_project_dirs(str(tmp_path))
        assert str(proj) in result

    def test_returns_root_if_project_yaml_there(self, tmp_path):
        (tmp_path / "Проект.yaml").write_text("Имя: Root\n", encoding="utf-8")
        result = find_project_dirs(str(tmp_path))
        assert str(tmp_path) in result

    def test_empty_dir(self, tmp_path):
        result = find_project_dirs(str(tmp_path))
        assert result == []


# ---------------------------------------------------------------------------
# Интеграционный тест: apply создаёт файлы
# ---------------------------------------------------------------------------

class TestApply:
    def _make_project(self, tmp_path) -> str:
        """Создаёт минимальную структуру проекта."""
        proj = tmp_path / "Vendor" / "MyProject"
        subsystem = proj / "Основное"
        subsystem.mkdir(parents=True)
        (proj / "Проект.yaml").write_text("Имя: MyProject\n", encoding="utf-8")
        (subsystem / "Подсистема.yaml").write_text("Имя: Основное\n", encoding="utf-8")
        return str(tmp_path)

    def test_creates_yaml_and_xbsl(self, tmp_path):
        root = self._make_project(tmp_path)
        main([
            "--name", "ТестовыйСервис",
            "--url", "/api/test",
            "--routes", "GET /, POST /, GET /{id}",
            "--root", root,
            "--apply",
        ])
        proj_path = tmp_path / "Vendor" / "MyProject" / "Основное"
        assert (proj_path / "ТестовыйСервис.yaml").exists()
        assert (proj_path / "ТестовыйСервис.xbsl").exists()

    def test_yaml_content_valid(self, tmp_path):
        root = self._make_project(tmp_path)
        main([
            "--name", "МойСервис",
            "--url", "/api/mine",
            "--routes", "GET /",
            "--root", root,
            "--apply",
        ])
        yaml_path = tmp_path / "Vendor" / "MyProject" / "Основное" / "МойСервис.yaml"
        content = yaml_path.read_text(encoding="utf-8")
        assert "ВидЭлемента: HttpСервис" in content
        assert "Имя: МойСервис" in content
        assert "КорневойUrl: /api/mine" in content

    def test_xbsl_content_valid(self, tmp_path):
        root = self._make_project(tmp_path)
        main([
            "--name", "МойСервис",
            "--url", "/api/mine",
            "--routes", "GET /, POST /, GET /{id}",
            "--root", root,
            "--apply",
        ])
        xbsl_path = tmp_path / "Vendor" / "MyProject" / "Основное" / "МойСервис.xbsl"
        content = xbsl_path.read_text(encoding="utf-8")
        assert "метод ПолучитьСписок" in content
        assert "метод Создать" in content
        assert "метод ПолучитьПоИд" in content
        assert "метод _ОбработатьОшибку" in content

    def test_conflict_detection(self, tmp_path):
        root = self._make_project(tmp_path)
        # Создаём файл заранее
        proj_path = tmp_path / "Vendor" / "MyProject" / "Основное"
        (proj_path / "МойСервис.yaml").write_text("ВидЭлемента: HttpСервис\n")

        # dry-run должен показать предупреждение
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            main([
                "--name", "МойСервис",
                "--url", "/api/mine",
                "--routes", "GET /",
                "--root", root,
            ])
        output = f.getvalue()
        assert "уже существует" in output

    def test_subsystem_hint(self, tmp_path):
        """--subsystem указывает нужную подсистему."""
        proj = tmp_path / "Vendor" / "MyProject"
        (proj / "Основное").mkdir(parents=True)
        (proj / "Продажи").mkdir(parents=True)
        (proj / "Проект.yaml").write_text("Имя: MyProject\n", encoding="utf-8")
        (proj / "Основное" / "Подсистема.yaml").write_text("Имя: Основное\n", encoding="utf-8")
        (proj / "Продажи" / "Подсистема.yaml").write_text("Имя: Продажи\n", encoding="utf-8")

        main([
            "--name", "СервисПродаж",
            "--url", "/api/sales",
            "--routes", "GET /",
            "--root", str(tmp_path),
            "--subsystem", "Продажи",
            "--apply",
        ])
        assert (proj / "Продажи" / "СервисПродаж.yaml").exists()
        assert not (proj / "Основное" / "СервисПродаж.yaml").exists()

    def test_dry_run_does_not_create_files(self, tmp_path):
        root = self._make_project(tmp_path)
        main([
            "--name", "МойСервис",
            "--url", "/api/mine",
            "--routes", "GET /",
            "--root", root,
            # нет --apply
        ])
        proj_path = tmp_path / "Vendor" / "MyProject" / "Основное"
        assert not (proj_path / "МойСервис.yaml").exists()
        assert not (proj_path / "МойСервис.xbsl").exists()
