from pathlib import Path

import yaml


FIXTURE = Path(__file__).parent / 'fixtures/extension_10_0/acme/РасширениеБазыЗадач'


def test_extension_10_project_contract() -> None:
    project = yaml.safe_load((FIXTURE / 'Проект.yaml').read_text(encoding='utf-8'))
    subsystem = yaml.safe_load(
        (FIXTURE / 'Дополнения/Подсистема.yaml').read_text(encoding='utf-8')
    )

    assert project['ВидПроекта'] == 'Расширение'
    assert project['РежимСовместимости'] == 10.0
    assert project['РасширяемыеПроекты'] == [{
        'Поставщик': 'acme',
        'Имя': 'БазаЗадач',
        'Версии': {
            'От': {'Версия': 1.0},
            'До': {'Версия': 2.0, 'Включать': 'Ложь'},
        },
    }]
    assert subsystem['Интерфейс']['ВключатьВАвтоИнтерфейс'] == 'Истина'
