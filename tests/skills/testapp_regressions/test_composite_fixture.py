from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = Path(__file__).parent / "fixtures"
PROJECT_DIR = FIXTURE_ROOT / "Demo" / "RegressionApp"
VALIDATE_SCRIPT = ROOT_DIR / "skills/xbsl-validate/scripts/validate.py"
BUILD_SCRIPT = ROOT_DIR / "skills/xbsl-deploy/scripts/build.py"


def test_composite_fixture_is_tracked_and_validates_without_errors() -> None:
    assert "tools" not in PROJECT_DIR.parts

    result = subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT), str(PROJECT_DIR), "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert result.stderr == ""
    assert payload["summary"] == {"files": 9, "errors": 0, "warnings": 3}
    assert {diagnostic["severity"] for diagnostic in payload["diagnostics"]} == {
        "warning"
    }
    assert {diagnostic["rule_id"] for diagnostic in payload["diagnostics"]} == {
        "coverage.out_of_scope"
    }
    assert {
        (
            Path(diagnostic["path"]).relative_to(PROJECT_DIR).as_posix(),
            diagnostic["severity"],
            diagnostic["rule_id"],
        )
        for diagnostic in payload["diagnostics"]
    } == {
        ("Проект.yaml", "warning", "coverage.out_of_scope"),
        ("Контракты/Подсистема.yaml", "warning", "coverage.out_of_scope"),
        (
            "Контракты/КонтрактныйОтчетФормаОтчета.yaml",
            "warning",
            "coverage.out_of_scope",
        ),
    }


def test_composite_fixture_build_preserves_cross_cutting_contracts(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(BUILD_SCRIPT),
            "--project-dir",
            str(PROJECT_DIR),
            "--output",
            str(tmp_path),
            "--version",
            "1.0-1",
            "--branch",
            "test/121-testapp-regressions",
            "--commit",
            "regression-sha",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    archive_path = Path(result.stdout.strip())
    assert archive_path.is_file()

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        manifest = archive.read("Assembly.yaml").decode("utf-8")
        schedule = archive.read(
            "Demo/RegressionApp/Контракты/ЕжедневнаяПроверка.yaml"
        ).decode("utf-8")
        report = archive.read(
            "Demo/RegressionApp/Контракты/КонтрактныйОтчет.yaml"
        ).decode("utf-8")
        query = archive.read(
            "Demo/RegressionApp/Контракты/КонтрактныйОтчет.xbql"
        ).decode("utf-8")
        register = archive.read(
            "Demo/RegressionApp/Контракты/КонтрактныеДанные.yaml"
        ).decode("utf-8")
        lifecycle = archive.read(
            "Demo/RegressionApp/Контракты/РасчетныйДокумент.Объект.xbsl"
        ).decode("utf-8")
        document = archive.read(
            "Demo/RegressionApp/Контракты/РасчетныйДокумент.yaml"
        ).decode("utf-8")
        automatic_key = archive.read(
            "Demo/RegressionApp/Контракты/КонтрактныйАвтоматическийКлюч.yaml"
        ).decode("utf-8")
        manual_key = archive.read(
            "Demo/RegressionApp/Контракты/КонтрактныйРучнойКлюч.yaml"
        ).decode("utf-8")
        manual_api = archive.read(
            "Demo/RegressionApp/Контракты/КонтрактныйРучнойКлюч.xbsl"
        ).decode("utf-8")

    assert {
        "Demo/RegressionApp/Контракты/ЕжедневнаяПроверка.xbsl",
        "Demo/RegressionApp/Контракты/КонтрактныйОтчет.xbql",
        "Demo/RegressionApp/Контракты/КонтрактныйОтчетФормаОтчета.yaml",
        "Demo/RegressionApp/Контракты/РасчетныйДокумент.Объект.xbsl",
        "Demo/RegressionApp/Контракты/КонтрактныйАвтоматическийКлюч.xbsl",
        "Demo/RegressionApp/Контракты/КонтрактныйРучнойКлюч.xbsl",
    } <= names
    assert "Vendor: Demo" in manifest
    assert "Name: RegressionApp" in manifest
    assert "BranchName: test/121-testapp-regressions" in manifest
    assert "CommitId: regression-sha" in manifest
    assert "ЗапуститьВ: 08:00" in schedule
    assert 'ЗапуститьВ: "08:00"' not in schedule
    assert "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина" in report
    assert "    Форма: КонтрактныйОтчетФормаОтчета" in report
    assert "\nЗапрос:" not in report
    assert "ЗаменитьNull" in query
    assert "Тип: Строка|Число|?" in register
    assert "Имя: Дата\n        Тип: ДатаВремя" in document
    assert "Имя: Номер\n        Длина: 8" in document
    assert "Имя: Сумма" in document
    assert "Имя: Строки" in document
    assert "РучнаяВыдача: Ложь" in automatic_key
    assert "ОтключитьСистемныеПересчеты: Истина" in automatic_key
    assert "РучнаяВыдача: Истина" in manual_key
    assert "ПроверитьНаличиеКлючейДоступа" not in manual_api
    assert ".Выдать(" in manual_api
    assert ".Отозвать(" in manual_api
    assert ".ОтозватьКлючи(" in manual_api
    assert "ВыдатьКлючиДоступа(" in manual_api

    before_write_start = lifecycle.index("метод ПередЗаписью(")
    next_method_start = lifecycle.find("\nметод ", before_write_start + 1)
    before_write = lifecycle[
        before_write_start : next_method_start if next_method_start >= 0 else None
    ]
    assert "Строка.Сумма = Строка.Количество * Строка.Цена" in before_write
    assert "Сумма = СуммаДокумента" in before_write
