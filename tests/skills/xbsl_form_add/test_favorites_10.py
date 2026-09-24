from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures" / "favorites-10"


def test_favorites_are_configured_at_form_entity_and_application_levels():
    entity = yaml.safe_load((FIXTURES / "Товары.yaml").read_text(encoding="utf-8"))
    form = yaml.safe_load((FIXTURES / "ТоварыФормаСписка.yaml").read_text(encoding="utf-8"))
    application = yaml.safe_load((FIXTURES / "Приложение.yaml").read_text(encoding="utf-8"))

    assert entity["ВажностьИзбранногоПользователя"] == "Высокая"
    assert form["Наследует"]["ВажностьИзбранногоПользователя"] == "Отсутствует"
    assert application["Наследует"]["ВажностьИзбранногоПользователя"] == "Обычная"

    result = subprocess.run(
        [sys.executable, str(ROOT / "skills/xbsl-validate/scripts/validate.py"), str(FIXTURES)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_favorites_are_optional_and_version_gated_in_skill_guidance():
    form = (ROOT / "skills/xbsl-form-add/references/favorites-10.md").read_text(encoding="utf-8")
    entity = (ROOT / "skills/xbsl-meta-add/references/Избранное.md").read_text(encoding="utf-8")
    dashboard = (ROOT / "skills/xbsl-form-dashboard/references/регистрация.md").read_text(encoding="utf-8")

    for text in (form, entity, dashboard):
        assert "10.0+" in text
        assert "без аутентификации" in text
        assert "Отсутствует" in text
        assert "Обычная" in text
        assert "Высокая" in text
    assert "форма → сущность → клиентское приложение" in form
    assert "форма → клиентское приложение" in form
