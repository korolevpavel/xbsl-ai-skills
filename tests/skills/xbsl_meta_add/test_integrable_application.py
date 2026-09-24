from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

from .helpers import REFERENCE_SECTIONS, SKILL_ROOT, load_yaml, record_for, section_names


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).parent / 'fixtures/integrable-app'
VALIDATOR = ROOT / 'skills/xbsl-validate/scripts/validate.py'


def load_validator():
    spec = importlib.util.spec_from_file_location('integration_validator', VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_integrable_application_registry_and_reference() -> None:
    record = record_for('ИнтегрируемоеПриложение')
    assert record['status'] == 'supported'
    assert record['min_version'] == '10.0'
    assert record['reference_path'] == 'references/ИнтегрируемоеПриложение.md'
    reference = (SKILL_ROOT / record['reference_path']).read_text(encoding='utf-8')
    assert section_names(reference) == REFERENCE_SECTIONS
    assert 'НастройкиПрямогоПодключения' in reference


def test_one_initiator_pair_has_matching_plans_and_valid_links() -> None:
    validator = load_validator()
    sender = FIXTURE / 'sender'
    receiver = FIXTURE / 'receiver'
    app = load_yaml(sender / 'Обмен/ПриложениеСклад.yaml')
    sender_plan = load_yaml(sender / 'Обмен/УдаленныйСклад.yaml')
    receiver_plan = load_yaml(receiver / 'Обмен/УдаленныйСклад.yaml')

    assert app['ВидЭлемента'] == 'ИнтегрируемоеПриложение'
    assert sender_plan['ПередачаДанных']['ИнтегрируемыеПриложения'] == [
        {'Имя': app['Имя']},
    ]
    assert sender_plan['Имя'] == receiver_plan['Имя']
    assert sender_plan['Состав'] == receiver_plan['Состав']
    assert 'ПередачаДанных' not in receiver_plan
    assert validator.main(['--format', 'json', str(sender)]) == 0
    assert validator.main(['--format', 'json', str(receiver)]) == 0


@pytest.mark.parametrize(
    ('old', 'new', 'rule'),
    [
        ('Имя: ПриложениеСклад', 'Имя: НетТакого', 'owner.exchange_plan.connection'),
        ('Имя: ПриложениеСклад', 'Имя: Товары', 'owner.exchange_plan.connection_kind'),
        ('ИнтегрируемыеПриложения:\n    - Имя: ПриложениеСклад', 'ИнтегрируемыеПриложения: []', 'owner.exchange_plan.connections'),
        ('Использовать: Истина', 'Использовать: Ошибка', 'owner.exchange_plan.transfer'),
        ('Использовать: Истина', 'Использовать: Истина\n  ВидПакетаПередачиДанных: Ошибка', 'owner.exchange_plan.batch_kind'),
    ],
)
def test_invalid_plan_link_or_transfer_setting_reports_rule(
    tmp_path: Path, old: str, new: str, rule: str
) -> None:
    validator = load_validator()
    sender = tmp_path / 'sender'
    shutil.copytree(FIXTURE / 'sender', sender)
    path = sender / 'Обмен/УдаленныйСклад.yaml'
    path.write_text(path.read_text(encoding='utf-8').replace(old, new), encoding='utf-8')
    input_file = validator.InputFile(path, str(path))
    diagnostics = validator.validate_file(
        input_file, {'ПланОбмена': {'status': 'supported'}}, {}
    )
    assert rule in {diagnostic.rule_id for diagnostic in diagnostics}


def test_system_connection_settings_cannot_be_declared_in_project(tmp_path: Path) -> None:
    validator = load_validator()
    sender = tmp_path / 'sender'
    shutil.copytree(FIXTURE / 'sender', sender)
    path = sender / 'Обмен/ПриложениеСклад.yaml'
    with path.open('a', encoding='utf-8') as output:
        output.write('НастройкиПрямогоПодключения:\n  Адрес: https://example.test\n')
    input_file = validator.InputFile(path, str(path))
    diagnostics = validator.validate_file(
        input_file, {'ИнтегрируемоеПриложение': {'status': 'supported'}}, {}
    )
    assert 'owner.integrable_application.system_settings' in {
        diagnostic.rule_id for diagnostic in diagnostics
    }
