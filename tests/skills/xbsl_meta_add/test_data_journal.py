from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path

import pytest

from .helpers import REFERENCE_SECTIONS, SKILL_ROOT, load_yaml, record_for, section_names


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).parent / 'fixtures/data-journal'
VALIDATOR = ROOT / 'skills/xbsl-validate/scripts/validate.py'


def load_validator():
    spec = importlib.util.spec_from_file_location('journal_validator', VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_data_journal_registry_and_reference() -> None:
    record = record_for('ЖурналДанных')
    assert record['status'] == 'supported'
    assert record['min_version'] == '10.0'
    assert record['reference_path'] == 'references/ЖурналДанных.md'
    assert [artifact['pattern'] for artifact in record['artifacts']] == ['*.yaml']
    reference = (SKILL_ROOT / record['reference_path']).read_text(encoding='utf-8')
    assert section_names(reference) == REFERENCE_SECTIONS
    assert 'КонтрольДоступа' in reference


def test_documented_query_examples_use_fields_for_each_composition() -> None:
    reference = (SKILL_ROOT / 'references/ЖурналДанных.md').read_text(encoding='utf-8')
    queries = re.findall(r'```xbql\n(.*?)\n```', reference, re.DOTALL)
    assert len(queries) == 3
    assert '.Дата' in queries[0] and '.Номер' in queries[0]
    assert '.Наименование' in queries[1] and '.Код' in queries[1]
    assert '.Тип' in queries[2] and '.КлючЗаписи' in queries[2]
    assert all(field not in queries[2] for field in ('.Дата', '.Номер', '.Наименование', '.Код'))


def test_mixed_journal_fixture_resolves_catalog_document_and_column() -> None:
    validator = load_validator()
    journal_path = FIXTURE / 'Основное/ОбщийЖурнал.yaml'
    data = load_yaml(journal_path)
    assert [item['Элемент'] for item in data['Состав']] == ['Контрагенты', 'Заказы']
    assert data['Колонки'][0]['Реквизиты'] == [
        'Контрагенты.Ответственный', 'Заказы.Ответственный',
    ]
    assert 'КонтрольДоступа' not in data
    assert validator.main(['--format', 'json', str(FIXTURE)]) == 0


@pytest.mark.parametrize(
    ('old', 'new', 'rule'),
    [
        ('Элемент: Заказы', 'Элемент: Неизвестный', 'owner.data_journal.source'),
        ('Контрагенты.Ответственный', 'Неизвестный.Ответственный', 'owner.data_journal.attribute_source'),
        ('Контрагенты.Ответственный', 'Контрагенты.Неизвестный', 'owner.data_journal.attribute_missing'),
        ('Ид: 10000000-0000-4000-8000-000000000007', 'Ид: bad', 'owner.data_journal.column_uuid'),
        ('Реквизиты:\n      - Контрагенты.Ответственный\n      - Заказы.Ответственный', 'Реквизиты: []', 'owner.data_journal.attributes'),
    ],
)
def test_journal_invalid_references_are_diagnostic(
    tmp_path: Path, old: str, new: str, rule: str
) -> None:
    validator = load_validator()
    project = tmp_path / 'project'
    shutil.copytree(FIXTURE, project)
    journal_path = project / 'Основное/ОбщийЖурнал.yaml'
    journal_path.write_text(
        journal_path.read_text(encoding='utf-8').replace(old, new), encoding='utf-8'
    )
    input_file = validator.InputFile(journal_path, str(journal_path))
    objects = {'ЖурналДанных': {'status': 'supported'}}
    diagnostics = validator.validate_file(input_file, objects, {})
    assert rule in {diagnostic.rule_id for diagnostic in diagnostics}


def test_journal_rejects_own_access(tmp_path: Path) -> None:
    validator = load_validator()
    project = tmp_path / 'project'
    shutil.copytree(FIXTURE, project)
    journal_path = project / 'Основное/ОбщийЖурнал.yaml'
    with journal_path.open('a', encoding='utf-8') as output:
        output.write('КонтрольДоступа:\n  Разрешения: {}\n')
    input_file = validator.InputFile(journal_path, str(journal_path))
    diagnostics = validator.validate_file(input_file, {'ЖурналДанных': {'status': 'supported'}}, {})
    assert 'owner.data_journal.access' in {diagnostic.rule_id for diagnostic in diagnostics}
