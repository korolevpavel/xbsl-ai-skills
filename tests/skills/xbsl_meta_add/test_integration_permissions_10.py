from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
VALIDATOR = ROOT / 'skills/xbsl-validate/scripts/validate.py'
PROCESS = Path(__file__).parent / 'fixtures/integration/positive/ПроцессИнтеграции/ОбменЗаказами.yaml'
REFERENCE = ROOT / 'skills/xbsl-meta-add/references/ПроцессИнтеграции.md'


def load_validator():
    spec = importlib.util.spec_from_file_location('integration_permissions_validator', VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_external_process_nodes_require_runtime_permission_check() -> None:
    validator = load_validator()
    input_file = validator.InputFile(PROCESS, str(PROCESS))
    diagnostics = validator.validate_file(
        input_file, {'ПроцессИнтеграции': {'status': 'supported'}}, {}
    )
    permission = [item for item in diagnostics
                  if item.rule_id == 'owner.integration_process.permissions_runtime']
    assert len(permission) == 1
    assert permission[0].severity == 'warning'
    assert 'ВОсновнуюБазу' in permission[0].message
    assert 'undelivered without retry' in permission[0].message


def test_permission_reference_distinguishes_local_and_remote_denial() -> None:
    text = REFERENCE.read_text(encoding='utf-8')
    for expected in (
        'ОшибкаПроверкиРазрешенийПроцессаИнтеграции',
        'Нет разрешения',
        'Доступ запрещен',
        'ФайлИсточник',
        'FtpИсточник',
        'RabbitMQ',
        'Kafka',
        'JMS',
    ):
        assert expected in text
