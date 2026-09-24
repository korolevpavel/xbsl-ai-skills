from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
PARAMETERIZED = Path(__file__).parent / "fixtures/report-10/ПродажиФормаОтчета.yaml"
REGRESSION = ROOT / "tests/skills/testapp_regressions/fixtures/Demo/RegressionApp/Контракты"


def test_report_forms_use_system_report_property_for_both_shapes():
    with_params = yaml.safe_load(PARAMETERIZED.read_text(encoding="utf-8"))
    without_params = yaml.safe_load((REGRESSION / "КонтрактныйОтчетФормаОтчета.yaml").read_text(encoding="utf-8"))
    report = yaml.safe_load((REGRESSION / "КонтрактныйОтчет.yaml").read_text(encoding="utf-8"))

    for form, report_name in ((with_params, "Продажи"), (without_params, "КонтрактныйОтчет")):
        inherited = form["Наследует"]
        assert inherited["Тип"] == f"ФормаОтчета<{report_name}>"
        assert inherited["Отчет"] == {"Тип": report_name}
        assert "Свойства" not in form
        assert "Заголовок" not in inherited

    children = with_params["Наследует"]["Содержимое"]["Содержимое"]["Содержимое"]
    assert children[0]["Значение"] == "=Отчет.Параметры.Период"
    assert children[1]["Тип"] == "ПросмотрОтчета<Продажи>"
    assert children[1]["Отчет"] == "=Отчет"
    assert without_params["Наследует"]["Содержимое"]["Содержимое"]["Тип"] == "ПросмотрОтчета<КонтрактныйОтчет>"
    assert report["Интерфейс"]["Форма"] == without_params["Имя"]


def test_parameterized_report_form_passes_yaml_validator():
    result = subprocess.run(
        [sys.executable, str(ROOT / "skills/xbsl-validate/scripts/validate.py"), str(PARAMETERIZED)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
